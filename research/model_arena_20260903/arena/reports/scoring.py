"""Reading official evaluator output (``scores/**``) without inventing a metric.

Lane E2 is not this lane's to define, and each of the three evaluators names
its own metrics (masterplan section 12.1) rather than sharing one "overall"
field. :func:`headline_metric` therefore tries a short, documented list of
common spellings and returns the first one present; when none are, the cell
is ``n/a`` with the summary's actual key set attached, so a report never
prints a silently wrong number and a reader can see exactly what was on disk.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena.reports.common import Cell, na_reason, to_cell

__all__ = [
    "DOCUMENT_TYPE_FAMILIES",
    "HEADLINE_METRIC_CANDIDATES",
    "PROVENANCE_KEYS",
    "document_type_family",
    "headline_metric",
    "metric_rows",
]

# Priority order: the first key present in a benchmark's summary.json wins.
# OmniDocBench and olmOCR-Bench both publish an "overall" (masterplan 12.1);
# ParseBench's evaluator does not name one in the masterplan list, so the
# generic aggregate spellings are tried after it.
HEADLINE_METRIC_CANDIDATES: tuple[str, ...] = (
    "overall",
    "overall_score",
    "aggregate_score",
    "final_score",
    "score",
)

PROVENANCE_KEYS: frozenset[str] = frozenset({"schema", "provenance", "status"})

# Masterplan section 28.2's example families. A per_case row is matched
# against these by the first candidate field name/value that hits.
DOCUMENT_TYPE_FAMILIES: tuple[str, ...] = (
    "tables",
    "formula_math",
    "multi_column",
    "old_scan",
    "tiny_text",
    "header_footer",
    "chart",
    "enterprise_dense_text",
    "photo",
    "multilingual",
)

_FAMILY_ALIASES: dict[str, str] = {
    "table": "tables",
    "tables": "tables",
    "formula": "formula_math",
    "math": "formula_math",
    "formula_math": "formula_math",
    "arxiv_math": "formula_math",
    "multi_column": "multi_column",
    "multi-column": "multi_column",
    "old_scan": "old_scan",
    "old_scans": "old_scan",
    "low_quality_scan": "old_scan",
    "tiny_text": "tiny_text",
    "long_tiny_text": "tiny_text",
    "small_text": "tiny_text",
    "header_footer": "header_footer",
    "headers_footers": "header_footer",
    "chart": "chart",
    "enterprise_dense_text": "enterprise_dense_text",
    "dense_text": "enterprise_dense_text",
    "photo": "photo",
    "multilingual": "multilingual",
}


def headline_metric(
    summary: Mapping[str, Any] | None, reason: str | None
) -> tuple[Cell, str | None]:
    """The headline quality number from one ``summary.json``, plus which key it used."""

    if summary is None:
        return na_reason(reason or "no summary.json found"), None
    if summary.get("status") == "EVALUATOR_BLOCKED":
        return na_reason("evaluator blocked (status: EVALUATOR_BLOCKED)"), None
    for key in HEADLINE_METRIC_CANDIDATES:
        value = summary.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return to_cell(float(value)), key
    available = sorted(k for k in summary if k not in PROVENANCE_KEYS)
    return (
        na_reason(f"no headline metric key found; summary.json keys were {available}"),
        None,
    )


def metric_rows(summary: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """Every non-provenance metric in a summary, in file order, for a long-format dump."""

    return [(key, value) for key, value in summary.items() if key not in PROVENANCE_KEYS]


def document_type_family(raw: str) -> str | None:
    """Map a per-case category/tag spelling to one of the section 28.2 families."""

    return _FAMILY_ALIASES.get(raw.strip().lower().replace(" ", "_").replace("-", "_"))
