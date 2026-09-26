"""Model disagreement matrix (masterplan section 27).

For every page, every pair of models that produced output is compared without
any reference to an answer key. The question this feeds — asked later, in
``correlate.py``, after official scoring — is whether GT-free disagreement
finds the pages an evaluator will mark wrong.

The pair is always stored with its two model keys in lexicographic order and
every metric is symmetric, so ``(a, b)`` and ``(b, a)`` are the same row. That
is what makes the matrix a matrix rather than a list of opinions.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from arena.constants import CAMPAIGN_ID
from arena.tavonel import features, guards, jsonio, outputs
from arena.tavonel.paths import ArenaPaths

PAIR_SCHEMA = "tavonel.arena.disagreement-pair.v1"

# difflib is quadratic; a page rarely needs more than this many characters to
# establish whether two transcriptions agree. Truncation is recorded per row.
MAX_SIMILARITY_CHARS: Final = 20_000


@dataclass(frozen=True, slots=True)
class DisagreementReport:
    pairs_path: Path
    row_count: int
    case_count: int
    models: tuple[str, ...]
    pairs_sha256: str


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return round(len(left & right) / len(union), 6)


@dataclass(frozen=True, slots=True)
class SideFeatures:
    """The few per-output numbers a pair comparison needs."""

    text: str
    normalized: str
    tokens: set[str]
    numbers: set[str]
    fingerprints: tuple[str, ...]
    output_chars: int
    empty: bool
    truncated: bool
    table_row_count: int
    heading_count: int
    formula_count: int


def side_features(text: str, signals_record: Mapping[str, Any] | None = None) -> SideFeatures:
    """Derive one side of a comparison, reusing a signals record when there is one."""
    block = signals_record.get("features") if isinstance(signals_record, dict) else None
    if not isinstance(block, dict):
        computed = features.compute_text_features(text)
        block = computed.as_dict()
    return SideFeatures(
        text=text,
        normalized=features.normalize_text(text),
        tokens=set(features.word_tokens(text)),
        numbers=set(features.number_tokens(text)),
        fingerprints=tuple(features.paragraph_fingerprints(text)),
        output_chars=int(block.get("output_chars") or 0),
        empty=bool(block.get("empty_output")),
        truncated=bool(block.get("suspicious_truncation")),
        table_row_count=int(block.get("table_row_count") or 0),
        heading_count=int(block.get("heading_count") or 0),
        formula_count=int(block.get("formula_count") or 0),
    )


def compare(left: SideFeatures, right: SideFeatures) -> dict[str, Any]:
    """Symmetric GT-free comparison of two outputs for the same page."""
    a_text = left.normalized[:MAX_SIMILARITY_CHARS]
    b_text = right.normalized[:MAX_SIMILARITY_CHARS]
    similarity = difflib.SequenceMatcher(None, a_text, b_text, autojunk=False).ratio()
    lengths = (left.output_chars, right.output_chars)
    longest = max(lengths)
    lcs = features.lcs_length(left.fingerprints, right.fingerprints)
    fingerprint_span = max(len(left.fingerprints), len(right.fingerprints))
    return {
        "formula_count_difference": abs(left.formula_count - right.formula_count),
        "heading_count_difference": abs(left.heading_count - right.heading_count),
        "number_set_jaccard": _jaccard(left.numbers, right.numbers),
        "number_set_disagreement": round(1.0 - _jaccard(left.numbers, right.numbers), 6),
        "one_empty_one_nonempty": left.empty != right.empty,
        "one_truncated_one_complete": left.truncated != right.truncated,
        "output_length_ratio": 1.0 if longest == 0 else round(min(lengths) / longest, 6),
        "reading_order_disagreement": (
            0.0 if fingerprint_span == 0 else round(1.0 - lcs / fingerprint_span, 6)
        ),
        "similarity_truncated": (
            len(left.normalized) > MAX_SIMILARITY_CHARS
            or len(right.normalized) > MAX_SIMILARITY_CHARS
        ),
        "table_row_count_difference": abs(left.table_row_count - right.table_row_count),
        "text_similarity": round(similarity, 6),
        "token_jaccard": _jaccard(left.tokens, right.tokens),
    }


def compare_models(
    model_a: str,
    side_a: SideFeatures,
    model_b: str,
    side_b: SideFeatures,
) -> tuple[str, str, dict[str, Any]]:
    """Order the pair lexicographically so the row cannot depend on call order."""
    if model_a <= model_b:
        return model_a, model_b, compare(side_a, side_b)
    return model_b, model_a, compare(side_b, side_a)


def build_disagreement(
    paths: ArenaPaths, model_keys: Sequence[str] | None = None
) -> DisagreementReport:
    """Write ``tavonel/disagreement/pairs.jsonl`` for every case with 2+ outputs."""
    available = outputs.load_outputs(paths, model_keys)
    models = sorted(available)
    case_keys: set[str] = set()
    for refs in available.values():
        case_keys.update(refs)

    rows: list[dict[str, Any]] = []
    cases_with_pairs = 0
    for case_key in sorted(case_keys):
        present = [model for model in models if case_key in available[model]]
        if len(present) < 2:
            continue
        cases_with_pairs += 1
        sides: dict[str, SideFeatures] = {}
        sample_id: str | None = None
        benchmark: str | None = None
        for model in present:
            ref = available[model][case_key]
            guards.assert_readable(ref.canonical_path)
            text = ref.canonical_path.read_text(encoding="utf-8", errors="replace")
            signals_path = paths.signals_path(model, case_key)
            record = (
                guards.read_json_guarded(signals_path, what="signals record")
                if signals_path.is_file()
                else None
            )
            sides[model] = side_features(text, record)
            if sample_id is None:
                sample_id = ref.sample_id or (
                    str(record.get("sample_id")) if isinstance(record, dict) else None
                )
            if benchmark is None:
                benchmark = ref.benchmark or (
                    str(record.get("benchmark")) if isinstance(record, dict) else None
                )
        for index, model_a in enumerate(present):
            for model_b in present[index + 1 :]:
                key_a, key_b, metrics = compare_models(
                    model_a, sides[model_a], model_b, sides[model_b]
                )
                rows.append(
                    {
                        "schema": PAIR_SCHEMA,
                        "campaign_id": CAMPAIGN_ID,
                        "case_key": case_key,
                        "sample_id": sample_id,
                        "benchmark": benchmark,
                        "model_a": key_a,
                        "model_b": key_b,
                        "metrics": metrics,
                    }
                )

    pairs_sha = jsonio.write_jsonl_atomic(paths.disagreement_pairs, rows)
    return DisagreementReport(
        pairs_path=paths.disagreement_pairs,
        row_count=len(rows),
        case_count=cases_with_pairs,
        models=tuple(models),
        pairs_sha256=pairs_sha,
    )


__all__ = [
    "MAX_SIMILARITY_CHARS",
    "PAIR_SCHEMA",
    "DisagreementReport",
    "SideFeatures",
    "build_disagreement",
    "compare",
    "compare_models",
    "side_features",
]
