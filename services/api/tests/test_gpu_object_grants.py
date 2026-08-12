from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from akc_api.settings import Settings
from akc_api.storage import (
    GpuObjectGrantNotSupportedError,
    LocalObjectStore,
    S3ObjectStore,
)


class FakePresignClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], int]] = []

    def generate_presigned_url(
        self,
        operation: str,
        *,
        Params: dict[str, str],
        ExpiresIn: int,
    ) -> str:
        self.calls.append((operation, Params, ExpiresIn))
        return f"https://objects.example/{operation}?signature=redacted"


def test_s3_role_clients_are_partitioned_by_bucket_purpose() -> None:
    store = S3ObjectStore.__new__(S3ObjectStore)
    fallback = cast(Any, object())
    source = cast(Any, object())
    working = cast(Any, object())
    derived = cast(Any, object())
    audit = cast(Any, object())
    store.client = fallback
    store._role_clients = {
        "source": source,
        "working": working,
        "derived": derived,
        "audit": audit,
    }

    assert store._client("quarantine") is source
    assert store._client("source") is source
    assert store._client("working") is working
    assert store._client("derived") is derived
    assert store._client("exports") is derived
    assert store._client("audit") is audit


def test_s3_role_credential_pairs_fail_closed() -> None:
    with pytest.raises(ValueError, match="every S3 role credential"):
        Settings(s3_source_access_key_id="source-access-only")


async def test_local_store_cannot_issue_remote_gpu_grants(tmp_path: Path) -> None:
    store = LocalObjectStore(Settings(data_dir=tmp_path))

    with pytest.raises(GpuObjectGrantNotSupportedError):
        await store.create_gpu_input_target(
            bucket="source",
            object_key="tenants/t/source/document.bin",
            expires=600,
        )
    with pytest.raises(GpuObjectGrantNotSupportedError):
        await store.create_gpu_output_target(
            object_key="tenants/t/derived/result.json",
            expires=600,
        )


async def test_s3_gpu_grants_are_exact_object_get_and_json_put() -> None:
    store = S3ObjectStore.__new__(S3ObjectStore)
    store.settings = cast(
        Any,
        SimpleNamespace(
            s3_bucket_quarantine="quarantine-private",
            s3_bucket_source="source-private",
            s3_bucket_working="working-private",
            s3_bucket_derived="derived-private",
            s3_bucket_exports="exports-private",
            s3_bucket_audit="audit-private",
        ),
    )
    client = FakePresignClient()
    store.client = cast(Any, client)

    input_target = await store.create_gpu_input_target(
        bucket="source",
        object_key="tenants/t/source/document.bin",
        expires=600,
    )
    output_target = await store.create_gpu_output_target(
        object_key="tenants/t/derived/invocations/i/result.json",
        expires=600,
    )

    assert input_target.headers == {}
    assert output_target.headers == {"Content-Type": "application/json"}
    assert client.calls == [
        (
            "get_object",
            {
                "Bucket": "source-private",
                "Key": "tenants/t/source/document.bin",
            },
            600,
        ),
        (
            "put_object",
            {
                "Bucket": "derived-private",
                "Key": "tenants/t/derived/invocations/i/result.json",
                "ContentType": "application/json",
            },
            600,
        ),
    ]


@pytest.mark.parametrize("expires", [0, 1801])
async def test_s3_gpu_grants_reject_unbounded_lifetimes(expires: int) -> None:
    store = S3ObjectStore.__new__(S3ObjectStore)
    store.settings = cast(
        Any,
        SimpleNamespace(
            s3_bucket_quarantine="quarantine-private",
            s3_bucket_source="source-private",
            s3_bucket_working="working-private",
            s3_bucket_derived="derived-private",
            s3_bucket_exports="exports-private",
            s3_bucket_audit="audit-private",
        ),
    )
    store.client = cast(Any, FakePresignClient())

    with pytest.raises(ValueError, match=r"1\.\.1800"):
        await store.create_gpu_input_target(
            bucket="source",
            object_key="tenants/t/source/document.bin",
            expires=expires,
        )
    with pytest.raises(ValueError, match=r"1\.\.1800"):
        await store.create_gpu_output_target(
            object_key="tenants/t/derived/result.json",
            expires=expires,
        )
