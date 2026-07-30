"""Email-verification tokens and privacy-safe delivery primitives.

Verification token plaintext exists only at issuance and delivery boundaries.
The database-facing envelope contains an HMAC digest and encrypted payload,
never the raw token or recipient address.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import re
import secrets
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol, cast
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken

from akc_api.abuse import AbuseControlConfigurationError, IdentityHasher

_TOKEN_PATTERN = re.compile(r"^akcv1\.([0-9a-f]{32})\.([A-Za-z0-9_-]{40,128})$")


class VerificationConfigurationError(ValueError):
    """Raised when email verification cannot be configured safely."""


class VerificationDeliveryError(RuntimeError):
    """A sanitized delivery failure that contains no recipient or token."""


class VerificationTokenStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    CONSUMED = "consumed"


@dataclass(frozen=True, slots=True)
class IssuedVerificationToken:
    plaintext: str = field(repr=False)
    digest: str
    tenant_hint: uuid.UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerificationMessage:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    recipient_email: str = field(repr=False)
    token: str = field(repr=False)
    expires_at: datetime
    purpose: Literal["verify_email", "team_invitation"] = "verify_email"


@dataclass(frozen=True, slots=True)
class VerificationOutboxEnvelope:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    recipient_pseudonym: str
    token_digest: str
    encrypted_payload: bytes = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    provider: str
    message_id: str


class VerificationDeliveryProvider(Protocol):
    async def deliver(self, message: VerificationMessage) -> DeliveryReceipt:
        """Deliver one message without logging its sensitive fields."""

    async def aclose(self) -> None:
        """Release provider resources."""


class VerificationTokenCodec:
    """Issues opaque tokens and computes the only digest stored server-side."""

    def __init__(self, secret: str | bytes, *, ttl_seconds: int = 1800) -> None:
        secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
        if len(secret_bytes) < 32:
            raise VerificationConfigurationError(
                "verification HMAC secret must contain at least 32 bytes"
            )
        if not 300 <= ttl_seconds <= 86_400:
            raise VerificationConfigurationError(
                "verification token TTL must be between 5 minutes and 24 hours"
            )
        self._secret = secret_bytes
        self._ttl_seconds = ttl_seconds

    def digest(self, plaintext: str) -> str:
        return hmac.new(
            self._secret,
            b"email-verification\x00" + plaintext.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def issue(
        self,
        *,
        tenant_id: uuid.UUID,
        now: datetime | None = None,
    ) -> IssuedVerificationToken:
        issued_at = _aware_utc(now or datetime.now(UTC))
        plaintext = f"akcv1.{tenant_id.hex}.{secrets.token_urlsafe(32)}"
        return IssuedVerificationToken(
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
        actual = self.digest(plaintext)
        return hmac.compare_digest(actual, expected_digest)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def verification_token_status(
    *,
    codec: VerificationTokenCodec,
    plaintext: str,
    expected_digest: str,
    expires_at: datetime,
    consumed_at: datetime | None,
    now: datetime | None = None,
) -> VerificationTokenStatus:
    """Evaluate a row locked by the caller without revealing failure details."""

    if not codec.matches(plaintext, expected_digest):
        return VerificationTokenStatus.INVALID
    if consumed_at is not None:
        return VerificationTokenStatus.CONSUMED
    current_time = _aware_utc(now or datetime.now(UTC))
    if _aware_utc(expires_at) <= current_time:
        return VerificationTokenStatus.EXPIRED
    return VerificationTokenStatus.VALID


class VerificationPayloadCipher:
    """Encrypts the durable delivery payload and pseudonymizes its recipient."""

    def __init__(
        self,
        *,
        encryption_key: str | bytes,
        identity_hasher: IdentityHasher,
    ) -> None:
        encoded_key = (
            encryption_key.encode("ascii") if isinstance(encryption_key, str) else encryption_key
        )
        try:
            self._fernet = Fernet(encoded_key)
        except (ValueError, TypeError) as exc:
            raise VerificationConfigurationError(
                "delivery encryption key must be Fernet-compatible"
            ) from exc
        self._identity_hasher = identity_hasher

    def encrypt(
        self,
        message: VerificationMessage,
        *,
        token_digest: str,
    ) -> VerificationOutboxEnvelope:
        payload = {
            "tenant_id": str(message.tenant_id),
            "user_id": str(message.user_id),
            "recipient_email": message.recipient_email,
            "token": message.token,
            "expires_at": _aware_utc(message.expires_at).isoformat(),
            "purpose": message.purpose,
        }
        ciphertext = self._fernet.encrypt(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        return VerificationOutboxEnvelope(
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            recipient_pseudonym=self._identity_hasher.pseudonymize(
                purpose="email-recipient",
                value=message.recipient_email.strip().casefold(),
            ),
            token_digest=token_digest,
            encrypted_payload=ciphertext,
            expires_at=_aware_utc(message.expires_at),
        )

    def decrypt(self, envelope: VerificationOutboxEnvelope) -> VerificationMessage:
        try:
            raw_payload = self._fernet.decrypt(envelope.encrypted_payload)
            payload = json.loads(raw_payload)
            if not isinstance(payload, dict):
                raise ValueError("invalid payload type")
            purpose = str(payload.get("purpose", "verify_email"))
            if purpose not in {"verify_email", "team_invitation"}:
                raise ValueError("invalid delivery purpose")
            message = VerificationMessage(
                tenant_id=uuid.UUID(str(payload["tenant_id"])),
                user_id=uuid.UUID(str(payload["user_id"])),
                recipient_email=str(payload["recipient_email"]),
                token=str(payload["token"]),
                expires_at=_aware_utc(datetime.fromisoformat(str(payload["expires_at"]))),
                purpose=cast(
                    Literal["verify_email", "team_invitation"],
                    purpose,
                ),
            )
        except (
            InvalidToken,
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise VerificationDeliveryError("verification outbox payload is invalid") from exc
        if message.tenant_id != envelope.tenant_id or message.user_id != envelope.user_id:
            raise VerificationDeliveryError("verification outbox metadata mismatch")
        expected_recipient = self._identity_hasher.pseudonymize(
            purpose="email-recipient",
            value=message.recipient_email.strip().casefold(),
        )
        if not hmac.compare_digest(expected_recipient, envelope.recipient_pseudonym):
            raise VerificationDeliveryError("verification outbox metadata mismatch")
        return message


class DevelopmentCaptureProvider:
    """Bounded in-memory delivery capture, forbidden in production."""

    def __init__(self, *, environment: str, max_messages: int = 100) -> None:
        if environment not in {"development", "test"}:
            raise VerificationConfigurationError(
                "development capture delivery is forbidden in production"
            )
        if max_messages < 1:
            raise VerificationConfigurationError("max_messages must be positive")
        self._messages: deque[VerificationMessage] = deque(maxlen=max_messages)
        self._lock = asyncio.Lock()

    async def deliver(self, message: VerificationMessage) -> DeliveryReceipt:
        async with self._lock:
            self._messages.append(message)
            message_id = f"capture-{len(self._messages)}"
        return DeliveryReceipt(provider="development-capture", message_id=message_id)

    async def latest_for(self, recipient_email: str) -> VerificationMessage | None:
        normalized = recipient_email.strip().casefold()
        async with self._lock:
            return next(
                (
                    message
                    for message in reversed(self._messages)
                    if message.recipient_email.strip().casefold() == normalized
                ),
                None,
            )

    async def take_for(self, recipient_email: str) -> VerificationMessage | None:
        """Remove one captured message for an isolated test harness."""

        normalized = recipient_email.strip().casefold()
        async with self._lock:
            messages = list(self._messages)
            for index in range(len(messages) - 1, -1, -1):
                if messages[index].recipient_email.strip().casefold() == normalized:
                    message = messages.pop(index)
                    self._messages.clear()
                    self._messages.extend(messages)
                    return message
        return None

    async def aclose(self) -> None:
        async with self._lock:
            self._messages.clear()


class UnavailableVerificationDeliveryProvider:
    """Disabled provider that never pretends a verification was delivered."""

    async def deliver(self, message: VerificationMessage) -> DeliveryReceipt:
        del message
        raise VerificationDeliveryError("email verification provider is unavailable")

    async def aclose(self) -> None:
        return


class ResendVerificationDeliveryProvider:
    """Production provider adapter; construction and tests perform no network I/O."""

    _ENDPOINT = "https://api.resend.com/emails"

    def __init__(
        self,
        *,
        api_key: str,
        sender: str,
        public_base_url: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip() or not sender.strip():
            raise VerificationConfigurationError("Resend credentials and sender are required")
        parsed = urlsplit(public_base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise VerificationConfigurationError(
                "public verification base URL must be a credential-free HTTPS URL"
            )
        self._api_key = api_key
        self._sender = sender
        self._public_base_url = public_base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def deliver(self, message: VerificationMessage) -> DeliveryReceipt:
        query = urlencode({"token": message.token})
        # The fragment is never sent in the browser's HTTP request or Referer.
        # The verification page reads it client-side and scrubs the address bar.
        if message.purpose == "team_invitation":
            verification_url = f"{self._public_base_url}/accept-invitation?invitation=1#{query}"
            subject = "Join your AI Knowledge Compiler workspace"
            intro_text = "Accept your team invitation by opening this link: "
            intro_html = "<p>You have been invited to an AI Knowledge Compiler workspace.</p>"
            link_label = "Accept invitation"
        else:
            verification_url = f"{self._public_base_url}/verify-email?verification=1#{query}"
            subject = "Verify your AI Knowledge Compiler email"
            intro_text = "Verify your email by opening this link: "
            intro_html = "<p>Verify your email to activate your account.</p>"
            link_label = "Verify email"
        expiration = _aware_utc(message.expires_at).isoformat()
        try:
            response = await self._client.post(
                self._ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self._sender,
                    "to": [message.recipient_email],
                    "subject": subject,
                    "text": (f"{intro_text}{verification_url}\nThis link expires at {expiration}."),
                    "html": (
                        intro_html + f'<p><a href="{html.escape(verification_url, quote=True)}">'
                        f"{link_label}</a></p>"
                        f"<p>This link expires at {html.escape(expiration)}.</p>"
                    ),
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise VerificationDeliveryError("email verification delivery failed") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
            raise VerificationDeliveryError("email verification provider returned invalid data")
        return DeliveryReceipt(provider="resend", message_id=payload["id"])

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def validate_token_envelope(
    *,
    codec: VerificationTokenCodec,
    message: VerificationMessage,
    envelope: VerificationOutboxEnvelope,
) -> None:
    """Authenticate decrypted outbox metadata against its peppered token digest."""

    if (
        message.tenant_id != envelope.tenant_id
        or message.user_id != envelope.user_id
        or not codec.matches(message.token, envelope.token_digest)
    ):
        raise VerificationDeliveryError("verification outbox metadata mismatch")


def normalize_public_email(email: str) -> str:
    """Return the normalized account key used only before HMAC pseudonymization."""

    normalized = email.strip().casefold()
    if not normalized or len(normalized) > 320 or "@" not in normalized:
        raise AbuseControlConfigurationError("invalid email identity")
    return normalized
