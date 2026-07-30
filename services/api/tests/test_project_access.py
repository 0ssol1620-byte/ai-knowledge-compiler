"""Project ACL isolation, role-intersection, API-key, and audit evidence."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import AuditEvent, Document
from akc_api.project_access_models import ProjectMembership
from akc_api.settings import Settings
from sqlalchemy import select

_SUPPORT_KEY = "project-access-test-support-key"
_PASSWORD = "correct horse battery staple"  # noqa: S105


@pytest_asyncio.fixture
async def project_api(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'project-access.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
        test_support_key=_SUPPORT_KEY,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client, app


async def _capture_token(client: httpx.AsyncClient, email: str) -> str:
    response = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _SUPPORT_KEY},
        json={"email": email},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


async def _register_owner(
    client: httpx.AsyncClient,
    *,
    email: str = "project.owner@example.com",
    tenant_name: str = "Project ACL Workspace",
) -> dict[str, Any]:
    registered = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "display_name": "Project Owner",
            "tenant_name": tenant_name,
        },
    )
    assert registered.status_code == 201, registered.text
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": await _capture_token(client, email)},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def _accept_member(
    owner_client: httpx.AsyncClient,
    app: Any,
    *,
    email: str,
    role: str,
) -> tuple[httpx.AsyncClient, dict[str, Any]]:
    invitation = await owner_client.post(
        "/v1/team/invitations",
        headers={"Idempotency-Key": f"invite-{role}"},
        json={"email": email, "role": role},
    )
    assert invitation.status_code == 201, invitation.text
    token = await _capture_token(owner_client, email)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    )
    accepted = await client.post(
        "/v1/team/invitations/accept",
        json={
            "token": token,
            "email": email,
            "password": _PASSWORD,
            "display_name": "Project Member",
        },
    )
    assert accepted.status_code == 200, accepted.text
    return client, accepted.json()


async def test_project_acl_intersection_api_key_revocation_and_audit(
    project_api: tuple[httpx.AsyncClient, Any],
) -> None:
    owner_client, app = project_api
    owner = await _register_owner(owner_client)
    project_a = await owner_client.post(
        "/v1/projects",
        headers={"Idempotency-Key": "create-project-a"},
        json={"name": "Project A"},
    )
    project_b = await owner_client.post(
        "/v1/projects",
        headers={"Idempotency-Key": "create-project-b"},
        json={"name": "Project B"},
    )
    assert project_a.status_code == project_b.status_code == 201
    project_a_id = project_a.json()["id"]
    project_b_id = project_b.json()["id"]
    document_a_id = uuid.uuid4()
    document_b_id = uuid.uuid4()
    async with app.state.database.sessions() as session:
        session.add_all(
            [
                Document(
                    id=document_a_id,
                    tenant_id=uuid.UUID(owner["tenant_id"]),
                    project_id=uuid.UUID(project_a_id),
                    title="Visible document",
                    document_type="txt",
                    status="COMPLETED",
                ),
                Document(
                    id=document_b_id,
                    tenant_id=uuid.UUID(owner["tenant_id"]),
                    project_id=uuid.UUID(project_b_id),
                    title="Hidden document",
                    document_type="txt",
                    status="COMPLETED",
                ),
            ]
        )
        await session.commit()

    member_client, member = await _accept_member(
        owner_client,
        app,
        email="project.member@example.com",
        role="admin",
    )
    try:
        api_key = await member_client.post(
            "/v1/api-keys",
            headers={"Idempotency-Key": "member-api-key"},
            json={
                "name": "member-project-key",
                "scopes": ["api:read", "api:write"],
            },
        )
        assert api_key.status_code == 201, api_key.text
        raw_key = api_key.json()["key"]

        demoted = await owner_client.patch(
            f"/v1/team/members/{member['user_id']}",
            headers={"Idempotency-Key": "member-to-editor"},
            json={"role": "editor"},
        )
        assert demoted.status_code == 200, demoted.text

        grant_payload = {"user_id": member["user_id"], "role": "viewer"}
        granted = await owner_client.post(
            f"/v1/projects/{project_a_id}/members",
            headers={"Idempotency-Key": "grant-a-viewer"},
            json=grant_payload,
        )
        replayed = await owner_client.post(
            f"/v1/projects/{project_a_id}/members",
            headers={"Idempotency-Key": "grant-a-viewer"},
            json=grant_payload,
        )
        assert granted.status_code == replayed.status_code == 201
        assert replayed.json() == granted.json()

        listed = await member_client.get("/v1/projects")
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()] == [project_a_id]
        assert (await member_client.get(f"/v1/projects/{project_a_id}")).status_code == 200
        hidden = await member_client.get(f"/v1/projects/{project_b_id}")
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "PROJECT_NOT_FOUND"
        assert (await member_client.get(f"/v1/documents/{document_a_id}")).status_code == 200
        assert (await member_client.get(f"/v1/documents/{document_b_id}")).status_code == 404

        denied_write = await member_client.patch(
            f"/v1/projects/{project_a_id}",
            headers={"Idempotency-Key": "viewer-cannot-write"},
            json={"description": "must not be stored"},
        )
        assert denied_write.status_code == 403
        assert denied_write.json()["error"]["code"] == "PROJECT_PERMISSION_DENIED"
        assert (await member_client.get(f"/v1/projects/{project_a_id}/members")).status_code == 403

        key_headers = {"Authorization": f"Bearer {raw_key}"}
        key_projects = await owner_client.get("/v1/projects", headers=key_headers)
        assert [row["id"] for row in key_projects.json()] == [project_a_id]
        key_denied = await owner_client.patch(
            f"/v1/projects/{project_a_id}",
            headers={
                **key_headers,
                "Idempotency-Key": "key-viewer-cannot-write",
            },
            json={"description": "must not be stored by key"},
        )
        assert key_denied.status_code == 403

        elevated = await owner_client.patch(
            f"/v1/projects/{project_a_id}/members/{member['user_id']}",
            headers={"Idempotency-Key": "project-member-to-editor"},
            json={"role": "editor"},
        )
        assert elevated.status_code == 200, elevated.text
        allowed_write = await member_client.patch(
            f"/v1/projects/{project_a_id}",
            headers={"Idempotency-Key": "editor-can-write"},
            json={"description": "editor update"},
        )
        assert allowed_write.status_code == 200, allowed_write.text

        tenant_downgrade = await owner_client.patch(
            f"/v1/team/members/{member['user_id']}",
            headers={"Idempotency-Key": "member-to-reviewer"},
            json={"role": "reviewer"},
        )
        assert tenant_downgrade.status_code == 200, tenant_downgrade.text
        intersection_denied = await owner_client.patch(
            f"/v1/projects/{project_a_id}",
            headers={
                **key_headers,
                "Idempotency-Key": "key-intersection-denied",
            },
            json={"description": "tenant role must cap project role"},
        )
        assert intersection_denied.status_code == 403

        escalation = await owner_client.post(
            f"/v1/projects/{project_b_id}/members",
            headers={"Idempotency-Key": "reviewer-cannot-project-editor"},
            json={"user_id": member["user_id"], "role": "editor"},
        )
        assert escalation.status_code == 403
        assert escalation.json()["error"]["code"] == "PROJECT_ROLE_ESCALATION_DENIED"

        revoked = await owner_client.delete(
            f"/v1/projects/{project_a_id}/members/{member['user_id']}",
            headers={"Idempotency-Key": "revoke-project-member"},
        )
        assert revoked.status_code == 204
        assert (await member_client.get(f"/v1/projects/{project_a_id}")).status_code == 404
        assert (
            await owner_client.get(
                f"/v1/projects/{project_a_id}",
                headers=key_headers,
            )
        ).status_code == 404

        owner_revoke = await owner_client.delete(
            f"/v1/projects/{project_a_id}/members/{owner['user_id']}",
            headers={"Idempotency-Key": "cannot-revoke-implicit-owner"},
        )
        assert owner_revoke.status_code == 403
        assert owner_revoke.json()["error"]["code"] == "PROJECT_ACCESS_IMPLICIT_ADMIN"
    finally:
        await member_client.aclose()

    other_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    )
    try:
        other_owner = await _register_owner(
            other_client,
            email="other.workspace.owner@example.com",
            tenant_name="Other Workspace",
        )
        cross_tenant = await owner_client.post(
            f"/v1/projects/{project_a_id}/members",
            headers={"Idempotency-Key": "cross-tenant-grant-denied"},
            json={"user_id": other_owner["user_id"], "role": "viewer"},
        )
        assert cross_tenant.status_code == 404
        assert cross_tenant.json()["error"]["code"] == "TEAM_MEMBER_NOT_FOUND"
    finally:
        await other_client.aclose()

    async with app.state.database.sessions() as session:
        explicit_member = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == uuid.UUID(project_a_id),
                ProjectMembership.user_id == uuid.UUID(member["user_id"]),
            )
        )
        owner_membership = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == uuid.UUID(project_a_id),
                ProjectMembership.user_id == uuid.UUID(owner["user_id"]),
            )
        )
        access_audits = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action.in_(
                        {
                            "project.member_granted",
                            "project.member_role_changed",
                            "project.member_revoked",
                        }
                    )
                )
            )
        )
    assert explicit_member is None
    assert owner_membership is not None
    assert owner_membership.role == "editor"
    assert [event.action for event in access_audits] == [
        "project.member_granted",
        "project.member_role_changed",
        "project.member_revoked",
    ]
    for event in access_audits:
        assert set(event.metadata_json) <= {"project_id", "user_id", "role"}
        assert "description" not in event.metadata_json
