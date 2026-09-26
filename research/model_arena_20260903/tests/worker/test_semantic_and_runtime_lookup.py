"""Decision D3 (semantic error class), D4 (heartbeat) and 11.3(5) (runtime lookup).

The three things a controller cannot recover from if the worker gets them
wrong: a semantic verdict it invented, a heartbeat metric it faked, and a
runtime directory it found somewhere other than ``ARENA_RUNTIME_DIR``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arena.constants import WORKER_STATES
from arena.worker.adapter_api import RawOutput
from arena.worker.config import WorkerConfigError, load_runtime_config, require_runtime_dir
from arena.worker.heartbeat import HeartbeatWriter, gpu_metrics
from arena.worker.loader import load_adapter, load_canonicalizer
from arena.worker.server import (
    SEMANTIC_ERROR_CLASSES,
    SEMANTIC_WARNING_PREFIX,
    resolve_semantic_error_class,
)
from harness import MODEL_KEY, MODEL_REVISION, worker


def _raw(**overrides: Any) -> RawOutput:
    payload: dict[str, Any] = {
        "raw_text": "# page\n",
        "output_format": "markdown",
        "native_json": None,
        "usage": {},
        "timings_ms": {"preprocess_ms": 1, "inference_ms": 1, "postprocess_ms": 1},
    }
    payload.update(overrides)
    return RawOutput(**payload)


# -- D3 resolution --------------------------------------------------------


@pytest.mark.parametrize("value", list(SEMANTIC_ERROR_CLASSES))
def test_adapter_field_wins(value: str) -> None:
    assert resolve_semantic_error_class(_raw(semantic_error_class=value)) == (value, ())


@pytest.mark.parametrize("value", list(SEMANTIC_ERROR_CLASSES))
def test_warning_prefix_is_parsed(value: str) -> None:
    raw = _raw(warnings=("something else", f"{SEMANTIC_WARNING_PREFIX}{value}"))
    assert resolve_semantic_error_class(raw) == (value, ())


def test_field_beats_the_warning() -> None:
    raw = _raw(
        semantic_error_class="OUTPUT_EMPTY",
        warnings=(f"{SEMANTIC_WARNING_PREFIX}OUTPUT_TRUNCATED",),
    )
    assert resolve_semantic_error_class(raw)[0] == "OUTPUT_EMPTY"


def test_absent_everywhere_is_none() -> None:
    assert resolve_semantic_error_class(_raw(warnings=("plain warning",))) == (None, ())
    assert resolve_semantic_error_class(None) == (None, ())


def test_a_warning_that_only_mentions_the_prefix_is_not_a_verdict() -> None:
    raw = _raw(warnings=(f"see {SEMANTIC_WARNING_PREFIX}OUTPUT_EMPTY for details",))
    assert resolve_semantic_error_class(raw) == (None, ())


@pytest.mark.parametrize(
    "bad", ["CUDA_OOM", "output_empty", "", "OUTPUT_EMPTY;DROP", "UNKNOWN"]
)
def test_a_bad_field_value_is_dropped_with_a_warning(bad: str) -> None:
    value, warnings = resolve_semantic_error_class(_raw(semantic_error_class=bad))
    assert value is None
    assert len(warnings) == 1
    assert "not one of" in warnings[0]


@pytest.mark.parametrize("bad", ["CUDA_OOM", "output_empty", "", "SOMETHING_ELSE"])
def test_a_bad_warning_value_is_dropped_with_a_warning(bad: str) -> None:
    value, warnings = resolve_semantic_error_class(
        _raw(warnings=(f"{SEMANTIC_WARNING_PREFIX}{bad}",))
    )
    assert value is None
    assert len(warnings) == 1
    assert "not one of" in warnings[0]


# -- D3 over the wire and in the persisted result --------------------------


def test_run_response_and_persisted_result_carry_the_field(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        payload = handle.run_payload(
            metadata={"page_index": 0, "fake": {"semantic_error_class": "OUTPUT_TRUNCATED"}}
        )
        status, body = handle.post("/v1/run", payload)
        assert status == 200
        # MP section 41: a semantic verdict does not make the page a failure.
        assert body["status"] == "SUCCESS"
        assert body["semantic_error_class"] == "OUTPUT_TRUNCATED"

        persisted = json.loads(
            (handle.state_dir / "results" / f"{payload['inference_job_id']}.json").read_text(
                encoding="utf-8"
            )
        )
        assert persisted["semantic_error_class"] == "OUTPUT_TRUNCATED"

        replayed = handle.get(f"/v1/result/{payload['inference_job_id']}")[1]
        assert replayed["semantic_error_class"] == "OUTPUT_TRUNCATED"


def test_run_response_parses_the_warning_convention(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        body = handle.post(
            "/v1/run",
            handle.run_payload(
                metadata={
                    "page_index": 0,
                    "fake": {"warnings": [f"{SEMANTIC_WARNING_PREFIX}OUTPUT_REPETITION"]},
                }
            ),
        )[1]
        assert body["semantic_error_class"] == "OUTPUT_REPETITION"
        assert body["raw_output"]["warnings"] == [
            f"{SEMANTIC_WARNING_PREFIX}OUTPUT_REPETITION"
        ]


def test_an_invalid_value_becomes_null_plus_a_warning_on_the_wire(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        body = handle.post(
            "/v1/run",
            handle.run_payload(
                metadata={"page_index": 0, "fake": {"semantic_error_class": "NOT_A_CLASS"}}
            ),
        )[1]
        assert body["semantic_error_class"] is None
        assert any("NOT_A_CLASS" in warning for warning in body["raw_output"]["warnings"])


def test_a_normal_page_reports_null(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        body = handle.post("/v1/run", handle.run_payload())[1]
        assert body["semantic_error_class"] is None


def test_a_failed_page_reports_null(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        body = handle.post(
            "/v1/run",
            handle.run_payload(metadata={"page_index": 0, "fake": {"error_class": "CUDA_OOM"}}),
        )[1]
        assert body["status"] == "FAILED"
        assert body["semantic_error_class"] is None


# -- D4 heartbeat ---------------------------------------------------------


def test_heartbeat_reports_ts_and_a_worker_state(tmp_path: Path) -> None:
    with worker(tmp_path) as handle:
        body = handle.get("/v1/heartbeat")[1]
        assert body["state"] in WORKER_STATES
        assert body["state"] == body["stage"]
        assert body["ts"].endswith("Z")


def test_missing_gpu_metrics_are_null_with_a_reason(tmp_path: Path) -> None:
    """Never 0 as a stand-in: 0% utilisation is a real, different measurement."""
    writer = HeartbeatWriter(
        tmp_path / "heartbeat.json",
        lambda: {"stage": "READY", "state": "READY"},
        gpu_reader=lambda: {
            "gpu_util": None,
            "vram_used": None,
            "gpu_metrics_unavailable_reason": "nvidia-smi not found on PATH",
        },
    )
    payload = writer.write_once()
    assert payload["gpu_util"] is None
    assert payload["vram_used"] is None
    assert payload["gpu_metrics_unavailable_reason"]
    assert json.loads((tmp_path / "heartbeat.json").read_text(encoding="utf-8")) == payload


def test_gpu_metrics_on_a_box_without_nvidia_smi_never_invents_a_number() -> None:
    metrics = gpu_metrics()
    if metrics.get("gpu_util") is None:
        assert metrics["vram_used"] is None
        assert metrics["gpu_metrics_unavailable_reason"]
    else:  # pragma: no cover - only on a GPU host
        assert "gpu_metrics_unavailable_reason" not in metrics


# -- 11.3(5) runtime lookup ------------------------------------------------


def _env(runtime_dir: Path, state_dir: Path) -> dict[str, str]:
    return {
        "ARENA_WORKER_TOKEN": "t",
        "ARENA_MODEL_KEY": MODEL_KEY,
        "ARENA_MODEL_REVISION": MODEL_REVISION,
        "ARENA_RUNTIME_MODE": "bootstrap",
        "ARENA_IMAGE_DIGEST": "bootstrap:sha256:" + "b" * 64,
        "ARENA_RUNTIME_DIR": str(runtime_dir),
        "ARENA_STATE_DIR": str(state_dir),
    }


def test_require_runtime_dir_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(WorkerConfigError, match="runtime directory not found"):
        require_runtime_dir(tmp_path / "absent")

    file_not_dir = tmp_path / "runtime"
    file_not_dir.write_text("not a directory", encoding="utf-8")
    with pytest.raises(WorkerConfigError, match="not a directory"):
        require_runtime_dir(file_not_dir)


def test_every_runtime_artefact_is_looked_up_only_under_arena_runtime_dir(
    tmp_path: Path,
) -> None:
    from arena.worker.config import WorkerEnv

    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "state"
    runtime_dir.mkdir()
    env = WorkerEnv.from_env(_env(runtime_dir, state_dir))

    # A descriptor next to the process, in the state dir and in the parent of
    # the runtime dir must not be found: there is one lookup rule.
    decoy = {"model_key": MODEL_KEY, "model_revision": MODEL_REVISION}
    for decoy_dir in (tmp_path, state_dir, runtime_dir.parent / "runtimes"):
        decoy_dir.mkdir(parents=True, exist_ok=True)
        (decoy_dir / "runtime.json").write_text(json.dumps(decoy), encoding="utf-8")
        (decoy_dir / "adapter.py").write_text("ADAPTER = object()\n", encoding="utf-8")
        (decoy_dir / "canonical.py").write_text("canonicalize = None\n", encoding="utf-8")

    with pytest.raises(WorkerConfigError, match="runtime descriptor not found"):
        load_runtime_config(env)
    with pytest.raises(WorkerConfigError, match="adapter not found"):
        load_adapter(runtime_dir)
    # canonical.py is optional and its absence is labelled, never silent.
    _, source = load_canonicalizer(runtime_dir)
    assert source == "arena.worker.canonical_default"


def test_model_key_mismatch_is_named_as_an_adapter_model_mismatch(tmp_path: Path) -> None:
    from arena.worker.config import WorkerEnv
    from harness import runtime_descriptor

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    descriptor = runtime_descriptor(model_key="glm_ocr")
    (runtime_dir / "runtime.json").write_text(json.dumps(descriptor), encoding="utf-8")
    env = WorkerEnv.from_env(_env(runtime_dir, tmp_path / "state"))
    with pytest.raises(WorkerConfigError, match="adapter/model mismatch"):
        load_runtime_config(env)
