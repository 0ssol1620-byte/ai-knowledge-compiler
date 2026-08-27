#!/usr/bin/env python3
"""Fail-closed execution contract for the GPU successor study.

This module deliberately contains no network or credential handling.  It
validates the exact materialized input set before provisioning and validates a
retrieved terminal worker result after teardown.  A pod id, a health response,
or a process id is never scientific completion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common import canonical_sha, sha_file, sha_text
from gpu_successor_preflight import CAP_GPU_HOURS, CAP_USD, DETERMINISM_REPEATS, STUDY_ID

MATERIALIZED_SCHEMA = "tavonel.v2.successor_materialized_inputs.v1"
WORKER_RESULT_SCHEMA = "tavonel.v2.gpu_successor_worker_result.v1"
RAW_OUTPUT_SCHEMA = "tavonel.v2.gpu_successor_raw_outputs.v1"
ARMS = ("VERIFIED_CURRENT_TYPED", "STALE_APPEND_ONLY")


class ExecutionContractError(RuntimeError):
    """The proposed or returned execution is not scientifically auditable."""


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ExecutionContractError(f"{label} is not a sha256:<64 hex> digest")
    try:
        int(value[7:], 16)
    except ValueError as error:
        raise ExecutionContractError(f"{label} is not a sha256:<64 hex> digest") from error
    return value


def load_input_contract(materialized_path: Path, manifest_path: Path) -> dict[str, Any]:
    """Load and independently re-hash the immutable GPU input set."""
    if not materialized_path.is_file():
        raise ExecutionContractError(f"materialized input file does not exist: {materialized_path}")
    if not manifest_path.is_file():
        raise ExecutionContractError(f"cohort manifest does not exist: {manifest_path}")
    try:
        body = json.loads(materialized_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExecutionContractError(
            f"could not parse a bound input: {type(error).__name__}"
        ) from error

    if body.get("schema") != MATERIALIZED_SCHEMA:
        raise ExecutionContractError("materialized input schema is not the frozen successor schema")
    if body.get("study_id") != STUDY_ID:
        raise ExecutionContractError("materialized inputs name a different study")
    if body.get("manifest_facts_digest") != manifest.get("facts_digest"):
        raise ExecutionContractError("materialized inputs do not bind this manifest's facts_digest")

    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise ExecutionContractError("materialized inputs contain no items")
    if body.get("item_count") != len(items):
        raise ExecutionContractError("materialized item_count does not equal the item array length")
    if manifest.get("eligible_count") != len(items):
        raise ExecutionContractError(
            "materialized item count does not equal manifest eligible_count"
        )

    seen: set[str] = set()
    item_digests: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            raise ExecutionContractError("a materialized item is not an object")
        fact_id = item.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id or fact_id in seen:
            raise ExecutionContractError("materialized fact ids must be non-empty and unique")
        seen.add(fact_id)
        arms = item.get("arms")
        if not isinstance(arms, dict) or set(arms) != set(ARMS):
            raise ExecutionContractError(
                f"materialized fact {fact_id!r} does not carry exactly both arms"
            )
        recorded = _require_sha(item.get("item_digest"), f"item_digest for {fact_id}")
        actual = canonical_sha({key: value for key, value in item.items() if key != "item_digest"})
        if recorded != actual:
            raise ExecutionContractError(f"materialized fact {fact_id!r} failed its item digest")
        item_digests.append(recorded)

    set_digest = _require_sha(body.get("set_digest"), "materialized set_digest")
    if set_digest != canonical_sha(item_digests):
        raise ExecutionContractError(
            "materialized set_digest does not match the ordered item digests"
        )

    return {
        "materialized_path": str(materialized_path.resolve()),
        "materialized_file_sha256": sha_file(materialized_path),
        "input_set_digest": set_digest,
        "manifest_sha256": sha_file(manifest_path),
        "manifest_facts_digest": manifest.get("facts_digest"),
        "fact_ids": sorted(seen),
        "item_count": len(items),
        "expected_calls": len(items) * len(ARMS) * DETERMINISM_REPEATS,
    }


def _numeric_usage(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExecutionContractError(f"observed {label} was not retrieved as a number")
    value = float(value)
    if value < 0:
        raise ExecutionContractError(f"observed {label} is negative")
    return value


def _validate_output_artifact(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise ExecutionContractError(
            "terminal worker result points to no retrieved output artifact"
        )
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExecutionContractError("retrieved worker output is not valid JSON") from error
    if artifact.get("schema") != RAW_OUTPUT_SCHEMA or artifact.get("status") != "completed":
        raise ExecutionContractError(
            "retrieved worker output is not a terminal completed raw-output artifact"
        )
    if artifact.get("input_set_digest") != contract["input_set_digest"]:
        raise ExecutionContractError("worker output does not bind the exact materialized input set")

    items = artifact.get("items")
    if not isinstance(items, list):
        raise ExecutionContractError("worker output has no item array")
    ids = [item.get("fact_id") for item in items if isinstance(item, dict)]
    if len(ids) != len(items) or sorted(ids) != contract["fact_ids"] or len(set(ids)) != len(ids):
        raise ExecutionContractError(
            "worker output fact ids are missing, duplicated, or unexpected"
        )

    completed_calls = 0
    for item in items:
        arms = item.get("arms")
        if not isinstance(arms, dict) or set(arms) != set(ARMS):
            raise ExecutionContractError(
                f"worker output fact {item.get('fact_id')!r} lacks exactly both arms"
            )
        for arm in ARMS:
            repetitions = (arms.get(arm) or {}).get("repetitions")
            if not isinstance(repetitions, list) or len(repetitions) != DETERMINISM_REPEATS:
                raise ExecutionContractError(
                    f"worker output fact {item.get('fact_id')!r} arm {arm!r} lacks exact repeats"
                )
            for repetition in repetitions:
                if not isinstance(repetition, dict) or not isinstance(
                    repetition.get("response_text"), str
                ):
                    raise ExecutionContractError("worker output contains a non-text response")
                if repetition.get("response_sha256") != sha_text(repetition["response_text"]):
                    raise ExecutionContractError(
                        "worker output response digest does not match its text"
                    )
                completed_calls += 1
    if completed_calls != contract["expected_calls"]:
        raise ExecutionContractError(
            "worker output completed-call count is not the frozen expected count"
        )
    return {"item_count": len(items), "completed_calls": completed_calls}


def validate_terminal_result(
    result: dict[str, Any],
    *,
    contract: dict[str, Any],
    runtime_image_digest: str,
    model_pin_sha256: str,
    handle: dict[str, Any],
) -> dict[str, Any]:
    """Validate completion, scientific output, observed caps, and teardown."""
    if not isinstance(result, dict) or result.get("schema") != WORKER_RESULT_SCHEMA:
        raise ExecutionContractError("executor returned no recognized worker result")
    if result.get("status") != "completed":
        raise ExecutionContractError("executor did not reach terminal status 'completed'")
    for key, expected in (
        ("input_set_digest", contract["input_set_digest"]),
        ("manifest_sha256", contract["manifest_sha256"]),
        ("runtime_image_digest", runtime_image_digest),
        ("model_pin_sha256", model_pin_sha256),
    ):
        if result.get(key) != expected:
            raise ExecutionContractError(f"terminal worker result has the wrong {key}")

    output_path = Path(str(result.get("output_path", "")))
    output_sha256 = _require_sha(result.get("output_sha256"), "worker output_sha256")
    if not output_path.is_file() or sha_file(output_path) != output_sha256:
        raise ExecutionContractError("retrieved worker output file does not match output_sha256")
    output_summary = _validate_output_artifact(output_path, contract)

    usage = handle.get("actual_usage")
    if not isinstance(usage, dict):
        raise ExecutionContractError("backend supplied no observed usage after teardown")
    gpu_seconds = _numeric_usage(usage.get("gpu_seconds"), "gpu_seconds")
    cost_usd = _numeric_usage(usage.get("cost_usd"), "cost_usd")
    if gpu_seconds > CAP_GPU_HOURS * 3600.0 or cost_usd > CAP_USD:
        raise ExecutionContractError(
            "observed execution exceeded the founder's GPU-hour or dollar cap"
        )
    if handle.get("torn_down") is not True:
        raise ExecutionContractError("backend supplied no positive teardown proof")

    return {
        "status": "completed",
        "input_set_digest": contract["input_set_digest"],
        "output_sha256": output_sha256,
        "output_summary": output_summary,
        "observed_usage": {
            "gpu_seconds": gpu_seconds,
            "gpu_hours": gpu_seconds / 3600.0,
            "cost_usd": cost_usd,
            "source": usage.get("source"),
        },
        "teardown_verified": True,
    }


__all__ = [
    "ARMS",
    "ExecutionContractError",
    "RAW_OUTPUT_SCHEMA",
    "WORKER_RESULT_SCHEMA",
    "load_input_contract",
    "validate_terminal_result",
]
