"""Obsidian vault adapter: polling notes as change events, resumable by snapshot.

A vault has no push channel, so the adapter polls: every fetch hashes each
``*.md`` file (sha256 of content bytes) and records ``mtime_ns`` beside it.
Change detection is content-first — a touched-but-unchanged note emits nothing,
a same-mtime-different-content note still does. The cursor carries the whole
``path -> {sha256, mtime_ns, size}`` snapshot, so a resumed poll sees adds,
edits *and* deletions exactly once.

Titles follow Obsidian's conventions in order: a ``title`` key in YAML
frontmatter, else the first H1 heading, else the file stem.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from akc_source_adapters.envelope import ChangeEvent, Cursor, FetchResult, utc_now

PROVIDER = "obsidian"
NOTE_GLOB = "*.md"
_FRONTMATTER_FENCE = "---"
KIND_NOTE_ADDED = "note_added"
KIND_NOTE_CHANGED = "note_changed"
KIND_NOTE_DELETED = "note_deleted"


@dataclass(frozen=True, slots=True)
class NoteState:
    """What one poll knows about one note file."""

    path: str
    sha256: str
    mtime_ns: int
    size_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {"mtime_ns": self.mtime_ns, "sha256": self.sha256, "size_bytes": self.size_bytes}


def _iter_note_files(vault: Path) -> Iterator[Path]:
    yield from sorted(
        (p for p in vault.rglob(NOTE_GLOB) if p.is_file()),
        key=lambda p: p.relative_to(vault).as_posix(),
    )


class ObsidianVaultAdapter:
    """Emit one :class:`ChangeEvent` per added, edited or deleted note."""

    provider: str = PROVIDER

    def __init__(
        self,
        vault_path: Path | str,
        *,
        source_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.vault_path = Path(vault_path)
        if not self.vault_path.is_dir():
            raise NotADirectoryError(f"vault path is not a directory: {self.vault_path}")
        self.source_id = source_id or f"obsidian:{self.vault_path.name}"
        self._clock: Callable[[], datetime] = clock or utc_now

    # -- public API ---------------------------------------------------------

    def discover(self) -> dict[str, object]:
        """Vault shape without emitting events."""
        return {
            "provider": PROVIDER,
            "source_id": self.source_id,
            "vault_path": str(self.vault_path),
            "note_count": len(self.scan()),
        }

    def scan(self) -> dict[str, NoteState]:
        """Hash every note; paths are vault-relative posix strings, sorted."""
        states: dict[str, NoteState] = {}
        for path in _iter_note_files(self.vault_path):
            relative = path.relative_to(self.vault_path).as_posix()
            try:
                content = path.read_bytes()
                stat = path.stat()
            except OSError:
                # Vanished between listing and reading: absent for this poll.
                continue
            digest = hashlib.sha256(content).hexdigest()
            states[relative] = NoteState(
                path=relative, sha256=digest, mtime_ns=stat.st_mtime_ns, size_bytes=stat.st_size
            )
        return states

    def fetch_changes(self, cursor: Cursor | None) -> FetchResult:
        """Changes since ``cursor``'s snapshot (everything when ``cursor`` is None)."""
        self._assert_compatible(cursor)
        previous = self._previous_states(cursor)
        current = self.scan()
        observed_at = self._clock()

        events: list[ChangeEvent] = []
        for relative in sorted(current):
            state = current[relative]
            old = previous.get(relative)
            if old is not None and old.sha256 == state.sha256:
                continue  # untouched since last poll: no event, cursor still advances
            kind = KIND_NOTE_ADDED if old is None else KIND_NOTE_CHANGED
            title, frontmatter = self._describe(self.vault_path / relative)
            events.append(
                ChangeEvent(
                    source_id=self.source_id,
                    provider=PROVIDER,
                    kind=kind,
                    revision=f"sha256:{state.sha256}",
                    observed_at=observed_at,
                    payload={
                        "frontmatter": frontmatter,
                        "mtime_ns": state.mtime_ns,
                        "path": relative,
                        "previous_sha256": old.sha256 if old is not None else None,
                        "size_bytes": state.size_bytes,
                        "title": title,
                    },
                )
            )
        for relative in sorted(set(previous) - set(current)):
            gone = previous[relative]
            events.append(
                ChangeEvent(
                    source_id=self.source_id,
                    provider=PROVIDER,
                    kind=KIND_NOTE_DELETED,
                    revision=f"deleted:sha256:{gone.sha256}",
                    observed_at=observed_at,
                    payload={"path": relative, "previous_sha256": gone.sha256},
                )
            )

        next_state = {relative: state.as_dict() for relative, state in current.items()}
        next_cursor = self._cursor_for(cursor, {"notes": next_state})
        return FetchResult(events=tuple(events), cursor=next_cursor)

    def checkpoint(self) -> Cursor:
        """Snapshot of the vault right now, without emitting events."""
        snapshot = {relative: state.as_dict() for relative, state in self.scan().items()}
        return Cursor(provider=PROVIDER, source_id=self.source_id, state={"notes": snapshot})

    # -- internals ----------------------------------------------------------

    def _describe(self, path: Path) -> tuple[str, dict[str, object]]:
        """Title and frontmatter of one note; never raises on malformed input."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return path.stem, {}
        frontmatter = self._parse_frontmatter(text)
        raw_title = frontmatter.get("title")
        title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else ""
        if not title:
            for line in text.splitlines():
                if line.startswith("# ") and line[2:].strip():
                    title = line[2:].strip()
                    break
        return (title or path.stem), frontmatter

    @staticmethod
    def _parse_frontmatter(text: str) -> dict[str, object]:
        if not text.startswith(_FRONTMATTER_FENCE):
            return {}
        lines = text.splitlines()
        if not lines or lines[0].strip() != _FRONTMATTER_FENCE:
            return {}
        block: list[str] = []
        for line in lines[1:]:
            if line.strip() == _FRONTMATTER_FENCE:
                try:
                    loaded = yaml.safe_load("\n".join(block))
                except yaml.YAMLError:
                    return {}
                return dict(loaded) if isinstance(loaded, dict) else {}
            block.append(line)
        return {}  # unterminated fence: treat as no frontmatter

    def _previous_states(self, cursor: Cursor | None) -> dict[str, NoteState]:
        if cursor is None:
            return {}
        raw = cursor.state.get("notes", {})
        if not isinstance(raw, dict):
            raise ValueError("obsidian cursor state is missing its 'notes' snapshot")
        states: dict[str, NoteState] = {}
        for relative, entry in raw.items():
            if not isinstance(entry, dict):
                raise ValueError(f"obsidian cursor entry for {relative!r} is malformed")
            states[str(relative)] = NoteState(
                path=str(relative),
                sha256=str(entry.get("sha256", "")),
                mtime_ns=int(entry.get("mtime_ns", 0)),
                size_bytes=int(entry.get("size_bytes", 0)),
            )
        return states

    def _cursor_for(self, cursor: Cursor | None, state: dict[str, object]) -> Cursor:
        if cursor is not None:
            return Cursor(provider=cursor.provider, source_id=cursor.source_id, state=state)
        return Cursor(provider=PROVIDER, source_id=self.source_id, state=state)

    def _assert_compatible(self, cursor: Cursor | None) -> None:
        if cursor is None:
            return
        if cursor.provider != PROVIDER:
            raise ValueError(f"cursor provider {cursor.provider!r} does not match {PROVIDER!r}")
        if cursor.source_id != self.source_id:
            raise ValueError(
                f"cursor belongs to source {cursor.source_id!r}, adapter serves {self.source_id!r}"
            )
