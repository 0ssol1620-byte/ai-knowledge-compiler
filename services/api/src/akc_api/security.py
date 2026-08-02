"""Password, cookie-session, bearer-token, API-key, and RBAC primitives."""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.database import get_session, set_rls_context
from akc_api.models import ApiKey, Membership, User, utcnow
from akc_api.settings import Settings

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
ALGORITHM = "HS256"
_EVENT_READ_PATH = re.compile(r"^/v1/jobs/[0-9a-fA-F-]{36}/events(?:/replay)?$")
_EXPORT_READ_PATH = re.compile(r"^/v1/exports/[0-9a-fA-F-]{36}(?:/download)?$")
_COLLECTION_RETRIEVAL_READ_PATH = re.compile(r"^/v1/collections/[0-9a-fA-F-]{36}/retrieval/search$")


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    roles: frozenset[str]
    scopes: frozenset[str]
    auth_type: str


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, candidate: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, candidate)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_session_token(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    roles: list[str],
    settings: Settings,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "roles": roles,
        "typ": "session",
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
        "jti": secrets.token_urlsafe(18),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_session_token(token: str, settings: Settings) -> Principal:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "sub", "tid", "iss"]},
        )
        if payload.get("typ") != "session":
            raise jwt.InvalidTokenError("invalid token type")
        return Principal(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tid"]),
            roles=frozenset(str(item) for item in payload.get("roles", [])),
            scopes=frozenset({"api:read", "api:write"}),
            auth_type="cookie_or_bearer",
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_SESSION", "retryable": False},
        ) from exc


def generate_api_key(tenant_id: uuid.UUID) -> tuple[str, str, str]:
    # The tenant segment is an untrusted RLS narrowing hint, not a credential.
    # Authenticity comes exclusively from the digest of the full random token.
    random_value = secrets.token_urlsafe(32)
    raw = f"akc_live_{random_value[:6]}_{tenant_id.hex}_{random_value[6:]}"
    prefix = raw[:24]
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, prefix, digest


async def _principal_from_api_key(raw_key: str, session: AsyncSession) -> Principal | None:
    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    key = await session.scalar(
        select(ApiKey).where(ApiKey.key_hash == digest, ApiKey.revoked_at.is_(None))
    )
    if key is None:
        return None
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == key.tenant_id,
            Membership.user_id == key.created_by,
        )
    )
    if membership is None:
        return None
    user = await session.scalar(
        select(User).where(
            User.id == key.created_by,
            User.is_active.is_(True),
        )
    )
    if user is None:
        return None
    key.last_used_at = utcnow()
    await session.flush()
    return Principal(
        user_id=key.created_by,
        tenant_id=key.tenant_id,
        roles=frozenset({membership.role}),
        scopes=frozenset(key.scopes),
        auth_type="api_key",
    )


def _required_api_key_scopes(request: Request) -> frozenset[str]:
    if request.method == "POST" and _COLLECTION_RETRIEVAL_READ_PATH.fullmatch(request.url.path):
        return frozenset({"api:read"})
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        return frozenset({"api:write"})
    path = request.url.path
    if _EVENT_READ_PATH.fullmatch(path):
        return frozenset({"api:read", "events:read"})
    if _EXPORT_READ_PATH.fullmatch(path):
        return frozenset({"api:read", "exports:read"})
    return frozenset({"api:read"})


def _enforce_api_key_scope(request: Request, principal: Principal) -> None:
    if principal.auth_type != "api_key":
        return
    permitted = _required_api_key_scopes(request)
    if principal.scopes.isdisjoint(permitted):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "API_KEY_SCOPE_DENIED",
                "required_any": sorted(permitted),
            },
        )


async def get_principal(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal:
    settings: Settings = request.app.state.settings
    authorization = request.headers.get("Authorization", "")
    token: str | None = None
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token.startswith("akc_live_"):
            principal = await _principal_from_api_key(token, session)
            if principal is None:
                raise HTTPException(status_code=401, detail={"code": "INVALID_API_KEY"})
            _enforce_api_key_scope(request, principal)
            await set_rls_context(
                session,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
            )
            return principal
    if token is None:
        token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})
    principal = decode_session_token(token, settings)
    await set_rls_context(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    user = await session.scalar(
        select(User).where(User.id == principal.user_id, User.is_active.is_(True))
    )
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == principal.tenant_id,
            Membership.user_id == principal.user_id,
        )
    )
    if user is None or membership is None:
        raise HTTPException(status_code=401, detail={"code": "SESSION_REVOKED"})
    return Principal(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        roles=frozenset({membership.role}),
        scopes=principal.scopes,
        auth_type=principal.auth_type,
    )


def require_roles(
    *allowed: str,
) -> Callable[[Request, Principal], Awaitable[Principal]]:
    async def dependency(
        request: Request,
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> Principal:
        _enforce_api_key_scope(request, principal)
        if principal.roles.isdisjoint(allowed):
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"})
        return principal

    return dependency


async def current_session(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> tuple[Principal, User]:
    user = await session.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "SESSION_REVOKED"})
    return principal, user
