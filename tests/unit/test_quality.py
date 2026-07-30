from __future__ import annotations

import pytest
from akc_quality import (
    FindingSeverity,
    QualityFinding,
    QualityStatus,
    QualityVector,
    compare_engine_outputs,
    compare_numeric_tokens,
    evaluate_quality,
    repeated_ngram_ratio,
)


def vector(score: float, *, numeric: float | None = None) -> QualityVector:
    numeric_score = score if numeric is None else numeric
    return QualityVector(
        text_fidelity=score,
        numeric_fidelity=numeric_score,
        layout_fidelity=score,
        table_fidelity=score,
        hierarchy_validity=score,
        provenance_coverage=score,
        repetition_safety=score,
        language_consistency=score,
        markdown_validity=score,
    )


def test_quality_boundary_has_no_overlap() -> None:
    assert evaluate_quality(vector(0.90)).status == QualityStatus.PASS
    assert evaluate_quality(vector(0.899999)).status == QualityStatus.PASS_WITH_WARNINGS
    assert evaluate_quality(vector(0.819999)).status == QualityStatus.ESCALATE


def test_high_risk_requires_perfect_numeric_fidelity() -> None:
    assert (
        evaluate_quality(vector(0.99, numeric=0.999), high_risk=True).status
        == QualityStatus.REVIEW_REQUIRED
    )


def test_critical_finding_overrides_high_score() -> None:
    finding = QualityFinding(
        code="numeric.mismatch",
        severity=FindingSeverity.CRITICAL,
        message="Amount differs.",
    )
    assert (
        evaluate_quality(vector(0.99), findings=(finding,)).status == QualityStatus.REVIEW_REQUIRED
    )


def test_numeric_comparison_preserves_sign_decimal_and_leading_zero() -> None:
    exact = compare_numeric_tokens("계정 001, 증감 -2.50%, 총액 ₩1,000", "001 -2.50% ₩1,000")
    assert exact.score == 1.0
    mismatch = compare_numeric_tokens("001 -2.50", "1 2.50")
    assert mismatch.score < 1.0
    assert mismatch.missing_tokens


def test_semantic_similarity_never_masks_numeric_mismatch() -> None:
    agreement = compare_engine_outputs(
        "매출은 10% 증가했다.",
        "매출은 100% 증가했다.",
        semantic_similarity=0.999,
    )
    assert agreement.semantic_similarity == 0.999
    assert agreement.numeric_token_match == 0.0


def test_repetition_detector_is_bounded() -> None:
    assert repeated_ngram_ratio("abcdefgh" * 20) > 0.08
    assert repeated_ngram_ratio("short") == 0.0
    with pytest.raises(ValueError):
        repeated_ngram_ratio("text", n=1)
