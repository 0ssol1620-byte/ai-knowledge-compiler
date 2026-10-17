"""`tavonel.table_read.v1` -> CIR `CanonicalTable` -> cell claims, as pure functions.

Table/limits plan 2026-10-17 §C2-§C5, task T3. **Shadow only (§C6 ladder step 1): nothing in the
compile path imports this module.** `ProductCoreCompiler` still reads paragraph regions only,
`compile_request.v2` carries no table, and the capability manifest keeps
`no_table_or_formula_extraction`. Wiring cells into a compile is contract v3 plus an ADR, behind
the same-condition benchmark of §C5. Passing through here is not table support and claims none.

Three steps, each usable alone:

1. `qualify_table_read` mirrors `qualifyTableRead` in Foundation `shared/tableReadContract.ts`
   (commit 922e950c, sha256 5b47899f...e669): exact keys at every level, the same bounds, the
   same reasonCodes, the same refusal order. A document that is absent, malformed or bound to
   other bytes fails whole; a table that cannot be used becomes a refusal and the rest of the
   page survives. One deliberate difference: a JSON number written as `1.0` is not an integer
   here (Python keeps it a float), so it fails closed as TABLE_READ_SCHEMA_INVALID.
2. `canonical_tables` maps the qualified page onto `akc_cir.models.CanonicalTable`, whose own
   `validate_grid` is the grid rule; a violation raises `TableReadRejected(TABLE_GRID_INVALID)`.
   A cell without its own box keeps that fact: its SourceRef points at the table's box (the
   only box the document carried for it) and it is flagged `cell_located_by_table_bbox_only`.
   No coordinate is derived. A cell no second reader confirmed is flagged
   `table_cell_text_unconfirmed`.
3. `table_cell_claims` makes one claim per confirmed data cell (§C3), composed
   deterministically as `{column header path}: {cell text}` with the value cell's SourceRef
   first and then the header cells it used. A table with no header row, an unconfirmed value
   cell, or a value under an unconfirmed or missing header yields no claim: shown as evidence,
   never promoted to a fact. `numeric_values` apply the sentence path's `_NUMBER` rule to the
   value text only; a number in a header (a year) is context, not the cell's value.

The plan's composition is `{row header path} · {column header path}: {cell text}`.
`table_read.v1` marks header *rows* only, so the row half is absent; it is never guessed from
column 0. Carrying row headers is a contract change (a v2 field), not an inference here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from akc_cir.models import BBox1000, BlockOrigin, CanonicalCell, CanonicalTable, SourceRef
from pydantic import ValidationError

from .semantics import _NUMBER, _stable_id

TABLE_READ_SCHEMA = "tavonel.table_read.v1"
CELL_LOCATED_BY_TABLE_BBOX_ONLY = "cell_located_by_table_bbox_only"
CELL_TEXT_UNCONFIRMED_FLAG = "table_cell_text_unconfirmed"

ReasonClass = Literal["operational", "evidence", "semantic"]
#: Every reasonCode and the kind of failure it is, as in the Foundation contract (§C4).
TABLE_READ_REASON_CLASS: dict[str, ReasonClass] = {
    "TABLE_READER_UNAVAILABLE": "operational",
    "TABLE_BINDING_MISMATCH": "evidence",
    "TABLE_READ_SCHEMA_INVALID": "semantic",
    "TABLE_OUTPUT_TRUNCATED": "semantic",
    "TABLE_GRID_INVALID": "semantic",
    "TABLE_REGION_UNLOCATED": "semantic",
    "TABLE_CELL_TEXT_UNCONFIRMED": "semantic",
    "FORMULA_LATEX_INVALID": "semantic",
}
DocumentFailureCode = Literal[
    "TABLE_READER_UNAVAILABLE", "TABLE_BINDING_MISMATCH", "TABLE_READ_SCHEMA_INVALID"
]
RefusalReasonCode = Literal[
    "TABLE_OUTPUT_TRUNCATED",
    "TABLE_GRID_INVALID",
    "TABLE_REGION_UNLOCATED",
    "FORMULA_LATEX_INVALID",
]
_TABLE_REFUSAL_CODES = frozenset(
    {"TABLE_OUTPUT_TRUNCATED", "TABLE_GRID_INVALID", "TABLE_REGION_UNLOCATED"}
)
_REFUSAL_CODES = _TABLE_REFUSAL_CODES | {"FORMULA_LATEX_INVALID"}

# Wire-shape bounds, the Foundation contract's. Not product limits and not calibrated.
_MAX_TABLES = 64
_MAX_CELLS = 10_000
_MAX_GRID_EXTENT = 1_000
_MAX_TEXT = 20_000
_MAX_FORMULAS = 256
_MAX_REFUSALS = 256
_MAX_CONFIRMED_BY = 64
_MAX_FLAGS = 32

_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_FLAG = re.compile(r"[a-z][a-z0-9_]{0,63}")
_PAGE_STATUSES = frozenset({"read", "no_table", "unreadable"})
_DISPLAYS = frozenset({"inline", "block"})
# JavaScript's `\s` and `trim()` set, so whitespace normalization matches the TypeScript validator.
_JS_SPACE = r"[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]"
_JS_SPACE_RUN = re.compile(_JS_SPACE + "+")
_JS_TRIM = re.compile(rf"\A{_JS_SPACE}+|{_JS_SPACE}+\Z")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LATEX_TOKEN = re.compile(
    r"\\begin\{([A-Za-z*]+)\}|\\end\{([A-Za-z*]+)\}|\\left(?![A-Za-z])|\\right(?![A-Za-z])"
    r"|\\[\\{}$]|[{}$]"
)

PageStatus = Literal["read", "no_table", "unreadable"]


class OcrRegion(TypedDict):
    regionId: str
    pageIndex0: int
    text: str
    bbox1000: list[int]


class TableReadExpectation(TypedDict):
    """What the caller already holds: the persisted ocr.json binding and that page's regions."""

    sourceImmutableKey: str
    inputSha256: str
    readerRevision: str
    readerBindingSha256: str
    pageIndex0: int
    ocrRegions: list[OcrRegion]


class QualifiedTableCell(TypedDict):
    cellId: str
    rowIndex0: int
    columnIndex0: int
    rowSpan: int
    columnSpan: int
    text: str
    bbox1000: list[int] | None  # exactly what the reader gave; null stays null
    locatorBbox1000: list[int]  # its own box, or its table's when it has none
    confirmedBy: list[str]
    qualityFlags: list[str]
    reasonCode: Literal["TABLE_CELL_TEXT_UNCONFIRMED"] | None


class QualifiedTable(TypedDict):
    tableId: str
    bbox1000: list[int]
    rowCount: int
    columnCount: int
    headerRowCount: int
    cells: list[QualifiedTableCell]
    qualityFlags: list[str]


class QualifiedFormula(TypedDict):
    formulaId: str
    bbox1000: list[int]
    latex: str
    display: Literal["inline", "block"]


class TableReadRefusal(TypedDict):
    bbox1000: list[int] | None
    reasonCode: RefusalReasonCode


class TableReadFailure(TypedDict):
    ok: Literal[False]
    reasonCode: DocumentFailureCode
    detail: str


class TableReadAccepted(TypedDict):
    ok: Literal[True]
    pageIndex0: int
    pageNumber1: int
    pageStatus: PageStatus  # recomputed from what survived validation
    tables: list[QualifiedTable]
    formulas: list[QualifiedFormula]
    refusals: list[TableReadRefusal]  # the reader's, then the validator's, in document order


TableReadQualification = TableReadFailure | TableReadAccepted
_Row = dict[str, Any]


class TableReadRejected(Exception):
    """A table_read page or table that cannot become CIR, with the contract's reasonCode."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


class _DocumentFailure(Exception):
    def __init__(self, reason_code: DocumentFailureCode, detail: str) -> None:
        super().__init__(detail)
        self.reason_code: DocumentFailureCode = reason_code


def _invalid(detail: str) -> _DocumentFailure:
    return _DocumentFailure("TABLE_READ_SCHEMA_INVALID", detail)


def _mismatch(detail: str) -> _DocumentFailure:
    return _DocumentFailure("TABLE_BINDING_MISMATCH", detail)


def _is_int(value: object) -> bool:
    return type(value) is int  # not bool, not 1.0


def _is_count(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _js_length(value: str) -> int:
    """String length in UTF-16 code units, as JavaScript's `.length` counts it."""
    return len(value.encode("utf-16-le", "surrogatepass")) // 2


def _is_text(value: object, limit: int) -> bool:
    return isinstance(value, str) and _js_length(value) <= limit


def _exact_keys(value: _Row, keys: tuple[str, ...]) -> bool:
    return sorted(value) == sorted(keys)


def is_bbox1000(value: object) -> bool:
    """ADR-001: four integers 0..1000 with x1<x2 and y1<y2."""
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(_is_count(coordinate, 0, 1000) for coordinate in value)
        and value[0] < value[2]
        and value[1] < value[3]
    )


def _contains(outer: list[int], inner: list[int]) -> bool:
    x1, y1, x2, y2 = outer
    return inner[0] >= x1 and inner[1] >= y1 and inner[2] <= x2 and inner[3] <= y2


def _overlaps(a: list[int], b: list[int]) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def normalize_space(text: str) -> str:
    """The plan's whitespace normalization (§C2(2)): no case folding, no Unicode normalization."""
    return _JS_SPACE_RUN.sub(" ", text).strip(" ")


def _status_of(table_count: int, refusals: list[TableReadRefusal] | list[_Row]) -> PageStatus:
    if table_count > 0:
        return "read"
    if any(refusal["reasonCode"] in _TABLE_REFUSAL_CODES for refusal in refusals):
        return "unreadable"
    return "no_table"


def is_structurally_valid_latex(latex: str) -> bool:
    """Brace, `\\begin`/`\\end` and `\\left`/`\\right` balance, no bare `$`, no control characters.

    ponytail: a structural check, not a LaTeX parser (`\\frac{a}` passes), the same ceiling as the
    TypeScript contract. The upgrade is the renderer's own parser once formulas are drawn.
    """
    if not _JS_TRIM.sub("", latex) or _js_length(latex) > _MAX_TEXT or _CONTROL.search(latex):
        return False
    stack: list[str] = []
    for match in _LATEX_TOKEN.finditer(latex):
        lexeme, begin, end = match.group(0), match.group(1), match.group(2)
        if begin:
            stack.append(f"env:{begin}")
        elif end:
            if not stack or stack.pop() != f"env:{end}":
                return False
        elif lexeme == "\\left":
            stack.append("left")
        elif lexeme == "\\right":
            if not stack or stack.pop() != "left":
                return False
        elif lexeme == "{":
            stack.append("{")
        elif lexeme == "}":
            if not stack or stack.pop() != "{":
                return False
        elif lexeme == "$":
            return False
    return not stack


def _grid_error(table: _Row) -> str | None:
    """`CanonicalTable.validate_grid`, the same rules in the same order, on the wire shape."""
    rows, columns = table["rowCount"], table["columnCount"]
    if table["headerRowCount"] > rows:
        return "headerRowCount exceeds rowCount"
    if not table["cells"]:
        return "table must contain at least one cell"
    occupied: dict[tuple[int, int], str] = {}
    for cell in table["cells"]:
        row_end = cell["rowIndex0"] + cell["rowSpan"]
        column_end = cell["columnIndex0"] + cell["columnSpan"]
        if row_end > rows or column_end > columns:
            return f"cell {cell['cellId']} span exceeds table dimensions"
        for row in range(cell["rowIndex0"], row_end):
            for column in range(cell["columnIndex0"], column_end):
                holder = occupied.get((row, column))
                if holder is not None:
                    return f"cell {cell['cellId']} overlaps {holder} at {row},{column}"
                occupied[(row, column)] = cell["cellId"]
    return None


def _check_shape(doc: _Row) -> tuple[list[_Row], list[_Row], list[_Row]]:
    """Shape, bounds and internal consistency. Raises TABLE_READ_SCHEMA_INVALID."""
    if not _exact_keys(
        doc,
        (
            "schemaVersion", "sourceImmutableKey", "inputSha256", "readerRevision",
            "readerBindingSha256", "pageIndex0", "pageNumber1", "pageStatus", "tables",
            "formulas", "refusals",
        ),
    ):
        raise _invalid("document keys are not the table_read.v1 set")
    if doc["schemaVersion"] != TABLE_READ_SCHEMA:
        raise _invalid("schemaVersion is not tavonel.table_read.v1")
    if not _is_text(doc["sourceImmutableKey"], 1024) or not doc["sourceImmutableKey"]:
        raise _invalid("sourceImmutableKey is not a key")
    for field in ("inputSha256", "readerRevision", "readerBindingSha256"):
        if not isinstance(doc[field], str) or not _DIGEST.fullmatch(doc[field]):
            raise _invalid(f"{field} is not a sha256 digest")
    if not _is_count(doc["pageIndex0"], 0, 999_999) or not (
        _is_int(doc["pageNumber1"]) and doc["pageNumber1"] == doc["pageIndex0"] + 1
    ):
        raise _invalid("pageNumber1 must equal pageIndex0 + 1")
    if not isinstance(doc["pageStatus"], str) or doc["pageStatus"] not in _PAGE_STATUSES:
        raise _invalid("pageStatus is not read, no_table or unreadable")

    def bounded(name: str, limit: int) -> list[_Row]:
        value = doc[name]
        if not isinstance(value, list) or len(value) > limit or not all(
            isinstance(item, dict) for item in value
        ):
            raise _invalid(f"{name} is not a bounded list of objects")
        return value

    tables = bounded("tables", _MAX_TABLES)
    formulas = bounded("formulas", _MAX_FORMULAS)
    refusals = bounded("refusals", _MAX_REFUSALS)

    ids: set[str] = set()

    def unique_id(value: object, what: str) -> None:
        if not isinstance(value, str) or not _ID.fullmatch(value) or value in ids:
            raise _invalid(f"{what} is missing, malformed or repeated")
        ids.add(value)

    def flags(value: object, what: str) -> None:
        if (
            not isinstance(value, list)
            or len(value) > _MAX_FLAGS
            or any(not isinstance(flag, str) or not _FLAG.fullmatch(flag) for flag in value)
        ):
            raise _invalid(f"{what} qualityFlags are malformed")

    for table in tables:
        if not _exact_keys(
            table,
            (
                "tableId", "bbox1000", "rowCount", "columnCount", "headerRowCount", "cells",
                "qualityFlags",
            ),
        ):
            raise _invalid("table keys are not the table_read.v1 set")
        unique_id(table["tableId"], "tableId")
        # Any bbox value passes here: a missing or unusable one is TABLE_REGION_UNLOCATED.
        if not (
            _is_count(table["rowCount"], 1, _MAX_GRID_EXTENT)
            and _is_count(table["columnCount"], 1, _MAX_GRID_EXTENT)
            and _is_count(table["headerRowCount"], 0, _MAX_GRID_EXTENT)
        ):
            raise _invalid(f"table {table['tableId']} dimensions are not bounded integers")
        flags(table["qualityFlags"], f"table {table['tableId']}")
        cells = table["cells"]
        if not isinstance(cells, list) or len(cells) > _MAX_CELLS or not all(
            isinstance(cell, dict) for cell in cells
        ):
            raise _invalid(f"table {table['tableId']} cells are not a bounded list")
        for cell in cells:
            if not _exact_keys(
                cell,
                (
                    "cellId", "rowIndex0", "columnIndex0", "rowSpan", "columnSpan", "text",
                    "bbox1000", "confirmedBy",
                ),
            ):
                raise _invalid("cell keys are not the table_read.v1 set")
            unique_id(cell["cellId"], "cellId")
            if not (
                _is_count(cell["rowIndex0"], 0, _MAX_GRID_EXTENT)
                and _is_count(cell["columnIndex0"], 0, _MAX_GRID_EXTENT)
                and _is_count(cell["rowSpan"], 1, _MAX_GRID_EXTENT)
                and _is_count(cell["columnSpan"], 1, _MAX_GRID_EXTENT)
            ):
                raise _invalid(f"cell {cell['cellId']} position is not bounded integers")
            if not _is_text(cell["text"], _MAX_TEXT):
                raise _invalid(f"cell {cell['cellId']} text is not a bounded string")
            # Null or an array; an array that is not a usable box is TABLE_REGION_UNLOCATED.
            if cell["bbox1000"] is not None and not isinstance(cell["bbox1000"], list):
                raise _invalid(f"cell {cell['cellId']} bbox1000 is neither null nor a box")
            confirmed_by = cell["confirmedBy"]
            if (
                not isinstance(confirmed_by, list)
                or len(confirmed_by) > _MAX_CONFIRMED_BY
                or any(
                    not isinstance(item, str) or not _ID.fullmatch(item) for item in confirmed_by
                )
                or len(set(confirmed_by)) != len(confirmed_by)
            ):
                raise _invalid(f"cell {cell['cellId']} confirmedBy is malformed")
    for formula in formulas:
        if not _exact_keys(formula, ("formulaId", "bbox1000", "latex", "display")):
            raise _invalid("formula keys are not the table_read.v1 set")
        unique_id(formula["formulaId"], "formulaId")
        if not is_bbox1000(formula["bbox1000"]):
            raise _invalid(f"formula {formula['formulaId']} bbox1000 is not a box")
        if not isinstance(formula["latex"], str) or not (
            isinstance(formula["display"], str) and formula["display"] in _DISPLAYS
        ):
            raise _invalid(f"formula {formula['formulaId']} latex or display is malformed")
    for refusal in refusals:
        if (
            not _exact_keys(refusal, ("bbox1000", "reasonCode"))
            or not isinstance(refusal["reasonCode"], str)
            or refusal["reasonCode"] not in _REFUSAL_CODES
            or (refusal["bbox1000"] is not None and not is_bbox1000(refusal["bbox1000"]))
        ):
            raise _invalid("refusal is not a located or null-located refusal code")
        # A region the reader refused and read at once: half a truncated table is not a table.
        if (
            refusal["bbox1000"] is not None
            and refusal["reasonCode"] in _TABLE_REFUSAL_CODES
            and any(
                is_bbox1000(table["bbox1000"]) and _overlaps(table["bbox1000"], refusal["bbox1000"])
                for table in tables
            )
        ):
            raise _invalid(
                f"a {refusal['reasonCode']} refusal overlaps a table the reader emitted"
            )
    if _status_of(len(tables), refusals) != doc["pageStatus"]:
        raise _invalid("pageStatus contradicts the tables and refusals")
    return tables, formulas, refusals


def _check_binding(doc: _Row, expected: TableReadExpectation) -> None:
    """The document is about the bytes, reader and page the caller holds."""
    for field in (
        "sourceImmutableKey", "inputSha256", "readerRevision", "readerBindingSha256", "pageIndex0",
    ):
        if doc[field] != expected[field]:
            raise _mismatch(f"{field} does not match the expected binding")


def _check_confirmations(tables: list[_Row], expected: TableReadExpectation) -> None:
    """`confirmedBy` is the second reader's measurement (§C2(2)).

    Every named OCR region is on this page, inside this table's box, used by one cell only, and
    together the regions read the same text. A confirmation that does not hold means the document
    was joined to other OCR output, so it fails whole; it is never downgraded to "unconfirmed".
    """
    regions = {region["regionId"]: region for region in expected["ocrRegions"]}
    used: set[str] = set()
    for table in tables:
        for cell in table["cells"]:
            if not cell["confirmedBy"]:
                continue
            texts: list[str] = []
            for region_id in cell["confirmedBy"]:
                region = regions.get(region_id)
                if region is None or region["pageIndex0"] != expected["pageIndex0"]:
                    raise _mismatch(
                        f"cell {cell['cellId']} names OCR region {region_id}, "
                        "which is not on this page"
                    )
                if region_id in used:
                    raise _mismatch(f"OCR region {region_id} confirms more than one cell")
                if is_bbox1000(table["bbox1000"]) and not _contains(
                    table["bbox1000"], region["bbox1000"]
                ):
                    raise _mismatch(f"OCR region {region_id} lies outside table {table['tableId']}")
                used.add(region_id)
                texts.append(region["text"])
            if normalize_space(" ".join(texts)) != normalize_space(cell["text"]):
                raise _mismatch(
                    f"cell {cell['cellId']} text differs from the OCR regions that confirm it"
                )


def _table_refusal(table: _Row) -> TableReadRefusal | None:
    if not is_bbox1000(table["bbox1000"]):
        return {"bbox1000": None, "reasonCode": "TABLE_REGION_UNLOCATED"}
    box: list[int] = table["bbox1000"]
    if _grid_error(table):
        return {"bbox1000": list(box), "reasonCode": "TABLE_GRID_INVALID"}
    # A cell box that is unusable or falls outside its table is not clamped into place.
    if any(
        cell["bbox1000"] is not None
        and (not is_bbox1000(cell["bbox1000"]) or not _contains(box, cell["bbox1000"]))
        for cell in table["cells"]
    ):
        return {"bbox1000": list(box), "reasonCode": "TABLE_REGION_UNLOCATED"}
    return None


def _qualified_table(table: _Row) -> QualifiedTable:
    box: list[int] = table["bbox1000"]
    quality_flags = list(table["qualityFlags"])
    if (
        any(cell["bbox1000"] is None for cell in table["cells"])
        and CELL_LOCATED_BY_TABLE_BBOX_ONLY not in quality_flags
    ):
        quality_flags.append(CELL_LOCATED_BY_TABLE_BBOX_ONLY)
    cells: list[QualifiedTableCell] = []
    for cell in table["cells"]:
        own: list[int] | None = cell["bbox1000"]
        confirmed_by = list(cell["confirmedBy"])
        cells.append(
            {
                "cellId": cell["cellId"],
                "rowIndex0": cell["rowIndex0"],
                "columnIndex0": cell["columnIndex0"],
                "rowSpan": cell["rowSpan"],
                "columnSpan": cell["columnSpan"],
                "text": cell["text"],
                "bbox1000": list(own) if own is not None else None,
                "locatorBbox1000": list(own if own is not None else box),
                "confirmedBy": confirmed_by,
                "qualityFlags": [] if own is not None else [CELL_LOCATED_BY_TABLE_BBOX_ONLY],
                "reasonCode": None if confirmed_by else "TABLE_CELL_TEXT_UNCONFIRMED",
            }
        )
    return {
        "tableId": table["tableId"],
        "bbox1000": list(box),
        "rowCount": table["rowCount"],
        "columnCount": table["columnCount"],
        "headerRowCount": table["headerRowCount"],
        "qualityFlags": quality_flags,
        "cells": cells,
    }


def qualify_table_read(payload: object, expected: TableReadExpectation) -> TableReadQualification:
    """Qualify one page of table reader output.

    `payload` None means the reader produced nothing: TABLE_READER_UNAVAILABLE, which must never
    be read as "this page has no table".
    """
    if payload is None:
        return {
            "ok": False,
            "reasonCode": "TABLE_READER_UNAVAILABLE",
            "detail": "no table reader output for this page",
        }
    try:
        if not isinstance(payload, dict):
            raise _invalid("document is not an object")
        tables, formulas, refusals = _check_shape(payload)
        _check_binding(payload, expected)
        _check_confirmations(tables, expected)
    except _DocumentFailure as failure:
        return {"ok": False, "reasonCode": failure.reason_code, "detail": str(failure)}

    out_refusals: list[TableReadRefusal] = [
        {
            "bbox1000": None if refusal["bbox1000"] is None else list(refusal["bbox1000"]),
            "reasonCode": refusal["reasonCode"],
        }
        for refusal in refusals
    ]
    out_tables: list[QualifiedTable] = []
    for table in tables:
        refused = _table_refusal(table)
        if refused is not None:
            out_refusals.append(refused)
        else:
            out_tables.append(_qualified_table(table))
    out_formulas: list[QualifiedFormula] = []
    for formula in formulas:
        box = list(formula["bbox1000"])
        if is_structurally_valid_latex(formula["latex"]):
            out_formulas.append(
                {
                    "formulaId": formula["formulaId"],
                    "bbox1000": box,
                    "latex": formula["latex"],
                    "display": formula["display"],
                }
            )
        else:
            out_refusals.append({"bbox1000": box, "reasonCode": "FORMULA_LATEX_INVALID"})
    return {
        "ok": True,
        "pageIndex0": payload["pageIndex0"],
        "pageNumber1": payload["pageNumber1"],
        "pageStatus": _status_of(len(out_tables), out_refusals),
        "tables": out_tables,
        "formulas": out_formulas,
        "refusals": out_refusals,
    }


def canonical_tables(
    page: TableReadQualification,
    expected: TableReadExpectation,
    *,
    document_id: str,
    document_version_id: str,
) -> tuple[CanonicalTable, ...]:
    """Map a qualified page's tables onto CIR (§C3), origin AI_RECONSTRUCTED.

    A failed page raises with its own reasonCode instead of returning no tables: an empty result
    would read as "this page has no table".
    """
    if page["ok"] is False:
        raise TableReadRejected(page["reasonCode"], page["detail"])
    page_index0 = page["pageIndex0"]

    def ref(bbox: list[int], native_object_id: str | None) -> SourceRef:
        return SourceRef(
            document_id=document_id,
            document_version_id=document_version_id,
            page_index0=page_index0,
            page_number1=page_index0 + 1,
            bbox1000=BBox1000((bbox[0], bbox[1], bbox[2], bbox[3])),
            native_object_id=native_object_id,
        )

    out: list[CanonicalTable] = []
    for table in page["tables"]:
        table_id = _stable_id(
            "table_read",
            document_version_id,
            expected["inputSha256"],
            expected["readerBindingSha256"],
            str(page_index0),
            table["tableId"],
        )
        cells: list[CanonicalCell] = []
        for cell in table["cells"]:
            if len(cell["cellId"]) < 3:
                # table_read.v1 allows 1-2 character ids; CIR StableId needs three. Carried
                # verbatim or not at all: never padded or renamed into a different id.
                raise TableReadRejected(
                    "TABLE_READ_SCHEMA_INVALID",
                    f"cellId {cell['cellId']} is shorter than a CIR native object id",
                )
            flags = tuple(cell["qualityFlags"])
            if cell["reasonCode"] is not None:
                flags += (CELL_TEXT_UNCONFIRMED_FLAG,)
            cells.append(
                CanonicalCell(
                    id=_stable_id("table_read_cell", table_id, cell["cellId"]),
                    row_index0=cell["rowIndex0"],
                    column_index0=cell["columnIndex0"],
                    row_span=cell["rowSpan"],
                    column_span=cell["columnSpan"],
                    raw_text=cell["text"],
                    normalized_text=normalize_space(cell["text"]),
                    origin=BlockOrigin.AI_RECONSTRUCTED,
                    source_refs=(ref(cell["locatorBbox1000"], cell["cellId"]),),
                    quality_flags=flags,
                )
            )
        try:
            out.append(
                CanonicalTable(
                    id=table_id,
                    row_count=table["rowCount"],
                    column_count=table["columnCount"],
                    header_row_count=table["headerRowCount"],
                    cells=tuple(cells),
                    source_refs=(ref(table["bbox1000"], None),),
                    quality_flags=tuple(table["qualityFlags"]),
                )
            )
        except ValidationError as error:
            # Ids, refs and counts are already valid here, so only validate_grid can refuse.
            raise TableReadRejected("TABLE_GRID_INVALID", str(error)) from error
    return tuple(out)


@dataclass(frozen=True, slots=True)
class TableCellClaim:
    claim_id: str
    table_id: str
    cell_id: str
    column_header_path: tuple[str, ...]
    value_text: str
    text: str
    numeric_values: tuple[str, ...]
    # The value cell's SourceRef first, then each header cell it used, top to bottom.
    source_refs: tuple[SourceRef, ...]


def table_cell_claims(table: CanonicalTable) -> tuple[TableCellClaim, ...]:
    """One claim per confirmed data cell under a confirmed column header path (§C3)."""
    if any(cell.origin is not BlockOrigin.AI_RECONSTRUCTED for cell in table.cells):
        # The confirmation rule belongs to the table reader lane; a native table lacks its flag.
        raise ValueError("table cell claims are defined for table reader output only")
    header_rows = table.header_row_count
    if header_rows == 0:
        return ()
    slot: dict[tuple[int, int], CanonicalCell] = {}
    for cell in table.cells:
        for row in range(cell.row_index0, cell.row_index0 + cell.row_span):
            for column in range(cell.column_index0, cell.column_index0 + cell.column_span):
                slot[(row, column)] = cell
    claims: list[TableCellClaim] = []
    for cell in table.cells:
        if (
            cell.row_index0 < header_rows
            or CELL_TEXT_UNCONFIRMED_FLAG in cell.quality_flags
            or not cell.normalized_text
        ):
            continue
        path: list[CanonicalCell] = []
        for row in range(header_rows):
            header = slot.get((row, cell.column_index0))
            # A header spanning several header rows is one level, not one per row.
            if header is None or not header.normalized_text:
                continue
            if not path or path[-1].id != header.id:
                path.append(header)
        if not path or any(CELL_TEXT_UNCONFIRMED_FLAG in header.quality_flags for header in path):
            continue
        column_path = tuple(header.normalized_text for header in path)
        text = f"{' / '.join(column_path)}: {cell.normalized_text}"
        claims.append(
            TableCellClaim(
                claim_id=_stable_id("table_claim", table.id, cell.id, text),
                table_id=table.id,
                cell_id=cell.id,
                column_header_path=column_path,
                value_text=cell.normalized_text,
                text=text,
                numeric_values=tuple(
                    match.group(0).strip() for match in _NUMBER.finditer(cell.normalized_text)
                ),
                source_refs=cell.source_refs
                + tuple(ref for header in path for ref in header.source_refs),
            )
        )
    return tuple(claims)
