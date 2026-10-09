"""GitHub source adapter: commit history over the REST API, resumable by sha.

Where :class:`~akc_source_adapters.git_adapter.GitAdapter` shells out to a local
clone, this adapter speaks the GitHub REST API with :mod:`urllib` only, so a
scheduler can watch repositories it never checks out. The commit's full sha is
the revision and the cursor stores the newest sha plus each file's latest
commit, which makes incremental fetches exact: every poll lists commits newer
than the anchor, slices off everything already delivered, and re-emits nothing.
The same cursor handed to ``fetch_changes`` twice yields the same events —
polling is a pure function of upstream state plus the cursor.

Deletions are explicit. A commit that removes files emits its own ``commit``
event *and* one ``file_deleted`` tombstone per removed path, because a consumer
that only follows ``commit`` events would keep a dead document alive forever.
The cursor's per-file map drops tombstoned paths so the next poll cannot
resurrect them.

Two failure modes are handled loudly rather than silently:

* **Broken history.** If the cursor's anchor sha no longer appears anywhere in
  the repository's history window (force-push, rebase), ``fetch_changes`` raises
  :class:`GitHubCursorInvalid`; the caller decides whether to re-pull from
  scratch — mirroring :class:`~akc_source_adapters.git_adapter.GitAdapter`.
* **Rate limits.** Every response's ``X-RateLimit-Remaining`` /
  ``X-RateLimit-Reset`` headers are honored: once remaining calls drop below the
  margin the adapter sleeps until the reset before its next request, and a
  secondary limit (403/429 with ``Retry-After``) buys exactly one patient retry
  instead of failing the poll.

Both ``api_base`` and the token provider are constructor-injected, so tests run
against a local stub server with no network and no credentials.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from akc_source_adapters.envelope import ChangeEvent, Cursor, FetchResult, utc_now

PROVIDER = "github"
KIND_COMMIT = "commit"
KIND_FILE_DELETED = "file_deleted"

DEFAULT_API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"
PER_PAGE = 100
MAX_PAGES = 50  # safety cap: MAX_PAGES * PER_PAGE commits examined per pull
RATE_LIMIT_MARGIN = 10  # sleep until reset once fewer than this many calls remain
RATE_LIMIT_MAX_WAIT_SECONDS = 3600.0
REQUEST_TIMEOUT_SECONDS = 30.0
_SINCE_BACKSTEP = timedelta(seconds=1)  # widens `since=` so the anchor stays in the window


class GitHubAdapterError(RuntimeError):
    """A GitHub REST call failed; the message carries status and endpoint."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GitHubCursorInvalid(GitHubAdapterError):
    """A stored cursor names a commit this repository no longer exposes."""


@dataclass(frozen=True, slots=True)
class _CommitSummary:
    sha: str
    committed_at: str
    author_name: str
    author_email: str
    message: str


class GitHubAdapter:
    """Emit one :class:`ChangeEvent` per commit, plus deletion tombstones."""

    provider: str = PROVIDER

    def __init__(
        self,
        repo: str,
        *,
        token_provider: Callable[[], str | None] | None = None,
        source_id: str | None = None,
        branch: str | None = None,
        api_base: str = DEFAULT_API_BASE,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], object] = time.sleep,
        rate_limit_margin: int = RATE_LIMIT_MARGIN,
        max_pages: int = MAX_PAGES,
    ) -> None:
        owner, _, name = repo.partition("/")
        if not owner or not name or "/" in name:
            raise ValueError(f"repo must look like 'owner/name', got {repo!r}")
        self.repo = f"{owner}/{name}"
        self.token_provider = token_provider
        self.source_id = source_id or f"github:{self.repo}"
        self.branch = branch
        self.api_base = api_base.rstrip("/")
        self._clock: Callable[[], datetime] = clock or utc_now
        self._sleep: Callable[[float], object] = sleep
        self.rate_limit_margin = rate_limit_margin
        self.max_pages = max_pages

    # -- public API ---------------------------------------------------------

    def discover(self) -> dict[str, object]:
        """Repository shape plus a visibility / branch-protection snapshot."""
        payload = self._request_json(f"/repos/{self.repo}", {})
        default_branch = str(payload.get("default_branch") or "")
        branch = self.branch or default_branch
        private = bool(payload.get("private", False))
        visibility = str(payload.get("visibility") or ("private" if private else "public"))
        snapshot: dict[str, object] = {
            "branch": branch,
            "branch_protected": self._branch_is_protected(branch),
            "visibility": visibility,
        }
        info: dict[str, object] = {
            "provider": PROVIDER,
            "source_id": self.source_id,
            "repo": self.repo,
            "default_branch": default_branch,
            **snapshot,
            "permission_snapshot": snapshot,
        }
        permissions = payload.get("permissions")
        if isinstance(permissions, Mapping):
            info["caller_permissions"] = {
                str(key): bool(value) for key, value in permissions.items()
            }
        return info

    def fetch_changes(self, cursor: Cursor | None) -> FetchResult:
        """Commits not covered by ``cursor``, oldest first, plus the next cursor."""
        self._assert_compatible(cursor)
        state = dict(cursor.state) if cursor is not None else {}
        previous_sha = str(state.get("last_sha", ""))
        observed_at = self._clock()

        collected, exhausted = self._list_commits(since_iso=self._since_iso(state))
        if not previous_sha:
            new_commits, caught_up = collected, True  # initial full pull
        elif _index_of_sha(collected, previous_sha) >= 0:
            new_commits, caught_up = collected[: _index_of_sha(collected, previous_sha)], True
        elif collected and exhausted:
            raise GitHubCursorInvalid(
                f"cursor sha {previous_sha!r} is not in {_ref(self.repo, self.branch)} "
                "history; it was likely force-pushed away — "
                "re-run with no cursor for a full pull"
            )
        else:
            # The page cap cut the walk short before the anchor surfaced; take
            # the window now and resume from its oldest commit instead of guessing.
            new_commits, caught_up = collected, False
        collected = list(collected)  # newest-first snapshot for the anchor below
        new_commits.reverse()  # oldest first so consumers apply history order

        events: list[ChangeEvent] = []
        stored_files = state.get("files") or {}
        if not isinstance(stored_files, Mapping):
            raise ValueError("GitHub cursor files must be a mapping")
        files: dict[str, str] = {str(path): str(sha) for path, sha in stored_files.items()}
        for summary in new_commits:
            detail = self._request_json(f"/repos/{self.repo}/commits/{summary.sha}", {})
            added, modified, removed = _split_files(detail.get("files"))
            events.append(
                ChangeEvent(
                    source_id=self.source_id,
                    provider=PROVIDER,
                    kind=KIND_COMMIT,
                    revision=summary.sha,
                    observed_at=observed_at,
                    payload={
                        "author_email": summary.author_email,
                        "author_name": summary.author_name,
                        "committed_at": summary.committed_at,
                        "files_added": list(added),
                        "files_modified": list(modified),
                        "files_removed": list(removed),
                        "message": summary.message,
                        "ref": self.branch,
                        "sha": summary.sha,
                    },
                )
            )
            for path in removed:
                events.append(
                    ChangeEvent(
                        source_id=self.source_id,
                        provider=PROVIDER,
                        kind=KIND_FILE_DELETED,
                        revision=summary.sha,
                        observed_at=observed_at,
                        payload={"path": path, "sha": summary.sha},
                    )
                )
                files.pop(path, None)  # tombstoned paths never come back via the map
            for path in sorted((*added, *modified)):
                files[path] = summary.sha

        next_state = _next_state(state, collected, new_commits, files, caught_up)
        next_cursor = (
            Cursor(provider=cursor.provider, source_id=cursor.source_id, state=next_state)
            if cursor is not None
            else Cursor(provider=PROVIDER, source_id=self.source_id, state=next_state)
        )
        return FetchResult(events=tuple(events), cursor=next_cursor)

    def checkpoint(self) -> Cursor:
        """Position at the current head right now, without emitting events."""
        params: dict[str, str | int] = {"per_page": 1}
        if self.branch is not None:
            params["sha"] = self.branch
        payload = self._request_json(f"/repos/{self.repo}/commits", params)
        commits = [_parse_summary(item) for item in payload] if isinstance(payload, list) else []
        head = commits[-1] if commits else None
        return Cursor(
            provider=PROVIDER,
            source_id=self.source_id,
            state={
                "branch": self.branch,
                "last_committed_at": head.committed_at if head else None,
                "last_sha": head.sha if head else "",
                "files": {},
            },
        )

    # -- internals ----------------------------------------------------------

    def _branch_is_protected(self, branch: str) -> bool:
        try:
            self._request_json(f"/repos/{self.repo}/branches/{branch}/protection", {})
        except GitHubAdapterError as exc:
            if exc.status == 404:
                return False  # unprotected branch, or caller cannot see protection
            raise
        return True

    def _list_commits(self, *, since_iso: str | None) -> tuple[list[_CommitSummary], bool]:
        """Commits newest-first; ``(window, walk_reached_history_end)``."""
        summaries: list[_CommitSummary] = []
        params: dict[str, str | int] = {"per_page": PER_PAGE}
        if self.branch is not None:
            params["sha"] = self.branch
        if since_iso:
            params["since"] = since_iso
        for _ in range(self.max_pages):
            payload = self._request_json(f"/repos/{self.repo}/commits", params)
            batch = payload if isinstance(payload, list) else []
            summaries.extend(_parse_summary(item) for item in batch)
            if len(batch) < PER_PAGE:
                return summaries, True
            params["page"] = int(params.get("page", 1)) + 1
        return summaries, False

    def _since_iso(self, state: dict[str, Any]) -> str | None:
        raw = state.get("last_committed_at")
        if not isinstance(raw, str) or not raw:
            return None
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None  # unparsable anchor date: widen to a fuller listing instead
        return (moment.astimezone(UTC) - _SINCE_BACKSTEP).isoformat().replace("+00:00", "Z")

    def _request_json(self, path: str, params: Mapping[str, str | int]) -> Any:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{self.api_base}{path}{'?' + query if query else ''}"
        for attempt in (1, 2):
            request = urllib.request.Request(url, method="GET")  # noqa: S310 -- api_base is operator-configured
            request.add_header("Accept", "application/vnd.github+json")
            request.add_header("User-Agent", f"akc-source-adapters/{PROVIDER}")
            request.add_header("X-GitHub-Api-Version", API_VERSION)
            token = self.token_provider() if self.token_provider is not None else None
            if token:
                request.add_header("Authorization", f"Bearer {token}")
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 -- same operator-configured base
                    body = response.read()
                    self._respect_rate_limit(dict(response.headers))
                    return json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                headers = dict(exc.headers or {})
                retry_after = headers.get("Retry-After")
                rate_limited = exc.code in (403, 429) and (
                    retry_after is not None or headers.get("X-RateLimit-Remaining") == "0"
                )
                if attempt == 1 and rate_limited and retry_after is not None:
                    self._sleep(min(float(retry_after), RATE_LIMIT_MAX_WAIT_SECONDS))
                    continue  # secondary rate limit: one patient retry, then give up
                raise GitHubAdapterError(
                    f"GET {path} failed (HTTP {exc.code}): {_body_hint(exc.read())}",
                    status=exc.code,
                ) from exc
            except urllib.error.URLError as exc:
                raise GitHubAdapterError(f"GET {path} failed: {exc.reason}") from exc
        raise GitHubAdapterError(f"GET {path} failed: retries exhausted")  # pragma: no cover

    def _respect_rate_limit(self, headers: Mapping[str, str]) -> None:
        remaining = headers.get("X-RateLimit-Remaining")
        reset_raw = headers.get("X-RateLimit-Reset")
        if remaining is None or not remaining.isdigit():
            return
        if int(remaining) >= self.rate_limit_margin:
            return
        wait = 1.0  # floor so a missing/unparsable reset still pauses before retrying
        if reset_raw is not None and reset_raw.isdigit():
            wait = max(int(reset_raw) - int(self._clock().timestamp()), 0) + 1.0
        self._sleep(min(wait, RATE_LIMIT_MAX_WAIT_SECONDS))

    def _assert_compatible(self, cursor: Cursor | None) -> None:
        if cursor is None:
            return
        if cursor.provider != PROVIDER:
            raise ValueError(f"cursor provider {cursor.provider!r} does not match {PROVIDER!r}")
        if cursor.source_id != self.source_id:
            raise ValueError(
                f"cursor belongs to source {cursor.source_id!r}, adapter serves {self.source_id!r}"
            )


# -- module-level helpers ----------------------------------------------------


def _ref(repo: str, branch: str | None) -> str:
    return f"{repo}@{branch}" if branch else repo


def _index_of_sha(commits: list[_CommitSummary], sha: str) -> int:
    for index, summary in enumerate(commits):
        if summary.sha == sha:
            return index
    return -1


def _parse_summary(item: Any) -> _CommitSummary:
    if not isinstance(item, Mapping):
        raise GitHubAdapterError("commit list entry is not an object")
    inner = item.get("commit")
    if not isinstance(inner, Mapping):
        raise GitHubAdapterError("commit list entry is missing its 'commit' object")
    committer = inner.get("committer")
    author = inner.get("author")
    message = str(inner.get("message") or "")
    return _CommitSummary(
        sha=str(item.get("sha") or ""),
        committed_at=str(committer.get("date") or "") if isinstance(committer, Mapping) else "",
        author_name=str(author.get("name") or "") if isinstance(author, Mapping) else "",
        author_email=str(author.get("email") or "") if isinstance(author, Mapping) else "",
        message=message.splitlines()[0] if message else "",
    )


def _split_files(raw: Any) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Sorted (added, modified, removed) paths of one commit detail."""
    if not isinstance(raw, list):
        return (), (), ()
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("filename") or "")
        status = str(item.get("status") or "")
        if status == "added":
            added.append(path)
        elif status == "removed":
            removed.append(path)
        else:
            modified.append(path)
    return tuple(sorted(added)), tuple(sorted(modified)), tuple(sorted(removed))


def _body_hint(raw: bytes | str, limit: int = 120) -> str:
    """Short human-readable hint from an error body, without dumping it all."""
    try:
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    except Exception:  # pragma: no cover - decode with replace cannot raise
        return ""
    return " ".join(text.split())[:limit]


def _next_state(
    state: dict[str, Any],
    collected: list[_CommitSummary],
    emitted: list[_CommitSummary],
    files: dict[str, str],
    caught_up: bool,
) -> dict[str, Any]:
    """Anchor choice: newest seen when fully caught up, oldest emitted when capped."""
    anchor = collected[0] if (emitted and caught_up) else None
    if emitted and not caught_up:
        anchor = emitted[0]
    if anchor is not None:
        return {
            "branch": state.get("branch"),
            "last_committed_at": anchor.committed_at,
            "last_sha": anchor.sha,
            "files": dict(sorted(files.items())),
        }
    return {  # nothing new: hand the caller their own position back, untouched
        "branch": state.get("branch"),
        "last_committed_at": state.get("last_committed_at"),
        "last_sha": state.get("last_sha", ""),
        "files": dict(sorted(files.items())),
    }
