"""HTTP contract and immediate-access fences for asynchronous deletion."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import DeletionRequest, Document
from akc_api.settings import Settings


@pytest_asyncio.fixture
async def api_without_deletion_worker(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'deletion-api.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client, app


async def _register(
    client: httpx.AsyncClient,
    app: Any,
    *,
    email: str,
    tenant_name: str,
) -> dict[str, Any]:
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": "Deletion Owner",
            "tenant_name": tenant_name,
        },
    )
    assert response.status_code == 201, response.text
    capture = app.state.verification_capture
    assert capture is not None
    message = await capture.take_for(email)
    assert message is not None
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": message.token},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["email_verified"] is True
    return verified.json()


async def _create_project_and_document(
    client: httpx.AsyncClient,
    *,
    suffix: str,
) -> tuple[str, str]:
    project = await client.post("/v1/projects", json={"name": f"Deletion {suffix}"})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    document = await client.post(
        "/v1/documents",
        json={"project_id": project_id, "title": f"Document {suffix}"},
    )
    assert document.status_code == 201, document.text
    return project_id, document.json()["id"]


async def test_delete_is_idempotent_async_and_tombstones_every_document_access(
    api_without_deletion_worker: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = api_without_deletion_worker
    await _register(
        client,
        app,
        email="deletion-owner@example.com",
        tenant_name="Deletion Owner",
    )
    project_id, first_document_id = await _create_project_and_document(
        client,
        suffix="One",
    )
    _, second_document_id = await _create_project_and_document(
        client,
        suffix="Two",
    )

    accepted = await client.delete(
        f"/v1/documents/{first_document_id}",
        headers={"Idempotency-Key": "delete-document-once"},
    )
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert body["state"] == "requested"
    assert body["receipt"] is None
    assert body["deleted_count"] == 0
    assert body["status_url"] == f"/v1/deletions/{body['id']}"

    replay = await client.delete(
        f"/v1/documents/{first_document_id}",
        headers={"Idempotency-Key": "delete-document-once"},
    )
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == body["id"]

    conflict = await client.delete(
        f"/v1/documents/{second_document_id}",
        headers={"Idempotency-Key": "delete-document-once"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    status = await client.get(body["status_url"])
    assert status.status_code == 200
    assert status.json()["state"] == "requested"
    assert status.json()["receipt"] is None

    denied_calls = (
        await client.get(f"/v1/documents/{first_document_id}"),
        await client.get(f"/v1/documents/{first_document_id}/estimate"),
        await client.get(f"/v1/documents/{first_document_id}/pages"),
        await client.get(f"/v1/documents/{first_document_id}/blocks"),
        await client.post(f"/v1/documents/{first_document_id}/analyze"),
        await client.post(
            f"/v1/documents/{first_document_id}/compile",
            json={},
            headers={"Idempotency-Key": "compile-after-delete"},
        ),
    )
    assert {response.status_code for response in denied_calls} == {404}

    listed_projects = await client.get("/v1/projects")
    assert listed_projects.status_code == 200
    assert project_id in {row["id"] for row in listed_projects.json()}

    request_id = uuid.UUID(body["id"])
    async with app.state.database.sessions() as session:
        deletion_request = await session.get(DeletionRequest, request_id)
        tombstoned_document = await session.get(Document, uuid.UUID(first_document_id))
    assert deletion_request is not None
    assert deletion_request.manifest_hash == body["manifest_hash"]
    assert deletion_request.manifest["target"]["id"] == first_document_id
    assert deletion_request.manifest["schema_version"] == "1.0"
    assert deletion_request.completed_at is None
    assert tombstoned_document is not None
    assert tombstoned_document.deletion_requested_at is not None

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as other_tenant:
        await _register(
            other_tenant,
            app,
            email="deletion-other@example.com",
            tenant_name="Deletion Other",
        )
        hidden = await other_tenant.get(body["status_url"])
        assert hidden.status_code == 404


async def test_project_tombstone_hides_project_children_and_jobs_immediately(
    api_without_deletion_worker: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = api_without_deletion_worker
    await _register(
        client,
        app,
        email="project-delete@example.com",
        tenant_name="Project Delete",
    )
    project_id, document_id = await _create_project_and_document(
        client,
        suffix="Cascade",
    )

    accepted = await client.delete(
        f"/v1/projects/{project_id}",
        headers={"Idempotency-Key": "delete-project-once"},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["target_type"] == "project"
    assert accepted.json()["receipt"] is None

    assert (await client.get(f"/v1/projects/{project_id}")).status_code == 404
    assert (await client.get(f"/v1/documents/{document_id}")).status_code == 404
    listed = await client.get("/v1/projects")
    assert listed.status_code == 200
    assert project_id not in {row["id"] for row in listed.json()}
