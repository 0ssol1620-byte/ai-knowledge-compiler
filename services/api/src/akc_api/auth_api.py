"""Verified OIDC account binding and Team/Enterprise MFA API."""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, cast
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.auth_security import (
    MfaSecurity,
    MfaTokenClaims,
    OidcClient,
    OidcProtocolError,
    OidcTransactionCipher,
)
from akc_api.database import get_session, set_rls_context
from akc_api.models import (
    Membership,
    MfaChallenge,
    MfaCredential,
    OidcIdentity,
    OidcLoginTransaction,
    Tenant,
    User,
    utcnow,
)
from akc_api.schemas import (
    MfaChallengeRequest,
    MfaEnrollmentConfirmedResponse,
    MfaEnrollmentConfirmRequest,
    MfaEnrollmentRequest,
    MfaEnrollmentResponse,
    MfaRecoveryCodesResponse,
    MfaRecoveryRegenerateRequest,
    MfaRequiredResponse,
    MfaStatusResponse,
    OidcAuthorizeResponse,
    SessionResponse,
)
from akc_api.security import (
    Principal,
    create_session_token,
    get_principal,
    hash_password,
)
from akc_api.services import audit, credit_entry
from akc_api.settings import Settings
from akc_api.verification import normalize_public_email

router = APIRouter(prefix="/v1/auth", tags=["auth"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]

_MAX_MFA_FAILURES = 5
_OIDC_BROWSER_COOKIE = "akc_oidc_transaction"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _slug(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{value[:50] or 'workspace'}-{secrets.token_hex(3)}"


def _mfa_required(settings: Settings, tenant: Tenant) -> bool:
    return tenant.plan_code.casefold() in settings.mfa_plan_codes


def _session_response(
    user: User,
    membership: Membership,
) -> SessionResponse:
    return SessionResponse(
        user_id=user.id,
        tenant_id=membership.tenant_id,
        email=user.email,
        display_name=user.display_name,
        roles=[membership.role],
        email_verified=user.email_verified_at is not None,
    )


def _set_session_cookie(
    response: Response,
    *,
    user: User,
    membership: Membership,
    settings: Settings,
) -> None:
    token = create_session_token(
        user_id=user.id,
        tenant_id=membership.tenant_id,
        roles=[membership.role],
        settings=settings,
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.effective_cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.access_token_minutes * 60,
        path="/",
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.effective_cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


async def begin_mfa_login(
    *,
    request: Request,
    response: Response,
    session: AsyncSession,
    user: User,
    membership: Membership,
    auth_method: Literal["password", "oidc"],
) -> MfaRequiredResponse | None:
    """Return a durable pending challenge when the tenant plan requires MFA."""

    settings = cast(Settings, request.app.state.settings)
    tenant = await session.get(Tenant, membership.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_NOT_AVAILABLE"})
    if not _mfa_required(settings, tenant):
        return None
    credential = await session.scalar(
        select(MfaCredential).where(
            MfaCredential.tenant_id == membership.tenant_id,
            MfaCredential.user_id == user.id,
            MfaCredential.status == "active",
        )
    )
    purpose: Literal["enroll", "challenge"] = "challenge" if credential is not None else "enroll"
    now = utcnow()
    await session.execute(
        update(MfaChallenge)
        .where(
            MfaChallenge.tenant_id == membership.tenant_id,
            MfaChallenge.user_id == user.id,
            MfaChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    security = cast(MfaSecurity, request.app.state.mfa_security)
    token, token_hash, expires_at = security.issue_pending_token(
        user_id=str(user.id),
        tenant_id=str(membership.tenant_id),
        roles=[membership.role],
        purpose=purpose,
    )
    session.add(
        MfaChallenge(
            tenant_id=membership.tenant_id,
            user_id=user.id,
            token_hash=token_hash,
            purpose=purpose,
            expires_at=expires_at,
        )
    )
    await audit(
        session,
        tenant_id=membership.tenant_id,
        actor_id=user.id,
        action="auth.mfa_required",
        target_type="user",
        target_id=str(user.id),
        metadata={"action": purpose, "primary_auth": auth_method},
    )
    _clear_session_cookie(response, settings)
    return MfaRequiredResponse(
        action=purpose,
        mfa_token=token,
        expires_in_seconds=settings.mfa_challenge_ttl_seconds,
    )


def _invalid_mfa_token() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "INVALID_OR_EXPIRED_MFA_TOKEN"},
    )


async def _pending_challenge(
    request: Request,
    session: AsyncSession,
    token: str,
    *,
    purpose: Literal["enroll", "challenge"],
) -> tuple[MfaTokenClaims, MfaChallenge, User, Membership, Tenant]:
    security = cast(MfaSecurity, request.app.state.mfa_security)
    try:
        claims = security.decode_pending_token(token)
        tenant_id = uuid.UUID(claims.tenant_id)
        user_id = uuid.UUID(claims.user_id)
    except (ValueError, TypeError):
        raise _invalid_mfa_token() from None
    if claims.purpose != purpose:
        raise _invalid_mfa_token()
    await set_rls_context(session, tenant_id=tenant_id, user_id=user_id)
    challenge = await session.scalar(
        select(MfaChallenge)
        .where(
            MfaChallenge.tenant_id == tenant_id,
            MfaChallenge.user_id == user_id,
            MfaChallenge.token_hash == security.pending_token_digest(claims.token_id),
        )
        .with_for_update()
    )
    now = utcnow()
    if (
        challenge is None
        or challenge.purpose != purpose
        or challenge.consumed_at is not None
        or _aware(challenge.expires_at) <= now
        or challenge.failures >= _MAX_MFA_FAILURES
    ):
        raise _invalid_mfa_token()
    user = await session.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user_id,
        )
    )
    tenant = await session.get(Tenant, tenant_id)
    settings = cast(Settings, request.app.state.settings)
    if user is None or membership is None or tenant is None or not _mfa_required(settings, tenant):
        raise _invalid_mfa_token()
    return claims, challenge, user, membership, tenant


@router.post("/mfa/enrollment", response_model=MfaEnrollmentResponse)
async def start_mfa_enrollment(
    payload: MfaEnrollmentRequest,
    request: Request,
    session: SessionDep,
) -> MfaEnrollmentResponse:
    _, _, user, membership, _ = await _pending_challenge(
        request,
        session,
        payload.mfa_token.get_secret_value(),
        purpose="enroll",
    )
    credential = await session.scalar(
        select(MfaCredential)
        .where(
            MfaCredential.tenant_id == membership.tenant_id,
            MfaCredential.user_id == user.id,
        )
        .with_for_update()
    )
    if credential is not None and credential.status == "active":
        raise HTTPException(
            status_code=409,
            detail={"code": "MFA_ALREADY_ENROLLED"},
        )
    security = cast(MfaSecurity, request.app.state.mfa_security)
    secret = security.generate_totp_secret()
    if credential is None:
        credential = MfaCredential(
            tenant_id=membership.tenant_id,
            user_id=user.id,
            encrypted_secret=security.encrypt_secret(secret),
            status="pending",
        )
        session.add(credential)
    else:
        credential.encrypted_secret = security.encrypt_secret(secret)
        credential.recovery_code_hashes = []
        credential.last_totp_step = None
        credential.confirmed_at = None
        credential.status = "pending"
    await session.flush()
    issuer = cast(Settings, request.app.state.settings).jwt_issuer
    label = quote(f"{issuer}:{user.email}", safe="")
    otpauth_uri = f"otpauth://totp/{label}?" + urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": "6",
            "period": "30",
        }
    )
    await audit(
        session,
        tenant_id=membership.tenant_id,
        actor_id=user.id,
        action="auth.mfa_enrollment_started",
        target_type="mfa_credential",
        target_id=str(credential.id),
    )
    await session.commit()
    return MfaEnrollmentResponse(
        credential_id=credential.id,
        secret=secret,
        otpauth_uri=otpauth_uri,
    )


@router.post(
    "/mfa/enrollment/confirm",
    response_model=MfaEnrollmentConfirmedResponse,
)
async def confirm_mfa_enrollment(
    payload: MfaEnrollmentConfirmRequest,
    request: Request,
    response: Response,
    session: SessionDep,
) -> MfaEnrollmentConfirmedResponse:
    _, challenge, user, membership, _ = await _pending_challenge(
        request,
        session,
        payload.mfa_token.get_secret_value(),
        purpose="enroll",
    )
    credential = await session.scalar(
        select(MfaCredential)
        .where(
            MfaCredential.tenant_id == membership.tenant_id,
            MfaCredential.user_id == user.id,
            MfaCredential.status == "pending",
        )
        .with_for_update()
    )
    if credential is None:
        raise _invalid_mfa_token()
    security = cast(MfaSecurity, request.app.state.mfa_security)
    try:
        secret = security.decrypt_secret(credential.encrypted_secret)
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail={"code": "MFA_CREDENTIAL_INTEGRITY_FAILURE"},
        ) from None
    code = payload.code.get_secret_value()
    step = security.matching_totp_step(secret, code)
    if step is None:
        challenge.failures += 1
        if challenge.failures >= _MAX_MFA_FAILURES:
            challenge.consumed_at = utcnow()
        await audit(
            session,
            tenant_id=membership.tenant_id,
            actor_id=user.id,
            action="auth.mfa_enrollment_failed",
            target_type="mfa_credential",
            target_id=str(credential.id),
            metadata={"attempts": challenge.failures},
        )
        await session.commit()
        raise HTTPException(status_code=401, detail={"code": "INVALID_MFA_CODE"})
    recovery_codes, recovery_hashes = security.generate_recovery_codes()
    now = utcnow()
    credential.status = "active"
    credential.confirmed_at = now
    credential.last_totp_step = step
    credential.recovery_code_hashes = recovery_hashes
    challenge.consumed_at = now
    await audit(
        session,
        tenant_id=membership.tenant_id,
        actor_id=user.id,
        action="auth.mfa_enrolled",
        target_type="mfa_credential",
        target_id=str(credential.id),
        metadata={"recovery_code_count": len(recovery_codes)},
    )
    await session.commit()
    settings = cast(Settings, request.app.state.settings)
    _set_session_cookie(
        response,
        user=user,
        membership=membership,
        settings=settings,
    )
    result = _session_response(user, membership)
    return MfaEnrollmentConfirmedResponse(
        **result.model_dump(),
        recovery_codes=recovery_codes,
    )


async def _record_invalid_factor(
    session: AsyncSession,
    *,
    challenge: MfaChallenge,
    credential: MfaCredential,
    user: User,
    method: str,
) -> None:
    challenge.failures += 1
    if challenge.failures >= _MAX_MFA_FAILURES:
        challenge.consumed_at = utcnow()
    await audit(
        session,
        tenant_id=challenge.tenant_id,
        actor_id=user.id,
        action="auth.mfa_challenge_failed",
        target_type="mfa_credential",
        target_id=str(credential.id),
        metadata={"method": method, "attempts": challenge.failures},
    )
    await session.commit()


@router.post("/mfa/challenge", response_model=SessionResponse)
async def complete_mfa_challenge(
    payload: MfaChallengeRequest,
    request: Request,
    response: Response,
    session: SessionDep,
) -> SessionResponse:
    _, challenge, user, membership, _ = await _pending_challenge(
        request,
        session,
        payload.mfa_token.get_secret_value(),
        purpose="challenge",
    )
    credential = await session.scalar(
        select(MfaCredential)
        .where(
            MfaCredential.tenant_id == membership.tenant_id,
            MfaCredential.user_id == user.id,
            MfaCredential.status == "active",
        )
        .with_for_update()
    )
    if credential is None:
        raise _invalid_mfa_token()
    security = cast(MfaSecurity, request.app.state.mfa_security)
    method: Literal["totp", "recovery"]
    if payload.code is not None:
        method = "totp"
        try:
            secret = security.decrypt_secret(credential.encrypted_secret)
        except ValueError:
            raise HTTPException(
                status_code=500,
                detail={"code": "MFA_CREDENTIAL_INTEGRITY_FAILURE"},
            ) from None
        step = security.matching_totp_step(
            secret,
            payload.code.get_secret_value(),
        )
        if step is None or (
            credential.last_totp_step is not None and step <= credential.last_totp_step
        ):
            await _record_invalid_factor(
                session,
                challenge=challenge,
                credential=credential,
                user=user,
                method=method,
            )
            raise HTTPException(status_code=401, detail={"code": "INVALID_MFA_CODE"})
        credential.last_totp_step = step
    else:
        method = "recovery"
        if payload.recovery_code is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "MFA_FACTOR_REQUIRED"},
            )
        candidate = security.recovery_digest(payload.recovery_code.get_secret_value())
        matched_index = next(
            (
                index
                for index, digest in enumerate(credential.recovery_code_hashes)
                if secrets.compare_digest(candidate, digest)
            ),
            None,
        )
        if matched_index is None:
            await _record_invalid_factor(
                session,
                challenge=challenge,
                credential=credential,
                user=user,
                method=method,
            )
            raise HTTPException(status_code=401, detail={"code": "INVALID_MFA_CODE"})
        credential.recovery_code_hashes = [
            digest
            for index, digest in enumerate(credential.recovery_code_hashes)
            if index != matched_index
        ]
    challenge.consumed_at = utcnow()
    await audit(
        session,
        tenant_id=membership.tenant_id,
        actor_id=user.id,
        action="auth.mfa_challenge_succeeded",
        target_type="mfa_credential",
        target_id=str(credential.id),
        metadata={
            "method": method,
            "recovery_codes_remaining": len(credential.recovery_code_hashes),
        },
    )
    await session.commit()
    _set_session_cookie(
        response,
        user=user,
        membership=membership,
        settings=cast(Settings, request.app.state.settings),
    )
    return _session_response(user, membership)


@router.get("/mfa/status", response_model=MfaStatusResponse)
async def mfa_status(
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> MfaStatusResponse:
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})
    credential = await session.scalar(
        select(MfaCredential).where(
            MfaCredential.tenant_id == principal.tenant_id,
            MfaCredential.user_id == principal.user_id,
            MfaCredential.status == "active",
        )
    )
    return MfaStatusResponse(
        required_for_plan=_mfa_required(
            cast(Settings, request.app.state.settings),
            tenant,
        ),
        enrolled=credential is not None,
        recovery_codes_remaining=(
            len(credential.recovery_code_hashes) if credential is not None else 0
        ),
    )


@router.post(
    "/mfa/recovery-codes/regenerate",
    response_model=MfaRecoveryCodesResponse,
)
async def regenerate_recovery_codes(
    payload: MfaRecoveryRegenerateRequest,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> MfaRecoveryCodesResponse:
    credential = await session.scalar(
        select(MfaCredential)
        .where(
            MfaCredential.tenant_id == principal.tenant_id,
            MfaCredential.user_id == principal.user_id,
            MfaCredential.status == "active",
        )
        .with_for_update()
    )
    if credential is None:
        raise HTTPException(status_code=409, detail={"code": "MFA_NOT_ENROLLED"})
    security = cast(MfaSecurity, request.app.state.mfa_security)
    try:
        secret = security.decrypt_secret(credential.encrypted_secret)
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail={"code": "MFA_CREDENTIAL_INTEGRITY_FAILURE"},
        ) from None
    step = security.matching_totp_step(
        secret,
        payload.code.get_secret_value(),
    )
    if step is None or (
        credential.last_totp_step is not None and step <= credential.last_totp_step
    ):
        raise HTTPException(status_code=401, detail={"code": "INVALID_MFA_CODE"})
    credential.last_totp_step = step
    codes, digests = security.generate_recovery_codes()
    credential.recovery_code_hashes = digests
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="auth.mfa_recovery_codes_regenerated",
        target_type="mfa_credential",
        target_id=str(credential.id),
        metadata={"recovery_code_count": len(codes)},
    )
    await session.commit()
    return MfaRecoveryCodesResponse(recovery_codes=codes)


def _oidc_unavailable(request: Request) -> tuple[OidcClient, OidcTransactionCipher]:
    client = cast(OidcClient | None, request.app.state.oidc_client)
    cipher = cast(OidcTransactionCipher | None, request.app.state.oidc_transaction_cipher)
    if client is None or cipher is None:
        raise HTTPException(status_code=404, detail={"code": "OIDC_NOT_ENABLED"})
    return client, cipher


async def _begin_oidc(
    *,
    request: Request,
    response: Response,
    session: AsyncSession,
    purpose: Literal["login", "bind"],
    binding_user_id: uuid.UUID | None = None,
    binding_tenant_id: uuid.UUID | None = None,
    tenant_slug: str | None = None,
    tenant_name: str | None = None,
) -> OidcAuthorizeResponse:
    client, cipher = _oidc_unavailable(request)
    state, nonce, challenge, encrypted = cipher.new()
    authorization_url = await client.authorization_url(
        state=state,
        nonce=nonce,
        code_challenge=challenge,
    )
    settings = cast(Settings, request.app.state.settings)
    browser_binding = secrets.token_urlsafe(32)
    session.add(
        OidcLoginTransaction(
            state_hash=cipher.state_digest(state),
            browser_binding_hash=cipher.state_digest(f"browser:{browser_binding}"),
            purpose=purpose,
            encrypted_secrets=encrypted,
            binding_user_id=binding_user_id,
            binding_tenant_id=binding_tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            expires_at=utcnow() + timedelta(seconds=settings.oidc_transaction_ttl_seconds),
        )
    )
    await session.commit()
    response.set_cookie(
        _OIDC_BROWSER_COOKIE,
        browser_binding,
        httponly=True,
        secure=settings.effective_cookie_secure,
        samesite="lax",
        max_age=settings.oidc_transaction_ttl_seconds,
        path="/v1/auth/oidc/callback",
    )
    return OidcAuthorizeResponse(
        authorization_url=authorization_url,
        expires_in_seconds=settings.oidc_transaction_ttl_seconds,
    )


@router.get("/oidc/authorize", response_model=OidcAuthorizeResponse)
async def oidc_authorize(
    request: Request,
    response: Response,
    session: SessionDep,
    tenant_slug: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        ),
    ] = None,
    tenant_name: Annotated[
        str | None,
        Query(min_length=1, max_length=200),
    ] = None,
) -> OidcAuthorizeResponse:
    return await _begin_oidc(
        request=request,
        response=response,
        session=session,
        purpose="login",
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
    )


@router.get("/oidc/bind/authorize", response_model=OidcAuthorizeResponse)
async def oidc_bind_authorize(
    request: Request,
    response: Response,
    principal: PrincipalDep,
    session: SessionDep,
) -> OidcAuthorizeResponse:
    user = await session.get(User, principal.user_id)
    if user is None or user.email_verified_at is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "EMAIL_VERIFICATION_REQUIRED"},
        )
    return await _begin_oidc(
        request=request,
        response=response,
        session=session,
        purpose="bind",
        binding_user_id=principal.user_id,
        binding_tenant_id=principal.tenant_id,
    )


async def _consume_oidc_transaction(
    request: Request,
    response: Response,
    session: AsyncSession,
    state: str,
) -> tuple[OidcLoginTransaction, str, str]:
    _, cipher = _oidc_unavailable(request)
    transaction = await session.scalar(
        select(OidcLoginTransaction)
        .where(OidcLoginTransaction.state_hash == cipher.state_digest(state))
        .with_for_update()
    )
    now = utcnow()
    if (
        transaction is None
        or transaction.consumed_at is not None
        or _aware(transaction.expires_at) <= now
    ):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_OR_EXPIRED_OIDC_STATE"},
        )
    browser_binding = request.cookies.get(_OIDC_BROWSER_COOKIE, "")
    expected_browser_hash = cipher.state_digest(f"browser:{browser_binding}")
    if not browser_binding or not secrets.compare_digest(
        transaction.browser_binding_hash,
        expected_browser_hash,
    ):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_OR_EXPIRED_OIDC_STATE"},
        )
    settings = cast(Settings, request.app.state.settings)
    response.delete_cookie(
        _OIDC_BROWSER_COOKIE,
        path="/v1/auth/oidc/callback",
        secure=settings.effective_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    transaction.consumed_at = now
    try:
        nonce, verifier = cipher.decrypt(transaction.encrypted_secrets)
    except OidcProtocolError:
        await session.commit()
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_OR_EXPIRED_OIDC_STATE"},
        ) from None
    await session.commit()
    return transaction, nonce, verifier


async def _select_membership(
    session: AsyncSession,
    *,
    user: User,
    tenant_slug: str | None,
) -> Membership:
    await set_rls_context(session, user_id=user.id)
    memberships = list(
        await session.scalars(
            select(Membership)
            .where(Membership.user_id == user.id)
            .order_by(Membership.created_at.asc(), Membership.tenant_id.asc())
        )
    )
    if not memberships:
        raise HTTPException(status_code=403, detail={"code": "NO_TENANT_MEMBERSHIP"})
    if tenant_slug is None:
        if len(memberships) != 1:
            raise HTTPException(
                status_code=409,
                detail={"code": "WORKSPACE_SELECTION_REQUIRED"},
            )
        return memberships[0]
    for membership in memberships:
        await set_rls_context(
            session,
            tenant_id=membership.tenant_id,
            user_id=user.id,
        )
        tenant = await session.scalar(
            select(Tenant).where(
                Tenant.id == membership.tenant_id,
                Tenant.slug == tenant_slug,
            )
        )
        if tenant is not None:
            return membership
    raise HTTPException(
        status_code=403,
        detail={"code": "WORKSPACE_NOT_AVAILABLE"},
    )


async def _oidc_account(
    request: Request,
    session: AsyncSession,
    *,
    transaction: OidcLoginTransaction,
    issuer: str,
    subject: str,
    email: str,
    display_name: str,
) -> tuple[User, Membership, bool]:
    identity = await session.scalar(
        select(OidcIdentity)
        .where(
            OidcIdentity.issuer == issuer,
            OidcIdentity.subject == subject,
        )
        .with_for_update()
    )
    if transaction.purpose == "bind":
        if transaction.binding_user_id is None or transaction.binding_tenant_id is None:
            raise HTTPException(status_code=400, detail={"code": "OIDC_BIND_INVALID"})
        await set_rls_context(
            session,
            tenant_id=transaction.binding_tenant_id,
            user_id=transaction.binding_user_id,
        )
        user = await session.scalar(
            select(User).where(
                User.id == transaction.binding_user_id,
                User.is_active.is_(True),
            )
        )
        membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == transaction.binding_tenant_id,
                Membership.user_id == transaction.binding_user_id,
            )
        )
        if user is None or membership is None:
            raise HTTPException(status_code=400, detail={"code": "OIDC_BIND_INVALID"})
        if identity is not None and identity.user_id != user.id:
            raise HTTPException(
                status_code=409,
                detail={"code": "OIDC_IDENTITY_ALREADY_BOUND"},
            )
        if identity is None:
            identity = OidcIdentity(
                user_id=user.id,
                issuer=issuer,
                subject=subject,
                email_at_binding=email,
            )
            session.add(identity)
            await session.flush()
        await audit(
            session,
            tenant_id=membership.tenant_id,
            actor_id=user.id,
            action="auth.oidc_identity_bound",
            target_type="oidc_identity",
            target_id=str(identity.id),
            metadata={"issuer": issuer},
        )
        return user, membership, True

    if identity is not None:
        user = await session.scalar(
            select(User).where(
                User.id == identity.user_id,
                User.is_active.is_(True),
            )
        )
        if user is None:
            raise HTTPException(status_code=401, detail={"code": "ACCOUNT_DISABLED"})
        identity.last_login_at = utcnow()
        membership = await _select_membership(
            session,
            user=user,
            tenant_slug=transaction.tenant_slug,
        )
        return user, membership, False

    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "OIDC_ACCOUNT_BINDING_REQUIRED"},
        )
    settings = cast(Settings, request.app.state.settings)
    if not settings.allow_public_registration:
        raise HTTPException(
            status_code=403,
            detail={"code": "PUBLIC_REGISTRATION_DISABLED"},
        )
    if not transaction.tenant_name:
        raise HTTPException(
            status_code=409,
            detail={"code": "OIDC_REGISTRATION_DETAILS_REQUIRED"},
        )
    tenant_id = uuid.uuid4()
    await set_rls_context(session, tenant_id=tenant_id)
    tenant = Tenant(
        id=tenant_id,
        slug=_slug(transaction.tenant_name),
        name=transaction.tenant_name,
        data_retention_days=settings.default_retention_days,
        private_mode=settings.private_mode,
        training_opt_in=settings.training_opt_in_default,
    )
    user = User(
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(64)),
        display_name=display_name,
        email_verified_at=utcnow(),
    )
    session.add_all([tenant, user])
    await session.flush()
    membership = Membership(
        tenant_id=tenant.id,
        user_id=user.id,
        role="owner",
    )
    session.add(membership)
    await session.flush()
    identity = OidcIdentity(
        user_id=user.id,
        issuer=issuer,
        subject=subject,
        email_at_binding=email,
        last_login_at=utcnow(),
    )
    session.add(identity)
    await credit_entry(
        session,
        tenant_id=tenant.id,
        operation_key="bootstrap:verified-free-credit",
        entry_type="grant",
        credits=Decimal("50"),
    )
    await audit(
        session,
        tenant_id=tenant.id,
        actor_id=user.id,
        action="auth.oidc_register",
        target_type="tenant",
        target_id=str(tenant.id),
        metadata={"issuer": issuer},
    )
    return user, membership, True


@router.get(
    "/oidc/callback",
    response_model=SessionResponse | MfaRequiredResponse,
)
async def oidc_callback(
    request: Request,
    response: Response,
    session: SessionDep,
    code: Annotated[str, Query(min_length=1, max_length=4096)],
    state: Annotated[str, Query(min_length=32, max_length=4096)],
) -> SessionResponse | MfaRequiredResponse:
    client, _ = _oidc_unavailable(request)
    transaction, nonce, verifier = await _consume_oidc_transaction(
        request,
        response,
        session,
        state,
    )
    try:
        claims = await client.exchange_code(
            code=code,
            code_verifier=verifier,
            expected_nonce=nonce,
        )
    except OidcProtocolError as exc:
        status_code = 503 if exc.code == "OIDC_PROVIDER_UNAVAILABLE" else 401
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code},
        ) from None
    try:
        email = normalize_public_email(claims.email.casefold().strip())
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={"code": "OIDC_CLAIMS_INVALID"},
        ) from None
    try:
        user, membership, bound = await _oidc_account(
            request,
            session,
            transaction=transaction,
            issuer=claims.issuer,
            subject=claims.subject,
            email=email,
            display_name=claims.display_name,
        )
        await set_rls_context(
            session,
            tenant_id=membership.tenant_id,
            user_id=user.id,
        )
        pending = await begin_mfa_login(
            request=request,
            response=response,
            session=session,
            user=user,
            membership=membership,
            auth_method="oidc",
        )
        await audit(
            session,
            tenant_id=membership.tenant_id,
            actor_id=user.id,
            action="auth.oidc_login",
            target_type="user",
            target_id=str(user.id),
            metadata={"issuer": claims.issuer, "new_binding": bound},
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "OIDC_ACCOUNT_CONFLICT"},
        ) from None
    if pending is not None:
        return pending
    _set_session_cookie(
        response,
        user=user,
        membership=membership,
        settings=cast(Settings, request.app.state.settings),
    )
    return _session_response(user, membership)
