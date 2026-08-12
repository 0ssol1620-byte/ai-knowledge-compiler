from __future__ import annotations

from benchmark.evaluators.system_algorithms import evaluate


def test_frozen_system_algorithm_corpus_passes_every_contract() -> None:
    report = evaluate()
    metrics = report["metrics"]

    assert report["gate"] == "PASS"
    assert metrics["page_classification"]["fixtures"] == 12
    assert metrics["page_classification"]["accuracy"] == 1.0
    assert metrics["quality_anomaly_detection"]["precision"] == 1.0
    assert metrics["quality_anomaly_detection"]["recall"] == 1.0
    assert metrics["failure_diagnosis"]["fixtures"] == 24
    assert metrics["failure_diagnosis"]["accuracy"] == 1.0
    assert metrics["recovery_selection"]["fixtures"] == 18
    assert metrics["recovery_selection"]["selection_accuracy"] == 1.0
    assert metrics["recovery_selection"]["minimum_scope_selected"] == "cell"
    assert metrics["routing_and_escalation"]["decision_accuracy"] == 1.0
    assert metrics["credit_accounting"]["duplicate_attempts"] == 32
    assert metrics["credit_accounting"]["duplicate_charge_credits"] == "0.000000"
    assert metrics["credit_accounting"]["conservation_invariant"] is True
