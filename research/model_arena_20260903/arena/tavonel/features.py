"""Pure, GT-free text features (masterplan sections 12.2 and 26).

Nothing in this module opens a file, looks at an answer key, or knows which
model produced the text. Every function takes a string and returns numbers, so
the whole feature set is reproducible from the frozen output alone.

Two deliberate restraints:

* **No scalar quality score.** The 2026-08 FOLYNTA campaign published blind
  ranking as *not supported*: a single blended "quality" number never beat
  length alone at finding the pages that actually failed. So these
  are named, separately recorded features, and the policies in
  ``policies.py`` trip on named thresholds — never on a blended score.
* **No invented value.** A feature that cannot be computed from the text is
  not defaulted to zero; the caller records it as unavailable with a reason
  (``signals.py``). Zero here always means "measured, and it was zero".

Floats are rounded to ``_ROUND`` digits so a signals record hashes identically
on any host.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

FEATURE_SET_VERSION: Final = "tavonel-arena-signals.v1"

_ROUND: Final = 6

# A repeated 5-gram is the classic decode-loop tell. Five is short enough to
# catch a stuck table row and long enough that ordinary prose does not trip it.
REPETITION_NGRAM: Final = 5
# Paragraphs shorter than this are page furniture (page numbers, single words)
# and would inflate the duplicate ratio on any well-formed document.
MIN_PARAGRAPH_CHARS: Final = 24

_WORD = re.compile(r"\w+", re.UNICODE)
_NUMBER_TOKEN = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")
_WHITESPACE_RUN = re.compile(r"\s+")

_MD_TABLE_ROW = re.compile(r"^\s{0,3}\|.*\|\s*$")
_MD_TABLE_DIVIDER = re.compile(r"^\s{0,3}\|[\s:|\-]+\|\s*$")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_MD_SETEXT = re.compile(r"^\s{0,3}(=+|-{2,})\s*$")
_MD_LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+\S|\d+[.)]\s+\S)")
_MD_FENCE = re.compile(r"^\s{0,3}(?:```|~~~)")

_HTML_TABLE_OPEN = re.compile(r"<table\b", re.IGNORECASE)
_HTML_TABLE_CLOSE = re.compile(r"</table\s*>", re.IGNORECASE)
_HTML_ROW_OPEN = re.compile(r"<tr\b", re.IGNORECASE)
_HTML_ROW_CLOSE = re.compile(r"</tr\s*>", re.IGNORECASE)
_HTML_CELL_OPEN = re.compile(r"<t[dh]\b", re.IGNORECASE)
_HTML_HEADING = re.compile(r"<h[1-6]\b", re.IGNORECASE)
_HTML_LIST_ITEM = re.compile(r"<li\b", re.IGNORECASE)
_HTML_TABLE_BLOCK = re.compile(r"<table\b.*?</table\s*>", re.IGNORECASE | re.DOTALL)

_DISPLAY_MATH = re.compile(r"\$\$.+?\$\$", re.DOTALL)
_INLINE_MATH = re.compile(r"\$[^$\n]+\$")
_PAREN_MATH = re.compile(r"\\\(.+?\\\)", re.DOTALL)
_BRACKET_MATH = re.compile(r"\\\[.+?\\\]", re.DOTALL)
_EQUATION_ENV = re.compile(r"\\begin\{equation\*?\}")

_ELLIPSIS_TAIL = re.compile(r"(?:\.\.\.|…)\s*$")
_SENTENCE_TERMINATORS: Final = frozenset(".!?\u3002\uff01\uff1f:;)]}\"'\u00bb\u201d\u2019|`>*")

# Phrases a transcription model emits when it starts talking *about* the page
# instead of transcribing it. Matched case-folded as substrings.
HALLUCINATED_BOILERPLATE_PHRASES: Final = (
    "i cannot",
    "i can't",
    "i am unable to",
    "i'm unable to",
    "i'm sorry",
    "i am sorry",
    "as an ai",
    "as a language model",
    "here is the transcription",
    "here's the transcription",
    "here is the markdown",
    "here is the extracted",
    "sure, here",
    "certainly! here",
    "the image shows",
    "this image appears to",
    "unfortunately, i",
)

_SCRIPT_BUCKETS: Final = ("latin", "hangul", "han", "cyrillic", "greek", "other")


def _round(value: float) -> float:
    return round(value, _ROUND)


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return _round(numerator / denominator)


def normalize_text(text: str) -> str:
    """NFKC + case-folded + whitespace-collapsed text for comparisons."""
    return _WHITESPACE_RUN.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


def word_tokens(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def number_tokens(text: str) -> list[str]:
    return [match.replace(",", "") for match in _NUMBER_TOKEN.findall(text)]


def paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text)
    return [normalized for block in blocks if (normalized := normalize_text(block))]


def script_distribution(text: str) -> dict[str, float]:
    """Ratios of letters per script bucket. All zero when the text has no letters."""
    counts: Counter[str] = Counter()
    letters = 0
    for char in text:
        if not char.isalpha():
            continue
        letters += 1
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F:
            counts["hangul"] += 1
        elif 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0xF900 <= code <= 0xFAFF:
            counts["han"] += 1
        elif 0x0400 <= code <= 0x04FF:
            counts["cyrillic"] += 1
        elif 0x0370 <= code <= 0x03FF:
            counts["greek"] += 1
        elif code < 0x0250 or 0x1E00 <= code <= 0x1EFF:
            counts["latin"] += 1
        else:
            counts["other"] += 1
    distribution = {bucket: _ratio(counts.get(bucket, 0), letters) for bucket in _SCRIPT_BUCKETS}
    distribution["letter_count"] = float(letters)
    return distribution


def count_formulas(text: str) -> int:
    """LaTeX spans: ``$$..$$``, ``$..$``, ``\\(..\\)``, ``\\[..\\]``, equation envs."""
    display = _DISPLAY_MATH.findall(text)
    without_display = _DISPLAY_MATH.sub(" ", text)
    return (
        len(display)
        + len(_INLINE_MATH.findall(without_display))
        + len(_PAREN_MATH.findall(text))
        + len(_BRACKET_MATH.findall(text))
        + len(_EQUATION_ENV.findall(text))
    )


@dataclass(frozen=True, slots=True)
class TableShape:
    markdown_tables: int
    markdown_rows: int
    markdown_blocks_without_divider: int
    markdown_ragged_blocks: int
    html_tables: int
    html_rows: int
    html_unbalanced: bool
    html_rows_without_cells: int


def table_shape(text: str) -> TableShape:
    """Markdown and HTML table structure, counted without repairing anything."""
    md_tables = 0
    md_rows = 0
    missing_divider = 0
    ragged = 0
    block_widths: list[int] = []
    block_has_divider = False
    in_fence = False

    def close_block() -> None:
        nonlocal md_tables, missing_divider, ragged, block_widths, block_has_divider
        if block_widths:
            md_tables += 1
            if not block_has_divider:
                missing_divider += 1
            if len(set(block_widths)) > 1:
                ragged += 1
        block_widths = []
        block_has_divider = False

    for line in text.splitlines():
        if _MD_FENCE.match(line):
            in_fence = not in_fence
            close_block()
            continue
        if in_fence:
            continue
        if _MD_TABLE_ROW.match(line):
            md_rows += 1
            if _MD_TABLE_DIVIDER.match(line):
                block_has_divider = True
            else:
                block_widths.append(line.strip().count("|"))
            continue
        close_block()
    close_block()

    html_open = len(_HTML_TABLE_OPEN.findall(text))
    html_close = len(_HTML_TABLE_CLOSE.findall(text))
    html_rows = len(_HTML_ROW_OPEN.findall(text))
    rows_without_cells = 0
    for block in _HTML_TABLE_BLOCK.findall(text):
        for row in _HTML_ROW_OPEN.split(block)[1:]:
            if not _HTML_CELL_OPEN.search(row.split("</tr")[0]):
                rows_without_cells += 1

    return TableShape(
        markdown_tables=md_tables,
        markdown_rows=md_rows,
        markdown_blocks_without_divider=missing_divider,
        markdown_ragged_blocks=ragged,
        html_tables=html_open,
        html_rows=html_rows,
        html_unbalanced=html_open != html_close or html_rows != len(_HTML_ROW_CLOSE.findall(text)),
        html_rows_without_cells=rows_without_cells,
    )


def count_headings(text: str) -> int:
    total = len(_HTML_HEADING.findall(text))
    lines = text.splitlines()
    for index, line in enumerate(lines):
        setext = bool(_MD_SETEXT.match(line)) and index > 0 and bool(lines[index - 1].strip())
        if _MD_HEADING.match(line) or setext:
            total += 1
    return total


def count_list_items(text: str) -> int:
    markdown = sum(1 for line in text.splitlines() if _MD_LIST_ITEM.match(line))
    return markdown + len(_HTML_LIST_ITEM.findall(text))


def duplicate_paragraph_ratio(text: str) -> float:
    blocks = [block for block in paragraphs(text) if len(block) >= MIN_PARAGRAPH_CHARS]
    if len(blocks) < 2:
        return 0.0
    return _ratio(len(blocks) - len(set(blocks)), len(blocks))


def ngram_repetition_ratio(text: str, n: int = REPETITION_NGRAM) -> float:
    tokens = word_tokens(text)
    if len(tokens) < n:
        return 0.0
    grams = [tuple(tokens[index : index + n]) for index in range(len(tokens) - n + 1)]
    return _ratio(len(grams) - len(set(grams)), len(grams))


def unbalanced_code_fence(text: str) -> bool:
    return sum(1 for line in text.splitlines() if _MD_FENCE.match(line)) % 2 == 1


def truncation_evidence(text: str, *, output_tokens_at_max: bool | None) -> tuple[str, ...]:
    """Named structural reasons to suspect the output was cut off.

    ``output_tokens_at_max`` is ``None`` when the cap is not knowable from the
    receipt and the registry; that absence is recorded by the caller rather
    than silently treated as "not truncated".
    """
    reasons: list[str] = []
    stripped = text.strip()
    if not stripped:
        return ()
    if unbalanced_code_fence(text):
        reasons.append("unclosed_code_fence")
    shape = table_shape(text)
    if shape.html_unbalanced:
        reasons.append("unclosed_html_table")
    lines = [line for line in text.splitlines() if line.strip()]
    last = lines[-1].strip() if lines else ""
    if last.startswith("|") and not last.endswith("|"):
        reasons.append("ends_mid_table_row")
    elif last and last[-1] not in _SENTENCE_TERMINATORS:
        reasons.append("ends_mid_sentence")
    if output_tokens_at_max:
        reasons.append("output_tokens_at_max")
    return tuple(reasons)


def continuation_evidence(text: str) -> tuple[str, ...]:
    """Evidence the page's content continues outside what the model emitted.

    Distinct from truncation: this looks at both ends for a fragment that
    begins or ends inside a sentence a recovery pass would have to continue.
    """
    reasons: list[str] = []
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ()
    first = lines[0].strip()
    if (
        first
        and not _MD_HEADING.match(first)
        and not _MD_LIST_ITEM.match(first)
        and not first.startswith(("|", "<", "#", "$", "!", "["))
        and (first[0].islower() or first[0] in ",;:)")
    ):
        reasons.append("starts_mid_sentence")
    if _ELLIPSIS_TAIL.search(text):
        reasons.append("ends_with_ellipsis")
    return tuple(reasons)


def matched_boilerplate(text: str) -> tuple[str, ...]:
    folded = text.casefold()
    return tuple(phrase for phrase in HALLUCINATED_BOILERPLATE_PHRASES if phrase in folded)


def markdown_issues(text: str) -> tuple[str, ...]:
    issues: list[str] = []
    if unbalanced_code_fence(text):
        issues.append("unclosed_code_fence")
    shape = table_shape(text)
    if shape.markdown_blocks_without_divider:
        issues.append("markdown_table_without_delimiter_row")
    if shape.markdown_ragged_blocks:
        issues.append("markdown_table_ragged_row_widths")
    return tuple(issues)


def html_table_issues(text: str) -> tuple[str, ...] | None:
    """``None`` when the output contains no HTML table at all."""
    shape = table_shape(text)
    if shape.html_tables == 0 and shape.html_rows == 0:
        return None
    issues: list[str] = []
    if shape.html_unbalanced:
        issues.append("unbalanced_table_or_row_tags")
    if shape.html_rows_without_cells:
        issues.append("row_without_cells")
    if shape.html_tables and shape.html_rows == 0:
        issues.append("table_without_rows")
    return tuple(issues)


def broken_text_counts(text: str) -> tuple[int, int]:
    """``(unicode replacement chars, other broken/control chars)``."""
    replacement = text.count("\ufffd")
    broken = 0
    for char in text:
        code = ord(char)
        if char in "\t\n\r":
            continue
        if code < 0x20 or code == 0x7F or 0xE000 <= code <= 0xF8FF:
            broken += 1
    return replacement, broken


@dataclass(frozen=True, slots=True)
class TextFeatures:
    """The GT-free feature block written into every signals record."""

    empty_output: bool
    output_chars: int
    output_words: int
    text_density: float
    alpha_ratio: float
    digit_ratio: float
    numeric_token_count: int
    formula_count: int
    table_count: int
    table_row_count: int
    heading_count: int
    list_count: int
    duplicate_paragraph_ratio: float
    ngram_repetition_ratio: float
    suspicious_truncation: bool
    truncation_reasons: tuple[str, ...]
    continuation_suspicion: bool
    continuation_reasons: tuple[str, ...]
    unicode_replacement_count: int
    broken_text_ratio: float
    language_distribution: dict[str, float]
    markdown_structural_validity: bool
    markdown_issues: tuple[str, ...]
    html_table_validity: bool | None
    html_table_issues: tuple[str, ...] | None
    hallucinated_boilerplate: bool
    hallucinated_boilerplate_phrases: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "alpha_ratio": self.alpha_ratio,
            "broken_text_ratio": self.broken_text_ratio,
            "continuation_reasons": list(self.continuation_reasons),
            "continuation_suspicion": self.continuation_suspicion,
            "digit_ratio": self.digit_ratio,
            "duplicate_paragraph_ratio": self.duplicate_paragraph_ratio,
            "empty_output": self.empty_output,
            "formula_count": self.formula_count,
            "hallucinated_boilerplate": self.hallucinated_boilerplate,
            "hallucinated_boilerplate_phrases": list(self.hallucinated_boilerplate_phrases),
            "heading_count": self.heading_count,
            "html_table_issues": (
                None if self.html_table_issues is None else list(self.html_table_issues)
            ),
            "html_table_validity": self.html_table_validity,
            "language_distribution": dict(self.language_distribution),
            "list_count": self.list_count,
            "markdown_issues": list(self.markdown_issues),
            "markdown_structural_validity": self.markdown_structural_validity,
            "ngram_repetition_ratio": self.ngram_repetition_ratio,
            "numeric_token_count": self.numeric_token_count,
            "output_chars": self.output_chars,
            "output_words": self.output_words,
            "suspicious_truncation": self.suspicious_truncation,
            "table_count": self.table_count,
            "table_row_count": self.table_row_count,
            "text_density": self.text_density,
            "truncation_reasons": list(self.truncation_reasons),
            "unicode_replacement_count": self.unicode_replacement_count,
        }


def compute_text_features(text: str, *, output_tokens_at_max: bool | None = None) -> TextFeatures:
    """Every GT-free feature derivable from the model's text alone."""
    chars = len(text)
    non_space = sum(1 for char in text if not char.isspace())
    alpha = sum(1 for char in text if char.isalpha())
    digits = sum(1 for char in text if char.isdigit())
    replacement, broken = broken_text_counts(text)
    shape = table_shape(text)
    truncation = truncation_evidence(text, output_tokens_at_max=output_tokens_at_max)
    continuation = continuation_evidence(text)
    boilerplate = matched_boilerplate(text)
    md_issues = markdown_issues(text)
    html_issues = html_table_issues(text)
    return TextFeatures(
        empty_output=not text.strip(),
        output_chars=chars,
        output_words=len(word_tokens(text)),
        text_density=_ratio(non_space, chars),
        alpha_ratio=_ratio(alpha, non_space),
        digit_ratio=_ratio(digits, non_space),
        numeric_token_count=len(number_tokens(text)),
        formula_count=count_formulas(text),
        table_count=shape.markdown_tables + shape.html_tables,
        table_row_count=shape.markdown_rows + shape.html_rows,
        heading_count=count_headings(text),
        list_count=count_list_items(text),
        duplicate_paragraph_ratio=duplicate_paragraph_ratio(text),
        ngram_repetition_ratio=ngram_repetition_ratio(text),
        suspicious_truncation=bool(truncation),
        truncation_reasons=truncation,
        continuation_suspicion=bool(continuation),
        continuation_reasons=continuation,
        unicode_replacement_count=replacement,
        broken_text_ratio=_ratio(replacement + broken, non_space),
        language_distribution=script_distribution(text),
        markdown_structural_validity=not md_issues,
        markdown_issues=md_issues,
        html_table_validity=None if html_issues is None else not html_issues,
        html_table_issues=html_issues,
        hallucinated_boilerplate=bool(boilerplate),
        hallucinated_boilerplate_phrases=boilerplate,
    )


def paragraph_fingerprints(text: str, *, digest_chars: int = 12) -> list[str]:
    """Stable short fingerprints per paragraph, for the reading-order proxy."""
    return [
        hashlib.sha256(block.encode("utf-8")).hexdigest()[:digest_chars]
        for block in paragraphs(text)
    ]


def lcs_length(left: Sequence[str], right: Sequence[str]) -> int:
    """Longest common subsequence length; O(len(left) * len(right)) in time."""
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    for left_item in left:
        current = [0] * (len(right) + 1)
        for index, right_item in enumerate(right, start=1):
            if left_item == right_item:
                current[index] = previous[index - 1] + 1
            else:
                current[index] = max(previous[index], current[index - 1])
        previous = current
    return previous[-1]


__all__ = [
    "FEATURE_SET_VERSION",
    "HALLUCINATED_BOILERPLATE_PHRASES",
    "MIN_PARAGRAPH_CHARS",
    "REPETITION_NGRAM",
    "TableShape",
    "TextFeatures",
    "compute_text_features",
    "continuation_evidence",
    "count_formulas",
    "count_headings",
    "count_list_items",
    "duplicate_paragraph_ratio",
    "lcs_length",
    "ngram_repetition_ratio",
    "normalize_text",
    "number_tokens",
    "paragraph_fingerprints",
    "paragraphs",
    "script_distribution",
    "table_shape",
    "truncation_evidence",
    "word_tokens",
]
