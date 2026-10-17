from __future__ import annotations

import unicodedata
from typing import Any

import pytest
from akc_quality import (
    FindingSeverity,
    QualityFinding,
    QualityStatus,
    QualityVector,
    compare_engine_outputs,
    compare_numeric_tokens,
    evaluate_quality,
    extract_numeric_tokens,
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


# ---------------------------------------------------------------------------
# KOREAN-BENCHMARK-DESIGN-2026-10-17 §2.3 (KB-A6). The legacy pattern's
# ``(?![\w])`` treats a Hangul syllable as a word character, so a number glued
# to 원/일/조/가 is truncated or dropped. Receipt: korean-benchmark-receipts/
# KO-NUMERIC-PROBE.out.txt, sha256 cdd7e95ee39f9928936293601c06742ad016034062cc27f12d499f94912d1073.

# What the legacy default returns, exactly as the receipt recorded it. This is
# the compatibility contract: the default stays byte-identical until a
# benchmark and canary move callers to the new mode, so these defects are
# pinned here on purpose rather than silently changing a published metric.
KO_LEGACY_RECEIPT: dict[str, tuple[str, ...]] = {
    "계정 001, 증감 -2.50%, 총액 ₩1,000": ("001", "-2.50%", "₩1,000"),
    "계약 종료 후 30일": (),
    "1,000원": ("1",),
    "제7조 제1항": (),
    "2026. 10. 17.": ("2026", "10", "17"),
    "2026.10.17": ("2026.10.17",),
    "매출은 10% 증가했다.": ("10%",),
    "매출은 10%가 증가": ("10",),
    "금 1,234,000원정": ("1,234",),
    "3억 5천만원": (),
}

# What the Korean-aware mode must return. The first, sixth and seventh rows are
# no-regression controls: the receipt shows legacy already reads them right.
KO_EXPECTED: dict[str, tuple[str, ...]] = {
    "계정 001, 증감 -2.50%, 총액 ₩1,000": ("001", "-2.50%", "₩1,000"),
    "계약 종료 후 30일": ("30",),
    "1,000원": ("1,000",),
    "제7조 제1항": ("7", "1"),
    "2026. 10. 17.": ("2026.10.17",),
    "2026.10.17": ("2026.10.17",),
    "매출은 10% 증가했다.": ("10%",),
    "매출은 10%가 증가": ("10%",),
    "금 1,234,000원정": ("1,234,000",),
    "3억 5천만원": ("3억", "5천만"),
}

# English inputs on which the new mode must agree with legacy token for token.
EN_NO_REGRESSION = (
    "001 -2.50",
    "1 2.50",
    "Revenue rose 10% to $1,234.50 on 2026-10-17 and 2026/1/5.",
    "Pages 1,2,3 and items 12,3456; A123, 12abc, v2.0, 5kg, 3 %.",
    "Total: € 1,000,000 (-0.5%) vs £ 12.75; ¥300 and ₩ 5,000.",
)


@pytest.mark.parametrize("text", list(KO_LEGACY_RECEIPT))
def test_legacy_default_is_unchanged_on_korean_receipt(text: str) -> None:
    assert extract_numeric_tokens(text) == KO_LEGACY_RECEIPT[text]


@pytest.mark.parametrize("text", [*KO_LEGACY_RECEIPT, *EN_NO_REGRESSION])
def test_explicit_legacy_mode_is_the_default(text: str) -> None:
    assert extract_numeric_tokens(text, mode="legacy") == extract_numeric_tokens(text)
    assert compare_numeric_tokens(text, "0", mode="legacy") == compare_numeric_tokens(text, "0")


@pytest.mark.parametrize("text", list(KO_EXPECTED))
def test_korean_mode_reads_section_2_3_cases(text: str) -> None:
    assert extract_numeric_tokens(text, mode="korean-v1") == KO_EXPECTED[text]


def test_korean_mode_does_not_let_a_wrong_amount_pass() -> None:
    # Legacy reads both sides as ("1",): a wrong amount scores as a perfect match.
    assert compare_numeric_tokens("1,000원", "1,999원").score == 1.0
    fixed = compare_numeric_tokens("1,000원", "1,999원", mode="korean-v1")
    assert fixed.score == 0.0
    assert fixed.missing_tokens == {"1,000": 1}
    assert fixed.unexpected_tokens == {"1,999": 1}
    # Legacy reads no token at all, so page_quality treats the page as unknown.
    assert compare_numeric_tokens("계약 종료 후 30일", "계약 종료 후 60일").reference_tokens == ()
    assert (
        compare_numeric_tokens("계약 종료 후 30일", "계약 종료 후 60일", mode="korean-v1").score
        == 0.0
    )


def test_korean_mode_keeps_the_magnitude_word() -> None:
    assert compare_numeric_tokens("3억원", "3만원", mode="korean-v1").score == 0.0
    assert extract_numeric_tokens("3억5천만원 10만 명 5천원", mode="korean-v1") == (
        "3억",
        "5천만",
        "10만",
        "5천",
    )


@pytest.mark.parametrize("text", EN_NO_REGRESSION)
def test_korean_mode_matches_legacy_on_english(text: str) -> None:
    assert extract_numeric_tokens(text, mode="korean-v1") == extract_numeric_tokens(text)


def test_korean_mode_reads_nfd_fullwidth_and_hanja_forms() -> None:
    nfd = unicodedata.normalize("NFD", "3억 5천만원, 제7조")
    assert extract_numeric_tokens(nfd, mode="korean-v1") == ("3억", "5천만", "7")
    fullwidth = f"총액 {chr(0xFFE6)}1,000, 증가율 50{chr(0xFF05)}"  # fullwidth won sign and percent
    assert extract_numeric_tokens(fullwidth, mode="korean-v1") == ("₩1,000", "50%")
    assert extract_numeric_tokens("第7條 金1,000圓", mode="korean-v1") == ("7", "1,000")


def test_korean_mode_does_not_read_a_hyphen_after_hangul_as_a_minus() -> None:
    assert extract_numeric_tokens("1월-3월, 가-1호", mode="korean-v1") == ("1", "3", "1")
    assert extract_numeric_tokens("증감 -2.50%", mode="korean-v1") == ("-2.50%",)


def test_unknown_numeric_mode_fails_closed() -> None:
    unknown: Any = "korean-v2"
    with pytest.raises(ValueError, match="korean-v2"):
        extract_numeric_tokens("1,000원", mode=unknown)
    with pytest.raises(ValueError, match="korean-v2"):
        compare_numeric_tokens("1,000원", "1,000원", mode=unknown)
