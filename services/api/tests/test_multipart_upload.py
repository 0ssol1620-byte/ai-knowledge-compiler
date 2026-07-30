"""Browser-direct multipart upload security and recovery evidence."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any, BinaryIO, cast

import httpx
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import SourceFile, UploadSession, utcnow
from akc_api.settings import Settings
from akc_api.storage import (
    CompletedPart,
    MultipartPartTarget,
    MultipartSession,
    MultipartUploadNotFoundError,
    ObjectMetadata,
    S3ObjectStore,
    UploadedPart,
    UploadTarget,
)
from botocore.exceptions import ClientError
from sqlalchemy import select

_TEST_SUPPORT_KEY = "multipart-verification-support-key"


class FakeMultipartStore:
    """In-memory provider double that never routes file bytes through FastAPI."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.quarantine: dict[str, bytes] = {}
        self.sources: dict[str, bytes] = {}
        self.exports: dict[str, bytes] = {}
        self.abort_calls: list[str] = []
        self.created_keys: list[str] = []

    async def create_upload_target(
        self,
        *,
        upload_id: str,
        object_key: str,
        content_type: str,
        expected_sha256: str,
        expires: int,
    ) -> UploadTarget:
        del upload_id, object_key, content_type, expected_sha256, expires
        raise AssertionError("multipart test must not create a single PUT target")

    async def create_multipart_upload(
        self,
        *,
        object_key: str,
        content_type: str,
        expected_sha256: str,
    ) -> MultipartSession:
        provider_id = f"provider-{len(self.sessions) + 1}"
        self.sessions[provider_id] = {
            "object_key": object_key,
            "content_type": content_type,
            "expected_sha256": expected_sha256,
            "parts": {},
        }
        self.created_keys.append(object_key)
        return MultipartSession(provider_upload_id=provider_id)

    async def create_multipart_part_target(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        part_number: int,
        expires: int,
    ) -> MultipartPartTarget:
        session = self._session(provider_upload_id)
        assert session["object_key"] == object_key
        assert 0 < expires <= 600
        return MultipartPartTarget(
            part_number=part_number,
            url=f"https://objects.invalid/upload/{provider_upload_id}/{part_number}",
            headers={},
        )

    async def list_multipart_parts(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
    ) -> list[UploadedPart]:
        session = self._session(provider_upload_id)
        assert session["object_key"] == object_key
        return [
            UploadedPart(
                part_number=part_number,
                etag=value["etag"],
                size_bytes=len(value["data"]),
            )
            for part_number, value in sorted(session["parts"].items())
        ]

    async def complete_multipart_upload(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        parts: list[CompletedPart],
    ) -> None:
        session = self._session(provider_upload_id)
        assert session["object_key"] == object_key
        assembled = bytearray()
        for part in parts:
            value = session["parts"][part.part_number]
            assert part.etag == value["etag"]
            assembled.extend(value["data"])
        self.quarantine[object_key] = bytes(assembled)
        del self.sessions[provider_upload_id]

    async def abort_multipart_upload(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
    ) -> None:
        session = self.sessions.get(provider_upload_id)
        if session is None:
            raise MultipartUploadNotFoundError
        assert session["object_key"] == object_key
        self.abort_calls.append(provider_upload_id)
        del self.sessions[provider_upload_id]

    async def put_quarantine(self, object_key: str, data: bytes) -> None:
        self.quarantine[object_key] = data

    async def put_quarantine_stream(
        self,
        object_key: str,
        stream: BinaryIO,
    ) -> None:
        self.quarantine[object_key] = stream.read()

    async def read_quarantine(self, object_key: str) -> bytes:
        return self.quarantine[object_key]

    async def download_quarantine(
        self,
        object_key: str,
        stream: BinaryIO,
    ) -> None:
        stream.write(self.quarantine[object_key])
        stream.seek(0)

    async def head_quarantine(self, object_key: str) -> ObjectMetadata:
        data = self.quarantine[object_key]
        matching_session = next(
            (session for session in self.sessions.values() if session["object_key"] == object_key),
            None,
        )
        content_type = str(matching_session["content_type"]) if matching_session else "text/plain"
        return ObjectMetadata(
            size_bytes=len(data),
            content_type=content_type,
            # Deliberately not a raw-object digest. Multipart finalization must
            # ignore provider composites and stream the real object instead.
            checksum_sha256="provider-composite-checksum",
        )

    async def promote_source(self, quarantine_key: str, source_key: str) -> None:
        self.sources.setdefault(source_key, self.quarantine[quarantine_key])

    async def read_source(self, source_key: str) -> bytes:
        return self.sources[source_key]

    async def download_source(self, source_key: str, stream: BinaryIO) -> None:
        stream.write(self.sources[source_key])
        stream.seek(0)

    async def put_export(self, object_key: str, data: bytes) -> None:
        self.exports[object_key] = data

    async def read_export(self, object_key: str) -> bytes:
        return self.exports[object_key]

    async def delete(self, bucket: str, object_key: str) -> bool:
        collection = {
            "quarantine": self.quarantine,
            "source": self.sources,
            "exports": self.exports,
            "working": {},
            "derived": {},
            "audit": {},
        }[bucket]
        return collection.pop(object_key, None) is not None

    def put_part(self, provider_upload_id: str, part_number: int, data: bytes) -> str:
        session = self._session(provider_upload_id)
        etag = hashlib.sha256(data).hexdigest()[:32]
        session["parts"][part_number] = {"data": data, "etag": etag}
        return etag

    def _session(self, provider_upload_id: str) -> dict[str, Any]:
        try:
            return self.sessions[provider_upload_id]
        except KeyError as exc:
            raise MultipartUploadNotFoundError from exc


@pytest_asyncio.fixture
async def multipart_api(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, FakeMultipartStore]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'multipart.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=True,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
        test_support_key=_TEST_SUPPORT_KEY,
    )
    app = create_app(settings)
    store = FakeMultipartStore()
    settings.object_store_driver = "s3"
    settings.multipart_upload_threshold_bytes = 5
    settings.multipart_part_size_bytes = 5
    settings.multipart_max_parts = 10
    settings.multipart_presign_batch_size = 2
    app.state.object_store = store
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client, app, store


async def _register(
    client: httpx.AsyncClient,
    email: str,
    tenant_name: str,
) -> dict[str, Any]:
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": "Multipart Owner",
            "tenant_name": tenant_name,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["email_verified"] is False
    captured = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _TEST_SUPPORT_KEY},
        json={"email": email},
    )
    assert captured.status_code == 200
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": captured.json()["token"]},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def _initiate(
    client: httpx.AsyncClient,
    content: bytes,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    response = await client.post(
        "/v1/uploads/initiate",
        json={
            "filename": "evidence.txt",
            "size": len(content),
            "content_type": "text/plain",
            "sha256": expected_sha256 or hashlib.sha256(content).hexdigest(),
        },
    )
    assert response.status_code == 201, response.text
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()


def _upload_all_parts(
    store: FakeMultipartStore,
    provider_id: str,
    content: bytes,
    part_size: int = 5,
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for index, offset in enumerate(range(0, len(content), part_size), start=1):
        etag = store.put_part(
            provider_id,
            index,
            content[offset : offset + part_size],
        )
        parts.append({"part_number": index, "etag": etag})
    return parts


async def test_multipart_happy_path_is_direct_verified_and_idempotent(
    multipart_api: tuple[httpx.AsyncClient, Any, FakeMultipartStore],
) -> None:
    client, app, store = multipart_api
    await _register(client, "owner@example.com", "Multipart Evidence")
    content = b"direct multipart evidence"
    initiated = await _initiate(client, content)

    assert initiated["method"] == "MULTIPART"
    assert initiated["upload_url"] is None
    assert initiated["headers"] == {}
    assert initiated["multipart"] == {
        "part_size": 5,
        "part_count": 5,
        "presign_batch_size": 2,
        "max_concurrency": 4,
        "max_retries": 3,
        "sign_parts_url": f"/v1/uploads/{initiated['upload_id']}/parts/sign",
        "list_parts_url": f"/v1/uploads/{initiated['upload_id']}/parts",
    }
    assert "evidence.txt" not in store.created_keys[0]
    assert "/uploads/" in store.created_keys[0]

    signed = await client.post(
        initiated["multipart"]["sign_parts_url"],
        json={"part_numbers": [2, 1]},
    )
    assert signed.status_code == 200, signed.text
    assert signed.headers["Cache-Control"] == "no-store"
    assert [part["part_number"] for part in signed.json()["parts"]] == [1, 2]
    assert all(
        part["upload_url"].startswith("https://objects.invalid/") for part in signed.json()["parts"]
    )

    provider_id = next(iter(store.sessions))
    completed_parts = _upload_all_parts(store, provider_id, content)
    listed = await client.get(initiated["multipart"]["list_parts_url"])
    assert listed.status_code == 200, listed.text
    assert [part["part_number"] for part in listed.json()["parts"]] == [1, 2, 3, 4, 5]

    completed = await client.post(
        f"/v1/uploads/{initiated['upload_id']}/complete",
        json={
            "sha256": hashlib.sha256(content).hexdigest(),
            "parts": completed_parts,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "SECURITY_VERIFIED"
    assert store.quarantine == {}
    assert list(store.sources.values()) == [content]

    completed_again = await client.post(
        f"/v1/uploads/{initiated['upload_id']}/complete",
        json={"sha256": hashlib.sha256(content).hexdigest(), "parts": []},
    )
    assert completed_again.status_code == 200
    assert completed_again.json()["source_file_id"] == completed.json()["source_file_id"]
    async with app.state.database.sessions() as session:
        sources = list(await session.scalars(select(SourceFile)))
    assert len(sources) == 1


async def test_multipart_rejects_order_count_etag_and_batch_violations(
    multipart_api: tuple[httpx.AsyncClient, Any, FakeMultipartStore],
) -> None:
    client, _, store = multipart_api
    await _register(client, "owner@example.com", "Multipart Validation")
    content = b"strict part ordering"
    initiated = await _initiate(client, content)
    provider_id = next(iter(store.sessions))
    parts = _upload_all_parts(store, provider_id, content)
    complete_url = f"/v1/uploads/{initiated['upload_id']}/complete"

    too_many = await client.post(
        initiated["multipart"]["sign_parts_url"],
        json={"part_numbers": [1, 2, 3]},
    )
    assert too_many.status_code == 422
    assert too_many.json()["error"]["code"] == "PART_BATCH_TOO_LARGE"
    out_of_range = await client.post(
        initiated["multipart"]["sign_parts_url"],
        json={"part_numbers": [99]},
    )
    assert out_of_range.status_code == 422
    assert out_of_range.json()["error"]["code"] == "PART_NUMBER_OUT_OF_RANGE"

    reversed_parts = await client.post(
        complete_url,
        json={"parts": list(reversed(parts))},
    )
    assert reversed_parts.status_code == 422
    assert reversed_parts.json()["error"]["code"] == "MULTIPART_PARTS_NOT_CONTIGUOUS"
    missing_part = await client.post(
        complete_url,
        json={"parts": parts[:-1]},
    )
    assert missing_part.status_code == 422
    assert missing_part.json()["error"]["code"] == "MULTIPART_PARTS_NOT_CONTIGUOUS"
    wrong_etag = [*parts]
    wrong_etag[0] = {"part_number": 1, "etag": "0" * 32}
    mismatch = await client.post(complete_url, json={"parts": wrong_etag})
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "MULTIPART_ETAG_MISMATCH"
    assert provider_id in store.sessions


async def test_multipart_ownership_expiry_and_abort_are_fail_closed(
    multipart_api: tuple[httpx.AsyncClient, Any, FakeMultipartStore],
) -> None:
    owner, app, store = multipart_api
    owner_session = await _register(owner, "owner@example.com", "Owner Tenant")
    content = b"tenant scoped upload"
    initiated = await _initiate(owner, content)
    provider_id = next(iter(store.sessions))
    store.put_part(provider_id, 1, content[:5])

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as intruder:
        await _register(intruder, "intruder@example.com", "Intruder Tenant")
        for method, path, payload in (
            ("GET", f"/v1/uploads/{initiated['upload_id']}", None),
            ("GET", initiated["multipart"]["list_parts_url"], None),
            (
                "POST",
                initiated["multipart"]["sign_parts_url"],
                {"part_numbers": [1]},
            ),
            ("POST", f"/v1/uploads/{initiated['upload_id']}/abort", None),
        ):
            response = await intruder.request(method, path, json=payload)
            assert response.status_code == 404

    async with app.state.database.sessions() as session:
        upload = await session.scalar(
            select(UploadSession).where(
                UploadSession.tenant_id == uuid.UUID(owner_session["tenant_id"]),
                UploadSession.id == uuid.UUID(initiated["upload_id"]),
            )
        )
        assert upload is not None
        upload.expires_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    expired = await owner.post(
        initiated["multipart"]["sign_parts_url"],
        json={"part_numbers": [1]},
    )
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "UPLOAD_EXPIRED"
    assert provider_id not in store.sessions
    assert store.abort_calls == [provider_id]
    # Both explicit abort calls are terminal no-ops after expiry.
    abort_url = f"/v1/uploads/{initiated['upload_id']}/abort"
    assert (await owner.post(abort_url)).status_code == 204
    assert (await owner.post(abort_url)).status_code == 204


async def test_multipart_finalization_streams_actual_sha_before_promotion(
    multipart_api: tuple[httpx.AsyncClient, Any, FakeMultipartStore],
) -> None:
    client, _, store = multipart_api
    await _register(client, "owner@example.com", "Checksum Tenant")
    expected = b"expected file bytes"
    tampered = b"tampered file bytes"
    assert len(expected) == len(tampered)
    initiated = await _initiate(
        client,
        expected,
        expected_sha256=hashlib.sha256(expected).hexdigest(),
    )
    provider_id = next(iter(store.sessions))
    parts = _upload_all_parts(store, provider_id, tampered)

    completed = await client.post(
        f"/v1/uploads/{initiated['upload_id']}/complete",
        json={
            "sha256": hashlib.sha256(expected).hexdigest(),
            "parts": parts,
        },
    )
    assert completed.status_code == 422
    assert completed.json()["error"]["code"] == "CHECKSUM_MISMATCH"
    assert store.quarantine == {}
    assert store.sources == {}


async def test_multipart_recovers_provider_ack_loss_and_abort_is_idempotent(
    multipart_api: tuple[httpx.AsyncClient, Any, FakeMultipartStore],
) -> None:
    client, _, store = multipart_api
    await _register(client, "owner@example.com", "Recovery Tenant")
    content = b"provider completed object"
    initiated = await _initiate(client, content)
    provider_id = next(iter(store.sessions))
    _upload_all_parts(store, provider_id, content)
    object_key = str(store.sessions[provider_id]["object_key"])
    # Simulate the provider committing the object while the control plane loses
    # the completion ACK before it can persist `uploaded`.
    store.quarantine[object_key] = content
    del store.sessions[provider_id]
    resumed = await client.get(initiated["multipart"]["list_parts_url"])
    assert resumed.status_code == 200, resumed.text
    assert resumed.json() == {
        "upload_id": initiated["upload_id"],
        "parts": [],
        "assembly_completed": True,
    }
    recovered = await client.post(
        f"/v1/uploads/{initiated['upload_id']}/complete",
        json={"sha256": hashlib.sha256(content).hexdigest(), "parts": []},
    )
    assert recovered.status_code == 200, recovered.text
    assert list(store.sources.values()) == [content]

    second = await _initiate(client, b"abort partial upload")
    second_provider_id = next(iter(store.sessions))
    store.put_part(second_provider_id, 1, b"abort")
    abort_url = f"/v1/uploads/{second['upload_id']}/abort"
    assert (await client.post(abort_url)).status_code == 204
    assert (await client.post(abort_url)).status_code == 204
    assert second_provider_id not in store.sessions
    assert store.abort_calls == [second_provider_id]


class FakeS3Client:
    def __init__(self) -> None:
        self.list_markers: list[int] = []
        self.completed: dict[str, Any] | None = None
        self.aborted = False

    def create_multipart_upload(self, **kwargs: Any) -> dict[str, str]:
        assert kwargs["ContentType"] == "application/pdf"
        assert kwargs["Metadata"] == {"expected-sha256": "a" * 64}
        return {"UploadId": "opaque-provider-id"}

    def generate_presigned_url(
        self,
        operation: str,
        *,
        Params: dict[str, Any],
        ExpiresIn: int,
    ) -> str:
        assert operation == "upload_part"
        assert Params["UploadId"] == "opaque-provider-id"
        assert ExpiresIn == 300
        return "https://signed.invalid/redacted"

    def list_parts(self, **kwargs: Any) -> dict[str, Any]:
        marker = int(kwargs["PartNumberMarker"])
        self.list_markers.append(marker)
        if marker == 0:
            return {
                "IsTruncated": True,
                "NextPartNumberMarker": 1,
                "Parts": [
                    {
                        "PartNumber": 1,
                        "ETag": f'"{"a" * 32}"',
                        "Size": 5,
                    }
                ],
            }
        return {
            "IsTruncated": False,
            "Parts": [
                {
                    "PartNumber": 2,
                    "ETag": f'"{"b" * 32}"',
                    "Size": 3,
                }
            ],
        }

    def complete_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.completed = kwargs
        return {}

    def abort_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        if self.aborted:
            raise ClientError(
                {"Error": {"Code": "NoSuchUpload", "Message": "gone"}},
                "AbortMultipartUpload",
            )
        self.aborted = True
        return {}


async def test_s3_adapter_scopes_calls_and_handles_provider_idempotency() -> None:
    settings = Settings(
        object_store_driver="s3",
        s3_use_ambient_credentials=False,
        s3_access_key_id="test-access-key",
        s3_secret_access_key="test-secret-key",  # noqa: S106
    )
    store = S3ObjectStore(settings)
    fake = FakeS3Client()
    store.client = cast(Any, fake)

    created = await store.create_multipart_upload(
        object_key="tenants/t/projects/p/uploads/u/original.bin",
        content_type="application/pdf",
        expected_sha256="a" * 64,
    )
    assert created.provider_upload_id == "opaque-provider-id"
    target = await store.create_multipart_part_target(
        object_key="tenants/t/projects/p/uploads/u/original.bin",
        provider_upload_id=created.provider_upload_id,
        part_number=1,
        expires=300,
    )
    assert target.url == "https://signed.invalid/redacted"
    listed = await store.list_multipart_parts(
        object_key="tenants/t/projects/p/uploads/u/original.bin",
        provider_upload_id=created.provider_upload_id,
    )
    assert fake.list_markers == [0, 1]
    assert [(part.part_number, part.size_bytes) for part in listed] == [(1, 5), (2, 3)]
    await store.complete_multipart_upload(
        object_key="tenants/t/projects/p/uploads/u/original.bin",
        provider_upload_id=created.provider_upload_id,
        parts=[
            CompletedPart(part_number=1, etag="a" * 32),
            CompletedPart(part_number=2, etag="b" * 32),
        ],
    )
    assert fake.completed is not None
    assert fake.completed["MultipartUpload"]["Parts"] == [
        {"ETag": f'"{"a" * 32}"', "PartNumber": 1},
        {"ETag": f'"{"b" * 32}"', "PartNumber": 2},
    ]
    await store.abort_multipart_upload(
        object_key="tenants/t/projects/p/uploads/u/original.bin",
        provider_upload_id=created.provider_upload_id,
    )
    # NoSuchUpload is a successful terminal outcome on retries.
    await store.abort_multipart_upload(
        object_key="tenants/t/projects/p/uploads/u/original.bin",
        provider_upload_id=created.provider_upload_id,
    )
