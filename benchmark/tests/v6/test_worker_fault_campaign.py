from benchmark.v6.worker_fault_campaign import evaluate_worker_fault_campaign


def test_masterplan_worker_fault_campaign_detects_every_fault_without_false_quarantine() -> None:
    report = evaluate_worker_fault_campaign()
    aggregate = report["aggregate"]
    assert aggregate == {
        "scenario_count": 11,
        "faulty_scenario_count": 8,
        "healthy_control_count": 3,
        "detection_recall": 1.0,
        "false_degradation_rate": 0.0,
        "false_quarantine_rate": 0.0,
        "detection_delay_p95_attempts": 0,
        "critical_leakage_count": 0,
        "fault_interval_start_accuracy": 1.0,
        "prevented_fault_count": 13,
        "gate_passed": True,
    }
    by_id = {item["scenario_id"]: item for item in report["scenarios"]}
    assert by_id["w4-last-row-delete-10pct"]["detected_state"] == "DEGRADED"
    assert by_id["w5-digit-mutation-5pct"]["detected_state"] == "QUARANTINED"
    assert "model_identity_mismatch" in by_id["wrong-revision"]["reason_codes"]
    assert "latency_p99_spike" in by_id["delayed-straggler"]["reason_codes"]
