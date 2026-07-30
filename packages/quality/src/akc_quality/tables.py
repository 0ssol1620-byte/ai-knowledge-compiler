"""Canonical table integrity checks."""

from __future__ import annotations

from collections import Counter

from akc_cir import CanonicalTable

from .models import FindingSeverity, QualityFinding
from .numeric import compare_numeric_tokens


def validate_table(table: CanonicalTable) -> tuple[QualityFinding, ...]:
    findings: list[QualityFinding] = []
    occupied = sum(cell.row_span * cell.column_span for cell in table.cells)
    total = table.row_count * table.column_count
    empty_ratio = max(0.0, 1 - occupied / total)
    if empty_ratio > 0.40:
        findings.append(
            QualityFinding(
                code="table.empty_cell_ratio",
                severity=FindingSeverity.ERROR,
                message="Too much of the table grid is unaccounted for.",
                observed=empty_ratio,
                threshold=0.40,
            )
        )
    if table.header_row_count == 0:
        findings.append(
            QualityFinding(
                code="table.header_missing",
                severity=FindingSeverity.WARNING,
                message="No table header was identified.",
            )
        )
    values = [
        cell.normalized_text.strip()
        for cell in table.cells
        if cell.normalized_text and cell.normalized_text.strip()
    ]
    counts = Counter(values)
    repeated = sum(count for count in counts.values() if count > 1)
    if values and repeated / len(values) > 0.65:
        findings.append(
            QualityFinding(
                code="table.repeated_cells",
                severity=FindingSeverity.WARNING,
                message="A high ratio of cells contain repeated text.",
                observed=repeated / len(values),
                threshold=0.65,
            )
        )
    return tuple(findings)


def table_numeric_fidelity(reference: CanonicalTable, candidate: CanonicalTable) -> float:
    reference_text = "\n".join(cell.raw_text for cell in reference.cells)
    candidate_text = "\n".join(cell.raw_text for cell in candidate.cells)
    return compare_numeric_tokens(reference_text, candidate_text).score


def table_shape_fidelity(reference: CanonicalTable, candidate: CanonicalTable) -> float:
    row_score = min(reference.row_count, candidate.row_count) / max(
        reference.row_count, candidate.row_count
    )
    column_score = min(reference.column_count, candidate.column_count) / max(
        reference.column_count, candidate.column_count
    )
    return (row_score + column_score) / 2
