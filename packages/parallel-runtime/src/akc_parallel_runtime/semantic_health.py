"""Semantic health policy independent from infrastructure liveness."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SemanticState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DRAINING = "DRAINING"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True, slots=True)
class SemanticHealthDecision:
    state: SemanticState
    allow_new_work: bool
    replay_inflight: bool
    reason_code: str


def decide_semantic_health(
    *, canary_score: float, consecutive_failures: int, infrastructure_healthy: bool
) -> SemanticHealthDecision:
    if not 0 <= canary_score <= 1 or consecutive_failures < 0:
        raise ValueError("invalid semantic health observation")
    if not infrastructure_healthy:
        return SemanticHealthDecision(
            SemanticState.DRAINING, False, True, "infrastructure_degraded"
        )
    if consecutive_failures >= 3 or canary_score < 0.8:
        return SemanticHealthDecision(
            SemanticState.QUARANTINED, False, True, "semantic_canary_failed"
        )
    if consecutive_failures or canary_score < 0.95:
        return SemanticHealthDecision(
            SemanticState.DEGRADED, False, False, "semantic_canary_degraded"
        )
    return SemanticHealthDecision(SemanticState.HEALTHY, True, False, "semantic_canary_healthy")


__all__ = ["SemanticHealthDecision", "SemanticState", "decide_semantic_health"]
