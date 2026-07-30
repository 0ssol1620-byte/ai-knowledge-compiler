"""Authenticated Runpod control-plane adapter for hardened GPU workers.

This module owns only provider transport and response validation. Durable
submission, retries, admission, and billing remain scheduler/database
responsibilities so an HTTP timeout cannot become an untracked side effect.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

import httpx

_ENDPOINT_ID = re.compile(r"^[A-Za-z0-9_-]{3,80}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,159}$")
_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RESULT_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_PROVIDER_RESPONSE_BYTES = 12 * 1024 * 1024
_TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"})


class GpuProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class GpuJobRequest:
    endpoint_id: str
    provider_key: str
    model_revision: str
    runtime_image_digest: str
    adapter_version: str
    job_id: str
    tenant_id: str
    idempotency_key: str
    input_url: str
    input_object_key: str
    input_sha256: str
    output_url: str
    output_object_key: str
    options: dict[str, Any] = field(default_factory=dict)
    document_id: str | None = None
    document_version_id: str | None = None
    page_index0: int | None = None

    def __post_init__(self) -> None:
        for name in ("provider_key", "job_id", "tenant_id", "idempotency_key"):
            if not _IDENTIFIER.fullmatch(str(getattr(self, name))):
                raise ValueError(f"invalid {name}")
        if not _ENDPOINT_ID.fullmatch(self.endpoint_id):
            raise ValueError("invalid endpoint_id")
        if not _REVISION.fullmatch(self.model_revision):
            raise ValueError("exact model_revision is required")
        if not _IMAGE_DIGEST.fullmatch(self.runtime_image_digest):
            raise ValueError("exact runtime_image_digest is required")
        if not _IDENTIFIER.fullmatch(self.adapter_version):
            raise ValueError("exact adapter_version is required")
        normalized_sha = self.input_sha256.removeprefix("sha256:")
        if not _SHA256.fullmatch(normalized_sha):
            raise ValueError("invalid input_sha256")
        object.__setattr__(self, "input_sha256", normalized_sha)
        _validate_scoped_url(
            self.input_url,
            object_key=self.input_object_key,
            tenant_id=self.tenant_id,
        )
        _validate_scoped_url(
            self.output_url,
            object_key=self.output_object_key,
            tenant_id=self.tenant_id,
        )
        if self.document_id is not None and not _IDENTIFIER.fullmatch(self.document_id):
            raise ValueError("invalid document_id")
        if self.document_version_id is not None and not _IDENTIFIER.fullmatch(
            self.document_version_id
        ):
            raise ValueError("invalid document_version_id")
        if self.page_index0 is not None and (
            not isinstance(self.page_index0, int)
            or isinstance(self.page_index0, bool)
            or self.page_index0 < 0
        ):
            raise ValueError("invalid page_index0")
        try:
            options_bytes = _canonical_json(self.options)
        except (TypeError, ValueError) as exc:
            raise ValueError("options must be finite JSON") from exc
        if len(options_bytes) > 1024 * 1024:
            raise ValueError("options too large")
        for key in self.options:
            if not isinstance(key, str):
                raise ValueError("option keys must be strings")
            folded = key.casefold()
            if folded in {"api_key", "password", "secret", "token"} or folded.endswith(
                ("_api_key", "_password", "_secret", "_token", "_url")
            ):
                raise ValueError("sensitive provider option forbidden")


@dataclass(frozen=True)
class SubmittedGpuJob:
    provider_job_id: str
    endpoint_id: str
    status: str


@dataclass(frozen=True)
class GpuJobResult:
    provider_job_id: str
    endpoint_id: str
    provider_key: str
    model_revision: str
    runtime_image_digest: str
    adapter_version: str
    result_id: str
    output_object_key: str
    output_sha256: str
    output_bytes: int
    metrics: dict[str, Any]
    warnings: tuple[str, ...]
    raw_provider_response_sha256: str


@dataclass(frozen=True)
class GpuJobPoll:
    """One durable polling observation.

    Non-terminal observations intentionally carry no provider payload. The
    scheduler persists only the bounded status and polls again in a later
    transaction-free attempt.
    """

    status: Literal["IN_QUEUE", "IN_PROGRESS", "COMPLETED"]
    result: GpuJobResult | None = None


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _validate_scoped_url(url: str, *, object_key: str, tenant_id: str) -> None:
    if len(url) > 4096 or any(ord(character) < 0x20 for character in url):
        raise ValueError("invalid scoped URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("invalid scoped URL")
    normalized_key = unquote(object_key).replace("\\", "/")
    if (
        normalized_key != object_key
        or "//" in normalized_key
        or any(part in {"", ".", ".."} for part in normalized_key.split("/"))
        or not normalized_key.startswith(f"tenants/{tenant_id}/")
    ):
        raise ValueError("invalid tenant object key")
    decoded_path = unquote(parsed.path).replace("\\", "/").lstrip("/")
    if decoded_path != normalized_key and not decoded_path.endswith(f"/{normalized_key}"):
        raise ValueError("scoped URL/object key mismatch")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def create_worker_token(
    *,
    secret: bytes,
    audience: str,
    job_id: str,
    tenant_id: str,
    now: int,
    lifetime_seconds: int,
) -> str:
    if len(secret) < 32:
        raise ValueError("worker callback secret must be at least 32 bytes")
    if not 30 <= lifetime_seconds <= 900:
        raise ValueError("worker token lifetime must be 30..900 seconds")
    header = _b64url(_canonical_json({"alg": "HS256", "typ": "JWT"}))
    claims = _b64url(
        _canonical_json(
            {
                "aud": audience,
                "exp": now + lifetime_seconds,
                "iat": now,
                "job_id": job_id,
                "scope": "gpu:execute",
                "tenant_id": tenant_id,
            }
        )
    )
    signing_input = f"{header}.{claims}"
    signature = _b64url(hmac.new(secret, signing_input.encode(), hashlib.sha256).digest())
    return f"{signing_input}.{signature}"


class RunpodGpuClient:
    def __init__(
        self,
        *,
        api_key: str,
        worker_hmac_secret: bytes,
        allowed_input_hosts: frozenset[str],
        allowed_output_hosts: frozenset[str],
        callback_audience: str = "akc-gpu-worker",
        request_timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key or len(api_key) > 2048:
            raise ValueError("Runpod API key is required")
        if len(worker_hmac_secret) < 32:
            raise ValueError("worker HMAC secret must be at least 32 bytes")
        if not allowed_input_hosts or not allowed_output_hosts:
            raise ValueError("provider object host allowlists are required")
        for host in allowed_input_hosts | allowed_output_hosts:
            if host != host.casefold() or not host or "*" in host or "/" in host or ":" in host:
                raise ValueError("invalid provider object host allowlist")
        if not _IDENTIFIER.fullmatch(callback_audience):
            raise ValueError("invalid callback audience")
        if not math.isfinite(request_timeout_seconds) or not 1 <= request_timeout_seconds <= 120:
            raise ValueError("invalid provider request timeout")
        self._api_key = api_key
        self._worker_hmac_secret = worker_hmac_secret
        self._allowed_input_hosts = allowed_input_hosts
        self._allowed_output_hosts = allowed_output_hosts
        self._callback_audience = callback_audience
        self._timeout = request_timeout_seconds
        self._client = client or httpx.AsyncClient(
            base_url="https://api.runpod.ai",
            timeout=httpx.Timeout(request_timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )
        self._owns_client = client is None
        self._clock = clock
        self._sleep = sleeper

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = self._headers
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = await self._client.request(
                method,
                path,
                content=_canonical_json(payload) if payload is not None else None,
                headers=headers,
                timeout=self._timeout,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GpuProviderError("GPU_PROVIDER_UNAVAILABLE", retryable=True) from exc
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > _MAX_PROVIDER_RESPONSE_BYTES:
                    raise GpuProviderError("GPU_PROVIDER_RESPONSE_TOO_LARGE")
            except ValueError as exc:
                raise GpuProviderError("GPU_PROVIDER_INVALID_CONTENT_LENGTH") from exc
        if len(response.content) > _MAX_PROVIDER_RESPONSE_BYTES:
            raise GpuProviderError("GPU_PROVIDER_RESPONSE_TOO_LARGE")
        if response.status_code == 429:
            raise GpuProviderError("GPU_PROVIDER_RATE_LIMITED", retryable=True)
        if response.status_code >= 500:
            raise GpuProviderError("GPU_PROVIDER_5XX", retryable=True)
        if response.status_code < 200 or response.status_code >= 300:
            raise GpuProviderError("GPU_PROVIDER_REQUEST_REJECTED")
        try:
            value = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GpuProviderError("GPU_PROVIDER_INVALID_RESPONSE") from exc
        if not isinstance(value, dict):
            raise GpuProviderError("GPU_PROVIDER_INVALID_RESPONSE")
        return value

    async def submit(self, request: GpuJobRequest) -> SubmittedGpuJob:
        input_host = (urlsplit(request.input_url).hostname or "").casefold()
        output_host = (urlsplit(request.output_url).hostname or "").casefold()
        if (
            input_host not in self._allowed_input_hosts
            or output_host not in self._allowed_output_hosts
        ):
            raise GpuProviderError("GPU_PROVIDER_OBJECT_HOST_FORBIDDEN")
        callback_token = create_worker_token(
            secret=self._worker_hmac_secret,
            audience=self._callback_audience,
            job_id=request.job_id,
            tenant_id=request.tenant_id,
            now=int(self._clock()),
            lifetime_seconds=900,
        )
        worker_input: dict[str, Any] = {
            "job_id": request.job_id,
            "tenant_id": request.tenant_id,
            "idempotency_key": request.idempotency_key,
            "callback_token": callback_token,
            "input_url": request.input_url,
            "input_object_key": request.input_object_key,
            "input_sha256": request.input_sha256,
            "expected_model_revision": request.model_revision,
            "expected_runtime_image_digest": request.runtime_image_digest,
            "expected_adapter_version": request.adapter_version,
            "output_url": request.output_url,
            "output_object_key": request.output_object_key,
            "options": request.options,
        }
        if request.document_id is not None:
            worker_input["document_id"] = request.document_id
        if request.document_version_id is not None:
            worker_input["document_version_id"] = request.document_version_id
        if request.page_index0 is not None:
            worker_input["page_index0"] = request.page_index0
        response = await self._request(
            "POST",
            f"/v2/{request.endpoint_id}/run",
            payload={"input": worker_input},
            idempotency_key=request.idempotency_key,
        )
        provider_job_id = response.get("id")
        status = response.get("status")
        if (
            not isinstance(provider_job_id, str)
            or not _IDENTIFIER.fullmatch(provider_job_id)
            or status not in {"IN_QUEUE", "IN_PROGRESS", "COMPLETED"}
        ):
            raise GpuProviderError("GPU_PROVIDER_INVALID_SUBMISSION")
        return SubmittedGpuJob(
            provider_job_id=provider_job_id,
            endpoint_id=request.endpoint_id,
            status=status,
        )

    async def cancel(self, submitted: SubmittedGpuJob) -> None:
        await self._request(
            "POST",
            f"/v2/{submitted.endpoint_id}/cancel/{submitted.provider_job_id}",
        )

    async def poll(
        self,
        request: GpuJobRequest,
        submitted: SubmittedGpuJob,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float = 1.0,
    ) -> GpuJobResult:
        if submitted.endpoint_id != request.endpoint_id:
            raise ValueError("submitted endpoint does not match request")
        if not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 3600:
            raise ValueError("invalid poll timeout")
        if not math.isfinite(poll_interval_seconds) or not 0.05 <= poll_interval_seconds <= 30:
            raise ValueError("invalid poll interval")
        deadline = self._clock() + timeout_seconds
        while True:
            observation = await self.poll_once(request, submitted)
            if observation.result is not None:
                return observation.result
            if self._clock() >= deadline:
                raise GpuProviderError("GPU_PROVIDER_POLL_TIMEOUT", retryable=True)
            await self._sleep(poll_interval_seconds)

    async def poll_once(
        self,
        request: GpuJobRequest,
        submitted: SubmittedGpuJob,
    ) -> GpuJobPoll:
        """Read one provider status without holding a scheduler transaction."""

        if submitted.endpoint_id != request.endpoint_id:
            raise ValueError("submitted endpoint does not match request")
        response = await self._request(
            "GET",
            f"/v2/{request.endpoint_id}/status/{submitted.provider_job_id}",
        )
        status = response.get("status")
        if status not in {
            "IN_QUEUE",
            "IN_PROGRESS",
            "COMPLETED",
            "FAILED",
            "CANCELLED",
            "TIMED_OUT",
        }:
            raise GpuProviderError("GPU_PROVIDER_INVALID_STATUS")
        if status in _TERMINAL_STATES:
            return GpuJobPoll(
                status="COMPLETED",
                result=_validate_terminal_response(
                    request,
                    submitted,
                    status=status,
                    response=response,
                ),
            )
        return GpuJobPoll(status=status)


def _validate_terminal_response(
    request: GpuJobRequest,
    submitted: SubmittedGpuJob,
    *,
    status: str,
    response: dict[str, Any],
) -> GpuJobResult:
    if status != "COMPLETED":
        error_code = {
            "FAILED": "GPU_PROVIDER_JOB_FAILED",
            "CANCELLED": "GPU_PROVIDER_JOB_CANCELLED",
            "TIMED_OUT": "GPU_PROVIDER_JOB_TIMED_OUT",
        }[status]
        raise GpuProviderError(
            error_code,
            retryable=status in {"FAILED", "TIMED_OUT"},
        )
    output = response.get("output")
    if not isinstance(output, dict):
        raise GpuProviderError("GPU_PROVIDER_INVALID_RESULT")
    if output.get("ok") is not True:
        error = output.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        retryable = bool(error.get("retryable")) if isinstance(error, dict) else False
        raise GpuProviderError(
            f"GPU_WORKER_{str(code or 'FAILED').upper()}",
            retryable=retryable,
        )
    expected = {
        "job_id": request.job_id,
        "tenant_id": request.tenant_id,
        "provider": request.provider_key,
        "model_revision": request.model_revision,
        "runtime_image_digest": request.runtime_image_digest,
        "adapter_version": request.adapter_version,
        "idempotency_key": request.idempotency_key,
        "output_object_key": request.output_object_key,
    }
    if any(output.get(key) != value for key, value in expected.items()):
        raise GpuProviderError("GPU_PROVIDER_RESULT_SCOPE_MISMATCH")
    result_id = output.get("result_id")
    output_sha = output.get("output_sha256")
    output_bytes = output.get("output_bytes")
    metrics = output.get("metrics")
    warnings = output.get("warnings", [])
    if (
        not isinstance(result_id, str)
        or not _RESULT_ID.fullmatch(result_id)
        or not isinstance(output_sha, str)
        or not output_sha.startswith("sha256:")
        or not _SHA256.fullmatch(output_sha.removeprefix("sha256:"))
        or not isinstance(output_bytes, int)
        or isinstance(output_bytes, bool)
        or output_bytes <= 0
        or not isinstance(metrics, dict)
        or not isinstance(warnings, list)
        or len(warnings) > 256
        or any(not isinstance(item, str) or not item or len(item) > 1000 for item in warnings)
    ):
        raise GpuProviderError("GPU_PROVIDER_INVALID_RESULT")
    raw_hash = hashlib.sha256(_canonical_json(response)).hexdigest()
    return GpuJobResult(
        provider_job_id=submitted.provider_job_id,
        endpoint_id=submitted.endpoint_id,
        provider_key=request.provider_key,
        model_revision=request.model_revision,
        runtime_image_digest=request.runtime_image_digest,
        adapter_version=request.adapter_version,
        result_id=result_id,
        output_object_key=request.output_object_key,
        output_sha256=output_sha,
        output_bytes=output_bytes,
        metrics=metrics,
        warnings=tuple(warnings),
        raw_provider_response_sha256=f"sha256:{raw_hash}",
    )
