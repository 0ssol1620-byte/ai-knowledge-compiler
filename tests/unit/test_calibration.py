from __future__ import annotations

import pytest
from akc_cir.calibration import (
    CalibrationExample,
    CalibrationMethod,
    evaluate_calibrator,
    fit_calibrator,
)


def _train():
    return [
        CalibrationExample("train-clean-1", 0.05, False),
        CalibrationExample("train-clean-2", 0.20, False),
        CalibrationExample("train-bad-1", 0.75, True),
        CalibrationExample("train-bad-2", 0.95, True),
    ]


@pytest.mark.parametrize("method", list(CalibrationMethod))
def test_calibrators_are_versioned_deterministic_and_bounded(method) -> None:
    artifact = fit_calibrator(
        _train(), method=method, detector_code="F9", calibrated_from="pilot-v1"
    )
    again = fit_calibrator(
        _train(), method=method, detector_code="F9", calibrated_from="pilot-v1"
    )
    assert artifact.artifact_id == again.artifact_id
    assert artifact.artifact_version == 1
    assert 0.0 <= artifact.predict(0.6) <= 1.0


def test_isotonic_is_monotone() -> None:
    artifact = fit_calibrator(
        _train(), method=CalibrationMethod.ISOTONIC,
        detector_code="F9", calibrated_from="pilot-v1"
    )
    predictions = [artifact.predict(x / 20) for x in range(21)]
    assert predictions == sorted(predictions)


def test_eval_reports_brier_ece_and_reliability() -> None:
    artifact = fit_calibrator(
        _train(), method=CalibrationMethod.LOGISTIC,
        detector_code="F9", calibrated_from="pilot-v1"
    )
    metrics = evaluate_calibrator(
        artifact,
        [
            CalibrationExample("eval-clean", 0.1, False),
            CalibrationExample("eval-bad", 0.9, True),
        ],
    )
    assert metrics.count == 2
    assert 0.0 <= metrics.brier <= 1.0
    assert 0.0 <= metrics.ece <= 1.0
    assert sum(item.count for item in metrics.reliability) == 2


def test_evaluation_refuses_train_eval_leakage() -> None:
    artifact = fit_calibrator(
        _train(), method=CalibrationMethod.LOGISTIC,
        detector_code="F9", calibrated_from="pilot-v1"
    )
    with pytest.raises(ValueError, match="leakage"):
        evaluate_calibrator(artifact, [CalibrationExample("train-clean-1", 0.1, False)])