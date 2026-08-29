from __future__ import annotations

import pytest
from confirmatory_execution import (
    ExecutionRefused,
    PageRuntimeInputs,
    TriggerEvidence,
    execute_arm,
)
from recovery_protocol import Arm


def inputs(**changes):
    data = {
        "page_id": "page-1",
        "benchmark_id": "fresh",
        "primary_text": "Revenue 100 Total 200",
        "peer_text": "Revenue 100 Total 200",
        "strong_text": "Revenue 100 Total 200",
        "trigger": TriggerEvidence(risk=0.1, uncertainty=0.1),
        "primary_gpu_seconds": 1.0,
        "strong_gpu_seconds": 5.0,
        "primary_cost_usd": 0.01,
        "strong_cost_usd": 0.05,
    }
    data.update(changes)
    return PageRuntimeInputs(**data)


def test_oracle_cannot_execute_as_primary_arm():
    with pytest.raises(ExecutionRefused, match="oracle"):
        execute_arm(Arm.ORACLE_DIAGNOSTIC, inputs())


def test_tavonel_accepts_primary_when_independent_evidence_agrees():
    result = execute_arm(Arm.TAVONEL_EVIDENCE_RECOVERY, inputs())
    assert result.accepted
    assert not result.escalated_to_strong
    assert result.strong_invocations == 0
    assert result.runtime_visible_evidence["evaluation_truth_visible"] is False


def test_tavonel_escalates_but_fails_closed_if_strong_is_not_independently_supported():
    result = execute_arm(
        Arm.TAVONEL_EVIDENCE_RECOVERY,
        inputs(
            primary_text="Revenue 100",
            peer_text="Revenue 900",
            strong_text="Revenue 900",
            trigger=TriggerEvidence(risk=0.9, uncertainty=0.8),
        ),
    )
    assert result.unresolved
    assert result.escalated_to_strong
    assert result.accepted_text is None


def test_tavonel_accepts_strong_only_after_independent_support():
    result = execute_arm(
        Arm.TAVONEL_EVIDENCE_RECOVERY,
        inputs(
            primary_text="Revenue 100",
            peer_text="Revenue 900 Total 200",
            strong_text="Revenue 900 Total 200",
            trigger=TriggerEvidence(
                risk=0.9,
                uncertainty=0.8,
                strong_verified_by_independent_evidence=True,
            ),
        ),
    )
    assert result.accepted
    assert result.escalated_to_strong
    assert result.accepted_text == "Revenue 900 Total 200"


def test_disagreement_only_escalates_without_claiming_disagreement_is_truth():
    result = execute_arm(
        Arm.DISAGREEMENT_ONLY,
        inputs(primary_text="A 1", peer_text="A 2", strong_text="A 3"),
    )
    assert result.accepted
    assert result.escalated_to_strong
    assert result.accepted_text == "A 3"


def test_prediction_only_is_a_fixed_threshold_baseline():
    clean = execute_arm(
        Arm.PREDICTION_ONLY,
        inputs(
            primary_text=(
                "This is a normal complete document sentence with enough ordinary text to stay "
                "above the frozen short-output detector threshold."
            )
        ),
    )
    assert clean.accepted
    assert not clean.escalated_to_strong
    empty = execute_arm(Arm.PREDICTION_ONLY, inputs(primary_text=""))
    assert empty.accepted
    assert empty.escalated_to_strong


def test_primary_only_does_not_get_hidden_recovery_help():
    result = execute_arm(Arm.PRIMARY_ONLY, inputs(primary_text="", strong_text="perfect"))
    assert result.unresolved
    assert result.strong_invocations == 0
