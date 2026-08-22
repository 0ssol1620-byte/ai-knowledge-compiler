"""Finite-sample conformal risk thresholds with explicit abstention."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True, slots=True)
class ConformalCalibration:
    threshold: float
    alpha: float
    calibration_count: int
    accepted_count: int
    empirical_error_rate: float


def calibrate_conformal_threshold(
    scored_outcomes: tuple[tuple[float, bool], ...], *, alpha: float
) -> ConformalCalibration:
    """Select the most permissive threshold whose accepted empirical risk fits alpha."""

    if not scored_outcomes:
        raise ValueError("conformal calibration requires held-out outcomes")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    if any(not 0 <= score <= 1 for score, _ in scored_outcomes):
        raise ValueError("scores must be between zero and one")
    candidates = sorted({score for score, _ in scored_outcomes}, reverse=True)
    selected: tuple[float, int, float] | None = None
    for threshold in candidates:
        accepted = tuple(correct for score, correct in scored_outcomes if score >= threshold)
        errors = sum(not correct for correct in accepted)
        # The +1 finite-sample correction prevents a tiny perfect sample from
        # certifying a zero-risk production route.
        corrected_risk = (errors + 1) / (len(accepted) + 1)
        if corrected_risk <= alpha:
            selected = (threshold, len(accepted), errors / len(accepted))
    if selected is None:
        return ConformalCalibration(1.0, alpha, len(scored_outcomes), 0, 0.0)
    threshold, accepted_count, empirical_error_rate = selected
    rank_floor = ceil((len(scored_outcomes) + 1) * (1 - alpha))
    if accepted_count < rank_floor:
        return ConformalCalibration(1.0, alpha, len(scored_outcomes), 0, 0.0)
    return ConformalCalibration(
        threshold,
        alpha,
        len(scored_outcomes),
        accepted_count,
        empirical_error_rate,
    )


def conformal_accept(score: float, calibration: ConformalCalibration) -> bool:
    if not 0 <= score <= 1:
        raise ValueError("score must be between zero and one")
    return calibration.accepted_count > 0 and score >= calibration.threshold


__all__ = ["ConformalCalibration", "calibrate_conformal_threshold", "conformal_accept"]
