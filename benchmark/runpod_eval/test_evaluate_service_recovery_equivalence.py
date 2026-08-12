from __future__ import annotations

import json
from pathlib import Path

from benchmark.runpod_eval.evaluate_service_recovery_equivalence import (
    SERVICE_SOURCE_PATHS,
    evaluate,
)


def test_service_recovery_equivalence_binds_sources_tests_and_faults(
    tmp_path: Path,
) -> None:
    for relative in SERVICE_SOURCE_PATHS:
        source = tmp_path / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"source:{relative}\n", encoding="utf-8")
    log = tmp_path / "benchmark/reports/generated/service-tests.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("................................ 60 passed in 1.00s\n", encoding="utf-8")
    output = tmp_path / "benchmark/reports/generated/service-evidence.json"

    payload = evaluate(repository=tmp_path, service_test_log=log, output=output)

    assert payload["schema"] == "folynta.service-recovery-equivalence-evaluation.v1"
    assert payload["status"] == "complete_service_recovery_equivalence_verified"
    assert payload["gate_passed"] is True
    assert payload["service_test_count"] == 60
    assert payload["scenario_count"] == 12
    assert payload["anomaly_detection"]["f1"] == 1.0
    assert payload["quarantine_detection"]["f1"] == 1.0
    assert len(payload["service_source_fingerprints"]) == len(SERVICE_SOURCE_PATHS)

    # Silence is its own failure mode: these two scenarios inject no observation
    # at all and must still be detected, otherwise a wedged probe transport
    # reads as health.
    silence = {
        item["scenario"]: item
        for item in payload["scenarios"]
        if item.get("signal_injected") is False
    }
    assert set(silence) == {"infrastructure_signal_stale", "infrastructure_signal_silent"}
    assert silence["infrastructure_signal_stale"]["observed_state"] == "DRAINING"
    assert silence["infrastructure_signal_silent"]["observed_state"] == "QUARANTINED"
    assert all(item["passed"] for item in silence.values())

    absence = payload["equivalence_contract"]["signal_absence_detection"]
    assert absence["stale_threshold_seconds"] < absence["silent_threshold_seconds"]

    # A destroyed resource is terminal and distinct from quarantine, and the
    # pool must be able to say how many replacements it needs.
    by_name = {item["scenario"]: item for item in payload["scenarios"]}
    loss = by_name["provider_resource_deleted"]
    assert loss["observed_state"] == "TERMINATED"
    assert loss["transition_reason_codes"] == ["provider_resource_deleted"]
    assert loss["serving_after"] == []

    deficit = by_name["pool_capacity_deficit_after_resource_loss"]
    assert deficit["passed"] is True
    assert deficit["intact_replacements_required"] == 0
    assert deficit["degraded_replacements_required"] == 2
    assert deficit["degraded_serving_worker_count"] == 1
    # The claim must say out loud what detection depends on.
    assert "conditional on an observation reaching the registry" in payload["claim_boundary"]
    assert json.loads(output.read_text(encoding="utf-8"))["receipt_sha256"].startswith(
        "sha256:"
    )


def test_service_recovery_equivalence_accepts_windows_utf16_pytest_log(
    tmp_path: Path,
) -> None:
    for relative in SERVICE_SOURCE_PATHS:
        source = tmp_path / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"source:{relative}\n", encoding="utf-8")
    log = tmp_path / "service-tests.log"
    log.write_text("90 passed in 2.00s\n", encoding="utf-16")

    payload = evaluate(
        repository=tmp_path,
        service_test_log=log,
        output=tmp_path / "service-evidence.json",
    )

    assert payload["service_test_count"] == 90
