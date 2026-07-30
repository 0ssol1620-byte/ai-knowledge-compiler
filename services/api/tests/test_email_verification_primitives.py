# ruff: noqa: S105
"""One-time token and delivery-boundary evidence for email verification."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from akc_api.abuse import IdentityHasher
from akc_api.verification import (
    DevelopmentCaptureProvider,
    ResendVerificationDeliveryProvider,
    UnavailableVerificationDeliveryProvider,
    VerificationConfigurationError,
    VerificationDeliveryError,
    VerificationMessage,
    VerificationPayloadCipher,
    VerificationTokenCodec,
    VerificationTokenStatus,
    validate_token_envelope,
    verification_token_status,
)
from cryptography.fernet import Fernet

_TOKEN_SECRET = "verification-secret-that-is-longer-than-thirty-two-bytes"
_IDENTITY_SECRET = "identity-secret-that-is-more-than-thirty-two-bytes"


def test_token_is_hashed_opaque_expiring_and_repr_safe() -> None:
    codec = VerificationTokenCodec(_TOKEN_SECRET, ttl_seconds=900)
    tenant_id = uuid.uuid4()
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

    issued = codec.issue(tenant_id=tenant_id, now=now)

    assert issued.plaintext.startswith(f"akcv1.{tenant_id.hex}.")
    assert issued.digest != issued.plaintext
    assert issued.plaintext not in repr(issued)
    assert codec.tenant_hint(issued.plaintext) == tenant_id
    assert codec.matches(issued.plaintext, issued.digest) is True
    assert issued.expires_at == now + timedelta(minutes=15)


def test_tampered_expired_and_replayed_tokens_are_not_valid() -> None:
    codec = VerificationTokenCodec(_TOKEN_SECRET, ttl_seconds=900)
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    issued = codec.issue(tenant_id=uuid.uuid4(), now=now)

    assert (
        verification_token_status(
            codec=codec,
            plaintext=issued.plaintext + "x",
            expected_digest=issued.digest,
            expires_at=issued.expires_at,
            consumed_at=None,
            now=now,
        )
        is VerificationTokenStatus.INVALID
    )
    assert (
        verification_token_status(
            codec=codec,
            plaintext=issued.plaintext,
            expected_digest=issued.digest,
            expires_at=issued.expires_at,
            consumed_at=None,
            now=issued.expires_at,
        )
        is VerificationTokenStatus.EXPIRED
    )
    assert (
        verification_token_status(
            codec=codec,
            plaintext=issued.plaintext,
            expected_digest=issued.digest,
            expires_at=issued.expires_at,
            consumed_at=now,
            now=now,
        )
        is VerificationTokenStatus.CONSUMED
    )


def test_outbox_encrypts_recipient_and_token_and_authenticates_metadata() -> None:
    codec = VerificationTokenCodec(_TOKEN_SECRET)
    hasher = IdentityHasher(_IDENTITY_SECRET)
    cipher = VerificationPayloadCipher(
        encryption_key=Fernet.generate_key(),
        identity_hasher=hasher,
    )
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    issued = codec.issue(tenant_id=tenant_id)
    message = VerificationMessage(
        tenant_id=tenant_id,
        user_id=user_id,
        recipient_email="Owner@Example.com",
        token=issued.plaintext,
        expires_at=issued.expires_at,
    )

    envelope = cipher.encrypt(message, token_digest=issued.digest)

    assert b"Owner@Example.com" not in envelope.encrypted_payload
    assert issued.plaintext.encode() not in envelope.encrypted_payload
    assert "Owner@Example.com" not in repr(envelope)
    assert issued.plaintext not in repr(message)
    assert envelope.recipient_pseudonym == hasher.pseudonymize(
        purpose="email-recipient",
        value="owner@example.com",
    )
    decrypted = cipher.decrypt(envelope)
    assert decrypted == message
    validate_token_envelope(codec=codec, message=decrypted, envelope=envelope)

    wrong_codec = VerificationTokenCodec("different-secret-that-is-also-at-least-32-bytes")
    with pytest.raises(VerificationDeliveryError):
        validate_token_envelope(
            codec=wrong_codec,
            message=decrypted,
            envelope=envelope,
        )


async def test_development_capture_is_bounded_and_forbidden_in_production() -> None:
    with pytest.raises(VerificationConfigurationError):
        DevelopmentCaptureProvider(environment="production")

    codec = VerificationTokenCodec(_TOKEN_SECRET)
    provider = DevelopmentCaptureProvider(environment="test", max_messages=1)
    first = VerificationMessage(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        recipient_email="first@example.com",
        token=codec.issue(tenant_id=uuid.uuid4()).plaintext,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    second = VerificationMessage(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        recipient_email="second@example.com",
        token=codec.issue(tenant_id=uuid.uuid4()).plaintext,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )

    await provider.deliver(first)
    receipt = await provider.deliver(second)

    assert receipt.provider == "development-capture"
    assert await provider.latest_for("first@example.com") is None
    assert await provider.latest_for("SECOND@example.com") == second
    assert await provider.take_for("second@example.com") == second
    assert await provider.latest_for("second@example.com") is None


async def test_unavailable_delivery_never_claims_success() -> None:
    codec = VerificationTokenCodec(_TOKEN_SECRET)
    tenant_id = uuid.uuid4()
    issued = codec.issue(tenant_id=tenant_id)
    provider = UnavailableVerificationDeliveryProvider()
    with pytest.raises(VerificationDeliveryError):
        await provider.deliver(
            VerificationMessage(
                tenant_id=tenant_id,
                user_id=uuid.uuid4(),
                recipient_email="owner@example.com",
                token=issued.plaintext,
                expires_at=issued.expires_at,
            )
        )


async def test_resend_adapter_is_mocked_and_does_not_leak_in_errors() -> None:
    codec = VerificationTokenCodec(_TOKEN_SECRET)
    tenant_id = uuid.uuid4()
    issued = codec.issue(tenant_id=tenant_id)
    message = VerificationMessage(
        tenant_id=tenant_id,
        user_id=uuid.uuid4(),
        recipient_email="owner@example.com",
        token=issued.plaintext,
        expires_at=issued.expires_at,
    )
    seen_request = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = True
        assert request.url == "https://api.resend.com/emails"
        payload = json.loads(await request.aread())
        assert isinstance(payload, dict)
        rendered = f"{payload.get('text')} {payload.get('html')}"
        assert "/verify-email?verification=1#token=" in rendered
        assert "/verify-email?token=" not in rendered
        return httpx.Response(200, json={"id": "mock-message-id"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ResendVerificationDeliveryProvider(
        api_key="mock-provider-key",
        sender="verify@example.com",
        public_base_url="https://app.example.com",
        client=client,
    )
    try:
        receipt = await provider.deliver(message)
    finally:
        await client.aclose()

    assert seen_request is True
    assert receipt.message_id == "mock-message-id"
    assert receipt.provider == "resend"


def test_production_provider_rejects_non_https_public_url() -> None:
    with pytest.raises(VerificationConfigurationError):
        ResendVerificationDeliveryProvider(
            api_key="mock-provider-key",
            sender="verify@example.com",
            public_base_url="http://app.example.com",
        )
