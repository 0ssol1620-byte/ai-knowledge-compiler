"""Client for the worker HTTP API of ARENA_CONTRACT section 4.

The controller talks to a pod only through this class. Two rules are load
bearing:

- **Checksum before acceptance.** Every ``RunResponse`` carries
  ``raw_output_sha256``. It is recomputed here over the UTF-8 bytes of
  ``raw_output.raw_text`` -- the same bytes ARENA_CONTRACT section 3.10 says
  are persisted as ``<case_key>.raw.txt``. A mismatch is a ``CHECKSUM``
  failure and the response is never accepted, never written, never marked
  SUCCESS.
- **The bearer stays a Secret.** It is revealed once, when the header dict is
  built, and appears in no receipt, log or exception.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType, TracebackType
from typing import Any, Final, Self

import httpx

from arena.constants import ERROR_CLASSES, WORKER_API_PREFIX, WORKER_PORT, WORKER_STATES
from arena.provider.safety import sha256_text
from arena.provider.secrets import Secret

# The worker's redactor, not a second copy of it: arena.worker.util is
# standard-library only and the patterns it strips are the ones the on-pod
# process already applies to the same strings before they leave the pod.
from arena.worker.util import redact

__all__ = [
    "MAX_REJECTION_DETAIL_CHARS",
    "REJECTION_ERROR_CLASSES",
    "SEMANTIC_ERROR_CLASSES",
    "RunRequest",
    "RunResponse",
    "WorkerChecksumError",
    "WorkerClient",
    "WorkerError",
    "WorkerHTTPError",
    "WorkerProtocolError",
    "WorkerTransportError",
    "worker_base_url",
]

PROXY_HOST_TEMPLATE: Final = "https://{pod_id}-{port}.proxy.runpod.net"

# ARENA_CONTRACT section 11 D3: a semantic failure the model produced, as
# opposed to an operational failure of the pod. An empty output is still
# SUCCESS (MP section 41); this class is what says it was empty.
SEMANTIC_ERROR_CLASSES: Final = (
    "OUTPUT_EMPTY",
    "OUTPUT_TRUNCATED",
    "OUTPUT_REPETITION",
    "OUTPUT_MALFORMED",
)
DEFAULT_TIMEOUTS: Final = MappingProxyType(
    {
        "ready": 20.0,
        "heartbeat": 15.0,
        "provenance": 30.0,
        "run": 900.0,
        "result": 30.0,
        "drain": 30.0,
    }
)

# The worker refuses a request it cannot serve with 422 and
# ``{"error": <code>, "detail": ...}`` (arena.worker.server.RequestRejected).
# None of these codes is a masterplan 15.9 row, and none of them is transient:
# the controller sent a request this runtime will never accept, so the honest
# class is ``UNKNOWN``, whose rule is "no masterplan 15.9 row; fail closed" --
# zero retries. Recording them as INFRA_NETWORK bought three retries with
# backoff per page against a deterministic refusal, on a billed GPU.
REJECTION_ERROR_CLASSES: Final = MappingProxyType(
    {
        "CAMPAIGN_MISMATCH": "UNKNOWN",
        "CONFIG_MISMATCH": "UNKNOWN",
        "PROMPT_MISMATCH": "UNKNOWN",
        "INVALID_REQUEST": "UNKNOWN",
    }
)

#: How much of a 422 ``detail`` reaches a page record. Long enough for two
#: sha256 refs and the sentence between them, short enough that a body cannot
#: become the receipt.
MAX_REJECTION_DETAIL_CHARS: Final = 400

#: The one status whose body the worker wrote (ARENA_CONTRACT section 4).
REJECTION_STATUS: Final = 422


class WorkerError(RuntimeError):
    """Sanitized worker failure."""


class WorkerHTTPError(WorkerError):
    """The pod answered, with a status the caller did not expect.

    The status code is carried rather than only formatted into the message,
    because the readiness poll has to tell two very different answers apart: a
    404/502/503 from the RunPod proxy means nothing is listening on 8000 yet
    and the pod is still installing, while a 401/403 means the bearer is wrong
    and no amount of waiting will fix it.

    ``worker_error_code`` and ``error_class`` are filled from a 422 body (see
    :func:`_rejection_facts`) so the controller can classify a refusal instead
    of recording every one of them as a transient network fault.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        url: str,
        worker_error_code: str | None = None,
        error_class: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.worker_error_code = worker_error_code
        self.error_class = error_class


class WorkerTransportError(WorkerError):
    """Nothing answered at all: no socket, no TLS handshake, no reply in time."""

    def __init__(self, message: str, *, url: str) -> None:
        super().__init__(message)
        self.url = url


class WorkerProtocolError(WorkerError):
    """The worker response does not match the section 4 contract."""


class WorkerChecksumError(WorkerError):
    """``raw_output_sha256`` does not match the bytes the worker returned."""

    error_class: Final = "CHECKSUM"


def worker_base_url(pod_id: str, *, port: int = WORKER_PORT) -> str:
    if not pod_id.strip():
        raise WorkerError("pod id is required to address a worker")
    return PROXY_HOST_TEMPLATE.format(pod_id=pod_id, port=port)


@dataclass(frozen=True, slots=True)
class RunRequest:
    campaign_id: str
    inference_job_id: str
    sample_id: str
    case_key: str
    benchmark: str
    source_sha256: str
    image_bytes: bytes
    width: int
    height: int
    prompt_id: str
    prompt_sha256: str
    inference_config_sha256: str
    job_kind: str = "inference"
    timeout_seconds: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.job_kind not in {"inference", "canary", "recovery"}:
            raise WorkerError("job_kind must be inference, canary or recovery")
        if not self.image_bytes:
            raise WorkerError("a run request must carry the page image bytes")
        if self.width < 1 or self.height < 1:
            raise WorkerError("page dimensions must be positive")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "campaign_id": self.campaign_id,
            "inference_job_id": self.inference_job_id,
            "sample_id": self.sample_id,
            "case_key": self.case_key,
            "benchmark": self.benchmark,
            "source_sha256": self.source_sha256,
            "image_b64": base64.b64encode(self.image_bytes).decode("ascii"),
            "width": self.width,
            "height": self.height,
            "prompt_id": self.prompt_id,
            "prompt_sha256": self.prompt_sha256,
            "inference_config_sha256": self.inference_config_sha256,
            "job_kind": self.job_kind,
            "metadata": dict(self.metadata),
        }
        if self.timeout_seconds is not None:
            payload["timeout_seconds"] = self.timeout_seconds
        return payload


@dataclass(frozen=True, slots=True)
class RunResponse:
    inference_job_id: str
    status: str
    error_class: str | None
    error_message: str | None
    worker_id: str
    model_key: str
    model_revision: str
    runtime_mode: str
    runtime_image_digest: str
    gpu_type: str | None
    pod_id: str | None
    started_at: str
    first_token_at: str | None
    finished_at: str
    timings_ms: Mapping[str, int]
    peak_vram_mb: int | None
    input_bytes: int
    output_bytes: int
    output_chars: int
    input_tokens: int | None
    output_tokens: int | None
    raw_text: str
    output_format: str
    native_json: Mapping[str, Any] | None
    warnings: tuple[str, ...]
    canonical_markdown: str
    canonical_lossy: bool
    conversion_notes: tuple[str, ...]
    raw_output_sha256: str
    canonical_output_sha256: str
    semantic_error_class: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "SUCCESS"


class WorkerClient:
    """One pod's worker API."""

    def __init__(
        self,
        base_url: str,
        *,
        bearer: Secret,
        timeouts: Mapping[str, float] | None = None,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url.startswith("http"):
            raise WorkerError("worker base URL must be an http(s) URL")
        self.base_url = base_url.rstrip("/")
        self._bearer = bearer
        self._timeouts = dict(DEFAULT_TIMEOUTS)
        if timeouts:
            self._timeouts.update(dict(timeouts))
        self._http = client or httpx.Client(follow_redirects=False, transport=transport)
        self._owns_client = client is None

    def __repr__(self) -> str:
        return f"WorkerClient(base_url={self.base_url!r})"

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def _headers(self) -> dict[str, str]:
        # The single audited place the worker bearer is revealed.
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._bearer.reveal()}",
        }

    def _call(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        payload: Mapping[str, object] | None = None,
        allow_not_found: bool = False,
        expected_status: int = 200,
    ) -> Mapping[str, Any] | None:
        url = f"{self.base_url}{WORKER_API_PREFIX}{path}"
        headers = self._headers()
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = self._http.request(
                method,
                url,
                headers=headers,
                json=payload,
                timeout=self._timeouts.get(operation, 60.0),
            )
        except httpx.HTTPError as exc:
            raise WorkerTransportError(
                f"worker transport failure for {method} {url}: {type(exc).__name__}", url=url
            ) from None
        if allow_not_found and response.status_code == 404:
            return None
        if response.status_code in {401, 403}:
            raise WorkerHTTPError(
                f"worker rejected the bearer for {method} {url} "
                f"(HTTP {response.status_code})",
                status_code=response.status_code,
                url=url,
            )
        if response.status_code == 409:
            raise WorkerHTTPError(
                f"worker is draining and refused {method} {url}",
                status_code=409,
                url=url,
            )
        if response.status_code != expected_status:
            code, error_class, detail = _rejection_facts(response)
            said = "; body withheld" if code is None else f": {code}"
            if detail:
                said = f"{said} -- {detail}"
            raise WorkerHTTPError(
                f"worker returned HTTP {response.status_code} for {method} {url}{said}",
                status_code=response.status_code,
                url=url,
                worker_error_code=code,
                error_class=error_class,
            )
        try:
            body = response.json()
        except ValueError:
            raise WorkerProtocolError(f"worker {method} {url} returned invalid JSON") from None
        if not isinstance(body, Mapping):
            raise WorkerProtocolError(f"worker {method} {url} did not return a JSON object")
        return body

    def ready(self) -> Mapping[str, Any]:
        body = self._call("GET", "/ready", operation="ready")
        assert body is not None
        stage = body.get("stage")
        if stage not in WORKER_STATES:
            raise WorkerProtocolError(f"worker reported unknown stage {stage!r}")
        return body

    def heartbeat(self) -> Mapping[str, Any]:
        body = self._call("GET", "/heartbeat", operation="heartbeat")
        assert body is not None
        stage = body.get("stage")
        if stage not in WORKER_STATES:
            raise WorkerProtocolError(f"heartbeat reported unknown stage {stage!r}")
        return body

    def provenance(self) -> Mapping[str, Any]:
        body = self._call("GET", "/provenance", operation="provenance")
        assert body is not None
        return body

    def drain(self) -> Mapping[str, Any]:
        body = self._call("POST", "/drain", operation="drain", payload={})
        assert body is not None
        if body.get("stage") != "DRAINING":
            raise WorkerProtocolError("drain did not move the worker to DRAINING")
        return body

    def run(self, request: RunRequest) -> RunResponse:
        body = self._call("POST", "/run", operation="run", payload=request.to_payload())
        assert body is not None
        return self._accept(body, expected_job_id=request.inference_job_id)

    def result(self, inference_job_id: str) -> RunResponse | None:
        body = self._call(
            "GET",
            f"/result/{inference_job_id}",
            operation="result",
            allow_not_found=True,
        )
        if body is None:
            return None
        return self._accept(body, expected_job_id=inference_job_id)

    def _accept(self, body: Mapping[str, Any], *, expected_job_id: str) -> RunResponse:
        response = _parse_run_response(body)
        if response.inference_job_id != expected_job_id:
            raise WorkerProtocolError(
                "worker answered with a different inference_job_id than was requested"
            )
        if response.succeeded:
            recomputed = sha256_text(response.raw_text)
            if recomputed != response.raw_output_sha256:
                raise WorkerChecksumError(
                    f"raw_output_sha256 mismatch for job {expected_job_id}: "
                    f"worker claimed {response.raw_output_sha256}, bytes hash to {recomputed}"
                )
        return response


def _rejection_facts(response: httpx.Response) -> tuple[str | None, str | None, str | None]:
    """``(worker code, error class, scrubbed detail)`` from a refusal body.

    The worker answers a refusal in one of two shapes, and both carry the one
    fact worth keeping -- *which* check failed:

    - ``{"error": "CONFIG_MISMATCH", "detail": "..."}`` from ``RequestRejected``
    - a full ``RunResponse`` with ``error_class`` ``INPUT_DECODE`` / ``CHECKSUM``

    Nothing else from the body is surfaced: the message goes into a page
    record, and a page record must never carry a body verbatim. The detail is
    passed through the worker's own redactor and capped, and an ``error_class``
    outside the section 16 taxonomy is dropped rather than propagated, because
    ``retry.rule_for`` refuses a class it does not know and the failure would
    surface as a crash in the controller rather than as a failed page.

    Only 422 is read. That is the worker's refusal channel (section 4); a 404,
    502 or 503 comes from the RunPod proxy in front of a pod that is not
    listening yet, and whatever is in that body was not written by a worker.
    """

    if response.status_code != REJECTION_STATUS:
        return None, None, None
    try:
        body = response.json()
    except ValueError:
        return None, None, None
    if not isinstance(body, Mapping):
        return None, None, None

    declared = body.get("error_class")
    if isinstance(declared, str) and declared in ERROR_CLASSES:
        code: str | None = declared
        error_class: str | None = declared
    else:
        raw_code = body.get("error")
        code = raw_code if isinstance(raw_code, str) and raw_code else None
        error_class = REJECTION_ERROR_CLASSES.get(code) if code is not None else None

    raw_detail = body.get("detail")
    if not isinstance(raw_detail, str) or not raw_detail:
        raw_detail = body.get("error_message")
    detail: str | None = None
    if isinstance(raw_detail, str) and raw_detail:
        detail = redact(raw_detail.replace("\r", " ").replace("\n", " "))
        if len(detail) > MAX_REJECTION_DETAIL_CHARS:
            detail = detail[: MAX_REJECTION_DETAIL_CHARS - 3] + "..."
    return code, error_class, detail


def _parse_run_response(body: Mapping[str, Any]) -> RunResponse:
    status = _string(body, "status", "RunResponse")
    if status not in {"SUCCESS", "FAILED"}:
        raise WorkerProtocolError(f"RunResponse.status {status!r} is outside the contract")
    error_class = _optional_string(body, "error_class")
    if error_class is not None and error_class not in ERROR_CLASSES:
        raise WorkerProtocolError(f"RunResponse.error_class {error_class!r} is not in the taxonomy")
    if status == "FAILED" and error_class is None:
        raise WorkerProtocolError("a FAILED RunResponse must carry an error_class")
    raw_output = body.get("raw_output")
    if not isinstance(raw_output, Mapping):
        raise WorkerProtocolError("RunResponse.raw_output is missing")
    canonical = body.get("canonical")
    if not isinstance(canonical, Mapping):
        raise WorkerProtocolError("RunResponse.canonical is missing")
    timings = body.get("timings_ms")
    if not isinstance(timings, Mapping):
        raise WorkerProtocolError("RunResponse.timings_ms is missing")
    native = raw_output.get("native_json")
    if native is not None and not isinstance(native, Mapping):
        raise WorkerProtocolError("raw_output.native_json must be an object or null")
    semantic = _optional_string(body, "semantic_error_class")
    if semantic is not None and semantic not in SEMANTIC_ERROR_CLASSES:
        raise WorkerProtocolError(
            f"RunResponse.semantic_error_class {semantic!r} is not in the D3 enum"
        )
    return RunResponse(
        inference_job_id=_string(body, "inference_job_id", "RunResponse"),
        status=status,
        error_class=error_class,
        error_message=_optional_string(body, "error_message"),
        worker_id=_string(body, "worker_id", "RunResponse"),
        model_key=_string(body, "model_key", "RunResponse"),
        model_revision=_string(body, "model_revision", "RunResponse"),
        runtime_mode=_string(body, "runtime_mode", "RunResponse"),
        runtime_image_digest=_string(body, "runtime_image_digest", "RunResponse"),
        gpu_type=_optional_string(body, "gpu_type"),
        pod_id=_optional_string(body, "pod_id"),
        started_at=_string(body, "started_at", "RunResponse"),
        first_token_at=_optional_string(body, "first_token_at"),
        finished_at=_string(body, "finished_at", "RunResponse"),
        timings_ms=MappingProxyType(
            {str(key): int(value) for key, value in timings.items() if isinstance(value, int)}
        ),
        peak_vram_mb=_optional_int(body, "peak_vram_mb"),
        input_bytes=_int(body, "input_bytes"),
        output_bytes=_int(body, "output_bytes"),
        output_chars=_int(body, "output_chars"),
        input_tokens=_optional_int(body, "input_tokens"),
        output_tokens=_optional_int(body, "output_tokens"),
        raw_text=str(raw_output.get("raw_text", "")),
        output_format=str(raw_output.get("output_format", "text")),
        native_json=None if native is None else MappingProxyType(dict(native)),
        warnings=tuple(str(item) for item in raw_output.get("warnings", ()) or ()),
        canonical_markdown=str(canonical.get("markdown", "")),
        canonical_lossy=bool(canonical.get("lossy", False)),
        conversion_notes=tuple(str(item) for item in canonical.get("conversion_notes", ()) or ()),
        raw_output_sha256=_string(body, "raw_output_sha256", "RunResponse"),
        canonical_output_sha256=_string(body, "canonical_output_sha256", "RunResponse"),
        semantic_error_class=semantic,
    )


def _string(body: Mapping[str, Any], key: str, context: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise WorkerProtocolError(f"{context}.{key} is missing or not a non-empty string")
    return value


def _optional_string(body: Mapping[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise WorkerProtocolError(f"RunResponse.{key} must be a string or null")
    return value


def _int(body: Mapping[str, Any], key: str) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkerProtocolError(f"RunResponse.{key} is missing or not an integer")
    return value


def _optional_int(body: Mapping[str, Any], key: str) -> int | None:
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkerProtocolError(f"RunResponse.{key} must be an integer or null")
    return int(value)
