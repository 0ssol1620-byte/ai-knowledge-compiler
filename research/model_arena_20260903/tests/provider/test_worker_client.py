"""Worker client: checksum verification is the gate a bad page cannot pass."""

from __future__ import annotations

import base64
import hashlib
import json

import httpx
import pytest
from arena.constants import CAMPAIGN_ID
from arena.provider.safety import sha256_text
from arena.provider.secrets import Secret
from arena.provider.worker_client import (
    RunRequest,
    WorkerChecksumError,
    WorkerClient,
    WorkerError,
    WorkerHTTPError,
    WorkerProtocolError,
    WorkerTransportError,
    worker_base_url,
)
from tests.provider.conftest import RecordingTransport, json_response

RAW_TEXT = "# Heading\n\nA transcribed paragraph.\n"
CANONICAL = "# Heading\n\nA transcribed paragraph.\n"


def _run_response(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "inference_job_id": "a" * 64,
        "status": "SUCCESS",
        "error_class": None,
        "error_message": None,
        "worker_id": "paddleocr_vl_1_6-w0-pod_test0001",
        "model_key": "paddleocr_vl_1_6",
        "model_revision": "b" * 40,
        "runtime_mode": "baked",
        "runtime_image_digest": "sha256:" + "c" * 64,
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "pod_id": "pod_test0001",
        "started_at": "2026-09-03T10:00:00Z",
        "first_token_at": None,
        "finished_at": "2026-09-03T10:00:04Z",
        "timings_ms": {
            "load_ms": 0,
            "preprocess_ms": 120,
            "inference_ms": 3400,
            "postprocess_ms": 40,
            "total_ms": 3560,
        },
        "peak_vram_mb": 18000,
        "input_bytes": 400_000,
        "output_bytes": len(RAW_TEXT.encode("utf-8")),
        "output_chars": len(RAW_TEXT),
        "input_tokens": None,
        "output_tokens": 220,
        "raw_output": {
            "raw_text": RAW_TEXT,
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
        "raw_output_sha256": sha256_text(RAW_TEXT),
        "canonical_output_sha256": sha256_text(CANONICAL),
    }
    body.update(overrides)
    return body


def _request() -> RunRequest:
    image = b"\x89PNG\r\n\x1a\nfake page bytes"
    return RunRequest(
        campaign_id=CAMPAIGN_ID,
        inference_job_id="a" * 64,
        sample_id="omnidoc:images/PPT_1001115_eng_page_003",
        case_key="omnidocbench-58851882e7b39101a6f5756c",
        benchmark="omnidoc",
        source_sha256="sha256:" + hashlib.sha256(image).hexdigest(),
        image_bytes=image,
        width=1654,
        height=2339,
        prompt_id="paddleocr_vl_official_v1",
        prompt_sha256="sha256:" + "d" * 64,
        inference_config_sha256="sha256:" + "e" * 64,
    )


def _client(handler: object, bearer: Secret) -> WorkerClient:
    transport = RecordingTransport(handler)  # type: ignore[arg-type]
    return WorkerClient(worker_base_url("pod_test0001"), bearer=bearer, transport=transport)


def test_base_url_uses_the_runpod_proxy() -> None:
    assert worker_base_url("pod_abc") == "https://pod_abc-8000.proxy.runpod.net"


def test_run_accepts_a_matching_checksum(worker_bearer_secret: Secret) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return json_response(200, _run_response())

    client = _client(handler, worker_bearer_secret)
    response = client.run(_request())
    assert response.succeeded
    assert response.raw_text == RAW_TEXT
    body = json.loads(captured[0].content)
    assert base64.b64decode(body["image_b64"]) == _request().image_bytes
    assert captured[0].headers["Authorization"] == (f"Bearer {worker_bearer_secret.reveal()}")
    client.close()


def test_run_rejects_a_checksum_mismatch(worker_bearer_secret: Secret) -> None:
    """A worker that mis-states its output hash is never accepted."""

    tampered = _run_response(raw_output_sha256="sha256:" + "0" * 64)
    client = _client(lambda _: json_response(200, tampered), worker_bearer_secret)
    with pytest.raises(WorkerChecksumError) as caught:
        client.run(_request())
    assert WorkerChecksumError.error_class == "CHECKSUM"
    assert "mismatch" in str(caught.value)
    client.close()


def test_run_rejects_output_whose_text_was_altered(worker_bearer_secret: Secret) -> None:
    body = _run_response()
    raw = dict(body["raw_output"])  # type: ignore[call-overload]
    raw["raw_text"] = RAW_TEXT + "an extra sentence the hash does not cover"
    body["raw_output"] = raw
    client = _client(lambda _: json_response(200, body), worker_bearer_secret)
    with pytest.raises(WorkerChecksumError):
        client.run(_request())
    client.close()


def test_run_rejects_an_answer_for_a_different_job(worker_bearer_secret: Secret) -> None:
    body = _run_response(inference_job_id="f" * 64)
    client = _client(lambda _: json_response(200, body), worker_bearer_secret)
    with pytest.raises(WorkerProtocolError, match="different inference_job_id"):
        client.run(_request())
    client.close()


def test_failed_response_must_carry_an_error_class(worker_bearer_secret: Secret) -> None:
    body = _run_response(status="FAILED", error_class=None)
    client = _client(lambda _: json_response(200, body), worker_bearer_secret)
    with pytest.raises(WorkerProtocolError, match="must carry an error_class"):
        client.run(_request())
    client.close()


def test_error_class_outside_the_taxonomy_is_refused(worker_bearer_secret: Secret) -> None:
    body = _run_response(status="FAILED", error_class="SOMETHING_INVENTED")
    client = _client(lambda _: json_response(200, body), worker_bearer_secret)
    with pytest.raises(WorkerProtocolError, match="not in the taxonomy"):
        client.run(_request())
    client.close()


def test_failed_response_is_returned_without_a_checksum_check(
    worker_bearer_secret: Secret,
) -> None:
    body = _run_response(
        status="FAILED",
        error_class="CUDA_OOM",
        error_message="out of memory",
        raw_output_sha256="sha256:" + "0" * 64,
    )
    client = _client(lambda _: json_response(200, body), worker_bearer_secret)
    response = client.run(_request())
    assert not response.succeeded
    assert response.error_class == "CUDA_OOM"
    client.close()


def test_unauthorized_is_reported_without_the_bearer(worker_bearer_secret: Secret) -> None:
    client = _client(lambda _: httpx.Response(401), worker_bearer_secret)
    with pytest.raises(WorkerError) as caught:
        client.run(_request())
    assert worker_bearer_secret.reveal() not in str(caught.value)
    client.close()


def test_drain_conflict_is_reported(worker_bearer_secret: Secret) -> None:
    client = _client(lambda _: httpx.Response(409), worker_bearer_secret)
    with pytest.raises(WorkerError, match="draining"):
        client.run(_request())
    client.close()


def test_ready_rejects_an_unknown_stage(worker_bearer_secret: Secret) -> None:
    client = _client(lambda _: json_response(200, {"stage": "MOSTLY_READY"}), worker_bearer_secret)
    with pytest.raises(WorkerProtocolError, match="unknown stage"):
        client.ready()
    client.close()


def test_ready_accepts_a_contract_stage(worker_bearer_secret: Secret) -> None:
    payload = {"stage": "READY", "worker_id": "w", "model_key": "paddleocr_vl_1_6"}
    client = _client(lambda _: json_response(200, payload), worker_bearer_secret)
    assert client.ready()["stage"] == "READY"
    client.close()


def test_result_returns_none_for_an_unknown_job(worker_bearer_secret: Secret) -> None:
    client = _client(lambda _: httpx.Response(404), worker_bearer_secret)
    assert client.result("a" * 64) is None
    client.close()


def test_drain_must_move_the_worker_to_draining(worker_bearer_secret: Secret) -> None:
    client = _client(lambda _: json_response(200, {"stage": "READY"}), worker_bearer_secret)
    with pytest.raises(WorkerProtocolError, match="DRAINING"):
        client.drain()
    client.close()


def test_run_request_refuses_an_empty_page() -> None:
    with pytest.raises(WorkerError, match="page image bytes"):
        RunRequest(
            campaign_id=CAMPAIGN_ID,
            inference_job_id="a" * 64,
            sample_id="s",
            case_key="c",
            benchmark="omnidoc",
            source_sha256="sha256:" + "0" * 64,
            image_bytes=b"",
            width=1,
            height=1,
            prompt_id="p",
            prompt_sha256="sha256:" + "0" * 64,
            inference_config_sha256="sha256:" + "0" * 64,
        )


# ------------------------------------------------- readiness classification


def test_ready_asks_for_v1_ready_on_the_pod_proxy(worker_bearer_secret: Secret) -> None:
    """The path the driver polls is ``/v1/ready``, and the message says so.

    The first live run logged ``worker returned HTTP 404 for GET /ready``,
    which left it unclear whether the client had dropped the ``/v1`` prefix.
    It had not -- but a receipt that cannot answer that question is a receipt
    that costs an hour, so the URL is now printed whole.
    """

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(404, content=b"<html>no upstream yet</html>")

    client = _client(handler, worker_bearer_secret)
    with pytest.raises(WorkerHTTPError) as caught:
        client.ready()
    client.close()

    assert str(seen[0].url) == "https://pod_test0001-8000.proxy.runpod.net/v1/ready"
    assert seen[0].url.path == "/v1/ready"
    assert "https://pod_test0001-8000.proxy.runpod.net/v1/ready" in str(caught.value)


@pytest.mark.parametrize("status", [404, 500, 502, 503, 504])
def test_a_proxy_status_is_carried_as_a_number_not_only_a_sentence(
    worker_bearer_secret: Secret, status: int
) -> None:
    """The poll needs the code itself to tell 404-yet from 401-never apart."""

    client = _client(lambda _: httpx.Response(status), worker_bearer_secret)
    with pytest.raises(WorkerHTTPError) as caught:
        client.ready()
    client.close()
    assert caught.value.status_code == status
    assert isinstance(caught.value, WorkerError)


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_bearer_is_its_own_status_and_never_echoes_the_token(
    worker_bearer_secret: Secret, status: int
) -> None:
    client = _client(lambda _: httpx.Response(status), worker_bearer_secret)
    with pytest.raises(WorkerHTTPError) as caught:
        client.ready()
    client.close()
    assert caught.value.status_code == status
    assert worker_bearer_secret.reveal() not in str(caught.value)


def test_a_connection_that_never_lands_is_a_transport_failure(
    worker_bearer_secret: Secret,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no listener on 8000 yet")

    client = _client(handler, worker_bearer_secret)
    with pytest.raises(WorkerTransportError, match="ConnectError"):
        client.ready()
    client.close()


# ------------------------------------------------- a refusal names its check
#
# Pod 27f6f6dif3jcp6 answered 422 to all 13 pages of the 2026-09-03 GLM-OCR
# canary and every page record said the same thing: "worker returned HTTP 422
# ...; body withheld", error_class INFRA_NETWORK. Which of the worker's five
# checks had failed, and with what values, could not be recovered from the
# receipts -- only from a second rented pod.


@pytest.mark.parametrize(
    ("code", "expected_class"),
    [
        ("CONFIG_MISMATCH", "UNKNOWN"),
        ("PROMPT_MISMATCH", "UNKNOWN"),
        ("CAMPAIGN_MISMATCH", "UNKNOWN"),
        ("INVALID_REQUEST", "UNKNOWN"),
    ],
)
def test_a_422_rejection_carries_its_code_and_a_section_16_class(
    worker_bearer_secret: Secret, code: str, expected_class: str
) -> None:
    detail = "worker inference_config_sha256 sha256:" + "2" * 64 + " != request sha256:" + "f" * 64
    client = _client(
        lambda _: json_response(422, {"error": code, "detail": detail}), worker_bearer_secret
    )
    with pytest.raises(WorkerHTTPError) as caught:
        client.run(_request())
    client.close()

    assert caught.value.status_code == 422
    assert caught.value.worker_error_code == code
    assert caught.value.error_class == expected_class
    assert code in str(caught.value)
    assert detail in str(caught.value)


def test_a_422_run_response_keeps_the_error_class_the_worker_declared(
    worker_bearer_secret: Secret,
) -> None:
    """INPUT_DECODE and CHECKSUM come back as a full RunResponse, not a rejection."""

    body = _run_response(
        status="FAILED",
        error_class="CHECKSUM",
        error_message="decoded image hashes to sha256:" + "1" * 64,
    )
    client = _client(lambda _: json_response(422, body), worker_bearer_secret)
    with pytest.raises(WorkerHTTPError) as caught:
        client.run(_request())
    client.close()

    assert caught.value.error_class == "CHECKSUM"
    assert caught.value.worker_error_code == "CHECKSUM"


def test_an_unknown_rejection_code_is_surfaced_but_not_classified(
    worker_bearer_secret: Secret,
) -> None:
    """``retry.rule_for`` refuses a class outside the taxonomy; do not invent one."""

    client = _client(
        lambda _: json_response(422, {"error": "SOMETHING_NEW", "detail": "?"}),
        worker_bearer_secret,
    )
    with pytest.raises(WorkerHTTPError) as caught:
        client.run(_request())
    client.close()

    assert caught.value.worker_error_code == "SOMETHING_NEW"
    assert caught.value.error_class is None


def test_a_rejection_detail_is_scrubbed_and_capped(worker_bearer_secret: Secret) -> None:
    """A body is not a receipt: no credential, no unbounded text."""

    detail = "adapter said Authorization: Bearer " + "Z" * 60 + " while loading " + "x" * 2000
    client = _client(
        lambda _: json_response(422, {"error": "INVALID_REQUEST", "detail": detail}),
        worker_bearer_secret,
    )
    with pytest.raises(WorkerHTTPError) as caught:
        client.run(_request())
    client.close()

    message = str(caught.value)
    assert "Z" * 60 not in message
    assert "[REDACTED]" in message
    assert len(message) < 700


def test_a_body_that_is_not_json_still_withholds_it(worker_bearer_secret: Secret) -> None:
    client = _client(
        lambda _: httpx.Response(422, content=b"<html>nginx</html>"), worker_bearer_secret
    )
    with pytest.raises(WorkerHTTPError) as caught:
        client.run(_request())
    client.close()

    assert caught.value.worker_error_code is None
    assert caught.value.error_class is None
    assert "body withheld" in str(caught.value)
    assert "nginx" not in str(caught.value)
