from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest
from akc_api.gpu_provider import (
    GpuJobRequest,
    GpuProviderError,
    RunpodGpuClient,
    SubmittedGpuJob,
    create_worker_token,
)

REVISION = "a" * 40
IMAGE_DIGEST = "sha256:" + ("e" * 64)
ADAPTER_VERSION = "parser-adapter-1.3.0"
SECRET = b"s" * 32


def _job() -> GpuJobRequest:
    return GpuJobRequest(
        endpoint_id="parser-balanced",
        provider_key="paddleocr_vl_1_6",
        model_revision=REVISION,
        runtime_image_digest=IMAGE_DIGEST,
        adapter_version=ADAPTER_VERSION,
        job_id="job-123",
        tenant_id="tenant-123",
        idempotency_key="idem-123",
        input_url=(
            "https://objects.example/tenants/tenant-123/source/page.png?X-Amz-Signature=redacted"
        ),
        input_object_key="tenants/tenant-123/source/page.png",
        input_sha256="b" * 64,
        output_url=(
            "https://objects.example/tenants/tenant-123/derived/result.json"
            "?X-Amz-Signature=redacted"
        ),
        output_object_key="tenants/tenant-123/derived/result.json",
        document_id="document-123",
        document_version_id="document-version-123",
        page_index0=0,
        options={"chart_recognition": False},
    )


def _decode_part(value: str) -> dict[str, Any]:
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    return parsed


def test_worker_token_is_signed_and_narrowly_scoped() -> None:
    token = create_worker_token(
        secret=SECRET,
        audience="akc-gpu-worker",
        job_id="job-123",
        tenant_id="tenant-123",
        now=100,
        lifetime_seconds=300,
    )
    header, claims, signature = token.split(".")
    assert _decode_part(header) == {"alg": "HS256", "typ": "JWT"}
    assert _decode_part(claims) == {
        "aud": "akc-gpu-worker",
        "exp": 400,
        "iat": 100,
        "job_id": "job-123",
        "scope": "gpu:execute",
        "tenant_id": "tenant-123",
    }
    expected = hmac.new(
        SECRET,
        f"{header}.{claims}".encode(),
        hashlib.sha256,
    ).digest()
    assert hmac.compare_digest(
        expected,
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
    )


def test_job_rejects_cross_tenant_or_secret_bearing_input() -> None:
    with pytest.raises(ValueError, match="scoped URL/object key mismatch"):
        GpuJobRequest(
            **{
                **_job().__dict__,
                "input_object_key": "tenants/tenant-123/source/other.png",
            }
        )
    with pytest.raises(ValueError, match="sensitive provider option forbidden"):
        GpuJobRequest(**{**_job().__dict__, "options": {"api_key": "forbidden"}})


@pytest.mark.asyncio
async def test_submit_and_poll_validate_scope_revision_and_output() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/run"):
            return httpx.Response(
                200,
                json={"id": "provider-job-1", "status": "IN_QUEUE"},
            )
        return httpx.Response(
            200,
            json={
                "id": "provider-job-1",
                "status": "COMPLETED",
                "output": {
                    "ok": True,
                    "job_id": "job-123",
                    "tenant_id": "tenant-123",
                    "provider": "paddleocr_vl_1_6",
                    "model_revision": REVISION,
                    "runtime_image_digest": IMAGE_DIGEST,
                    "adapter_version": ADAPTER_VERSION,
                    "idempotency_key": "idem-123",
                    "result_id": "sha256:" + "c" * 64,
                    "output_object_key": "tenants/tenant-123/derived/result.json",
                    "output_sha256": "sha256:" + "d" * 64,
                    "output_bytes": 100,
                    "metrics": {
                        "gpu_seconds": 1.5,
                        "metering_source": "worker_estimate_not_provider_invoice",
                    },
                    "warnings": [],
                },
            },
        )

    http_client = httpx.AsyncClient(
        base_url="https://api.runpod.ai",
        transport=httpx.MockTransport(handler),
    )
    client = RunpodGpuClient(
        api_key="runpod-test-key",
        worker_hmac_secret=SECRET,
        allowed_input_hosts=frozenset({"objects.example"}),
        allowed_output_hosts=frozenset({"objects.example"}),
        client=http_client,
        clock=lambda: 100.0,
    )
    job = _job()
    submitted = await client.submit(job)
    result = await client.poll(job, submitted, timeout_seconds=10)
    await http_client.aclose()

    submit_payload = json.loads(seen[0].content)
    assert seen[0].headers["Idempotency-Key"] == "idem-123"
    assert submit_payload["input"]["idempotency_key"] == "idem-123"
    assert submit_payload["input"]["input_sha256"] == "b" * 64
    assert "callback_token" in submit_payload["input"]
    assert result.result_id == "sha256:" + "c" * 64
    assert result.raw_provider_response_sha256.startswith("sha256:")


@pytest.mark.asyncio
async def test_poll_rejects_tenant_or_revision_substitution() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "COMPLETED",
                "output": {
                    "ok": True,
                    "job_id": "job-123",
                    "tenant_id": "tenant-attacker",
                    "provider": "paddleocr_vl_1_6",
                    "model_revision": REVISION,
                    "runtime_image_digest": IMAGE_DIGEST,
                    "adapter_version": ADAPTER_VERSION,
                    "idempotency_key": "idem-123",
                    "result_id": "sha256:" + "c" * 64,
                    "output_object_key": "tenants/tenant-123/derived/result.json",
                    "output_sha256": "sha256:" + "d" * 64,
                    "output_bytes": 100,
                    "metrics": {},
                    "warnings": [],
                },
            },
        )

    http_client = httpx.AsyncClient(
        base_url="https://api.runpod.ai",
        transport=httpx.MockTransport(handler),
    )
    client = RunpodGpuClient(
        api_key="runpod-test-key",
        worker_hmac_secret=SECRET,
        allowed_input_hosts=frozenset({"objects.example"}),
        allowed_output_hosts=frozenset({"objects.example"}),
        client=http_client,
    )
    job = _job()
    submitted = SubmittedGpuJob(
        provider_job_id="provider-job-1",
        endpoint_id="parser-balanced",
        status="COMPLETED",
    )
    with pytest.raises(GpuProviderError, match="GPU_PROVIDER_RESULT_SCOPE_MISMATCH"):
        await client.poll(job, submitted, timeout_seconds=10)
    await http_client.aclose()


@pytest.mark.asyncio
async def test_poll_rejects_unbounded_warning_evidence() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "COMPLETED",
                "output": {
                    "ok": True,
                    "job_id": "job-123",
                    "tenant_id": "tenant-123",
                    "provider": "paddleocr_vl_1_6",
                    "model_revision": REVISION,
                    "runtime_image_digest": IMAGE_DIGEST,
                    "adapter_version": ADAPTER_VERSION,
                    "idempotency_key": "idem-123",
                    "result_id": "sha256:" + "c" * 64,
                    "output_object_key": "tenants/tenant-123/derived/result.json",
                    "output_sha256": "sha256:" + "d" * 64,
                    "output_bytes": 100,
                    "metrics": {},
                    "warnings": ["warning"] * 257,
                },
            },
        )

    http_client = httpx.AsyncClient(
        base_url="https://api.runpod.ai",
        transport=httpx.MockTransport(handler),
    )
    client = RunpodGpuClient(
        api_key="runpod-test-key",
        worker_hmac_secret=SECRET,
        allowed_input_hosts=frozenset({"objects.example"}),
        allowed_output_hosts=frozenset({"objects.example"}),
        client=http_client,
    )
    submitted = SubmittedGpuJob(
        provider_job_id="provider-job-1",
        endpoint_id="parser-balanced",
        status="COMPLETED",
    )
    with pytest.raises(GpuProviderError, match="GPU_PROVIDER_INVALID_RESULT"):
        await client.poll(_job(), submitted, timeout_seconds=10)
    await http_client.aclose()


@pytest.mark.asyncio
async def test_provider_429_is_retryable_without_leaking_response() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited", "secret": "do-not-log"})

    http_client = httpx.AsyncClient(
        base_url="https://api.runpod.ai",
        transport=httpx.MockTransport(handler),
    )
    client = RunpodGpuClient(
        api_key="runpod-test-key",
        worker_hmac_secret=SECRET,
        allowed_input_hosts=frozenset({"objects.example"}),
        allowed_output_hosts=frozenset({"objects.example"}),
        client=http_client,
    )
    with pytest.raises(GpuProviderError) as captured:
        await client.submit(_job())
    assert captured.value.code == "GPU_PROVIDER_RATE_LIMITED"
    assert captured.value.retryable is True
    assert "do-not-log" not in str(captured.value)
    await http_client.aclose()


@pytest.mark.asyncio
async def test_provider_5xx_has_a_distinct_retry_policy_code() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    http_client = httpx.AsyncClient(
        base_url="https://api.runpod.ai",
        transport=httpx.MockTransport(handler),
    )
    client = RunpodGpuClient(
        api_key="runpod-test-key",
        worker_hmac_secret=SECRET,
        allowed_input_hosts=frozenset({"objects.example"}),
        allowed_output_hosts=frozenset({"objects.example"}),
        client=http_client,
    )
    with pytest.raises(GpuProviderError) as captured:
        await client.submit(_job())
    assert captured.value.code == "GPU_PROVIDER_5XX"
    assert captured.value.retryable is True
    await http_client.aclose()


@pytest.mark.asyncio
async def test_submit_rejects_object_host_outside_deployment_allowlist() -> None:
    http_client = httpx.AsyncClient(
        base_url="https://api.runpod.ai",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                500,
                json={"error": "must not be reached"},
            )
        ),
    )
    client = RunpodGpuClient(
        api_key="runpod-test-key",
        worker_hmac_secret=SECRET,
        allowed_input_hosts=frozenset({"different.example"}),
        allowed_output_hosts=frozenset({"objects.example"}),
        client=http_client,
    )
    with pytest.raises(GpuProviderError, match="GPU_PROVIDER_OBJECT_HOST_FORBIDDEN"):
        await client.submit(_job())
    await http_client.aclose()
