from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from akc_source_adapters.foundation_agent import (
    AgentState,
    FoundationAgentError,
    HttpFoundationClient,
    _is_safe_transport_url,
    load_state,
    save_state,
    sync_file_server,
    sync_s3_source,
)

CONNECTION_ID = "49d42924-a3cc-4a09-b92d-9c86b58901a1"
DOCUMENT_ID = "59d42924-a3cc-4a09-b92d-9c86b58901a1"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://storage.example/object?signature=secret", True),
        ("http://localhost:9000/bucket", True),
        ("http://127.0.0.1:9000/bucket", True),
        ("http://[::1]:9000/bucket", True),
        ("http://localhost.evil.example/bucket", False),
        ("https://user:password@storage.example/bucket", False),
        ("http://storage.example/bucket", False),
    ],
)
def test_transport_urls_require_https_or_exact_loopback(url: str, expected: bool) -> None:
    assert _is_safe_transport_url(url) is expected


def test_foundation_client_rejects_deceptive_localhost_base() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        HttpFoundationClient("http://localhost.evil.example", "tvnl_live_test")


class FakeFoundation:
    def __init__(self, *, fail_batch: bool = False) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.direct_uploads: list[bytes] = []
        self.batches: list[dict[str, Any]] = []
        self.fail_batch = fail_batch

    def create_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.uploads.append(dict(kwargs))
        return {"uploadUrl": "https://upload.example/object", "documentId": DOCUMENT_ID}

    def upload_file(self, **kwargs: Any) -> None:
        self.direct_uploads.append(kwargs["path"].read_bytes())

    def apply_batch(self, connection_id: str, batch: dict[str, Any]) -> dict[str, Any]:
        self.batches.append({"connection_id": connection_id, **batch})
        if self.fail_batch:
            raise FoundationAgentError("batch failed")
        return {"status": "applied"}


def test_agent_uploads_qualified_bytes_directly_then_commits_cursor(tmp_path: Path) -> None:
    root = tmp_path / "share"
    root.mkdir()
    (root / "report.pdf").write_bytes(b"qualified-pdf")
    (root / "notes.md").write_text("metadata only", encoding="utf-8")
    state_path = tmp_path / "agent-state.json"
    client = FakeFoundation()

    result = sync_file_server(
        root=root,
        connection_id=CONNECTION_ID,
        state_path=state_path,
        client=client,
    )

    assert result["status"] == "applied"
    assert len(client.uploads) == 1
    assert client.uploads[0]["filename"] == "report.pdf"
    assert client.direct_uploads == [b"qualified-pdf"]
    events = client.batches[0]["events"]
    assert [event["nativeId"] for event in events] == ["notes.md", "report.pdf"]
    assert events[0]["documentId"] is None
    assert events[1]["documentId"] == DOCUMENT_ID
    assert len(events[1]["sourceIdempotencyKey"]) == 64
    assert load_state(state_path, CONNECTION_ID).server_cursor_sha256

    replay = sync_file_server(
        root=root,
        connection_id=CONNECTION_ID,
        state_path=state_path,
        client=client,
    )
    assert replay == {"status": "unchanged", "eventCount": 0}
    assert len(client.uploads) == 1
    assert len(client.batches) == 1


def test_agent_does_not_advance_cursor_when_remote_commit_fails(tmp_path: Path) -> None:
    root = tmp_path / "share"
    root.mkdir()
    (root / "report.pdf").write_bytes(b"qualified-pdf")
    state_path = tmp_path / "state.json"

    with pytest.raises(FoundationAgentError, match="batch failed"):
        sync_file_server(
            root=root,
            connection_id=CONNECTION_ID,
            state_path=state_path,
            client=FakeFoundation(fail_batch=True),
        )

    assert not state_path.exists()


def test_agent_state_is_connection_bound_and_never_contains_api_keys(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    save_state(state_path, AgentState(CONNECTION_ID, None, None))
    assert "tvnl_live_" not in state_path.read_text(encoding="utf-8")
    with pytest.raises(FoundationAgentError, match="binding"):
        load_state(state_path, "69d42924-a3cc-4a09-b92d-9c86b58901a1")


class FakeS3:
    def __init__(self) -> None:
        self.objects = {
            "approved/report.pdf": b"s3-pdf",
            "approved/notes.md": b"metadata",
        }
        self.get_calls: list[dict[str, object]] = []

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        prefix = str(kwargs.get("Prefix") or "")
        return {
            "Contents": [
                {
                    "Key": key,
                    "ETag": f'"etag-{key}"',
                    "Size": len(value),
                    "LastModified": datetime(2026, 8, 30, tzinfo=UTC),
                }
                for key, value in self.objects.items()
                if key.startswith(prefix)
            ],
            "IsTruncated": False,
        }

    def get_object(self, **kwargs: object) -> dict[str, object]:
        self.get_calls.append(dict(kwargs))
        return {"Body": BytesIO(self.objects[str(kwargs["Key"])])}


def test_s3_agent_downloads_only_qualified_objects_then_commits(tmp_path: Path) -> None:
    s3 = FakeS3()
    foundation = FakeFoundation()
    state_path = tmp_path / "s3-state.json"

    result = sync_s3_source(
        s3_client=s3,
        bucket="research",
        prefix="approved/",
        connection_id=CONNECTION_ID,
        state_path=state_path,
        client=foundation,
        endpoint_label="r2",
    )

    assert result["status"] == "applied"
    assert [call["Key"] for call in s3.get_calls] == ["approved/report.pdf"]
    assert foundation.direct_uploads == [b"s3-pdf"]
    events = foundation.batches[0]["events"]
    report = next(event for event in events if event["nativeId"].endswith("report.pdf"))
    notes = next(event for event in events if event["nativeId"].endswith("notes.md"))
    assert report["documentId"] == DOCUMENT_ID
    assert len(report["sourceIdempotencyKey"]) == 64
    assert report["contentSha256"]
    assert notes["documentId"] is None
    assert notes["contentSha256"] is None

    replay = sync_s3_source(
        s3_client=s3,
        bucket="research",
        prefix="approved/",
        connection_id=CONNECTION_ID,
        state_path=state_path,
        client=foundation,
        endpoint_label="r2",
    )
    assert replay == {"status": "unchanged", "eventCount": 0}
    assert len(s3.get_calls) == 1
