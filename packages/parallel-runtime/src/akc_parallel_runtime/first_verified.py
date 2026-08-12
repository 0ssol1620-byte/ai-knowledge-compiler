"""Deterministic first-verified arbitration with immutable tie-breaking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class VerifiedCandidate:
    attempt_id: str
    verified_at: datetime
    evidence_level: int
    hard_failure_count: int
    output_sha256: str


def select_first_verified(candidates: tuple[VerifiedCandidate, ...]) -> VerifiedCandidate | None:
    eligible = tuple(
        item for item in candidates if item.evidence_level >= 5 and item.hard_failure_count == 0
    )
    if any(item.verified_at.tzinfo is None for item in eligible):
        raise ValueError("verified_at must be timezone-aware")
    return min(eligible, key=lambda item: (item.verified_at, item.attempt_id)) if eligible else None


__all__ = ["VerifiedCandidate", "select_first_verified"]
