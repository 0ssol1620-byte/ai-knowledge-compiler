from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_source_adapters import (
    PROVIDER_DEFAULT_FRESHNESS,
    Cursor,
    FileServerAdapter,
    FileServerAdapterError,
    Freshness,
    S3Adapter,
    S3AdapterError,
    SourceAdapter,
)

NOW = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)


def test_file_server_adapter_tracks_add_change_delete_and_resume(tmp_path: Path) -> None:
    root = tmp_path / "share"
    root.mkdir()
    (root / "contract.pdf").write_bytes(b"pdf-v1")
    (root / "notes.md").write_text("# Note\n", encoding="utf-8")
    adapter = FileServerAdapter(root, source_name="legal", clock=lambda: NOW)

    assert isinstance(adapter, SourceAdapter)
    first = adapter.fetch_changes(None)
    assert [(event.kind, event.payload["path"]) for event in first.events] == [
        ("file_added", "contract.pdf"),
        ("file_added", "notes.md"),
    ]
    assert adapter.fetch_changes(Cursor.decode(first.cursor.encoded())).events == ()

    (root / "contract.pdf").write_bytes(b"pdf-v2")
    (root / "notes.md").unlink()
    (root / "new.docx").write_bytes(b"docx")
    changed = adapter.fetch_changes(first.cursor)
    assert [(event.kind, event.payload["path"]) for event in changed.events] == [
        ("file_changed", "contract.pdf"),
        ("file_added", "new.docx"),
        ("file_deleted", "notes.md"),
    ]
    assert changed.events[0].payload["previous_sha256"]
    assert changed.events[-1].payload["previous_sha256"]


def test_file_server_adapter_excludes_system_files_and_never_follows_symlinks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "share"
    root.mkdir()
    (root / "keep.md").write_text("keep", encoding="utf-8")
    (root / "~$draft.docx").write_text("temp", encoding="utf-8")
    link = root / "outside-link"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not available on this host")
    adapter = FileServerAdapter(root)

    discovered = adapter.discover()
    assert discovered["files"] == 1
    assert discovered["skipped_symlinks"] == 1
    assert [event.payload["path"] for event in adapter.fetch_changes(None).events] == ["keep.md"]


def test_file_server_adapter_fails_closed_on_bounds(tmp_path: Path) -> None:
    root = tmp_path / "share"
    root.mkdir()
    (root / "too-large.bin").write_bytes(b"1234")
    with pytest.raises(FileServerAdapterError, match="max_file_bytes"):
        FileServerAdapter(root, max_file_bytes=3).fetch_changes(None)


class FakeS3:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, object]] = []

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return self.pages[len(self.calls) - 1]


def _object(key: str, etag: str, *, size: int = 10) -> dict[str, object]:
    return {"Key": key, "ETag": f'"{etag}"', "Size": size, "LastModified": NOW}


def test_s3_adapter_pages_metadata_without_reading_object_bytes() -> None:
    client = FakeS3(
        [
            {
                "Contents": [_object("team/a.pdf", "aaa")],
                "IsTruncated": True,
                "NextContinuationToken": "next",
            },
            {"Contents": [_object("team/b.pdf", "bbb")], "IsTruncated": False},
        ]
    )
    adapter = S3Adapter(
        client,
        bucket="customer-docs",
        prefix="team/",
        source_name="customer-s3",
        endpoint_label="r2",
        clock=lambda: NOW,
    )

    assert isinstance(adapter, SourceAdapter)
    first = adapter.fetch_changes(None)
    assert [event.kind for event in first.events] == ["object_added", "object_added"]
    assert all(event.payload["customer_bytes_read"] is False for event in first.events)
    assert client.calls[1]["ContinuationToken"] == "next"
    assert adapter.discover()["permission_snapshot"] == {
        "read_only": True,
        "operations": ["ListBucket"],
        "customer_bytes_read": False,
    }


def test_s3_adapter_tracks_metadata_changes_and_tombstones() -> None:
    baseline_client = FakeS3([{"Contents": [_object("a.pdf", "aaa"), _object("b.pdf", "bbb")]}])
    baseline = S3Adapter(baseline_client, bucket="docs", clock=lambda: NOW).fetch_changes(None)
    changed_client = FakeS3(
        [{"Contents": [_object("a.pdf", "new", size=11), _object("c.pdf", "ccc")]}]
    )
    changed = S3Adapter(changed_client, bucket="docs", clock=lambda: NOW).fetch_changes(
        baseline.cursor
    )

    assert [(event.kind, event.payload["key"]) for event in changed.events] == [
        ("object_changed", "a.pdf"),
        ("object_added", "c.pdf"),
        ("object_deleted", "b.pdf"),
    ]
    assert changed.events[0].payload["previous_revision"]
    assert changed.events[-1].payload["previous_revision"]


def test_s3_adapter_rejects_prefix_escape_and_broken_pagination() -> None:
    escaped = S3Adapter(
        FakeS3([{"Contents": [_object("other/a.pdf", "aaa")]}]),
        bucket="docs",
        prefix="team/",
    )
    with pytest.raises(S3AdapterError, match="outside the configured prefix"):
        escaped.fetch_changes(None)

    broken = S3Adapter(FakeS3([{"Contents": [], "IsTruncated": True}]), bucket="docs")
    with pytest.raises(S3AdapterError, match="continuation token"):
        broken.fetch_changes(None)


def test_cloud_and_file_server_defaults_are_hourly() -> None:
    assert PROVIDER_DEFAULT_FRESHNESS["file_server"] is Freshness.F1
    assert PROVIDER_DEFAULT_FRESHNESS["s3"] is Freshness.F1
