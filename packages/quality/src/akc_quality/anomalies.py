"""Deterministic text and Markdown anomaly detectors."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from itertools import pairwise

from .models import FindingSeverity, QualityFinding

_HEADING = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)
_CONTROL_ALLOWED = {"\n", "\r", "\t"}


def repeated_ngram_ratio(text: str, n: int = 8) -> float:
    if n < 2 or n > 32:
        raise ValueError("n must be between 2 and 32")
    characters = [character for character in text if not character.isspace()]
    if len(characters) < n:
        return 0.0
    grams = ["".join(characters[index : index + n]) for index in range(len(characters) - n + 1)]
    counts = Counter(grams)
    repeated_positions = sum(count for count in counts.values() if count > 1)
    return repeated_positions / len(grams)


def text_anomalies(
    text: str,
    *,
    reference_length: int | None = None,
    repeated_8gram_threshold: float = 0.08,
) -> tuple[QualityFinding, ...]:
    findings: list[QualityFinding] = []
    if not text.strip():
        findings.append(
            QualityFinding(
                code="text.empty",
                severity=FindingSeverity.CRITICAL,
                message="Parser output is empty.",
            )
        )
        return tuple(findings)
    replacement_ratio = text.count("\ufffd") / max(len(text), 1)
    if replacement_ratio > 0.001:
        findings.append(
            QualityFinding(
                code="text.replacement_characters",
                severity=FindingSeverity.ERROR,
                message="Replacement-character ratio exceeds the gate.",
                observed=replacement_ratio,
                threshold=0.001,
            )
        )
    controls = [
        character
        for character in text
        if unicodedata.category(character) == "Cc" and character not in _CONTROL_ALLOWED
    ]
    if controls:
        findings.append(
            QualityFinding(
                code="text.control_characters",
                severity=FindingSeverity.ERROR,
                message="Unexpected control characters were emitted.",
                observed=len(controls),
            )
        )
    repeated_ratio = repeated_ngram_ratio(text)
    if repeated_ratio > repeated_8gram_threshold:
        findings.append(
            QualityFinding(
                code="text.repetition",
                severity=FindingSeverity.ERROR,
                message="Repeated 8-gram ratio exceeds the safety threshold.",
                observed=repeated_ratio,
                threshold=repeated_8gram_threshold,
            )
        )
    if reference_length is not None and reference_length > 0:
        ratio = len(text) / reference_length
        if ratio < 0.35 or ratio > 6.0:
            findings.append(
                QualityFinding(
                    code="text.length_anomaly",
                    severity=FindingSeverity.ERROR,
                    message="Output length is implausible relative to the reference.",
                    observed=ratio,
                    threshold="0.35..6.0",
                )
            )
    return tuple(findings)


def markdown_anomalies(markdown: str) -> tuple[QualityFinding, ...]:
    findings: list[QualityFinding] = []
    levels = [len(match.group(1)) for match in _HEADING.finditer(markdown)]
    h1_count = levels.count(1)
    if h1_count > 1:
        findings.append(
            QualityFinding(
                code="markdown.multiple_h1",
                severity=FindingSeverity.WARNING,
                message="Portable profile recommends one H1 per document.",
                observed=h1_count,
                threshold=1,
            )
        )
    for previous, current in pairwise(levels):
        if current > previous + 1:
            findings.append(
                QualityFinding(
                    code="markdown.heading_level_jump",
                    severity=FindingSeverity.WARNING,
                    message="Heading level jumps by more than one.",
                    observed=f"{previous}->{current}",
                )
            )
    if "\x00" in markdown:
        findings.append(
            QualityFinding(
                code="markdown.null_byte",
                severity=FindingSeverity.CRITICAL,
                message="Markdown contains a null byte.",
            )
        )
    return tuple(findings)
