"""Signed, DNS-pinned webhook HTTP delivery."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import secrets
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx
import orjson
from akc_security import (
    UnsafeUrlError,
    UrlValidationResult,
    validate_redirect_chain,
    validate_resolved_url,
)
from cryptography.fernet import Fernet, InvalidToken

DnsResolver = Callable[[str, int], Awaitable[Sequence[str]]]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_USER_AGENT = "akc-scheduler/0.1"
_MAX_RESOLVED_ADDRESSES = 8


def utcnow() -> datetime:
    return datetime.now(UTC)


class WebhookDeliveryError(RuntimeError):
    """Base error carrying whether a later attempt may succeed."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class SecretDecryptionError(WebhookDeliveryError):
    """The endpoint secret could not be decrypted with the configured key."""

    def __init__(self) -> None:
        super().__init__("webhook_secret_decryption_failed", retryable=True)


class WebhookTargetError(WebhookDeliveryError):
    """The destination failed the explicit host and public-IP policy."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class WebhookDnsError(WebhookTargetError):
    """A DNS lookup failed transiently before target validation could complete."""

    def __init__(self, message: str) -> None:
        WebhookDeliveryError.__init__(self, message, retryable=True)


class WebhookHostNotAllowedError(WebhookTargetError):
    """A safe endpoint is paused because the runtime allowlist excludes it."""

    def __init__(self) -> None:
        WebhookDeliveryError.__init__(
            self,
            "webhook_host_not_allowlisted",
            retryable=True,
        )


class WebhookHttpError(WebhookDeliveryError):
    """The outbound connection failed before an HTTP response was received."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class WebhookPayloadError(WebhookDeliveryError):
    """A persisted event could not be represented by the webhook contract."""

    def __init__(self) -> None:
        super().__init__("webhook_payload_not_serializable", retryable=False)


class WebhookSecretIntegrityError(WebhookDeliveryError):
    """The decrypted endpoint secret does not match its stored digest."""

    def __init__(self) -> None:
        super().__init__("webhook_secret_integrity_failed", retryable=False)


@dataclass(frozen=True, slots=True)
class WebhookResponse:
    """Bounded response metadata retained by the scheduler."""

    status_code: int
    final_url: str
    redirect_count: int
    retry_after_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class HostAllowlist:
    """Exact hosts and ``*.example.com`` subdomain patterns."""

    patterns: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized: list[str] = []
        for raw_pattern in self.patterns:
            pattern = raw_pattern.rstrip(".").casefold()
            candidate = pattern[2:] if pattern.startswith("*.") else pattern
            if not candidate or "*" in candidate:
                raise ValueError(f"invalid webhook host allowlist entry: {raw_pattern!r}")
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                try:
                    candidate_ascii = candidate.encode("idna").decode("ascii")
                except UnicodeError as exc:
                    raise ValueError(
                        f"invalid webhook host allowlist entry: {raw_pattern!r}"
                    ) from exc
                if "." not in candidate_ascii:
                    raise ValueError(
                        f"invalid webhook host allowlist entry: {raw_pattern!r}"
                    ) from None
            else:
                candidate_ascii = address.compressed
            prefix = "*." if pattern.startswith("*.") else ""
            normalized.append(prefix + candidate_ascii)
        object.__setattr__(self, "patterns", tuple(dict.fromkeys(normalized)))

    def allows(self, hostname: str) -> bool:
        candidate = hostname.rstrip(".").casefold()
        for pattern in self.patterns:
            if pattern.startswith("*."):
                suffix = pattern[1:]
                if candidate.endswith(suffix) and candidate != pattern[2:]:
                    return True
            elif hmac.compare_digest(candidate, pattern):
                return True
        return False


def _fernet(encryption_key: str) -> Fernet:
    if not encryption_key:
        raise ValueError("webhook encryption key is required")
    try:
        return Fernet(encryption_key.encode("ascii"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("webhook encryption key must be a Fernet-compatible key") from exc


def generate_webhook_secret() -> str:
    """Generate a high-entropy HMAC signing secret for a new endpoint."""

    return secrets.token_urlsafe(32)


def encrypt_secret(secret: str, encryption_key: str) -> str:
    """Encrypt a webhook signing secret for ``WebhookEndpoint.encrypted_secret``."""

    if not secret:
        raise ValueError("webhook signing secret is required")
    return _fernet(encryption_key).encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str, encryption_key: str) -> str:
    """Decrypt an endpoint signing secret without exposing it in logs."""

    try:
        decrypted = _fernet(encryption_key).decrypt(token.encode("ascii"))
        secret = decrypted.decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise SecretDecryptionError from exc
    if not secret:
        raise SecretDecryptionError
    return secret


def verify_secret_hash(secret: str, expected_hash: str) -> bool:
    """Verify the endpoint's plaintext secret against its persisted SHA-256."""

    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, expected_hash)


# Backwards-compatible descriptive aliases used by the scheduler internals.
encrypt_webhook_secret = encrypt_secret
decrypt_webhook_secret = decrypt_secret


def canonical_webhook_body(
    *,
    delivery_id: str,
    event_type: str,
    payload: dict[str, object],
) -> bytes:
    """Build the stable, signed webhook envelope."""

    try:
        return orjson.dumps(
            {
                "data": payload,
                "id": delivery_id,
                "type": event_type,
            },
            option=orjson.OPT_SORT_KEYS,
        )
    except TypeError as exc:
        raise WebhookPayloadError from exc


def sign_webhook_payload(
    *,
    body: bytes,
    secret: str,
    timestamp: int,
) -> str:
    """Return the versioned HMAC-SHA256 signature header value."""

    signed_payload = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def webhook_headers(
    *,
    body: bytes,
    delivery_id: str,
    event_type: str,
    attempt: int,
    secret: str,
    timestamp: int,
) -> dict[str, str]:
    """Create stable identity headers and an attempt-specific signature."""

    return {
        "Content-Type": "application/json",
        "Idempotency-Key": delivery_id,
        "User-Agent": _USER_AGENT,
        "X-AKC-Delivery-Attempt": str(attempt),
        "X-AKC-Event-ID": delivery_id,
        "X-AKC-Event-Type": event_type,
        "X-AKC-Signature": sign_webhook_payload(
            body=body,
            secret=secret,
            timestamp=timestamp,
        ),
        "X-AKC-Timestamp": str(timestamp),
    }


def parse_retry_after(
    value: str | None,
    *,
    now: datetime,
    maximum_seconds: float,
) -> float | None:
    """Parse a bounded HTTP Retry-After delta or HTTP-date."""

    if value is None:
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 128:
        return None
    if candidate.isdecimal():
        seconds = float(int(candidate))
    else:
        try:
            retry_at = parsedate_to_datetime(candidate)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        seconds = max(0.0, (retry_at - now).total_seconds())
    return min(maximum_seconds, seconds)


async def resolve_public_addresses(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve a hostname asynchronously; public-address checks happen separately."""

    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(
        hostname,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    return tuple(dict.fromkeys(record[4][0] for record in records))


async def validate_webhook_url(
    url: str,
    *,
    allowed_hosts: Sequence[str],
    resolver: DnsResolver = resolve_public_addresses,
    dns_timeout_seconds: float = 5.0,
) -> UrlValidationResult:
    """Resolve and validate a registration or redirect target against one policy."""

    try:
        parsed = httpx.URL(url)
        if parsed.host is None:
            raise UnsafeUrlError("hostname_required")
        try:
            literal = ipaddress.ip_address(parsed.host)
        except ValueError:
            structural_addresses = ("1.1.1.1",)
        else:
            structural_addresses = (literal.compressed,)
        structural_target = validate_resolved_url(url, structural_addresses)
        if not HostAllowlist(tuple(allowed_hosts)).allows(structural_target.hostname_ascii):
            raise WebhookHostNotAllowedError
    except WebhookTargetError:
        raise
    except (httpx.InvalidURL, UnsafeUrlError) as exc:
        raise WebhookTargetError(f"unsafe_webhook_target:{exc}") from exc

    try:
        addresses = await asyncio.wait_for(
            resolver(structural_target.hostname_ascii, structural_target.port),
            timeout=dns_timeout_seconds,
        )
    except (OSError, TimeoutError) as exc:
        raise WebhookDnsError(f"webhook_dns_resolution_failed:{type(exc).__name__}") from exc

    try:
        target = validate_resolved_url(url, addresses)
        if len(target.resolved_ips) > _MAX_RESOLVED_ADDRESSES:
            raise UnsafeUrlError("too_many_dns_results")
    except UnsafeUrlError as exc:
        raise WebhookTargetError(f"unsafe_webhook_target:{exc}") from exc
    return target


class WebhookHttpClient:
    """HTTP sender that validates and pins every redirect hop to a resolved IP."""

    def __init__(
        self,
        *,
        allowed_hosts: Sequence[str],
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 10.0,
        max_redirects: int = 3,
        max_retry_after_seconds: float = 86400.0,
        resolver: DnsResolver = resolve_public_addresses,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._allowlist = HostAllowlist(tuple(allowed_hosts))
        self._max_redirects = max_redirects
        self._resolver = resolver
        self._dns_timeout_seconds = connect_timeout_seconds
        self._max_retry_after_seconds = max_retry_after_seconds
        self._clock = clock
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds,
                read=read_timeout_seconds,
                write=read_timeout_seconds,
                pool=connect_timeout_seconds,
            ),
            limits=httpx.Limits(max_keepalive_connections=0),
            transport=httpx.AsyncHTTPTransport(retries=0, http2=False),
            trust_env=False,
        )

    async def __aenter__(self) -> WebhookHttpClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _validate_target(self, url: str) -> UrlValidationResult:
        return await validate_webhook_url(
            url,
            allowed_hosts=self._allowlist.patterns,
            resolver=self._resolver,
            dns_timeout_seconds=self._dns_timeout_seconds,
        )

    async def _post_to_pinned_target(
        self,
        target: UrlValidationResult,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> httpx.Response:
        last_error: httpx.HTTPError | None = None
        for address in target.resolved_ips:
            pinned_url = httpx.URL(target.normalized_url).copy_with(host=address)
            pinned_headers = dict(headers)
            pinned_headers["Host"] = urlsplit(target.normalized_url).netloc
            request = httpx.Request(
                "POST",
                pinned_url,
                content=body,
                headers=pinned_headers,
                extensions={"sni_hostname": target.hostname_ascii},
            )
            try:
                return await self._client.send(
                    request,
                    stream=True,
                    follow_redirects=False,
                )
            except httpx.HTTPError as exc:
                last_error = exc
        detail = type(last_error).__name__ if last_error is not None else "no_address"
        raise WebhookHttpError(f"webhook_transport_error:{detail}")

    async def post(
        self,
        url: str,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> WebhookResponse:
        """POST a webhook while bounding and revalidating every redirect."""

        current_url = url
        chain: list[tuple[str, Sequence[str]]] = []
        for redirect_count in range(self._max_redirects + 1):
            target = await self._validate_target(current_url)
            chain.append((target.normalized_url, target.resolved_ips))
            try:
                validate_redirect_chain(chain, max_redirects=self._max_redirects)
            except UnsafeUrlError as exc:
                raise WebhookTargetError(f"unsafe_redirect_chain:{exc}") from exc

            response = await self._post_to_pinned_target(
                target,
                body=body,
                headers=headers,
            )
            try:
                status_code = response.status_code
                if status_code not in _REDIRECT_STATUSES:
                    return WebhookResponse(
                        status_code=status_code,
                        final_url=target.normalized_url,
                        redirect_count=redirect_count,
                        retry_after_seconds=parse_retry_after(
                            response.headers.get("Retry-After"),
                            now=self._clock(),
                            maximum_seconds=self._max_retry_after_seconds,
                        ),
                    )
                location = response.headers.get("Location")
                if not location:
                    raise WebhookTargetError("webhook_redirect_missing_location")
                if redirect_count >= self._max_redirects:
                    raise WebhookTargetError("webhook_redirect_limit_exceeded")
                current_url = urljoin(target.normalized_url, location)
            finally:
                await response.aclose()

        raise WebhookTargetError("webhook_redirect_limit_exceeded")
