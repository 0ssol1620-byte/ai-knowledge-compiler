from __future__ import annotations

import json
from pathlib import Path

import pytest
from akc_parallel_runtime import FailureCode

from benchmark.v6.failure_detection import (
    FailureLabel,
    FailurePrediction,
    evaluate_failure_detection,
)
from benchmark.v6.fault_injection import (
    RecoveryBenchmarkSample,
    detect_faults,
    inject_fault,
)


def _sample() -> RecoveryBenchmarkSample:
    return RecoveryBenchmarkSample(
        item_id="page-1",
        text_blocks=("Revenue 123", "Operating income 45"),
        table_rows=(("Period", "Value"), ("2024", "100"), ("2025", "123")),
        source_refs=("page://1", "xbrl://fact/1"),
        reading_order=(0, 1),
    )


@pytest.mark.parametrize("code", tuple(FailureCode))
def test_fault_injection_is_content_bound_and_changes_one_sample(code: FailureCode) -> None:
    source = _sample()
    result = inject_fault(source, code)

    assert result.code is code
    assert result.source_sha256 != result.corrupted_sha256
    assert result.sample.item_id == "page-1"
    assert detect_faults(source, result.sample) == frozenset({code})


def test_authority_bound_detector_does_not_flag_healthy_control() -> None:
    source = _sample()

    assert detect_faults(source, source) == frozenset()


def test_golden_campaign_covers_exact_masterplan_taxonomy() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "v6"
        / "cohorts"
        / "recovery-fault-injection-golden.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    label_codes = {
        code
        for item in payload["failure_labels"]
        for code in item["failure_codes"]
    }
    prediction_codes = {
        code
        for item in payload["failure_predictions"]
        for code in item["failure_codes"]
    }

    assert label_codes == prediction_codes == {code.value for code in FailureCode}
    assert len(payload["failure_labels"]) == len(FailureCode) + 1


def test_failure_detection_reports_silent_omission_and_false_recovery() -> None:
    labels = (
        FailureLabel("faulty", frozenset({"T01"}), "row", "row-2", True),
        FailureLabel("healthy", frozenset(), None, None, False),
    )
    predictions = (
        FailurePrediction("healthy", frozenset({"T01"}), "row", "row-1", True),
    )

    metrics = evaluate_failure_detection(labels, predictions)

    assert metrics.recall == 0
    assert metrics.silent_omission_rate == 1
    assert metrics.false_recovery_rate == 1
    assert metrics.gate_passed is False


def test_failure_detection_gate_requires_exact_detection_scope_and_recovery() -> None:
    labels = (
        FailureLabel("faulty", frozenset({"N01"}), "cell", "cell-4", True, True),
        FailureLabel("healthy", frozenset(), None, None, False),
    )
    predictions = (
        FailurePrediction("faulty", frozenset({"N01"}), "cell", "cell-4", True, True),
        FailurePrediction("healthy", frozenset(), None, None, False),
    )

    metrics = evaluate_failure_detection(labels, predictions)

    assert metrics.precision == metrics.recall == metrics.f1 == 1
    assert metrics.localization_exact_accuracy == 1
    assert metrics.minimal_scope_accuracy == 1
    assert metrics.recovery_decision_accuracy == 1
    assert metrics.escalation_accuracy == 1
    assert metrics.gate_passed is True


@pytest.mark.parametrize(
    ("prediction", "expected_metric"),
    (
        (
            FailurePrediction(
                "faulty", frozenset({"N01", "T01"}), "cell", "cell-4", True, True
            ),
            "type_exact_accuracy",
        ),
        (
            FailurePrediction("faulty", frozenset({"N01"}), "row", "row-4", True, True),
            "localization_exact_accuracy",
        ),
        (
            FailurePrediction("faulty", frozenset({"N01"}), "cell", "cell-4", False, True),
            "recovery_decision_accuracy",
        ),
        (
            FailurePrediction("faulty", frozenset({"N01"}), "cell", "cell-4", True, False),
            "escalation_accuracy",
        ),
    ),
)
def test_failure_detection_gate_rejects_each_inexact_detector_dimension(
    prediction: FailurePrediction,
    expected_metric: str,
) -> None:
    label = FailureLabel("faulty", frozenset({"N01"}), "cell", "cell-4", True, True)

    metrics = evaluate_failure_detection((label,), (prediction,))

    assert getattr(metrics, expected_metric) < 1
    assert metrics.gate_passed is False
