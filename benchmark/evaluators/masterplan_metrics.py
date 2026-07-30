"""Versioned evaluators for the complete masterplan section 22 metric surface.

The functions in this module deliberately operate on explicit benchmark
annotations.  If the annotation required to measure a metric is absent or
malformed, the result is ``None``.  In particular, this module never invents a
human score, review duration, model quality result, or route cost.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

EVALUATOR_VERSION = "22.4-22.8-v1.0.0"
type MetricValue = float | dict[str, float] | None

SCALAR_METRIC_KEYS = (
    "hangul_syllable_corruption_rate",
    "hangul_jamo_corruption_rate",
    "punctuation_accuracy",
    "whitespace_normalized_exact_match",
    "date_exact_match",
    "currency_percent_unit_match",
    "identifier_exact_match",
    "block_detection_precision_iou50",
    "block_detection_recall_iou50",
    "block_type_macro_f1_iou50",
    "reading_order_kendall_tau",
    "reading_order_spearman_rho",
    "header_footer_precision_iou50",
    "header_footer_recall_iou50",
    "caption_association_accuracy",
    "heading_text_f1",
    "heading_level_accuracy",
    "heading_hierarchy_edit_distance",
    "table_row_count_accuracy",
    "table_column_count_accuracy",
    "table_cell_edit_score",
    "table_span_accuracy",
    "multi_page_table_merge_accuracy",
    "formula_exact_match",
    "formula_symbol_edit_distance",
    "equation_block_precision_iou50",
    "equation_block_recall_iou50",
    "source_page_accuracy",
    "source_bbox_iou",
    "note_split_precision",
    "note_split_recall",
    "title_quality_human_score",
    "duplicate_note_rate",
    "unsupported_summary_claim_rate",
    "relation_precision",
    "evidence_completeness",
    "conflict_detection_recall",
    "user_edit_distance",
    "review_time_ms",
    "rag_recall_at_5",
    "rag_recall_at_10",
    "rag_mrr",
    "rag_ndcg_at_10",
    "rag_citation_precision",
    "rag_citation_recall",
    "rag_answer_groundedness",
    "rag_stale_version_rejection",
    "rag_unanswerable_refusal_accuracy",
    "rag_multihop_evidence_completeness",
    "router_first_pass_acceptance_rate",
    "router_escalation_recall",
    "router_false_escalation_rate",
    "router_fallback_rate",
    "router_quality_after_escalation",
    "router_route_regret",
)

MAP_METRIC_KEYS = (
    "router_cost_per_page_by_class",
    "router_latency_ms_per_page_by_class",
)

MASTERPLAN_METRIC_KEYS = SCALAR_METRIC_KEYS + MAP_METRIC_KEYS

_IDENTIFIER_FIELDS = ("serials", "models", "versions")
_UNIT_FIELDS = ("currencies", "percentages", "units")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _scalar(value: str) -> str:
    return " ".join(_normalize(value).split())


def _levenshtein(reference: Sequence[Any], candidate: Sequence[Any]) -> int:
    if len(reference) < len(candidate):
        reference, candidate = candidate, reference
    previous = list(range(len(candidate) + 1))
    for row_index, left in enumerate(reference, start=1):
        current = [row_index]
        for column_index, right in enumerate(candidate, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column_index] + 1,
                    previous[column_index - 1] + (left != right),
                )
            )
        previous = current
    return previous[-1]


def _error_rate(reference: Sequence[Any], candidate: Sequence[Any]) -> float:
    if not reference:
        return 0.0 if not candidate else 1.0
    return _levenshtein(reference, candidate) / len(reference)


def _similarity(reference: str, candidate: str) -> float:
    left = _normalize(reference)
    right = _normalize(candidate)
    return max(0.0, 1.0 - _levenshtein(left, right) / max(len(left), len(right), 1))


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _prf(expected: set[Any], actual: set[Any]) -> tuple[float, float, float]:
    true_positive = len(expected & actual)
    precision = 1.0 if not actual and not expected else _ratio(true_positive, len(actual))
    recall = 1.0 if not expected else _ratio(true_positive, len(expected))
    f1 = 0.0 if precision + recall == 0.0 else 2.0 * precision * recall / (precision + recall)
    return precision, recall, f1


def _string_sequence(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        result.append(_scalar(item))
    return tuple(result)


def _annotation_exact(
    truth: Mapping[str, Any],
    output: Mapping[str, Any],
    fields: Sequence[str],
) -> float | None:
    expected_annotations = truth.get("token_annotations")
    actual_annotations = output.get("token_annotations")
    if not isinstance(expected_annotations, Mapping):
        if fields == ("dates",):
            expected_annotations = truth.get("date_unit_annotations")
            actual_annotations = output.get("date_unit_annotations")
        elif fields == _UNIT_FIELDS:
            legacy_expected = truth.get("date_unit_annotations")
            legacy_actual = output.get("date_unit_annotations")
            if isinstance(legacy_expected, Mapping) and "units" in legacy_expected:
                expected_annotations = {"units": legacy_expected["units"]}
                actual_annotations = (
                    {"units": legacy_actual.get("units")}
                    if isinstance(legacy_actual, Mapping)
                    else {}
                )
    if not isinstance(expected_annotations, Mapping):
        return None
    active = [field for field in fields if field in expected_annotations]
    if not active:
        return None
    actual_mapping = actual_annotations if isinstance(actual_annotations, Mapping) else {}
    for field in active:
        expected = _string_sequence(expected_annotations.get(field))
        actual = _string_sequence(actual_mapping.get(field, []))
        if expected is None:
            return None
        if actual is None or expected != actual:
            return 0.0
    return 1.0


def _hangul_syllables(value: str) -> list[str]:
    return [character for character in _normalize(value) if "\uac00" <= character <= "\ud7a3"]


def _hangul_jamo(value: str) -> list[str]:
    decomposed = unicodedata.normalize("NFD", value)
    return [
        character
        for character in decomposed
        if ("\u1100" <= character <= "\u11ff")
        or ("\u3130" <= character <= "\u318f")
        or ("\ua960" <= character <= "\ua97f")
        or ("\ud7b0" <= character <= "\ud7ff")
    ]


def _punctuation(value: str) -> list[str]:
    return [
        character
        for character in _normalize(value)
        if unicodedata.category(character).startswith("P")
    ]


def _text_metrics(truth: Mapping[str, Any], output: Mapping[str, Any]) -> dict[str, MetricValue]:
    reference = str(truth.get("text") or "")
    candidate = str(output.get("text") or "")
    reference_syllables = _hangul_syllables(reference)
    reference_jamo = _hangul_jamo(reference)
    punctuation = _punctuation(reference)
    return {
        "hangul_syllable_corruption_rate": (
            _error_rate(reference_syllables, _hangul_syllables(candidate))
            if reference_syllables
            else None
        ),
        "hangul_jamo_corruption_rate": (
            _error_rate(reference_jamo, _hangul_jamo(candidate)) if reference_jamo else None
        ),
        "punctuation_accuracy": (
            max(0.0, 1.0 - _error_rate(punctuation, _punctuation(candidate)))
            if punctuation
            else None
        ),
        "whitespace_normalized_exact_match": float(_scalar(reference) == _scalar(candidate)),
        "date_exact_match": _annotation_exact(truth, output, ("dates",)),
        "currency_percent_unit_match": _annotation_exact(truth, output, _UNIT_FIELDS),
        "identifier_exact_match": _annotation_exact(truth, output, _IDENTIFIER_FIELDS),
    }


def _valid_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
    ):
        return None
    left, top, right, bottom = (float(item) for item in value)
    if not (0.0 <= left < right <= 1000.0 and 0.0 <= top < bottom <= 1000.0):
        return None
    return left, top, right, bottom


def _bbox_iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    intersection_width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    intersection_height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = intersection_width * intersection_height
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    return _ratio(intersection, left_area + right_area - intersection)


def _block_geometry(block: Any) -> tuple[int, tuple[float, float, float, float]] | None:
    if not isinstance(block, Mapping):
        return None
    refs = block.get("source_refs")
    if not isinstance(refs, list) or not refs or not isinstance(refs[0], Mapping):
        return None
    ref = refs[0]
    page = ref.get("page_index", ref.get("pageIndex", ref.get("page_number", 1)))
    bbox = _valid_bbox(ref.get("bbox1000"))
    if isinstance(page, bool) or not isinstance(page, int) or bbox is None:
        return None
    return page, bbox


def _blocks_share_source_page(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> bool:
    expected_geometry = _block_geometry(expected)
    actual_geometry = _block_geometry(actual)
    return (
        expected_geometry is not None
        and actual_geometry is not None
        and expected_geometry[0] == actual_geometry[0]
    )


def _raw_blocks(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = document.get("blocks")
    return (
        [block for block in value if isinstance(block, Mapping)] if isinstance(value, list) else []
    )


def _greedy_matches(
    expected: Sequence[Mapping[str, Any]],
    actual: Sequence[Mapping[str, Any]],
    *,
    iou_threshold: float = 0.5,
) -> list[tuple[int, int, float]]:
    candidates: list[tuple[float, int, int]] = []
    for expected_index, expected_block in enumerate(expected):
        expected_geometry = _block_geometry(expected_block)
        if expected_geometry is None:
            continue
        for actual_index, actual_block in enumerate(actual):
            actual_geometry = _block_geometry(actual_block)
            if actual_geometry is None or actual_geometry[0] != expected_geometry[0]:
                continue
            iou = _bbox_iou(expected_geometry[1], actual_geometry[1])
            if iou >= iou_threshold:
                candidates.append((iou, expected_index, actual_index))
    matched_expected: set[int] = set()
    matched_actual: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for iou, expected_index, actual_index in sorted(
        candidates,
        key=lambda item: (-item[0], item[1], item[2]),
    ):
        if expected_index in matched_expected or actual_index in matched_actual:
            continue
        matched_expected.add(expected_index)
        matched_actual.add(actual_index)
        matches.append((expected_index, actual_index, iou))
    return matches


def _macro_f1(
    expected: Sequence[Mapping[str, Any]],
    actual: Sequence[Mapping[str, Any]],
    matches: Sequence[tuple[int, int, float]],
) -> float | None:
    labels = {
        str(block.get("type"))
        for block in [*expected, *actual]
        if isinstance(block.get("type"), str)
    }
    if not labels:
        return None
    matched_pairs = {(left, right) for left, right, _ in matches}
    scores: list[float] = []
    for label in sorted(labels):
        expected_indexes = {
            index for index, block in enumerate(expected) if block.get("type") == label
        }
        actual_indexes = {index for index, block in enumerate(actual) if block.get("type") == label}
        true_positive = sum(
            1
            for expected_index, actual_index in matched_pairs
            if expected_index in expected_indexes and actual_index in actual_indexes
        )
        precision = _ratio(true_positive, len(actual_indexes)) if actual_indexes else 0.0
        recall = _ratio(true_positive, len(expected_indexes)) if expected_indexes else 0.0
        scores.append(
            0.0 if precision + recall == 0.0 else 2.0 * precision * recall / (precision + recall)
        )
    return sum(scores) / len(scores)


def _rank_correlations(reference: Any, candidate: Any) -> tuple[float | None, float | None]:
    if (
        not isinstance(reference, list)
        or not isinstance(candidate, list)
        or len(reference) < 2
        or len(set(reference)) != len(reference)
        or len(set(candidate)) != len(candidate)
    ):
        return None, None
    candidate_positions = {item: index for index, item in enumerate(candidate)}
    if any(item not in candidate_positions for item in reference):
        return 0.0, 0.0
    inversions = 0
    pair_count = 0
    for left_index, left in enumerate(reference):
        for right in reference[left_index + 1 :]:
            pair_count += 1
            inversions += int(candidate_positions[left] > candidate_positions[right])
    kendall = 1.0 - 2.0 * _ratio(inversions, pair_count)
    rank_delta_squared = sum(
        (index - candidate_positions[item]) ** 2 for index, item in enumerate(reference)
    )
    count = len(reference)
    spearman = 1.0 - (6.0 * rank_delta_squared) / (count * (count * count - 1))
    return kendall, max(-1.0, min(1.0, spearman))


def _layout_metrics(
    truth: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, MetricValue]:
    expected = _raw_blocks(truth)
    actual = _raw_blocks(output)
    geometry_expected = [block for block in expected if _block_geometry(block) is not None]
    geometry_actual = [block for block in actual if _block_geometry(block) is not None]
    matches = _greedy_matches(geometry_expected, geometry_actual)
    geometry_available = bool(geometry_expected)
    precision = (
        _ratio(len(matches), len(geometry_actual))
        if geometry_available and geometry_actual
        else (0.0 if geometry_available else None)
    )
    recall = _ratio(len(matches), len(geometry_expected)) if geometry_available else None

    header_footer_types = {"header", "footer"}
    expected_hf = [block for block in expected if block.get("type") in header_footer_types]
    actual_hf = [block for block in actual if block.get("type") in header_footer_types]
    hf_matches = _greedy_matches(expected_hf, actual_hf)
    hf_precision = (
        _ratio(len(hf_matches), len(actual_hf))
        if expected_hf and actual_hf
        else (0.0 if expected_hf else None)
    )
    hf_recall = _ratio(len(hf_matches), len(expected_hf)) if expected_hf else None

    expected_captions = {
        (str(block.get("block_id")), str(block.get("caption_for_block_id")))
        for block in expected
        if block.get("block_id") and block.get("caption_for_block_id")
    }
    actual_captions = {
        (str(block.get("block_id")), str(block.get("caption_for_block_id")))
        for block in actual
        if block.get("block_id") and block.get("caption_for_block_id")
    }
    caption_accuracy = _prf(expected_captions, actual_captions)[2] if expected_captions else None
    kendall, spearman = _rank_correlations(
        truth.get("reading_order"),
        output.get("reading_order"),
    )
    return {
        "block_detection_precision_iou50": precision,
        "block_detection_recall_iou50": recall,
        "block_type_macro_f1_iou50": (
            _macro_f1(geometry_expected, geometry_actual, matches) if geometry_available else None
        ),
        "reading_order_kendall_tau": kendall,
        "reading_order_spearman_rho": spearman,
        "header_footer_precision_iou50": hf_precision,
        "header_footer_recall_iou50": hf_recall,
        "caption_association_accuracy": caption_accuracy,
        "source_page_accuracy": (
            sum(
                1
                for left, right, _ in matches
                if _blocks_share_source_page(
                    geometry_expected[left],
                    geometry_actual[right],
                )
            )
            / len(geometry_expected)
            if geometry_available
            else None
        ),
        "source_bbox_iou": (
            sum(iou for _, _, iou in matches) / len(geometry_expected)
            if geometry_available
            else None
        ),
    }


def _headings(document: Mapping[str, Any]) -> list[tuple[str, int]]:
    raw = document.get("heading_outline")
    if not isinstance(raw, list):
        raw = [
            block for block in _raw_blocks(document) if block.get("type") in {"title", "heading"}
        ]
    result: list[tuple[str, int]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        text = item.get("text")
        level = item.get("level", item.get("heading_level"))
        if (
            isinstance(text, str)
            and text.strip()
            and isinstance(level, int)
            and not isinstance(level, bool)
            and 1 <= level <= 6
        ):
            result.append((_scalar(text), level))
    return result


def _heading_metrics(
    truth: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, MetricValue]:
    expected = _headings(truth)
    if not expected:
        return {
            "heading_text_f1": None,
            "heading_level_accuracy": None,
            "heading_hierarchy_edit_distance": None,
        }
    actual = _headings(output)
    expected_text = Counter(text for text, _ in expected)
    actual_text = Counter(text for text, _ in actual)
    overlap = sum((expected_text & actual_text).values())
    precision = _ratio(overlap, sum(actual_text.values())) if actual_text else 0.0
    recall = _ratio(overlap, sum(expected_text.values()))
    text_f1 = 0.0 if precision + recall == 0.0 else 2.0 * precision * recall / (precision + recall)
    actual_by_text: dict[str, list[int]] = defaultdict(list)
    for text, level in actual:
        actual_by_text[text].append(level)
    matched_levels = 0
    seen: Counter[str] = Counter()
    for text, level in expected:
        position = seen[text]
        seen[text] += 1
        levels = actual_by_text.get(text, [])
        matched_levels += int(position < len(levels) and levels[position] == level)
    hierarchy_distance = _error_rate(expected, actual)
    return {
        "heading_text_f1": text_f1,
        "heading_level_accuracy": matched_levels / len(expected),
        "heading_hierarchy_edit_distance": hierarchy_distance,
    }


def _tables(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = document.get("tables")
    if isinstance(raw, list):
        return [table for table in raw if isinstance(table, Mapping)]
    result: list[Mapping[str, Any]] = []
    for block in _raw_blocks(document):
        if block.get("type") != "table":
            continue
        table = block.get("table")
        if isinstance(table, Mapping):
            result.append(table)
    return result


def _table_cells(table: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    cells = table.get("cells")
    return [cell for cell in cells if isinstance(cell, Mapping)] if isinstance(cells, list) else []


def _paired_average(
    expected: Sequence[Mapping[str, Any]],
    actual: Sequence[Mapping[str, Any]],
    scorer: Any,
) -> float:
    count = max(len(expected), len(actual))
    if count == 0:
        return 0.0
    return (
        sum(
            scorer(expected[index], actual[index])
            if index < len(expected) and index < len(actual)
            else 0.0
            for index in range(count)
        )
        / count
    )


def _table_metrics(
    truth: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, MetricValue]:
    expected = _tables(truth)
    if not expected:
        return {
            "table_row_count_accuracy": None,
            "table_column_count_accuracy": None,
            "table_cell_edit_score": None,
            "table_span_accuracy": None,
            "multi_page_table_merge_accuracy": None,
        }
    actual = _tables(output)

    def exact_field(field: str) -> float:
        return _paired_average(
            expected,
            actual,
            lambda left, right: float(left.get(field) == right.get(field)),
        )

    def cell_edit(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
        expected_cells = _table_cells(left)
        actual_cells = _table_cells(right)
        count = max(len(expected_cells), len(actual_cells))
        if not count:
            return 1.0
        total = 0.0
        for index in range(count):
            if index >= len(expected_cells) or index >= len(actual_cells):
                continue
            left_text = str(expected_cells[index].get("text") or "")
            right_text = str(actual_cells[index].get("text") or "")
            total += _similarity(left_text, right_text)
        return total / count

    def span_exact(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
        expected_spans = [
            (
                cell.get("row_index0"),
                cell.get("column_index0"),
                cell.get("row_span"),
                cell.get("column_span"),
            )
            for cell in _table_cells(left)
        ]
        actual_spans = [
            (
                cell.get("row_index0"),
                cell.get("column_index0"),
                cell.get("row_span"),
                cell.get("column_span"),
            )
            for cell in _table_cells(right)
        ]
        count = max(len(expected_spans), len(actual_spans), 1)
        return sum((Counter(expected_spans) & Counter(actual_spans)).values()) / count

    expected_merges = _edge_set(truth.get("multi_page_table_merges"))
    actual_merges = _edge_set(output.get("multi_page_table_merges"))
    return {
        "table_row_count_accuracy": exact_field("row_count"),
        "table_column_count_accuracy": exact_field("column_count"),
        "table_cell_edit_score": _paired_average(expected, actual, cell_edit),
        "table_span_accuracy": _paired_average(expected, actual, span_exact),
        "multi_page_table_merge_accuracy": (
            _prf(expected_merges, actual_merges or set())[2]
            if expected_merges is not None
            else None
        ),
    }


def _formulas(document: Mapping[str, Any]) -> list[str]:
    raw = document.get("formulas")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str)]
    result: list[str] = []
    for block in _raw_blocks(document):
        if block.get("type") != "formula":
            continue
        value = block.get("formula_latex", block.get("latex"))
        if isinstance(value, str):
            result.append(value)
    return result


def _normalize_formula(value: str) -> str:
    normalized = _normalize(value).strip()
    normalized = re.sub(r"\\(?:left|right)\b", "", normalized)
    return "".join(normalized.replace("$$", "").strip("$").split())


def _formula_metrics(
    truth: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, MetricValue]:
    expected = [_normalize_formula(value) for value in _formulas(truth)]
    if not expected:
        return {
            "formula_exact_match": None,
            "formula_symbol_edit_distance": None,
            "equation_block_precision_iou50": None,
            "equation_block_recall_iou50": None,
        }
    actual = [_normalize_formula(value) for value in _formulas(output)]
    count = max(len(expected), len(actual))
    exact = (
        sum(
            int(index < len(actual) and value == actual[index])
            for index, value in enumerate(expected)
        )
        / count
    )
    symbol_distance = (
        sum(
            _error_rate(list(value), list(actual[index])) if index < len(actual) else 1.0
            for index, value in enumerate(expected)
        )
        / count
    )
    expected_blocks = [block for block in _raw_blocks(truth) if block.get("type") == "formula"]
    actual_blocks = [block for block in _raw_blocks(output) if block.get("type") == "formula"]
    detection_available = any(_block_geometry(block) for block in expected_blocks)
    matches = _greedy_matches(expected_blocks, actual_blocks) if detection_available else []
    return {
        "formula_exact_match": exact,
        "formula_symbol_edit_distance": symbol_distance,
        "equation_block_precision_iou50": (
            _ratio(len(matches), len(actual_blocks))
            if detection_available and actual_blocks
            else (0.0 if detection_available else None)
        ),
        "equation_block_recall_iou50": (
            _ratio(len(matches), len(expected_blocks)) if detection_available else None
        ),
    }


def _edge_set(value: Any) -> set[tuple[str, ...]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    edges: set[tuple[str, ...]] = set()
    for item in value:
        if isinstance(item, list) and item and all(isinstance(part, str) for part in item):
            edges.add(tuple(item))
        elif isinstance(item, Mapping):
            parts = tuple(
                str(item[key])
                for key in ("source", "target", "type")
                if isinstance(item.get(key), str)
            )
            if len(parts) >= 2:
                edges.add(parts)
            else:
                return None
        else:
            return None
    return edges


def _note_signatures(value: Any) -> set[frozenset[str]] | None:
    if not isinstance(value, list):
        return None
    result: set[frozenset[str]] = set()
    for note in value:
        if not isinstance(note, Mapping):
            return None
        refs = note.get("source_block_ids")
        if not isinstance(refs, list) or not refs or not all(isinstance(ref, str) for ref in refs):
            return None
        result.add(frozenset(refs))
    return result


def _verified_human_score(output: Mapping[str, Any], name: str) -> float | None:
    metrics = output.get("verified_human_metrics")
    if not isinstance(metrics, Mapping):
        return None
    record = metrics.get(name)
    if not isinstance(record, Mapping):
        return None
    value = record.get("value")
    reviewers = record.get("reviewer_count")
    rubric = record.get("rubric_version")
    evidence_sha256 = record.get("evidence_sha256")
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
        and isinstance(reviewers, int)
        and not isinstance(reviewers, bool)
        and reviewers >= 2
        and isinstance(rubric, str)
        and rubric.strip()
        and isinstance(evidence_sha256, str)
        and _SHA256.fullmatch(evidence_sha256)
    ):
        return float(value)
    return None


def _knowledge_metrics(
    truth: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, MetricValue]:
    expected = truth.get("knowledge_evaluation")
    actual = output.get("knowledge_evaluation")
    if not isinstance(expected, Mapping):
        return {
            "note_split_precision": None,
            "note_split_recall": None,
            "title_quality_human_score": _verified_human_score(output, "title_quality_human_score"),
            "duplicate_note_rate": None,
            "unsupported_summary_claim_rate": None,
            "relation_precision": None,
            "evidence_completeness": None,
            "conflict_detection_recall": None,
            "user_edit_distance": None,
        }
    actual_mapping = actual if isinstance(actual, Mapping) else {}
    expected_notes = _note_signatures(expected.get("notes"))
    actual_notes = _note_signatures(actual_mapping.get("notes"))
    if expected_notes is None:
        note_precision = note_recall = None
    else:
        note_precision, note_recall, _ = _prf(expected_notes, actual_notes or set())
    raw_actual_notes = actual_mapping.get("notes")
    note_list = (
        [note for note in raw_actual_notes if isinstance(note, Mapping)]
        if isinstance(raw_actual_notes, list)
        else []
    )
    signatures = [
        (
            _scalar(str(note.get("title") or "")).casefold(),
            tuple(sorted(str(ref) for ref in note.get("source_block_ids") or [])),
        )
        for note in note_list
    ]
    duplicate_rate = (
        _ratio(len(signatures) - len(set(signatures)), len(signatures)) if signatures else 0.0
    )
    evidence_complete = (
        _ratio(
            sum(
                bool(note.get("source_block_ids"))
                and all(isinstance(ref, str) and ref for ref in note.get("source_block_ids", []))
                for note in note_list
            ),
            len(note_list),
        )
        if note_list
        else (0.0 if expected_notes else None)
    )
    claims = actual_mapping.get("summary_claims")
    available_ids = {
        str(block.get("block_id")) for block in _raw_blocks(output) if block.get("block_id")
    }
    unsupported = None
    if isinstance(claims, list):
        unsupported_count = 0
        for claim in claims:
            refs = claim.get("source_block_ids") if isinstance(claim, Mapping) else None
            unsupported_count += int(
                not isinstance(refs, list)
                or not refs
                or not set(str(ref) for ref in refs).issubset(available_ids)
            )
        unsupported = _ratio(unsupported_count, len(claims)) if claims else 0.0
    expected_relations = _edge_set(expected.get("relations"))
    actual_relations = _edge_set(actual_mapping.get("relations"))
    relation_precision = (
        _prf(expected_relations, actual_relations or set())[0]
        if expected_relations is not None
        else None
    )
    expected_conflicts = _string_sequence(expected.get("conflicts"))
    actual_conflicts = _string_sequence(actual_mapping.get("conflicts"))
    conflict_recall = (
        _prf(set(expected_conflicts), set(actual_conflicts or ()))[1]
        if expected_conflicts is not None
        else None
    )
    edit_pair = actual_mapping.get("user_edit_pair")
    user_edit_distance = None
    if isinstance(edit_pair, Mapping):
        before = edit_pair.get("before")
        after = edit_pair.get("after")
        if isinstance(before, str) and isinstance(after, str):
            user_edit_distance = _error_rate(list(_normalize(before)), list(_normalize(after)))
    return {
        "note_split_precision": note_precision,
        "note_split_recall": note_recall,
        "title_quality_human_score": _verified_human_score(output, "title_quality_human_score"),
        "duplicate_note_rate": duplicate_rate,
        "unsupported_summary_claim_rate": unsupported,
        "relation_precision": relation_precision,
        "evidence_completeness": evidence_complete,
        "conflict_detection_recall": conflict_recall,
        "user_edit_distance": user_edit_distance,
    }


def _dcg(relevances: Sequence[float]) -> float:
    return sum(value / math.log2(index + 2) for index, value in enumerate(relevances))


def _rag_metrics(
    truth: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, MetricValue]:
    expected = truth.get("rag_evaluation")
    actual = output.get("rag_evaluation")
    queries = expected.get("queries") if isinstance(expected, Mapping) else None
    actual_queries = actual.get("queries") if isinstance(actual, Mapping) else None
    if not isinstance(queries, list):
        return {key: None for key in SCALAR_METRIC_KEYS if key.startswith("rag_")}
    actual_by_id = {
        str(item.get("query_id")): item
        for item in actual_queries or []
        if isinstance(item, Mapping) and item.get("query_id")
    }
    recalls5: list[float] = []
    recalls10: list[float] = []
    reciprocals: list[float] = []
    ndcgs: list[float] = []
    citation_precisions: list[float] = []
    citation_recalls: list[float] = []
    groundedness: list[float] = []
    stale_rejections: list[float] = []
    refusals: list[float] = []
    multihop: list[float] = []
    for query in queries:
        if not isinstance(query, Mapping) or not query.get("query_id"):
            continue
        actual_query = actual_by_id.get(str(query["query_id"]), {})
        relevant = _string_sequence(query.get("relevant_ids"))
        retrieved = _string_sequence(actual_query.get("retrieved_ids")) or ()
        if relevant is not None:
            relevant_set = set(relevant)
            recalls5.append(_ratio(len(relevant_set & set(retrieved[:5])), len(relevant_set)))
            recalls10.append(_ratio(len(relevant_set & set(retrieved[:10])), len(relevant_set)))
            rank = next(
                (index for index, item in enumerate(retrieved, start=1) if item in relevant_set),
                None,
            )
            reciprocals.append(0.0 if rank is None else 1.0 / rank)
            relevances = [float(item in relevant_set) for item in retrieved[:10]]
            ideal = [1.0] * min(len(relevant_set), 10)
            ideal_dcg = _dcg(ideal)
            ndcgs.append(_ratio(_dcg(relevances), ideal_dcg) if ideal_dcg else 0.0)
        expected_citations = _string_sequence(query.get("citation_ids"))
        actual_citations = _string_sequence(actual_query.get("citation_ids")) or ()
        if expected_citations is not None:
            precision, recall, _ = _prf(set(expected_citations), set(actual_citations))
            citation_precisions.append(precision)
            citation_recalls.append(recall)
        claims = actual_query.get("answer_claims")
        if isinstance(claims, list):
            supported = 0
            for claim in claims:
                refs = claim.get("citation_ids") if isinstance(claim, Mapping) else None
                supported += int(
                    isinstance(refs, list)
                    and bool(refs)
                    and set(str(ref) for ref in refs).issubset(set(actual_citations))
                )
            groundedness.append(_ratio(supported, len(claims)) if claims else 1.0)
        stale_ids = _string_sequence(query.get("stale_version_ids"))
        rejected_ids = _string_sequence(actual_query.get("rejected_version_ids")) or ()
        if stale_ids is not None:
            stale_rejections.append(_prf(set(stale_ids), set(rejected_ids))[1])
        if isinstance(query.get("unanswerable"), bool):
            refusals.append(float(bool(actual_query.get("refused")) == query["unanswerable"]))
        required_hops = query.get("required_evidence_groups")
        if isinstance(required_hops, list):
            groups = [
                set(str(item) for item in group)
                for group in required_hops
                if isinstance(group, list) and group
            ]
            if groups:
                cited = set(actual_citations)
                multihop.append(_ratio(sum(bool(group & cited) for group in groups), len(groups)))

    def average(values: Sequence[float]) -> float | None:
        return sum(values) / len(values) if values else None

    return {
        "rag_recall_at_5": average(recalls5),
        "rag_recall_at_10": average(recalls10),
        "rag_mrr": average(reciprocals),
        "rag_ndcg_at_10": average(ndcgs),
        "rag_citation_precision": average(citation_precisions),
        "rag_citation_recall": average(citation_recalls),
        "rag_answer_groundedness": average(groundedness),
        "rag_stale_version_rejection": average(stale_rejections),
        "rag_unanswerable_refusal_accuracy": average(refusals),
        "rag_multihop_evidence_completeness": average(multihop),
    }


def _finite_nonnegative(value: Any) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    ):
        return float(value)
    return None


def _router_metrics(
    truth: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, MetricValue]:
    expected = truth.get("router_evaluation")
    actual = output.get("router_evaluation")
    pages = actual.get("pages") if isinstance(actual, Mapping) else None
    if not isinstance(expected, Mapping) or not isinstance(pages, list):
        return {
            "router_first_pass_acceptance_rate": None,
            "router_escalation_recall": None,
            "router_false_escalation_rate": None,
            "router_fallback_rate": None,
            "router_quality_after_escalation": None,
            "router_cost_per_page_by_class": None,
            "router_latency_ms_per_page_by_class": None,
            "router_route_regret": None,
        }
    valid_pages = [page for page in pages if isinstance(page, Mapping)]
    if not valid_pages:
        return {
            "router_first_pass_acceptance_rate": 0.0,
            "router_escalation_recall": 0.0,
            "router_false_escalation_rate": 0.0,
            "router_fallback_rate": 0.0,
            "router_quality_after_escalation": None,
            "router_cost_per_page_by_class": {},
            "router_latency_ms_per_page_by_class": {},
            "router_route_regret": None,
        }
    failures = [page for page in valid_pages if bool(page.get("first_pass_failed"))]
    nonfailures = [page for page in valid_pages if not bool(page.get("first_pass_failed"))]
    escalated = [page for page in valid_pages if bool(page.get("escalated"))]
    quality_values = [
        value
        for page in escalated
        if (value := _finite_nonnegative(page.get("quality_after_escalation"))) is not None
        and value <= 1.0
    ]
    regrets = [
        max(0.0, best - chosen)
        for page in valid_pages
        if (best := _finite_nonnegative(page.get("best_route_quality"))) is not None
        and (chosen := _finite_nonnegative(page.get("chosen_route_quality"))) is not None
    ]
    cost_buckets: dict[str, list[float]] = defaultdict(list)
    latency_buckets: dict[str, list[float]] = defaultdict(list)
    for page in valid_pages:
        document_class = page.get("document_class")
        if not isinstance(document_class, str) or not document_class:
            continue
        cost = _finite_nonnegative(page.get("variable_cost"))
        latency = _finite_nonnegative(page.get("latency_ms"))
        if cost is not None:
            cost_buckets[document_class].append(cost)
        if latency is not None:
            latency_buckets[document_class].append(latency)
    costs = {key: sum(values) / len(values) for key, values in sorted(cost_buckets.items())}
    latencies = {key: sum(values) / len(values) for key, values in sorted(latency_buckets.items())}
    return {
        "router_first_pass_acceptance_rate": _ratio(
            sum(not bool(page.get("first_pass_failed")) for page in valid_pages),
            len(valid_pages),
        ),
        "router_escalation_recall": (
            _ratio(sum(bool(page.get("escalated")) for page in failures), len(failures))
            if failures
            else None
        ),
        "router_false_escalation_rate": (
            _ratio(sum(bool(page.get("escalated")) for page in nonfailures), len(nonfailures))
            if nonfailures
            else None
        ),
        "router_fallback_rate": _ratio(
            sum(bool(page.get("fallback")) for page in valid_pages),
            len(valid_pages),
        ),
        "router_quality_after_escalation": (
            sum(quality_values) / len(quality_values) if quality_values else None
        ),
        "router_cost_per_page_by_class": costs or None,
        "router_latency_ms_per_page_by_class": latencies or None,
        "router_route_regret": sum(regrets) / len(regrets) if regrets else None,
    }


def evaluate_masterplan_metrics(
    truth: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, MetricValue]:
    """Return every section 22.4-22.7 metric with explicit unavailable values."""

    metrics: dict[str, MetricValue] = {key: None for key in MASTERPLAN_METRIC_KEYS}
    for evaluator in (
        _text_metrics,
        _layout_metrics,
        _heading_metrics,
        _table_metrics,
        _formula_metrics,
        _knowledge_metrics,
        _rag_metrics,
        _router_metrics,
    ):
        metrics.update(evaluator(truth, output))
    return metrics
