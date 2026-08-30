"""Mounted file-server adapter with content-addressed, resumable polling.

SMB, NFS, SFTP mounts and cloud-sync folders are intentionally treated as a
filesystem boundary. Authentication and mounting stay with the operating
system; this adapter never receives or persists a file-server password.
"""

from __future__ import annotations

import fnmatch
import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from akc_source_adapters.envelope import ChangeEvent, Cursor, FetchResult

PROVIDER = "file_server"
FRESHNESS_TIER = "F1"
DEFAULT_EXCLUDES = (
    ".git/**",
    ".svn/**",
    ".DS_Store",
    "Thumbs.db",
    "~$*",
    "*.tmp",
)


class FileServerAdapterError(RuntimeError):
    """A mounted source cannot be scanned without weakening its limits."""


class FileServerAdapter:
    """Poll one mounted directory and emit content-hash change envelopes."""

    provider = PROVIDER

    def __init__(
        self,
        root: str | Path,
        *,
        source_name: str | None = None,
        exclude_globs: Sequence[str] = DEFAULT_EXCLUDES,
        max_files: int = 100_000,
        max_file_bytes: int = 512 * 1024 * 1024,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(self.root)
        if max_files < 1 or max_file_bytes < 1:
            raise ValueError("file-server limits must be positive")
        self.source_id = f"{PROVIDER}:{source_name or self.root.name}"
        self.exclude_globs = tuple(str(pattern) for pattern in exclude_globs)
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self._clock = clock or (lambda: datetime.now(UTC))

    def discover(self) -> Mapping[str, object]:
        snapshot, skipped_symlinks = self._snapshot()
        return {
            "provider": PROVIDER,
            "source_id": self.source_id,
            "freshness_tier": FRESHNESS_TIER,
            "files": len(snapshot),
            "skipped_symlinks": skipped_symlinks,
            "permission_snapshot": {
                "read_only": True,
                "credentials_managed_by": "operating_system_mount",
            },
        }

    def fetch_changes(self, cursor: Cursor | None) -> FetchResult:
        self._assert_compatible(cursor)
        previous = _cursor_files(cursor)
        current, _ = self._snapshot()
        observed_at = self._clock()
        events: list[ChangeEvent] = []

        for path in sorted(current):
            state = current[path]
            prior = previous.get(path)
            if prior == state:
                continue
            kind = "file_changed" if prior is not None else "file_added"
            events.append(
                ChangeEvent(
                    source_id=self.source_id,
                    provider=PROVIDER,
                    kind=kind,
                    revision=f"sha256:{state['sha256']}",
                    observed_at=observed_at,
                    payload={
                        "path": path,
                        "size": state["size"],
                        "mtime_ns": state["mtime_ns"],
                        "sha256": state["sha256"],
                        "previous_sha256": prior.get("sha256") if prior else None,
                    },
                )
            )

        for path in sorted(set(previous) - set(current)):
            prior = previous[path]
            events.append(
                ChangeEvent(
                    source_id=self.source_id,
                    provider=PROVIDER,
                    kind="file_deleted",
                    revision=f"sha256:{prior['sha256']}",
                    observed_at=observed_at,
                    payload={
                        "path": path,
                        "previous_sha256": prior["sha256"],
                        "previous_size": prior["size"],
                    },
                )
            )

        return FetchResult(
            events=tuple(events),
            cursor=Cursor(
                provider=PROVIDER,
                source_id=self.source_id,
                state={"files": current, "last_polled_at": observed_at.isoformat()},
            ),
        )

    def checkpoint(self) -> Cursor:
        snapshot, _ = self._snapshot()
        return Cursor(provider=PROVIDER, source_id=self.source_id, state={"files": snapshot})

    def _snapshot(self) -> tuple[dict[str, dict[str, object]], int]:
        snapshot: dict[str, dict[str, object]] = {}
        skipped_symlinks = 0
        for candidate in sorted(self.root.rglob("*"), key=lambda item: item.as_posix()):
            relative = candidate.relative_to(self.root).as_posix()
            if candidate.is_symlink():
                skipped_symlinks += 1
                continue
            if not candidate.is_file() or _excluded(relative, self.exclude_globs):
                continue
            if len(snapshot) >= self.max_files:
                raise FileServerAdapterError(
                    f"source exceeds max_files={self.max_files}; narrow the mounted root"
                )
            snapshot[relative] = self._stable_file_state(candidate)
        return snapshot, skipped_symlinks

    def _stable_file_state(self, path: Path) -> dict[str, object]:
        for attempt in range(2):
            before = path.stat()
            if before.st_size > self.max_file_bytes:
                raise FileServerAdapterError(
                    f"{path.name!r} exceeds max_file_bytes={self.max_file_bytes}"
                )
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
                return {
                    "sha256": digest.hexdigest(),
                    "size": after.st_size,
                    "mtime_ns": after.st_mtime_ns,
                }
            if attempt == 1:
                break
        raise FileServerAdapterError(f"{path.name!r} changed while it was being scanned")

    def _assert_compatible(self, cursor: Cursor | None) -> None:
        if cursor is None:
            return
        if cursor.provider != PROVIDER:
            raise ValueError(f"cursor provider {cursor.provider!r} does not match {PROVIDER!r}")
        if cursor.source_id != self.source_id:
            raise ValueError(
                f"cursor belongs to source {cursor.source_id!r}, adapter serves {self.source_id!r}"
            )


def _cursor_files(cursor: Cursor | None) -> dict[str, dict[str, object]]:
    raw = cursor.state.get("files", {}) if cursor is not None else {}
    if not isinstance(raw, Mapping):
        raise ValueError("file-server cursor files must be an object")
    files: dict[str, dict[str, object]] = {}
    for path, state in raw.items():
        if not isinstance(path, str) or not isinstance(state, Mapping):
            raise ValueError("file-server cursor contains an invalid file state")
        sha256 = state.get("sha256")
        size = state.get("size")
        mtime_ns = state.get("mtime_ns")
        if (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or not isinstance(size, int)
            or not isinstance(mtime_ns, int)
        ):
            raise ValueError("file-server cursor contains an invalid file state")
        files[path] = {"sha256": sha256, "size": size, "mtime_ns": mtime_ns}
    return files


def _excluded(path: str, patterns: Sequence[str]) -> bool:
    return any(
        fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(Path(path).name, pattern)
        for pattern in patterns
    )
