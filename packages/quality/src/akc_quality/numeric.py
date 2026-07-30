"""Strict numeric-token fidelity; semantic similarity never masks number errors."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from akc_cir import ContractModel

_TOKEN_PATTERN = re.compile(
    r"""
    (?<![\w])
    (?:
        \d{4}[-/.]\d{1,2}[-/.]\d{1,2}
        |
        (?:[$€£¥₩]\s*)?[+-]?
        (?:\d{1,3}(?:,\d{3})+|\d+)
        (?:\.\d+)?
        (?:\s*%)?
    )
    (?![\w])
    """,
    re.VERBOSE,
)


class NumericComparison(ContractModel):
    reference_tokens: tuple[str, ...]
    candidate_tokens: tuple[str, ...]
    matched_count: int
    missing_tokens: dict[str, int]
    unexpected_tokens: dict[str, int]
    score: float


def _normalize_token(token: str) -> str:
    return "".join(unicodedata.normalize("NFKC", token).split())


def extract_numeric_tokens(text: str) -> tuple[str, ...]:
    return tuple(_normalize_token(match.group(0)) for match in _TOKEN_PATTERN.finditer(text))


def compare_numeric_tokens(reference: str, candidate: str) -> NumericComparison:
    reference_tokens = extract_numeric_tokens(reference)
    candidate_tokens = extract_numeric_tokens(candidate)
    reference_counter = Counter(reference_tokens)
    candidate_counter = Counter(candidate_tokens)
    matched = sum((reference_counter & candidate_counter).values())
    denominator = max(len(reference_tokens), len(candidate_tokens))
    score = 1.0 if denominator == 0 else matched / denominator
    return NumericComparison(
        reference_tokens=reference_tokens,
        candidate_tokens=candidate_tokens,
        matched_count=matched,
        missing_tokens=dict(sorted((reference_counter - candidate_counter).items())),
        unexpected_tokens=dict(sorted((candidate_counter - reference_counter).items())),
        score=score,
    )
