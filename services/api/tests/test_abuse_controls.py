# ruff: noqa: S105, S106
"""Security and concurrency evidence for privacy-preserving abuse controls."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from akc_api.abuse import (
    AbuseControlConfigurationError,
    CaptchaProviderUnavailable,
    CaptchaRejectedError,
    CaptchaRequiredError,
    IdentityHasher,
    InMemoryRateLimiter,
    RateLimitBackendUnavailable,
    RateLimitDecision,
    RateLimitPolicy,
    RedisRateLimiter,
    TrustedProxyIdentityResolver,
    TurnstileCaptchaProvider,
    UnavailableCaptchaProvider,
    build_rate_limiter,
    enforce_captcha,
    rate_limit_http_exception,
)
from redis.exceptions import ConnectionError as RedisConnectionError

_SECRET = "identity-secret-that-is-more-than-thirty-two-bytes"


def test_untrusted_peer_cannot_spoof_forwarded_identity() -> None:
    hasher = IdentityHasher(_SECRET)
    resolver = TrustedProxyIdentityResolver(
        hasher=hasher,
        trusted_proxy_cidrs=["10.0.0.0/8"],
    )

    identity = resolver.resolve_values(
        peer_host="198.51.100.44",
        headers={
            "Forwarded": 'for="203.0.113.9"',
            "X-Forwarded-For": "192.0.2.10",
        },
    )

    assert identity.used_trusted_proxy_chain is False
    assert identity.pseudonym == hasher.pseudonymize(
        purpose="client-ip",
        value="198.51.100.44",
    )
    assert "198.51.100.44" not in identity.pseudonym
    assert "203.0.113.9" not in identity.pseudonym


def test_trusted_proxy_chain_selects_rightmost_untrusted_hop() -> None:
    hasher = IdentityHasher(_SECRET)
    resolver = TrustedProxyIdentityResolver(
        hasher=hasher,
        trusted_proxy_cidrs=["10.0.0.0/8", "fd00::/8"],
    )

    identity = resolver.resolve_values(
        peer_host="10.9.8.7",
        headers={"X-Forwarded-For": "192.0.2.19, 10.2.3.4"},
    )

    assert identity.used_trusted_proxy_chain is True
    assert identity.pseudonym == hasher.pseudonymize(
        purpose="client-ip",
        value="192.0.2.19",
    )


def test_malformed_trusted_proxy_header_falls_back_to_peer() -> None:
    hasher = IdentityHasher(_SECRET)
    resolver = TrustedProxyIdentityResolver(
        hasher=hasher,
        trusted_proxy_cidrs=["10.0.0.0/8"],
    )

    identity = resolver.resolve_values(
        peer_host="10.9.8.7",
        headers={"Forwarded": "for=_hidden"},
    )

    assert identity.used_trusted_proxy_chain is False
    assert identity.pseudonym == hasher.pseudonymize(
        purpose="client-ip",
        value="10.9.8.7",
    )


def test_identity_hmac_is_stable_and_purpose_bound() -> None:
    hasher = IdentityHasher(_SECRET)
    first = hasher.pseudonymize(purpose="account", value="owner@example.com")
    second = hasher.pseudonymize(purpose="account", value="owner@example.com")
    client = hasher.pseudonymize(purpose="client-ip", value="owner@example.com")

    assert first == second
    assert first != client
    assert first.startswith("h1_")
    assert "owner@example.com" not in first


def test_invalid_proxy_cidr_and_short_secret_fail_configuration() -> None:
    with pytest.raises(AbuseControlConfigurationError):
        IdentityHasher("short")
    with pytest.raises(AbuseControlConfigurationError):
        TrustedProxyIdentityResolver(
            hasher=IdentityHasher(_SECRET),
            trusted_proxy_cidrs=["not-a-network"],
        )


async def test_in_memory_limiter_is_atomic_under_concurrency() -> None:
    hasher = IdentityHasher(_SECRET)
    subject = hasher.pseudonymize(purpose="account", value="owner@example.com")
    limiter = InMemoryRateLimiter(environment="test", max_buckets=100)
    policy = RateLimitPolicy(limit=50, window_seconds=60, captcha_after=25)

    decisions = await asyncio.gather(
        *(
            limiter.consume(
                control="login",
                subject=subject,
                policy=policy,
            )
            for _ in range(100)
        )
    )

    assert sum(decision.allowed for decision in decisions) == 50
    assert sorted(decision.observed_count for decision in decisions) == list(range(1, 101))
    assert sum(decision.captcha_required for decision in decisions) == 76


async def test_in_memory_limiter_is_bounded_and_expires() -> None:
    current_time = [100.0]
    hasher = IdentityHasher(_SECRET)
    limiter = InMemoryRateLimiter(
        environment="test",
        max_buckets=2,
        clock=lambda: current_time[0],
    )
    policy = RateLimitPolicy(limit=1, window_seconds=10)
    subjects = [
        hasher.pseudonymize(purpose="account", value=f"user-{index}")
        for index in range(3)
    ]

    for subject in subjects:
        await limiter.consume(control="upload", subject=subject, policy=policy)
    assert limiter.bucket_count == 2

    current_time[0] = 111.0
    reset = await limiter.consume(
        control="upload",
        subject=subjects[-1],
        policy=policy,
    )
    assert reset.allowed is True
    assert reset.observed_count == 1


async def test_limiter_rejects_raw_subject_and_production_memory_fallback() -> None:
    limiter = InMemoryRateLimiter(environment="test")
    with pytest.raises(AbuseControlConfigurationError):
        await limiter.consume(
            control="login",
            subject="owner@example.com",
            policy=RateLimitPolicy(limit=2, window_seconds=60),
        )
    with pytest.raises(AbuseControlConfigurationError):
        build_rate_limiter(
            environment="production",
            redis_url=None,
            memory_max_buckets=100,
        )


def test_rate_limit_error_includes_retry_after_header_and_bounded_code() -> None:
    decision = RateLimitDecision(
        allowed=False,
        remaining=0,
        retry_after_seconds=17,
        observed_count=11,
        captcha_required=True,
    )
    error = rate_limit_http_exception(decision, code="LOGIN_RATE_LIMITED")

    assert error.status_code == 429
    assert error.headers == {"Retry-After": "17"}
    assert error.detail == {
        "code": "LOGIN_RATE_LIMITED",
        "message": "Too many requests. Retry after the indicated delay.",
        "retry_after_seconds": 17,
    }


class _FakeRedis:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.count = 0
        self.unavailable = unavailable
        self.lock = asyncio.Lock()
        self.closed = False

    async def eval(self, *_args: object) -> list[int]:
        if self.unavailable:
            raise RedisConnectionError("test outage")
        async with self.lock:
            cost = int(_args[-2])
            self.count += cost
            return [self.count, 30_000]

    async def ping(self) -> bool:
        if self.unavailable:
            raise RedisConnectionError("test outage")
        return True

    async def aclose(self) -> None:
        self.closed = True


async def test_redis_limiter_uses_atomic_result_and_fails_closed_on_outage() -> None:
    hasher = IdentityHasher(_SECRET)
    subject = hasher.pseudonymize(purpose="tenant", value="tenant-a")
    fake = _FakeRedis()
    limiter = RedisRateLimiter(fake)
    policy = RateLimitPolicy(limit=3, window_seconds=30)

    decisions = await asyncio.gather(
        *(
            limiter.consume(control="compile", subject=subject, policy=policy)
            for _ in range(5)
        )
    )
    assert [decision.allowed for decision in decisions] == [
        True,
        True,
        True,
        False,
        False,
    ]
    assert all(decision.retry_after_seconds == 30 for decision in decisions)

    unavailable = RedisRateLimiter(_FakeRedis(unavailable=True))
    with pytest.raises(RateLimitBackendUnavailable):
        await unavailable.consume(
            control="compile",
            subject=subject,
            policy=policy,
        )
    with pytest.raises(RateLimitBackendUnavailable):
        await unavailable.healthcheck()


class _CaptchaResult:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls = 0

    async def verify(
        self,
        *,
        token: str,
        client_identity: str,
        action: str,
    ) -> bool:
        assert token == "opaque-response"
        assert client_identity.startswith("h1_")
        assert action == "register"
        self.calls += 1
        return self.result

    async def aclose(self) -> None:
        return


async def test_risk_triggered_captcha_never_uses_a_fake_success() -> None:
    identity = IdentityHasher(_SECRET).pseudonymize(
        purpose="client-ip",
        value="192.0.2.1",
    )
    provider = _CaptchaResult(True)

    await enforce_captcha(
        required=False,
        token=None,
        provider=provider,
        client_identity=identity,
        action="register",
    )
    assert provider.calls == 0

    with pytest.raises(CaptchaRequiredError):
        await enforce_captcha(
            required=True,
            token=None,
            provider=provider,
            client_identity=identity,
            action="register",
        )
    with pytest.raises(CaptchaRejectedError):
        await enforce_captcha(
            required=True,
            token="opaque-response",
            provider=_CaptchaResult(False),
            client_identity=identity,
            action="register",
        )
    with pytest.raises(CaptchaRejectedError):
        await enforce_captcha(
            required=True,
            token="opaque-response",
            provider=UnavailableCaptchaProvider(),
            client_identity=identity,
            action="register",
        )


async def test_turnstile_adapter_sends_no_raw_client_address() -> None:
    identity = IdentityHasher(_SECRET).pseudonymize(
        purpose="client-ip",
        value="192.0.2.55",
    )
    captured_body = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = (await request.aread()).decode()
        return httpx.Response(200, json={"success": True, "action": "register"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TurnstileCaptchaProvider(secret_key="provider-secret", client=client)
    try:
        assert (
            await provider.verify(
                token="opaque-response",
                client_identity=identity,
                action="register",
            )
            is True
        )
    finally:
        await client.aclose()

    assert "192.0.2.55" not in captured_body
    assert "remoteip" not in captured_body
    assert identity not in captured_body


async def test_captcha_provider_outage_is_sanitized() -> None:
    identity = IdentityHasher(_SECRET).pseudonymize(
        purpose="client-ip",
        value="192.0.2.55",
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test provider outage")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TurnstileCaptchaProvider(secret_key="provider-secret", client=client)
    try:
        with pytest.raises(CaptchaProviderUnavailable) as caught:
            await provider.verify(
                token="opaque-response",
                client_identity=identity,
                action="register",
            )
    finally:
        await client.aclose()
    assert "opaque-response" not in str(caught.value)
    assert "192.0.2.55" not in str(caught.value)
