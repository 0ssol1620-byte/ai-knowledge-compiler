"""Transactional issuance and delivery for email-verification messages."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.models import (
    EmailVerificationDelivery,
    EmailVerificationToken,
    utcnow,
)
from akc_api.verification import (
    VerificationDeliveryError,
    VerificationDeliveryProvider,
    VerificationMessage,
    VerificationOutboxEnvelope,
    VerificationPayloadCipher,
    VerificationTokenCodec,
    validate_token_envelope,
)


@dataclass(frozen=True, slots=True)
class VerificationEnqueued:
    token_id: uuid.UUID
    delivery_id: uuid.UUID


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def enqueue_verification(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    recipient_email: str,
    codec: VerificationTokenCodec,
    cipher: VerificationPayloadCipher,
    provider_name: str,
    invalidate_existing: bool,
) -> VerificationEnqueued:
    """Persist an HMAC token and encrypted delivery in the caller transaction."""

    now = utcnow()
    if invalidate_existing:
        await session.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.tenant_id == tenant_id,
                EmailVerificationToken.user_id == user_id,
                EmailVerificationToken.consumed_at.is_(None),
                EmailVerificationToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
        )
    issued = codec.issue(tenant_id=tenant_id, now=now)
    message = VerificationMessage(
        tenant_id=tenant_id,
        user_id=user_id,
        recipient_email=recipient_email,
        token=issued.plaintext,
        expires_at=issued.expires_at,
    )
    envelope = cipher.encrypt(message, token_digest=issued.digest)
    token_row = EmailVerificationToken(
        tenant_id=tenant_id,
        user_id=user_id,
        token_hash=issued.digest,
        expires_at=issued.expires_at,
    )
    delivery = EmailVerificationDelivery(
        tenant_id=tenant_id,
        user_id=user_id,
        token_hash=issued.digest,
        recipient_pseudonym=envelope.recipient_pseudonym,
        encrypted_payload=envelope.encrypted_payload,
        provider=provider_name,
        status="pending",
        expires_at=issued.expires_at,
    )
    session.add(token_row)
    # The outbox authenticates its encrypted payload through the token digest.
    # Flush that parent explicitly because the foreign key targets a unique
    # digest rather than the token's primary key.
    await session.flush()
    session.add(delivery)
    await session.flush()
    return VerificationEnqueued(token_id=token_row.id, delivery_id=delivery.id)


async def deliver_verification(
    session: AsyncSession,
    *,
    delivery_id: uuid.UUID,
    codec: VerificationTokenCodec,
    cipher: VerificationPayloadCipher,
    provider: VerificationDeliveryProvider,
    max_attempts: int,
    retry_seconds: int,
) -> bool:
    """Attempt one durable delivery without ever exposing plaintext to logs."""

    now = utcnow()
    row = await session.scalar(
        select(EmailVerificationDelivery)
        .where(EmailVerificationDelivery.id == delivery_id)
        .with_for_update()
    )
    if row is None or row.status not in {"pending", "retry"}:
        return row is not None and row.status == "delivered"
    if _aware(row.available_at) > now:
        return False
    token_row = await session.scalar(
        select(EmailVerificationToken)
        .where(
            EmailVerificationToken.tenant_id == row.tenant_id,
            EmailVerificationToken.token_hash == row.token_hash,
        )
        .with_for_update()
    )
    if (
        token_row is None
        or token_row.consumed_at is not None
        or token_row.invalidated_at is not None
        or _aware(row.expires_at) <= now
        or _aware(token_row.expires_at) <= now
    ):
        row.status = "dead_letter"
        row.dead_lettered_at = now
        row.last_error_code = "VERIFICATION_NOT_DELIVERABLE"
        return False
    envelope = VerificationOutboxEnvelope(
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        recipient_pseudonym=row.recipient_pseudonym,
        token_digest=row.token_hash,
        encrypted_payload=row.encrypted_payload,
        expires_at=row.expires_at,
    )
    try:
        message = cipher.decrypt(envelope)
        validate_token_envelope(codec=codec, message=message, envelope=envelope)
        receipt = await provider.deliver(message)
    except VerificationDeliveryError:
        row.attempts += 1
        if row.attempts >= max_attempts:
            row.status = "dead_letter"
            row.dead_lettered_at = now
        else:
            row.status = "retry"
            row.available_at = now + timedelta(
                seconds=retry_seconds * (2 ** max(0, row.attempts - 1))
            )
        row.last_error_code = "VERIFICATION_DELIVERY_FAILED"
        row.updated_at = now
        return False
    row.attempts += 1
    row.status = "delivered"
    row.provider_message_id = receipt.message_id[:200]
    row.delivered_at = now
    row.last_error_code = None
    row.updated_at = now
    return True
