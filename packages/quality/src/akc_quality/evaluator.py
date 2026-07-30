"""Weighted gate with non-overlapping production thresholds."""

from __future__ import annotations

from collections.abc import Iterable

from .models import (
    FindingSeverity,
    QualityEvaluation,
    QualityFinding,
    QualityStatus,
    QualityVector,
)

NORMAL_WEIGHTS = {
    "text_fidelity": 0.22,
    "numeric_fidelity": 0.12,
    "layout_fidelity": 0.14,
    "table_fidelity": 0.12,
    "hierarchy_validity": 0.12,
    "provenance_coverage": 0.12,
    "repetition_safety": 0.07,
    "language_consistency": 0.05,
    "markdown_validity": 0.04,
}

HIGH_RISK_WEIGHTS = {
    "text_fidelity": 0.18,
    "numeric_fidelity": 0.22,
    "layout_fidelity": 0.10,
    "table_fidelity": 0.15,
    "hierarchy_validity": 0.08,
    "provenance_coverage": 0.15,
    "repetition_safety": 0.07,
    "language_consistency": 0.03,
    "markdown_validity": 0.02,
}


def weighted_quality(vector: QualityVector, *, high_risk: bool = False) -> float:
    weights = HIGH_RISK_WEIGHTS if high_risk else NORMAL_WEIGHTS
    values = vector.model_dump(mode="python", by_alias=False)
    active = {key: value for key, value in values.items() if value is not None}
    denominator = sum(weights[key] for key in active)
    if denominator == 0:
        return 0.0
    return sum(float(active[key]) * weights[key] for key in active) / denominator


def evaluate_quality(
    vector: QualityVector,
    *,
    findings: Iterable[QualityFinding] = (),
    high_risk: bool = False,
    failed_attempts: int = 0,
    hard_failure: bool = False,
) -> QualityEvaluation:
    materialized = tuple(findings)
    score = weighted_quality(vector, high_risk=high_risk)
    critical_count = sum(finding.severity == FindingSeverity.CRITICAL for finding in materialized)
    if hard_failure:
        status = QualityStatus.FAIL
    elif (
        critical_count
        or (high_risk and (vector.numeric_fidelity is None or vector.numeric_fidelity < 1.0))
        or failed_attempts >= 2
    ):
        status = QualityStatus.REVIEW_REQUIRED
    elif score >= 0.90:
        status = QualityStatus.PASS
    elif score >= 0.82:
        status = QualityStatus.PASS_WITH_WARNINGS
    else:
        status = QualityStatus.ESCALATE
    return QualityEvaluation(
        overall_score=score,
        status=status,
        vector=vector,
        findings=materialized,
        critical_finding_count=critical_count,
    )
