"""Fail-closed final quality metrics for publish and package decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FinalDisposition(StrEnum):
    VERIFIED = "verified"
    RECOVERED_VERIFIED = "recovered_verified"
    UNRESOLVED = "unresolved"
    EXCLUDED = "excluded"


@dataclass(frozen=True, slots=True)
class FinalMetricInput:
    disposition: FinalDisposition
    critical_error: bool = False
    source_linked: bool = True
    publishable: bool = True


@dataclass(frozen=True, slots=True)
class FinalMetrics:
    total_count: int
    verified_count: int
    recovered_verified_count: int
    unresolved_count: int
    excluded_count: int
    critical_false_verified_count: int
    silent_omission_count: int
    verified_coverage: float
    accepted_precision: float | None
    publishable: bool
    reason_codes: tuple[str, ...]


def calculate_final_metrics(items: tuple[FinalMetricInput, ...]) -> FinalMetrics:
    """Aggregate terminal states without treating abstention as correctness.

    Empty inputs and unlinked accepted outputs fail closed. Excluded items stay in
    the denominator so a router cannot inflate coverage by silently dropping them.
    """

    if not items:
        return FinalMetrics(
            total_count=0,
            verified_count=0,
            recovered_verified_count=0,
            unresolved_count=0,
            excluded_count=0,
            critical_false_verified_count=0,
            silent_omission_count=0,
            verified_coverage=0.0,
            accepted_precision=None,
            publishable=False,
            reason_codes=("empty_evaluation",),
        )
    verified = sum(item.disposition is FinalDisposition.VERIFIED for item in items)
    recovered = sum(item.disposition is FinalDisposition.RECOVERED_VERIFIED for item in items)
    unresolved = sum(item.disposition is FinalDisposition.UNRESOLVED for item in items)
    excluded = sum(item.disposition is FinalDisposition.EXCLUDED for item in items)
    accepted = tuple(
        item
        for item in items
        if item.disposition in {FinalDisposition.VERIFIED, FinalDisposition.RECOVERED_VERIFIED}
    )
    critical_false_verified = sum(item.critical_error for item in accepted)
    silent_omissions = sum((not item.source_linked) or (not item.publishable) for item in accepted)
    accepted_correct = len(accepted) - critical_false_verified - silent_omissions
    precision = accepted_correct / len(accepted) if accepted else None
    coverage = len(accepted) / len(items)
    reasons: list[str] = []
    if critical_false_verified:
        reasons.append("critical_false_verified")
    if silent_omissions:
        reasons.append("accepted_output_without_publish_proof")
    if unresolved:
        reasons.append("unresolved_output_present")
    if excluded:
        reasons.append("excluded_output_present")
    if coverage < 0.99:
        reasons.append("verified_coverage_below_0_99")
    if precision is None or precision < 0.9999:
        reasons.append("accepted_precision_below_0_9999")
    return FinalMetrics(
        total_count=len(items),
        verified_count=verified,
        recovered_verified_count=recovered,
        unresolved_count=unresolved,
        excluded_count=excluded,
        critical_false_verified_count=critical_false_verified,
        silent_omission_count=silent_omissions,
        verified_coverage=coverage,
        accepted_precision=precision,
        publishable=not reasons,
        reason_codes=tuple(reasons or ("publish_gate_satisfied",)),
    )


__all__ = [
    "FinalDisposition",
    "FinalMetricInput",
    "FinalMetrics",
    "calculate_final_metrics",
]
