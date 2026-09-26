"""A worker pod that never existed: the section 4 API over an httpx transport.

The controller talks to a worker only through :class:`WorkerClient`, so the
honest way to test the driver is to answer real HTTP on a fake transport
rather than to stub the client out. Everything the driver can meet in the
field is reachable from here: a pod that warms slowly, one that never becomes
READY, one that times out on a page, one that crashes, and one that reports a
runtime digest other than the one we provisioned.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import httpx
from arena.provider.safety import sha256_text
from arena.provider.secrets import Secret
from arena.provider.worker_client import WorkerClient, worker_base_url

__all__ = [
    "BEARER",
    "CANONICAL",
    "RAW",
    "FakeWorkerTransport",
    "fake_worker_client",
    "json_response",
    "worker_response_body",
]

RAW = "# Page\n\nTranscribed text.\n"
CANONICAL = "# Page\n\nTranscribed text.\n"
BEARER = Secret("arena-fake-bearer-value-0000000000", label="ARENA_WORKER_TOKEN")

_DEFAULT_MODEL_KEY = "paddleocr_vl_1_6"


def json_response(status: int, payload: object) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def worker_response_body(
    job_id: str,
    *,
    model_key: str = _DEFAULT_MODEL_KEY,
    runtime_mode: str = "baked",
    runtime_image_digest: str = "sha256:" + "b" * 64,
    **overrides: object,
) -> dict[str, object]:
    """One section 4 ``RunResponse``, byte-consistent with its own hashes."""

    body: dict[str, object] = {
        "inference_job_id": job_id,
        "status": "SUCCESS",
        "error_class": None,
        "error_message": None,
        "worker_id": f"{model_key}-w0-pod_fake",
        "model_key": model_key,
        "model_revision": "a" * 40,
        "runtime_mode": runtime_mode,
        "runtime_image_digest": runtime_image_digest,
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "pod_id": "pod_fake",
        "started_at": "2026-09-03T10:00:00Z",
        "first_token_at": None,
        "finished_at": "2026-09-03T10:00:04Z",
        "timings_ms": {
            "load_ms": 0,
            "preprocess_ms": 100,
            "inference_ms": 3400,
            "postprocess_ms": 60,
            "total_ms": 3560,
        },
        "peak_vram_mb": 17000,
        "input_bytes": 1024,
        "output_bytes": len(RAW.encode("utf-8")),
        "output_chars": len(RAW),
        "input_tokens": None,
        "output_tokens": 210,
        "raw_output": {
            "raw_text": RAW,
            "output_format": "markdown",
            "native_json": None,
            "usage": {},
            "warnings": [],
        },
        "canonical": {
            "markdown": CANONICAL,
            "elements": None,
            "lossy": False,
            "conversion_notes": [],
        },
        "raw_output_sha256": sha256_text(RAW),
        "canonical_output_sha256": sha256_text(CANONICAL),
    }
    body.update(overrides)
    return body


class FakeWorkerTransport(httpx.BaseTransport):
    """A worker pod. Answers ``/v1/ready``, ``/v1/run`` and ``/v1/drain``.

    ``stages`` is consumed one entry per ``/v1/ready`` poll; a single-entry
    list is answered forever, which is how a pod that is already READY behaves.
    ``run_override`` takes the job id and returns the body to answer with, so a
    test can fail exactly the third page and no other.

    ``ready_answers`` models the RunPod proxy in front of a pod that is still
    installing: each entry is either an HTTP status to answer ``/v1/ready``
    with (404, 502, 503 -- nothing is listening on 8000 yet) or an exception to
    raise (the connection that never lands). It is consumed like ``stages``, so
    ``[404, 503, 200]`` is a pod that comes up on the third poll and
    ``[404]`` is one that never does. ``200`` falls through to ``stages``.

    ``ready_extra`` is merged into every ready body, which is how a worker that
    reports ``CRASHED`` also reports the ``last_error`` that killed it.
    """

    def __init__(
        self,
        *,
        stages: Sequence[str] | None = None,
        ready_answers: Sequence[int | Exception] | None = None,
        run_override: Callable[[str], dict[str, object]] | None = None,
        run_status: int = 200,
        model_key: str = _DEFAULT_MODEL_KEY,
        ready_extra: dict[str, object] | None = None,
    ) -> None:
        self.stages: list[str] = list(stages or ["READY"])
        self.ready_answers: list[int | Exception] = list(ready_answers or [200])
        self.run_override = run_override
        self.run_status = run_status
        self.model_key = model_key
        # Merged into every ``/v1/ready`` body. ``last_error`` lives here: a
        # worker that died while warming answers 200 with a terminal stage and
        # puts the reason in that field.
        self.ready_extra: dict[str, object] = dict(ready_extra or {})
        self.run_calls: list[str] = []
        self.ready_calls = 0
        self.ready_urls: list[str] = []
        self.drained = False
        self.requests: list[dict[str, object]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/ready"):
            self.ready_calls += 1
            self.ready_urls.append(str(request.url))
            answer = (
                self.ready_answers[0]
                if len(self.ready_answers) == 1
                else self.ready_answers.pop(0)
            )
            if isinstance(answer, Exception):
                raise answer
            if answer != 200:
                # What the proxy actually serves before the pod binds 8000:
                # its own error page, with a non-JSON content type.
                return httpx.Response(
                    answer,
                    content=b"<html><body>error 404 no upstream</body></html>",
                    headers={"content-type": "text/html"},
                )
            stage = self.stages[0] if len(self.stages) == 1 else self.stages.pop(0)
            return json_response(
                200,
                {
                    "stage": stage,
                    "worker_id": "w0",
                    "model_key": self.model_key,
                    **self.ready_extra,
                },
            )
        if path.endswith("/drain"):
            self.drained = True
            return json_response(200, {"stage": "DRAINING"})
        if path.endswith("/run"):
            body = json.loads(request.content)
            self.requests.append(body)
            job_id = str(body["inference_job_id"])
            self.run_calls.append(job_id)
            if self.run_override is not None:
                return json_response(self.run_status, self.run_override(job_id))
            return json_response(
                self.run_status,
                worker_response_body(job_id, model_key=self.model_key),
            )
        return httpx.Response(404)


def fake_worker_client(
    transport: httpx.BaseTransport, *, pod_id: str = "pod_fake"
) -> WorkerClient:
    return WorkerClient(worker_base_url(pod_id), bearer=BEARER, transport=transport)
