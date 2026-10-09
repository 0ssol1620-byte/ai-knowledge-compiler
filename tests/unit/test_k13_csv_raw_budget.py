"""CSV verbatim text obeys the total fence without changing source/grid fidelity."""

from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from akc_cir import CanonicalDocument, canonical_json, sha256_digest
from akc_native_parsers import (
    ParseContext,
    ParserLimits,
    StructuredParseError,
    parse_non_pdf_to_cir,
)


def _payload(rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerows(rows)
    payload = stream.getvalue().encode()
    assert len(payload) < 8_192
    return payload


def _parse(payload: bytes, budget: int) -> CanonicalDocument:
    document = parse_non_pdf_to_cir(
        filename="budget.csv",
        declared_mime="text/csv",
        data=payload,
        context=ParseContext(
            tenant_id="tenant_csv_budget",
            document_id="document_csv_budget",
            document_version_id="version_csv_budget",
            created_at=datetime(2026, 10, 5, tzinfo=UTC),
        ),
        limits=replace(ParserLimits(), max_total_text_chars=budget),
    )
    assert document.source_sha256 == sha256_digest(payload)
    wire = canonical_json(document)
    restored = CanonicalDocument.model_validate_json(wire)
    assert restored == document
    assert canonical_json(restored) == wire
    return restored


@pytest.mark.parametrize(
    "rows",
    [
        [["Label"], [" " * 1_000]],
        [["Label"], [" \r\n" * 333]],
        [["Label"], [" " * 500 + "x" + " " * 500]],
        [["Label"], ["e\u0301" * 70]],
        [["Label"], [" " * 70, "\t" * 70]],
        [["Label"], [" " * 70], ["\t" * 70]],
        [["x" * 1_000]],
    ],
    ids=("spaces", "quoted-crlf", "padding", "unicode", "columns", "rows", "nonblank-control"),
)
def test_csv_total_limit_refuses_preserved_raw_characters(rows: list[list[str]]) -> None:
    with pytest.raises(StructuredParseError) as failure:
        _parse(_payload(rows), 128)
    assert failure.value.code == "EXTRACTED_TEXT_LIMIT"


@pytest.mark.parametrize(
    "rows",
    [
        [["H"], [" " * 127]],
        [["x" * 128]],
        [[" " * 63 + "x" + " " * 64]],
        [["e\u0301" * 64]],
        [["A" * 62 + "\r\n" + "B" * 64]],
    ],
    ids=("empty-display", "ordinary", "padding", "unicode", "quoted-crlf"),
)
def test_csv_exact_raw_boundary_is_allowed_without_double_charge(rows: list[list[str]]) -> None:
    payload = _payload(rows)
    document = _parse(payload, 128)
    table = next(block.table for block in document.blocks if block.table is not None)
    assert [(cell.row_index0, cell.column_index0, cell.raw_text) for cell in table.cells] == [
        (row, column, value)
        for row, record in enumerate(rows)
        for column, value in enumerate(record)
        if value
    ]
    with pytest.raises(StructuredParseError) as failure:
        _parse(payload, 127)
    assert failure.value.code == "EXTRACTED_TEXT_LIMIT"


@pytest.mark.parametrize("field", ("x", "=1+2", "+42", "@SUM(A1)"))
def test_csv_ordinary_and_formula_prefixed_text_keep_existing_exact_budget(field: str) -> None:
    document = _parse(_payload([[field]]), len(field))
    table = next(block.table for block in document.blocks if block.table is not None)
    cell = table.cells[0]
    assert (cell.raw_text, cell.normalized_text, cell.value_type, cell.formula) == (
        field,
        field,
        "string",
        None,
    )
    assert cell.raw_text_verbatim is True
    assert ("spreadsheet_formula_prefix_preserved_as_text" in cell.quality_flags) == (field != "x")


def test_csv_combined_multiline_padding_unicode_survives_exact_budget_and_wire() -> None:
    raw = '  cafe\u0301, "quoted"\r\n한글  '
    document = _parse(_payload([[raw]]), len(raw))
    table = next(block.table for block in document.blocks if block.table is not None)
    cell = table.cells[0]
    assert (cell.raw_text, cell.normalized_text) == (raw, 'café, "quoted"\n한글')
    assert cell.source_refs[0].native_object_id == "csv/row/000000/cell/A1"
    assert "csv_field_whitespace_normalized" in cell.quality_flags
    with pytest.raises(StructuredParseError) as failure:
        _parse(_payload([[raw]]), len(raw) - 1)
    assert failure.value.code == "EXTRACTED_TEXT_LIMIT"


def test_csv_resource_fence_preserves_sparse_coordinates_and_trailing_record_semantics() -> None:
    payload = b"a,b\r\n0,\r\n,,\r\n\r\n"
    document = _parse(payload, 5)
    table = next(block.table for block in document.blocks if block.table is not None)
    assert (table.row_count, table.column_count, table.header_row_count) == (2, 3, 0)
    assert document.metadata["csv"]["recordCount"] == 4
    assert table.source_refs[0].native_object_id == "csv/table/range/A1:C2"
    assert [(cell.row_index0, cell.column_index0, cell.raw_text) for cell in table.cells] == [
        (0, 0, "a"),
        (0, 1, "b"),
        (1, 0, "0"),
    ]
    assert "csv_header_not_declared" in table.quality_flags
