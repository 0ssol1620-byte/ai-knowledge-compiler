"""Regression evidence for the long-lived SSE transaction boundary."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from akc_api.main import stream_events
from akc_api.security import Principal


async def test_stream_releases_dependency_transaction_before_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid.uuid4()
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    session = AsyncMock()
    job = SimpleNamespace(
        id=job_id,
        project_id=project_id,
        document_id=document_id,
    )

    async def tenant_job(*_: object, **__: object) -> SimpleNamespace:
        return job

    monkeypatch.setattr("akc_api.main._tenant_job", tenant_job)
    principal = Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        roles=frozenset({"owner"}),
        scopes=frozenset({"api:read", "api:write"}),
        auth_type="cookie",
    )

    response = await stream_events(
        job_id=job_id,
        request=SimpleNamespace(),
        principal=principal,
        session=session,
    )

    session.commit.assert_awaited_once_with()
    await response.body_iterator.aclose()
