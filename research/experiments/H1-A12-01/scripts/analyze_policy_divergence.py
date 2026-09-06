"""Phase-0, zero-GPU policy-divergence analysis for H1-A12-01.

This script is deliberately incapable of claiming recovery quality. It accepts
per-case recovery-state rows, runs the existing fixed selector and the registered
cause-conditioned selector at the same decision point, and reports only how often
the selected next action differs and what each selected policy estimates it would
cost. Aggregate experiment metrics are rejected because they cannot reconstruct a
counterfactual policy decision.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from akc_cir.cause_conditioned_recovery import (
    classify_failure,
    operator_kind,
    select_cause_conditioned_recovery,
)
from akc_cir.inspection import FailureCode
from akc_cir.recovery_policy import (
    QualityMode,
    RecoveryAttempt,
    RecoveryBudget,
    RecoveryDecision,
    default_recovery_registry,
    select_recovery,
)

SCHEMA = "tavonel.h1-a12-policy-divergence.v1"


class InputContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CaseDecision:
    case_id: str
    failure_code: str
    failure_class: str
    fixed_outcome: str
    fixed_policy_signature: str | None
    fixed_operator_kind: str | None
    fixed_estimated_gpu_seconds: float
    fixed_estimated_cost_units: float
    cause_outcome: str
    cause_policy_signature: str | None
    cause_operator_kind: str | None
    cause_estimated_gpu_seconds: float
    cause_estimated_cost_units: float
    policy_diverged: bool


def _policy_fields(decision: RecoveryDecision) -> tuple[str | None, str | None, float, float]:
    policy = decision.policy
    if policy is None:
        return None, None, 0.0, 0.0
    return (
        policy.signature,
        operator_kind(policy).value,
        float(policy.estimated_gpu_seconds),
        float(policy.estimated_cost_units),
    )


def _attempt(value: Mapping[str, object]) -> RecoveryAttempt:
    required = {"policy_signature", "failure_signature"}
    missing = sorted(required - set(value))
    if missing:
        raise InputContractError(f"history attempt missing required field(s): {missing}")
    return RecoveryAttempt(
        policy_signature=str(value["policy_signature"]),
        failure_signature=str(value["failure_signature"]),
        succeeded=bool(value.get("succeeded", False)),
        gpu_seconds=float(value.get("gpu_seconds", 0.0)),
        cost_units=float(value.get("cost_units", 0.0)),
        wall_clock_seconds=float(value.get("wall_clock_seconds", 0.0)),
    )


def _mode(value: object) -> QualityMode:
    raw = str(value or QualityMode.VERIFIED.value).upper()
    try:
        return QualityMode(raw)
    except ValueError as exc:
        raise InputContractError(f"unsupported quality_mode: {raw}") from exc


def _budget(value: object) -> RecoveryBudget:
    if value is None:
        return RecoveryBudget()
    if not isinstance(value, Mapping):
        raise InputContractError("budget must be an object")
    return RecoveryBudget(
        max_attempts_per_page=int(value.get("max_attempts_per_page", 4)),
        max_gpu_seconds=float(value.get("max_gpu_seconds", 600.0)),
        max_wall_clock_seconds=float(value.get("max_wall_clock_seconds", 1800.0)),
        max_cost_units=float(value.get("max_cost_units", 100.0)),
        stop_on_same_failure_signature=bool(value.get("stop_on_same_failure_signature", True)),
    )


def analyze_case(row: Mapping[str, object]) -> CaseDecision:
    required = {"case_id", "failure_code", "failure_signature", "history"}
    missing = sorted(required - set(row))
    if missing:
        raise InputContractError(
            "per-case replay row required; aggregate metrics are not admissible. "
            f"missing field(s): {missing}"
        )
    if not isinstance(row["history"], list):
        raise InputContractError("history must be a list of observed RecoveryAttempt records")

    try:
        code = FailureCode(str(row["failure_code"]))
    except ValueError as exc:
        raise InputContractError(f"unknown failure_code: {row['failure_code']}") from exc

    history = tuple(_attempt(item) for item in row["history"] if isinstance(item, Mapping))
    if len(history) != len(row["history"]):
        raise InputContractError("every history item must be an object")

    registry = default_recovery_registry()
    mode = _mode(row.get("quality_mode"))
    budget = _budget(row.get("budget"))
    signature = str(row["failure_signature"])
    circuit_open = bool(row.get("circuit_open", False))

    fixed = select_recovery(
        code=code,
        failure_signature=signature,
        registry=registry,
        history=history,
        mode=mode,
        budget=budget,
        circuit_open=circuit_open,
    )
    cause = select_cause_conditioned_recovery(
        code=code,
        failure_signature=signature,
        registry=registry,
        history=history,
        mode=mode,
        budget=budget,
        circuit_open=circuit_open,
    )

    fixed_signature, fixed_operator, fixed_gpu, fixed_cost = _policy_fields(fixed)
    cause_signature, cause_operator, cause_gpu, cause_cost = _policy_fields(cause.decision)
    diverged = (
        fixed.outcome != cause.decision.outcome
        or fixed_signature != cause_signature
    )

    return CaseDecision(
        case_id=str(row["case_id"]),
        failure_code=code.value,
        failure_class=classify_failure(code).value,
        fixed_outcome=fixed.outcome.value,
        fixed_policy_signature=fixed_signature,
        fixed_operator_kind=fixed_operator,
        fixed_estimated_gpu_seconds=fixed_gpu,
        fixed_estimated_cost_units=fixed_cost,
        cause_outcome=cause.decision.outcome.value,
        cause_policy_signature=cause_signature,
        cause_operator_kind=cause_operator,
        cause_estimated_gpu_seconds=cause_gpu,
        cause_estimated_cost_units=cause_cost,
        policy_diverged=diverged,
    )


def analyze_records(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    decisions = [analyze_case(row) for row in rows]
    class_counts = Counter(item.failure_class for item in decisions)
    divergent = [item for item in decisions if item.policy_diverged]
    divergent_by_class = Counter(item.failure_class for item in divergent)
    estimated_fixed_gpu = sum(item.fixed_estimated_gpu_seconds for item in decisions)
    estimated_cause_gpu = sum(item.cause_estimated_gpu_seconds for item in decisions)
    estimated_fixed_cost = sum(item.fixed_estimated_cost_units for item in decisions)
    estimated_cause_cost = sum(item.cause_estimated_cost_units for item in decisions)

    return {
        "schema": SCHEMA,
        "phase": 0,
        "case_count": len(decisions),
        "failure_class_counts": dict(sorted(class_counts.items())),
        "policy_divergent_count": len(divergent),
        "policy_divergent_fraction": (
            len(divergent) / len(decisions) if decisions else 0.0
        ),
        "policy_divergent_by_failure_class": dict(sorted(divergent_by_class.items())),
        "selected_policy_estimates": {
            "fixed_gpu_seconds": estimated_fixed_gpu,
            "cause_conditioned_gpu_seconds": estimated_cause_gpu,
            "fixed_cost_units": estimated_fixed_cost,
            "cause_conditioned_cost_units": estimated_cause_cost,
        },
        "cases": [asdict(item) for item in decisions],
        "performance_conclusion_allowed": False,
        "counterfactual_recovery_outcomes_observed": False,
        "interpretation": (
            "Phase 0 measures selector divergence and selected-policy metadata only. "
            "It cannot determine which unexecuted recovery action would have succeeded."
        ),
    }


def read_jsonl(path: Path) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, Mapping):
            raise InputContractError(f"line {line_number}: each JSONL row must be an object")
        rows.append(value)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    result = analyze_records(read_jsonl(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"H1-A12-01 phase0: {result['case_count']} cases, "
        f"{result['policy_divergent_count']} divergent; PERFORMANCE CLAIMS DISALLOWED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
