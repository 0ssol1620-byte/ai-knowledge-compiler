"""Cross-engine agreement measures."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import AgreementScore
from .numeric import compare_numeric_tokens

_HEADING_TEXT = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


def _normalized_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def compare_engine_outputs(
    reference: str,
    candidate: str,
    *,
    semantic_similarity: float | None = None,
    table_shape_match: float | None = None,
    source_coverage_delta: float = 0.0,
) -> AgreementScore:
    normalized_reference = _normalized_text(reference)
    normalized_candidate = _normalized_text(candidate)
    edit_similarity = SequenceMatcher(
        None, normalized_reference, normalized_candidate, autojunk=False
    ).ratio()
    numeric_match = compare_numeric_tokens(reference, candidate).score
    reference_headings = [_normalized_text(value) for value in _HEADING_TEXT.findall(reference)]
    candidate_headings = [_normalized_text(value) for value in _HEADING_TEXT.findall(candidate)]
    heading_match = SequenceMatcher(
        None, reference_headings, candidate_headings, autojunk=False
    ).ratio()
    return AgreementScore(
        normalized_edit_similarity=edit_similarity,
        semantic_similarity=semantic_similarity,
        numeric_token_match=numeric_match,
        heading_match=heading_match,
        table_shape_match=table_shape_match,
        source_coverage_delta=source_coverage_delta,
    )
