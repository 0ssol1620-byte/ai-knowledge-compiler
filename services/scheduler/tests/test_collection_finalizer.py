from __future__ import annotations

import hashlib
import hmac
import uuid

import httpx
import pytest
from akc_api.collection_schemas import CollectionFinalizerRequest
from akc_api.models import OutboxEvent
from akc_scheduler.collection_finalizer import (
    HttpCollectionFinalizer,
    canonical_finalizer_body,
)
from akc_scheduler.settings import SchedulerSettings
from pydantic import ValidationError


def _finalizer_event() -> OutboxEvent:
    tenant_id = uuid.uuid4()
    processing_job_id = uuid.uuid4()
    return OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        aggregate_type="collection_processing",
        aggregate_id=processing_job_id,
        event_type="collection.semantic.compile.requested.v1",
        payload={
            "tenant_id": str(tenant_id),
            "collection_id": str(uuid.uuid4()),
            "processing_job_id": str(processing_job_id),
            "architecture_plan_id": str(uuid.uuid4()),
            "actor_user_id": str(uuid.uuid4()),
        },
    )


async def test_http_collection_finalizer_posts_exact_canonical_hmac_body() -> None:
    event = _finalizer_event()
    secret = b"collection-finalizer-test-key-32b"
    observed: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["body"] = await request.aread()
        observed["content_type"] = request.headers.get("Content-Type")
        observed["signature"] = request.headers.get("X-AKC-Collection-Finalizer-Signature")
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        finalizer = HttpCollectionFinalizer(
            endpoint_url="http://akc-api:8000/v1/internal/collections/finalize",
            hmac_secret=secret,
            timeout_seconds=30,
            client=client,
        )
        await finalizer.finalize(event)
        await finalizer.aclose()

    payload = CollectionFinalizerRequest(
        event_id=event.id,
        tenant_id=event.tenant_id,
        collection_id=uuid.UUID(str(event.payload["collection_id"])),
        processing_job_id=event.aggregate_id,
        architecture_plan_id=uuid.UUID(str(event.payload["architecture_plan_id"])),
        actor_user_id=uuid.UUID(str(event.payload["actor_user_id"])),
    )
    expected_body = canonical_finalizer_body(payload)
    expected_signature = "sha256=" + hmac.new(secret, expected_body, hashlib.sha256).hexdigest()
    assert observed == {
        "url": "http://akc-api:8000/v1/internal/collections/finalize",
        "body": expected_body,
        "content_type": "application/json",
        "signature": expected_signature,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "event_type",
        "aggregate_type",
        "aggregate_id",
        "tenant_id",
        "missing_payload_field",
    ],
)
async def test_http_collection_finalizer_rejects_unscoped_event_before_http(
    mutation: str,
) -> None:
    event = _finalizer_event()
    if mutation == "event_type":
        event.event_type = "job.dispatch.requested.v1"
    elif mutation == "aggregate_type":
        event.aggregate_type = "job"
    elif mutation == "aggregate_id":
        event.aggregate_id = uuid.uuid4()
    elif mutation == "tenant_id":
        event.tenant_id = uuid.uuid4()
    else:
        del event.payload["architecture_plan_id"]
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        finalizer = HttpCollectionFinalizer(
            endpoint_url="http://akc-api:8000/v1/internal/collections/finalize",
            hmac_secret=b"collection-finalizer-test-key-32b",
            timeout_seconds=30,
            client=client,
        )
        with pytest.raises(
            ValueError,
            match=r"collection_finalizer_(event_scope_mismatch|payload_invalid)",
        ):
            await finalizer.finalize(event)

    assert calls == 0


async def test_http_collection_finalizer_does_not_follow_redirect() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            307,
            headers={"Location": "https://attacker.example/finalize"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    ) as client:
        finalizer = HttpCollectionFinalizer(
            endpoint_url="http://akc-api:8000/v1/internal/collections/finalize",
            hmac_secret=b"collection-finalizer-test-key-32b",
            timeout_seconds=30,
            client=client,
        )
        with pytest.raises(RuntimeError, match="collection_finalizer_http_307"):
            await finalizer.finalize(_finalizer_event())

    assert calls == 1


def test_scheduler_settings_accept_exact_cluster_finalizer_contract() -> None:
    settings = SchedulerSettings(
        env="production",
        database_url="postgresql+asyncpg://akc@postgres.internal/akc",
        metrics_bind_host="0.0.0.0",
        collection_finalizer_enabled=True,
        collection_finalizer_api_url=("http://akc-api:8000/v1/internal/collections/finalize"),
        collection_finalizer_hmac_secret="x" * 32,
    )

    assert settings.collection_finalizer_enabled is True


@pytest.mark.parametrize(
    ("secret", "endpoint", "message"),
    [
        (
            "too-short",
            "http://akc-api:8000/v1/internal/collections/finalize",
            "HMAC secret must contain at least 32 bytes",
        ),
        (
            "collection-finalizer-production-key",
            "http://169.254.169.254/v1/internal/collections/finalize",
            "API URL is not an exact trusted endpoint",
        ),
        (
            "collection-finalizer-production-key",
            "https://user:password@api.example/v1/internal/collections/finalize",
            "API URL is not an exact trusted endpoint",
        ),
        (
            "collection-finalizer-production-key",
            "https://api.example/v1/internal/collections/finalize?redirect=true",
            "API URL is not an exact trusted endpoint",
        ),
    ],
)
def test_scheduler_settings_fail_closed_for_invalid_finalizer_contract(
    secret: str,
    endpoint: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        SchedulerSettings(
            collection_finalizer_enabled=True,
            collection_finalizer_api_url=endpoint,
            collection_finalizer_hmac_secret=secret,
        )
