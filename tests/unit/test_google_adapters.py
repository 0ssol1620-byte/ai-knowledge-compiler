"""Stub-server contract tests for the Google adapters (no network, no keys)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

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

    def do_GET(self) -> None:  # noqa: N802
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
                    {"fileId": "f1", "file": {"name": "spec.md", "mimeType": "text/markdown", "modifiedTime": "2026-08-01T00:00:00Z"}, "removed": False},
                ],
                "newStartPageToken": "TOK1",
            },
            {
                "changes": [
                    {"fileId": "f1", "file": {"name": "spec.md", "mimeType": "text/markdown", "modifiedTime": "2026-08-02T00:00:00Z"}, "removed": False},
                    {"fileId": "f2", "removed": True},
                ],
                "newStartPageToken": "TOK2",
            },
        ],
    }
    adapter = DriveAdapter(source_name="main", token_provider=StaticTokenProvider(_token()), api_base=base)

    first = adapter.fetch_changes(None)
    assert [e.kind for e in first.events] == ["file_added"]
    assert first.cursor.state["delta_token"] == "TOK1"

    second = adapter.fetch_changes(first.cursor)
    kinds = [e.kind for e in second.events]
    assert kinds == ["file_changed", "file_removed"]
    assert second.cursor.state["delta_token"] == "TOK2"


def test_gmail_history_tombstones_and_resume(stub) -> None:
    base, state = stub
    state["routes"] = {
        "/profile": [
            {"emailAddress": "a@b.c", "historyId": "1000"},
            {"emailAddress": "a@b.c", "historyId": "1000"},
        ],
        "/messages/m1": {"id": "m1", "threadId": "t1", "snippet": "hello",
                          "labelIds": ["INBOX"],
                          "payload": {"headers": [{"name": "Subject", "value": "Kickoff notes"}]}},
        "/history": {
            "history": [
                {"messagesAdded": [{"message": {"id": "m1", "threadId": "t1"}}]},
                {"messagesDeleted": [{"message": {"id": "m0"}}]},
            ],
            "historyId": "1001",
        },
    }
    adapter = GmailAdapter(source_name="me", token_provider=StaticTokenProvider(_token()), api_base=base)

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
                {"id": "e1", "status": "confirmed", "summary": "Standup", "start": {"dateTime": "2026-08-24T09:00:00+09:00"}, "etag": "1"},
                {"id": "e2", "status": "cancelled", "summary": "Old", "etag": "2"},
            ],
            "nextSyncToken": "SYNC1",
        },
    }
    adapter = CalendarAdapter(
        source_name="work", calendar_id="cal-1", token_provider=StaticTokenProvider(_token()), api_base=base
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
        source_name="main", token_provider=StaticTokenProvider(_token()), api_base=base,
        sleep=sleeps.append,
    )
    result = adapter.fetch_changes(None)
    assert result.events == ()
    assert sleeps and sleeps[0] >= 1.0


def test_discover_reports_account_and_tier(stub) -> None:
    base, state = stub
    state["routes"] = {"/about": {"user": {"emailAddress": "x@y.z"}, "storageQuota": {}}}
    adapter = DriveAdapter(source_name="main", token_provider=StaticTokenProvider(_token()), api_base=base)
    info = adapter.discover()
    assert info["account"] == "x@y.z"
    assert info["freshness_tier"] == "F1"
