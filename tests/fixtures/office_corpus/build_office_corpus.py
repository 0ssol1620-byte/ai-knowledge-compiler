"""Deterministic native-Office qualification corpus (lane C-3).

Running this module rewrites every file under ``tests/fixtures/office_corpus``
plus ``expected.json``. Two runs produce byte-identical output, and
``tests/unit/test_office_qualification.py`` asserts that.

**How determinism is reached.** openpyxl, python-docx and python-pptx stamp the
local clock into three places: the ZIP member timestamps, the core properties,
and ``w:date`` on a comment or a tracked change. The first is rewritten to a
fixed 1980-01-01 by :func:`_rewrite_package`, the second is set explicitly to
:data:`FIXED_TIME`, and the third is scrubbed to :data:`FIXED_DATE`. Nothing
else in these packages carries a clock — which is why the corpus can be
committed as bytes rather than hashed after parsing. Determinism is a property
of *this* library set (openpyxl 3.1.5, python-docx 1.2.0, python-pptx 1.0.2), not
a claim about every version of them.

**What ``expected.json`` is.** Per file, the facts a faithful reader must
recover, written from the literals this builder put into the file — never from
what a parser reported back. A row that a reader fails is a fail; the manifest is
not edited to make it pass (lane contract §1, C-4).

That rule was broken once and is worth naming: six ``"Slide N"`` strings sat
in the ``pptx_slide_units`` rows of four files whose slides use the Blank
layout. No such text is in those packages -- it is the heading the pptx parser
invents for a slide with no title placeholder, flagged
``slide_title_inferred``. The literals were written from what the parser
reported back, and four receipt rows passed on text that is not in the source.
They are gone, and the reader no longer emits the invented block at all.

Comments, tracked changes, footnotes and the OMML equation have no python-docx
authoring API, so they are injected as raw WordprocessingML. The footnote part
is added to ``[Content_Types].xml`` and to the document relationships as well as
to the package, so the fixture is a real DOCX and not a part smuggled past the
package rules.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
import zipfile
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.section import WD_SECTION
from lxml import etree
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from pptx import Presentation
from pptx.util import Inches, Pt

CORPUS_ROOT = Path(__file__).resolve().parent
EXPECTED_PATH = CORPUS_ROOT / "expected.json"
EXPECTED_SCHEMA = "tavonel.office_corpus_expected.v1"
FORMATS = ("xlsx", "docx", "pptx")

#: One clock for the whole corpus.
FIXED_TIME = datetime(2026, 1, 1, 0, 0, 0)
FIXED_DATE = "2026-01-01T00:00:00Z"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_FOOTNOTES_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
)
_FOOTNOTES_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
_ENDNOTES_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"
_ENDNOTES_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes"

_DATE_ATTRIBUTE = re.compile(rb'\sw:date="[^"]*"')
#: openpyxl and python-pptx overwrite `modified` with the local clock inside
#: `save()`, after the caller has set the core properties, so the value has to be
#: scrubbed from the written package rather than set on the object.
_DCTERMS = re.compile(
    rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)"
)


# --------------------------------------------------------------------------
# package plumbing
# --------------------------------------------------------------------------


def _rewrite_package(
    payload: bytes,
    *,
    edit: Callable[[str, bytes], bytes] | None = None,
    extra: dict[str, bytes] | None = None,
) -> bytes:
    """Rewrite an OOXML package deterministically, with optional edits.

    Members are written in sorted name order with fixed timestamps, every
    ``w:date`` attribute becomes :data:`FIXED_DATE`, ``edit`` may rewrite a
    member, and ``extra`` adds new parts.

    Sorting is not cosmetic. openpyxl decides its part order from a set, so the
    same workbook comes out in a different member order in a different process —
    the corpus was byte-stable within one interpreter and unstable across two
    until the order stopped depending on hash randomisation. ``[Content_Types]``
    still sorts first, and OPC readers address parts by name, never by position.
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as source:
        members = {
            info.filename: (source.read(info.filename), info.external_attr)
            for info in source.infolist()
        }
    for name, member in (extra or {}).items():
        members[name] = (member, 0)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for name in sorted(members):
            data, external_attr = members[name]
            if edit is not None:
                data = edit(name, data)
            data = _DATE_ATTRIBUTE.sub(b' w:date="' + FIXED_DATE.encode() + b'"', data)
            data = _DCTERMS.sub(rb"\g<1>" + FIXED_DATE.encode() + rb"\g<2>", data)
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = external_attr
            target.writestr(entry, data)
    return out.getvalue()


def _replace_once(member: bytes, old: bytes, new: bytes) -> bytes:
    """Rewrite one fragment, or fail loudly.

    A `bytes.replace` that matches nothing returns the input, so a fixture that
    was supposed to carry an injected construct would be committed without it
    and the row that tests for it would fail for the wrong reason — exactly how
    ``07-chart-cached-series.xlsx`` came to have no cached series.
    """
    if old not in member:
        raise ValueError(f"fixture fragment not found: {old!r}")
    return member.replace(old, new, 1)


def _insert_before(member: bytes, closing: bytes, addition: bytes) -> bytes:
    if addition in member:
        return member
    return member.replace(closing, addition + closing, 1)


# --------------------------------------------------------------------------
# expected-value helpers
# --------------------------------------------------------------------------


def _row(capability: str, expected: Any) -> dict[str, Any]:
    return {"capability": capability, "expected": expected}


def _cell_text(value: object) -> str:
    """The text form of a spreadsheet value a faithful reader must produce."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return unicodedata.normalize("NFC", str(value)).strip()


def _write_grid(worksheet: Any, origin: str, grid: Sequence[Sequence[object]]) -> None:
    first_row, first_column = coordinate_to_tuple(origin)
    for row_offset, row in enumerate(grid):
        for column_offset, value in enumerate(row):
            if value is None:
                continue
            cell = worksheet.cell(row=first_row + row_offset, column=first_column + column_offset)
            cell.value = value


def _grid_cells(sheet: str, origin: str, grid: Sequence[Sequence[object]]) -> dict[str, str]:
    """``{"Sheet!A1": "text"}`` for every non-empty cell the grid writes."""
    first_row, first_column = coordinate_to_tuple(origin)
    cells: dict[str, str] = {}
    for row_offset, row in enumerate(grid):
        for column_offset, value in enumerate(row):
            if value is None:
                continue
            coordinate = (
                f"{get_column_letter(first_column + column_offset)}{first_row + row_offset}"
            )
            cells[f"{sheet}!{coordinate}"] = _cell_text(value)
    return cells


def _grid_range(origin: str, grid: Sequence[Sequence[object]]) -> str:
    first_row, first_column = coordinate_to_tuple(origin)
    last_row = first_row + len(grid) - 1
    last_column = first_column + max(len(row) for row in grid) - 1
    return (
        f"{get_column_letter(first_column)}{first_row}:"
        f"{get_column_letter(last_column)}{last_row}"
    )


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------


def _workbook(first_sheet: str) -> Workbook:
    workbook = Workbook()
    workbook.worksheets[0].title = first_sheet
    workbook.properties.created = FIXED_TIME
    workbook.properties.modified = FIXED_TIME
    return workbook


def _save_xlsx(workbook: Workbook, *, edit: Callable[[str, bytes], bytes] | None = None) -> bytes:
    payload = io.BytesIO()
    workbook.save(payload)
    return _rewrite_package(payload.getvalue(), edit=edit)


def _cached_value_edit(part: str, cached: dict[str, str]) -> Callable[[str, bytes], bytes]:
    """Write a cached formula result, which openpyxl cannot author.

    A real spreadsheet carries the last value the application computed beside
    the formula text. openpyxl writes an *empty* ``<v/>``, so without this the
    corpus would only ever exercise the "cached value missing" path.
    """

    def edit(name: str, member: bytes) -> bytes:
        if name != part:
            return member
        for coordinate, value in cached.items():
            pattern = re.compile(
                rb'(<c r="' + coordinate.encode() + rb'"[^>]*><f>[^<]*</f>)(?:<v>[^<]*</v>)?'
            )
            member = pattern.sub(rb"\1<v>" + value.encode() + rb"</v>", member)
        return member

    return edit


def _xlsx_basic_grid() -> tuple[bytes, list[dict[str, Any]]]:
    grid = [["Item", "Count"], ["alpha", 2], ["beta", 3], ["gamma", 5]]
    workbook = _workbook("Data")
    _write_grid(workbook["Data"], "A1", grid)
    return _save_xlsx(workbook), [
        _row("xlsx_sheet_names", ["Data"]),
        _row("xlsx_cell_values", _grid_cells("Data", "A1", grid)),
        _row("xlsx_table_range", {"Data": _grid_range("A1", grid)}),
    ]


def _xlsx_formulas_cached() -> tuple[bytes, list[dict[str, Any]]]:
    grid = [["Item", "Count", "Doubled"], ["alpha", 2, "=B2*2"], ["beta", 3, "=B3*2"]]
    workbook = _workbook("Data")
    _write_grid(workbook["Data"], "A1", grid)
    payload = _save_xlsx(
        workbook,
        edit=_cached_value_edit("xl/worksheets/sheet1.xml", {"C2": "4", "C3": "6"}),
    )
    cells = _grid_cells("Data", "A1", grid)
    cells["Data!C2"] = "4"
    cells["Data!C3"] = "6"
    return payload, [
        _row("xlsx_cell_values", cells),
        _row("xlsx_formula_text", {"Data!C2": "=B2*2", "Data!C3": "=B3*2"}),
    ]


def _xlsx_formulas_uncached() -> tuple[bytes, list[dict[str, Any]]]:
    """No cached result: the formula text is all a reader may report."""
    grid = [["Item", "Count", "Trebled"], ["alpha", 2, "=B2*3"]]
    workbook = _workbook("Data")
    _write_grid(workbook["Data"], "A1", grid)
    return _save_xlsx(workbook), [
        _row("xlsx_cell_values", _grid_cells("Data", "A1", grid)),
        _row("xlsx_formula_text", {"Data!C2": "=B2*3"}),
    ]


def _xlsx_merged_header() -> tuple[bytes, list[dict[str, Any]]]:
    workbook = _workbook("Data")
    sheet = workbook["Data"]
    sheet["A1"] = "Quarterly report"
    sheet.merge_cells("A1:C1")
    _write_grid(sheet, "A2", [["Item", "Count", "Share"], ["alpha", 2, "0.4"]])
    cells = {"Data!A1": "Quarterly report"}
    cells.update(_grid_cells("Data", "A2", [["Item", "Count", "Share"], ["alpha", 2, "0.4"]]))
    return _save_xlsx(workbook), [
        _row("xlsx_cell_values", cells),
        _row("xlsx_merged_ranges", {"Data": ["A1:C1"]}),
    ]


def _xlsx_hidden_sheet() -> tuple[bytes, list[dict[str, Any]]]:
    workbook = _workbook("Visible")
    _write_grid(workbook["Visible"], "A1", [["Item"], ["alpha"]])
    hidden = workbook.create_sheet("Draft")
    _write_grid(hidden, "A1", [["Note"], ["not for release"]])
    hidden.sheet_state = "hidden"
    cells = _grid_cells("Visible", "A1", [["Item"], ["alpha"]])
    cells.update(_grid_cells("Draft", "A1", [["Note"], ["not for release"]]))
    return _save_xlsx(workbook), [
        _row("xlsx_sheet_names", ["Visible", "Draft"]),
        _row("xlsx_cell_values", cells),
        _row("xlsx_hidden_sheets", ["Draft"]),
    ]


def _xlsx_named_range() -> tuple[bytes, list[dict[str, Any]]]:
    grid = [["Item", "Revenue"], ["alpha", 2], ["beta", 3]]
    workbook = _workbook("Data")
    _write_grid(workbook["Data"], "A1", grid)
    workbook.defined_names.add(DefinedName("RevenueColumn", attr_text="Data!$B$2:$B$3"))
    return _save_xlsx(workbook), [
        _row("xlsx_cell_values", _grid_cells("Data", "A1", grid)),
        _row("xlsx_named_ranges", {"RevenueColumn": "Data!$B$2:$B$3"}),
    ]


def _xlsx_cell_comments() -> tuple[bytes, list[dict[str, Any]]]:
    grid = [["Item", "Count"], ["alpha", 2], ["beta", 3]]
    workbook = _workbook("Data")
    sheet = workbook["Data"]
    _write_grid(sheet, "A1", grid)
    sheet["B2"].comment = Comment("Restated after the Q2 close.", "reviewer")
    sheet["B3"].comment = Comment("Awaiting the regional split.", "reviewer")
    return _save_xlsx(workbook), [
        _row("xlsx_cell_values", _grid_cells("Data", "A1", grid)),
        _row(
            "xlsx_cell_comments",
            {
                "Data!B2": "Restated after the Q2 close.",
                "Data!B3": "Awaiting the regional split.",
            },
        ),
    ]


def _xlsx_number_formats() -> tuple[bytes, list[dict[str, Any]]]:
    """Cells whose displayed text is not their value.

    A finance sheet shows ``(1,234)`` for a negative and ``1,234원`` for an
    amount. The reader emits ``-1234`` and ``1234``. The expected value here is
    the format string per cell — what a caller would need to reproduce the
    display — and the row is expected to fail at the reader surface, because
    ``ExtractedUnit`` has no formatting field. It is in the corpus so the receipt
    states that gap instead of omitting it.
    """
    grid = [["항목", "금액", "비중"], ["매출", 1234, 0.406], ["영업손실", -1234, -0.113]]
    workbook = _workbook("Data")
    sheet = workbook["Data"]
    _write_grid(sheet, "A1", grid)
    for coordinate in ("B2", "B3"):
        sheet[coordinate].number_format = '#,##0"원";(#,##0)"원"'
    for coordinate in ("C2", "C3"):
        sheet[coordinate].number_format = "0.0%;(0.0%)"
    return _save_xlsx(workbook), [
        _row("xlsx_cell_values", _grid_cells("Data", "A1", grid)),
        _row(
            "xlsx_number_formats",
            {
                "Data!B2": '#,##0"원";(#,##0)"원"',
                "Data!B3": '#,##0"원";(#,##0)"원"',
                "Data!C2": "0.0%;(0.0%)",
                "Data!C3": "0.0%;(0.0%)",
            },
        ),
    ]


def _xlsx_formula_dependency() -> tuple[bytes, list[dict[str, Any]]]:
    """One formula whose operands are other cells.

    Program §27 asks for formula dependency. Nothing parses a formula's
    operands, so this row is expected to fail; it exists so the receipt names
    the gap with a fixture behind it rather than in prose.
    """
    grid = [["Item", "Count"], ["alpha", 2], ["beta", 3], ["total", "=SUM(B2:B3)"]]
    workbook = _workbook("Data")
    _write_grid(workbook["Data"], "A1", grid)
    cells = _grid_cells("Data", "A1", grid)
    cells["Data!B4"] = "5"
    return _save_xlsx(
        workbook,
        edit=_cached_value_edit("xl/worksheets/sheet1.xml", {"B4": "5"}),
    ), [
        _row("xlsx_cell_values", cells),
        _row("xlsx_formula_text", {"Data!B4": "=SUM(B2:B3)"}),
        _row("xlsx_formula_dependency", {"Data!B4": ["Data!B2", "Data!B3"]}),
    ]


def _chart_cache_edit(part: str) -> Callable[[str, bytes], bytes]:
    """Write the series caches openpyxl does not author.

    A real chart carries the last values the application computed beside the
    cell references: ``c:strCache`` under the series name reference and
    ``c:numCache`` under its value reference. openpyxl writes references only,
    so without this the file named ``07-chart-cached-series.xlsx`` contained no
    cache at all and the contract's "chart with cached series" hard case was
    never exercised — the filename claimed what the bytes lacked.
    """

    def edit(name: str, member: bytes) -> bytes:
        if name != part:
            return member
        member = _replace_once(
            member,
            b"<tx><strRef><f>'Data'!B1</f></strRef></tx>",
            b"<tx><strRef><f>'Data'!B1</f><strCache><ptCount val=\"1\"/>"
            b"<pt idx=\"0\"><v>Revenue</v></pt></strCache></strRef></tx>",
        )
        return _replace_once(
            member,
            b"<val><numRef><f>'Data'!$B$2:$B$4</f></numRef></val>",
            b"<val><numRef><f>'Data'!$B$2:$B$4</f><numCache>"
            b"<formatCode>General</formatCode><ptCount val=\"3\"/>"
            b"<pt idx=\"0\"><v>2</v></pt><pt idx=\"1\"><v>3</v></pt>"
            b"<pt idx=\"2\"><v>5</v></pt></numCache></numRef></val>",
        )

    return edit


def _xlsx_chart_cached_series() -> tuple[bytes, list[dict[str, Any]]]:
    grid = [["Quarter", "Revenue"], ["Q1", 2], ["Q2", 3], ["Q3", 5]]
    workbook = _workbook("Data")
    sheet = workbook["Data"]
    _write_grid(sheet, "A1", grid)
    chart = BarChart()
    chart.title = "Quarterly revenue"
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=4), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=4))
    sheet.add_chart(chart, "D2")
    return _save_xlsx(workbook, edit=_chart_cache_edit("xl/charts/chart1.xml")), [
        _row("xlsx_cell_values", _grid_cells("Data", "A1", grid)),
        _row("xlsx_chart_title", {"Data": "Quarterly revenue"}),
        _row("xlsx_chart_series_names", {"Data": ["Revenue"]}),
    ]


def _xlsx_multi_sheet() -> tuple[bytes, list[dict[str, Any]]]:
    grids = {
        "Summary": [["Metric", "Value"], ["total", 10]],
        "Detail": [["Item", "Count"], ["alpha", 4], ["beta", 6]],
        "Notes": [["Note"], ["reconciled"]],
    }
    workbook = _workbook("Summary")
    cells: dict[str, str] = {}
    for name, grid in grids.items():
        sheet = workbook[name] if name == "Summary" else workbook.create_sheet(name)
        _write_grid(sheet, "A1", grid)
        cells.update(_grid_cells(name, "A1", grid))
    return _save_xlsx(workbook), [
        _row("xlsx_sheet_names", list(grids)),
        _row("xlsx_cell_values", cells),
    ]


def _xlsx_offset_origin() -> tuple[bytes, list[dict[str, Any]]]:
    """A used range that does not start at A1.

    The absolute coordinate is the only truthful cell reference; a table-relative
    index would report ``A1`` for what is really ``C5``.
    """
    grid = [["Item", "Count"], ["alpha", 7], ["beta", 8]]
    workbook = _workbook("Offset")
    _write_grid(workbook["Offset"], "C5", grid)
    return _save_xlsx(workbook), [
        _row("xlsx_cell_values", _grid_cells("Offset", "C5", grid)),
        _row("xlsx_table_range", {"Offset": _grid_range("C5", grid)}),
    ]


def _xlsx_value_types() -> tuple[bytes, list[dict[str, Any]]]:
    grid = [
        ["Kind", "Value"],
        ["text", "가나다 Ünïcode"],
        ["integer", 42],
        ["float", 3.5],
        ["boolean", True],
        ["timestamp", datetime(2026, 1, 15, 0, 0, 0)],
    ]
    workbook = _workbook("Types")
    _write_grid(workbook["Types"], "A1", grid)
    return _save_xlsx(workbook), [
        _row("xlsx_cell_values", _grid_cells("Types", "A1", grid)),
    ]


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------


def _document() -> Any:
    document = Document()
    document.core_properties.created = FIXED_TIME
    document.core_properties.modified = FIXED_TIME
    return document


def _save_docx(
    document: Any,
    *,
    edit: Callable[[str, bytes], bytes] | None = None,
    extra: dict[str, bytes] | None = None,
) -> bytes:
    payload = io.BytesIO()
    document.save(payload)
    return _rewrite_package(payload.getvalue(), edit=edit, extra=extra)


def _xml(fragment: str) -> Any:
    return etree.fromstring(fragment)


def _docx_headings_paragraphs() -> tuple[bytes, list[dict[str, Any]]]:
    document = _document()
    document.add_heading("Quarterly report", level=1)
    document.add_paragraph("Revenue rose in every region.")
    document.add_heading("Risks", level=2)
    document.add_paragraph("Supply remains constrained.")
    return _save_docx(document), [
        _row(
            "docx_body_paragraphs",
            [
                "Quarterly report",
                "Revenue rose in every region.",
                "Risks",
                "Supply remains constrained.",
            ],
        ),
    ]


def _docx_table_simple() -> tuple[bytes, list[dict[str, Any]]]:
    document = _document()
    document.add_paragraph("Headcount by team.")
    grid = [["Team", "People"], ["platform", "4"], ["research", "2"]]
    table = document.add_table(rows=3, cols=2)
    for row_index, row in enumerate(grid):
        for column_index, value in enumerate(row):
            table.cell(row_index, column_index).text = value
    cells = {
        f"r/{row_index:06d}/c/{column_index:06d}": value
        for row_index, row in enumerate(grid)
        for column_index, value in enumerate(row)
    }
    return _save_docx(document), [_row("docx_table_cells", {"0": cells})]


def _docx_table_merged_header() -> tuple[bytes, list[dict[str, Any]]]:
    document = _document()
    table = document.add_table(rows=3, cols=2)
    merged = table.cell(0, 0).merge(table.cell(0, 1))
    merged.text = "Headcount"
    body = [["platform", "4"], ["research", "2"]]
    for row_offset, row in enumerate(body):
        for column_index, value in enumerate(row):
            table.cell(row_offset + 1, column_index).text = value
    cells = {"r/000000/c/000000": "Headcount"}
    cells.update(
        {
            f"r/{row_offset + 1:06d}/c/{column_index:06d}": value
            for row_offset, row in enumerate(body)
            for column_index, value in enumerate(row)
        }
    )
    return _save_docx(document), [
        _row("docx_table_cells", {"0": cells}),
        _row("docx_merged_cell_spans", {"0": {"r/000000/c/000000": [1, 2]}}),
    ]


def _docx_comments() -> tuple[bytes, list[dict[str, Any]]]:
    document = _document()
    first = document.add_paragraph("Revenue rose 12 percent.")
    second = document.add_paragraph("Costs were flat.")
    document.add_comment(first.runs, text="Check this number.", author="Dana Reviewer")
    document.add_comment(second.runs, text="Source, please.", author="Kim Auditor")
    return _save_docx(document), [
        _row("docx_comment_text", {"0": "Check this number.", "1": "Source, please."}),
        _row("docx_comment_author", {"0": "Dana Reviewer", "1": "Kim Auditor"}),
    ]


def _docx_tracked_changes() -> tuple[bytes, list[dict[str, Any]]]:
    document = _document()
    paragraph = document.add_paragraph("The contract runs for ")
    paragraph._p.append(
        _xml(
            f'<w:ins xmlns:w="{W_NS}" w:id="101" w:author="Dana Reviewer" w:date="{FIXED_DATE}">'
            "<w:r><w:t>three years</w:t></w:r></w:ins>"
        )
    )
    paragraph._p.append(
        _xml(
            f'<w:del xmlns:w="{W_NS}" w:id="102" w:author="Dana Reviewer" w:date="{FIXED_DATE}">'
            "<w:r><w:delText>two years</w:delText></w:r></w:del>"
        )
    )
    return _save_docx(document), [
        _row("docx_body_paragraphs", ["The contract runs for three years"]),
        _row(
            "docx_tracked_changes",
            [
                {"kind": "insertion", "text": "three years"},
                {"kind": "deletion", "text": "two years"},
            ],
        ),
    ]


def _docx_headers_footers() -> tuple[bytes, list[dict[str, Any]]]:
    document = _document()
    document.add_paragraph("Body of the single-section document.")
    section = document.sections[0]
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    section.header.paragraphs[0].text = "Acme internal"
    section.footer.paragraphs[0].text = "Confidential draft"
    return _save_docx(document), [
        _row(
            "docx_headers_footers",
            {
                "docx/section/0000/header/p/000000": "Acme internal",
                "docx/section/0000/footer/p/000000": "Confidential draft",
            },
        ),
    ]


def _docx_multi_section_headers() -> tuple[bytes, list[dict[str, Any]]]:
    document = _document()
    document.add_paragraph("First section body.")
    document.sections[0].header.is_linked_to_previous = False
    document.sections[0].header.paragraphs[0].text = "Part one"
    second = document.add_section(WD_SECTION.NEW_PAGE)
    second.header.is_linked_to_previous = False
    second.header.paragraphs[0].text = "Part two"
    document.add_paragraph("Second section body.")
    return _save_docx(document), [
        _row(
            "docx_headers_footers",
            {
                "docx/section/0000/header/p/000000": "Part one",
                "docx/section/0001/header/p/000000": "Part two",
            },
        ),
    ]


def _docx_footnotes() -> tuple[bytes, list[dict[str, Any]]]:
    """A real footnotes part, declared in the content types and the rels."""
    document = _document()
    paragraph = document.add_paragraph("Revenue rose 12 percent.")
    paragraph._p.append(
        _xml(f'<w:r xmlns:w="{W_NS}"><w:footnoteReference w:id="2"/></w:r>')
    )
    footnotes = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:footnotes xmlns:w="{W_NS}">'
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p>'
        "</w:footnote>"
        '<w:footnote w:type="continuationSeparator" w:id="0">'
        "<w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>"
        '<w:footnote w:id="2"><w:p><w:r>'
        "<w:t>Source: the internal revenue ledger.</w:t></w:r></w:p></w:footnote>"
        "</w:footnotes>"
    ).encode()

    def edit(name: str, member: bytes) -> bytes:
        if name == "[Content_Types].xml":
            return _insert_before(
                member,
                b"</Types>",
                b'<Override PartName="/word/footnotes.xml" ContentType="'
                + _FOOTNOTES_TYPE.encode()
                + b'"/>',
            )
        if name == "word/_rels/document.xml.rels":
            return _insert_before(
                member,
                b"</Relationships>",
                b'<Relationship Id="rIdFootnotes" Type="'
                + _FOOTNOTES_REL.encode()
                + b'" Target="footnotes.xml"/>',
            )
        return member

    payload = _save_docx(document, edit=edit, extra={"word/footnotes.xml": footnotes})
    return payload, [
        _row("docx_footnotes", {"2": "Source: the internal revenue ledger."}),
    ]


def _docx_omml_equation() -> tuple[bytes, list[dict[str, Any]]]:
    document = _document()
    paragraph = document.add_paragraph()
    paragraph._p.append(
        _xml(
            f'<m:oMath xmlns:m="{M_NS}" xmlns:w="{W_NS}">'
            "<m:sSup><m:e><m:r><m:t>E</m:t></m:r></m:e>"
            "<m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup>"
            "<m:r><m:t>=mc</m:t></m:r></m:oMath>"
        )
    )
    return _save_docx(document), [
        _row("docx_equation_text", ["E2=mc"]),
        _row("docx_equation_formula", True),
    ]


def _docx_unicode_lists() -> tuple[bytes, list[dict[str, Any]]]:
    document = _document()
    document.add_paragraph("분기 보고서")
    document.add_paragraph("첫 번째 항목", style="List Bullet")
    document.add_paragraph("Zweiter Eintrag — mit Gedankenstrich", style="List Bullet")
    return _save_docx(document), [
        _row(
            "docx_body_paragraphs",
            ["분기 보고서", "첫 번째 항목", "Zweiter Eintrag — mit Gedankenstrich"],
        ),
    ]


def _docx_sdt_content_control() -> tuple[bytes, list[dict[str, Any]]]:
    """A body paragraph wrapped in a structured document tag.

    Word writes every content control -- a template field, an approval block, a
    date picker -- as ``w:sdt`` around the paragraph that holds the text. The
    paragraph is ordinary content; only its wrapper differs, and a reader that
    dispatches on the body child's tag name never reaches it.
    """
    document = _document()
    document.add_paragraph("Contract summary.")
    body = document.element.body
    control = _xml(
        f'<w:sdt xmlns:w="{W_NS}"><w:sdtPr><w:alias w:val="Approval"/>'
        '<w:id w:val="411"/><w:text/></w:sdtPr><w:sdtContent>'
        "<w:p><w:r><w:t>Approved by the audit committee.</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt>"
    )
    section_properties = body.find(f"{{{W_NS}}}sectPr")
    section_properties.addprevious(control)
    document.add_paragraph("Signed on the first of January.")
    return _save_docx(document), [
        _row(
            "docx_body_paragraphs",
            [
                "Contract summary.",
                "Approved by the audit committee.",
                "Signed on the first of January.",
            ],
        ),
    ]


def _docx_endnotes() -> tuple[bytes, list[dict[str, Any]]]:
    """A real endnotes part, declared in the content types and the rels."""
    document = _document()
    paragraph = document.add_paragraph("Costs fell four percent.")
    paragraph._p.append(_xml(f'<w:r xmlns:w="{W_NS}"><w:endnoteReference w:id="2"/></w:r>'))
    endnotes = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:endnotes xmlns:w="{W_NS}">'
        '<w:endnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p>'
        "</w:endnote>"
        '<w:endnote w:type="continuationSeparator" w:id="0">'
        "<w:p><w:r><w:continuationSeparator/></w:r></w:p></w:endnote>"
        '<w:endnote w:id="2"><w:p><w:r>'
        "<w:t>Source: the board minutes of 2 January.</w:t></w:r></w:p></w:endnote>"
        "</w:endnotes>"
    ).encode()

    def edit(name: str, member: bytes) -> bytes:
        if name == "[Content_Types].xml":
            return _insert_before(
                member,
                b"</Types>",
                b'<Override PartName="/word/endnotes.xml" ContentType="'
                + _ENDNOTES_TYPE.encode()
                + b'"/>',
            )
        if name == "word/_rels/document.xml.rels":
            return _insert_before(
                member,
                b"</Relationships>",
                b'<Relationship Id="rIdEndnotes" Type="'
                + _ENDNOTES_REL.encode()
                + b'" Target="endnotes.xml"/>',
            )
        return member

    payload = _save_docx(document, edit=edit, extra={"word/endnotes.xml": endnotes})
    return payload, [
        _row("docx_endnotes", {"2": "Source: the board minutes of 2 January."}),
    ]


def _docx_nested_table() -> tuple[bytes, list[dict[str, Any]]]:
    """A table inside a table cell.

    ``_Cell.text`` walks the cell's paragraphs and stops there, so the text of a
    nested table is not part of any cell a reader reports. The outer cell's
    expected text is its own paragraph followed by the nested table's, which is
    the same newline join the cell already uses between its paragraphs.
    """
    document = _document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Outer cell"
    inner = table.cell(0, 0).add_table(rows=1, cols=1)
    inner.cell(0, 0).text = "Inner cell"
    table.cell(0, 1).text = "Right cell"
    table.cell(1, 0).text = "platform"
    table.cell(1, 1).text = "4"
    return _save_docx(document), [
        _row(
            "docx_table_cells",
            {
                "0": {
                    "r/000000/c/000000": "Outer cell\nInner cell",
                    "r/000000/c/000001": "Right cell",
                    "r/000001/c/000000": "platform",
                    "r/000001/c/000001": "4",
                }
            },
        ),
    ]


# --------------------------------------------------------------------------
# PPTX
# --------------------------------------------------------------------------


def _presentation() -> Any:
    presentation = Presentation()
    presentation.core_properties.created = FIXED_TIME
    presentation.core_properties.modified = FIXED_TIME
    return presentation


def _save_pptx(presentation: Any) -> bytes:
    payload = io.BytesIO()
    presentation.save(payload)
    return _rewrite_package(payload.getvalue())


def _blank_slide(presentation: Any) -> Any:
    return presentation.slides.add_slide(presentation.slide_layouts[6])


def _textbox(container: Any, text: str, *, top: float, left: float = 1.0) -> Any:
    box = container.add_textbox(Inches(left), Inches(top), Inches(4), Inches(0.8))
    box.text_frame.text = text
    for paragraph in box.text_frame.paragraphs:
        for run in paragraph.runs:
            run.font.size = Pt(18)
    return box


def _pptx_title_and_body() -> tuple[bytes, list[dict[str, Any]]]:
    presentation = _presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Quarterly review"
    slide.placeholders[1].text_frame.text = "Revenue rose in every region."
    return _save_pptx(presentation), [
        _row("pptx_slide_units", {"1": ["Quarterly review", "Revenue rose in every region."]}),
    ]


def _pptx_speaker_notes() -> tuple[bytes, list[dict[str, Any]]]:
    presentation = _presentation()
    slide = _blank_slide(presentation)
    _textbox(slide.shapes, "Pipeline health", top=1.0)
    slide.notes_slide.notes_text_frame.text = "Mention the two stalled deals."
    return _save_pptx(presentation), [
        _row("pptx_speaker_notes", {"1": "Mention the two stalled deals."}),
    ]


def _pptx_table() -> tuple[bytes, list[dict[str, Any]]]:
    presentation = _presentation()
    slide = _blank_slide(presentation)
    grid = [["Team", "People"], ["platform", "4"], ["research", "2"]]
    table = slide.shapes.add_table(3, 2, Inches(1), Inches(1), Inches(6), Inches(2)).table
    for row_index, row in enumerate(grid):
        for column_index, value in enumerate(row):
            table.cell(row_index, column_index).text = value
    return _save_pptx(presentation), [
        _row("pptx_table_cells", {"1/0000": [value for row in grid for value in row]}),
    ]


def _pptx_grouped_shapes() -> tuple[bytes, list[dict[str, Any]]]:
    presentation = _presentation()
    slide = _blank_slide(presentation)
    group = slide.shapes.add_group_shape()
    _textbox(group.shapes, "Group first", top=1.0)
    _textbox(group.shapes, "Group second", top=2.0)
    _textbox(slide.shapes, "After the group", top=4.0)
    return _save_pptx(presentation), [
        _row("pptx_shape_reading_order", {"1": ["0000.0000", "0000.0001", "0001"]}),
        _row(
            "pptx_slide_units",
            {"1": ["Group first", "Group second", "After the group"]},
        ),
    ]


def _pptx_multi_slide() -> tuple[bytes, list[dict[str, Any]]]:
    presentation = _presentation()
    for index, text in enumerate(("Agenda", "Results", "Next steps"), start=1):
        slide = _blank_slide(presentation)
        _textbox(slide.shapes, f"{text} for slide {index}", top=1.0)
    return _save_pptx(presentation), [
        _row(
            "pptx_slide_units",
            {
                "1": ["Agenda for slide 1"],
                "2": ["Results for slide 2"],
                "3": ["Next steps for slide 3"],
            },
        ),
    ]


def _pptx_nested_group() -> tuple[bytes, list[dict[str, Any]]]:
    presentation = _presentation()
    slide = _blank_slide(presentation)
    outer = slide.shapes.add_group_shape()
    _textbox(outer.shapes, "Outer first", top=1.0)
    inner = outer.shapes.add_group_shape()
    _textbox(inner.shapes, "Inner one", top=2.0)
    _textbox(inner.shapes, "Inner two", top=3.0)
    return _save_pptx(presentation), [
        _row(
            "pptx_shape_reading_order",
            {"1": ["0000.0000", "0000.0001.0000", "0000.0001.0001"]},
        ),
    ]


def _pptx_notes_multi_slide() -> tuple[bytes, list[dict[str, Any]]]:
    presentation = _presentation()
    for index, note in enumerate(("First note.", "Second note."), start=1):
        slide = _blank_slide(presentation)
        _textbox(slide.shapes, f"Slide body {index}", top=1.0)
        slide.notes_slide.notes_text_frame.text = note
    return _save_pptx(presentation), [
        _row("pptx_speaker_notes", {"1": "First note.", "2": "Second note."}),
    ]


def _pptx_textbox_reading_order() -> tuple[bytes, list[dict[str, Any]]]:
    """Three boxes authored bottom-up: reading order is top-to-bottom, not z."""
    presentation = _presentation()
    slide = _blank_slide(presentation)
    _textbox(slide.shapes, "Bottom box", top=5.0)
    _textbox(slide.shapes, "Middle box", top=3.0)
    _textbox(slide.shapes, "Top box", top=1.0)
    return _save_pptx(presentation), [
        _row("pptx_shape_reading_order", {"1": ["0002", "0001", "0000"]}),
        _row("pptx_slide_units", {"1": ["Top box", "Middle box", "Bottom box"]}),
    ]


def _pptx_unicode() -> tuple[bytes, list[dict[str, Any]]]:
    presentation = _presentation()
    slide = _blank_slide(presentation)
    _textbox(slide.shapes, "분기 검토", top=1.0)
    _textbox(slide.shapes, "Résumé — Übersicht", top=2.5)
    return _save_pptx(presentation), [
        _row("pptx_slide_units", {"1": ["분기 검토", "Résumé — Übersicht"]}),
    ]


def _pptx_table_merged_header() -> tuple[bytes, list[dict[str, Any]]]:
    presentation = _presentation()
    slide = _blank_slide(presentation)
    table = slide.shapes.add_table(3, 2, Inches(1), Inches(1), Inches(6), Inches(2)).table
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 0).text = "Headcount"
    body = [["platform", "4"], ["research", "2"]]
    for row_offset, row in enumerate(body):
        for column_index, value in enumerate(row):
            table.cell(row_offset + 1, column_index).text = value
    return _save_pptx(presentation), [
        _row(
            "pptx_table_cells",
            {"1/0000": ["Headcount", "platform", "4", "research", "2"]},
        ),
        _row("pptx_merged_cell_spans", {"1/0000": {"r/0000/c/0000": [1, 2]}}),
    ]


#: A `p:graphicFrame` carrying the SmartArt `graphicData` uri. The diagram parts
#: it would reference in a Word-authored file are deliberately absent: this
#: fixture exists to prove the parser *notices* a diagram frame and says so, and
#: a frame with no `dgm:relIds` is the smallest package that puts one there.
#: python-pptx cannot author SmartArt, so it is injected as raw XML.
_PPTX_SMARTART_FRAME = (
    b'<p:graphicFrame xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
    b' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    b"<p:nvGraphicFramePr>"
    b'<p:cNvPr id="9" name="Diagram 9"/><p:cNvGraphicFramePr/><p:nvPr/>'
    b"</p:nvGraphicFramePr>"
    b'<p:xfrm><a:off x="914400" y="3200400"/><a:ext cx="3657600" cy="1828800"/></p:xfrm>'
    b'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/diagram"/>'
    b"</a:graphic></p:graphicFrame>"
)


def _pptx_smartart_frame() -> tuple[bytes, list[dict[str, Any]]]:
    """A slide whose diagram the parser does not read and does not hide."""
    presentation = _presentation()
    slide = _blank_slide(presentation)
    _textbox(slide.shapes, "Delivery model", top=1.0)
    payload = io.BytesIO()
    presentation.save(payload)

    def edit(name: str, member: bytes) -> bytes:
        if name != "ppt/slides/slide1.xml":
            return member
        return _replace_once(member, b"</p:spTree>", _PPTX_SMARTART_FRAME + b"</p:spTree>")

    return _rewrite_package(payload.getvalue(), edit=edit), [
        _row("pptx_slide_units", {"1": ["Delivery model"]}),
        _row("pptx_smartart_warning", ["pptx_smartart_not_extracted"]),
    ]


# --------------------------------------------------------------------------
# corpus assembly
# --------------------------------------------------------------------------

Builder = Callable[[], "tuple[bytes, list[dict[str, Any]]]"]

CORPUS: dict[str, tuple[tuple[str, Builder], ...]] = {
    "xlsx": (
        ("01-basic-grid.xlsx", _xlsx_basic_grid),
        ("02-formulas-cached.xlsx", _xlsx_formulas_cached),
        ("03-formulas-uncached.xlsx", _xlsx_formulas_uncached),
        ("04-merged-header.xlsx", _xlsx_merged_header),
        ("05-hidden-sheet.xlsx", _xlsx_hidden_sheet),
        ("06-named-range.xlsx", _xlsx_named_range),
        ("07-chart-cached-series.xlsx", _xlsx_chart_cached_series),
        ("08-multi-sheet.xlsx", _xlsx_multi_sheet),
        ("09-offset-origin.xlsx", _xlsx_offset_origin),
        ("10-value-types-unicode.xlsx", _xlsx_value_types),
        ("11-cell-comments.xlsx", _xlsx_cell_comments),
        ("12-number-formats.xlsx", _xlsx_number_formats),
        ("13-formula-dependency.xlsx", _xlsx_formula_dependency),
    ),
    "docx": (
        ("01-headings-paragraphs.docx", _docx_headings_paragraphs),
        ("02-table-simple.docx", _docx_table_simple),
        ("03-table-merged-header.docx", _docx_table_merged_header),
        ("04-comments.docx", _docx_comments),
        ("05-tracked-changes.docx", _docx_tracked_changes),
        ("06-headers-footers.docx", _docx_headers_footers),
        ("07-multi-section-headers.docx", _docx_multi_section_headers),
        ("08-footnotes.docx", _docx_footnotes),
        ("09-omml-equation.docx", _docx_omml_equation),
        ("10-unicode-lists.docx", _docx_unicode_lists),
        ("11-sdt-content-control.docx", _docx_sdt_content_control),
        ("12-endnotes.docx", _docx_endnotes),
        ("13-nested-table.docx", _docx_nested_table),
    ),
    "pptx": (
        ("01-title-and-body.pptx", _pptx_title_and_body),
        ("02-speaker-notes.pptx", _pptx_speaker_notes),
        ("03-table.pptx", _pptx_table),
        ("04-grouped-shapes.pptx", _pptx_grouped_shapes),
        ("05-multi-slide.pptx", _pptx_multi_slide),
        ("06-nested-group.pptx", _pptx_nested_group),
        ("07-notes-multi-slide.pptx", _pptx_notes_multi_slide),
        ("08-textbox-reading-order.pptx", _pptx_textbox_reading_order),
        ("09-unicode.pptx", _pptx_unicode),
        ("10-table-merged-header.pptx", _pptx_table_merged_header),
        ("11-smartart-frame.pptx", _pptx_smartart_frame),
    ),
}


def build_corpus(root: Path) -> dict[str, Any]:
    """Write every corpus file under ``root`` and return the expected manifest."""
    files: list[dict[str, Any]] = []
    for source_format in FORMATS:
        directory = root / source_format
        directory.mkdir(parents=True, exist_ok=True)
        for name, builder in CORPUS[source_format]:
            payload, rows = builder()
            (directory / name).write_bytes(payload)
            files.append(
                {
                    "path": f"{source_format}/{name}",
                    "format": source_format,
                    "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                    "rows": rows,
                }
            )
    return {
        "schemaVersion": EXPECTED_SCHEMA,
        "builder": "tests/fixtures/office_corpus/build_office_corpus.py",
        "libraries": _library_versions(),
        "files": files,
    }


def _library_versions() -> dict[str, str]:
    from importlib.metadata import version

    return {name: version(name) for name in ("openpyxl", "python-docx", "python-pptx")}


def corpus_digest(paths: Iterable[Path]) -> str:
    """sha256 over the corpus files, hashed in sorted-name order."""
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def write_expected(manifest: dict[str, Any], path: Path) -> None:
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    manifest = build_corpus(CORPUS_ROOT)
    write_expected(manifest, EXPECTED_PATH)
    print(f"wrote {len(manifest['files'])} files and {EXPECTED_PATH.name}")


if __name__ == "__main__":
    main()
