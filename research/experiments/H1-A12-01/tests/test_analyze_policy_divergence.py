from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_policy_divergence.py"
SPEC = importlib.util.spec_from_file_location("h1_a12_phase0", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _history(policy_signature: str, failure_signature: str) -> list[dict[str, object]]:
    return [
        {
            "policy_signature": policy_signature,
            "failure_signature": failure_signature,
            "succeeded": False,
            "gpu_seconds": 1.0,
            "cost_units": 1.0,
            "wall_clock_seconds": 1.0,
        }
    ]


def test_phase0_detects_semantic_policy_divergence_without_claiming_outcome() -> None:
    registry = MODULE.default_recovery_registry()
    first = registry.for_code(MODULE.FailureCode.F13_TABLE_STRUCTURE)[0]
    row = {
        "case_id": "semantic-1",
        "failure_code": MODULE.FailureCode.F13_TABLE_STRUCTURE.value,
        "failure_signature": "new-table-failure",
        "history": _history(first.signature, "old-table-failure"),
        "quality_mode": "VERIFIED",
    }

    result = MODULE.analyze_records([row])

    assert result["policy_divergent_count"] == 1
    assert result["performance_conclusion_allowed"] is False
    assert result["counterfactual_recovery_outcomes_observed"] is False
    case = result["cases"][0]
    assert case["fixed_operator_kind"] == "SAME_FAMILY_RETRY"
    assert case["cause_operator_kind"] == "INDEPENDENT_FAMILY"


def test_phase0_operational_control_retains_same_policy() -> None:
    registry = MODULE.default_recovery_registry()
    first = registry.for_code(MODULE.FailureCode.F7_PARSER_EXCEPTION)[0]
    row = {
        "case_id": "operational-1",
        "failure_code": MODULE.FailureCode.F7_PARSER_EXCEPTION.value,
        "failure_signature": "new-parser-exception",
        "history": _history(first.signature, "old-parser-exception"),
        "quality_mode": "VERIFIED",
    }

    result = MODULE.analyze_records([row])

    assert result["policy_divergent_count"] == 0
    case = result["cases"][0]
    assert case["fixed_operator_kind"] == "SAME_FAMILY_RETRY"
    assert case["cause_operator_kind"] == "SAME_FAMILY_RETRY"


def test_aggregate_metrics_are_rejected_as_non_replayable() -> None:
    with pytest.raises(MODULE.InputContractError, match="aggregate metrics are not admissible"):
        MODULE.analyze_case(
            {
                "corpus_documents": 5132,
                "recovery_recovered": 1796,
                "recovery_rate": 0.99944,
            }
        )


def test_security_case_remains_blocked_in_both_selectors() -> None:
    row = {
        "case_id": "security-1",
        "failure_code": MODULE.FailureCode.F29_PROMPT_INJECTION_SUSPECTED.value,
        "failure_signature": "security",
        "history": [],
        "quality_mode": "VERIFIED",
    }

    result = MODULE.analyze_records([row])
    case = result["cases"][0]

    assert case["fixed_outcome"] == "BLOCK_SECURITY"
    assert case["cause_outcome"] == "BLOCK_SECURITY"
    assert case["policy_diverged"] is False
