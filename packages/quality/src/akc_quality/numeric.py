r"""Strict numeric-token fidelity; semantic similarity never masks number errors.

Two tokenizer modes (KOREAN-BENCHMARK-DESIGN-2026-10-17 section 2.3, lane KB-A6):

* ``"legacy"`` -- the published behaviour and the default. Its ``(?![\w])``
  lookaround counts a Hangul syllable as a word character, so ``1,000원`` reads
  as ``1`` and ``30일`` reads as nothing. Kept byte-identical so no caller's
  metric moves until a benchmark and canary say so.
* ``"korean-v1"`` -- opt-in. Hangul and Hanja next to a number are a boundary,
  not part of a word; Latin letters still are (``A123``, ``5kg`` stay unread, as
  in legacy). It also keeps the magnitude words ``십/백/천/만/억`` with the digits
  (``3억`` is not ``3만``), reads ``2026. 10. 17.`` as one date, reads the
  fullwidth won and percent signs, NFC-normalises first, and never reads a
  hyphen glued to Hangul (``1월-3월``) as a minus sign.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Literal

from akc_cir import ContractModel

NumericTokenMode = Literal["legacy", "korean-v1"]

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

# Scripts written without spaces, where a number is routinely glued to the next
# word: Hangul (jamo, compatibility/halfwidth jamo, syllables) and Hanja (CJK
# ideographs). ponytail: kana are not listed, so Japanese keeps legacy behaviour.
_GLUED_SCRIPTS = "".join(
    f"{chr(start)}-{chr(end)}"
    for start, end in (
        (0x1100, 0x11FF),  # Hangul Jamo
        (0x3130, 0x318F),  # Hangul Compatibility Jamo
        (0xA960, 0xA97F),  # Hangul Jamo Extended-A
        (0xAC00, 0xD7FF),  # Hangul Syllables and Jamo Extended-B
        (0xFFA0, 0xFFDC),  # Halfwidth Hangul
        (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
        (0x4E00, 0x9FFF),  # CJK Unified Ideographs
        (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    )
)
# A word character a number may not touch: everything \w matches except the above.
_WORD_NOT_GLUED = r"[^\W" + _GLUED_SCRIPTS + "]"
_FULLWIDTH_WON, _FULLWIDTH_PERCENT = chr(0xFFE6), chr(0xFF05)

_KOREAN_V1_PATTERN = re.compile(
    "(?<!" + _WORD_NOT_GLUED + ")"
    r"(?:"
    r"\d{4}[-/.]\s*\d{1,2}[-/.]\s*\d{1,2}(?!" + _WORD_NOT_GLUED + ")"
    r"|"
    r"(?:[$€£¥₩" + _FULLWIDTH_WON + r"]\s*)?"
    # A sign glued to a preceding word is a separator (1월-3월, 가-1호), as in legacy.
    r"(?:(?<!\w)[+-])?"
    r"(?:\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.\d+)?"
    # A magnitude word ends the number and may touch the next one (3억5천만).
    # ponytail: 조 (10^12) is left out because 제7조 is an article number, so
    # 1조 reads as 1. Upgrade path: the KB1 ko_tokens article rule.
    r"(?:[십백천]?[만억]|[십백천]"
    r"|(?:\s*[%" + _FULLWIDTH_PERCENT + r"])?(?!" + _WORD_NOT_GLUED + "))"
    r")"
)

_PATTERNS: dict[str, re.Pattern[str]] = {
    "legacy": _TOKEN_PATTERN,
    "korean-v1": _KOREAN_V1_PATTERN,
}


class NumericComparison(ContractModel):
    reference_tokens: tuple[str, ...]
    candidate_tokens: tuple[str, ...]
    matched_count: int
    missing_tokens: dict[str, int]
    unexpected_tokens: dict[str, int]
    score: float


def _normalize_token(token: str) -> str:
    return "".join(unicodedata.normalize("NFKC", token).split())


def extract_numeric_tokens(text: str, *, mode: NumericTokenMode = "legacy") -> tuple[str, ...]:
    pattern = _PATTERNS.get(mode)
    if pattern is None:
        raise ValueError(f"unknown numeric token mode {mode!r}; expected {sorted(_PATTERNS)}")
    if mode == "korean-v1":
        text = unicodedata.normalize("NFC", text)
    return tuple(_normalize_token(match.group(0)) for match in pattern.finditer(text))


def compare_numeric_tokens(
    reference: str, candidate: str, *, mode: NumericTokenMode = "legacy"
) -> NumericComparison:
    reference_tokens = extract_numeric_tokens(reference, mode=mode)
    candidate_tokens = extract_numeric_tokens(candidate, mode=mode)
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
