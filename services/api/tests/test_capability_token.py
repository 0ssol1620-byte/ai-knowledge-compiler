"""HTTP contract tests for capability token issuance and bearer verification.

The issue endpoint is tested against the real application (session cookie,
database, RLS) so the "session in, capability out" path is exercised end to
end. Verification is exercised through :func:`get_capability_claims` mounted
on a probe app -- the same dependency the production routes use -- so every
negative class maps to the exact 401 code a client would see.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
import pytest
import pytest_asyncio
from akc_api.capability_api import (
    CapabilityIssueResponse,
    get_capability_claims,
    grantable_scopes,
)
from akc_api.main import create_app
from akc_api.models import Membership
from akc_api.security import Principal
from akc_api.settings import Settings
from akc_cir import Claims, TokenError, mint, verify
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import select


@pytest_asyncio.fixture
async def api(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'capability-api.db').as_posix()}",
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


@pytest_asyncio.fixture
async def owner_client(api: tuple[httpx.AsyncClient, Any]) -> httpx.AsyncClient:
    """A client holding an authenticated owner session (tenant creator)."""
    client, app = api
    registered = await client.post(
        "/v1/auth/register",
        json={
            "email": "capability-owner@example.com",
            "password": "correct horse battery staple",
            "display_name": "Capability Owner",
            "tenant_name": "Capability Owner",
        },
    )
    assert registered.status_code == 201, registered.text
    capture = app.state.verification_capture
    message = await capture.take_for("capability-owner@example.com")
    assert message is not None
    verified = await client.post("/v1/auth/verify-email", json={"token": message.token})
    assert verified.status_code == 200, verified.text
    return client


@pytest_asyncio.fixture
async def probe_app(api: tuple[httpx.AsyncClient, Any]) -> FastAPI:
    """A minimal app mounting the production capability dependency."""
    _, app = api
    probe = FastAPI()
    probe.state.settings = app.state.settings
    probe.state.capability_revocations = app.state.capability_revocations
    router = APIRouter()

    @router.get("/probe/capability")
    async def probe_capability(
        claims: Annotated[Claims, Depends(get_capability_claims)],
    ) -> dict[str, Any]:
        return {"sub": claims.sub, "scopes": list(claims.scopes), "jti": claims.jti}

    probe.include_router(router)
    return probe


async def _issue(
    client: httpx.AsyncClient,
    *,
    scopes: list[str],
    **extra: Any,
) -> httpx.Response:
    return await client.post("/v1/capability/issue", json={"scopes": scopes, **extra})


async def _probe(probe_app: FastAPI, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=probe_app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get("/probe/capability", headers=headers)


# ---------------------------------------------------------------------------
# Issue -> verify round trip
# ---------------------------------------------------------------------------


async def test_issue_then_verify_roundtrip_over_http(
    owner_client: httpx.AsyncClient,
    api: tuple[httpx.AsyncClient, Any],
    probe_app: FastAPI,
) -> None:
    _, app = api

    issued = await _issue(owner_client, scopes=["worlds:read", "search:run"])
    assert issued.status_code == 200, issued.text
    body = issued.json()
    parsed = CapabilityIssueResponse.model_validate(body)
    # "cap_v1" is a format label, not a secret; ruff's S105 cannot tell.
    assert parsed.token_type == "cap_v1"  # noqa: S105
    assert parsed.scopes == ["search:run", "worlds:read"]
    assert parsed.aud == app.state.settings.jwt_issuer
    assert parsed.expires_at > datetime.now(UTC)

    claims = verify(
        parsed.token,
        aud=app.state.settings.jwt_issuer,
        secret=app.state.settings.effective_capability_token_secret,
        now=time.time(),
        revocation_store=app.state.capability_revocations,
    )
    assert claims.sub == parsed.sub
    assert claims.scopes == ("search:run", "worlds:read")
    assert claims.jti == parsed.jti

    probed = await _probe(probe_app, parsed.token)
    assert probed.status_code == 200, probed.text
    assert probed.json() == {
        "sub": claims.sub,
        "scopes": ["search:run", "worlds:read"],
        "jti": claims.jti,
    }


async def test_issued_token_rejects_audience_and_secret_confusion(
    owner_client: httpx.AsyncClient,
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    _, app = api

    issued = await _issue(owner_client, scopes=["evidence:read"])
    assert issued.status_code == 200, issued.text
    token = issued.json()["token"]

    # A capability is for this control plane only...
    with pytest.raises(TokenError) as aud_exc:
        verify(
            token,
            aud="some-other-service",
            secret=app.state.settings.effective_capability_token_secret,
            now=time.time(),
        )
    assert aud_exc.value.code == "AUDIENCE_MISMATCH"

    # ...and it is not a session credential under the JWT key either.
    with pytest.raises(TokenError) as sig_exc:
        verify(
            token,
            aud=app.state.settings.jwt_issuer,
            secret=app.state.settings.jwt_secret,
            now=time.time(),
        )
    assert sig_exc.value.code == "BAD_SIGNATURE"


# ---------------------------------------------------------------------------
# Issuance policy: session required, scopes constrained by role
# ---------------------------------------------------------------------------


async def test_issue_requires_an_authenticated_session(api: tuple[httpx.AsyncClient, Any]) -> None:
    client, _ = api

    anonymous = await _issue(client, scopes=["worlds:read"])
    assert anonymous.status_code == 401, anonymous.text
    assert anonymous.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_unknown_scope_is_rejected_with_422(owner_client: httpx.AsyncClient) -> None:
    rejected = await _issue(owner_client, scopes=["worlds:read", "tenants:admin"])

    assert rejected.status_code == 422, rejected.text


async def test_scope_escalation_is_denied_with_missing_scopes_named(
    owner_client: httpx.AsyncClient,
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    _, app = api

    # Demote the session's membership: the role, not the request, is the
    # authority on what may be delegated.
    async with app.state.database.sessions() as session:
        membership = await session.scalar(select(Membership))
        assert membership is not None
        membership.role = "viewer"
        await session.commit()

    denied = await _issue(owner_client, scopes=["export:run", "worlds:read"])
    assert denied.status_code == 403, denied.text
    error = denied.json()["error"]
    assert error["code"] == "CAPABILITY_SCOPE_DENIED"
    assert error["details"]["requested"] == ["export:run", "worlds:read"]
    assert error["details"]["missing"] == ["export:run"]

    narrowed = await _issue(owner_client, scopes=["worlds:read"])
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json()["scopes"] == ["worlds:read"]


async def test_ttl_is_bounded_by_the_request_model(owner_client: httpx.AsyncClient) -> None:
    too_long = await _issue(owner_client, scopes=["worlds:read"], ttl_seconds=100_000)

    assert too_long.status_code == 422, too_long.text

    bounded = await _issue(owner_client, scopes=["worlds:read"], ttl_seconds=3600)
    assert bounded.status_code == 200, bounded.text


def test_api_key_principals_cannot_delegate_capabilities() -> None:
    principal = Principal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        roles=frozenset({"owner"}),
        scopes=frozenset({"api:read", "api:write", "worlds:read"}),
        auth_type="api_key",
    )

    assert grantable_scopes(principal) == frozenset()


def test_role_grants_follow_the_policy_table() -> None:
    def principal(*roles: str) -> Principal:
        return Principal(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            roles=frozenset(roles),
            scopes=frozenset({"api:read", "api:write"}),
            auth_type="cookie_or_bearer",
        )

    assert grantable_scopes(principal("owner")) == grantable_scopes(principal("admin"))
    assert "export:run" in grantable_scopes(principal("admin"))
    assert "export:run" not in grantable_scopes(principal("editor"))
    assert grantable_scopes(principal("editor")) == {"worlds:read", "search:run", "evidence:read"}
    assert grantable_scopes(principal("viewer", "reviewer")) == {"worlds:read", "evidence:read"}
    assert grantable_scopes(principal("billing")) == frozenset()
    # Union across roles, never intersection: an editor who is also a viewer
    # delegates the editor set.
    assert grantable_scopes(principal("editor", "viewer")) == {
        "worlds:read",
        "search:run",
        "evidence:read",
    }


# ---------------------------------------------------------------------------
# Verification dependency: every negative class maps to a 401 code
# ---------------------------------------------------------------------------


async def test_dependency_requires_bearer_scheme(probe_app: FastAPI) -> None:
    missing_header = await _probe(probe_app, None)
    assert missing_header.status_code == 401, missing_header.text
    assert missing_header.json()["detail"]["code"] == "AUTH_REQUIRED"

    wrong_scheme = await _probe(probe_app, "")  # "Bearer " with empty token
    assert wrong_scheme.status_code == 401, wrong_scheme.text


async def test_dependency_rejects_malformed_and_tampered_tokens(probe_app: FastAPI) -> None:
    malformed = await _probe(probe_app, "garbage.token")
    assert malformed.status_code == 401, malformed.text
    assert malformed.json()["detail"]["code"] == "TOKEN_MALFORMED"

    tampered = await _probe(probe_app, "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.notasig")
    assert tampered.status_code == 401, tampered.text


async def test_dependency_rejects_expired_token(
    api: tuple[httpx.AsyncClient, Any],
    probe_app: FastAPI,
) -> None:
    _, app = api
    settings = app.state.settings

    # Minted in the past with a short ttl: already dead on arrival.
    token = mint(
        sub="user:expired",
        scopes=["worlds:read"],
        aud=settings.jwt_issuer,
        secret=settings.effective_capability_token_secret,
        now=time.time() - 3600,
        ttl_seconds=60,
    )

    rejected = await _probe(probe_app, token)
    assert rejected.status_code == 401, rejected.text
    assert rejected.json()["detail"]["code"] == "TOKEN_EXPIRED"


async def test_dependency_rejects_revoked_token(
    owner_client: httpx.AsyncClient,
    api: tuple[httpx.AsyncClient, Any],
    probe_app: FastAPI,
) -> None:
    _, app = api

    issued = await _issue(owner_client, scopes=["worlds:read"])
    assert issued.status_code == 200, issued.text
    body = issued.json()

    live = await _probe(probe_app, body["token"])
    assert live.status_code == 200, live.text

    app.state.capability_revocations.revoke(body["jti"])

    revoked = await _probe(probe_app, body["token"])
    assert revoked.status_code == 401, revoked.text
    assert revoked.json()["detail"]["code"] == "JTI_REVOKED"


async def test_dependency_rejects_session_jwt_as_capability(
    owner_client: httpx.AsyncClient,
    probe_app: FastAPI,
) -> None:
    # The client holds a valid session cookie; its JWT must not double as a
    # capability token. Different key derivation, different claim shape.
    cookie = owner_client.cookies.get("akc_session")
    assert cookie

    rejected = await _probe(probe_app, cookie)
    assert rejected.status_code == 401, rejected.text
    # probe_app is a bare FastAPI app, so its errors keep FastAPI's default
    # ``detail`` envelope rather than the control plane's ``error`` one.
    assert rejected.json()["detail"]["code"] in {"BAD_SIGNATURE", "TOKEN_MALFORMED"}
