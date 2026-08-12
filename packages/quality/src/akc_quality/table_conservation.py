"""Conservation checks for table rows, columns, cells, and numeric tokens."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TableConservation:
    row_delta: int
    column_delta: int
    cell_delta: int
    missing_numeric_tokens: tuple[str, ...]
    extra_numeric_tokens: tuple[str, ...]
    passed: bool


def validate_table_conservation(
    *,
    source_shape: tuple[int, int],
    output_shape: tuple[int, int],
    source_numeric_tokens: tuple[str, ...],
    output_numeric_tokens: tuple[str, ...],
) -> TableConservation:
    if min(*source_shape, *output_shape) < 0:
        raise ValueError("table dimensions cannot be negative")
    source_numbers = set(source_numeric_tokens)
    output_numbers = set(output_numeric_tokens)
    row_delta = output_shape[0] - source_shape[0]
    column_delta = output_shape[1] - source_shape[1]
    cell_delta = output_shape[0] * output_shape[1] - source_shape[0] * source_shape[1]
    missing = tuple(sorted(source_numbers - output_numbers))
    extra = tuple(sorted(output_numbers - source_numbers))
    return TableConservation(
        row_delta=row_delta,
        column_delta=column_delta,
        cell_delta=cell_delta,
        missing_numeric_tokens=missing,
        extra_numeric_tokens=extra,
        passed=not any((row_delta, column_delta, cell_delta, missing, extra)),
    )


__all__ = ["TableConservation", "validate_table_conservation"]
