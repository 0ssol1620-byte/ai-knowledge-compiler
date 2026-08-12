"""Ground-truth evaluation for failure detection, localization, and recovery decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class _HasItemId(Protocol):
    @property
    def item_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class FailureLabel:
    item_id: str
    failure_codes: frozenset[str]
    scope_level: str | None
    scope_id: str | None
    should_recover: bool
    should_escalate: bool = False

    def __post_init__(self) -> None:
        if not self.item_id:
            raise ValueError("failure label item_id is required")
        if bool(self.scope_level) != bool(self.scope_id):
            raise ValueError("scope_level and scope_id must be declared together")
        if not self.failure_codes and self.should_recover:
            raise ValueError("healthy labels cannot require recovery")


@dataclass(frozen=True, slots=True)
class FailurePrediction:
    item_id: str
    failure_codes: frozenset[str]
    scope_level: str | None
    scope_id: str | None
    request_recovery: bool
    escalate: bool = False

    def __post_init__(self) -> None:
        if not self.item_id:
            raise ValueError("failure prediction item_id is required")
        if bool(self.scope_level) != bool(self.scope_id):
            raise ValueError("scope_level and scope_id must be declared together")


@dataclass(frozen=True, slots=True)
class FailureDetectionMetrics:
    item_count: int
    healthy_item_count: int
    faulty_item_count: int
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    f1: float
    type_exact_accuracy: float
    localization_exact_accuracy: float
    minimal_scope_accuracy: float
    recovery_decision_accuracy: float
    escalation_accuracy: float
    silent_omission_rate: float
    false_recovery_rate: float
    gate_passed: bool

    def to_dict(self) -> dict[str, int | float | bool]:
        return {
            "item_count": self.item_count,
            "healthy_item_count": self.healthy_item_count,
            "faulty_item_count": self.faulty_item_count,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "type_exact_accuracy": self.type_exact_accuracy,
            "localization_exact_accuracy": self.localization_exact_accuracy,
            "minimal_scope_accuracy": self.minimal_scope_accuracy,
            "recovery_decision_accuracy": self.recovery_decision_accuracy,
            "escalation_accuracy": self.escalation_accuracy,
            "silent_omission_rate": self.silent_omission_rate,
            "false_recovery_rate": self.false_recovery_rate,
            "gate_passed": self.gate_passed,
        }


def evaluate_failure_detection(
    labels: tuple[FailureLabel, ...],
    predictions: tuple[FailurePrediction, ...],
) -> FailureDetectionMetrics:
    """Evaluate detector output without treating missing predictions as healthy evidence."""

    if not labels:
        raise ValueError("failure detection evaluation requires labels")
    label_map = _unique(labels, "label")
    prediction_map = _unique(predictions, "prediction")
    unknown = set(prediction_map) - set(label_map)
    if unknown:
        raise ValueError(f"predictions contain unknown item ids: {sorted(unknown)}")

    true_positive = false_positive = false_negative = 0
    type_exact = localization_exact = minimal_scope_exact = escalation_exact = 0
    recovery_decision_exact = 0
    faulty_items = healthy_items = recoverable_items = nonrecoverable_items = 0
    silent_omissions = false_recoveries = 0
    for item_id, label in label_map.items():
        prediction = prediction_map.get(
            item_id,
            FailurePrediction(item_id, frozenset(), None, None, False, False),
        )
        expected = label.failure_codes
        actual = prediction.failure_codes
        true_positive += len(expected & actual)
        false_positive += len(actual - expected)
        false_negative += len(expected - actual)
        type_exact += int(expected == actual)
        escalation_exact += int(label.should_escalate == prediction.escalate)
        recovery_decision_exact += int(
            label.should_recover == prediction.request_recovery
        )
        if label.should_recover:
            recoverable_items += 1
            silent_omissions += int(not actual or not prediction.request_recovery)
        else:
            nonrecoverable_items += 1
            false_recoveries += int(prediction.request_recovery)
        if expected:
            faulty_items += 1
            scope_matches = (
                label.scope_level == prediction.scope_level
                and label.scope_id == prediction.scope_id
            )
            localization_exact += int(scope_matches)
            minimal_scope_exact += int(
                scope_matches
                and label.should_recover == prediction.request_recovery
            )
        else:
            healthy_items += 1

    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    f1 = _ratio(2 * precision * recall, precision + recall)
    return FailureDetectionMetrics(
        item_count=len(labels),
        healthy_item_count=healthy_items,
        faulty_item_count=faulty_items,
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        precision=precision,
        recall=recall,
        f1=f1,
        type_exact_accuracy=_ratio(type_exact, len(labels)),
        localization_exact_accuracy=_ratio(localization_exact, faulty_items),
        minimal_scope_accuracy=_ratio(minimal_scope_exact, faulty_items),
        recovery_decision_accuracy=_ratio(recovery_decision_exact, len(labels)),
        escalation_accuracy=_ratio(escalation_exact, len(labels)),
        silent_omission_rate=_ratio(silent_omissions, recoverable_items),
        false_recovery_rate=_ratio(false_recoveries, nonrecoverable_items),
        gate_passed=(
            false_positive == 0
            and false_negative == 0
            and type_exact == len(labels)
            and localization_exact == faulty_items
            and minimal_scope_exact == faulty_items
            and recovery_decision_exact == len(labels)
            and escalation_exact == len(labels)
            and silent_omissions == 0
            and false_recoveries == 0
        ),
    )


def _unique[Item: _HasItemId](items: tuple[Item, ...], kind: str) -> dict[str, Item]:
    result: dict[str, Item] = {}
    for item in items:
        item_id = item.item_id
        if item_id in result:
            raise ValueError(f"duplicate {kind} item id: {item_id}")
        result[item_id] = item
    return result


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


__all__ = [
    "FailureDetectionMetrics",
    "FailureLabel",
    "FailurePrediction",
    "evaluate_failure_detection",
]
