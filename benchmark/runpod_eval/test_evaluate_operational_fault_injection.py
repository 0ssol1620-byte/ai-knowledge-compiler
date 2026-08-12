from __future__ import annotations

from pathlib import Path

from benchmark.runpod_eval.evaluate_operational_fault_injection import (
    SCENARIOS,
    evaluate_fault_injection,
)


def test_controlled_fault_injection_validates_state_and_quarantine(
    tmp_path: Path,
) -> None:
    output = tmp_path / "evaluation.json"
    result = evaluate_fault_injection(repository=Path.cwd(), output_path=output)

    assert result["scenario_count"] == len(SCENARIOS)
    assert result["worker_observation_count"] == len(SCENARIOS) * 4
    assert result["state_exact_accuracy"] == 1.0
    assert result["anomaly_detection"]["f1"] == 1.0
    assert result["repeated_stall_quarantine_detection"]["f1"] == 1.0
    assert result["gate_passed"] is True
    assert output.is_file()
