#!/usr/bin/env python3
"""Quantify case-failure detection and worker quarantine decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")


@dataclass(frozen=True, slots=True)
class WorkerResult:
    worker_index: int
    result_root: Path


def _load(path: Path) -> dict[str, Any]:
    # PowerShell-written receipts carry a UTF-8 BOM; utf-8-sig reads both shapes.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"non-object JSONL at {path}:{line_number}")
        records.append(value)
    return records


def _metrics(tp: int, fp: int, fn: int, tn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    accuracy = (tp + tn) / (tp + fp + fn + tn) if tp + fp + fn + tn else None
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "accuracy": accuracy,
    }


def evaluate_operational_detection(
    *,
    worker_results: tuple[WorkerResult, ...],
    retry_plan: Path,
    worker_health: Path,
    operational_overlay: Path | None = None,
    controlled_fault_evaluation: Path | None = None,
    live_prefetch_incident_evidence: Path | None = None,
    output_path: Path,
) -> dict[str, Any]:
    workers = sorted(worker_results, key=lambda item: item.worker_index)
    if [item.worker_index for item in workers] != [0, 1, 2, 3]:
        raise ValueError("exactly worker indices 0, 1, 2, and 3 are required")
    if output_path.exists():
        raise FileExistsError(f"operational detection report exists: {output_path}")
    plan = _load(retry_plan)
    health = _load(worker_health)
    if (
        plan.get("schema") != "folynta.public-core-operational-retry-plan.v1"
        or health.get("schema") != "folynta.public-core-operational-worker-health.v1"
    ):
        raise ValueError("operational detection input identity is invalid")
    routed = {
        (str(item["benchmark_id"]), str(item["case_id"]))
        for item in plan.get("failures", [])
    }
    if len(routed) != int(plan.get("failed_input_count", -1)):
        raise ValueError("operational retry plan contains duplicate failure routes")
    actual_failed: set[tuple[str, str]] = set()
    all_cases: set[tuple[str, str]] = set()
    live_worker_evidence: list[dict[str, Any]] = []
    per_suite_counts: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    )
    for worker in workers:
        suite_evidence: list[dict[str, Any]] = []
        for suite in SUITES:
            summary_path = worker.result_root / suite / "run-summary.json"
            summary = _load(summary_path)
            runs = summary.get("runs", [])
            if len(runs) != 1 or int(runs[0].get("repeat_index", -1)) != 1:
                raise ValueError("operational detection requires baseline repeat 1")
            for case in runs[0].get("cases", []):
                key = (suite, str(case["case_id"]))
                if key in all_cases:
                    raise ValueError(f"duplicate baseline case: {key}")
                all_cases.add(key)
                status = str(case.get("status"))
                if status == "failed":
                    actual_failed.add(key)
                elif status != "completed":
                    raise ValueError(f"unsupported baseline status: {key}/{status}")
            suite_cases = runs[0].get("cases", [])
            suite_evidence.append(
                {
                    "benchmark_id": suite,
                    "input_count": int(summary.get("input_count", len(suite_cases))),
                    "completed": int(
                        runs[0].get(
                            "completed",
                            sum(case.get("status") == "completed" for case in suite_cases),
                        )
                    ),
                    "failed": int(
                        runs[0].get(
                            "failed",
                            sum(case.get("status") == "failed" for case in suite_cases),
                        )
                    ),
                    "run_summary_sha256": _sha256(summary_path),
                }
            )
        watchdog_path = worker.result_root / "stall-watchdog.jsonl"
        watchdog_events = _json_lines(watchdog_path)
        live_worker_evidence.append(
            {
                "worker_index": worker.worker_index,
                "suites": suite_evidence,
                "watchdog_sha256": (
                    _sha256(watchdog_path) if watchdog_path.is_file() else None
                ),
                "watchdog_events": watchdog_events,
            }
        )
    if len(all_cases) != 5132:
        raise ValueError("operational detection requires all 5,132 public cases")
    tp_cases = actual_failed & routed
    fp_cases = routed - actual_failed
    fn_cases = actual_failed - routed
    tn_cases = all_cases - actual_failed - routed
    for suite, case_id in all_cases:
        key = (suite, case_id)
        bucket = per_suite_counts[suite]
        if key in tp_cases:
            bucket["tp"] += 1
        elif key in fp_cases:
            bucket["fp"] += 1
        elif key in fn_cases:
            bucket["fn"] += 1
        else:
            bucket["tn"] += 1

    health_workers = {int(item["worker_index"]): item for item in health.get("workers", [])}
    if set(health_workers) != {0, 1, 2, 3}:
        raise ValueError("worker health receipt does not cover all four workers")
    anomaly_tp = anomaly_fp = anomaly_fn = anomaly_tn = 0
    quarantine_tp = quarantine_fp = quarantine_fn = quarantine_tn = 0
    worker_decisions: list[dict[str, Any]] = []
    for index, worker in sorted(health_workers.items()):
        actual_anomaly = int(worker["failed_case_count"]) > 0 or int(
            worker["stall_event_count"]
        ) > 0
        predicted_anomaly = str(worker["state"]) != "HEALTHY"
        actual_quarantine = int(worker["stall_event_count"]) >= int(
            health["classification_policy"]["quarantine_on_stall_events_gte"]
        )
        predicted_quarantine = str(worker["state"]) == "QUARANTINED"
        if actual_anomaly and predicted_anomaly:
            anomaly_tp += 1
        elif not actual_anomaly and predicted_anomaly:
            anomaly_fp += 1
        elif actual_anomaly:
            anomaly_fn += 1
        else:
            anomaly_tn += 1
        if actual_quarantine and predicted_quarantine:
            quarantine_tp += 1
        elif not actual_quarantine and predicted_quarantine:
            quarantine_fp += 1
        elif actual_quarantine:
            quarantine_fn += 1
        else:
            quarantine_tn += 1
        worker_decisions.append(
            {
                "worker_index": index,
                "observed_anomaly": actual_anomaly,
                "predicted_anomaly": predicted_anomaly,
                "observed_repeated_stall": actual_quarantine,
                "predicted_quarantine": predicted_quarantine,
                "state": str(worker["state"]),
            }
        )
    quarantined = set(int(value) for value in health["quarantined_worker_indices"])
    invalid_retry_targets = [
        item
        for item in plan.get("failures", [])
        if int(item["retry_worker_index"]) in quarantined
        or int(item["retry_worker_index"]) == int(item["primary_worker_index"])
    ]
    routing_metrics = _metrics(
        len(tp_cases), len(fp_cases), len(fn_cases), len(tn_cases)
    )
    retry_confirmation: dict[str, Any] | None = None
    if operational_overlay is not None:
        overlay = _load(operational_overlay)
        if overlay.get("schema") != "folynta.public-core-operational-retry-overlay.v1":
            raise ValueError("operational retry overlay identity is invalid")
        planned = int(overlay.get("planned", -1))
        accepted = int(overlay.get("accepted", -1))
        unresolved = int(overlay.get("unresolved", -1))
        if (
            planned != len(routed)
            or accepted < 0
            or unresolved < 0
            or accepted + unresolved != planned
            or str(overlay.get("retry_plan_sha256")) != _sha256(retry_plan)
        ):
            raise ValueError("operational retry overlay coverage is invalid")
        case_outcomes = overlay.get("case_outcomes", [])
        outcome_keys = {
            (str(item["benchmark_id"]), str(item["case_id"]))
            for item in case_outcomes
        }
        if (
            len(case_outcomes) != planned
            or outcome_keys != routed
            or sum(bool(item.get("accepted")) for item in case_outcomes) != accepted
        ):
            raise ValueError("operational retry case outcomes are incomplete")
        retry_confirmation = {
            "detected_case_count": planned,
            "different_pod_retry_completed": accepted,
            "different_pod_retry_failed": unresolved,
            "confirmed_recoverable_rate": accepted / planned if planned else None,
            "interpretation": (
                "Completion on a different eligible Pod is outcome-based support for "
                "a transient or worker-local operational failure. A repeated failure "
                "remains ambiguous and is not counted as a confirmed false positive."
            ),
            "overlay_sha256": _sha256(operational_overlay),
            "case_outcomes": case_outcomes,
        }
    controlled_faults: dict[str, Any] | None = None
    if controlled_fault_evaluation is not None:
        controlled = _load(controlled_fault_evaluation)
        classifier_path = Path(__file__).resolve().with_name(
            "classify_operational_worker_health.py"
        )
        if (
            controlled.get("schema")
            != "folynta.operational-fault-injection-evaluation.v1"
            or controlled.get("gate_passed") is not True
            or str(controlled.get("source_hashes", {}).get("classifier"))
            != _sha256(classifier_path)
        ):
            raise ValueError("controlled operational fault evaluation is invalid")
        controlled_faults = {
            "scenario_count": int(controlled["scenario_count"]),
            "worker_observation_count": int(controlled["worker_observation_count"]),
            "state_exact_accuracy": float(controlled["state_exact_accuracy"]),
            "anomaly_detection": controlled["anomaly_detection"],
            "repeated_stall_quarantine_detection": controlled[
                "repeated_stall_quarantine_detection"
            ],
            "claim_boundary": str(controlled["claim_boundary"]),
            "evidence_sha256": _sha256(controlled_fault_evaluation),
        }
    live_prefetch_incidents: dict[str, Any] | None = None
    if live_prefetch_incident_evidence is not None:
        incidents = _load(live_prefetch_incident_evidence)
        observations = incidents.get("corrected_worker_observations", [])
        incident_codes = [str(item["code"]) for item in incidents.get("incidents", [])]
        if (
            incidents.get("schema")
            != "folynta.operational-prefetch-incident-evidence.v1"
            or incidents.get("secret_free") is not True
            or len(incident_codes) != 3
            or len(set(incident_codes)) != 3
            or len(observations) != 3
            or any(
                int(item.get("corrected_runner_process_count", 0)) < 1
                for item in observations
            )
            or sum(
                int(item.get("corrected_run_model_artifact_count", 0))
                for item in observations
            )
            < 1
        ):
            raise ValueError("live operational prefetch incident evidence is invalid")
        live_prefetch_incidents = {
            "incident_count": len(incident_codes),
            "incident_codes": incident_codes,
            "corrected_worker_count": len(observations),
            "corrected_running_worker_count": sum(
                int(item["corrected_runner_process_count"]) >= 1
                for item in observations
            ),
            "corrected_model_artifact_count_at_capture": sum(
                int(item["corrected_run_model_artifact_count"])
                for item in observations
            ),
            "evidence_sha256": _sha256(live_prefetch_incident_evidence),
            "interpretation": (
                "These are live campaign launch and contract faults with preserved "
                "raw evidence and successful corrected-run observations. They extend "
                "the controlled fault set but are not an external-distribution claim."
            ),
        }
    receipt: dict[str, Any] = {
        "schema": "folynta.public-core-operational-detection-evaluation.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "input_count": len(all_cases),
        "case_failure_detection": routing_metrics,
        "case_failure_routing_coverage": routing_metrics,
        "retry_route_evidence": plan.get("failures", []),
        "live_worker_evidence": live_worker_evidence,
        "case_failure_detection_by_suite": {
            suite: _metrics(
                per_suite_counts[suite]["tp"],
                per_suite_counts[suite]["fp"],
                per_suite_counts[suite]["fn"],
                per_suite_counts[suite]["tn"],
            )
            for suite in SUITES
        },
        "worker_anomaly_detection": _metrics(
            anomaly_tp, anomaly_fp, anomaly_fn, anomaly_tn
        ),
        "worker_repeated_stall_quarantine": _metrics(
            quarantine_tp, quarantine_fp, quarantine_fn, quarantine_tn
        ),
        "worker_decisions": worker_decisions,
        "invalid_retry_target_count": len(invalid_retry_targets),
        "different_worker_only": plan.get("different_worker_only") is True,
        "quarantined_worker_excluded": not invalid_retry_targets,
        "live_different_pod_retry_confirmation": retry_confirmation,
        "controlled_fault_injection": controlled_faults,
        "live_prefetch_incidents": live_prefetch_incidents,
        "measurement_scope": {
            "case_labels": (
                "baseline run-summary terminal status; this measures exact retry "
                "routing coverage, not independent predictive generalization"
            ),
            "worker_anomaly_labels": (
                "observed failed cases or watchdog stall events; this measures live "
                "policy conformance"
            ),
            "quarantine_labels": (
                "observed repeated watchdog stalls under the frozen threshold; this "
                "measures live policy conformance"
            ),
            "outcome_confirmation": (
                "subsequent different-Pod retry completion, when an overlay is supplied"
            ),
            "controlled_fault_labels": (
                "independently declared deterministic injected scenario labels, when "
                "controlled evidence is supplied"
            ),
            "external_incident_generalization_claimed": False,
        },
        "retry_plan_sha256": _sha256(retry_plan),
        "worker_health_sha256": _sha256(worker_health),
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


def _worker(value: str) -> WorkerResult:
    try:
        index, path = value.split("=", 1)
        return WorkerResult(int(index), Path(path))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("worker result must be INDEX=PATH") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-result", action="append", type=_worker, required=True)
    parser.add_argument("--retry-plan", type=Path, required=True)
    parser.add_argument("--worker-health", type=Path, required=True)
    parser.add_argument("--operational-overlay", type=Path)
    parser.add_argument("--controlled-fault-evaluation", type=Path)
    parser.add_argument("--live-prefetch-incident-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = evaluate_operational_detection(
        worker_results=tuple(args.worker_result),
        retry_plan=args.retry_plan.resolve(),
        worker_health=args.worker_health.resolve(),
        operational_overlay=(
            args.operational_overlay.resolve() if args.operational_overlay else None
        ),
        controlled_fault_evaluation=(
            args.controlled_fault_evaluation.resolve()
            if args.controlled_fault_evaluation
            else None
        ),
        live_prefetch_incident_evidence=(
            args.live_prefetch_incident_evidence.resolve()
            if args.live_prefetch_incident_evidence
            else None
        ),
        output_path=args.output.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["WorkerResult", "evaluate_operational_detection"]
