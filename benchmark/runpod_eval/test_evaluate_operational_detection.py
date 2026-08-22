from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluate_operational_detection import WorkerResult, evaluate_operational_detection

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_evaluate_operational_detection_proves_exact_routing(tmp_path: Path) -> None:
    workers = []
    for worker in range(4):
        root = tmp_path / f"worker-{worker:02d}"
        workers.append(WorkerResult(worker, root))
        for suite in SUITES:
            cases = []
            if worker == 0 and suite == "parsebench":
                cases = [
                    {
                        "case_id": f"case-{index}",
                        "status": "failed" if index == 0 else "completed",
                    }
                    for index in range(5132)
                ]
            _write(
                root / suite / "run-summary.json",
                {"runs": [{"repeat_index": 1, "cases": cases}]},
            )
    plan = tmp_path / "plan.json"
    _write(
        plan,
        {
            "schema": "folynta.public-core-operational-retry-plan.v1",
            "failed_input_count": 1,
            "different_worker_only": True,
            "failures": [
                {
                    "benchmark_id": "parsebench",
                    "case_id": "case-0",
                    "primary_worker_index": 0,
                    "retry_worker_index": 1,
                }
            ],
        },
    )
    health = tmp_path / "health.json"
    _write(
        health,
        {
            "schema": "folynta.public-core-operational-worker-health.v1",
            "classification_policy": {"quarantine_on_stall_events_gte": 2},
            "quarantined_worker_indices": [2],
            "workers": [
                {
                    "worker_index": 0,
                    "failed_case_count": 1,
                    "stall_event_count": 0,
                    "state": "DEGRADED",
                },
                {
                    "worker_index": 1,
                    "failed_case_count": 0,
                    "stall_event_count": 0,
                    "state": "HEALTHY",
                },
                {
                    "worker_index": 2,
                    "failed_case_count": 2,
                    "stall_event_count": 2,
                    "state": "QUARANTINED",
                },
                {
                    "worker_index": 3,
                    "failed_case_count": 0,
                    "stall_event_count": 0,
                    "state": "HEALTHY",
                },
            ],
        },
    )
    overlay = tmp_path / "overlay.json"
    _write(
        overlay,
        {
            "schema": "folynta.public-core-operational-retry-overlay.v1",
            "planned": 1,
            "accepted": 1,
            "unresolved": 0,
            "case_outcomes": [
                {
                    "benchmark_id": "parsebench",
                    "case_id": "case-0",
                    "primary_worker_index": 0,
                    "retry_worker_index": 1,
                    "retry_status": "completed",
                    "accepted": True,
                }
            ],
            "retry_plan_sha256": (
                "sha256:" + hashlib.sha256(plan.read_bytes()).hexdigest()
            ),
        },
    )
    classifier = Path("benchmark/runpod_eval/classify_operational_worker_health.py")
    controlled = tmp_path / "controlled.json"
    _write(
        controlled,
        {
            "schema": "folynta.operational-fault-injection-evaluation.v1",
            "gate_passed": True,
            "scenario_count": 6,
            "worker_observation_count": 24,
            "state_exact_accuracy": 1.0,
            "anomaly_detection": {"f1": 1.0},
            "repeated_stall_quarantine_detection": {"f1": 1.0},
            "claim_boundary": "controlled only",
            "source_hashes": {
                "classifier": (
                    "sha256:" + hashlib.sha256(classifier.read_bytes()).hexdigest()
                )
            },
        },
    )
    receipt = evaluate_operational_detection(
        worker_results=tuple(workers),
        retry_plan=plan,
        worker_health=health,
        operational_overlay=overlay,
        controlled_fault_evaluation=controlled,
        output_path=tmp_path / "evaluation.json",
    )
    assert receipt["case_failure_detection"]["true_positive"] == 1
    assert receipt["case_failure_detection"]["false_positive"] == 0
    assert receipt["case_failure_detection"]["false_negative"] == 0
    assert receipt["case_failure_detection"]["true_negative"] == 5131
    assert receipt["worker_repeated_stall_quarantine"]["recall"] == 1.0
    assert receipt["quarantined_worker_excluded"] is True
    assert (
        receipt["live_different_pod_retry_confirmation"][
            "different_pod_retry_completed"
        ]
        == 1
    )
    assert receipt["controlled_fault_injection"]["state_exact_accuracy"] == 1.0
