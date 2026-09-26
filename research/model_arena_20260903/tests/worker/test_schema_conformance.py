"""The worker's wire objects against lane A1's frozen JSON Schemas.

These are the tests that catch a B2/B1 integration break before a pod is ever
provisioned. If A1 changes a schema, one of these goes red on the next run
rather than at 3am with 5,132 pages queued.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arena.constants import NAMESPACE_ROOT, WORKER_STATES
from harness import worker

SCHEMA_DIR = NAMESPACE_ROOT / "arena" / "core" / "schemas"

# Known deltas between this worker's wire objects and lane A1's schemas while
# the integration pass lands. Each is a decision recorded in ARENA_CONTRACT
# section 11.1, not a refusal to conform: A1 owns the schema files, B2 owns the
# worker, and the two land in the same pass.
HEARTBEAT_EXTRA_KEYS = frozenset({"ts", "gpu_metrics_unavailable_reason"})  # D4
RESPONSE_PENDING_KEYS = frozenset({"semantic_error_class"})  # D3


def _schema(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / name
    if not path.is_file():
        pytest.skip(f"lane A1 has not written {name} yet")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _trim_pending(schema: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Drop D3 keys A1 has not added yet, and prove nothing else is extra."""
    properties = set(schema["properties"])
    extra = set(body) - properties
    assert extra <= RESPONSE_PENDING_KEYS, f"unexpected response keys: {sorted(extra)}"
    return {key: value for key, value in body.items() if key in properties}


def _errors(schema: dict[str, Any], instance: object) -> list[str]:
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{list(error.path)}: {error.message}"
        for error in sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    ]


def test_run_request_fixture_matches_the_request_schema(tmp_path: Path) -> None:
    schema = _schema("worker-run-request.schema.json")
    with worker(tmp_path) as handle:
        assert _errors(schema, handle.run_payload()) == []
        assert _errors(schema, handle.run_payload(timeout_seconds=120)) == []


def test_success_response_matches_the_response_schema(tmp_path: Path) -> None:
    schema = _schema("worker-run-response.schema.json")
    with worker(tmp_path) as handle:
        status, body = handle.post("/v1/run", handle.run_payload())
        assert status == 200
        assert body["status"] == "SUCCESS"
        assert _errors(schema, _trim_pending(schema, body)) == []


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"metadata": {"fake": {"error_class": "CUDA_OOM"}}}, 200),
        ({"metadata": {"fake": {"raise_plain_exception": True}}}, 200),
        ({"source_sha256": "sha256:" + "e" * 64}, 422),
        ({"image_b64": "%%%not base64%%%"}, 422),
    ],
)
def test_failed_responses_match_the_response_schema(
    tmp_path: Path, overrides: dict[str, Any], expected_status: int
) -> None:
    schema = _schema("worker-run-response.schema.json")
    with worker(tmp_path) as handle:
        status, body = handle.post("/v1/run", handle.run_payload(**overrides))
        assert status == expected_status
        assert body["status"] == "FAILED"
        assert _errors(schema, _trim_pending(schema, body)) == []


def test_timeout_response_matches_the_response_schema(tmp_path: Path) -> None:
    schema = _schema("worker-run-response.schema.json")
    with worker(tmp_path) as handle:
        status, body = handle.post(
            "/v1/run",
            handle.run_payload(
                timeout_seconds=1,
                metadata={"page_index": 0, "fake": {"delay_seconds": 30}},
            ),
        )
        assert status == 200
        assert body["error_class"] == "INFERENCE_TIMEOUT"
        assert _errors(schema, _trim_pending(schema, body)) == []


def test_ready_response_matches_the_ready_schema(tmp_path: Path) -> None:
    schema = _schema("ready-response.schema.json")
    with worker(tmp_path, prompt_text="prompt\n") as handle:
        assert _errors(schema, handle.get("/v1/ready")[1]) == []


def test_crashed_ready_response_matches_the_ready_schema(tmp_path: Path) -> None:
    schema = _schema("ready-response.schema.json")
    with worker(
        tmp_path, descriptor_overrides={"inference_config": {"fake_load_error": "MODEL_LOAD"}}
    ) as handle:
        body = handle.get("/v1/ready")[1]
        assert body["stage"] == "CRASHED"
        assert _errors(schema, body) == []


def test_fatal_file_ready_response_matches_the_ready_schema(tmp_path: Path) -> None:
    """D47: the fatal-file CRASHED path carries its reason in ``last_error``.

    ``ready-response.schema.json`` is ``additionalProperties: false`` and has
    no ``fatal`` object, so the worker folds the reason into the existing
    ``last_error`` string field instead of inventing a new one.
    """
    schema = _schema("ready-response.schema.json")
    fatal = tmp_path / "FATAL"
    fatal.write_text("model server never became healthy\n", encoding="utf-8")
    with worker(tmp_path, env_overrides={"ARENA_FATAL_FILE": str(fatal)}) as handle:
        body = handle.get("/v1/ready")[1]
        assert body["stage"] == "CRASHED"
        assert _errors(schema, body) == []


def test_runtime_descriptor_fixture_matches_the_runtime_schema(tmp_path: Path) -> None:
    schema = _schema("runtime.schema.json")
    with worker(tmp_path) as handle:
        assert _errors(schema, handle.descriptor) == []


def test_heartbeat_matches_the_heartbeat_schema_modulo_known_deltas(tmp_path: Path) -> None:
    """The heartbeat shape is right; two documented deltas remain.

    1. Extra diagnostic keys (A1's schema is additionalProperties:false).
    2. ``gpu_util``/``vram_used`` are null on a host with no nvidia-smi, which
       the schema types as a bare number. Reporting 0 there would be
       indistinguishable from a genuinely idle GPU.
    """
    schema = _schema("heartbeat.schema.json")
    with worker(tmp_path) as handle:
        status, body = handle.get("/v1/heartbeat")
        assert status == 200
        assert body["state"] in WORKER_STATES  # D4
        assert set(body) - set(schema["properties"]) <= HEARTBEAT_EXTRA_KEYS

        trimmed = {key: value for key, value in body.items() if key in schema["properties"]}
        if trimmed.get("gpu_util") is None:
            assert body["gpu_metrics_unavailable_reason"]
            trimmed["gpu_util"] = 0
            trimmed["vram_used"] = 0
        assert _errors(schema, trimmed) == []


def test_heartbeat_state_is_always_a_worker_states_value() -> None:
    """D4: no coarse bucket, no invented label, no stage without a state."""
    from arena.worker.server import WORKER_STATE_VALUES, _worker_state

    assert set(WORKER_STATES) == WORKER_STATE_VALUES
    for stage in WORKER_STATES:
        assert _worker_state(stage) == stage

    with pytest.raises(RuntimeError, match="WORKER_STATES"):
        _worker_state("NOT_A_STATE")
