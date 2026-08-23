"""Contract tests for :class:`GitHubAdapter` against a local stub API.

No network, no tokens: a ``ThreadingHTTPServer`` on localhost answers the few
REST routes the adapter calls, with realistic shapes (pagination via ``page``/
``per_page``, rate-limit headers on every response, ``Retry-After`` on secondary
limits). What gets pinned here mirrors ``test_source_adapters.py``: a full pull
followed by an empty incremental pull, resume through an encoded cursor string,
deletion tombstones, the rate-limit wait path, and byte-stable replays of the
same cursor.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from akc_source_adapters.github_adapter import (
    KIND_FILE_DELETED,
    GitHubAdapter,
    GitHubCursorInvalid,
)
from akc_source_adapters.envelope import Cursor, SourceAdapter

FIXED_NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
OWNER = "octo"
REPO = "docs"
SHA_1 = "a" * 40
SHA_2 = "b" * 40
SHA_3 = "c" * 40
SHA_4 = "d" * 40


def _iso(minute: int) -> str:
    return f"2026-08-01T00:{minute:02d}:00Z"


def _summary(sha: str, minute: int, message: str) -> dict[str, Any]:
    return {
        "sha": sha,
        "commit": {
            "author": {"name": "Ada Lovelace", "email": "ada@example.com"},
            "committer": {"name": "Ada Lovelace", "email": "ada@example.com", "date": _iso(minute)},
            "message": message,
        },
    }


def _files(*entries: tuple[str, str]) -> list[dict[str, str]]:
    return [{"filename": name, "status": status} for name, status in entries]


# -- stub server ---------------------------------------------------------------


@dataclass
class StubState:
    repo: dict[str, Any]
    protection_status: int = 200
    commits: list[dict[str, Any]] = field(default_factory=list)  # newest-first
    details: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    remaining: int = 480
    reset_in_seconds: int = 60
    fail_first_commits_with_retry_after: int | None = None
    requests: list[dict[str, str]] = field(default_factory=list)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        pass

    @property
    def state(self) -> StubState:
        stub_state: StubState = self.server.state  # type: ignore[attr-defined]
        return stub_state

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        parsed = urlparse(self.path)
        parts = [segment for segment in parsed.path.split("/") if segment]
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        state = self.state
        state.requests.append({"path": self.path, "authorization": self.headers.get("Authorization", "")})

        # Routes: /repos/o/r, /repos/o/r/branches/<b>/protection,
        #         /repos/o/r/commits, /repos/o/r/commits/<sha>
        if parts == ["repos", OWNER, REPO]:
            self._send_json(200, state.repo)
        elif (
            len(parts) == 6
            and parts[:4] == ["repos", OWNER, REPO, "branches"]
            and parts[5] == "protection"
        ):
            self._send_json(state.protection_status, {})
        elif parts == ["repos", OWNER, REPO, "commits"]:
            if state.fail_first_commits_with_retry_after is not None:
                pause = state.fail_first_commits_with_retry_after
                state.fail_first_commits_with_retry_after = None
                self._send_json(403, {"message": "secondary rate limit"}, retry_after=pause)
                return
            batch = self._commit_page(params)
            self._send_json(200, batch)
        elif len(parts) == 5 and parts[:4] == ["repos", OWNER, REPO, "commits"]:
            sha = parts[4]
            if sha not in state.details:
                self._send_json(404, {"message": "not found"})
                return
            merged = dict(_detail_shell(sha))
            merged["files"] = state.details[sha]
            self._send_json(200, merged)
        else:
            self._send_json(404, {"message": "not found"})

    def _commit_page(self, params: dict[str, str]) -> list[dict[str, Any]]:
        per_page = int(params.get("per_page", "30"))
        page = int(params.get("page", "1"))
        since = params.get("since")
        window = self.state.commits
        if since:
            window = [item for item in window if item["commit"]["committer"]["date"] >= since]
        start = (page - 1) * per_page
        return window[start : start + per_page]

    def _send_json(
        self, status: int, payload: dict[str, Any] | list[dict[str, Any]], *, retry_after: int | None = None
    ) -> None:
        state = self.state
        state.remaining = max(state.remaining - 1, 0)
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-RateLimit-Limit", "5000")
        self.send_header("X-RateLimit-Remaining", str(state.remaining))
        reset_epoch = int(FIXED_NOW.timestamp()) + state.reset_in_seconds
        self.send_header("X-RateLimit-Reset", str(reset_epoch))
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        self.wfile.write(body)


def _detail_shell(sha: str) -> dict[str, Any]:
    return {"sha": sha, "commit": {"message": "detail"}}


@contextmanager
def stub_github(state: StubState) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def make_state() -> StubState:
    """Three commits: adds docs/a.md, edits docs/a.md, edits README.md."""
    state = StubState(
        repo={
            "full_name": f"{OWNER}/{REPO}",
            "private": True,
            "visibility": "private",
            "default_branch": "main",
            "permissions": {"admin": False, "push": True, "pull": True},
        },
        commits=[_summary(SHA_3, 3, "third"), _summary(SHA_2, 2, "second"), _summary(SHA_1, 1, "first")],
        details={
            SHA_1: _files(("docs/a.md", "added"), ("README.md", "added")),
            SHA_2: _files(("docs/a.md", "modified"),),
            SHA_3: _files(("README.md", "modified"),),
        },
    )
    return state


class SleepRecorder:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def make_adapter(
    base_url: str, sleeps: SleepRecorder | None = None, **overrides: Any
) -> GitHubAdapter:
    options: dict[str, Any] = {
        "api_base": base_url,
        "clock": lambda: FIXED_NOW,
        "source_id": "github:octo/docs",
    }
    if sleeps is not None:
        options["sleep"] = sleeps
    options.update(overrides)
    return GitHubAdapter(f"{OWNER}/{REPO}", **options)


# -- protocol shape -------------------------------------------------------------


def test_github_adapter_satisfies_the_protocol() -> None:
    with stub_github(make_state()) as base:
        adapter = make_adapter(base)
        assert isinstance(adapter, SourceAdapter)
        assert adapter.provider == "github"


def test_discover_snapshots_visibility_and_branch_protection() -> None:
    with stub_github(make_state()) as base:
        info = make_adapter(base).discover()
    assert info["provider"] == "github"
    assert info["default_branch"] == "main"
    assert info["permission_snapshot"] == {
        "branch": "main",
        "branch_protected": True,
        "visibility": "private",
    }


def test_discover_reports_unprotected_branch_when_protection_is_404() -> None:
    state = make_state()
    state.protection_status = 404
    with stub_github(state) as base:
        info = make_adapter(base).discover()
    assert info["visibility"] == "private"
    assert info["branch_protected"] is False


# -- full pull ------------------------------------------------------------------


def test_full_pull_emits_every_commit_oldest_first_with_unique_revisions() -> None:
    with stub_github(make_state()) as base:
        result = make_adapter(base).fetch_changes(None)

    kinds = [event.kind for event in result.events]
    assert kinds == ["commit", "commit", "commit"]
    revisions = [event.revision for event in result.events]
    assert revisions == [SHA_1, SHA_2, SHA_3]  # oldest applied first
    assert len(set(revisions)) == 3  # revision identity is the commit sha
    assert result.events[0].payload["message"] == "first"
    assert result.events[0].payload["files_added"] == ["README.md", "docs/a.md"]
    assert result.cursor.state["last_sha"] == SHA_3


def test_token_provider_supplies_a_bearer_header_and_absent_token_omits_it() -> None:
    state = make_state()
    with stub_github(state) as base:
        make_adapter(base, token_provider=lambda: "t0ken-123").fetch_changes(None)
    assert state.requests
    assert all(request["authorization"] == "Bearer t0ken-123" for request in state.requests)

    anonymous = make_state()
    with stub_github(anonymous) as base:
        make_adapter(base).discover()
    assert all(request["authorization"] == "" for request in anonymous.requests)


# -- incremental, resume, idempotency --------------------------------------------


def test_incremental_emits_only_new_commits_then_replays_empty() -> None:
    state = make_state()
    with stub_github(state) as base:
        adapter = make_adapter(base)
        first = adapter.fetch_changes(None)

        replay = adapter.fetch_changes(first.cursor)
        assert replay.events == ()  # same position: nothing re-emitted
        assert replay.cursor.state["last_sha"] == first.cursor.state["last_sha"]

        state.commits.insert(0, _summary(SHA_4, 4, "fourth"))
        state.details[SHA_4] = _files(("docs/b.md", "added"))

        second = adapter.fetch_changes(first.cursor)
        assert [event.revision for event in second.events] == [SHA_4]
        assert second.cursor.state["last_sha"] == SHA_4
        assert second.cursor.state["files"]["docs/b.md"] == SHA_4


def test_same_cursor_request_yields_identical_results_across_instances() -> None:
    with stub_github(make_state()) as base:
        baseline = make_adapter(base).fetch_changes(None)
        token = baseline.cursor.encoded()

        fresh = make_adapter(base)  # separate adapter instance, same upstream
        decoded_round = fresh.fetch_changes(Cursor.decode(token))
        again = fresh.fetch_changes(Cursor.decode(token))

    # The cursor already names SHA_3, so a fresh instance replaying it sees no new
    # commits -- and two instances given the identical cursor must agree byte-for-byte.
    assert decoded_round.events == again.events == ()
    assert decoded_round.cursor == again.cursor == baseline.cursor


def test_resume_survives_encoded_cursor_round_trip_without_duplicates() -> None:
    with stub_github(make_state()) as base:
        adapter = make_adapter(base)
        first = adapter.fetch_changes(None)
        token = first.cursor.encoded()
        resumed = adapter.fetch_changes(Cursor.decode(token))
    assert resumed.events == ()
    assert resumed.cursor.encoded() == token


# -- deletions -------------------------------------------------------------------


def test_delete_commit_emits_tombstone_and_drops_path_from_file_map() -> None:
    state = make_state()
    state.details[SHA_3] = _files(("docs/a.md", "removed"), ("README.md", "modified"))
    with stub_github(state) as base:
        adapter = make_adapter(base)
        result = adapter.fetch_changes(None)

    commits = [event for event in result.events if event.kind == "commit"]
    third = commits[-1]
    tombstones = [event for event in result.events if event.kind == KIND_FILE_DELETED]
    assert len(tombstones) == 1
    assert tombstones[0].revision == SHA_3  # deletion rides the removing commit's sha
    assert tombstones[0].payload == {"path": "docs/a.md", "sha": SHA_3}
    assert third.payload["files_removed"] == ["docs/a.md"]
    assert "docs/a.md" not in result.cursor.state["files"]
    assert result.cursor.state["files"]["README.md"] == SHA_3


def test_tombstoned_paths_are_not_resurrected_by_the_next_poll() -> None:
    state = make_state()
    state.details[SHA_3] = _files(("docs/a.md", "removed"))
    with stub_github(state) as base:
        adapter = make_adapter(base)
        first = adapter.fetch_changes(None)
        assert "docs/a.md" not in first.cursor.state["files"]

        state.commits.insert(0, _summary(SHA_4, 4, "fourth"))
        state.details[SHA_4] = _files(("docs/b.md", "added"))
        second = adapter.fetch_changes(first.cursor)

    assert "docs/a.md" not in second.cursor.state["files"]
    assert [event.kind for event in second.events] == ["commit"]


# -- rate limits -----------------------------------------------------------------


def test_low_remaining_headers_sleep_until_reset_before_next_call() -> None:
    state = make_state()
    state.remaining = 13  # four calls ahead: the fourth response dips below 10
    state.reset_in_seconds = 7
    sleeps = SleepRecorder()
    with stub_github(state) as base:
        result = make_adapter(base, sleeps=sleeps).fetch_changes(None)

    assert len(result.events) == 3  # the poll still completes
    assert sleeps.sleeps == [float(7 + 1)]  # reset epoch - now + 1s floor


def test_secondary_rate_limit_retries_once_after_retry_after() -> None:
    state = make_state()
    state.fail_first_commits_with_retry_after = 2
    sleeps = SleepRecorder()
    with stub_github(state) as base:
        result = make_adapter(base, sleeps=sleeps).fetch_changes(None)

    assert [event.revision for event in result.events] == [SHA_1, SHA_2, SHA_3]
    assert sleeps.sleeps == [2.0]
    from urllib.parse import urlparse as _up

    commit_calls = [
        request
        for request in state.requests
        if _up(request["path"]).path.endswith("/commits")
    ]
    assert len(commit_calls) == 2  # first attempt 403'd, patient retry succeeded


# -- broken history and foreign cursors -------------------------------------------


def test_force_pushed_anchor_raises_cursor_invalid() -> None:
    state = StubState(
        repo={"full_name": f"{OWNER}/{REPO}", "default_branch": "main"},
        commits=[_summary("e" * 40, 9, "rewritten")],
        details={"e" * 40: _files(("docs/a.md", "added"))},
    )
    with stub_github(make_state()) as base:
        anchor = make_adapter(base).checkpoint()
    with stub_github(state) as base:
        with pytest.raises(GitHubCursorInvalid):
            make_adapter(base).fetch_changes(anchor)


def test_checkpoint_reports_head_without_emitting_events() -> None:
    with stub_github(make_state()) as base:
        adapter = make_adapter(base)
        cursor = adapter.checkpoint()
    assert cursor.state["last_sha"] == SHA_3
    assert cursor.state["files"] == {}
    assert cursor.provider == "github"


def test_foreign_or_mismatched_cursors_are_rejected() -> None:
    with stub_github(make_state()) as base:
        adapter = make_adapter(base)
        with pytest.raises(ValueError, match="provider"):
            adapter.fetch_changes(
                Cursor(provider="git", source_id=adapter.source_id, state={"head": "x"})
            )
        with pytest.raises(ValueError, match="belongs to source"):
            adapter.fetch_changes(Cursor(provider="github", source_id="github:other/repo"))
