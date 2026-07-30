"""Security and tenant-boundary tests for Phase 9 team collaboration."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import AuditEvent, Membership, Tenant
from akc_api.settings import Settings
from akc_api.team_api import TeamInvitationTokenCodec
from akc_api.team_models import TeamInvitation, TeamInvitationDelivery
from sqlalchemy import func, select

_SUPPORT_KEY = "team-collaboration-test-support-key"
_PASSWORD = "correct horse battery staple"  # noqa: S105


@pytest_asyncio.fixture
async def team_api(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'team.db').as_posix()}",
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


async def _register_verified(
    client: httpx.AsyncClient,
    *,
    email: str,
    tenant_name: str,
) -> dict[str, Any]:
    registered = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "display_name": email.split("@", 1)[0],
            "tenant_name": tenant_name,
        },
    )
    assert registered.status_code == 201, registered.text
    token = await _capture_token(client, email)
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": token},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def _invite(
    client: httpx.AsyncClient,
    *,
    email: str,
    role: str,
    key: str,
) -> tuple[dict[str, Any], str]:
    response = await client.post(
        "/v1/team/invitations",
        headers={"Idempotency-Key": key},
        json={"email": email, "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json(), await _capture_token(client, email)


async def test_invitation_token_is_encrypted_one_time_and_audited(
    team_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = team_api
    owner = await _register_verified(
        client,
        email="owner@example.com",
        tenant_name="Alpha Workspace",
    )
    invitation, token = await _invite(
        client,
        email="new.member@example.com",
        role="editor",
        key="invite-new-member",
    )

    replay = await client.post(
        "/v1/team/invitations",
        headers={"Idempotency-Key": "invite-new-member"},
        json={"email": "new.member@example.com", "role": "editor"},
    )
    assert replay.status_code == 201
    assert replay.json() == invitation

    cancelled_invite, cancelled_token = await _invite(
        client,
        email="cancelled@example.com",
        role="viewer",
        key="invite-to-cancel",
    )
    cancelled = await client.delete(
        f"/v1/team/invitations/{cancelled_invite['id']}",
        headers={"Idempotency-Key": "cancel-invitation"},
    )
    assert cancelled.status_code == 204
    cancelled_accept = await client.post(
        "/v1/team/invitations/accept",
        json={
            "token": cancelled_token,
            "email": "cancelled@example.com",
            "password": _PASSWORD,
            "display_name": "Cancelled",
        },
    )
    assert cancelled_accept.status_code == 400
    listed = await client.get("/v1/team/invitations")
    assert listed.status_code == 200
    listed_by_id = {item["id"]: item for item in listed.json()["items"]}
    assert listed_by_id[cancelled_invite["id"]]["status"] == "cancelled"

    async with app.state.database.sessions() as session:
        row = await session.get(TeamInvitation, uuid.UUID(invitation["id"]))
        delivery = await session.scalar(
            select(TeamInvitationDelivery).where(
                TeamInvitationDelivery.invitation_id == uuid.UUID(invitation["id"])
            )
        )
        assert row is not None
        assert delivery is not None
        assert row.token_hash == app.state.team_invitation_token_codec.digest(token)
        assert token not in repr(row)
        assert token.encode() not in delivery.encrypted_payload
        assert b"new.member@example.com" not in delivery.encrypted_payload

    mismatch = await client.post(
        "/v1/team/invitations/accept",
        json={
            "token": token,
            "email": "wrong@example.com",
            "password": _PASSWORD,
            "display_name": "Wrong",
        },
    )
    unknown = await client.post(
        "/v1/team/invitations/accept",
        json={
            "token": f"akci1.{uuid.UUID(owner['tenant_id']).hex}.{'x' * 43}",
            "email": "wrong@example.com",
            "password": _PASSWORD,
            "display_name": "Wrong",
        },
    )
    assert mismatch.status_code == unknown.status_code == 400
    assert mismatch.json()["error"]["code"] == unknown.json()["error"]["code"]

    accepted = await client.post(
        "/v1/team/invitations/accept",
        json={
            "token": token,
            "email": "new.member@example.com",
            "password": _PASSWORD,
            "display_name": "New Member",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["tenant_id"] == owner["tenant_id"]
    assert accepted.json()["roles"] == ["editor"]
    assert accepted.json()["email_verified"] is True

    reused = await client.post(
        "/v1/team/invitations/accept",
        json={
            "token": token,
            "email": "new.member@example.com",
            "password": _PASSWORD,
            "display_name": "New Member",
        },
    )
    assert reused.status_code == 400
    assert reused.json()["error"]["code"] == "INVALID_OR_EXPIRED_INVITATION"

    async with app.state.database.sessions() as session:
        assert (
            await session.scalar(
                select(func.count(Membership.user_id)).where(
                    Membership.tenant_id == uuid.UUID(owner["tenant_id"])
                )
            )
            == 2
        )
        actions = set(
            await session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.tenant_id == uuid.UUID(owner["tenant_id"]),
                    AuditEvent.action.like("team.%"),
                )
            )
        )
    assert {
        "team.invitation_created",
        "team.invitation_delivery",
        "team.invitation_accepted",
        "team.invitation_cancelled",
    }.issubset(actions)


async def test_role_hierarchy_self_protection_and_credential_revocation(
    team_api: tuple[httpx.AsyncClient, Any],
) -> None:
    owner_client, app = team_api
    owner = await _register_verified(
        owner_client,
        email="owner.roles@example.com",
        tenant_name="Roles Workspace",
    )
    _, admin_token = await _invite(
        owner_client,
        email="admin@example.com",
        role="admin",
        key="invite-admin",
    )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as admin_client:
        accepted = await admin_client.post(
            "/v1/team/invitations/accept",
            json={
                "token": admin_token,
                "email": "admin@example.com",
                "password": _PASSWORD,
                "display_name": "Admin",
            },
        )
        assert accepted.status_code == 200, accepted.text
        admin_id = accepted.json()["user_id"]

        forbidden_invite = await admin_client.post(
            "/v1/team/invitations",
            headers={"Idempotency-Key": "admin-cannot-create-owner"},
            json={"email": "owner2@example.com", "role": "owner"},
        )
        assert forbidden_invite.status_code == 403
        assert forbidden_invite.json()["error"]["code"] == "ROLE_ESCALATION_DENIED"

        forbidden_owner_change = await admin_client.patch(
            f"/v1/team/members/{owner['user_id']}",
            headers={"Idempotency-Key": "admin-cannot-demote-owner"},
            json={"role": "viewer"},
        )
        assert forbidden_owner_change.status_code == 403

        self_remove = await admin_client.delete(
            f"/v1/team/members/{admin_id}",
            headers={"Idempotency-Key": "admin-self-remove"},
        )
        assert self_remove.status_code == 409
        assert self_remove.json()["error"]["code"] == "SELF_MEMBERSHIP_CHANGE_DENIED"

        api_key = await admin_client.post(
            "/v1/api-keys",
            headers={"Idempotency-Key": "admin-api-key"},
            json={"name": "will-be-revoked", "scopes": ["api:read", "api:write"]},
        )
        assert api_key.status_code == 201, api_key.text
        raw_api_key = api_key.json()["key"]

    role_changed = await owner_client.patch(
        f"/v1/team/members/{admin_id}",
        headers={"Idempotency-Key": "owner-demotes-admin"},
        json={"role": "reviewer"},
    )
    assert role_changed.status_code == 200, role_changed.text
    assert role_changed.json()["role"] == "reviewer"

    removed = await owner_client.delete(
        f"/v1/team/members/{admin_id}",
        headers={"Idempotency-Key": "owner-removes-member"},
    )
    assert removed.status_code == 204, removed.text
    revoked = await owner_client.get(
        "/v1/projects",
        headers={"Authorization": f"Bearer {raw_api_key}"},
    )
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "INVALID_API_KEY"

    members = await owner_client.get("/v1/team/members")
    assert members.status_code == 200
    assert [item["user_id"] for item in members.json()["items"]] == [owner["user_id"]]


async def test_multi_workspace_login_requires_explicit_slug(
    team_api: tuple[httpx.AsyncClient, Any],
) -> None:
    first_client, app = team_api
    first = await _register_verified(
        first_client,
        email="first.owner@example.com",
        tenant_name="First Workspace",
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as second_client:
        second = await _register_verified(
            second_client,
            email="second.owner@example.com",
            tenant_name="Second Workspace",
        )

        _, token = await _invite(
            first_client,
            email="second.owner@example.com",
            role="viewer",
            key="cross-workspace-invite",
        )
        accepted = await second_client.post(
            "/v1/team/invitations/accept",
            json={
                "token": token,
                "email": "second.owner@example.com",
                "password": _PASSWORD,
                "display_name": "Second Owner",
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["tenant_id"] == first["tenant_id"]

        await second_client.post("/v1/auth/logout")
        ambiguous = await second_client.post(
            "/v1/auth/login",
            json={"email": "second.owner@example.com", "password": _PASSWORD},
        )
        assert ambiguous.status_code == 409
        assert ambiguous.json()["error"]["code"] == "WORKSPACE_SELECTION_REQUIRED"

        async with app.state.database.sessions() as session:
            second_tenant = await session.get(Tenant, uuid.UUID(second["tenant_id"]))
            assert second_tenant is not None
            second_slug = second_tenant.slug

        selected = await second_client.post(
            "/v1/auth/login",
            json={
                "email": "second.owner@example.com",
                "password": _PASSWORD,
                "tenant_slug": second_slug,
            },
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["tenant_id"] == second["tenant_id"]
        assert selected.json()["roles"] == ["owner"]

        second_project = await second_client.post(
            "/v1/projects",
            headers={"Idempotency-Key": "second-workspace-project"},
            json={"name": "Second workspace project"},
        )
        assert second_project.status_code == 201, second_project.text
        api_key = await second_client.post(
            "/v1/api-keys",
            headers={"Idempotency-Key": "second-workspace-api-key"},
            json={"name": "second-only", "scopes": ["api:read"]},
        )
        assert api_key.status_code == 201, api_key.text
        first_project = await first_client.post(
            "/v1/projects",
            headers={"Idempotency-Key": "first-workspace-project"},
            json={"name": "First workspace project"},
        )
        assert first_project.status_code == 201, first_project.text
        api_key_projects = await second_client.get(
            "/v1/projects",
            headers={"Authorization": f"Bearer {api_key.json()['key']}"},
        )
        assert api_key_projects.status_code == 200, api_key_projects.text
        assert [project["id"] for project in api_key_projects.json()] == [
            second_project.json()["id"]
        ]

        unavailable = await second_client.post(
            "/v1/auth/login",
            json={
                "email": "second.owner@example.com",
                "password": _PASSWORD,
                "tenant_slug": "not-a-workspace",
            },
        )
        assert unavailable.status_code == 403
        assert unavailable.json()["error"]["code"] == "WORKSPACE_NOT_AVAILABLE"


async def test_concurrent_owner_removal_cannot_remove_last_owner(
    team_api: tuple[httpx.AsyncClient, Any],
) -> None:
    first_client, app = team_api
    first = await _register_verified(
        first_client,
        email="owner.one@example.com",
        tenant_name="Owner Lock Workspace",
    )
    _, token = await _invite(
        first_client,
        email="owner.two@example.com",
        role="owner",
        key="invite-second-owner",
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as second_client:
        second_accept = await second_client.post(
            "/v1/team/invitations/accept",
            json={
                "token": token,
                "email": "owner.two@example.com",
                "password": _PASSWORD,
                "display_name": "Owner Two",
            },
        )
        assert second_accept.status_code == 200, second_accept.text
        second_id = second_accept.json()["user_id"]

        first_delete, second_delete = await asyncio.gather(
            first_client.delete(
                f"/v1/team/members/{second_id}",
                headers={"Idempotency-Key": "owner-one-removes-two"},
            ),
            second_client.delete(
                f"/v1/team/members/{first['user_id']}",
                headers={"Idempotency-Key": "owner-two-removes-one"},
            ),
        )

    assert [first_delete.status_code, second_delete.status_code].count(204) == 1
    assert {first_delete.status_code, second_delete.status_code}.issubset({204, 401, 403, 404, 409})
    async with app.state.database.sessions() as session:
        remaining_owners = await session.scalar(
            select(func.count(Membership.user_id)).where(
                Membership.tenant_id == uuid.UUID(first["tenant_id"]),
                Membership.role == "owner",
            )
        )
    assert remaining_owners == 1


def test_invitation_token_codec_is_domain_separated_and_tenant_bound() -> None:
    tenant_id = uuid.uuid4()
    secret = b"s" * 32
    codec = TeamInvitationTokenCodec(secret, ttl_seconds=300)
    issued = codec.issue(tenant_id=tenant_id)

    assert codec.tenant_hint(issued.plaintext) == tenant_id
    assert codec.matches(issued.plaintext, issued.digest)
    assert (
        codec.digest(issued.plaintext)
        != __import__("hmac")
        .new(
            secret,
            b"email-verification\x00" + issued.plaintext.encode(),
            __import__("hashlib").sha256,
        )
        .hexdigest()
    )
