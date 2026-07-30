"""Local cryptographic and API evidence for OIDC and Team/Enterprise MFA."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
import pytest_asyncio
from akc_api.auth_security import (
    MfaSecurity,
    OidcClaims,
    OidcClient,
    OidcProtocolError,
)
from akc_api.main import create_app
from akc_api.models import (
    AuditEvent,
    MfaChallenge,
    MfaCredential,
    OidcIdentity,
    OidcLoginTransaction,
    Tenant,
)
from akc_api.settings import Settings
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

_PASSWORD = "correct horse battery staple"  # noqa: S105
_SUPPORT_KEY = "oidc-mfa-test-support-key"
_ISSUER = "https://identity.example.test"
_CLIENT_ID = "akc-local-test-client"
_CLIENT_SECRET = "local-test-confidential-secret-value"  # noqa: S105


def _b64uint(value: int) -> str:
    width = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(width, "big")).rstrip(b"=").decode()


def _oidc_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "database_url": (f"sqlite+aiosqlite:///{(tmp_path / 'auth.db').as_posix()}"),
        "data_dir": tmp_path / "data",
        "local_background_tasks": False,
        "local_analysis_worker_enabled": False,
        "clamav_enabled": False,
        "allow_development_antivirus_bypass": True,
        "test_support_key": _SUPPORT_KEY,
        "oidc_enabled": True,
        "oidc_issuer_url": _ISSUER,
        "oidc_client_id": _CLIENT_ID,
        "oidc_client_secret": _CLIENT_SECRET,
        "oidc_redirect_uri": "http://testserver/v1/auth/oidc/callback",
        "oidc_transaction_encryption_key": Fernet.generate_key().decode(),
        "oidc_state_hmac_secret": "state-hmac-secret-for-tests-32-bytes",
    }
    values.update(overrides)
    return Settings(**values)


class StubOidcClient:
    def __init__(self) -> None:
        self.subject = "external-subject-1"
        self.email = "oidc.user@example.com"
        self.name = "OIDC User"
        self.state = ""
        self.nonce = ""
        self.code_challenge = ""
        self.code_verifier = ""

    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        self.state = state
        self.nonce = nonce
        self.code_challenge = code_challenge
        return (
            f"{_ISSUER}/authorize?"
            f"state={state}&nonce={nonce}&code_challenge={code_challenge}"
            "&code_challenge_method=S256"
        )

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str,
    ) -> OidcClaims:
        assert code == "one-time-code"
        assert expected_nonce == self.nonce
        self.code_verifier = code_verifier
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert expected == self.code_challenge
        return OidcClaims(
            issuer=_ISSUER,
            subject=self.subject,
            email=self.email,
            display_name=self.name,
        )


@pytest_asyncio.fixture
async def auth_api(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, StubOidcClient]]:
    app = create_app(_oidc_settings(tmp_path))
    stub = StubOidcClient()
    app.state.oidc_client = stub
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client, app, stub


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
    captured = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _SUPPORT_KEY},
        json={"email": email},
    )
    assert captured.status_code == 200, captured.text
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": captured.json()["token"]},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


@pytest.mark.asyncio
async def test_verified_oidc_client_enforces_discovery_jwks_nonce_pkce_and_at_hash(
    tmp_path: Path,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": "local-key-1",
        "n": _b64uint(numbers.n),
        "e": _b64uint(numbers.e),
    }
    access_token = "opaque-access-token"  # noqa: S105
    digest = hashlib.sha256(access_token.encode()).digest()
    at_hash = base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode()
    nonce = "expected-nonce"
    now = int(time.time())
    id_token = jwt.encode(
        {
            "iss": _ISSUER,
            "sub": "subject-123",
            "aud": _CLIENT_ID,
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
            "email": "verified@example.com",
            "email_verified": True,
            "name": "Verified User",
            "at_hash": at_hash,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "local-key-1"},
    )
    token_form: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": _ISSUER,
                    "authorization_endpoint": f"{_ISSUER}/authorize",
                    "token_endpoint": f"{_ISSUER}/token",
                    "jwks_uri": f"{_ISSUER}/jwks",
                    "token_endpoint_auth_methods_supported": ["client_secret_basic"],
                },
            )
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [jwk]})
        if request.url.path == "/token":
            token_form.update(
                {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            )
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(
                200,
                json={
                    "access_token": access_token,
                    "id_token": id_token,
                    "token_type": "Bearer",
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    settings = _oidc_settings(tmp_path)
    client = OidcClient(settings, transport=httpx.MockTransport(handler))
    try:
        authorization_url = await client.authorization_url(
            state="opaque-state",
            nonce=nonce,
            code_challenge="pkce-challenge",
        )
        query = parse_qs(urlsplit(authorization_url).query)
        assert query["state"] == ["opaque-state"]
        assert query["nonce"] == [nonce]
        assert query["code_challenge_method"] == ["S256"]
        claims = await client.exchange_code(
            code="authorization-code",
            code_verifier="pkce-verifier",
            expected_nonce=nonce,
        )
        with pytest.raises(OidcProtocolError, match="OIDC_NONCE_INVALID"):
            await client.exchange_code(
                code="authorization-code",
                code_verifier="pkce-verifier",
                expected_nonce="different-nonce",
            )
    finally:
        await client.aclose()
    assert claims.subject == "subject-123"
    assert claims.email == "verified@example.com"
    assert token_form["code_verifier"] == "pkce-verifier"
    assert token_form["grant_type"] == "authorization_code"


@pytest.mark.asyncio
async def test_oidc_client_rejects_nonce_and_discovery_issuer_mismatch(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/.well-known/openid-configuration")
        return httpx.Response(
            200,
            json={
                "issuer": "https://attacker.example",
                "authorization_endpoint": f"{_ISSUER}/authorize",
                "token_endpoint": f"{_ISSUER}/token",
                "jwks_uri": f"{_ISSUER}/jwks",
            },
        )

    client = OidcClient(
        _oidc_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OidcProtocolError, match="OIDC_ISSUER_MISMATCH"):
            await client.discovery()
    finally:
        await client.aclose()


def test_totp_matches_rfc_vector_and_recovery_digests_are_one_way(
    tmp_path: Path,
) -> None:
    security = MfaSecurity(_oidc_settings(tmp_path))
    # RFC 6238 SHA-1 test seed.  The RFC's 8-digit value at t=59 is
    # 94287082, so this product's 6-digit profile yields 287082.
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    moment = datetime.fromtimestamp(59, tz=UTC)
    assert security.totp_code(secret, at=moment) == "287082"
    assert security.matching_totp_step(secret, "287082", at=moment) == 1
    codes, digests = security.generate_recovery_codes()
    assert len(codes) == len(digests) == 10
    assert all(code not in json.dumps(digests) for code in codes)
    assert security.recovery_digest(codes[0]) == digests[0]


@pytest.mark.asyncio
async def test_team_login_requires_enrollment_then_single_use_mfa_and_audits(
    auth_api: tuple[httpx.AsyncClient, Any, StubOidcClient],
) -> None:
    client, app, _ = auth_api
    account = await _register_verified(
        client,
        email="team.owner@example.com",
        tenant_name="Team Workspace",
    )
    async with app.state.database.sessions.begin() as session:
        tenant = await session.get(Tenant, uuid.UUID(account["tenant_id"]))
        assert tenant is not None
        tenant.plan_code = "team"
    await client.post("/v1/auth/logout")

    primary = await client.post(
        "/v1/auth/login",
        json={"email": "team.owner@example.com", "password": _PASSWORD},
    )
    assert primary.status_code == 200, primary.text
    assert primary.json()["action"] == "enroll"
    assert app.state.settings.session_cookie_name not in client.cookies
    mfa_token = primary.json()["mfa_token"]

    enrollment = await client.post(
        "/v1/auth/mfa/enrollment",
        json={"mfa_token": mfa_token},
    )
    assert enrollment.status_code == 200, enrollment.text
    secret = enrollment.json()["secret"]
    code = app.state.mfa_security.totp_code(secret)
    confirmed = await client.post(
        "/v1/auth/mfa/enrollment/confirm",
        json={"mfa_token": mfa_token, "code": code},
    )
    assert confirmed.status_code == 200, confirmed.text
    recovery_codes = confirmed.json()["recovery_codes"]
    assert len(recovery_codes) == 10
    assert app.state.settings.session_cookie_name in client.cookies

    await client.post("/v1/auth/logout")
    challenge_login = await client.post(
        "/v1/auth/login",
        json={"email": "team.owner@example.com", "password": _PASSWORD},
    )
    assert challenge_login.json()["action"] == "challenge"
    challenge_token = challenge_login.json()["mfa_token"]
    recovery = await client.post(
        "/v1/auth/mfa/challenge",
        json={
            "mfa_token": challenge_token,
            "recovery_code": recovery_codes[0],
        },
    )
    assert recovery.status_code == 200, recovery.text

    await client.post("/v1/auth/logout")
    replay_login = await client.post(
        "/v1/auth/login",
        json={"email": "team.owner@example.com", "password": _PASSWORD},
    )
    replay = await client.post(
        "/v1/auth/mfa/challenge",
        json={
            "mfa_token": replay_login.json()["mfa_token"],
            "recovery_code": recovery_codes[0],
        },
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "INVALID_MFA_CODE"

    async with app.state.database.sessions() as session:
        credential = await session.scalar(select(MfaCredential))
        assert credential is not None
        assert secret.encode() not in credential.encrypted_secret
        assert recovery_codes[0] not in credential.recovery_code_hashes
        assert len(credential.recovery_code_hashes) == 9
        actions = set(await session.scalars(select(AuditEvent.action)))
    assert {
        "auth.mfa_required",
        "auth.mfa_enrollment_started",
        "auth.mfa_enrolled",
        "auth.mfa_challenge_succeeded",
        "auth.mfa_challenge_failed",
    }.issubset(actions)


@pytest.mark.asyncio
async def test_mfa_challenge_failure_limit_consumes_pending_token(
    auth_api: tuple[httpx.AsyncClient, Any, StubOidcClient],
) -> None:
    client, app, _ = auth_api
    account = await _register_verified(
        client,
        email="limit@example.com",
        tenant_name="Limit Workspace",
    )
    async with app.state.database.sessions.begin() as session:
        tenant = await session.get(Tenant, uuid.UUID(account["tenant_id"]))
        assert tenant is not None
        tenant.plan_code = "enterprise"
    await client.post("/v1/auth/logout")
    primary = await client.post(
        "/v1/auth/login",
        json={"email": "limit@example.com", "password": _PASSWORD},
    )
    mfa_token = primary.json()["mfa_token"]
    enrollment = await client.post(
        "/v1/auth/mfa/enrollment",
        json={"mfa_token": mfa_token},
    )
    secret = enrollment.json()["secret"]
    confirmed = await client.post(
        "/v1/auth/mfa/enrollment/confirm",
        json={
            "mfa_token": mfa_token,
            "code": app.state.mfa_security.totp_code(secret),
        },
    )
    assert confirmed.status_code == 200
    await client.post("/v1/auth/logout")
    login = await client.post(
        "/v1/auth/login",
        json={"email": "limit@example.com", "password": _PASSWORD},
    )
    token = login.json()["mfa_token"]
    for _ in range(5):
        failed = await client.post(
            "/v1/auth/mfa/challenge",
            json={"mfa_token": token, "code": "000000"},
        )
        assert failed.status_code == 401
    consumed = await client.post(
        "/v1/auth/mfa/challenge",
        json={"mfa_token": token, "code": "000000"},
    )
    assert consumed.status_code == 401
    assert consumed.json()["error"]["code"] == "INVALID_OR_EXPIRED_MFA_TOKEN"
    async with app.state.database.sessions() as session:
        challenge = await session.scalar(
            select(MfaChallenge).order_by(MfaChallenge.created_at.desc())
        )
        assert challenge is not None
        assert challenge.failures == 5
        assert challenge.consumed_at is not None


@pytest.mark.asyncio
async def test_team_invitation_acceptance_cannot_bypass_mfa_session_gate(
    auth_api: tuple[httpx.AsyncClient, Any, StubOidcClient],
) -> None:
    owner_client, app, _ = auth_api
    owner = await _register_verified(
        owner_client,
        email="invite.owner@example.com",
        tenant_name="Invite Team",
    )
    async with app.state.database.sessions.begin() as session:
        tenant = await session.get(Tenant, uuid.UUID(owner["tenant_id"]))
        assert tenant is not None
        tenant.plan_code = "team"
    invitation = await owner_client.post(
        "/v1/team/invitations",
        headers={"Idempotency-Key": "mfa-team-invite"},
        json={"email": "invited@example.com", "role": "editor"},
    )
    assert invitation.status_code == 201, invitation.text
    captured = await owner_client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _SUPPORT_KEY},
        json={"email": "invited@example.com"},
    )
    assert captured.status_code == 200, captured.text

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as invited_client:
        accepted = await invited_client.post(
            "/v1/team/invitations/accept",
            json={
                "token": captured.json()["token"],
                "email": "invited@example.com",
                "password": _PASSWORD,
                "display_name": "Invited Editor",
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["action"] == "enroll"
        assert app.state.settings.session_cookie_name not in invited_client.cookies


@pytest.mark.asyncio
async def test_oidc_pkce_transaction_is_browser_bound_single_use_and_encrypted(
    auth_api: tuple[httpx.AsyncClient, Any, StubOidcClient],
) -> None:
    client, app, stub = auth_api
    started = await client.get(
        "/v1/auth/oidc/authorize",
        params={"tenant_name": "OIDC Workspace"},
    )
    assert started.status_code == 200, started.text
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as other_browser:
        rejected = await other_browser.get(
            "/v1/auth/oidc/callback",
            params={"code": "one-time-code", "state": state},
        )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "INVALID_OR_EXPIRED_OIDC_STATE"

    callback = await client.get(
        "/v1/auth/oidc/callback",
        params={"code": "one-time-code", "state": state},
    )
    assert callback.status_code == 200, callback.text
    assert callback.json()["email"] == stub.email
    replay = await client.get(
        "/v1/auth/oidc/callback",
        params={"code": "one-time-code", "state": state},
    )
    assert replay.status_code == 400
    async with app.state.database.sessions() as session:
        transaction = await session.scalar(select(OidcLoginTransaction))
        identity = await session.scalar(select(OidcIdentity))
        assert transaction is not None
        assert identity is not None
        assert transaction.state_hash != state
        assert stub.nonce.encode() not in transaction.encrypted_secrets
        assert stub.code_verifier.encode() not in transaction.encrypted_secrets
        assert identity.subject == stub.subject


@pytest.mark.asyncio
async def test_existing_oidc_identity_obeys_team_mfa_policy_before_session(
    auth_api: tuple[httpx.AsyncClient, Any, StubOidcClient],
) -> None:
    client, app, _ = auth_api
    initial = await client.get(
        "/v1/auth/oidc/authorize",
        params={"tenant_name": "OIDC Team"},
    )
    initial_state = parse_qs(urlsplit(initial.json()["authorization_url"]).query)["state"][0]
    registered = await client.get(
        "/v1/auth/oidc/callback",
        params={"code": "one-time-code", "state": initial_state},
    )
    assert registered.status_code == 200, registered.text
    async with app.state.database.sessions.begin() as session:
        tenant = await session.get(
            Tenant,
            uuid.UUID(registered.json()["tenant_id"]),
        )
        assert tenant is not None
        tenant.plan_code = "team"
    await client.post("/v1/auth/logout")

    login = await client.get("/v1/auth/oidc/authorize")
    state = parse_qs(urlsplit(login.json()["authorization_url"]).query)["state"][0]
    challenged = await client.get(
        "/v1/auth/oidc/callback",
        params={"code": "one-time-code", "state": state},
    )
    assert challenged.status_code == 200, challenged.text
    assert challenged.json()["action"] == "enroll"
    assert app.state.settings.session_cookie_name not in client.cookies


@pytest.mark.asyncio
async def test_oidc_existing_email_requires_explicit_authenticated_binding(
    auth_api: tuple[httpx.AsyncClient, Any, StubOidcClient],
) -> None:
    client, app, stub = auth_api
    account = await _register_verified(
        client,
        email="existing@example.com",
        tenant_name="Existing Workspace",
    )
    stub.email = "existing@example.com"
    login_start = await client.get("/v1/auth/oidc/authorize")
    login_state = parse_qs(urlsplit(login_start.json()["authorization_url"]).query)["state"][0]
    denied = await client.get(
        "/v1/auth/oidc/callback",
        params={"code": "one-time-code", "state": login_state},
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "OIDC_ACCOUNT_BINDING_REQUIRED"

    # The password-authenticated session remains present because the denied
    # OIDC login never replaces or broadens it.
    assert (await client.get("/v1/auth/session")).status_code == 200
    bind_start = await client.get("/v1/auth/oidc/bind/authorize")
    assert bind_start.status_code == 200, bind_start.text
    bind_state = parse_qs(urlsplit(bind_start.json()["authorization_url"]).query)["state"][0]
    bound = await client.get(
        "/v1/auth/oidc/callback",
        params={"code": "one-time-code", "state": bind_state},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["user_id"] == account["user_id"]
    async with app.state.database.sessions() as session:
        identities = list(await session.scalars(select(OidcIdentity)))
    assert len(identities) == 1
    assert str(identities[0].user_id) == account["user_id"]


def test_oidc_configuration_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="credential-free HTTPS"):
        _oidc_settings(
            tmp_path,
            oidc_issuer_url="http://identity.example.test",
        )
    with pytest.raises(ValueError, match="asymmetric"):
        _oidc_settings(
            tmp_path,
            oidc_allowed_algorithms="HS256",
        )
    with pytest.raises(ValueError, match="requires issuer"):
        _oidc_settings(
            tmp_path,
            oidc_issuer_url=None,
        )
