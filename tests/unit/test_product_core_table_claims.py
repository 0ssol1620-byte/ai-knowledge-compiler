"""`tavonel.table_read.v1` -> CanonicalTable -> cell claims (table/limits plan §C2-§C5, task T3).

The fixtures are byte copies of the Foundation contract's synthetic fixtures (commit 922e950c,
`nextjs/lib/fixtures/table-read/`), and each carries its hand-written TypeScript qualification:
the Python mirror must produce exactly that. Every reasonCode has a failure path here, a cell
without its own box is never given one, and a cell nobody confirmed never becomes a claim.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from akc_cir.models import BlockOrigin, CanonicalTable
from akc_product_core import table_claims
from akc_product_core.table_claims import (
    CELL_LOCATED_BY_TABLE_BBOX_ONLY,
    CELL_TEXT_UNCONFIRMED_FLAG,
    TABLE_READ_REASON_CLASS,
    TableReadRejected,
    canonical_tables,
    is_structurally_valid_latex,
    qualify_table_read,
    table_cell_claims,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "table-read"
READ = "synthetic-read-table-and-formula.json"
# sha256 of the Foundation originals at 922e950c; a drifted copy is no longer the shared fixture.
FOUNDATION_FIXTURE_SHA256 = {
    "synthetic-no-table.json": "3960d4e7108e4c56099841ad9bfa9d224e06e28e0781968417aa33824e9565ea",
    "synthetic-read-table-and-formula.json": (
        "dcc6b83578172b7c1bb089d7571f619c7e6e8653d063caa15f12c97958e10919"
    ),
    "synthetic-unreadable-truncated.json": (
        "c14408e9c085fbf45f09e2980481046832c98ba3b1ac713fa383cd1c6454d032"
    ),
}
DOC_ID = "synthetic-document-0001"
VERSION_ID = "synthetic-document-0001-v1"
TABLE_BOX = [80, 180, 520, 330]

Json = dict[str, Any]


def load(name: str) -> Json:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def variant(mutate: Callable[[Json, Json], None]) -> Any:
    fixture = load(READ)
    mutate(fixture["document"], fixture["expected"])
    return qualify_table_read(fixture["document"], fixture["expected"])


def cell_of(doc: Json, cell_id: str) -> Json:
    return next(cell for cell in doc["tables"][0]["cells"] if cell["cellId"] == cell_id)


def ok_result(result: Any) -> Any:
    assert result["ok"], f"expected ok, got {result}"
    return result


def tables_of(result: Any, expected: Json | None = None) -> tuple[CanonicalTable, ...]:
    return canonical_tables(
        result,
        expected or load(READ)["expected"],
        document_id=DOC_ID,
        document_version_id=VERSION_ID,
    )


def boxes(value: Any, found: list[list[int]] | None = None) -> list[list[int]]:
    """Every bbox in a value: lists or tuples of four numbers, wherever they sit."""
    found = [] if found is None else found
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, list | tuple):
        if len(value) == 4 and all(type(item) is int for item in value):
            found.append(list(value))
        else:
            for item in value:
                boxes(item, found)
    elif isinstance(value, dict):
        for item in value.values():
            boxes(item, found)
    return found


# --- the fixtures ------------------------------------------------------------------------------


def test_fixtures_are_labelled_synthetic_byte_copies_of_the_foundation_contract() -> None:
    names = sorted(path.name for path in FIXTURES.glob("*.json"))
    assert names == sorted(FOUNDATION_FIXTURE_SHA256)
    for name in names:
        raw = (FIXTURES / name).read_bytes()
        assert name.startswith("synthetic-")
        assert hashlib.sha256(raw).hexdigest() == FOUNDATION_FIXTURE_SHA256[name], name
        assert b'"synthetic": true' in raw
        assert json.loads(raw)["synthetic"] is True


@pytest.mark.parametrize("name", sorted(FOUNDATION_FIXTURE_SHA256))
def test_python_mirror_reproduces_the_typescript_qualification(name: str) -> None:
    fixture = load(name)
    document, expected = copy.deepcopy(fixture["document"]), copy.deepcopy(fixture["expected"])
    assert qualify_table_read(fixture["document"], fixture["expected"]) == fixture["qualification"]
    # Pure: the inputs are not mutated.
    assert (fixture["document"], fixture["expected"]) == (document, expected)


def test_the_label_lives_on_the_fixture_never_on_the_reader_document() -> None:
    result = variant(lambda doc, _: doc.update(synthetic=True))
    assert result["reasonCode"] == "TABLE_READ_SCHEMA_INVALID"


# --- one failure path per reasonCode -----------------------------------------------------------


def document_failure(code: str) -> Callable[[Any], None]:
    def check(result: Any) -> None:
        assert result["ok"] is False
        assert result["reasonCode"] == code
        assert "pageStatus" not in result

    return check


def refused_table(code: str, bbox: list[int] | None) -> Callable[[Any], None]:
    def check(result: Any) -> None:
        ok = ok_result(result)
        assert ok["tables"] == [], "a refused table emits no cells"
        assert {"bbox1000": bbox, "reasonCode": code} in ok["refusals"]
        assert ok["pageStatus"] == "unreadable"
        assert [formula["formulaId"] for formula in ok["formulas"]] == ["f1"]
        assert tables_of(ok) == ()

    return check


def _set(target: Json, **values: Any) -> None:
    target.update(values)


def _truncated_page() -> Any:
    fixture = load("synthetic-unreadable-truncated.json")
    return qualify_table_read(fixture["document"], fixture["expected"])


def _check_truncated(result: Any) -> None:
    ok = ok_result(result)
    assert ok["pageStatus"] == "unreadable"
    assert ok["tables"] == []
    assert ok["refusals"] == [
        {"bbox1000": [80, 180, 920, 700], "reasonCode": "TABLE_OUTPUT_TRUNCATED"}
    ]


def _check_second_truncated(result: Any) -> None:
    ok = ok_result(result)
    assert ok["pageStatus"] == "read"
    assert [table["tableId"] for table in ok["tables"]] == ["t1"]
    assert ok["refusals"] == [
        {"bbox1000": [80, 600, 920, 900], "reasonCode": "TABLE_OUTPUT_TRUNCATED"}
    ]


def _check_unconfirmed(result: Any) -> None:
    cells = ok_result(result)["tables"][0]["cells"]
    unconfirmed = [cell for cell in cells if cell["reasonCode"] == "TABLE_CELL_TEXT_UNCONFIRMED"]
    assert [cell["cellId"] for cell in unconfirmed] == ["t1-c6"]
    assert unconfirmed[0]["confirmedBy"] == []
    assert len([cell for cell in cells if cell["reasonCode"] is None]) == 5
    # Shown as evidence (still a CIR cell, flagged) and never promoted to a claim.
    (table,) = tables_of(result)
    flagged = [cell for cell in table.cells if CELL_TEXT_UNCONFIRMED_FLAG in cell.quality_flags]
    assert [cell.source_refs[0].native_object_id for cell in flagged] == ["t1-c6"]
    assert all(claim.value_text != "7" for claim in table_cell_claims(table))


def _check_latex(result: Any) -> None:
    ok = ok_result(result)
    assert ok["formulas"] == []
    assert ok["refusals"] == [
        {"bbox1000": [100, 400, 600, 460], "reasonCode": "FORMULA_LATEX_INVALID"}
    ]
    assert [table["tableId"] for table in ok["tables"]] == ["t1"]
    assert ok["pageStatus"] == "read"


def _many_tables(doc: Json) -> None:
    doc["tables"] = [
        {**doc["tables"][0], "tableId": f"t{index}", "cells": []} for index in range(65)
    ]


_TRUNC = "TABLE_OUTPUT_TRUNCATED"
FAILURES: list[tuple[str, str, Callable[[], Any], Callable[[Any], None]]] = [
    (
        "no reader output",
        "TABLE_READER_UNAVAILABLE",
        lambda: qualify_table_read(None, load(READ)["expected"]),
        document_failure("TABLE_READER_UNAVAILABLE"),
    ),
    (
        "another sanitized PDF",
        "TABLE_BINDING_MISMATCH",
        lambda: variant(lambda doc, _: _set(doc, inputSha256="sha256:" + "0" * 64)),
        document_failure("TABLE_BINDING_MISMATCH"),
    ),
    (
        "another reader revision",
        "TABLE_BINDING_MISMATCH",
        lambda: variant(lambda doc, _: _set(doc, readerRevision="sha256:" + "1" * 64)),
        document_failure("TABLE_BINDING_MISMATCH"),
    ),
    (
        "another reader binding",
        "TABLE_BINDING_MISMATCH",
        lambda: variant(lambda doc, _: _set(doc, readerBindingSha256="sha256:" + "2" * 64)),
        document_failure("TABLE_BINDING_MISMATCH"),
    ),
    (
        "another source key",
        "TABLE_BINDING_MISMATCH",
        lambda: variant(
            lambda doc, _: _set(doc, sourceImmutableKey="synthetic/other/sanitized.pdf")
        ),
        document_failure("TABLE_BINDING_MISMATCH"),
    ),
    (
        "another page",
        "TABLE_BINDING_MISMATCH",
        lambda: variant(lambda doc, _: _set(doc, pageIndex0=1, pageNumber1=2)),
        document_failure("TABLE_BINDING_MISMATCH"),
    ),
    (
        "confirmedBy names a missing OCR region",
        "TABLE_BINDING_MISMATCH",
        lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c1"), confirmedBy=["r-9999"])),
        document_failure("TABLE_BINDING_MISMATCH"),
    ),
    (
        "confirmedBy names a region on another page",
        "TABLE_BINDING_MISMATCH",
        lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c6"), confirmedBy=["r-0101"])),
        document_failure("TABLE_BINDING_MISMATCH"),
    ),
    (
        "one OCR region confirms two cells",
        "TABLE_BINDING_MISMATCH",
        lambda: variant(
            lambda doc, _: _set(cell_of(doc, "t1-c6"), text="12", confirmedBy=["r-0005"])
        ),
        document_failure("TABLE_BINDING_MISMATCH"),
    ),
    (
        "a confirming region outside the table",
        "TABLE_BINDING_MISMATCH",
        lambda: variant(
            lambda doc, _: _set(
                cell_of(doc, "t1-c6"), text="Synthetic page heading", confirmedBy=["r-0001"]
            )
        ),
        document_failure("TABLE_BINDING_MISMATCH"),
    ),
    (
        "a confirming region with other text",
        "TABLE_BINDING_MISMATCH",
        lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c4"), text="13")),
        document_failure("TABLE_BINDING_MISMATCH"),
    ),
    (
        "a payload that is not an object",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: qualify_table_read("[]", load(READ)["expected"]),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "an extra document key",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: _set(doc, confidence=1)),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "a missing cell key",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: cell_of(doc, "t1-c1").pop("confirmedBy")),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "another schema version",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: _set(doc, schemaVersion="tavonel.table_read.v2")),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "a bare hex digest",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(
            lambda doc, exp: (_set(doc, inputSha256="5e" * 32), _set(exp, inputSha256="5e" * 32))
        ),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "pageNumber1 not pageIndex0 + 1",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: _set(doc, pageNumber1=3)),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "a repeated cellId",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c6"), cellId="t1-c5")),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "a non-integer span",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c1"), rowSpan=1.5)),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "a boolean where an integer belongs",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c1"), rowSpan=True)),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "an integral float (fails closed in Python)",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c1"), rowSpan=1.0)),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        '"read" with no table',
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: _set(doc, tables=[])),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        '"no_table" beside a truncated table',
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(
            lambda doc, _: _set(
                doc,
                pageStatus="no_table",
                tables=[],
                refusals=[{"bbox1000": TABLE_BOX, "reasonCode": _TRUNC}],
            )
        ),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "an unhashable pageStatus",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: _set(doc, pageStatus=["read"])),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "a refusal with a document-level code",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(
            lambda doc, _: _set(
                doc, refusals=[{"bbox1000": None, "reasonCode": "TABLE_READER_UNAVAILABLE"}]
            )
        ),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "a refusal with the cell-level code",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(
            lambda doc, _: _set(
                doc, refusals=[{"bbox1000": None, "reasonCode": "TABLE_CELL_TEXT_UNCONFIRMED"}]
            )
        ),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "a truncated refusal over a table the reader still emitted",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(
            lambda doc, _: _set(doc, refusals=[{"bbox1000": TABLE_BOX, "reasonCode": _TRUNC}])
        ),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "a formula without a box",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: _set(doc["formulas"][0], bbox1000=None)),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "more tables than one page carries",
        "TABLE_READ_SCHEMA_INVALID",
        lambda: variant(lambda doc, _: _many_tables(doc)),
        document_failure("TABLE_READ_SCHEMA_INVALID"),
    ),
    (
        "the reader's output hit the token limit",
        "TABLE_OUTPUT_TRUNCATED",
        _truncated_page,
        _check_truncated,
    ),
    (
        "a second, truncated table beside a read one",
        "TABLE_OUTPUT_TRUNCATED",
        lambda: variant(
            lambda doc, _: _set(
                doc, refusals=[{"bbox1000": [80, 600, 920, 900], "reasonCode": _TRUNC}]
            )
        ),
        _check_second_truncated,
    ),
    (
        "two cells on one slot",
        "TABLE_GRID_INVALID",
        lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c6"), rowIndex0=1)),
        refused_table("TABLE_GRID_INVALID", TABLE_BOX),
    ),
    (
        "a span past the last column",
        "TABLE_GRID_INVALID",
        lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c6"), columnSpan=2)),
        refused_table("TABLE_GRID_INVALID", TABLE_BOX),
    ),
    (
        "more header rows than rows",
        "TABLE_GRID_INVALID",
        lambda: variant(lambda doc, _: _set(doc["tables"][0], headerRowCount=4)),
        refused_table("TABLE_GRID_INVALID", TABLE_BOX),
    ),
    (
        "a table with no cells",
        "TABLE_GRID_INVALID",
        lambda: variant(lambda doc, _: _set(doc["tables"][0], cells=[])),
        refused_table("TABLE_GRID_INVALID", TABLE_BOX),
    ),
    (
        "a table with no box",
        "TABLE_REGION_UNLOCATED",
        lambda: variant(lambda doc, _: _set(doc["tables"][0], bbox1000=None)),
        refused_table("TABLE_REGION_UNLOCATED", None),
    ),
    (
        "a table box past 1000",
        "TABLE_REGION_UNLOCATED",
        lambda: variant(lambda doc, _: _set(doc["tables"][0], bbox1000=[80, 180, 1001, 330])),
        refused_table("TABLE_REGION_UNLOCATED", None),
    ),
    (
        "a table box with x1 >= x2",
        "TABLE_REGION_UNLOCATED",
        lambda: variant(lambda doc, _: _set(doc["tables"][0], bbox1000=[520, 180, 80, 330])),
        refused_table("TABLE_REGION_UNLOCATED", None),
    ),
    (
        "a cell box outside its table",
        "TABLE_REGION_UNLOCATED",
        lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c1"), bbox1000=[100, 150, 300, 240])),
        refused_table("TABLE_REGION_UNLOCATED", TABLE_BOX),
    ),
    (
        "a cell box of three numbers",
        "TABLE_REGION_UNLOCATED",
        lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c1"), bbox1000=[100, 200, 300])),
        refused_table("TABLE_REGION_UNLOCATED", TABLE_BOX),
    ),
    (
        "a cell no OCR region confirms",
        "TABLE_CELL_TEXT_UNCONFIRMED",
        lambda: qualify_table_read(load(READ)["document"], load(READ)["expected"]),
        _check_unconfirmed,
    ),
    (
        "an unclosed brace",
        "FORMULA_LATEX_INVALID",
        lambda: variant(lambda doc, _: _set(doc["formulas"][0], latex="\\frac{a}{b")),
        _check_latex,
    ),
]


def test_failure_paths_cover_every_reason_code_and_no_other() -> None:
    assert {code for _, code, _, _ in FAILURES} == set(TABLE_READ_REASON_CLASS)


@pytest.mark.parametrize(
    ("label", "code", "run", "check"), FAILURES, ids=[row[0] for row in FAILURES]
)
def test_failure_path(
    label: str, code: str, run: Callable[[], Any], check: Callable[[Any], None]
) -> None:
    result = run()
    check(result)
    if not result["ok"]:
        assert result["reasonCode"] == code


def test_operational_failure_is_kept_apart_from_the_reader_being_wrong() -> None:
    assert TABLE_READ_REASON_CLASS["TABLE_READER_UNAVAILABLE"] == "operational"
    assert TABLE_READ_REASON_CLASS["TABLE_BINDING_MISMATCH"] == "evidence"
    semantic = {code for code, kind in TABLE_READ_REASON_CLASS.items() if kind == "semantic"}
    assert semantic == {
        "TABLE_READ_SCHEMA_INVALID",
        "TABLE_OUTPUT_TRUNCATED",
        "TABLE_GRID_INVALID",
        "TABLE_REGION_UNLOCATED",
        "TABLE_CELL_TEXT_UNCONFIRMED",
        "FORMULA_LATEX_INVALID",
    }


# --- confirmations and LaTeX, as in the TypeScript contract --------------------------------------


def test_a_cell_whose_text_spans_two_ocr_lines_is_confirmed_in_order() -> None:
    def mutate(doc: Json, expected: Json) -> None:
        expected["ocrRegions"] += [
            {"regionId": "r-0007", "pageIndex0": 0, "text": "7", "bbox1000": [300, 280, 400, 320]},
            {
                "regionId": "r-0008",
                "pageIndex0": 0,
                "text": "units",
                "bbox1000": [400, 280, 500, 320],
            },
        ]
        _set(cell_of(doc, "t1-c6"), text="7  units", confirmedBy=["r-0007", "r-0008"])

    cells = ok_result(variant(mutate))["tables"][0]["cells"]
    assert next(cell for cell in cells if cell["cellId"] == "t1-c6")["reasonCode"] is None


def test_confirmation_normalizes_whitespace_only() -> None:
    assert variant(lambda doc, _: _set(cell_of(doc, "t1-c1"), text=" Region\n"))["ok"] is True
    assert variant(lambda doc, _: _set(cell_of(doc, "t1-c1"), text="Region　"))["ok"] is True
    folded = variant(lambda doc, _: _set(cell_of(doc, "t1-c1"), text="region"))
    assert folded["reasonCode"] == "TABLE_BINDING_MISMATCH"


@pytest.mark.parametrize(
    "latex",
    [
        "x = \\frac{a}{b}",
        "\\{a\\}",
        "a \\\\ {b}",
        "\\left( x \\right)",
        "a \\leftarrow b",
        "\\begin{matrix} a & b \\end{matrix}",
        "\\$5",
    ],
)
def test_latex_structure_check_accepts(latex: str) -> None:
    assert is_structurally_valid_latex(latex)


@pytest.mark.parametrize(
    "latex",
    [
        "",
        "  ",
        "\\frac{a}{b",
        "a}",
        "$x$",
        "\\left( x",
        "x \\right)",
        "\\begin{matrix} a",
        "\\begin{matrix} a \\end{cases}",
        "a\u0000b",
    ],
)
def test_latex_structure_check_refuses(latex: str) -> None:
    assert not is_structurally_valid_latex(latex)


# --- CanonicalTable mapping ----------------------------------------------------------------------


def test_cell_bbox_null_is_preserved_and_never_invented() -> None:
    fixture = load(READ)
    page = ok_result(qualify_table_read(fixture["document"], fixture["expected"]))
    qualified = {cell["cellId"]: cell for cell in page["tables"][0]["cells"]}
    (table,) = tables_of(page)
    by_reader_id = {cell.source_refs[0].native_object_id: cell for cell in table.cells}
    for cell_id in ("t1-c4", "t1-c6"):
        assert qualified[cell_id]["bbox1000"] is None
        cir = by_reader_id[cell_id]
        assert list(cir.source_refs[0].bbox1000.as_tuple()) == TABLE_BOX  # type: ignore[union-attr]
        assert CELL_LOCATED_BY_TABLE_BBOX_ONLY in cir.quality_flags
    # t1-c4 is confirmed by r-0005, whose box the OCR reader measured; it stays the OCR reader's.
    assert [300, 240, 500, 280] not in boxes(table)
    assert list(by_reader_id["t1-c1"].source_refs[0].bbox1000.as_tuple()) == [100, 200, 300, 240]  # type: ignore[union-attr]
    assert CELL_LOCATED_BY_TABLE_BBOX_ONLY in table.quality_flags
    carried = boxes(fixture["document"])
    assert all(box in carried for box in boxes(table))


def test_canonical_table_is_ai_reconstructed_and_bound_to_page_document_and_reader() -> None:
    page = qualify_table_read(load(READ)["document"], load(READ)["expected"])
    (table,) = tables_of(page)
    assert (table.row_count, table.column_count, table.header_row_count) == (3, 2, 1)
    assert all(cell.origin is BlockOrigin.AI_RECONSTRUCTED for cell in table.cells)
    refs = [*table.source_refs, *(ref for cell in table.cells for ref in cell.source_refs)]
    assert {
        (ref.document_id, ref.document_version_id, ref.page_index0, ref.page_number1)
        for ref in refs
    } == {(DOC_ID, VERSION_ID, 0, 1)}
    assert table.cells[0].confidence is None  # the contract carries none; none is invented
    other = load(READ)
    for side in ("document", "expected"):
        other[side]["readerBindingSha256"] = "sha256:" + "c" * 64
    (rebound,) = tables_of(
        qualify_table_read(other["document"], other["expected"]), other["expected"]
    )
    assert rebound.id != table.id


@pytest.mark.parametrize(
    ("qualification", "code"),
    [
        (lambda: qualify_table_read(None, load(READ)["expected"]), "TABLE_READER_UNAVAILABLE"),
        (
            lambda: variant(lambda doc, _: _set(cell_of(doc, "t1-c4"), text="13")),
            "TABLE_BINDING_MISMATCH",
        ),
        (lambda: qualify_table_read({}, load(READ)["expected"]), "TABLE_READ_SCHEMA_INVALID"),
    ],
)
def test_a_failed_page_raises_instead_of_reading_as_no_tables(
    qualification: Callable[[], Any], code: str
) -> None:
    with pytest.raises(TableReadRejected) as raised:
        tables_of(qualification())
    assert raised.value.reason_code == code


def _accepted_page(table: Json) -> Any:
    return {
        "ok": True,
        "pageIndex0": 0,
        "pageNumber1": 1,
        "pageStatus": "read",
        "tables": [table],
        "formulas": [],
        "refusals": [],
    }


def _cell(cell_id: str, row: int, column: int, text: str, **extra: Any) -> Json:
    return {
        "cellId": cell_id,
        "rowIndex0": row,
        "columnIndex0": column,
        "rowSpan": 1,
        "columnSpan": 1,
        "text": text,
        "bbox1000": None,
        "locatorBbox1000": list(TABLE_BOX),
        "confirmedBy": [f"r-{cell_id}"],
        "qualityFlags": [CELL_LOCATED_BY_TABLE_BBOX_ONLY],
        "reasonCode": None,
        **extra,
    }


def _table(cells: list[Json], rows: int, columns: int, headers: int) -> Json:
    return {
        "tableId": "t-synthetic",
        "bbox1000": list(TABLE_BOX),
        "rowCount": rows,
        "columnCount": columns,
        "headerRowCount": headers,
        "cells": cells,
        "qualityFlags": [CELL_LOCATED_BY_TABLE_BBOX_ONLY],
    }


def test_a_grid_violation_reaching_the_mapping_raises_table_grid_invalid() -> None:
    overlapping = _table(
        [_cell("c-a", 0, 0, "A"), _cell("c-b", 0, 0, "B")], rows=1, columns=1, headers=0
    )
    with pytest.raises(TableReadRejected) as raised:
        tables_of(_accepted_page(overlapping))
    assert raised.value.reason_code == "TABLE_GRID_INVALID"


def test_a_reader_id_too_short_for_cir_is_refused_not_renamed() -> None:
    page = variant(lambda doc, _: _set(cell_of(doc, "t1-c1"), cellId="c1"))
    assert page["ok"] is True  # valid table_read.v1 ...
    with pytest.raises(TableReadRejected) as raised:
        tables_of(page)  # ... but CIR cannot carry it verbatim
    assert raised.value.reason_code == "TABLE_READ_SCHEMA_INVALID"


# --- cell claims ---------------------------------------------------------------------------


def _fixture_claims() -> tuple[table_claims.TableCellClaim, ...]:
    (table,) = tables_of(qualify_table_read(load(READ)["document"], load(READ)["expected"]))
    return table_cell_claims(table)


def test_one_claim_per_confirmed_data_cell_with_value_then_header_evidence() -> None:
    claims = _fixture_claims()
    assert [claim.text for claim in claims] == ["Region: North", "Units: 12", "Region: South"]
    units = claims[1]
    assert units.column_header_path == ("Units",)
    assert units.numeric_values == ("12",)
    assert [ref.native_object_id for ref in units.source_refs] == ["t1-c4", "t1-c2"]
    # The value cell has no box of its own: its evidence points at the table, not a derived box.
    assert list(units.source_refs[0].bbox1000.as_tuple()) == TABLE_BOX  # type: ignore[union-attr]
    assert len({claim.claim_id for claim in claims}) == 3
    assert [claim.claim_id for claim in _fixture_claims()] == [claim.claim_id for claim in claims]


def test_a_table_without_a_header_row_yields_no_claims() -> None:
    page = variant(lambda doc, _: _set(doc["tables"][0], headerRowCount=0))
    (table,) = tables_of(page)
    assert len(table.cells) == 6
    assert table_cell_claims(table) == ()


def test_unconfirmed_cells_yield_no_claims() -> None:
    def unconfirm_all(doc: Json, _: Json) -> None:
        for cell in doc["tables"][0]["cells"]:
            cell["confirmedBy"] = []

    (table,) = tables_of(variant(unconfirm_all))
    assert all(CELL_TEXT_UNCONFIRMED_FLAG in cell.quality_flags for cell in table.cells)
    assert table_cell_claims(table) == ()


def test_a_value_under_an_unconfirmed_header_is_not_promoted() -> None:
    (table,) = tables_of(variant(lambda doc, _: _set(cell_of(doc, "t1-c2"), confirmedBy=[])))
    assert [claim.text for claim in table_cell_claims(table)] == ["Region: North", "Region: South"]


def test_multi_row_headers_compose_a_path_and_a_tall_header_counts_once() -> None:
    cells = [
        _cell("h-region", 0, 0, "Region", rowSpan=2),
        _cell("h-revenue", 0, 1, "Revenue", columnSpan=2),
        _cell("h-2024", 1, 1, "2024"),
        _cell("h-2025", 1, 2, " 2025 "),
        _cell("d-north", 2, 0, "North"),
        _cell("d-north-2024", 2, 1, "1,200 억원"),
        _cell("d-north-2025", 2, 2, "", confirmedBy=[]),
    ]
    cells[-1]["reasonCode"] = "TABLE_CELL_TEXT_UNCONFIRMED"
    (table,) = tables_of(_accepted_page(_table(cells, rows=3, columns=3, headers=2)))
    claims = table_cell_claims(table)
    assert [claim.text for claim in claims] == ["Region: North", "Revenue / 2024: 1,200 억원"]
    assert claims[1].numeric_values == ("1,200 억원",)
    assert [ref.native_object_id for ref in claims[1].source_refs] == [
        "d-north-2024",
        "h-revenue",
        "h-2024",
    ]


def test_a_data_cell_with_no_header_above_it_yields_no_claim() -> None:
    cells = [_cell("h-a", 0, 0, "A"), _cell("d-a", 1, 0, "1"), _cell("d-b", 1, 1, "2")]
    (table,) = tables_of(_accepted_page(_table(cells, rows=2, columns=2, headers=1)))
    assert [claim.text for claim in table_cell_claims(table)] == ["A: 1"]


def test_claims_are_defined_for_table_reader_output_only() -> None:
    (table,) = tables_of(qualify_table_read(load(READ)["document"], load(READ)["expected"]))
    native = table.model_copy(
        update={
            "cells": tuple(
                cell.model_copy(update={"origin": BlockOrigin.NATIVE_EXTRACTED})
                for cell in table.cells
            )
        }
    )
    with pytest.raises(ValueError, match="table reader output only"):
        table_cell_claims(native)


def test_shadow_only_nothing_in_product_core_imports_the_projection() -> None:
    package = Path(table_claims.__file__).parent
    importers = [
        path.name
        for path in package.glob("*.py")
        if path.name != "table_claims.py" and "table_claims" in path.read_text(encoding="utf-8")
    ]
    assert importers == []
