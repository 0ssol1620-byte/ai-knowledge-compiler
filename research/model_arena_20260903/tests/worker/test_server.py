"""End-to-end tests for the on-pod worker HTTP server (ARENA_CONTRACT section 4)."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from arena.constants import CAMPAIGN_ID, ERROR_CLASSES
from arena.worker.canonical_default import PASSTHROUGH_NOTE
from arena.worker.server import CONTRACT_RESULT_KEYS
from arena.worker.util import sha256_label
from harness import (
    FAILING_CANONICAL_SOURCE,
    IMAGE_DIGEST,
    MODEL_KEY,
    MODEL_REVISION,
    UPPERCASE_CANONICAL_SOURCE,
    worker,
)

pytestmark = pytest.mark.filterwarnings("ignore::ResourceWarning")


# --------------------------------------------------------------------------
# Readiness (masterplan 15.3, 34)
# --------------------------------------------------------------------------


def test_readiness_reaches_ready_with_both_receipts(tmp_path: Path) -> None:
    with worker(tmp_path, prompt_text="Transcribe this page.\n") as handle:
        status, body = handle.get("/v1/ready")
        assert status == 200
        assert body["stage"] == "READY"
        assert body["worker_id"] == f"{MODEL_KEY}-w0-test"
        assert body["model_key"] == MODEL_KEY
        assert body["model_revision"] == MODEL_REVISION
        assert body["runtime_mode"] == "baked"
        assert body["runtime_image_digest"] == IMAGE_DIGEST
        assert body["last_error"] is None
        assert body["started_at"] and body["ready_at"]
        assert body["load_receipt"]["model_revision"] == MODEL_REVISION
        assert body["load_receipt"]["cache_hit"] is False
        assert body["warmup_receipt"]["schema_valid"] is True
        assert body["schema"] == "tavonel.arena.ready-response.v1"

        info = json.loads((handle.state_dir / "worker-info.json").read_text(encoding="utf-8"))
        assert info["prompt_sha256"] == handle.prompt_sha256
        assert info["canonicalizer"] == "arena.worker.canonical_default"
        assert info["max_concurrency_per_worker"] == 2
        assert handle.token not in json.dumps(info)


def test_load_failure_leaves_the_process_up_in_crashed(tmp_path: Path) -> None:
    descriptor = {"inference_config": {"fake_load_error": "MODEL_LOAD"}}
    with worker(tmp_path, descriptor_overrides=descriptor) as handle:
        status, body = handle.get("/v1/ready")
        assert status == 200
        assert body["stage"] == "CRASHED"
        assert "MODEL_LOAD" in body["last_error"]
        assert body["ready_at"] is None
        # The controller can still reach every diagnostic endpoint.
        assert handle.get("/v1/heartbeat")[0] == 200
        run_status, run_body = handle.post("/v1/run", handle.run_payload())
        assert run_status == 409
        assert run_body["error"] == "NOT_ACCEPTING"
        assert run_body["stage"] == "CRASHED"


def test_revision_mismatch_between_adapter_and_runtime_json_crashes(tmp_path: Path) -> None:
    descriptor = {"inference_config": {"fake_load_revision": "f" * 40}}
    with worker(tmp_path, descriptor_overrides=descriptor) as handle:
        body = handle.wait_for_stage(("CRASHED",))
        assert "runtime.json" in body["last_error"]


def test_warmup_schema_failure_crashes(tmp_path: Path) -> None:
    descriptor = {"inference_config": {"fake_warmup_invalid": True}}
    with worker(tmp_path, descriptor_overrides=descriptor) as handle:
        body = handle.wait_for_stage(("CRASHED",))
        assert "schema check" in body["last_error"]


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


def test_wrong_and_missing_tokens_are_401(tmp_path: Path) -> None:
    wrong = "not-" + "the-credential"
    empty = ""
    with worker(tmp_path) as handle:
        assert handle.get("/v1/ready", token=wrong)[0] == 401
        assert handle.get("/v1/ready", send_auth=False)[0] == 401
        assert handle.post("/v1/run", handle.run_payload(), token=empty)[0] == 401
        assert handle.post("/v1/drain", token=wrong)[0] == 401
        # A rejected request must not leak the expected credential anywhere.
        _, body = handle.get("/v1/ready", token=wrong)
        assert handle.token not in json.dumps(body)


def test_unknown_paths_are_404(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        assert handle.get("/v1/nope")[0] == 404
        assert handle.post("/v1/nope", {})[0] == 404


# --------------------------------------------------------------------------
# /v1/run happy path and idempotent replay
# --------------------------------------------------------------------------


def test_run_happy_path_persists_before_responding(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        payload = handle.run_payload()
        status, body = handle.post("/v1/run", payload)
        assert status == 200, body

        missing = [key for key in CONTRACT_RESULT_KEYS if key not in body]
        assert missing == []
        assert body["status"] == "SUCCESS"
        assert body["error_class"] is None
        assert body["error_message"] is None
        assert body["inference_job_id"] == payload["inference_job_id"]
        assert body["model_key"] == MODEL_KEY
        assert body["runtime_mode"] == "baked"
        assert body["runtime_image_digest"] == IMAGE_DIGEST
        assert body["gpu_type"] == "NVIDIA L40S"
        assert body["pod_id"] == "pod-test"
        assert body["input_bytes"] == len(base64.b64decode(payload["image_b64"]))

        raw_text = body["raw_output"]["raw_text"]
        assert body["output_chars"] == len(raw_text)
        assert body["output_bytes"] == len(raw_text.encode("utf-8"))
        assert body["raw_output_sha256"] == sha256_label(raw_text.encode("utf-8"))
        assert body["canonical"]["markdown"] == raw_text
        assert body["canonical"]["lossy"] is False
        assert body["canonical"]["conversion_notes"] == [PASSTHROUGH_NOTE]
        assert body["canonical_output_sha256"] == sha256_label(raw_text.encode("utf-8"))
        assert body["timings_ms"]["total_ms"] >= 0
        assert body["timings_ms"]["load_ms"] == 7
        assert body["input_tokens"] == 11

        # The page image landed under the state dir, byte-identical.
        image_path = handle.state_dir / "inputs" / f"{payload['case_key']}.png"
        assert image_path.is_file()
        assert sha256_label(image_path.read_bytes()) == payload["source_sha256"]

        # The result is durable and identical to what was returned.
        result_path = handle.state_dir / "results" / f"{payload['inference_job_id']}.json"
        assert result_path.is_file()
        assert json.loads(result_path.read_text(encoding="utf-8")) == body

        fetched_status, fetched = handle.get(f"/v1/result/{payload['inference_job_id']}")
        assert fetched_status == 200
        assert fetched == body


def test_repeated_job_id_replays_without_new_inference(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        payload = handle.run_payload()
        first_status, first = handle.post("/v1/run", payload)
        assert first_status == 200

        # Same job id, but the adapter is now told to emit something else and
        # to fail. A re-run would be visible; a replay cannot be.
        replay = dict(payload)
        replay["metadata"] = {
            "page_index": 0,
            "media_type": "pdf",
            "fake": {"text": "SHOULD NEVER APPEAR", "error_class": "CUDA_OOM"},
        }
        second_status, second = handle.post("/v1/run", replay)
        assert second_status == 200
        assert second == first
        assert "SHOULD NEVER APPEAR" not in json.dumps(second)


def test_result_endpoint_404_for_unknown_job(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        status, body = handle.get("/v1/result/" + "0" * 64)
        assert status == 404
        assert body["error"] == "NOT_FOUND"


def test_result_endpoint_422_for_malformed_job_id(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        status, body = handle.get("/v1/result/not-a-job-id")
        assert status == 422
        assert body["error"] == "INVALID_REQUEST"


# --------------------------------------------------------------------------
# Request-level integrity failures (nothing is persisted)
# --------------------------------------------------------------------------


def test_bad_checksum_is_422_failed_and_is_not_persisted(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        payload = handle.run_payload(source_sha256="sha256:" + "e" * 64)
        status, body = handle.post("/v1/run", payload)
        assert status == 422
        assert body["status"] == "FAILED"
        assert body["error_class"] == "CHECKSUM"
        assert "sha256:" + "e" * 64 in body["error_message"]
        assert body["raw_output"] is None
        assert body["canonical"] is None
        assert body["raw_output_sha256"] is None
        assert body["output_bytes"] == 0
        assert body["output_chars"] == 0
        assert body["timings_ms"]["inference_ms"] == 0
        result_path = handle.state_dir / "results" / f"{payload['inference_job_id']}.json"
        assert not result_path.exists()
        assert handle.get(f"/v1/result/{payload['inference_job_id']}")[0] == 404


def test_undecodable_image_is_input_decode(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        payload = handle.run_payload(image_b64="!!!! not base64 !!!!")
        status, body = handle.post("/v1/run", payload)
        assert status == 422
        assert body["error_class"] == "INPUT_DECODE"


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"inference_job_id": "short"}, "INVALID_REQUEST"),
        ({"case_key": "../escape"}, "INVALID_REQUEST"),
        ({"benchmark": "not-a-benchmark"}, "INVALID_REQUEST"),
        ({"job_kind": "sneaky"}, "INVALID_REQUEST"),
        ({"width": 0}, "INVALID_REQUEST"),
        ({"source_sha256": "md5:abc"}, "INVALID_REQUEST"),
        ({"timeout_seconds": -1}, "INVALID_REQUEST"),
        ({"campaign_id": "SOME-OTHER-CAMPAIGN"}, "CAMPAIGN_MISMATCH"),
        ({"inference_config_sha256": "sha256:" + "9" * 64}, "CONFIG_MISMATCH"),
    ],
)
def test_malformed_requests_are_422(
    tmp_path: Path, override: dict[str, Any], expected: str
) -> None:
    with worker(tmp_path) as handle:
        status, body = handle.post("/v1/run", handle.run_payload(**override))
        assert status == 422, body
        assert body["error"] == expected


def test_prompt_hash_mismatch_is_refused(tmp_path: Path) -> None:
    with worker(tmp_path, prompt_text="the campaign prompt\n") as handle:
        payload = handle.run_payload(prompt_sha256="sha256:" + "1" * 64)
        status, body = handle.post("/v1/run", payload)
        assert status == 422
        assert body["error"] == "PROMPT_MISMATCH"


def test_non_json_body_is_422(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        import http.client

        connection = http.client.HTTPConnection(handle.host, handle.port, timeout=30)
        try:
            connection.request(
                "POST",
                "/v1/run",
                body=b"{not json",
                headers={
                    "Authorization": f"Bearer {handle.token}",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            assert response.status == 422
            assert json.loads(response.read())["error"] == "INVALID_REQUEST"
        finally:
            connection.close()


# --------------------------------------------------------------------------
# Adapter failures (a real result, persisted)
# --------------------------------------------------------------------------


def test_adapter_error_maps_to_its_error_class(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        payload = handle.run_payload(
            metadata={"page_index": 0, "media_type": "pdf", "fake": {"error_class": "CUDA_OOM"}}
        )
        status, body = handle.post("/v1/run", payload)
        assert status == 200
        assert body["status"] == "FAILED"
        assert body["error_class"] == "CUDA_OOM"
        assert body["error_class"] in ERROR_CLASSES
        assert body["raw_output"] is None
        assert body["canonical_output_sha256"] is None
        # A real inference outcome IS checkpointed.
        assert (handle.state_dir / "results" / f"{payload['inference_job_id']}.json").is_file()
        assert handle.get(f"/v1/result/{payload['inference_job_id']}")[1] == body


def test_unknown_adapter_error_class_falls_back_to_unknown(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        payload = handle.run_payload(
            metadata={"page_index": 0, "media_type": "pdf", "fake": {"error_class": "MADE_UP"}}
        )
        status, body = handle.post("/v1/run", payload)
        assert status == 200
        assert body["error_class"] == "UNKNOWN"
        assert "MADE_UP" in body["error_message"]


def test_plain_exception_maps_to_unknown(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        payload = handle.run_payload(
            metadata={
                "page_index": 0,
                "media_type": "pdf",
                "fake": {"raise_plain_exception": True},
            }
        )
        status, body = handle.post("/v1/run", payload)
        assert status == 200
        assert body["status"] == "FAILED"
        assert body["error_class"] == "UNKNOWN"
        assert "ValueError" in body["error_message"]


def test_error_messages_are_redacted(tmp_path: Path) -> None:
    leaked = "rpa_" + "Z" * 32
    with worker(tmp_path) as handle:
        payload = handle.run_payload(
            metadata={
                "page_index": 0,
                "media_type": "pdf",
                "fake": {"error_class": "AUTH", "error_message": f"denied with {leaked}"},
            }
        )
        status, body = handle.post("/v1/run", payload)
        assert status == 200
        assert leaked not in json.dumps(body)
        assert "[REDACTED]" in body["error_message"]


def test_canonicalizer_failure_is_postprocess(tmp_path: Path) -> None:
    with worker(tmp_path, canonical_source=FAILING_CANONICAL_SOURCE) as handle:
        status, body = handle.post("/v1/run", handle.run_payload())
        assert status == 200
        assert body["status"] == "FAILED"
        assert body["error_class"] == "POSTPROCESS"
        assert body["raw_output"] is not None
        assert body["canonical"] is None


def test_runtime_canonicalizer_is_preferred_over_the_default(tmp_path: Path) -> None:
    with worker(tmp_path, canonical_source=UPPERCASE_CANONICAL_SOURCE) as handle:
        info = json.loads((handle.state_dir / "worker-info.json").read_text(encoding="utf-8"))
        assert info["canonicalizer"].endswith("canonical.py")
        status, body = handle.post("/v1/run", handle.run_payload())
        assert status == 200
        raw_text = body["raw_output"]["raw_text"]
        assert body["canonical"]["markdown"] == raw_text.upper()
        assert body["canonical"]["lossy"] is True
        assert body["canonical_output_sha256"] == sha256_label(raw_text.upper().encode("utf-8"))


# --------------------------------------------------------------------------
# Timeout, stall and drain
# --------------------------------------------------------------------------


def test_timeout_stalls_the_worker_and_then_409(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        payload = handle.run_payload(
            timeout_seconds=1,
            metadata={"page_index": 0, "media_type": "pdf", "fake": {"delay_seconds": 30}},
        )
        status, body = handle.post("/v1/run", payload)
        assert status == 200
        assert body["status"] == "FAILED"
        assert body["error_class"] == "INFERENCE_TIMEOUT"
        assert "per-page timeout" in body["error_message"]
        assert (handle.state_dir / "results" / f"{payload['inference_job_id']}.json").is_file()

        assert handle.get("/v1/ready")[1]["stage"] == "STALLED"
        next_status, next_body = handle.post("/v1/run", handle.run_payload())
        assert next_status == 409
        assert next_body["stage"] == "STALLED"

        # A page already answered is still replayable from a stalled worker.
        assert handle.post("/v1/run", payload)[0] == 200


def test_drain_refuses_new_work(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        status, body = handle.post("/v1/drain")
        assert status == 200
        assert body["stage"] == "DRAINING"
        assert handle.get("/v1/ready")[1]["stage"] == "DRAINING"
        run_status, run_body = handle.post("/v1/run", handle.run_payload())
        assert run_status == 409
        assert run_body["stage"] == "DRAINING"


def test_concurrency_is_capped_by_runtime_json(tmp_path: Path) -> None:
    descriptor = {"max_concurrency_per_worker": 1}
    with worker(tmp_path, descriptor_overrides=descriptor) as handle:
        info = json.loads((handle.state_dir / "worker-info.json").read_text(encoding="utf-8"))
        assert info["max_concurrency_per_worker"] == 1
        results: list[tuple[int, Any]] = []
        lock = threading.Lock()

        def fire() -> None:
            payload = handle.run_payload(
                metadata={
                    "page_index": 0,
                    "media_type": "pdf",
                    "fake": {"delay_seconds": 0.35},
                }
            )
            outcome = handle.post("/v1/run", payload)
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=fire) for _ in range(2)]
        started = time.perf_counter()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        elapsed = time.perf_counter() - started

        assert [status for status, _ in results] == [200, 200]
        assert all(body["status"] == "SUCCESS" for _, body in results)
        # Serialised: two 0.35s pages cannot both finish inside one slot.
        assert elapsed >= 0.6


# --------------------------------------------------------------------------
# Heartbeat and provenance
# --------------------------------------------------------------------------


def test_heartbeat_carries_the_masterplan_fields(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        handle.post("/v1/run", handle.run_payload())
        status, body = handle.get("/v1/heartbeat")
        assert status == 200
        for key in (
            "worker_id",
            "state",
            "stage",
            "job_id",
            "last_progress_at",
            "gpu_util",
            "vram_used",
            "output_progress",
            "jobs_done",
            "jobs_failed",
            "pid",
        ):
            assert key in body, key
        assert body["stage"] == "READY"
        assert body["state"] == "READY"
        assert body["job_id"] is None
        assert body["jobs_done"] == 1
        assert body["jobs_failed"] == 0
        assert body["output_progress"] > 0
        if body["gpu_util"] is None:
            assert body["gpu_metrics_unavailable_reason"]

        on_disk = json.loads((handle.state_dir / "heartbeat.json").read_text(encoding="utf-8"))
        assert on_disk["worker_id"] == body["worker_id"]


def test_provenance_reports_masterplan_38_fields(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        status, body = handle.get("/v1/provenance")
        assert status == 200
        for key in (
            "python",
            "os",
            "versions",
            "cuda",
            "driver",
            "pip_freeze_text",
            "pip_freeze_sha256",
            "pip_freeze_source",
            "apt_snapshot_sha256",
            "image_digest",
            "adapter",
            "unavailable",
        ):
            assert key in body, key
        assert body["image_digest"] == IMAGE_DIGEST
        assert body["pip_freeze_sha256"].startswith("sha256:")
        assert body["pip_freeze_text"].strip()
        assert body["adapter"]["backend"] == "fake"
        assert body["versions"]["pillow"] is not None
        # Nothing is silently zeroed: every absent fact carries a reason.
        for name, value in (
            ("apt_snapshot_sha256", body["apt_snapshot_sha256"]),
            ("nvidia_smi", body["driver"]["nvidia_smi_driver_version"]),
        ):
            if value is None:
                assert body["unavailable"], name


def test_worker_environment_never_serializes_the_token(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        public = json.dumps(handle.core.env.public())
        assert handle.token not in public
        assert "token" not in public
        for path in ("/v1/ready", "/v1/heartbeat", "/v1/provenance"):
            assert handle.token not in json.dumps(handle.get(path)[1])


def test_campaign_id_default_matches_constants(tmp_path: Path) -> None:
    with worker(tmp_path, env_overrides={"ARENA_CAMPAIGN_ID": ""}) as handle:
        info = json.loads((handle.state_dir / "worker-info.json").read_text(encoding="utf-8"))
        assert info["campaign_id"] == CAMPAIGN_ID
        # A request carrying the constant is accepted; anything else is not.
        assert handle.post("/v1/run", handle.run_payload())[0] == 200
        status, body = handle.post("/v1/run", handle.run_payload(campaign_id="OTHER"))
        assert (status, body["error"]) == (422, "CAMPAIGN_MISMATCH")


def test_case_key_cannot_escape_the_inputs_directory(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        for hostile in ("../../etc/passwd", "a/b", "C:\\Windows\\x", ""):
            status, _ = handle.post("/v1/run", handle.run_payload(case_key=hostile))
            assert status == 422, hostile
        assert list((handle.state_dir / "inputs").glob("*")) == []


def test_job_id_is_the_only_result_filename(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        payload = handle.run_payload()
        handle.post("/v1/run", payload)
        names = sorted(path.name for path in (handle.state_dir / "results").glob("*.json"))
        assert names == [f"{payload['inference_job_id']}.json"]
        assert hashlib.sha256().hexdigest() != payload["inference_job_id"]
