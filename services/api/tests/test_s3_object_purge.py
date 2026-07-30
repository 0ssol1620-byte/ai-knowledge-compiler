"""Exact-key physical purge evidence for versioned object storage."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from akc_api.storage import ObjectPurgeIncompleteError, S3ObjectStore


class FakeVersionedS3:
    def __init__(self, *, partial_failure: bool = False) -> None:
        self.entries: list[tuple[str, str, bool]] = [
            ("tenant/document.bin", "version-3", False),
            ("tenant/document.bin", "version-2", False),
            ("tenant/document.bin", "delete-marker-1", True),
            ("tenant/document.bin-neighbor", "neighbor-version", False),
        ]
        self.partial_failure = partial_failure
        self.deleted: list[tuple[str, str]] = []
        self.list_calls = 0

    def list_object_versions(self, **kwargs: Any) -> dict[str, Any]:
        self.list_calls += 1
        prefix = str(kwargs["Prefix"])
        candidates = [entry for entry in self.entries if entry[0].startswith(prefix)]
        marker = str(kwargs.get("VersionIdMarker", "cursor-0"))
        offset = int(marker.removeprefix("cursor-"))
        page = candidates[offset : offset + 2]
        result: dict[str, Any] = {
            "IsTruncated": offset + len(page) < len(candidates),
            "Versions": [
                {"Key": key, "VersionId": version_id}
                for key, version_id, is_marker in page
                if not is_marker
            ],
            "DeleteMarkers": [
                {"Key": key, "VersionId": version_id}
                for key, version_id, is_marker in page
                if is_marker
            ],
        }
        if result["IsTruncated"]:
            result["NextKeyMarker"] = prefix
            result["NextVersionIdMarker"] = f"cursor-{offset + len(page)}"
        return result

    def delete_objects(self, **kwargs: Any) -> dict[str, Any]:
        objects = list(kwargs["Delete"]["Objects"])
        errors: list[dict[str, str]] = []
        for index, identity in enumerate(objects):
            key = str(identity["Key"])
            version_id = str(identity["VersionId"])
            if self.partial_failure and index == 0:
                errors.append(
                    {
                        "Key": key,
                        "VersionId": version_id,
                        "Code": "AccessDenied",
                    }
                )
                continue
            self.deleted.append((key, version_id))
            self.entries = [
                entry
                for entry in self.entries
                if (entry[0], entry[1]) != (key, version_id)
            ]
        return {"Errors": errors}


class FakeUnversionedS3:
    def __init__(self) -> None:
        self.deleted = False

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        self.deleted = True
        return {}

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {"IsTruncated": False, "Contents": [] if self.deleted else [{"Key": "present"}]}


def _store(client: object, *, mode: str = "versioned") -> S3ObjectStore:
    store = S3ObjectStore.__new__(S3ObjectStore)
    store.settings = cast(
        Any,
        SimpleNamespace(
            s3_deletion_mode=mode,
            s3_bucket_quarantine="quarantine",
            s3_bucket_source="source",
            s3_bucket_working="working",
            s3_bucket_derived="derived",
            s3_bucket_exports="exports",
            s3_bucket_audit="audit",
        ),
    )
    store.client = cast(Any, client)
    return store


async def test_versioned_delete_removes_every_version_and_marker_across_pages() -> None:
    client = FakeVersionedS3()
    store = _store(client)

    assert await store.delete("source", "tenant/document.bin") is True
    assert set(client.deleted) == {
        ("tenant/document.bin", "version-3"),
        ("tenant/document.bin", "version-2"),
        ("tenant/document.bin", "delete-marker-1"),
    }
    assert client.entries == [
        ("tenant/document.bin-neighbor", "neighbor-version", False)
    ]
    assert client.list_calls >= 3
    assert await store.delete("source", "tenant/document.bin") is False


async def test_versioned_partial_delete_fails_closed() -> None:
    client = FakeVersionedS3(partial_failure=True)
    store = _store(client)

    with pytest.raises(
        ObjectPurgeIncompleteError,
        match="object_store_partial_version_delete:AccessDenied",
    ):
        await store.delete("source", "tenant/document.bin")
    assert any(key == "tenant/document.bin" for key, _version, _marker in client.entries)


async def test_explicit_unversioned_contract_verifies_key_absence() -> None:
    client = FakeUnversionedS3()
    store = _store(client, mode="unversioned-explicit")

    assert await store.delete("source", "tenant/document.bin") is True
    assert client.deleted
