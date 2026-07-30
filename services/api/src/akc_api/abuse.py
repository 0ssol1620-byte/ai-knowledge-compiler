"""Fail-closed abuse controls with privacy-preserving request identities.

Raw client addresses and account identifiers must never be used as rate-limit
keys.  ``IdentityHasher`` creates stable, purpose-bound HMAC pseudonyms before
an identifier crosses the request boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import math
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

import httpx
from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

_CONTROL_PATTERN = re.compile(r"^[a-z][a-z0-9:_-]{0,63}$")
_PSEUDONYM_PATTERN = re.compile(r"^h1_[0-9a-f]{64}$")


class AbuseControlConfigurationError(ValueError):
    """Raised when an abuse-control boundary is configured unsafely."""


class RateLimitBackendUnavailable(RuntimeError):
    """Raised when a durable limiter cannot make an authoritative decision."""


class CaptchaRequiredError(RuntimeError):
    """Raised when a risk decision requires a CAPTCHA response."""


class CaptchaRejectedError(RuntimeError):
    """Raised when a CAPTCHA response is invalid or its provider is unavailable."""


class CaptchaProviderUnavailable(RuntimeError):
    """Raised when the configured CAPTCHA provider cannot verify a response."""


@dataclass(frozen=True, slots=True)
class ClientIdentity:
    """A request identity safe to place in logs, metrics, or Redis keys."""

    pseudonym: str
    used_trusted_proxy_chain: bool


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """A fixed-window policy and optional risk threshold."""

    limit: int
    window_seconds: int
    captcha_after: int | None = None

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise AbuseControlConfigurationError("rate-limit limit must be positive")
        if self.window_seconds < 1:
            raise AbuseControlConfigurationError("rate-limit window must be positive")
        if self.captcha_after is not None and not 1 <= self.captcha_after <= self.limit:
            raise AbuseControlConfigurationError(
                "captcha_after must be between one and the hard limit"
            )


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Authoritative result returned by a rate-limit backend."""

    allowed: bool
    remaining: int
    retry_after_seconds: int
    observed_count: int
    captcha_required: bool


class RateLimiter(Protocol):
    async def consume(
        self,
        *,
        control: str,
        subject: str,
        policy: RateLimitPolicy,
        cost: int = 1,
    ) -> RateLimitDecision:
        """Atomically consume capacity for a pseudonymous subject."""

    async def healthcheck(self) -> None:
        """Raise when this backend cannot make authoritative decisions."""

    async def aclose(self) -> None:
        """Release backend resources."""


class CaptchaProvider(Protocol):
    async def verify(
        self,
        *,
        token: str,
        client_identity: str,
        action: str,
    ) -> bool:
        """Verify one opaque response without logging or persisting it."""

    async def aclose(self) -> None:
        """Release backend resources."""


class _RedisClient(Protocol):
    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: str,
    ) -> object:
        """Evaluate one atomic script."""

    async def ping(self) -> bool:
        """Return backend health."""

    async def aclose(self) -> None:
        """Release the connection pool."""


class IdentityHasher:
    """Creates purpose-bound HMAC pseudonyms for sensitive identifiers."""

    def __init__(self, secret: str | bytes) -> None:
        secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
        if len(secret_bytes) < 32:
            raise AbuseControlConfigurationError(
                "identity HMAC secret must contain at least 32 bytes"
            )
        self._secret = secret_bytes

    def pseudonymize(self, *, purpose: str, value: str) -> str:
        if not _CONTROL_PATTERN.fullmatch(purpose):
            raise AbuseControlConfigurationError("invalid identity purpose")
        canonical_value = value.strip()
        payload = purpose.encode("ascii") + b"\x00" + canonical_value.encode("utf-8")
        return "h1_" + hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def combine(self, *, purpose: str, values: Iterable[str]) -> str:
        encoded = "\x1f".join(value.strip() for value in values)
        return self.pseudonymize(purpose=purpose, value=encoded)


def _normalized_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    candidate = value.strip().strip('"')
    if candidate.startswith("["):
        closing = candidate.find("]")
        if closing < 0:
            raise ValueError("unterminated bracketed address")
        candidate = candidate[1:closing]
    elif candidate.count(":") == 1 and "." in candidate:
        host, possible_port = candidate.rsplit(":", 1)
        if possible_port.isdigit():
            candidate = host
    if "%" in candidate:
        raise ValueError("scoped addresses are not accepted")
    parsed = ipaddress.ip_address(candidate)
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        return parsed.ipv4_mapped
    return parsed


def _forwarded_chain(header: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    result: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for element in header.split(","):
        for parameter in element.split(";"):
            name, separator, raw_value = parameter.strip().partition("=")
            if separator and name.casefold() == "for":
                value = raw_value.strip()
                if value.casefold() == "unknown" or value.startswith("_"):
                    raise ValueError("non-address Forwarded identifier")
                result.append(_normalized_ip(value))
                break
        else:
            raise ValueError("Forwarded element has no for parameter")
    if not result:
        raise ValueError("empty Forwarded chain")
    return result


def _xff_chain(header: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    values = [item.strip() for item in header.split(",")]
    if not values or any(not item for item in values):
        raise ValueError("invalid X-Forwarded-For chain")
    return [_normalized_ip(item) for item in values]


class TrustedProxyIdentityResolver:
    """Resolves a client only through explicitly trusted proxy CIDRs."""

    def __init__(
        self,
        *,
        hasher: IdentityHasher,
        trusted_proxy_cidrs: Iterable[str],
    ) -> None:
        self._hasher = hasher
        try:
            self._trusted_networks = tuple(
                ipaddress.ip_network(item.strip(), strict=False)
                for item in trusted_proxy_cidrs
                if item.strip()
            )
        except ValueError as exc:
            raise AbuseControlConfigurationError("invalid trusted proxy CIDR") from exc

    def _trusted(self, address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return any(
            address.version == network.version and address in network
            for network in self._trusted_networks
        )

    def resolve_values(
        self,
        *,
        peer_host: str | None,
        headers: Mapping[str, str],
    ) -> ClientIdentity:
        try:
            peer = _normalized_ip(peer_host or "")
        except ValueError:
            return ClientIdentity(
                pseudonym=self._hasher.pseudonymize(
                    purpose="client-ip",
                    value="unparseable-peer",
                ),
                used_trusted_proxy_chain=False,
            )

        selected = peer
        used_chain = False
        if self._trusted(peer):
            lowered = {name.casefold(): value for name, value in headers.items()}
            forwarded = lowered.get("forwarded")
            xff = lowered.get("x-forwarded-for")
            try:
                chain = (
                    _forwarded_chain(forwarded)
                    if forwarded is not None
                    else _xff_chain(xff)
                    if xff is not None
                    else []
                )
            except ValueError:
                chain = []
            if chain:
                full_chain = [*chain, peer]
                selected = full_chain[0]
                for candidate in reversed(full_chain):
                    if not self._trusted(candidate):
                        selected = candidate
                        break
                used_chain = True

        return ClientIdentity(
            pseudonym=self._hasher.pseudonymize(
                purpose="client-ip",
                value=selected.compressed,
            ),
            used_trusted_proxy_chain=used_chain,
        )

    def resolve_request(self, request: Request) -> ClientIdentity:
        peer_host = request.client.host if request.client is not None else None
        return self.resolve_values(peer_host=peer_host, headers=request.headers)


def _validate_limiter_input(*, control: str, subject: str, cost: int) -> None:
    if not _CONTROL_PATTERN.fullmatch(control):
        raise AbuseControlConfigurationError("invalid low-cardinality control name")
    if not _PSEUDONYM_PATTERN.fullmatch(subject):
        raise AbuseControlConfigurationError("rate-limit subject must be an HMAC pseudonym")
    if cost < 1:
        raise AbuseControlConfigurationError("rate-limit cost must be positive")


@dataclass(slots=True)
class _MemoryBucket:
    count: int
    expires_at: float
    touched_at: float


class InMemoryRateLimiter:
    """Bounded, process-local limiter permitted only in development and tests."""

    def __init__(
        self,
        *,
        environment: str,
        max_buckets: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if environment not in {"development", "test"}:
            raise AbuseControlConfigurationError(
                "the in-memory limiter is forbidden outside development and test"
            )
        if max_buckets < 1:
            raise AbuseControlConfigurationError("max_buckets must be positive")
        self._max_buckets = max_buckets
        self._clock = clock
        self._buckets: dict[str, _MemoryBucket] = {}
        self._lock = asyncio.Lock()

    @property
    def bucket_count(self) -> int:
        return len(self._buckets)

    async def consume(
        self,
        *,
        control: str,
        subject: str,
        policy: RateLimitPolicy,
        cost: int = 1,
    ) -> RateLimitDecision:
        _validate_limiter_input(control=control, subject=subject, cost=cost)
        now = self._clock()
        key = f"{control}:{subject}"
        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.expires_at <= now:
                if bucket is None and len(self._buckets) >= self._max_buckets:
                    expired = [
                        existing_key
                        for existing_key, existing in self._buckets.items()
                        if existing.expires_at <= now
                    ]
                    for existing_key in expired:
                        del self._buckets[existing_key]
                if bucket is None and len(self._buckets) >= self._max_buckets:
                    oldest_key = min(
                        self._buckets,
                        key=lambda existing_key: self._buckets[existing_key].touched_at,
                    )
                    del self._buckets[oldest_key]
                bucket = _MemoryBucket(
                    count=0,
                    expires_at=now + policy.window_seconds,
                    touched_at=now,
                )
                self._buckets[key] = bucket

            bucket.count += cost
            bucket.touched_at = now
            retry_after = max(1, math.ceil(bucket.expires_at - now))
            return RateLimitDecision(
                allowed=bucket.count <= policy.limit,
                remaining=max(0, policy.limit - bucket.count),
                retry_after_seconds=retry_after,
                observed_count=bucket.count,
                captcha_required=(
                    policy.captcha_after is not None and bucket.count >= policy.captcha_after
                ),
            )

    async def healthcheck(self) -> None:
        return

    async def aclose(self) -> None:
        async with self._lock:
            self._buckets.clear()


_REDIS_CONSUME_SCRIPT = """
local count = redis.call('INCRBY', KEYS[1], ARGV[1])
local ttl = redis.call('PTTL', KEYS[1])
if ttl < 0 then
  redis.call('PEXPIRE', KEYS[1], ARGV[2])
  ttl = tonumber(ARGV[2])
end
return {count, ttl}
""".strip()


class RedisRateLimiter:
    """Atomic Redis-backed limiter used by shared and production deployments."""

    def __init__(
        self,
        client: _RedisClient,
        *,
        key_prefix: str = "akc:rate:v1",
    ) -> None:
        if not key_prefix or any(character.isspace() for character in key_prefix):
            raise AbuseControlConfigurationError("invalid Redis rate-limit prefix")
        self._client = client
        self._key_prefix = key_prefix

    async def consume(
        self,
        *,
        control: str,
        subject: str,
        policy: RateLimitPolicy,
        cost: int = 1,
    ) -> RateLimitDecision:
        _validate_limiter_input(control=control, subject=subject, cost=cost)
        key = f"{self._key_prefix}:{control}:{subject}"
        try:
            raw_result = await self._client.eval(
                _REDIS_CONSUME_SCRIPT,
                1,
                key,
                str(cost),
                str(policy.window_seconds * 1000),
            )
        except (RedisError, OSError, TimeoutError) as exc:
            raise RateLimitBackendUnavailable(
                "the authoritative rate-limit backend is unavailable"
            ) from exc
        if (
            not isinstance(raw_result, (list, tuple))
            or len(raw_result) != 2
            or not all(isinstance(value, (bytes, int, str)) for value in raw_result)
        ):
            raise RateLimitBackendUnavailable("invalid response from rate-limit backend")
        try:
            observed_count = int(raw_result[0])
            ttl_ms = int(raw_result[1])
        except (TypeError, ValueError) as exc:
            raise RateLimitBackendUnavailable("invalid response from rate-limit backend") from exc
        retry_after = max(1, math.ceil(max(0, ttl_ms) / 1000))
        return RateLimitDecision(
            allowed=observed_count <= policy.limit,
            remaining=max(0, policy.limit - observed_count),
            retry_after_seconds=retry_after,
            observed_count=observed_count,
            captcha_required=(
                policy.captcha_after is not None and observed_count >= policy.captcha_after
            ),
        )

    async def healthcheck(self) -> None:
        try:
            healthy = await self._client.ping()
        except (RedisError, OSError, TimeoutError) as exc:
            raise RateLimitBackendUnavailable(
                "the authoritative rate-limit backend is unavailable"
            ) from exc
        if not healthy:
            raise RateLimitBackendUnavailable(
                "the authoritative rate-limit backend rejected its health check"
            )

    async def aclose(self) -> None:
        await self._client.aclose()


def build_rate_limiter(
    *,
    environment: str,
    redis_url: str | None,
    memory_max_buckets: int,
) -> RateLimiter:
    """Build a limiter without ever falling back from Redis in production."""

    if redis_url:
        client = Redis.from_url(
            redis_url,
            decode_responses=False,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        return RedisRateLimiter(cast(_RedisClient, client))
    if environment == "production":
        raise AbuseControlConfigurationError("production requires Redis rate limiting")
    return InMemoryRateLimiter(
        environment=environment,
        max_buckets=memory_max_buckets,
    )


class UnavailableCaptchaProvider:
    """A disabled provider that always fails closed when verification is required."""

    async def verify(
        self,
        *,
        token: str,
        client_identity: str,
        action: str,
    ) -> bool:
        del token, client_identity, action
        raise CaptchaProviderUnavailable("CAPTCHA provider is not configured")

    async def aclose(self) -> None:
        return


class TurnstileCaptchaProvider:
    """Server-side Cloudflare Turnstile adapter.

    The caller passes only a pseudonymous client identity.  It is bound into
    Turnstile's idempotency key; a raw client address is never transmitted.
    """

    def __init__(
        self,
        *,
        secret_key: str,
        verify_url: str = "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        timeout_seconds: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not secret_key.strip():
            raise AbuseControlConfigurationError("Turnstile secret is required")
        if not verify_url.startswith("https://"):
            raise AbuseControlConfigurationError("CAPTCHA verification URL must use HTTPS")
        self._secret_key = secret_key
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._verify_url = verify_url

    async def verify(
        self,
        *,
        token: str,
        client_identity: str,
        action: str,
    ) -> bool:
        if not token.strip() or not _PSEUDONYM_PATTERN.fullmatch(client_identity):
            return False
        if not _CONTROL_PATTERN.fullmatch(action):
            return False
        idempotency_key = hashlib.sha256(
            f"{action}\x00{client_identity}\x00{token}".encode()
        ).hexdigest()
        try:
            response = await self._client.post(
                self._verify_url,
                data={
                    "secret": self._secret_key,
                    "response": token,
                    "idempotency_key": idempotency_key,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CaptchaProviderUnavailable("CAPTCHA verification service is unavailable") from exc
        if not isinstance(payload, dict) or payload.get("success") is not True:
            return False
        return payload.get("action") == action

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


async def enforce_captcha(
    *,
    required: bool,
    token: str | None,
    provider: CaptchaProvider,
    client_identity: str,
    action: str,
) -> None:
    """Verify CAPTCHA only after a risk trigger and fail closed on every error."""

    if not required:
        return
    if not token:
        raise CaptchaRequiredError("CAPTCHA verification is required")
    try:
        accepted = await provider.verify(
            token=token,
            client_identity=client_identity,
            action=action,
        )
    except CaptchaProviderUnavailable as exc:
        raise CaptchaRejectedError("CAPTCHA verification could not be completed") from exc
    if not accepted:
        raise CaptchaRejectedError("CAPTCHA verification was rejected")


def rate_limit_http_exception(
    decision: RateLimitDecision,
    *,
    code: str = "RATE_LIMITED",
) -> HTTPException:
    """Build the canonical 429 envelope inputs and standards-based retry hint."""

    if decision.allowed:
        raise ValueError("cannot create a rate-limit error for an allowed decision")
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": code,
            "message": "Too many requests. Retry after the indicated delay.",
            "retry_after_seconds": decision.retry_after_seconds,
        },
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )
