"""Paired before/after metrics for selective recovery versus full replay."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecoveryCaseResult:
    item_id: str
    initial_correct: bool
    selective_final_correct: bool
    full_replay_correct: bool
    recovery_attempted: bool
    recovery_verified: bool
    critical_failure: bool
    selective_latency_seconds: float
    full_replay_latency_seconds: float
    selective_cost: float
    full_replay_cost: float

    def __post_init__(self) -> None:
        if not self.item_id:
            raise ValueError("recovery case item_id is required")
        if min(
            self.selective_latency_seconds,
            self.full_replay_latency_seconds,
            self.selective_cost,
            self.full_replay_cost,
        ) < 0:
            raise ValueError("recovery latency and cost cannot be negative")
        if self.recovery_verified and not self.recovery_attempted:
            raise ValueError("unattempted recovery cannot be verified")


@dataclass(frozen=True, slots=True)
class RecoveryCampaignMetrics:
    item_count: int
    initial_accuracy: float
    selective_final_accuracy: float
    full_replay_accuracy: float
    absolute_uplift: float
    accepted_precision: float
    verified_coverage: float
    unresolved_rate: float
    recovery_yield: float
    repair_induced_error_rate: float
    false_verified_count: int
    critical_failure_count: int
    selective_latency_seconds: float
    full_replay_latency_seconds: float
    latency_saved_ratio: float
    selective_cost: float
    full_replay_cost: float
    cost_saved_ratio: float
    selective_accuracy_delta_vs_full_replay: float
    gate_passed: bool

    def to_dict(self) -> dict[str, int | float | bool]:
        return {
            "item_count": self.item_count,
            "initial_accuracy": self.initial_accuracy,
            "selective_final_accuracy": self.selective_final_accuracy,
            "full_replay_accuracy": self.full_replay_accuracy,
            "absolute_uplift": self.absolute_uplift,
            "accepted_precision": self.accepted_precision,
            "verified_coverage": self.verified_coverage,
            "unresolved_rate": self.unresolved_rate,
            "recovery_yield": self.recovery_yield,
            "repair_induced_error_rate": self.repair_induced_error_rate,
            "false_verified_count": self.false_verified_count,
            "critical_failure_count": self.critical_failure_count,
            "selective_latency_seconds": self.selective_latency_seconds,
            "full_replay_latency_seconds": self.full_replay_latency_seconds,
            "latency_saved_ratio": self.latency_saved_ratio,
            "selective_cost": self.selective_cost,
            "full_replay_cost": self.full_replay_cost,
            "cost_saved_ratio": self.cost_saved_ratio,
            "selective_accuracy_delta_vs_full_replay": (
                self.selective_accuracy_delta_vs_full_replay
            ),
            "gate_passed": self.gate_passed,
        }


def evaluate_recovery_campaign(
    cases: tuple[RecoveryCaseResult, ...],
    *,
    maximum_accuracy_loss_vs_full_replay: float = 0.0,
) -> RecoveryCampaignMetrics:
    if not cases:
        raise ValueError("recovery campaign requires cases")
    if maximum_accuracy_loss_vs_full_replay < 0:
        raise ValueError("maximum accuracy loss cannot be negative")
    ids = [case.item_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("recovery campaign item ids must be unique")

    initial_correct = sum(case.initial_correct for case in cases)
    selective_correct = sum(case.selective_final_correct for case in cases)
    full_correct = sum(case.full_replay_correct for case in cases)
    recoverable = tuple(case for case in cases if not case.initial_correct)
    recovered = sum(case.selective_final_correct for case in recoverable)
    initially_correct = tuple(case for case in cases if case.initial_correct)
    induced_errors = sum(not case.selective_final_correct for case in initially_correct)
    false_verified = sum(
        case.recovery_verified and not case.selective_final_correct for case in cases
    )
    critical_failures = sum(case.critical_failure for case in cases)
    accepted = tuple(
        case
        for case in cases
        if case.recovery_verified
        or (case.initial_correct and not case.recovery_attempted)
    )
    accepted_correct = sum(case.selective_final_correct for case in accepted)
    count = len(cases)
    initial_accuracy = initial_correct / count
    selective_accuracy = selective_correct / count
    full_accuracy = full_correct / count
    selective_latency = sum(case.selective_latency_seconds for case in cases)
    full_latency = sum(case.full_replay_latency_seconds for case in cases)
    selective_cost = sum(case.selective_cost for case in cases)
    full_cost = sum(case.full_replay_cost for case in cases)
    accuracy_delta = selective_accuracy - full_accuracy
    return RecoveryCampaignMetrics(
        item_count=count,
        initial_accuracy=initial_accuracy,
        selective_final_accuracy=selective_accuracy,
        full_replay_accuracy=full_accuracy,
        absolute_uplift=selective_accuracy - initial_accuracy,
        accepted_precision=_ratio(accepted_correct, len(accepted)),
        verified_coverage=_ratio(len(accepted), count),
        unresolved_rate=_ratio(count - len(accepted), count),
        recovery_yield=_ratio(recovered, len(recoverable)),
        repair_induced_error_rate=_ratio(induced_errors, len(initially_correct)),
        false_verified_count=false_verified,
        critical_failure_count=critical_failures,
        selective_latency_seconds=selective_latency,
        full_replay_latency_seconds=full_latency,
        latency_saved_ratio=_saved_ratio(selective_latency, full_latency),
        selective_cost=selective_cost,
        full_replay_cost=full_cost,
        cost_saved_ratio=_saved_ratio(selective_cost, full_cost),
        selective_accuracy_delta_vs_full_replay=accuracy_delta,
        gate_passed=(
            false_verified == 0
            and critical_failures == 0
            and induced_errors == 0
            and accuracy_delta >= -maximum_accuracy_loss_vs_full_replay
            and selective_latency <= full_latency
            and selective_cost <= full_cost
        ),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _saved_ratio(selective: float, full: float) -> float:
    return (full - selective) / full if full else 0.0


__all__ = [
    "RecoveryCampaignMetrics",
    "RecoveryCaseResult",
    "evaluate_recovery_campaign",
]
