"""ValidationEvidence ladder, hard gates, and selective-verification metrics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum


class EvidenceLevel(IntEnum):
    NONE = 0
    OUTPUT_EXISTS = 1
    SCHEMA_VALID = 2
    SOURCE_LOCATED = 3
    SOURCE_HASHED = 4
    BLOCK_ANCHORED = 5
    CROSS_CHECKED = 6
    AUTHORITY_MATCHED = 7
    INDEPENDENTLY_VERIFIED = 8
    REPAIR_REVERIFIED = 9
    PACKAGE_ATTESTED = 10


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    evidence_id: str
    level: EvidenceLevel
    source_ids: tuple[str, ...]
    finding_ids: tuple[str, ...] = ()
    source_hashes: tuple[str, ...] = ()
    hard_gate_failures: tuple[str, ...] = ()
    repair_attempt_id: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("evidence id is required")
        if self.level >= EvidenceLevel.SOURCE_LOCATED and not self.source_ids:
            raise ValueError("source-located evidence requires a source")
        if self.level >= EvidenceLevel.SOURCE_HASHED and not self.source_hashes:
            raise ValueError("source-hashed evidence requires a source hash")
        if self.level >= EvidenceLevel.REPAIR_REVERIFIED and not self.repair_attempt_id:
            raise ValueError("repair-reverified evidence requires a repair attempt")


@dataclass(frozen=True, slots=True)
class EvidencePolicy:
    minimum_level: EvidenceLevel
    minimum_independent_sources: int = 1
    forbidden_hard_gates: tuple[str, ...] = (
        "critical_numeric_mismatch",
        "page_omission",
        "source_anchor_missing",
        "schema_invalid",
    )

    def __post_init__(self) -> None:
        if self.minimum_independent_sources < 1:
            raise ValueError("at least one independent source is required")


@dataclass(frozen=True, slots=True)
class EvidenceDecision:
    accepted: bool
    disposition: str
    reason_codes: tuple[str, ...]
    attained_level: EvidenceLevel


def verify_evidence(
    evidence: ValidationEvidence, policy: EvidencePolicy
) -> EvidenceDecision:
    reasons: list[str] = []
    forbidden = sorted(set(evidence.hard_gate_failures) & set(policy.forbidden_hard_gates))
    if forbidden:
        reasons.extend(f"hard_gate:{name}" for name in forbidden)
    if evidence.level < policy.minimum_level:
        reasons.append("evidence_level_insufficient")
    independent_sources = len(set(evidence.source_ids))
    if independent_sources < policy.minimum_independent_sources:
        reasons.append("independent_source_count_insufficient")
    accepted = not reasons
    return EvidenceDecision(
        accepted=accepted,
        disposition="accept" if accepted else "escalate",
        reason_codes=tuple(reasons or ("evidence_policy_satisfied",)),
        attained_level=evidence.level,
    )


@dataclass(frozen=True, slots=True)
class SelectivePrediction:
    confidence: float
    correct: bool

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class RiskCoveragePoint:
    threshold: float
    coverage: float
    risk: float | None
    accepted_count: int


def risk_coverage_curve(
    predictions: Iterable[SelectivePrediction], *, thresholds: Iterable[float]
) -> tuple[RiskCoveragePoint, ...]:
    observed = tuple(predictions)
    if not observed:
        raise ValueError("risk-coverage requires predictions")
    points: list[RiskCoveragePoint] = []
    for threshold in thresholds:
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between zero and one")
        accepted = [item for item in observed if item.confidence >= threshold]
        risk = (
            sum(not item.correct for item in accepted) / len(accepted)
            if accepted
            else None
        )
        points.append(
            RiskCoveragePoint(
                threshold=threshold,
                coverage=len(accepted) / len(observed),
                risk=risk,
                accepted_count=len(accepted),
            )
        )
    return tuple(points)


__all__ = [
    "EvidenceDecision",
    "EvidenceLevel",
    "EvidencePolicy",
    "RiskCoveragePoint",
    "SelectivePrediction",
    "ValidationEvidence",
    "risk_coverage_curve",
    "verify_evidence",
]
