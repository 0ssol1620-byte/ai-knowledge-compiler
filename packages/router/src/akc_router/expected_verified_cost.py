"""Expected verified cost routing; raw inference cost is never the objective."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RouteCostCandidate:
    route_id: str
    inference_cost: float
    verification_cost: float
    recovery_probability: float
    recovery_cost: float
    critical_failure_probability: float
    critical_failure_penalty: float

    @property
    def expected_verified_cost(self) -> float:
        return (
            self.inference_cost
            + self.verification_cost
            + self.recovery_probability * self.recovery_cost
            + self.critical_failure_probability * self.critical_failure_penalty
        )


def select_expected_verified_cost(
    candidates: tuple[RouteCostCandidate, ...], *, maximum_critical_failure_probability: float
) -> RouteCostCandidate | None:
    if not 0 <= maximum_critical_failure_probability <= 1:
        raise ValueError("invalid critical failure bound")
    eligible = tuple(
        item
        for item in candidates
        if item.critical_failure_probability <= maximum_critical_failure_probability
    )
    return (
        min(eligible, key=lambda item: (item.expected_verified_cost, item.route_id))
        if eligible
        else None
    )


__all__ = ["RouteCostCandidate", "select_expected_verified_cost"]
