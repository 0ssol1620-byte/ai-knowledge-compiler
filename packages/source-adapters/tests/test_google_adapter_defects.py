"""Defect tests for the Google adapters: fileId keying, Gmail paging, typed revoke/cursor errors."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from akc_source_adapters.envelope import Cursor
from akc_source_adapters.google import (
    CalendarAdapter,
    DriveAdapter,
    GmailAdapter,
    SourceAccessRevoked,
    SourceCursorInvalid,
)
from akc_source_adapters.google._common import GoogleAdapterError, StaticTokenProvider


class _Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, code: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        state = self.server.state  # type: ignore[attr-defined]
        state["requests"].append(self.path)
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
        if isinstance(body, int):  # a bare status code
            self._send(body, {"error": body})
            return
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


def _file(file_id: str, name: str, modified: str = "2026-08-01T00:00:00Z") -> dict[str, Any]:
    return {
        "fileId": file_id,
        "removed": False,
        "file": {"name": name, "mimeType": "text/markdown", "modifiedTime": modified},
    }


def _drive(base: str) -> DriveAdapter:
    return DriveAdapter(source_name="main", token_provider=StaticTokenProvider("t"), api_base=base)


def _drive_run(stub, *batches: list[dict[str, Any]]):
    base, state = stub
    state["routes"] = {
        "/changes": [{"changes": b, "newStartPageToken": f"TOK{i}"} for i, b in enumerate(batches)]
    }
    adapter = _drive(base)
    cursor = None
    results = []
    for _ in batches:
        result = adapter.fetch_changes(cursor)
        cursor = result.cursor
        results.append(result)
    return results


def test_drive_removal_of_known_file_tombstones_its_last_path(stub) -> None:
    r = _drive_run(
        stub,
        [_file("f1", "spec.md")],
        [{"fileId": "f1", "removed": True}],
        [_file("f3", "spec.md")],
    )
    assert [e.kind for e in r[1].events] == ["file_removed"]
    assert r[1].events[0].payload["path"] == "spec.md"
    assert [e.kind for e in r[2].events] == ["file_added"]


def test_drive_same_name_in_two_folders_keeps_two_slots(stub) -> None:
    r = _drive_run(
        stub,
        [_file("f1", "README.md"), _file("f2", "README.md")],
        [{"fileId": "f1", "removed": True}],
    )
    assert set(r[1].cursor.state["files"]) == {"f2"}


def test_drive_rename_emits_renamed_with_previous_path(stub) -> None:
    r = _drive_run(stub, [_file("f1", "a.md")], [_file("f1", "b.md", "2026-08-02T00:00:00Z")])
    event = r[1].events[0]
    assert event.kind == "file_renamed"
    assert event.payload["path"] == "b.md"
    assert event.payload["previous_path"] == "a.md"


def test_drive_legacy_name_keyed_cursor_is_refused_not_guessed(stub) -> None:
    base, state = stub
    state["routes"] = {"/changes": {"changes": [], "newStartPageToken": "T2"}}
    legacy = Cursor(
        provider="gdrive",
        source_id="gdrive:main",
        state={"delta_token": "T1", "files": {"spec.md": "f1@2026-08-01T00:00:00Z"}},
    )
    with pytest.raises(SourceCursorInvalid):
        _drive(base).fetch_changes(legacy)
    assert state["requests"] == []


def test_gmail_history_pages_are_all_consumed_before_cursor_advances(stub) -> None:
    base, state = stub
    msg = {"labelIds": ["INBOX"], "payload": {"headers": []}}
    state["routes"] = {
        "/history": [
            {
                "history": [{"messagesAdded": [{"message": {"id": "m1"}}]}],
                "historyId": "1005",
                "nextPageToken": "P2",
            },
            {"history": [{"messagesAdded": [{"message": {"id": "m2"}}]}], "historyId": "1009"},
        ],
        "/messages/m1": {"id": "m1", **msg},
        "/messages/m2": {"id": "m2", **msg},
    }
    adapter = GmailAdapter(source_name="me", token_provider=StaticTokenProvider("t"), api_base=base)
    cursor = Cursor(provider="gmail", source_id="gmail:me", state={"history_id": "1000"})
    result = adapter.fetch_changes(cursor)
    assert sorted(e.payload["message_id"] for e in result.events) == ["m1", "m2"]
    assert result.cursor.state["history_id"] == "1009"
    assert any("pageToken=P2" in r for r in state["requests"])


def test_gmail_stale_history_id_raises_cursor_invalid(stub) -> None:
    base, state = stub
    state["routes"] = {"/history": 404}
    adapter = GmailAdapter(source_name="me", token_provider=StaticTokenProvider("t"), api_base=base)
    cursor = Cursor(provider="gmail", source_id="gmail:me", state={"history_id": "1"})
    with pytest.raises(SourceCursorInvalid):
        adapter.fetch_changes(cursor)


def test_calendar_expired_sync_token_raises_cursor_invalid(stub) -> None:
    base, state = stub
    state["routes"] = {"/calendars/cal-1/events": 410}
    adapter = CalendarAdapter(
        source_name="w", calendar_id="cal-1", token_provider=StaticTokenProvider("t"), api_base=base
    )
    cursor = Cursor(provider="gcal", source_id="gcal:w", state={"sync_token": "OLD"})
    with pytest.raises(SourceCursorInvalid):
        adapter.fetch_changes(cursor)


@pytest.mark.parametrize("status", [401, 403])
def test_revoked_token_raises_access_revoked_not_retry(stub, status: int) -> None:
    base, state = stub
    state["routes"] = {"/changes": status}
    cursor = Cursor(provider="gdrive", source_id="gdrive:main", state={"delta_token": "T"})
    with pytest.raises(SourceAccessRevoked):
        _drive(base).fetch_changes(cursor)
    assert len(state["requests"]) == 1


def test_5xx_on_cursor_request_still_retries(stub, monkeypatch) -> None:
    base, state = stub
    state["routes"] = {
        "/changes": [503, {"changes": [], "newStartPageToken": "T2"}],
    }
    cursor = Cursor(provider="gdrive", source_id="gdrive:main", state={"delta_token": "T"})
    result = _drive(base).fetch_changes(cursor)  # adapter's sleep is a no-op
    assert "T2" in result.cursor.state.values()
    assert len(state["requests"]) == 2


def test_5xx_exhaustion_is_plain_adapter_error_not_cursor_invalid(stub) -> None:
    base, state = stub
    state["routes"] = {"/changes": 503}
    cursor = Cursor(provider="gdrive", source_id="gdrive:main", state={"delta_token": "T"})
    with pytest.raises(GoogleAdapterError) as info:
        _drive(base).fetch_changes(cursor)
    assert not isinstance(info.value, (SourceCursorInvalid, SourceAccessRevoked))
