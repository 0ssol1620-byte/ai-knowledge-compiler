#!/usr/bin/env python3
"""Evaluate worker-health classification against controlled fault injections."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmark.runpod_eval.classify_operational_worker_health import (
    SUITES,
    WorkerResult,
    classify_workers,
)


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    target_worker: int | None
    failed_cases: int
    stall_events: int
    expected_state: str


SCENARIOS = (
    Scenario("all_healthy", None, 0, 0, "HEALTHY"),
    Scenario("single_case_failure", 0, 1, 0, "DEGRADED"),
    Scenario("single_stall", 1, 0, 1, "DEGRADED"),
    Scenario("repeated_stall", 2, 0, 2, "QUARANTINED"),
    Scenario("failure_plus_repeated_stall", 3, 1, 2, "QUARANTINED"),
    Scenario("many_failures_without_stall", 1, 3, 0, "DEGRADED"),
)


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _metrics(tp: int, fp: int, fn: int, tn: int) -> dict[str, int | float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _write_worker(root: Path, *, failed_cases: int, stall_events: int) -> None:
    for suite_index, suite in enumerate(SUITES):
        suite_root = root / suite
        suite_root.mkdir(parents=True)
        failures = failed_cases if suite_index == 0 else 0
        cases = [
            {
                "case_id": f"{suite}-case-{case_index}",
                "status": "failed" if case_index < failures else "completed",
            }
            for case_index in range(max(1, failures))
        ]
        payload = {
            "input_count": len(cases),
            "runs": [
                {
                    "repeat_index": 1,
                    "completed": sum(case["status"] == "completed" for case in cases),
                    "failed": sum(case["status"] == "failed" for case in cases),
                    "return_code": 1 if failures else 0,
                    "cases": cases,
                }
            ],
        }
        (suite_root / "run-summary.json").write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )
    if stall_events:
        (root / "stall-watchdog.jsonl").write_text(
            "".join(
                json.dumps(
                    {
                        "event": "suite_stall_detected",
                        "suite": SUITES[event_index % len(SUITES)],
                        "seconds_since_output": 1200,
                    },
                    sort_keys=True,
                )
                + "\n"
                for event_index in range(stall_events)
            ),
            encoding="utf-8",
        )


def evaluate_fault_injection(*, repository: Path, output_path: Path) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"fault-injection evaluation exists: {output_path}")
    observations: list[dict[str, Any]] = []
    anomaly_tp = anomaly_fp = anomaly_fn = anomaly_tn = 0
    quarantine_tp = quarantine_fp = quarantine_fn = quarantine_tn = 0
    exact = 0
    with tempfile.TemporaryDirectory(prefix="folynta-operational-fault-") as temporary:
        temporary_root = Path(temporary)
        for scenario_index, scenario in enumerate(SCENARIOS):
            scenario_root = temporary_root / f"scenario-{scenario_index:02d}"
            worker_results: list[WorkerResult] = []
            for worker_index in range(4):
                worker_root = scenario_root / f"worker-{worker_index:02d}"
                targeted = worker_index == scenario.target_worker
                _write_worker(
                    worker_root,
                    failed_cases=scenario.failed_cases if targeted else 0,
                    stall_events=scenario.stall_events if targeted else 0,
                )
                worker_results.append(WorkerResult(worker_index, worker_root))
            receipt = classify_workers(
                worker_results=tuple(worker_results),
                output_path=scenario_root / "classification.json",
            )
            for worker in receipt["workers"]:
                worker_index = int(worker["worker_index"])
                expected_state = (
                    scenario.expected_state
                    if worker_index == scenario.target_worker
                    else "HEALTHY"
                )
                predicted_state = str(worker["state"])
                expected_anomaly = expected_state != "HEALTHY"
                predicted_anomaly = predicted_state != "HEALTHY"
                expected_quarantine = expected_state == "QUARANTINED"
                predicted_quarantine = predicted_state == "QUARANTINED"
                anomaly_tp += int(expected_anomaly and predicted_anomaly)
                anomaly_fp += int(not expected_anomaly and predicted_anomaly)
                anomaly_fn += int(expected_anomaly and not predicted_anomaly)
                anomaly_tn += int(not expected_anomaly and not predicted_anomaly)
                quarantine_tp += int(expected_quarantine and predicted_quarantine)
                quarantine_fp += int(not expected_quarantine and predicted_quarantine)
                quarantine_fn += int(expected_quarantine and not predicted_quarantine)
                quarantine_tn += int(
                    not expected_quarantine and not predicted_quarantine
                )
                exact += int(expected_state == predicted_state)
                observations.append(
                    {
                        "scenario": scenario.name,
                        "worker_index": worker_index,
                        "injected_failed_case_count": (
                            scenario.failed_cases
                            if worker_index == scenario.target_worker
                            else 0
                        ),
                        "injected_stall_event_count": (
                            scenario.stall_events
                            if worker_index == scenario.target_worker
                            else 0
                        ),
                        "expected_state": expected_state,
                        "predicted_state": predicted_state,
                    }
                )
    anomaly = _metrics(anomaly_tp, anomaly_fp, anomaly_fn, anomaly_tn)
    quarantine = _metrics(
        quarantine_tp, quarantine_fp, quarantine_fn, quarantine_tn
    )
    receipt: dict[str, Any] = {
        "schema": "folynta.operational-fault-injection-evaluation.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scenario_count": len(SCENARIOS),
        "worker_observation_count": len(observations),
        "state_exact_accuracy": exact / len(observations),
        "anomaly_detection": anomaly,
        "repeated_stall_quarantine_detection": quarantine,
        "gate_passed": (
            exact == len(observations)
            and anomaly["false_positive"] == 0
            and anomaly["false_negative"] == 0
            and quarantine["false_positive"] == 0
            and quarantine["false_negative"] == 0
        ),
        "observations": observations,
        "claim_boundary": (
            "Controlled deterministic injections validate policy implementation; "
            "they do not establish external incident prevalence or generalization."
        ),
        "source_hashes": {
            "classifier": _sha256(
                repository
                / "benchmark/runpod_eval/classify_operational_worker_health.py"
            ),
            "evaluator": _sha256(Path(__file__).resolve()),
        },
    }
    encoded = json.dumps(
        receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    receipt["receipt_sha256"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = evaluate_fault_injection(
        repository=args.repository.resolve(), output_path=args.output.resolve()
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SCENARIOS", "evaluate_fault_injection"]
