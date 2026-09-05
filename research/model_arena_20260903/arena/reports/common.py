"""Shared primitives for every report generator.

Three rules from ``CLAUDE.md`` and ``ARENA_CONTRACT.md`` become mechanical
here rather than repeated in each table module:

*Never invent data to satisfy a schema.* :data:`NA` is the only spelling for
"not available" a cell may hold; nothing here ever writes ``0`` for a metric
that was not measured. :class:`Cell` pairs a value with the reason it is
missing, so a table can render ``n/a`` and still say *why*.

*Missing input is not a crash.* :func:`read_json_optional` and
:func:`read_jsonl_optional` return ``(None, reason)`` for an absent file and
raise only when a file exists but is not well-formed JSON, which is a real
integrity problem the caller should not swallow silently.

*A read-only lane never mutates what it reads.* Every loader here opens files
for reading only; no path under this module is ever written to except the
report outputs themselves, via :func:`write_csv` and :func:`write_text`.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "NA",
    "Cell",
    "TableSpec",
    "first_present",
    "na_reason",
    "read_json_optional",
    "read_jsonl_optional",
    "rows_to_csv_text",
    "to_cell",
    "write_csv",
    "write_json",
    "write_text",
]

# The one string every "not measured" cell renders as. Never ``0``, never
# an empty string (which reads as measured-and-blank in a spreadsheet).
NA: Final = "n/a"


class ReportInputError(ValueError):
    """A report input file exists but is not well-formed."""


def read_json_optional(path: Path) -> tuple[Any | None, str | None]:
    """Read one JSON file. ``(None, reason)`` if it is absent.

    Raises :class:`ReportInputError` if the file exists but does not parse,
    because a corrupt file is a different problem than a missing one and
    must not be silently treated as "no data".
    """

    if not path.is_file():
        return None, f"missing: {path.name}"
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ReportInputError(f"{path} is not valid UTF-8: {exc}") from exc
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        raise ReportInputError(f"{path} is not valid JSON: {exc}") from exc


def read_jsonl_optional(path: Path) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Read one JSONL file into a list of objects. ``(None, reason)`` if absent."""

    if not path.is_file():
        return None, f"missing: {path.name}"
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ReportInputError(f"{path} is not valid UTF-8: {exc}") from exc
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ReportInputError(f"{path}:{line_number} is not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ReportInputError(f"{path}:{line_number} is not a JSON object")
        rows.append(value)
    return rows, None


def first_present(mapping: Mapping[str, Any], *keys: str) -> Any | None:
    """The first key present in ``mapping`` with a non-``None`` value, or ``None``."""

    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


@dataclass(frozen=True, slots=True)
class Cell:
    """A table cell that is either a real value or an explained absence."""

    value: Any | None
    reason: str | None = None

    def rendered(self) -> str:
        if self.value is None:
            return NA
        if isinstance(self.value, float):
            return f"{self.value:.6g}"
        return str(self.value)


def to_cell(value: Any | None, *, reason: str | None = None) -> Cell:
    if value is None and reason is None:
        reason = "not measured"
    return Cell(value, reason if value is None else None)


def na_reason(reason: str) -> Cell:
    """A cell that is ``n/a`` for a stated reason."""

    return Cell(None, reason)


@dataclass(frozen=True, slots=True)
class TableSpec:
    """A CSV table: a fixed header plus rows, each row a ``dict`` of cells.

    A row dict may omit a header column when there was truly nothing to say;
    it renders as :data:`NA` with no reason recorded, which is why every
    generator is expected to supply a ``Cell`` (via :func:`na_reason`) for any
    column it means to explain.
    """

    header: Sequence[str]
    rows: Sequence[Mapping[str, Cell | Any]]


def _render(value: Cell | Any) -> str:
    if isinstance(value, Cell):
        return value.rendered()
    if value is None:
        return NA
    return str(value)


def rows_to_csv_text(spec: TableSpec) -> str:
    """Render a :class:`TableSpec` as CSV text (header always present)."""

    import io

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(spec.header)
    for row in spec.rows:
        writer.writerow([_render(row.get(column)) for column in spec.header])
    return buffer.getvalue()


def write_csv(path: Path, spec: TableSpec) -> None:
    """Write one CSV file. The header is written even when there are 0 rows."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rows_to_csv_text(spec), encoding="utf-8", newline="")


def write_text(path: Path, text: str) -> None:
    """Write one text file (Markdown, etc.), creating parent directories."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8", newline="")


def write_json(path: Path, payload: Any) -> str:
    """Write one JSON file, sorted and indented, and return ``sha256:<hex>`` of its bytes."""

    import hashlib

    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def iter_existing(paths: Iterable[Path]) -> list[Path]:
    """Filter an iterable of paths down to the ones that exist as files."""

    return [path for path in paths if path.is_file()]
