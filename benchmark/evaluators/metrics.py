"""Dependency-free benchmark metrics with explicit unavailable values."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from benchmark.evaluators.masterplan_metrics import (
    MetricValue,
    evaluate_masterplan_metrics,
)

NUMBER = re.compile(
    r"(?<![\d.,])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\d.,])"
)
WORD = re.compile(r"\w+|[^\w\s]", re.UNICODE)
SEVERE_TABLE_SCORE_THRESHOLD = 0.50
RUNTIME_METRIC_KEYS = frozenset(
    {
        "latency_ms",
        "p50_latency_ms",
        "p95_latency_ms",
        "cold_start_ms",
        "gpu_seconds",
        "peak_vram_mb",
        "estimated_cost_usd",
        "normalized_speed",
        "review_time_ms",
    }
)
_MISSING = object()


@dataclass(frozen=True)
class _TableCell:
    row_index0: int
    column_index0: int
    row_span: int
    column_span: int
    text: str


@dataclass(frozen=True)
class _Table:
    row_count: int
    column_count: int
    header_row_count: int
    cells: tuple[_TableCell, ...]


@dataclass(frozen=True)
class _Heading:
    level: int
    text: str


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _normalize_scalar(value: str) -> str:
    return " ".join(normalize_text(value).split())


def levenshtein(reference: Sequence[Any], candidate: Sequence[Any]) -> int:
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


def error_rate(reference: Sequence[Any], candidate: Sequence[Any]) -> float:
    if not reference:
        return 0.0 if not candidate else 1.0
    return levenshtein(reference, candidate) / len(reference)


def character_error_rate(reference: str, candidate: str) -> float:
    return error_rate(list(normalize_text(reference)), list(normalize_text(candidate)))


def word_error_rate(reference: str, candidate: str) -> float:
    return error_rate(
        WORD.findall(normalize_text(reference)),
        WORD.findall(normalize_text(candidate)),
    )


def normalized_edit_similarity(reference: str, candidate: str) -> float:
    left = normalize_text(reference)
    right = normalize_text(candidate)
    denominator = max(len(left), len(right), 1)
    return max(0.0, 1.0 - levenshtein(left, right) / denominator)


def numeric_tokens(value: str) -> list[str]:
    return [token.replace(",", "") for token in NUMBER.findall(normalize_text(value))]


def numeric_exact_match(reference: str, candidate: str) -> float:
    expected = numeric_tokens(reference)
    actual = numeric_tokens(candidate)
    return 1.0 if expected == actual else 0.0


def reading_order_pair_accuracy(reference: Sequence[str], candidate: Sequence[str]) -> float:
    if len(reference) < 2:
        return 1.0 if list(reference) == list(candidate)[: len(reference)] else 0.0
    candidate_position = {block_id: index for index, block_id in enumerate(candidate)}
    correct = 0
    total = 0
    for left_index, left in enumerate(reference):
        for right in reference[left_index + 1 :]:
            total += 1
            if left in candidate_position and right in candidate_position:
                correct += int(candidate_position[left] < candidate_position[right])
    return correct / total


def _first_present(value: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in value:
            return value[name]
    return _MISSING


def _strict_int(value: Any, *, minimum: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return int(value)


def _canonical_table(value: Any) -> _Table | None:
    if not isinstance(value, Mapping):
        return None
    row_count = _strict_int(_first_present(value, "row_count", "rowCount"), minimum=1)
    column_count = _strict_int(_first_present(value, "column_count", "columnCount"), minimum=1)
    header_row_count = _strict_int(_first_present(value, "header_row_count", "headerRowCount"))
    raw_cells = value.get("cells")
    if (
        row_count is None
        or column_count is None
        or header_row_count is None
        or header_row_count > row_count
        or not isinstance(raw_cells, list)
        or not raw_cells
    ):
        return None

    cells: list[_TableCell] = []
    occupied: set[tuple[int, int]] = set()
    for raw_cell in raw_cells:
        if not isinstance(raw_cell, Mapping):
            return None
        row_index0 = _strict_int(_first_present(raw_cell, "row_index0", "row_index", "rowIndex0"))
        column_index0 = _strict_int(
            _first_present(
                raw_cell,
                "column_index0",
                "column_index",
                "columnIndex0",
            )
        )
        row_span = _strict_int(_first_present(raw_cell, "row_span", "rowSpan"), minimum=1)
        column_span = _strict_int(_first_present(raw_cell, "column_span", "columnSpan"), minimum=1)
        text = _first_present(
            raw_cell,
            "normalized_text",
            "normalizedText",
            "text",
            "raw_text",
            "rawText",
        )
        if (
            row_index0 is None
            or column_index0 is None
            or row_span is None
            or column_span is None
            or not isinstance(text, str)
            or row_index0 + row_span > row_count
            or column_index0 + column_span > column_count
        ):
            return None
        coordinates = {
            (row, column)
            for row in range(row_index0, row_index0 + row_span)
            for column in range(column_index0, column_index0 + column_span)
        }
        if coordinates & occupied:
            return None
        occupied.update(coordinates)
        cells.append(
            _TableCell(
                row_index0=row_index0,
                column_index0=column_index0,
                row_span=row_span,
                column_span=column_span,
                text=_normalize_scalar(text),
            )
        )
    cells.sort(
        key=lambda cell: (
            cell.row_index0,
            cell.column_index0,
            cell.row_span,
            cell.column_span,
            cell.text,
        )
    )
    return _Table(row_count, column_count, header_row_count, tuple(cells))


def _table_structure_tokens(table: _Table) -> tuple[tuple[Any, ...], ...]:
    tokens: list[tuple[Any, ...]] = [
        ("table", table.row_count, table.column_count, table.header_row_count)
    ]
    for row_index0 in range(table.row_count):
        tokens.append(("row", row_index0 < table.header_row_count))
        tokens.extend(
            (
                "cell",
                cell.column_index0,
                cell.row_span,
                cell.column_span,
            )
            for cell in table.cells
            if cell.row_index0 == row_index0
        )
        tokens.append(("end_row",))
    tokens.append(("end_table",))
    return tuple(tokens)


def _table_pair_average(
    reference: Sequence[_Table],
    candidate: Sequence[_Table | None],
    scorer: Callable[[_Table, _Table], float],
) -> float:
    pair_count = max(len(reference), len(candidate))
    total = 0.0
    for index in range(pair_count):
        if index < len(reference) and index < len(candidate) and candidate[index] is not None:
            candidate_table = candidate[index]
            assert candidate_table is not None
            total += scorer(reference[index], candidate_table)
    return total / pair_count


def table_structure_similarity(
    reference: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any] | None],
) -> float | None:
    """Score ordered table topology using a deterministic tree-token edit surrogate.

    This is deliberately not the official TEDS implementation. The public score-record
    key remains ``table_teds`` for contract compatibility, while the benchmark
    documentation identifies the exact local semantics.
    """

    reference_tables = [_canonical_table(table) for table in reference]
    if not reference_tables or any(table is None for table in reference_tables):
        return None
    candidate_tables = [_canonical_table(table) for table in candidate]

    def score(left: _Table, right: _Table) -> float:
        left_tokens = _table_structure_tokens(left)
        right_tokens = _table_structure_tokens(right)
        denominator = max(len(left_tokens), len(right_tokens), 1)
        return max(0.0, 1.0 - levenshtein(left_tokens, right_tokens) / denominator)

    return _table_pair_average(
        [table for table in reference_tables if table is not None],
        candidate_tables,
        score,
    )


def table_cell_exactness(
    reference: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any] | None],
) -> float | None:
    """Score exact coordinate/span/text cell matches, penalizing missing and extras."""

    reference_tables = [_canonical_table(table) for table in reference]
    if not reference_tables or any(table is None for table in reference_tables):
        return None
    candidate_tables = [_canonical_table(table) for table in candidate]

    def score(left: _Table, right: _Table) -> float:
        expected = Counter(left.cells)
        actual = Counter(right.cells)
        exact = sum((expected & actual).values())
        return exact / max(sum(expected.values()), sum(actual.values()), 1)

    return _table_pair_average(
        [table for table in reference_tables if table is not None],
        candidate_tables,
        score,
    )


def normalize_formula(value: str) -> str:
    """Normalize presentational LaTeX differences without changing identifiers."""

    normalized = normalize_text(value).strip()
    delimiters = (("$$", "$$"), (r"\[", r"\]"), (r"\(", r"\)"), ("$", "$"))
    for opening, closing in delimiters:
        if (
            normalized.startswith(opening)
            and normalized.endswith(closing)
            and len(normalized) >= len(opening) + len(closing)
        ):
            normalized = normalized[len(opening) : len(normalized) - len(closing)].strip()
            break
    normalized = re.sub(r"\\(?:left|right)\b", "", normalized)
    formula_translations: dict[str, str | int | None] = {
        "\N{MINUS SIGN}": "-",
        "\N{MULTIPLICATION SIGN}": r"\times",
        "\N{DIVISION SIGN}": r"\div",
        "\N{LESS-THAN OR EQUAL TO}": r"\le",
        "\N{GREATER-THAN OR EQUAL TO}": r"\ge",
        "\N{NOT EQUAL TO}": r"\ne",
    }
    normalized = normalized.translate(str.maketrans(formula_translations))
    return "".join(normalized.split())


def formula_normalized_edit_score(
    reference: Sequence[str],
    candidate: Sequence[str | None],
) -> float | None:
    """Average normalized character-edit similarity over formulas in reading order."""

    normalized_reference = [
        normalize_formula(value) if isinstance(value, str) and value.strip() else None
        for value in reference
    ]
    if not normalized_reference or any(value is None for value in normalized_reference):
        return None
    normalized_candidate = [
        normalize_formula(value) if isinstance(value, str) and value.strip() else None
        for value in candidate
    ]
    pair_count = max(len(normalized_reference), len(normalized_candidate))
    total = 0.0
    for index in range(pair_count):
        if (
            index < len(normalized_reference)
            and index < len(normalized_candidate)
            and normalized_candidate[index] is not None
        ):
            total += normalized_edit_similarity(
                normalized_reference[index] or "",
                normalized_candidate[index] or "",
            )
    return total / pair_count


def _canonical_heading(value: Any) -> _Heading | None:
    if not isinstance(value, Mapping):
        return None
    level = _strict_int(_first_present(value, "level", "heading_level", "headingLevel"), minimum=1)
    text = _first_present(
        value,
        "text",
        "normalized_text",
        "normalizedText",
        "raw_text",
        "rawText",
        "title",
    )
    if level is None or level > 6 or not isinstance(text, str) or not text.strip():
        return None
    return _Heading(level=level, text=_normalize_scalar(text))


def _weighted_levenshtein(
    reference: Sequence[_Heading],
    candidate: Sequence[_Heading | None],
) -> float:
    previous = [float(index) for index in range(len(candidate) + 1)]
    for row_index, left in enumerate(reference, start=1):
        current = [float(row_index)]
        for column_index, right in enumerate(candidate, start=1):
            if right is None:
                substitution_cost = 1.0
            else:
                level_cost = float(left.level != right.level)
                label_cost = 1.0 - normalized_edit_similarity(left.text, right.text)
                substitution_cost = (level_cost + label_cost) / 2
            current.append(
                min(
                    current[-1] + 1.0,
                    previous[column_index] + 1.0,
                    previous[column_index - 1] + substitution_cost,
                )
            )
        previous = current
    return previous[-1]


def heading_tree_score(
    reference: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any] | None],
) -> float | None:
    """Compare ordered heading labels and levels as a flat deterministic outline."""

    reference_headings = [_canonical_heading(heading) for heading in reference]
    if not reference_headings or any(heading is None for heading in reference_headings):
        return None
    candidate_headings = [_canonical_heading(heading) for heading in candidate]
    distance = _weighted_levenshtein(
        [heading for heading in reference_headings if heading is not None],
        candidate_headings,
    )
    denominator = max(len(reference_headings), len(candidate_headings), 1)
    return max(0.0, 1.0 - distance / denominator)


def _annotation_sequence(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        normalized.append(_normalize_scalar(item))
    return tuple(normalized)


def date_unit_exact_match(reference: Any, candidate: Any) -> float | None:
    """Compare explicit date and unit annotations without reusing numeric tokens."""

    if not isinstance(reference, Mapping):
        return None
    active_fields = [name for name in ("dates", "units") if name in reference]
    if not active_fields:
        return None
    expected: dict[str, tuple[str, ...]] = {}
    for name in active_fields:
        values = _annotation_sequence(reference[name])
        if values is None:
            return None
        expected[name] = values

    candidate_mapping = candidate if isinstance(candidate, Mapping) else {}
    for name in active_fields:
        if name not in candidate_mapping:
            actual: tuple[str, ...] = ()
        else:
            values = _annotation_sequence(candidate_mapping[name])
            if values is None:
                return 0.0
            actual = values
        if expected[name] != actual:
            return 0.0
    return 1.0


def _raw_tables(document: Mapping[str, Any]) -> tuple[bool, list[Any]]:
    if "tables" in document:
        tables = document["tables"]
        return True, list(tables) if isinstance(tables, list) else [None]
    blocks = document.get("blocks")
    if not isinstance(blocks, list):
        return False, []
    raw_tables: list[Any] = []
    for block in blocks:
        if not isinstance(block, Mapping) or block.get("type") != "table":
            continue
        nested = block.get("table")
        if isinstance(nested, Mapping):
            raw_tables.append(nested)
        elif any(name in block for name in ("row_count", "rowCount", "cells")):
            raw_tables.append(block)
        else:
            raw_tables.append(None)
    return bool(raw_tables), raw_tables


def _raw_formulas(document: Mapping[str, Any]) -> tuple[bool, list[Any]]:
    if "formulas" in document:
        raw_formulas = document["formulas"]
        return True, list(raw_formulas) if isinstance(raw_formulas, list) else [None]
    blocks = document.get("blocks")
    if not isinstance(blocks, list):
        return False, []
    formulas: list[Any] = []
    for block in blocks:
        if not isinstance(block, Mapping) or block.get("type") != "formula":
            continue
        formula = _first_present(block, "formula_latex", "formulaLatex", "latex")
        formulas.append(None if formula is _MISSING else formula)
    return bool(formulas), formulas


def _raw_headings(document: Mapping[str, Any]) -> tuple[bool, list[Any]]:
    if "heading_outline" in document:
        headings = document["heading_outline"]
        return True, list(headings) if isinstance(headings, list) else [None]
    blocks = document.get("blocks")
    if not isinstance(blocks, list):
        return False, []
    headings = [
        block
        for block in blocks
        if isinstance(block, Mapping) and block.get("type") in {"title", "heading"}
    ]
    return bool(headings), headings


def valid_bbox1000(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
        and all(0 <= item <= 1000 for item in value)
        and value[0] < value[2]
        and value[1] < value[3]
    )


def provenance_coverage(blocks: Sequence[dict[str, Any]]) -> float:
    if not blocks:
        return 1.0
    supported = 0
    for block in blocks:
        refs = block.get("source_refs")
        if (
            isinstance(refs, list)
            and refs
            and all(isinstance(ref, dict) and valid_bbox1000(ref.get("bbox1000")) for ref in refs)
        ):
            supported += 1
    return supported / len(blocks)


def unsupported_claim_rate(
    claims: Sequence[dict[str, Any]], available_block_ids: Iterable[str]
) -> float:
    if not claims:
        return 0.0
    available = set(available_block_ids)
    unsupported = 0
    for claim in claims:
        evidence = claim.get("source_block_ids")
        if not isinstance(evidence, list) or not evidence or not set(evidence).issubset(available):
            unsupported += 1
    return unsupported / len(claims)


def repetition_rate(value: str, ngram_size: int = 8) -> float:
    tokens = WORD.findall(normalize_text(value).lower())
    if len(tokens) < ngram_size:
        return 0.0
    ngrams = [
        tuple(tokens[index : index + ngram_size]) for index in range(len(tokens) - ngram_size + 1)
    ]
    counts = Counter(ngrams)
    repeated = sum(count - 1 for count in counts.values() if count > 1)
    return repeated / len(ngrams)


def _metric_float(metrics: Mapping[str, MetricValue], name: str) -> float | None:
    value = metrics.get(name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def score_case(
    truth: dict[str, Any],
    output: dict[str, Any],
    runtime_metrics: dict[str, float] | None = None,
) -> tuple[dict[str, MetricValue], list[str]]:
    expected_text = str(truth.get("text") or "")
    actual_text = str(output.get("text") or "")
    raw_blocks = output.get("blocks")
    blocks: list[dict[str, Any]] = (
        [block for block in raw_blocks if isinstance(block, dict)]
        if isinstance(raw_blocks, list)
        else []
    )
    raw_claims = output.get("generated_claims")
    claims: list[dict[str, Any]] = (
        [claim for claim in raw_claims if isinstance(claim, dict)]
        if isinstance(raw_claims, list)
        else []
    )
    raw_expected_blocks = truth.get("blocks")
    expected_blocks = raw_expected_blocks if isinstance(raw_expected_blocks, list) else []
    expected_block_ids = [
        str(block.get("block_id"))
        for block in expected_blocks
        if isinstance(block, Mapping) and block.get("block_id")
    ]
    actual_block_ids = [
        str(block.get("block_id"))
        for block in blocks
        if isinstance(block, Mapping) and block.get("block_id")
    ]
    available_block_ids = actual_block_ids

    expected_table_present, expected_tables = _raw_tables(truth)
    _, actual_tables = _raw_tables(output)
    if expected_table_present:
        table_structure = table_structure_similarity(expected_tables, actual_tables)
        cell_exactness = table_cell_exactness(expected_tables, actual_tables)
    else:
        table_structure = None
        cell_exactness = None

    expected_formula_present, expected_formulas = _raw_formulas(truth)
    _, actual_formulas = _raw_formulas(output)
    formula_score = (
        formula_normalized_edit_score(expected_formulas, actual_formulas)
        if expected_formula_present
        else None
    )

    expected_heading_present, expected_headings = _raw_headings(truth)
    _, actual_headings = _raw_headings(output)
    outline_score = (
        heading_tree_score(expected_headings, actual_headings) if expected_heading_present else None
    )

    expected_numbers = numeric_tokens(expected_text)
    actual_numbers = numeric_tokens(actual_text)
    number_score = (
        numeric_exact_match(expected_text, actual_text)
        if expected_numbers or actual_numbers
        else None
    )
    date_unit_score = date_unit_exact_match(
        truth.get("date_unit_annotations"),
        output.get("date_unit_annotations"),
    )

    metrics: dict[str, MetricValue] = {
        "schema_validity": 1.0,
        "cer": character_error_rate(expected_text, actual_text),
        "wer": word_error_rate(expected_text, actual_text),
        "normalized_edit_similarity": normalized_edit_similarity(expected_text, actual_text),
        "reading_order_pair_accuracy": reading_order_pair_accuracy(
            truth.get("reading_order") or expected_block_ids,
            output.get("reading_order") or actual_block_ids,
        ),
        "table_teds": table_structure,
        "table_cell_exactness": cell_exactness,
        "formula_edit_score": formula_score,
        "heading_tree_score": outline_score,
        "numeric_exact_match": number_score,
        "date_unit_exact_match": date_unit_score,
        "provenance_coverage": provenance_coverage(blocks),
        "unsupported_claim_rate": unsupported_claim_rate(claims, available_block_ids),
        "repetition_rate": repetition_rate(actual_text),
        "latency_ms": None,
        "p50_latency_ms": None,
        "p95_latency_ms": None,
        "cold_start_ms": None,
        "gpu_seconds": None,
        "peak_vram_mb": None,
        "estimated_cost_usd": None,
        "normalized_speed": None,
        **evaluate_masterplan_metrics(truth, output),
    }
    for key, value in (runtime_metrics or {}).items():
        numeric_value = (
            float(value)
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            else None
        )
        if (
            key in RUNTIME_METRIC_KEYS
            and numeric_value is not None
            and numeric_value >= 0.0
            and (key != "normalized_speed" or numeric_value <= 1.0)
        ):
            metrics[key] = numeric_value

    hard_failures: list[str] = []
    numeric_metric = _metric_float(metrics, "numeric_exact_match")
    date_unit_metric = _metric_float(metrics, "date_unit_exact_match")
    if truth.get("high_risk") and numeric_metric is not None and numeric_metric < 1.0:
        hard_failures.append("high_risk_numeric_below_threshold")
    if truth.get("high_risk") and date_unit_metric is not None and date_unit_metric < 1.0:
        hard_failures.append("high_risk_date_unit_below_threshold")
    available_table_scores = [
        score
        for name in ("table_teds", "table_cell_exactness")
        if (score := _metric_float(metrics, name)) is not None
    ]
    if available_table_scores and min(available_table_scores) < SEVERE_TABLE_SCORE_THRESHOLD:
        hard_failures.append("severe_table_error")
    unsupported_metric = _metric_float(metrics, "unsupported_claim_rate")
    if unsupported_metric is not None and unsupported_metric > 0:
        hard_failures.append("unsupported_statement")
    if not blocks and truth.get("blocks"):
        hard_failures.append("missing_page")
    repetition_metric = _metric_float(metrics, "repetition_rate")
    if repetition_metric is not None and repetition_metric > 0.10:
        hard_failures.append("repetition_loop")
    provenance_metric = _metric_float(metrics, "provenance_coverage")
    if provenance_metric is not None and provenance_metric < 1.0:
        hard_failures.append("provenance_below_threshold")
    return metrics, hard_failures


def utility(metrics: Mapping[str, MetricValue]) -> float | None:
    cer = _metric_float(metrics, "cer")
    unsupported = _metric_float(metrics, "unsupported_claim_rate")
    components: dict[str, float | None] = {
        "text_accuracy": None if cer is None else 1.0 - cer,
        "reading_order": _metric_float(metrics, "reading_order_pair_accuracy"),
        "table_accuracy": _metric_float(metrics, "table_teds"),
        "formula_accuracy": _metric_float(metrics, "formula_edit_score"),
        "structure_accuracy": _metric_float(metrics, "heading_tree_score"),
        "provenance_coverage": _metric_float(metrics, "provenance_coverage"),
        "hallucination_safety": (None if unsupported is None else 1.0 - unsupported),
        "normalized_speed": _metric_float(metrics, "normalized_speed"),
    }
    if any(value is None for value in components.values()):
        return None
    weights = {
        "text_accuracy": 0.22,
        "reading_order": 0.14,
        "table_accuracy": 0.14,
        "formula_accuracy": 0.08,
        "structure_accuracy": 0.12,
        "provenance_coverage": 0.12,
        "hallucination_safety": 0.10,
        "normalized_speed": 0.08,
    }
    return sum(value * weights[name] for name, value in components.items() if value is not None)
