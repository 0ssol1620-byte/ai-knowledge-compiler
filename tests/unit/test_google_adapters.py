"""Stub-server contract tests for the Google adapters (no network, no keys)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from akc_source_adapters.envelope import Cursor
from akc_source_adapters.google import CalendarAdapter, DriveAdapter, GmailAdapter
from akc_source_adapters.google._common import StaticTokenProvider


class _Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, code: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        state = self.server.state  # type: ignore[attr-defined]
        state["requests"].append(self.path)
        if state.get("fail_first_with_429"):
            state["fail_first_with_429"] -= 1
            self._send(429, {"error": "rate"}, {"Retry-After": "1"})
            return
        path = self.path.split("?")[0]
        route = state["routes"].get(path)
        if route is None:
            self._send(404, {"error": "not found"})
            return
        page = state["pages"].get(path, 0)
        if isinstance(route, list):
            body = route[min(page, len(route) - 1)]
            state["pages"][path] = page + 1
        else:
            body = route
        self._send(200, body)


@pytest.fixture()
def stub():
    state: dict[str, Any] = {"routes": {}, "requests": [], "pages": {}}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    server.state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", state
    server.shutdown()


def _token() -> str:
    return "stub-token"


def test_drive_full_then_incremental_with_tombstone(stub) -> None:
    base, state = stub
    state["routes"] = {
        "/about": {"user": {"emailAddress": "a@b.c"}, "storageQuota": {}},
        "/changes": [
            {
                "changes": [
                    {
                        "fileId": "f1",
                        "file": {
                            "name": "spec.md",
                            "mimeType": "text/markdown",
                            "modifiedTime": "2026-08-01T00:00:00Z",
                        },
                        "removed": False,
                    },
                ],
                "newStartPageToken": "TOK1",
            },
            {
                "changes": [
                    {
                        "fileId": "f1",
                        "file": {
                            "name": "spec.md",
                            "mimeType": "text/markdown",
                            "modifiedTime": "2026-08-02T00:00:00Z",
                        },
                        "removed": False,
                    },
                    {"fileId": "f2", "removed": True},
                ],
                "newStartPageToken": "TOK2",
            },
        ],
    }
    adapter = DriveAdapter(
        source_name="main", token_provider=StaticTokenProvider(_token()), api_base=base
    )

    first = adapter.fetch_changes(None)
    assert [e.kind for e in first.events] == ["file_added"]
    assert first.cursor.state["delta_token"] == "TOK1"

    original_files = dict(first.cursor.state["files"])
    second = adapter.fetch_changes(first.cursor)
    assert first.cursor.state["files"] == original_files
    kinds = [e.kind for e in second.events]
    assert kinds == ["file_changed", "file_removed"]
    assert second.cursor.state["delta_token"] == "TOK2"


def _drive_file(file_id: str, name: str, modified: str) -> dict[str, Any]:
    return {
        "fileId": file_id,
        "file": {"name": name, "mimeType": "text/markdown", "modifiedTime": modified},
        "removed": False,
    }


def test_drive_tracks_file_ids_across_rename_tombstone_and_shared_names(stub) -> None:
    base, state = stub
    state["routes"] = {
        "/changes": [
            {
                "changes": [
                    _drive_file("f1", "a.md", "2026-08-01T00:00:00Z"),
                    _drive_file("f2", "dup.md", "2026-08-01T00:00:00Z"),
                    _drive_file("f3", "dup.md", "2026-08-01T00:00:00Z"),
                ],
                "newStartPageToken": "TOK1",
            },
            {
                "changes": [
                    _drive_file("f1", "b.md", "2026-08-02T00:00:00Z"),
                    _drive_file("f3", "dup.md", "2026-08-02T00:00:00Z"),
                    {"fileId": "f2", "removed": True},
                ],
                "newStartPageToken": "TOK2",
            },
        ],
    }
    adapter = DriveAdapter(
        source_name="main", token_provider=StaticTokenProvider(_token()), api_base=base
    )

    first = adapter.fetch_changes(None)
    assert [e.kind for e in first.events] == ["file_added"] * 3
    assert sorted(first.cursor.state["file_ids"]) == ["f1", "f2", "f3"]
    assert first.cursor.state["file_ids"]["f2"]["path"] == "dup.md"
    assert first.cursor.state["file_ids"]["f3"]["path"] == "dup.md"

    second = adapter.fetch_changes(first.cursor)
    assert [(e.kind, e.payload["path"]) for e in second.events] == [
        ("file_removed", "a.md"),
        ("file_added", "b.md"),
        ("file_changed", "dup.md"),
        ("file_removed", "dup.md"),
    ]
    assert second.cursor.state["file_ids"] == {
        "f1": {"path": "b.md", "revision": "f1@2026-08-02T00:00:00Z"},
        "f3": {"path": "dup.md", "revision": "f3@2026-08-02T00:00:00Z"},
    }
    assert second.cursor.state["files"] == {
        "b.md": "f1@2026-08-02T00:00:00Z",
        "dup.md": "f3@2026-08-02T00:00:00Z",
    }


def test_drive_legacy_files_cursor_derives_file_ids(stub) -> None:
    base, state = stub
    state["routes"] = {
        "/changes": {
            "changes": [
                {"fileId": "f1", "removed": True},
                _drive_file("f2", "notes.md", "2026-08-02T00:00:00Z"),
                _drive_file("f9", "notes.md", "2026-08-02T00:00:00Z"),
            ],
            "newStartPageToken": "TOK2",
        },
    }
    adapter = DriveAdapter(
        source_name="main", token_provider=StaticTokenProvider(_token()), api_base=base
    )
    legacy = Cursor(
        provider="gdrive",
        source_id=adapter.source_id,
        state={
            "delta_token": "TOK1",
            "files": {
                "spec.md": "f1@2026-08-01T00:00:00Z",
                "notes.md": "f2@2026-08-01T00:00:00Z",
            },
        },
    )

    result = adapter.fetch_changes(legacy)
    assert [(e.kind, e.payload["path"]) for e in result.events] == [
        ("file_removed", "spec.md"),
        ("file_changed", "notes.md"),
        ("file_added", "notes.md"),
    ]
    assert sorted(result.cursor.state["file_ids"]) == ["f2", "f9"]
    assert result.cursor.state["files"] == {"notes.md": "f9@2026-08-02T00:00:00Z"}
    assert "file_ids" not in legacy.state


def test_drive_shared_name_projection_survives_encoded_roundtrip(stub) -> None:
    base, state = stub
    state["routes"] = {
        "/changes": [
            {
                "changes": [
                    _drive_file("f2", "dup.md", "2026-08-01T00:00:00Z"),
                    _drive_file("f1", "dup.md", "2026-08-01T00:00:00Z"),
                ],
                "newStartPageToken": "TOK1",
            },
            {"changes": [], "newStartPageToken": "TOK2"},
            {
                "changes": [_drive_file("f1", "dup.md", "2026-08-03T00:00:00Z")],
                "newStartPageToken": "TOK3",
            },
        ],
    }
    adapter = DriveAdapter(
        source_name="main", token_provider=StaticTokenProvider(_token()), api_base=base
    )

    first = adapter.fetch_changes(None)
    assert first.cursor.state["files"] == {"dup.md": "f1@2026-08-01T00:00:00Z"}

    decoded = Cursor.decode(first.cursor.encoded())
    assert list(decoded.state["file_ids"]) == ["f1", "f2"]

    empty = adapter.fetch_changes(decoded)
    assert empty.events == ()
    assert empty.cursor.state["files"] == {"dup.md": "f1@2026-08-01T00:00:00Z"}
    assert sorted(empty.cursor.state["file_ids"]) == ["f1", "f2"]

    later = adapter.fetch_changes(Cursor.decode(empty.cursor.encoded()))
    assert [(e.kind, e.payload["path"]) for e in later.events] == [("file_changed", "dup.md")]
    assert later.cursor.state["files"] == {"dup.md": "f1@2026-08-03T00:00:00Z"}
    assert later.cursor.state["file_ids"] == {
        "f1": {"path": "dup.md", "revision": "f1@2026-08-03T00:00:00Z"},
        "f2": {"path": "dup.md", "revision": "f2@2026-08-01T00:00:00Z"},
    }


def test_drive_legacy_cursor_rejects_file_id_under_two_paths(stub) -> None:
    base, state = stub
    state["routes"] = {
        "/changes": {
            "changes": [_drive_file("f1", "a.md", "2026-08-03T00:00:00Z")],
            "newStartPageToken": "TOK2",
        },
    }
    adapter = DriveAdapter(
        source_name="main", token_provider=StaticTokenProvider(_token()), api_base=base
    )
    legacy = Cursor(
        provider="gdrive",
        source_id=adapter.source_id,
        state={
            "delta_token": "TOK1",
            "files": {"a.md": "f1@2026-08-02T00:00:00Z", "z.md": "f1@2026-08-01T00:00:00Z"},
        },
    )
    token = legacy.encoded()
    decoded = Cursor.decode(token)

    with pytest.raises(ValueError, match="fileId 'f1' to multiple paths"):
        adapter.fetch_changes(decoded)
    assert state["requests"] == []
    assert decoded.state["delta_token"] == "TOK1"
    assert "file_ids" not in decoded.state
    assert decoded.encoded() == token


def test_gmail_history_tombstones_and_resume(stub) -> None:
    base, state = stub
    state["routes"] = {
        "/profile": [
            {"emailAddress": "a@b.c", "historyId": "1000"},
            {"emailAddress": "a@b.c", "historyId": "1000"},
        ],
        "/messages/m1": {
            "id": "m1",
            "threadId": "t1",
            "snippet": "hello",
            "labelIds": ["INBOX"],
            "payload": {"headers": [{"name": "Subject", "value": "Kickoff notes"}]},
        },
        "/history": {
            "history": [
                {"messagesAdded": [{"message": {"id": "m1", "threadId": "t1"}}]},
                {"messagesDeleted": [{"message": {"id": "m0"}}]},
            ],
            "historyId": "1001",
        },
    }
    adapter = GmailAdapter(
        source_name="me", token_provider=StaticTokenProvider(_token()), api_base=base
    )

    bootstrap = adapter.fetch_changes(None)
    assert bootstrap.events == ()
    assert bootstrap.cursor.state["history_id"] == "1000"

    second = adapter.fetch_changes(bootstrap.cursor)
    kinds = sorted(e.kind for e in second.events)
    assert kinds == ["message_added", "message_removed"]
    assert second.cursor.state["history_id"] == "1001"


def test_calendar_cancelled_is_tombstone_and_sync_token_persists(stub) -> None:
    base, state = stub
    state["routes"] = {
        "/calendars/cal-1": {"summary": "Work", "timeZone": "Asia/Seoul"},
        "/calendars/cal-1/events": {
            "items": [
                {
                    "id": "e1",
                    "status": "confirmed",
                    "summary": "Standup",
                    "start": {"dateTime": "2026-08-24T09:00:00+09:00"},
                    "etag": "1",
                },
                {"id": "e2", "status": "cancelled", "summary": "Old", "etag": "2"},
            ],
            "nextSyncToken": "SYNC1",
        },
    }
    adapter = CalendarAdapter(
        source_name="work",
        calendar_id="cal-1",
        token_provider=StaticTokenProvider(_token()),
        api_base=base,
    )
    result = adapter.fetch_changes(None)
    kinds = sorted(e.kind for e in result.events)
    assert kinds == ["event_added", "event_cancelled"]
    assert result.cursor.state["sync_token"] == "SYNC1"


def test_backoff_honors_retry_after_then_succeeds(stub, monkeypatch) -> None:
    base, state = stub
    state["routes"] = {"/changes": {"changes": [], "newStartPageToken": "T1"}}
    state["fail_first_with_429"] = 1
    sleeps: list[float] = []
    adapter = DriveAdapter(
        source_name="main",
        token_provider=StaticTokenProvider(_token()),
        api_base=base,
        sleep=sleeps.append,
    )
    result = adapter.fetch_changes(None)
    assert result.events == ()
    assert sleeps and sleeps[0] >= 1.0


def test_discover_reports_account_and_tier(stub) -> None:
    base, state = stub
    state["routes"] = {"/about": {"user": {"emailAddress": "x@y.z"}, "storageQuota": {}}}
    adapter = DriveAdapter(
        source_name="main", token_provider=StaticTokenProvider(_token()), api_base=base
    )
    info = adapter.discover()
    assert info["account"] == "x@y.z"
    assert info["freshness_tier"] == "F1"


@pytest.mark.parametrize("files", [None, [], "invalid"])
def test_drive_rejects_malformed_file_cursor(files: object) -> None:
    adapter = DriveAdapter(source_name="main", token_provider=StaticTokenProvider(_token()))
    cursor = Cursor(provider="gdrive", source_id=adapter.source_id, state={"files": files})
    with pytest.raises(ValueError, match="cursor files must be a mapping"):
        adapter.fetch_changes(cursor)
