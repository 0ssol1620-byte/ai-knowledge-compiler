"""Focused zero-network tests for terminal GPU execution evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

from common import canonical_sha, sha_file, sha_text  # noqa: E402
import gpu_successor_execution as execution  # noqa: E402
import gpu_successor_preflight as gsp  # noqa: E402
import runpod_provisioner as runpod  # noqa: E402


def _contract(tmp_path: Path) -> tuple[dict, dict, Path]:
    fact_id = "fact-1"
    manifest = tmp_path / "manifest.json"
    manifest_body = {
        "eligible_count": 1,
        "facts_digest": "sha256:" + "a" * 64,
        "facts": [{"fact_id": fact_id}],
    }
    manifest.write_text(json.dumps(manifest_body), encoding="utf-8")
    item = {
        "fact_id": fact_id,
        "arms": {arm: {"fixture": arm} for arm in execution.ARMS},
    }
    item["item_digest"] = canonical_sha(item)
    materialized = tmp_path / "inputs.json"
    materialized.write_text(
        json.dumps(
            {
                "schema": execution.MATERIALIZED_SCHEMA,
                "study_id": gsp.STUDY_ID,
                "manifest_facts_digest": manifest_body["facts_digest"],
                "item_count": 1,
                "items": [item],
                "set_digest": canonical_sha([item["item_digest"]]),
            }
        ),
        encoding="utf-8",
    )
    contract = execution.load_input_contract(materialized, manifest)
    return contract, manifest_body, materialized


def _terminal(tmp_path: Path, contract: dict) -> tuple[dict, dict]:
    output = {
        "schema": execution.RAW_OUTPUT_SCHEMA,
        "status": "completed",
        "input_set_digest": contract["input_set_digest"],
        "items": [],
    }
    for fact_id in contract["fact_ids"]:
        arms = {}
        for arm in execution.ARMS:
            text = f"answer {fact_id} {arm}"
            arms[arm] = {
                "repetitions": [
                    {"response_text": text, "response_sha256": sha_text(text)}
                    for _ in range(gsp.DETERMINISM_REPEATS)
                ]
            }
        output["items"].append({"fact_id": fact_id, "arms": arms})
    output_path = tmp_path / "outputs.json"
    output_path.write_text(json.dumps(output), encoding="utf-8")
    result = {
        "schema": execution.WORKER_RESULT_SCHEMA,
        "status": "completed",
        "input_set_digest": contract["input_set_digest"],
        "manifest_sha256": contract["manifest_sha256"],
        "runtime_image_digest": "repo/image@sha256:" + "b" * 64,
        "model_pin_sha256": "sha256:" + "c" * 64,
        "output_path": str(output_path),
        "output_sha256": sha_file(output_path),
    }
    handle = {
        "actual_usage": {"gpu_seconds": 30.0, "cost_usd": 0.05, "source": "fixture"},
        "torn_down": True,
    }
    return result, handle


def _validate(result: dict, handle: dict, contract: dict) -> dict:
    return execution.validate_terminal_result(
        result,
        contract=contract,
        runtime_image_digest="repo/image@sha256:" + "b" * 64,
        model_pin_sha256="sha256:" + "c" * 64,
        handle=handle,
    )


def test_terminal_completed_output_with_hashes_usage_and_teardown_passes(tmp_path):
    contract, _manifest, _materialized = _contract(tmp_path)
    result, handle = _terminal(tmp_path, contract)
    validated = _validate(result, handle, contract)
    assert validated["status"] == "completed"
    assert validated["output_summary"]["completed_calls"] == 4
    assert validated["teardown_verified"] is True


@pytest.mark.parametrize("mutation", ["running", "bad_output_hash", "usage_unknown", "not_torn_down"])
def test_nonterminal_or_unauditable_result_never_passes(tmp_path, mutation):
    contract, _manifest, _materialized = _contract(tmp_path)
    result, handle = _terminal(tmp_path, contract)
    if mutation == "running":
        result["status"] = "running"
    elif mutation == "bad_output_hash":
        result["output_sha256"] = "sha256:" + "0" * 64
    elif mutation == "usage_unknown":
        handle["actual_usage"]["gpu_seconds"] = runpod.NOT_RETRIEVED
    else:
        handle["torn_down"] = False
    with pytest.raises(execution.ExecutionContractError):
        _validate(result, handle, contract)


def test_observed_cap_violation_never_passes(tmp_path):
    contract, _manifest, _materialized = _contract(tmp_path)
    result, handle = _terminal(tmp_path, contract)
    handle["actual_usage"]["cost_usd"] = gsp.CAP_USD + 0.01
    with pytest.raises(execution.ExecutionContractError, match="exceeded"):
        _validate(result, handle, contract)


def test_real_runpod_backend_names_missing_scientific_prerequisites():
    readiness = runpod.RunpodPodProvisioner.execution_readiness({})
    assert readiness["passed"] is False
    codes = {item["code"] for item in readiness["missing_prerequisites"]}
    assert {
        "PINNED_WORKER_ENTRYPOINT_ABSENT",
        "CONTENT_ADDRESSED_INPUT_TRANSPORT_ABSENT",
        "TERMINAL_STATUS_CHANNEL_ABSENT",
        "CONTENT_ADDRESSED_OUTPUT_RETRIEVAL_ABSENT",
        "LIVE_USAGE_KILL_SWITCH_ABSENT",
        "FROZEN_SUCCESSOR_SCORER_ABSENT",
    } == codes
