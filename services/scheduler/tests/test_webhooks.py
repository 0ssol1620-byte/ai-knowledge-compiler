from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import socket
from datetime import UTC, datetime
from email.utils import format_datetime

import httpx
import pytest
from akc_scheduler.webhooks import (
    HostAllowlist,
    WebhookDnsError,
    WebhookHttpClient,
    WebhookTargetError,
    canonical_webhook_body,
    decrypt_secret,
    encrypt_secret,
    generate_webhook_secret,
    parse_retry_after,
    sign_webhook_payload,
    validate_webhook_url,
    webhook_headers,
)
from cryptography.fernet import Fernet

PUBLIC_IP = "93.184.216.34"
PUBLIC_IPV6 = "2606:4700:4700::1111"
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


async def public_resolver(_hostname: str, _port: int) -> tuple[str, ...]:
    return (PUBLIC_IP,)


def test_secret_encryption_and_signing_contract() -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    secret = generate_webhook_secret()
    encrypted = encrypt_secret(secret, encryption_key)

    assert encrypted != secret
    assert decrypt_secret(encrypted, encryption_key) == secret

    body = canonical_webhook_body(
        delivery_id="delivery-1",
        event_type="job.completed.v1",
        payload={"job_id": "job-1"},
    )
    assert json.loads(body) == {
        "data": {"job_id": "job-1"},
        "id": "delivery-1",
        "type": "job.completed.v1",
    }
    timestamp = 1_785_312_000
    expected = hmac.new(
        secret.encode(),
        str(timestamp).encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    assert (
        sign_webhook_payload(
            body=body,
            secret=secret,
            timestamp=timestamp,
        )
        == f"v1={expected}"
    )
    headers = webhook_headers(
        body=body,
        delivery_id="delivery-1",
        event_type="job.completed.v1",
        attempt=2,
        secret=secret,
        timestamp=timestamp,
    )
    assert headers["Idempotency-Key"] == "delivery-1"
    assert headers["X-AKC-Event-ID"] == "delivery-1"
    assert headers["X-AKC-Delivery-Attempt"] == "2"


def test_host_allowlist_supports_exact_and_subdomain_patterns() -> None:
    policy = HostAllowlist(("hooks.example.com", "*.events.example.com"))

    assert policy.allows("hooks.example.com")
    assert policy.allows("tenant.events.example.com")
    assert not policy.allows("events.example.com")
    assert not policy.allows("hooks.example.com.attacker.invalid")
    with pytest.raises(ValueError, match="invalid webhook host"):
        HostAllowlist(("*",))


def test_retry_after_parser_accepts_delta_and_date_and_caps_values() -> None:
    assert parse_retry_after("600", now=NOW, maximum_seconds=300) == 300
    assert (
        parse_retry_after(
            format_datetime(NOW.replace(hour=13), usegmt=True),
            now=NOW,
            maximum_seconds=7200,
        )
        == 3600
    )
    assert parse_retry_after("not-a-date", now=NOW, maximum_seconds=300) is None


async def test_validate_webhook_url_fails_closed_for_private_or_unlisted_hosts() -> None:
    async def private_resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        return ("127.0.0.1",)

    with pytest.raises(WebhookTargetError, match="dns_result_not_public"):
        await validate_webhook_url(
            "https://hooks.example.com/events",
            allowed_hosts=("hooks.example.com",),
            resolver=private_resolver,
        )
    with pytest.raises(WebhookTargetError, match="not_allowlisted"):
        await validate_webhook_url(
            "https://other.example.com/events",
            allowed_hosts=("hooks.example.com",),
            resolver=public_resolver,
        )


async def test_unlisted_host_is_rejected_before_dns_resolution() -> None:
    resolver_called = False

    async def resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        nonlocal resolver_called
        resolver_called = True
        return (PUBLIC_IP,)

    with pytest.raises(WebhookTargetError, match="not_allowlisted"):
        await validate_webhook_url(
            "https://attacker.example.net/collect",
            allowed_hosts=("hooks.example.com",),
            resolver=resolver,
        )

    assert not resolver_called


async def test_excessive_dns_answers_are_rejected() -> None:
    async def resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        return tuple(f"8.8.8.{index}" for index in range(1, 10))

    with pytest.raises(WebhookTargetError, match="too_many_dns_results"):
        await validate_webhook_url(
            "https://hooks.example.com/events",
            allowed_hosts=("hooks.example.com",),
            resolver=resolver,
        )


async def test_transient_dns_error_remains_retryable() -> None:
    async def resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        raise socket.gaierror(socket.EAI_AGAIN, "temporary failure")

    with pytest.raises(WebhookDnsError) as error:
        await validate_webhook_url(
            "https://hooks.example.com/events",
            allowed_hosts=("hooks.example.com",),
            resolver=resolver,
        )

    assert error.value.retryable


async def test_dns_resolution_timeout_remains_retryable() -> None:
    async def resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        await asyncio.get_running_loop().create_future()
        raise AssertionError("unreachable")

    with pytest.raises(WebhookDnsError, match="TimeoutError") as error:
        await validate_webhook_url(
            "https://hooks.example.com/events",
            allowed_hosts=("hooks.example.com",),
            resolver=resolver,
            dns_timeout_seconds=0.001,
        )

    assert error.value.retryable


async def test_http_delivery_pins_dns_and_revalidates_redirects() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers["Host"] == "hooks.example.com":
            return httpx.Response(
                307,
                headers={"Location": "https://backup.example.com/final"},
            )
        return httpx.Response(204)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )
    sender = WebhookHttpClient(
        allowed_hosts=("hooks.example.com", "backup.example.com"),
        max_redirects=2,
        resolver=public_resolver,
        client=client,
    )
    result = await sender.post(
        "https://hooks.example.com/start",
        body=b"{}",
        headers={"Content-Type": "application/json"},
    )
    await client.aclose()

    assert result.status_code == 204
    assert result.redirect_count == 1
    assert [request.headers["Host"] for request in requests] == [
        "hooks.example.com",
        "backup.example.com",
    ]
    assert all(request.url.host == PUBLIC_IP for request in requests)
    assert all(
        request.extensions["sni_hostname"] in {"hooks.example.com", "backup.example.com"}
        for request in requests
    )


async def test_ipv6_literal_uses_bracketed_host_header() -> None:
    requests: list[httpx.Request] = []

    async def resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        return (PUBLIC_IPV6,)

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sender = WebhookHttpClient(
        allowed_hosts=(PUBLIC_IPV6,),
        resolver=resolver,
        client=client,
    )
    response = await sender.post(
        f"https://[{PUBLIC_IPV6}]/events",
        body=b"{}",
        headers={},
    )
    await client.aclose()

    assert response.status_code == 204
    assert requests[0].headers["Host"] == f"[{PUBLIC_IPV6}]"
    assert requests[0].url.host == PUBLIC_IPV6


async def test_response_retry_after_is_preserved_and_capped() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "999999"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sender = WebhookHttpClient(
        allowed_hosts=("hooks.example.com",),
        max_retry_after_seconds=600,
        resolver=public_resolver,
        client=client,
        clock=lambda: NOW,
    )
    response = await sender.post(
        "https://hooks.example.com/events",
        body=b"{}",
        headers={},
    )
    await client.aclose()

    assert response.status_code == 429
    assert response.retry_after_seconds == 600


async def test_redirect_limit_is_terminal_and_bounded() -> None:
    call_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(307, headers={"Location": "/again"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sender = WebhookHttpClient(
        allowed_hosts=("hooks.example.com",),
        max_redirects=1,
        resolver=public_resolver,
        client=client,
    )
    with pytest.raises(WebhookTargetError, match="redirect_limit"):
        await sender.post(
            "https://hooks.example.com/start",
            body=b"{}",
            headers={},
        )
    await client.aclose()

    assert call_count == 2


async def test_redirect_to_private_address_is_rejected_before_second_request() -> None:
    call_count = 0

    async def resolver(hostname: str, _port: int) -> tuple[str, ...]:
        return ("127.0.0.1",) if hostname == "private.example.com" else (PUBLIC_IP,)

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            307,
            headers={"Location": "https://private.example.com/internal"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sender = WebhookHttpClient(
        allowed_hosts=("hooks.example.com", "private.example.com"),
        max_redirects=2,
        resolver=resolver,
        client=client,
    )
    with pytest.raises(WebhookTargetError, match="dns_result_not_public"):
        await sender.post(
            "https://hooks.example.com/start",
            body=b"{}",
            headers={},
        )
    await client.aclose()

    assert call_count == 1
