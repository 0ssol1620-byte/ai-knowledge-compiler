"""Production-oriented team collaboration and invitation API.

Invitation tokens are one-time credentials.  Only a domain-separated HMAC is
stored in the invitation row; the recipient and token are persisted solely in
the existing encrypted email-delivery outbox boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.abuse import IdentityHasher
from akc_api.auth_api import begin_mfa_login
from akc_api.database import get_session, set_rls_context
from akc_api.idempotency import idempotent_mutation
from akc_api.models import ApiKey, Membership, Tenant, User, utcnow
from akc_api.schemas import MfaRequiredResponse, SessionResponse
from akc_api.security import (
    Principal,
    create_session_token,
    hash_password,
    require_roles,
    verify_password,
)
from akc_api.services import audit
from akc_api.settings import Settings
from akc_api.team_models import TeamInvitation, TeamInvitationDelivery
from akc_api.verification import (
    VerificationDeliveryError,
    VerificationDeliveryProvider,
    VerificationMessage,
    VerificationOutboxEnvelope,
    VerificationPayloadCipher,
    normalize_public_email,
)

router = APIRouter(prefix="/v1/team", tags=["team"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
TeamAdminDep = Annotated[Principal, Depends(require_roles("owner", "admin"))]

TeamRole = Literal["owner", "admin", "editor", "reviewer", "viewer", "billing"]
_ALL_ROLES = frozenset({"owner", "admin", "editor", "reviewer", "viewer", "billing"})
_ADMIN_MANAGED_ROLES = frozenset({"editor", "reviewer", "viewer", "billing"})
_TOKEN_PATTERN = re.compile(r"^akci1\.([0-9a-f]{32})\.([A-Za-z0-9_-]{40,128})$")


class WireModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class InvitationCreate(WireModel):
    email: str = Field(min_length=3, max_length=320)
    role: TeamRole = "viewer"


class InvitationResponse(WireModel):
    id: uuid.UUID
    email: str | None
    role: TeamRole
    status: Literal["pending", "accepted", "cancelled", "expired"]
    invited_by: uuid.UUID
    accepted_by: uuid.UUID | None
    expires_at: datetime
    accepted_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime


class InvitationListResponse(WireModel):
    items: list[InvitationResponse]


class InvitationAccept(WireModel):
    token: SecretStr = Field(min_length=48, max_length=256, repr=False)
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=12, max_length=1024, repr=False)
    display_name: str = Field(min_length=1, max_length=200)


class MemberResponse(WireModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: TeamRole
    email_verified: bool
    joined_at: datetime


class MemberListResponse(WireModel):
    items: list[MemberResponse]


class MemberRolePatch(WireModel):
    role: TeamRole


@dataclass(frozen=True, slots=True)
class IssuedInvitationToken:
    plaintext: str = field(repr=False)
    digest: str
    tenant_hint: uuid.UUID
    expires_at: datetime


class TeamInvitationTokenCodec:
    """Issue opaque team tokens and store only a domain-separated HMAC."""

    def __init__(self, secret: str | bytes, *, ttl_seconds: int) -> None:
        value = secret.encode("utf-8") if isinstance(secret, str) else secret
        if len(value) < 32:
            raise ValueError("team invitation HMAC secret must contain at least 32 bytes")
        if not 300 <= ttl_seconds <= 2_592_000:
            raise ValueError("team invitation TTL must be between 5 minutes and 30 days")
        self._secret = value
        self._ttl_seconds = ttl_seconds

    def digest(self, plaintext: str) -> str:
        return hmac.new(
            self._secret,
            b"team-invitation\x00" + plaintext.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def issue(
        self,
        *,
        tenant_id: uuid.UUID,
        now: datetime | None = None,
    ) -> IssuedInvitationToken:
        issued_at = _aware(now or utcnow())
        plaintext = f"akci1.{tenant_id.hex}.{secrets.token_urlsafe(32)}"
        return IssuedInvitationToken(
            plaintext=plaintext,
            digest=self.digest(plaintext),
            tenant_hint=tenant_id,
            expires_at=issued_at + timedelta(seconds=self._ttl_seconds),
        )

    def tenant_hint(self, plaintext: str) -> uuid.UUID | None:
        matched = _TOKEN_PATTERN.fullmatch(plaintext)
        if matched is None:
            return None
        try:
            return uuid.UUID(hex=matched.group(1))
        except ValueError:
            return None

    def matches(self, plaintext: str, expected_digest: str) -> bool:
        if _TOKEN_PATTERN.fullmatch(plaintext) is None:
            return False
        return hmac.compare_digest(self.digest(plaintext), expected_digest)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _generic_invitation_error() -> HTTPException:
    # Every public invitation failure deliberately collapses to one response.
    return HTTPException(
        status_code=400,
        detail={"code": "INVALID_OR_EXPIRED_INVITATION"},
    )


def _recipient_pseudonym(request: Request, email: str) -> str:
    hasher = cast(IdentityHasher, request.app.state.identity_hasher)
    return hasher.pseudonymize(
        purpose="email-recipient",
        value=email,
    )


async def _verified_actor(
    session: AsyncSession,
    principal: Principal,
) -> tuple[User, Membership]:
    user = await session.scalar(
        select(User).where(
            User.id == principal.user_id,
            User.is_active.is_(True),
        )
    )
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == principal.tenant_id,
            Membership.user_id == principal.user_id,
        )
    )
    if user is None or membership is None:
        raise HTTPException(status_code=401, detail={"code": "SESSION_REVOKED"})
    if user.email_verified_at is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "EMAIL_VERIFICATION_REQUIRED"},
        )
    return user, membership


async def _lock_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "WORKSPACE_NOT_FOUND"})
    return tenant


def _can_manage_role(actor_role: str, target_role: str) -> bool:
    if actor_role == "owner":
        return target_role in _ALL_ROLES
    return actor_role == "admin" and target_role in _ADMIN_MANAGED_ROLES


def _authorize_assignment(actor_role: str, assigned_role: str) -> None:
    if not _can_manage_role(actor_role, assigned_role):
        raise HTTPException(
            status_code=403,
            detail={"code": "ROLE_ESCALATION_DENIED"},
        )


def _invitation_response(
    invitation: TeamInvitation,
    *,
    email: str | None,
    now: datetime | None = None,
) -> InvitationResponse:
    status = invitation.status
    if status == "pending" and _aware(invitation.expires_at) <= _aware(now or utcnow()):
        status = "expired"
    return InvitationResponse(
        id=invitation.id,
        email=email,
        role=cast(TeamRole, invitation.role),
        status=cast(Literal["pending", "accepted", "cancelled", "expired"], status),
        invited_by=invitation.invited_by,
        accepted_by=invitation.accepted_by,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        cancelled_at=invitation.cancelled_at,
        created_at=invitation.created_at,
    )


def _delivery_envelope(
    invitation: TeamInvitation,
    delivery: TeamInvitationDelivery,
) -> VerificationOutboxEnvelope:
    return VerificationOutboxEnvelope(
        tenant_id=invitation.tenant_id,
        user_id=invitation.id,
        recipient_pseudonym=delivery.recipient_pseudonym,
        token_digest=invitation.token_hash,
        encrypted_payload=delivery.encrypted_payload,
        expires_at=delivery.expires_at,
    )


def _decrypt_invitation_message(
    *,
    invitation: TeamInvitation,
    delivery: TeamInvitationDelivery,
    cipher: VerificationPayloadCipher,
    codec: TeamInvitationTokenCodec,
) -> VerificationMessage:
    message = cipher.decrypt(_delivery_envelope(invitation, delivery))
    if (
        message.purpose != "team_invitation"
        or message.tenant_id != invitation.tenant_id
        or message.user_id != invitation.id
        or not codec.matches(message.token, invitation.token_hash)
        or not hmac.compare_digest(
            delivery.recipient_pseudonym,
            invitation.recipient_pseudonym,
        )
    ):
        raise VerificationDeliveryError("team invitation outbox metadata mismatch")
    return message


async def _deliver_team_invitation(
    session: AsyncSession,
    *,
    delivery_id: uuid.UUID,
    codec: TeamInvitationTokenCodec,
    cipher: VerificationPayloadCipher,
    provider: VerificationDeliveryProvider,
    max_attempts: int,
    retry_seconds: int,
) -> bool:
    now = utcnow()
    delivery = await session.scalar(
        select(TeamInvitationDelivery)
        .where(TeamInvitationDelivery.id == delivery_id)
        .with_for_update()
    )
    if delivery is None or delivery.status not in {"pending", "retry"}:
        return delivery is not None and delivery.status == "delivered"
    invitation = await session.scalar(
        select(TeamInvitation)
        .where(
            TeamInvitation.tenant_id == delivery.tenant_id,
            TeamInvitation.id == delivery.invitation_id,
        )
        .with_for_update()
    )
    if (
        invitation is None
        or invitation.status != "pending"
        or _aware(delivery.expires_at) <= now
        or _aware(invitation.expires_at) <= now
    ):
        delivery.status = "dead_letter"
        delivery.dead_lettered_at = now
        delivery.last_error_code = "INVITATION_NOT_DELIVERABLE"
        if invitation is not None and invitation.status == "pending":
            invitation.status = "expired"
            invitation.updated_at = now
        return False
    try:
        message = _decrypt_invitation_message(
            invitation=invitation,
            delivery=delivery,
            cipher=cipher,
            codec=codec,
        )
        receipt = await provider.deliver(message)
    except VerificationDeliveryError:
        delivery.attempts += 1
        if delivery.attempts >= max_attempts:
            delivery.status = "dead_letter"
            delivery.dead_lettered_at = now
        else:
            delivery.status = "retry"
            delivery.available_at = now + timedelta(
                seconds=retry_seconds * (2 ** max(0, delivery.attempts - 1))
            )
        delivery.last_error_code = "INVITATION_DELIVERY_FAILED"
        delivery.updated_at = now
        return False
    delivery.attempts += 1
    delivery.status = "delivered"
    delivery.provider_message_id = receipt.message_id[:200]
    delivery.delivered_at = now
    delivery.last_error_code = None
    delivery.updated_at = now
    return True


async def _dispatch_team_invitation(
    app: FastAPI,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    delivery_id: uuid.UUID,
) -> None:
    database = app.state.database
    async with database.sessions() as session:
        await set_rls_context(session, tenant_id=tenant_id, user_id=actor_id)
        delivered = await _deliver_team_invitation(
            session,
            delivery_id=delivery_id,
            codec=app.state.team_invitation_token_codec,
            cipher=app.state.verification_payload_cipher,
            provider=app.state.verification_delivery_provider,
            max_attempts=app.state.settings.verification_delivery_max_attempts,
            retry_seconds=app.state.settings.verification_delivery_retry_seconds,
        )
        await audit(
            session,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="team.invitation_delivery",
            target_type="team_invitation_delivery",
            target_id=str(delivery_id),
            metadata={"result": "delivered" if delivered else "queued_retry"},
        )
        await session.commit()


@router.post("/invitations", response_model=InvitationResponse, status_code=201)
@idempotent_mutation
async def create_invitation(
    payload: InvitationCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    principal: TeamAdminDep,
    session: SessionDep,
) -> InvitationResponse:
    _, actor_membership = await _verified_actor(session, principal)
    _authorize_assignment(actor_membership.role, payload.role)
    try:
        email = normalize_public_email(payload.email)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_EMAIL"},
        ) from exc
    recipient_pseudonym = _recipient_pseudonym(request, email)
    await _lock_tenant(session, principal.tenant_id)

    existing_user = await session.scalar(select(User).where(User.email == email))
    if existing_user is not None:
        existing_membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == principal.tenant_id,
                Membership.user_id == existing_user.id,
            )
        )
        if existing_membership is not None:
            raise HTTPException(
                status_code=409,
                detail={"code": "MEMBER_ALREADY_EXISTS"},
            )

    now = utcnow()
    pending = await session.scalar(
        select(TeamInvitation)
        .where(
            TeamInvitation.tenant_id == principal.tenant_id,
            TeamInvitation.recipient_pseudonym == recipient_pseudonym,
            TeamInvitation.status == "pending",
        )
        .with_for_update()
    )
    if pending is not None and _aware(pending.expires_at) > now:
        raise HTTPException(
            status_code=409,
            detail={"code": "INVITATION_ALREADY_PENDING"},
        )
    if pending is not None:
        pending.status = "expired"
        pending.updated_at = now
        prior_delivery = await session.scalar(
            select(TeamInvitationDelivery).where(
                TeamInvitationDelivery.tenant_id == principal.tenant_id,
                TeamInvitationDelivery.invitation_id == pending.id,
            )
        )
        if prior_delivery is not None and prior_delivery.status in {"pending", "retry"}:
            prior_delivery.status = "dead_letter"
            prior_delivery.dead_lettered_at = now
            prior_delivery.last_error_code = "INVITATION_EXPIRED"
        # Release the partial unique active-recipient slot before inserting
        # the replacement invitation in the same transaction.
        await session.flush()

    codec = cast(
        TeamInvitationTokenCodec,
        request.app.state.team_invitation_token_codec,
    )
    issued = codec.issue(tenant_id=principal.tenant_id, now=now)
    invitation = TeamInvitation(
        tenant_id=principal.tenant_id,
        invited_by=principal.user_id,
        recipient_pseudonym=recipient_pseudonym,
        token_hash=issued.digest,
        role=payload.role,
        expires_at=issued.expires_at,
    )
    session.add(invitation)
    await session.flush()

    cipher = cast(
        VerificationPayloadCipher,
        request.app.state.verification_payload_cipher,
    )
    message = VerificationMessage(
        tenant_id=principal.tenant_id,
        user_id=invitation.id,
        recipient_email=email,
        token=issued.plaintext,
        expires_at=issued.expires_at,
        purpose="team_invitation",
    )
    envelope = cipher.encrypt(message, token_digest=issued.digest)
    delivery = TeamInvitationDelivery(
        tenant_id=principal.tenant_id,
        invitation_id=invitation.id,
        recipient_pseudonym=envelope.recipient_pseudonym,
        encrypted_payload=envelope.encrypted_payload,
        provider=request.app.state.settings.email_verification_provider,
        expires_at=issued.expires_at,
    )
    session.add(delivery)
    await session.flush()
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="team.invitation_created",
        target_type="team_invitation",
        target_id=str(invitation.id),
        metadata={"role": payload.role},
    )
    await session.commit()
    background_tasks.add_task(
        _dispatch_team_invitation,
        request.app,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        delivery_id=delivery.id,
    )
    return _invitation_response(invitation, email=email)


@router.get("/invitations", response_model=InvitationListResponse)
async def list_invitations(
    request: Request,
    principal: TeamAdminDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> InvitationListResponse:
    await _verified_actor(session, principal)
    invitations = list(
        await session.scalars(
            select(TeamInvitation)
            .where(TeamInvitation.tenant_id == principal.tenant_id)
            .order_by(TeamInvitation.created_at.desc(), TeamInvitation.id.desc())
            .limit(limit)
        )
    )
    if not invitations:
        return InvitationListResponse(items=[])
    deliveries = list(
        await session.scalars(
            select(TeamInvitationDelivery).where(
                TeamInvitationDelivery.tenant_id == principal.tenant_id,
                TeamInvitationDelivery.invitation_id.in_(
                    [invitation.id for invitation in invitations]
                ),
            )
        )
    )
    by_invitation = {delivery.invitation_id: delivery for delivery in deliveries}
    cipher = cast(
        VerificationPayloadCipher,
        request.app.state.verification_payload_cipher,
    )
    codec = cast(
        TeamInvitationTokenCodec,
        request.app.state.team_invitation_token_codec,
    )
    items: list[InvitationResponse] = []
    for invitation in invitations:
        email: str | None = None
        delivery = by_invitation.get(invitation.id)
        if delivery is not None:
            try:
                email = _decrypt_invitation_message(
                    invitation=invitation,
                    delivery=delivery,
                    cipher=cipher,
                    codec=codec,
                ).recipient_email
            except VerificationDeliveryError:
                email = None
        items.append(_invitation_response(invitation, email=email))
    return InvitationListResponse(items=items)


@router.delete("/invitations/{invitation_id}", status_code=204)
@idempotent_mutation
async def cancel_invitation(
    invitation_id: uuid.UUID,
    principal: TeamAdminDep,
    session: SessionDep,
) -> Response:
    _, actor_membership = await _verified_actor(session, principal)
    await _lock_tenant(session, principal.tenant_id)
    invitation = await session.scalar(
        select(TeamInvitation)
        .where(
            TeamInvitation.tenant_id == principal.tenant_id,
            TeamInvitation.id == invitation_id,
        )
        .with_for_update()
    )
    if invitation is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "INVITATION_NOT_FOUND"},
        )
    if not _can_manage_role(actor_membership.role, invitation.role):
        raise HTTPException(
            status_code=403,
            detail={"code": "ROLE_ESCALATION_DENIED"},
        )
    if invitation.status == "accepted":
        raise HTTPException(
            status_code=409,
            detail={"code": "INVITATION_ALREADY_ACCEPTED"},
        )
    if invitation.status not in {"cancelled", "expired"}:
        now = utcnow()
        invitation.status = "cancelled"
        invitation.cancelled_at = now
        invitation.updated_at = now
        delivery = await session.scalar(
            select(TeamInvitationDelivery).where(
                TeamInvitationDelivery.tenant_id == principal.tenant_id,
                TeamInvitationDelivery.invitation_id == invitation.id,
            )
        )
        if delivery is not None and delivery.status in {"pending", "retry"}:
            delivery.status = "dead_letter"
            delivery.dead_lettered_at = now
            delivery.last_error_code = "INVITATION_CANCELLED"
        await audit(
            session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action="team.invitation_cancelled",
            target_type="team_invitation",
            target_id=str(invitation.id),
            metadata={"role": invitation.role},
        )
        await session.commit()
    return Response(status_code=204)


@router.post(
    "/invitations/accept",
    response_model=SessionResponse | MfaRequiredResponse,
)
async def accept_invitation(
    payload: InvitationAccept,
    response: Response,
    request: Request,
    session: SessionDep,
) -> SessionResponse | MfaRequiredResponse:
    plaintext = payload.token.get_secret_value()
    codec = cast(
        TeamInvitationTokenCodec,
        request.app.state.team_invitation_token_codec,
    )
    tenant_id = codec.tenant_hint(plaintext)
    if tenant_id is None:
        raise _generic_invitation_error()
    await set_rls_context(session, tenant_id=tenant_id)
    invitation = await session.scalar(
        select(TeamInvitation)
        .where(
            TeamInvitation.tenant_id == tenant_id,
            TeamInvitation.token_hash == codec.digest(plaintext),
        )
        .with_for_update()
    )
    now = utcnow()
    if (
        invitation is None
        or invitation.status != "pending"
        or _aware(invitation.expires_at) <= now
        or not codec.matches(plaintext, invitation.token_hash)
    ):
        if (
            invitation is not None
            and invitation.status == "pending"
            and _aware(invitation.expires_at) <= now
        ):
            invitation.status = "expired"
            invitation.updated_at = now
            await session.commit()
        raise _generic_invitation_error()
    try:
        email = normalize_public_email(payload.email)
    except ValueError as exc:
        raise _generic_invitation_error() from exc
    if not hmac.compare_digest(
        _recipient_pseudonym(request, email),
        invitation.recipient_pseudonym,
    ):
        raise _generic_invitation_error()
    delivery = await session.scalar(
        select(TeamInvitationDelivery).where(
            TeamInvitationDelivery.tenant_id == tenant_id,
            TeamInvitationDelivery.invitation_id == invitation.id,
        )
    )
    if delivery is None:
        raise _generic_invitation_error()
    try:
        message = _decrypt_invitation_message(
            invitation=invitation,
            delivery=delivery,
            cipher=request.app.state.verification_payload_cipher,
            codec=codec,
        )
    except VerificationDeliveryError as exc:
        raise _generic_invitation_error() from exc
    if not hmac.compare_digest(
        message.recipient_email.encode("utf-8"),
        email.encode("utf-8"),
    ) or not hmac.compare_digest(message.token, plaintext):
        raise _generic_invitation_error()

    user = await session.scalar(select(User).where(User.email == email).with_for_update())
    password = payload.password.get_secret_value()
    new_user = user is None
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=payload.display_name,
            email_verified_at=now,
        )
        session.add(user)
        await session.flush()
    elif (
        not user.is_active
        or user.email_verified_at is None
        or not verify_password(user.password_hash, password)
    ):
        raise _generic_invitation_error()

    membership = await session.scalar(
        select(Membership)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user.id,
        )
        .with_for_update()
    )
    if membership is None:
        membership = Membership(
            tenant_id=tenant_id,
            user_id=user.id,
            role=invitation.role,
        )
        session.add(membership)
        await session.flush()

    accepted_id = await session.scalar(
        update(TeamInvitation)
        .where(
            TeamInvitation.id == invitation.id,
            TeamInvitation.tenant_id == tenant_id,
            TeamInvitation.status == "pending",
            TeamInvitation.expires_at > now,
        )
        .values(
            status="accepted",
            accepted_by=user.id,
            accepted_at=now,
            updated_at=now,
        )
        .returning(TeamInvitation.id)
        .execution_options(synchronize_session=False)
    )
    if accepted_id is None:
        raise _generic_invitation_error()
    await audit(
        session,
        tenant_id=tenant_id,
        actor_id=user.id,
        action="team.invitation_accepted",
        target_type="team_invitation",
        target_id=str(invitation.id),
        metadata={"role": membership.role, "new_user": new_user},
    )
    pending_mfa = await begin_mfa_login(
        request=request,
        response=response,
        session=session,
        user=user,
        membership=membership,
        auth_method="password",
    )
    await session.commit()
    if pending_mfa is not None:
        return pending_mfa
    settings = cast(Settings, request.app.state.settings)
    session_token = create_session_token(
        user_id=user.id,
        tenant_id=tenant_id,
        roles=[membership.role],
        settings=settings,
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        httponly=True,
        secure=settings.effective_cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.access_token_minutes * 60,
        path="/",
    )
    return SessionResponse(
        user_id=user.id,
        tenant_id=tenant_id,
        email=user.email,
        display_name=user.display_name,
        roles=[membership.role],
        email_verified=True,
    )


@router.get("/members", response_model=MemberListResponse)
async def list_members(
    principal: TeamAdminDep,
    session: SessionDep,
) -> MemberListResponse:
    await _verified_actor(session, principal)
    rows = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.tenant_id == principal.tenant_id)
            .order_by(Membership.created_at.asc(), Membership.user_id.asc())
        )
    ).all()
    return MemberListResponse(
        items=[
            MemberResponse(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                role=cast(TeamRole, membership.role),
                email_verified=user.email_verified_at is not None,
                joined_at=membership.created_at,
            )
            for membership, user in rows
        ]
    )


async def _locked_actor_and_target(
    session: AsyncSession,
    *,
    principal: Principal,
    target_user_id: uuid.UUID,
) -> tuple[Membership, Membership]:
    if target_user_id == principal.user_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "SELF_MEMBERSHIP_CHANGE_DENIED"},
        )
    await _lock_tenant(session, principal.tenant_id)
    memberships = list(
        await session.scalars(
            select(Membership)
            .where(
                Membership.tenant_id == principal.tenant_id,
                Membership.user_id.in_([principal.user_id, target_user_id]),
            )
            .with_for_update()
        )
    )
    by_user = {membership.user_id: membership for membership in memberships}
    actor = by_user.get(principal.user_id)
    target = by_user.get(target_user_id)
    if actor is None:
        raise HTTPException(status_code=401, detail={"code": "SESSION_REVOKED"})
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "MEMBER_NOT_FOUND"})
    if not _can_manage_role(actor.role, target.role):
        raise HTTPException(
            status_code=403,
            detail={"code": "ROLE_ESCALATION_DENIED"},
        )
    return actor, target


async def _protect_last_owner(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    target: Membership,
) -> None:
    if target.role != "owner":
        return
    owner_count = await session.scalar(
        select(func.count(Membership.user_id)).where(
            Membership.tenant_id == tenant_id,
            Membership.role == "owner",
        )
    )
    if int(owner_count or 0) <= 1:
        raise HTTPException(
            status_code=409,
            detail={"code": "LAST_OWNER_REQUIRED"},
        )


@router.patch("/members/{user_id}", response_model=MemberResponse)
@idempotent_mutation
async def change_member_role(
    user_id: uuid.UUID,
    payload: MemberRolePatch,
    principal: TeamAdminDep,
    session: SessionDep,
) -> MemberResponse:
    await _verified_actor(session, principal)
    actor, target = await _locked_actor_and_target(
        session,
        principal=principal,
        target_user_id=user_id,
    )
    _authorize_assignment(actor.role, payload.role)
    if target.role == "owner" and payload.role != "owner":
        await _protect_last_owner(
            session,
            tenant_id=principal.tenant_id,
            target=target,
        )
    previous_role = target.role
    target.role = payload.role
    target_user = await session.scalar(
        select(User).where(User.id == target.user_id, User.is_active.is_(True))
    )
    if target_user is None:
        raise HTTPException(status_code=404, detail={"code": "MEMBER_NOT_FOUND"})
    if previous_role != payload.role:
        await audit(
            session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action="team.member_role_changed",
            target_type="user",
            target_id=str(target.user_id),
            metadata={"previous_role": previous_role, "role": payload.role},
        )
        await session.commit()
    return MemberResponse(
        user_id=target_user.id,
        email=target_user.email,
        display_name=target_user.display_name,
        role=target.role,
        email_verified=target_user.email_verified_at is not None,
        joined_at=target.created_at,
    )


@router.delete("/members/{user_id}", status_code=204)
@idempotent_mutation
async def remove_member(
    user_id: uuid.UUID,
    principal: TeamAdminDep,
    session: SessionDep,
) -> Response:
    await _verified_actor(session, principal)
    _, target = await _locked_actor_and_target(
        session,
        principal=principal,
        target_user_id=user_id,
    )
    await _protect_last_owner(
        session,
        tenant_id=principal.tenant_id,
        target=target,
    )
    now = utcnow()
    await session.execute(
        update(ApiKey)
        .where(
            ApiKey.tenant_id == principal.tenant_id,
            ApiKey.created_by == target.user_id,
            ApiKey.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await session.delete(target)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="team.member_removed",
        target_type="user",
        target_id=str(user_id),
        metadata={"role": target.role},
    )
    await session.commit()
    return Response(status_code=204)


__all__ = [
    "TeamInvitationTokenCodec",
    "router",
]
