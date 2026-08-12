"""Quality drift detection with a rollback-first disposition."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DriftDecision:
    drifted: bool
    rollback_required: bool
    relative_change: float
    reason_code: str


def detect_quality_drift(
    *, baseline: float, observed: float, maximum_relative_drop: float
) -> DriftDecision:
    if baseline <= 0 or not 0 <= observed <= 1 or not 0 <= maximum_relative_drop < 1:
        raise ValueError("invalid drift inputs")
    relative_change = (observed - baseline) / baseline
    drifted = relative_change < -maximum_relative_drop
    return DriftDecision(
        drifted,
        drifted,
        relative_change,
        "quality_drift_rollback" if drifted else "quality_within_control_limit",
    )


__all__ = ["DriftDecision", "detect_quality_drift"]
