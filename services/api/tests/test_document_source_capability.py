from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from akc_api import main
from akc_api.security import Principal
from akc_api.storage import UploadTarget
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession


class ScalarSession:
    def __init__(self, *values: Any) -> None:
        self.values = list(values)

    async def scalar(self, _statement: Any) -> Any:
        return self.values.pop(0)


class RecordingStore:
    def __init__(self) -> None:
        self.call: dict[str, Any] | None = None

    async def create_gpu_input_target(self, **kwargs: Any) -> UploadTarget:
        self.call = kwargs
        return UploadTarget(url="https://source.example/signed", headers={})


def principal(tenant_id: uuid.UUID) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        roles=frozenset({"owner"}),
        scopes=frozenset({"api:read"}),
        auth_type="api_key",
    )


@pytest.mark.asyncio
async def test_source_capability_requires_active_sanitized_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    source_file_id = uuid.uuid4()
    version = SimpleNamespace(
        id=version_id,
        document_id=document_id,
        version=3,
        status="source_verified",
        source_file_id=source_file_id,
    )
    source_file = SimpleNamespace(
        cdr_status="sanitized",
        sanitized_storage_key="tenant/sanitized.pdf",
    )
    document = SimpleNamespace(active_version=3)
    store = RecordingStore()

    async def tenant_document(*_args: Any, **_kwargs: Any) -> Any:
        return document

    monkeypatch.setattr(main, "_tenant_document", tenant_document)
    request = cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    settings=SimpleNamespace(presigned_download_ttl_seconds=900),
                    object_store=store,
                )
            )
        ),
    )
    response = await main.get_document_version_source_capability(
        version_id,
        request,
        principal(tenant_id),
        cast(AsyncSession, ScalarSession(version, source_file)),
    )

    assert response["read_url"] == "https://source.example/signed"
    assert response["expires_in_seconds"] == 300
    assert store.call == {
        "bucket": "source",
        "object_key": "tenant/sanitized.pdf",
        "expires": 300,
    }


@pytest.mark.asyncio
async def test_source_capability_fails_closed_before_cdr(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    version = SimpleNamespace(
        id=version_id,
        document_id=document_id,
        version=1,
        status="source_verified",
        source_file_id=uuid.uuid4(),
    )
    source_file = SimpleNamespace(cdr_status="not_requested", sanitized_storage_key=None)

    async def tenant_document(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(active_version=1)

    monkeypatch.setattr(main, "_tenant_document", tenant_document)
    request = cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    settings=SimpleNamespace(presigned_download_ttl_seconds=300),
                    object_store=RecordingStore(),
                )
            )
        ),
    )
    with pytest.raises(HTTPException) as raised:
        await main.get_document_version_source_capability(
            version_id,
            request,
            principal(tenant_id),
            cast(AsyncSession, ScalarSession(version, source_file)),
        )

    assert raised.value.status_code == 409
    assert raised.value.detail == {"code": "SANITIZED_SOURCE_NOT_AVAILABLE"}
