"""Git source adapter: commit history as change events, resumable by sha.

The adapter shells out to ``git log`` (no library dependency, works against any
bare or working repository). A commit's full sha *is* the revision, which makes
incremental fetches exact: the cursor stores one sha and the next fetch walks
``<sha>..HEAD``, so a resumed poll re-emits nothing already delivered and misses
nothing reachable from HEAD. Events are emitted oldest-first so consumers can
apply them in history order.

History rewrite caveat: if the cursor's sha is no longer present in the
repository (force-push, rebase), the adapter raises
:class:`GitCursorInvalid` instead of guessing — the caller decides whether to
re-pull from scratch.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from akc_source_adapters.envelope import (
    ChangeEvent,
    Cursor,
    FetchResult,
    utc_now,
)

PROVIDER = "git"

# Leading RS joins records unambiguously; US separates fields inside one record.
_LOG_FORMAT = "%x1e%H%x1f%aI%x1f%cI%x1f%an%x1f%ae%x1f%s"
_RECORD_SEPARATOR = "\x1e"
_FIELD_SEPARATOR = "\x1f"


class GitAdapterError(RuntimeError):
    """A git invocation failed; message carries git's stderr."""


class GitCursorInvalid(GitAdapterError):
    """A stored cursor names a revision this repository no longer contains."""


@dataclass(frozen=True)
class _CommitRecord:
    sha: str
    authored_at: str
    committed_at: str
    author_name: str
    author_email: str
    subject: str


class GitAdapter:
    """Emit one :class:`ChangeEvent` per commit on the current branch."""

    provider: str = PROVIDER

    def __init__(
        self,
        repo_path: Path | str,
        *,
        source_id: str | None = None,
        branch: str | None = None,
        git_executable: str = "git",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repo_path = Path(repo_path)
        resolved = self.repo_path.name or str(self.repo_path)
        self.source_id = source_id or f"git:{resolved}"
        self.branch = branch
        self.git_executable = git_executable
        self._clock: Callable[[], datetime] = clock or utc_now

    # -- public API ---------------------------------------------------------

    def discover(self) -> dict[str, object]:
        """Current head, branch and commit count without emitting events."""
        head = self._head_sha()
        return {
            "provider": PROVIDER,
            "source_id": self.source_id,
            "repo_path": str(self.repo_path),
            "branch": self._current_branch(),
            "head_commit": head,
            "commit_count": self._commit_count(),
        }

    def fetch_changes(self, cursor: Cursor | None) -> FetchResult:
        """Commits not covered by ``cursor``, oldest first, plus the next cursor."""
        self._assert_compatible(cursor)
        head = self._head_sha()
        previous_head = "" if cursor is None else str(cursor.state.get("head", ""))
        observed_at = self._clock()

        if head == "":
            return self._result((), previous_head, cursor)

        commits = self._log(self._range(previous_head))
        events = tuple(
            ChangeEvent(
                source_id=self.source_id,
                provider=PROVIDER,
                kind="commit",
                revision=record.sha,
                observed_at=observed_at,
                payload={
                    "author_email": record.author_email,
                    "author_name": record.author_name,
                    "authored_at": record.authored_at,
                    "committed_at": record.committed_at,
                    "ref": self.branch,
                    "subject": record.subject,
                },
            )
            for record in commits
        )
        new_head = commits[-1].sha if commits else previous_head
        return self._result(events, new_head, cursor)

    def checkpoint(self) -> Cursor:
        """Position at HEAD right now, without fetching."""
        return Cursor(provider=PROVIDER, source_id=self.source_id, state={"head": self._head_sha()})

    # -- internals ----------------------------------------------------------

    def _result(
        self,
        events: tuple[ChangeEvent, ...],
        new_head: str,
        cursor: Cursor | None,
    ) -> FetchResult:
        if cursor is not None:
            state = dict(cursor.state)
            state["head"] = new_head
            next_cursor = Cursor(provider=cursor.provider, source_id=cursor.source_id, state=state)
        else:
            next_cursor = Cursor(
                provider=PROVIDER, source_id=self.source_id, state={"head": new_head}
            )
        return FetchResult(events=events, cursor=next_cursor)

    def _range(self, previous_head: str) -> list[str]:
        tip = self.branch if self.branch is not None else "HEAD"
        if not previous_head:
            return [tip]
        if not self._commit_exists(previous_head):
            raise GitCursorInvalid(
                f"cursor head {previous_head!r} is not a commit in {self.repo_path}; "
                "the history was likely rewritten — re-run with no cursor for a full pull"
            )
        return [f"{previous_head}..{tip}"]

    def _log(self, revs: list[str]) -> list[_CommitRecord]:
        args = ["log", "--reverse", *revs, f"--format={_LOG_FORMAT}"]
        output = self._run(*args)
        records: list[_CommitRecord] = []
        for raw in output.split(_RECORD_SEPARATOR):
            line = raw.strip("\n")
            if not line.strip():
                continue
            parts = line.split(_FIELD_SEPARATOR)
            if len(parts) < 6:
                raise GitAdapterError(f"unexpected git log record shape: {line!r}")
            records.append(
                _CommitRecord(
                    sha=parts[0],
                    authored_at=parts[1],
                    committed_at=parts[2],
                    author_name=parts[3],
                    author_email=parts[4],
                    subject=_FIELD_SEPARATOR.join(parts[5:]),
                )
            )
        return records

    def _run(self, *args: str) -> str:
        completed = subprocess.run(  # noqa: S603 -- fixed executable; paths are operator-configured sources
            [self.git_executable, "-C", str(self.repo_path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            raise GitAdapterError(
                f"git {' '.join(args)} failed (exit {completed.returncode}): "
                f"{completed.stderr.strip()}"
            )
        return completed.stdout

    def _head_sha(self) -> str:
        try:
            return self._run("rev-parse", "--verify", "HEAD").strip()
        except GitAdapterError as exc:
            if self._is_missing_head(str(exc)):
                return ""
            raise

    def _commit_exists(self, sha: str) -> bool:
        try:
            self._run("cat-file", "-e", f"{sha}^{{commit}}")
        except GitAdapterError as exc:
            if self._is_missing_object(str(exc)):
                return False
            raise
        return True

    def _commit_count(self) -> int:
        if self._head_sha() == "":
            return 0
        return int(self._run("rev-list", "--count", "HEAD").strip())

    def _current_branch(self) -> str | None:
        try:
            name = self._run("rev-parse", "--abbrev-ref", "HEAD").strip()
        except GitAdapterError as exc:
            if self._is_missing_head(str(exc)):
                return None
            raise
        return None if name in ("", "HEAD") else name

    @staticmethod
    def _is_missing_head(message: str) -> bool:
        markers = ("ambiguous argument 'HEAD'", "unknown revision", "bad revision 'HEAD'")
        return any(marker in message for marker in markers)

    @staticmethod
    def _is_missing_object(message: str) -> bool:
        return "Not a valid object name" in message or "ambiguous argument" in message

    def _assert_compatible(self, cursor: Cursor | None) -> None:
        if cursor is None:
            return
        if cursor.provider != PROVIDER:
            raise ValueError(f"cursor provider {cursor.provider!r} does not match {PROVIDER!r}")
        if cursor.source_id != self.source_id:
            raise ValueError(
                f"cursor belongs to source {cursor.source_id!r}, adapter serves {self.source_id!r}"
            )
