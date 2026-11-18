"""Crop-verifier (Jev) contract: HOLD states, sentinels, explicit fallback.

A verifier score never overrides a hard gate, never accepts without a
calibration, and an unavailable verifier is recorded as OFF, not accepted.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from akc_quality.conformal_risk import ConformalCalibration, conformal_accept

VerifierState = Literal[
    "SCORED",
    "HOLD_MISSING_CROP",
    "HOLD_RENDERER_MISMATCH",
    "HOLD_SENTINEL_FAILED",
    "HOLD_INVALID_OUTPUT",
    "OFF",
]
Policy = Literal["jev_on", "jev_off"]
FALLBACK_JEV_OFF = "jev_off_policy"


@dataclass(frozen=True, slots=True)
class VerifierRequest:
    region_id: str
    crop_sha256: str | None
    renderer_id: str
    renderer_version: str
    candidate_text: str
    region_kind: str


@dataclass(frozen=True, slots=True)
class VerifierResult:
    state: VerifierState
    score: float | None
    verifier_id: str
    revision: str
    fallback: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    accepted: bool
    reason: str
    fallback: str | None = None


def build_result(
    request: VerifierRequest,
    raw_score: object,
    *,
    calibrated_renderer: tuple[str, str],
    verifier_id: str,
    revision: str,
) -> VerifierResult:
    """Map a raw verifier output to a result; every failure becomes a HOLD."""

    def hold(state: VerifierState) -> VerifierResult:
        return VerifierResult(state, None, verifier_id, revision)

    if not request.crop_sha256:
        return hold("HOLD_MISSING_CROP")
    if (request.renderer_id, request.renderer_version) != calibrated_renderer:
        return hold("HOLD_RENDERER_MISMATCH")
    if (
        isinstance(raw_score, bool)
        or not isinstance(raw_score, (int, float))
        or not math.isfinite(raw_score)
        or not 0 <= raw_score <= 1
    ):
        return hold("HOLD_INVALID_OUTPUT")
    return VerifierResult("SCORED", float(raw_score), verifier_id, revision)


def off_result(verifier_id: str, revision: str) -> VerifierResult:
    """The verifier is unavailable: say so, and name the fallback policy."""

    return VerifierResult("OFF", None, verifier_id, revision, FALLBACK_JEV_OFF)


def check_sentinels(
    batch_results: Mapping[str, VerifierResult],
    *,
    match_ids: Sequence[str],
    mismatch_ids: Sequence[str],
) -> dict[str, VerifierResult]:
    """Hold the whole batch unless every mismatch sentinel scores below every match sentinel."""

    def scores(ids: Sequence[str]) -> list[float | None]:
        return [
            r.score if (r := batch_results.get(i)) is not None and r.state == "SCORED" else None
            for i in ids
        ]

    matches = scores(match_ids)
    mismatches = scores(mismatch_ids)
    match_floor = [m for m in matches if m is not None]
    mismatch_ceiling = [m for m in mismatches if m is not None]
    ok = (
        bool(matches)
        and bool(mismatches)
        and len(match_floor) == len(matches)
        and len(mismatch_ceiling) == len(mismatches)
        and max(mismatch_ceiling) < min(match_floor)
    )
    if ok:
        return dict(batch_results)
    return {
        region_id: replace(result, state="HOLD_SENTINEL_FAILED", score=None)
        for region_id, result in batch_results.items()
    }


def decide(
    hard_gates_passed: bool,
    result: VerifierResult,
    calibration: ConformalCalibration | None,
    policy: Policy,
) -> Decision:
    if not hard_gates_passed:
        return Decision(False, "hard_gate_failed")
    if policy == "jev_off":
        return Decision(True, "hard_gates_passed_jev_off")
    if calibration is None:
        raise ValueError("jev_on requires a calibration; refusing to accept without one")
    if result.state == "OFF":
        return Decision(True, "verifier_off", result.fallback or FALLBACK_JEV_OFF)
    if result.state != "SCORED" or result.score is None:
        return Decision(False, result.state.lower())
    if conformal_accept(result.score, calibration):
        return Decision(True, "score_above_threshold")
    return Decision(False, "score_below_threshold")


__all__ = [
    "Decision",
    "VerifierRequest",
    "VerifierResult",
    "build_result",
    "check_sentinels",
    "decide",
    "off_result",
]
