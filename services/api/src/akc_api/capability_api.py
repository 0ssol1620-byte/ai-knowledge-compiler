"""Capability token issuance and bearer verification for the control plane.

A session is a broad, long-lived grant; a capability token is a narrow,
short-lived one. This module is the bridge between the two: an authenticated
session may mint a ``cap_v1`` token carrying *fewer* powers than itself, and
downstream endpoints may then demand exactly those powers through
:func:`get_capability_claims` instead of a full session.

The policy is deliberately fail-closed on both ends:

* Issuance requires a real session (cookie or session bearer -- API keys do
  not qualify) and refuses any requested scope the caller's roles cannot
  grant. Escalation is structurally impossible because the grantable set is
  derived from membership roles, never from the request.
* Verification accepts nothing but a well-formed ``cap_v1`` token whose
  signature, audience, lifetime, and revocation status all check out; every
  failure maps to a distinct error code so clients and operators can tell a
  clock problem from tampering.

Token mechanics live in :mod:`akc_cir.capability_token` (pure stdlib); this
module only wires them into FastAPI. No database migration accompanies this
surface: revocation state is process-local by design until a deployment needs
shared revocation, at which point a store backed by Redis or Postgres can
satisfy the same ``RevocationStore`` protocol.
"""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime
from typing import Annotated

from akc_cir import (
    CAPABILITY_SCOPES,
    MAX_TTL_SECONDS,
    Claims,
    InMemoryRevocationStore,
    TokenError,
    mint,
    verify,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from akc_api.security import Principal, get_principal
from akc_api.settings import Settings

router = APIRouter(prefix="/v1/capability", tags=["capability"])

PrincipalDep = Annotated[Principal, Depends(get_principal)]

#: What each membership role may delegate. The mapping, not the request, is
#: the authority: no caller can talk the issuer into a scope its role does not
#: list here. Roles absent from the map (e.g. billing) can delegate nothing.
_ROLE_GRANTABLE_SCOPES: dict[str, frozenset[str]] = {
    "owner": CAPABILITY_SCOPES,
    "admin": CAPABILITY_SCOPES,
    "editor": frozenset({"worlds:read", "search:run", "evidence:read"}),
    "reviewer": frozenset({"worlds:read", "evidence:read"}),
    "viewer": frozenset({"worlds:read"}),
}

DEFAULT_ISSUE_TTL_SECONDS = 900


def grantable_scopes(principal: Principal) -> frozenset[str]:
    """The union of scopes every role held by ``principal`` may delegate.

    Only genuine sessions (cookie or session bearer) may hold capabilities at
    all. API keys already are scoped credentials; letting them mint more of
    them would turn one leaked key into arbitrary delegation.
    """
    if principal.auth_type != "cookie_or_bearer":
        return frozenset()
    granted: frozenset[str] = frozenset()
    for role in principal.roles:
        granted |= _ROLE_GRANTABLE_SCOPES.get(role, frozenset())
    return granted


class CapabilityIssueRequest(BaseModel):
    """Body of POST /v1/capability/issue."""

    scopes: list[str] = Field(min_length=1, max_length=len(CAPABILITY_SCOPES))
    ttl_seconds: int = Field(
        default=DEFAULT_ISSUE_TTL_SECONDS,
        ge=60,
        le=MAX_TTL_SECONDS,
    )

    @field_validator("scopes")
    @classmethod
    def _scopes_must_be_known(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - CAPABILITY_SCOPES)
        if unknown:
            raise ValueError(f"unknown capability scopes: {unknown}")
        return value


class CapabilityIssueResponse(BaseModel):
    """A freshly minted cap_v1 token and everything needed to track it."""

    token: str
    token_type: str = "cap_v1"  # noqa: S105 - format label, not a secret
    sub: str
    scopes: list[str]
    aud: str
    jti: str
    expires_at: datetime


def get_capability_revocations(request: Request) -> InMemoryRevocationStore:
    """The process-local revocation registry for this app instance."""
    store = getattr(request.app.state, "capability_revocations", None)
    if store is None:
        # Deployments wire the store in create_app; creating one lazily keeps
        # partial test apps honest instead of sharing global mutable state.
        store = InMemoryRevocationStore()
        request.app.state.capability_revocations = store
    return store


async def get_capability_claims(
    request: Request,
    revocations: Annotated[InMemoryRevocationStore, Depends(get_capability_revocations)],
) -> Claims:
    """FastAPI dependency: authenticate the request via a Bearer cap_v1 token.

    Deliberately parallel to :func:`akc_api.security.get_principal`: same
    header convention, same 401-with-code shape, but the credential is a
    capability token rather than a session, and the resulting object carries
    scopes instead of roles. Endpoints that accept capabilities use this
    dependency in place of (not stacked on top of) ``get_principal``.
    """
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})
    settings: Settings = request.app.state.settings
    try:
        claims = verify(
            token,
            aud=settings.jwt_issuer,
            secret=settings.effective_capability_token_secret,
            now=time.time(),
            revocation_store=revocations,
        )
    except TokenError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": exc.code, "retryable": False},
        ) from exc
    return claims


CapabilityClaimsDep = Annotated[Claims, Depends(get_capability_claims)]


@router.post("/issue", response_model=CapabilityIssueResponse)
async def issue_capability_token(
    payload: CapabilityIssueRequest,
    principal: PrincipalDep,
    request: Request,
) -> CapabilityIssueResponse:
    """Mint a short-lived capability token from the current session.

    Requires an authenticated session and grants only scopes the session's
    roles may delegate; anything else is a 403 with the exact missing scopes
    named, so callers can correct themselves without guessing.
    """
    requested = sorted(set(payload.scopes))
    missing = [scope for scope in requested if scope not in grantable_scopes(principal)]
    if missing:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CAPABILITY_SCOPE_DENIED",
                "requested": requested,
                "missing": missing,
            },
        )
    settings: Settings = request.app.state.settings
    subject = f"user:{principal.user_id}"
    now = time.time()
    # The issuer owns the jti so the response can name it: callers keep the id
    # alongside their own records and can present it when revoking later.
    token_id = secrets.token_urlsafe(24)
    token = mint(
        sub=subject,
        scopes=requested,
        aud=settings.jwt_issuer,
        secret=settings.effective_capability_token_secret,
        now=now,
        ttl_seconds=payload.ttl_seconds,
        jti=token_id,
    )
    return CapabilityIssueResponse(
        token=token,
        sub=subject,
        scopes=requested,
        aud=settings.jwt_issuer,
        jti=token_id,
        expires_at=datetime.fromtimestamp(int(now) + payload.ttl_seconds, tz=UTC),
    )
