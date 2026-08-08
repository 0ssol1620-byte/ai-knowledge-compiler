"""Build one fail-closed recovery/detector/adaptive-repeat evidence receipt."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmark.v6.contracts import canonical_sha256
from benchmark.v6.failure_detection import (
    FailureLabel,
    FailurePrediction,
    evaluate_failure_detection,
)
from benchmark.v6.recovery_campaign import RecoveryCaseResult, evaluate_recovery_campaign
from benchmark.v6.repeats import RepeatObservation, RepeatScope, evaluate_adaptive_repeats


def evaluate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    labels = tuple(
        FailureLabel(
            item_id=str(item["item_id"]),
            failure_codes=frozenset(str(code) for code in item["failure_codes"]),
            scope_level=_optional_string(item.get("scope_level")),
            scope_id=_optional_string(item.get("scope_id")),
            should_recover=bool(item["should_recover"]),
            should_escalate=bool(item.get("should_escalate", False)),
        )
        for item in payload["failure_labels"]
    )
    predictions = tuple(
        FailurePrediction(
            item_id=str(item["item_id"]),
            failure_codes=frozenset(str(code) for code in item["failure_codes"]),
            scope_level=_optional_string(item.get("scope_level")),
            scope_id=_optional_string(item.get("scope_id")),
            request_recovery=bool(item["request_recovery"]),
            escalate=bool(item.get("escalate", False)),
        )
        for item in payload["failure_predictions"]
    )
    cases = tuple(
        RecoveryCaseResult(
            item_id=str(item["item_id"]),
            initial_correct=bool(item["initial_correct"]),
            selective_final_correct=bool(item["selective_final_correct"]),
            full_replay_correct=bool(item["full_replay_correct"]),
            recovery_attempted=bool(item["recovery_attempted"]),
            recovery_verified=bool(item["recovery_verified"]),
            critical_failure=bool(item.get("critical_failure", False)),
            selective_latency_seconds=float(item["selective_latency_seconds"]),
            full_replay_latency_seconds=float(item["full_replay_latency_seconds"]),
            selective_cost=float(item["selective_cost"]),
            full_replay_cost=float(item["full_replay_cost"]),
        )
        for item in payload["recovery_cases"]
    )
    repeats = tuple(
        RepeatObservation(
            run_id=str(item["run_id"]),
            candidate_id=str(item["candidate_id"]),
            benchmark_id=str(item["benchmark_id"]),
            environment_sha256=str(item["environment_sha256"]),
            scope=RepeatScope(str(item["scope"])),
            prediction_hashes=tuple(
                (str(pair[0]), str(pair[1])) for pair in item["prediction_hashes"]
            ),
            score=float(item["score"]),
            failure_count=int(item.get("failure_count", 0)),
        )
        for item in payload["repeat_observations"]
    )
    _validate_payload_binding(payload, labels, cases, repeats)
    detection = evaluate_failure_detection(labels, predictions)
    recovery = evaluate_recovery_campaign(
        cases,
        maximum_accuracy_loss_vs_full_replay=float(
            payload.get("maximum_accuracy_loss_vs_full_replay", 0)
        ),
    )
    repeat_decision = evaluate_adaptive_repeats(
        repeats,
        finalist=bool(payload["finalist"]),
        score_tolerance=float(payload.get("score_tolerance", 0)),
    )
    gate_passed = detection.gate_passed and recovery.gate_passed and repeat_decision.gate_complete
    receipt = {
        "schema": "folynta.recovery-campaign-evidence.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "candidate_id": str(payload["candidate_id"]),
        "benchmark_id": str(payload["benchmark_id"]),
        "evidence_class": str(payload.get("evidence_class", "unspecified")),
        "failure_detection": detection.to_dict(),
        "recovery": recovery.to_dict(),
        "adaptive_repeats": {
            "required_full_runs": repeat_decision.required_full_runs,
            "required_audit_runs": repeat_decision.required_audit_runs,
            "additional_full_runs": repeat_decision.additional_full_runs,
            "additional_audit_runs": repeat_decision.additional_audit_runs,
            "deterministic": repeat_decision.deterministic,
            "gate_complete": repeat_decision.gate_complete,
            "reason_codes": list(repeat_decision.reason_codes),
        },
        "gate": "PASS" if gate_passed else "FAIL",
        "claim_boundary": (
            "This receipt measures only the supplied frozen cases and repeat observations; "
            "it is not public-core or private-holdout evidence unless those exact inputs are bound."
        ),
        "input_claim_boundary": _optional_string(payload.get("claim_boundary")),
        "input_sha256": canonical_sha256(payload),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _validate_payload_binding(
    payload: dict[str, Any],
    labels: tuple[FailureLabel, ...],
    cases: tuple[RecoveryCaseResult, ...],
    repeats: tuple[RepeatObservation, ...],
) -> None:
    candidate_id = str(payload["candidate_id"])
    benchmark_id = str(payload["benchmark_id"])
    if any(item.candidate_id != candidate_id for item in repeats):
        raise ValueError("repeat candidate_id does not match receipt candidate_id")
    if any(item.benchmark_id != benchmark_id for item in repeats):
        raise ValueError("repeat benchmark_id does not match receipt benchmark_id")
    label_ids = {item.item_id for item in labels}
    case_ids = {item.item_id for item in cases}
    if case_ids != label_ids:
        raise ValueError("recovery case ids must exactly match failure label ids")
    full_run_ids = {
        item_id
        for repeat in repeats
        if repeat.scope is RepeatScope.FULL
        for item_id, _digest in repeat.prediction_hashes
    }
    if full_run_ids != label_ids:
        raise ValueError("full repeat observations must cover every labeled item exactly")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    receipt = evaluate_payload(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if receipt["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
