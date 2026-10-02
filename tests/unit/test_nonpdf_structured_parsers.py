from __future__ import annotations

import csv
import io
import json
import re
import struct
import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from akc_cir import BlockType, CanonicalCell, CanonicalDocument, CanonicalTable, canonical_json
from akc_native_parsers import (
    SUPPORTED_EXTENSIONS,
    ParseContext,
    ParserLimits,
    StructuredParseError,
    csv_parser,
    parse_non_pdf_to_cir,
)
from akc_native_parsers.csv_parser import CsvPreflight, preflight_csv
from akc_native_parsers.models import normalize_text
from docx import Document as WordDocument
from jsonschema import Draft202012Validator
from openpyxl import Workbook
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula
from openpyxl.worksheet.table import Table as WorksheetTable
from pptx import Presentation
from pptx.util import Inches
from pydantic import ValidationError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "nonpdf"
CANONICAL_DOCUMENT_SCHEMA = (
    Path(__file__).parents[2]
    / "packages"
    / "contracts"
    / "schemas"
    / "canonical-document.schema.json"
)
GENERATED_CONTRACTS = (
    Path(__file__).parents[2] / "packages" / "contracts" / "src" / "generated-contracts.ts"
)
# The optional native-fidelity cell fields: absent and null both mean the
# source did not provide the fact.
NULLABLE_CELL_FIELDS = ("valueType", "numberFormat", "formula")
MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "csv": "text/csv",
}
# Synthetic CSV, written for this test file: quoted delimiter, embedded
# newline, a blank record, spreadsheet formula prefixes, padded and empty
# fields, and one record wider than the rest.
CSV_SOURCE = (
    "name,amount,note\r\n"
    '"Kim, J.",=1+2,"multi\nline"\r\n'
    "\r\n"
    "Lee,-5,@SUM(A1)\r\n"
    'Park,"  spaced  ",\r\n'
    "Choi,1,2,extra\r\n"
)
# Synthetic CSV boundary cases, written for this test file: a quoted
# delimiter, CRLF and LF inside quotes, doubled quotes (one closing a field),
# an empty quoted field, empty fields, blank records ended by CRLF, LF and a
# lone CR, a quote inside an unquoted field, and records ended by the end of
# the text.
CSV_BOUNDARY_SOURCES = (
    CSV_SOURCE,
    'a,"b,c",d\r\n',
    '"x\r\ny","p\nq",z\n',
    '"say ""hi""","""",""\r\n',
    '"a""",b\r\n',
    ",,\r\n,\r\n",
    ",a\r\n",
    "\r\n\n\r\r\nlast",
    "a\rb\r\nc\nd",
    'ab"c,d"e\r\n',
    "a,",
    '"trailing line\r\n"\r\n',
    '"\r\n"',
)


@pytest.fixture
def parse_context() -> ParseContext:
    return ParseContext(
        tenant_id="tenant_fixture",
        document_id="document_fixture",
        document_version_id="version_fixture",
        created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        source_url="https://ingest.example.test/source",
        retrieved_at=datetime(2026, 7, 29, 11, 59, tzinfo=UTC),
    )


@pytest.fixture
def docx_bytes() -> bytes:
    document = WordDocument()
    document.core_properties.title = "구조 보존 DOCX"
    document.add_paragraph("구조 보존 DOCX", style="Title")
    document.add_heading("실험 결과", level=1)
    document.add_paragraph("원문 문단입니다.")
    document.add_paragraph("첫 번째 항목", style="List Bullet")
    table = document.add_table(rows=2, cols=3)
    table.cell(0, 0).text = "구성"
    table.cell(0, 1).text = "점수"
    table.cell(0, 2).text = "비고"
    table.cell(1, 0).text = "개선"
    table.cell(1, 1).text = "0.94"
    table.cell(1, 1).merge(table.cell(1, 2))
    document.sections[0].header.paragraphs[0].text = "보안 등급: 내부"
    document.sections[0].footer.paragraphs[0].text = "문서 끝"
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


@pytest.fixture
def pptx_bytes() -> bytes:
    deck = Presentation()
    first = deck.slides.add_slide(deck.slide_layouts[1])
    first.shapes.title.text = "PPTX 구조"
    body = first.placeholders[1].text_frame
    body.text = "첫 번째 문단"
    bullet = body.add_paragraph()
    bullet.text = "핵심 항목"
    bullet.level = 1
    table = first.shapes.add_table(
        2,
        2,
        Inches(1),
        Inches(4),
        Inches(4),
        Inches(1.5),
    ).table
    table.cell(0, 0).text = "구성"
    table.cell(0, 1).text = "점수"
    table.cell(1, 0).text = "기준"
    table.cell(1, 1).text = "0.86"
    first.notes_slide.notes_text_frame.text = "발표자 전용 메모"
    second = deck.slides.add_slide(deck.slide_layouts[5])
    second.shapes.title.text = "두 번째 슬라이드"
    second.shapes.add_textbox(
        Inches(1),
        Inches(2),
        Inches(5),
        Inches(1),
    ).text_frame.text = "슬라이드 순서를 보존합니다."
    deck.core_properties.title = "구조 보존 PPTX"
    output = io.BytesIO()
    deck.save(output)
    return output.getvalue()


@pytest.fixture
def xlsx_bytes() -> bytes:
    workbook = Workbook()
    workbook.properties.title = "구조 보존 XLSX"
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Results"
    sheet.append(["구성", "점수", "비고", "병합", "합계"])
    sheet.append(["기준", 0.86, "검증 전", None, "=SUM(B2:B3)"])
    sheet.append(["개선", 0.94, "검증 후", None, None])
    sheet.merge_cells("C2:D2")
    sheet.row_dimensions[3].hidden = True
    sheet.add_table(WorksheetTable(displayName="EvidenceTable", ref="A1:B3"))
    hidden = workbook.create_sheet("Raw")
    hidden.sheet_state = "hidden"
    hidden.append(["raw", "value"])
    hidden.append(["alpha", 1])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


@pytest.fixture
def rich_xlsx_bytes() -> bytes:
    """Synthetic multi-sheet workbook built for the native-fidelity tests."""

    workbook = Workbook()
    summary = workbook.active
    assert summary is not None
    summary.title = "Summary"
    summary["A1"] = "분기 실적"
    summary.merge_cells("A1:C1")
    summary.append(["항목", "값", "형식"])
    summary["A3"], summary["B3"] = "중량", 12.5
    summary["B3"].number_format = '#,##0.0" kg"'
    summary["A4"], summary["B4"] = "수량", 1234567
    summary["B4"].number_format = "#,##0"
    summary["A5"], summary["B5"] = "비율", 0.25
    summary["B5"].number_format = "0.00%"
    summary["A6"], summary["B6"] = "기준일", datetime(2026, 3, 31)
    summary["B6"].number_format = "yyyy-mm-dd"
    summary["A7"], summary["B7"] = "검증", True
    summary["A8"], summary["B8"] = "합계", "=SUM(B3:B4)"
    summary["B8"].number_format = "#,##0.0"
    summary["A9"], summary["B9"] = "두 배", "=B3*2"
    summary["E12"] = "sparse"
    archive = workbook.create_sheet("Archive")
    archive.sheet_state = "hidden"
    archive.append(["보관", 1])
    notes = workbook.create_sheet("Notes")
    notes.sheet_state = "veryHidden"
    notes.append(["메모"])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()

    def add_one_formula_cache(value: bytes) -> bytes:
        # openpyxl never writes a cached result. Inject one for B8 only, so the
        # same sheet holds a cached and an uncached formula.
        needle = b"<f>SUM(B3:B4)</f><v></v>"
        assert value.count(needle) == 1
        return value.replace(needle, b"<f>SUM(B3:B4)</f><v>1234579.5</v>")

    return _rewrite_zip(
        output.getvalue(),
        transform={"xl/worksheets/sheet1.xml": add_one_formula_cache},
    )


def _parse(
    *,
    filename: str,
    data: bytes,
    context: ParseContext,
    limits: ParserLimits | None = None,
) -> CanonicalDocument:
    extension = Path(filename).suffix.removeprefix(".")
    return parse_non_pdf_to_cir(
        filename=filename,
        declared_mime=MIME[extension],
        data=data,
        context=context,
        limits=limits,
    )


def test_docx_preserves_xml_order_hierarchy_table_and_story_parts(
    parse_context: ParseContext,
    docx_bytes: bytes,
) -> None:
    document = _parse(
        filename="evidence.docx",
        data=docx_bytes,
        context=parse_context,
    )
    types = [block.type for block in document.blocks]
    assert types[:4] == [
        BlockType.TITLE,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.LIST,
    ]
    assert BlockType.TABLE in types
    assert BlockType.HEADER in types
    assert BlockType.FOOTER in types
    table_block = next(block for block in document.blocks if block.type == BlockType.TABLE)
    assert table_block.table is not None
    assert any(cell.column_span == 2 for cell in table_block.table.cells)
    assert all(
        (native_id := block.source_refs[0].native_object_id) is not None
        and native_id.startswith("docx/")
        for block in document.blocks
    )


def test_pptx_preserves_slide_shape_order_geometry_tables_and_notes(
    parse_context: ParseContext,
    pptx_bytes: bytes,
) -> None:
    document = _parse(
        filename="deck.pptx",
        data=pptx_bytes,
        context=parse_context,
    )
    assert document.metadata["slides"][0]["shapeCount"] >= 3
    assert {block.source_refs[0].page_index0 for block in document.blocks} == {0, 1}
    assert any(block.type == BlockType.TABLE for block in document.blocks)
    assert any(block.type == BlockType.LIST for block in document.blocks)
    assert any(block.type == BlockType.FOOTNOTE for block in document.blocks)
    positioned = [
        block
        for block in document.blocks
        if "/shape/" in (block.source_refs[0].native_object_id or "")
    ]
    assert positioned
    assert all(block.source_refs[0].bbox1000 is not None for block in positioned)


def test_xlsx_preserves_sheet_table_merge_formula_and_visibility(
    parse_context: ParseContext,
    xlsx_bytes: bytes,
) -> None:
    document = _parse(
        filename="workbook.xlsx",
        data=xlsx_bytes,
        context=parse_context,
    )
    assert [sheet["name"] for sheet in document.metadata["sheets"]] == [
        "Results",
        "Raw",
    ]
    assert document.metadata["sheets"][1]["state"] == "hidden"
    table_blocks = [block for block in document.blocks if block.type == BlockType.TABLE]
    assert len(table_blocks) == 2
    first_table = table_blocks[0].table
    assert first_table is not None
    assert any(cell.column_span == 2 for cell in first_table.cells)
    formula = next(cell for cell in first_table.cells if cell.raw_text.startswith("="))
    assert "formula_preserved_not_executed" in formula.quality_flags
    assert "formula_cached_value_missing" in formula.quality_flags
    assert document.metadata["sheets"][0]["tables"][0]["name"] == "EvidenceTable"


def test_html_preserves_dom_blocks_and_never_retains_active_fetches(
    parse_context: ParseContext,
) -> None:
    source = (FIXTURES / "sample.html").read_bytes()
    document = _parse(
        filename="article.html",
        data=source,
        context=parse_context,
    )
    types = {block.type for block in document.blocks}
    assert {
        BlockType.TITLE,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.LIST,
        BlockType.TABLE,
        BlockType.FIGURE,
        BlockType.CAPTION,
    }.issubset(types)
    joined = "\n".join(block.raw_text or "" for block in document.blocks)
    assert "window.evil" not in joined
    assert "제거할 탐색" not in joined
    assert document.metadata["htmlSafety"]["strippedReferenceCount"] == 2
    assert "html_external_references_not_fetched" in document.metadata["warnings"]
    assert all(
        (native_id := block.source_refs[0].native_object_id) is not None
        and native_id.startswith("html/")
        for block in document.blocks
    )


def test_html_preserves_multiple_articles_and_unique_text_node_locations(
    parse_context: ParseContext,
) -> None:
    source = (
        b"<!doctype html><html><body>"
        b"<article>alpha <strong>beta</strong> omega<!--ignored--></article>"
        b"<article><p>second article</p></article>"
        b"</body></html>"
    )
    document = _parse(
        filename="articles.html",
        data=source,
        context=parse_context,
    )
    texts = [block.raw_text for block in document.blocks]
    assert texts == ["alpha", "beta", "omega", "second article"]
    assert len({block.id for block in document.blocks}) == len(document.blocks)
    locations = [block.source_refs[0].native_object_id for block in document.blocks]
    assert len(set(locations)) == len(locations)
    assert all("ignored" not in (text or "") for text in texts)


def test_subtitles_preserve_time_speaker_and_merge_repeated_cues(
    parse_context: ParseContext,
) -> None:
    srt = _parse(
        filename="captions.srt",
        data=(FIXTURES / "sample.srt").read_bytes(),
        context=parse_context,
    )
    assert srt.metadata["subtitles"]["sourceCueCount"] == 4
    assert srt.metadata["subtitles"]["canonicalCueCount"] == 3
    cue_blocks = [block for block in srt.blocks if block.type == BlockType.PARAGRAPH]
    assert len(cue_blocks) == 3
    assert cue_blocks[0].source_refs[0].time_start_ms == 1_000
    assert cue_blocks[0].source_refs[0].time_end_ms == 3_000
    assert "speaker_label_detected" in cue_blocks[0].quality_flags
    merged = next(block for block in cue_blocks if "repeated_cues_merged" in block.quality_flags)
    assert merged.source_refs[0].time_start_ms == 3_500
    assert merged.source_refs[0].time_end_ms == 6_500

    vtt = _parse(
        filename="captions.vtt",
        data=(FIXTURES / "sample.vtt").read_bytes(),
        context=parse_context,
    )
    assert vtt.metadata["subtitles"]["sourceCueCount"] == 2
    assert vtt.metadata["subtitles"]["skippedMetadataBlockCount"] == 2
    first_vtt_cue = next(block for block in vtt.blocks if block.type == BlockType.PARAGRAPH)
    assert first_vtt_cue.normalized_text == "첫 번째 관찰입니다."
    assert "speaker_label_detected" in first_vtt_cue.quality_flags


def test_deterministic_ids_order_and_wire_round_trip(
    parse_context: ParseContext,
    docx_bytes: bytes,
) -> None:
    first = _parse(
        filename="stable.docx",
        data=docx_bytes,
        context=parse_context,
    )
    second = _parse(
        filename="stable.docx",
        data=docx_bytes,
        context=parse_context,
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [block.order for block in first.blocks] == list(range(len(first.blocks)))
    wire = canonical_json(first)
    assert CanonicalDocument.model_validate_json(wire) == first


def test_all_real_minimal_samples_reach_canonical_cir(
    parse_context: ParseContext,
    docx_bytes: bytes,
    pptx_bytes: bytes,
    xlsx_bytes: bytes,
) -> None:
    sources = [
        ("sample.docx", docx_bytes),
        ("sample.pptx", pptx_bytes),
        ("sample.xlsx", xlsx_bytes),
        ("sample.html", (FIXTURES / "sample.html").read_bytes()),
        ("sample.srt", (FIXTURES / "sample.srt").read_bytes()),
        ("sample.vtt", (FIXTURES / "sample.vtt").read_bytes()),
        ("sample.csv", CSV_SOURCE.encode("utf-8")),
    ]
    for filename, payload in sources:
        document = _parse(
            filename=filename,
            data=payload,
            context=parse_context,
        )
        assert document.blocks
        assert all(block.source_refs for block in document.blocks)
        assert CanonicalDocument.model_validate_json(canonical_json(document)) == document


def test_fail_closed_mime_macro_external_relation_and_embedding(
    parse_context: ParseContext,
    docx_bytes: bytes,
) -> None:
    with pytest.raises(StructuredParseError, match="MIME_MISMATCH"):
        parse_non_pdf_to_cir(
            filename="sample.docx",
            declared_mime="application/pdf",
            data=docx_bytes,
            context=parse_context,
        )
    with pytest.raises(StructuredParseError, match="UNSUPPORTED_NON_PDF_TYPE"):
        parse_non_pdf_to_cir(
            filename="sample.docm",
            declared_mime="application/octet-stream",
            data=docx_bytes,
            context=parse_context,
        )

    external = _rewrite_zip(
        docx_bytes,
        transform={
            "word/_rels/document.xml.rels": lambda value: value.replace(
                b"</Relationships>",
                (
                    b'<Relationship Id="unsafe" '
                    b'Type="http://schemas.openxmlformats.org/officeDocument/'
                    b'2006/relationships/hyperlink" '
                    b'Target="https://example.invalid/" TargetMode="External"/>'
                    b"</Relationships>"
                ),
            )
        },
    )
    with pytest.raises(StructuredParseError, match="OFFICE_EXTERNAL_RELATION"):
        _parse(
            filename="external.docx",
            data=external,
            context=parse_context,
        )

    embedded = _rewrite_zip(
        docx_bytes,
        additions={"word/embeddings/object.bin": b"untrusted object"},
    )
    with pytest.raises(StructuredParseError, match="OFFICE_EMBEDDED_OBJECT"):
        _parse(
            filename="embedded.docx",
            data=embedded,
            context=parse_context,
        )

    macro_enabled = _rewrite_zip(
        docx_bytes,
        transform={
            "[Content_Types].xml": lambda value: value.replace(
                b"</Types>",
                (
                    b'<Override PartName="/word/macro.bin" '
                    b'ContentType="application/vnd.ms-office.'
                    b'vbaProjectMacroEnabled.main+xml"/></Types>'
                ),
            )
        },
    )
    with pytest.raises(StructuredParseError, match="OFFICE_ACTIVE_CONTENT"):
        _parse(
            filename="macro-disguised.docx",
            data=macro_enabled,
            context=parse_context,
        )


def test_format_specific_limits_fail_before_unbounded_work(
    parse_context: ParseContext,
    pptx_bytes: bytes,
    xlsx_bytes: bytes,
) -> None:
    with pytest.raises(StructuredParseError, match="SLIDE_LIMIT"):
        _parse(
            filename="deck.pptx",
            data=pptx_bytes,
            context=parse_context,
            limits=replace(ParserLimits(), max_slides=1),
        )
    with pytest.raises(StructuredParseError, match="SHEET_ROW_LIMIT"):
        _parse(
            filename="book.xlsx",
            data=xlsx_bytes,
            context=parse_context,
            limits=replace(ParserLimits(), max_rows_per_sheet=2),
        )
    with pytest.raises(StructuredParseError, match="SUBTITLE_CUE_LIMIT"):
        _parse(
            filename="captions.srt",
            data=(FIXTURES / "sample.srt").read_bytes(),
            context=parse_context,
            limits=replace(ParserLimits(), max_subtitle_cues=2),
        )
    with pytest.raises(StructuredParseError, match="HTML_NODE_LIMIT"):
        _parse(
            filename="article.html",
            data=(FIXTURES / "sample.html").read_bytes(),
            context=parse_context,
            limits=replace(ParserLimits(), max_html_nodes=5),
        )


def test_archive_size_ratio_magic_column_and_table_area_limits_fail_closed(
    parse_context: ParseContext,
    docx_bytes: bytes,
    xlsx_bytes: bytes,
) -> None:
    with pytest.raises(StructuredParseError, match="FILE_TOO_LARGE"):
        _parse(
            filename="sample.docx",
            data=docx_bytes,
            context=parse_context,
            limits=replace(ParserLimits(), max_input_bytes=len(docx_bytes) - 1),
        )
    with pytest.raises(StructuredParseError, match="ARCHIVE_ENTRY_LIMIT"):
        _parse(
            filename="sample.docx",
            data=docx_bytes,
            context=parse_context,
            limits=replace(ParserLimits(), max_archive_entries=1),
        )
    with pytest.raises(StructuredParseError, match="ARCHIVE_SIZE_LIMIT"):
        _parse(
            filename="sample.docx",
            data=docx_bytes,
            context=parse_context,
            limits=replace(ParserLimits(), max_archive_uncompressed_bytes=1_000),
        )
    with pytest.raises(StructuredParseError, match="ARCHIVE_RATIO_LIMIT"):
        _parse(
            filename="sample.docx",
            data=docx_bytes,
            context=parse_context,
            limits=replace(ParserLimits(), max_compression_ratio=1.01),
        )
    with pytest.raises(StructuredParseError, match="MAGIC_MISMATCH"):
        _parse(
            filename="fake.docx",
            data=b"<!doctype html><html><body>not office</body></html>",
            context=parse_context,
        )
    with pytest.raises(StructuredParseError, match="SHEET_COLUMN_LIMIT"):
        _parse(
            filename="wide.xlsx",
            data=xlsx_bytes,
            context=parse_context,
            limits=replace(ParserLimits(), max_columns_per_sheet=4),
        )
    with pytest.raises(StructuredParseError, match="TABLE_CELL_LIMIT"):
        _parse(
            filename="span.html",
            data=(
                b"<!doctype html><html><body><table><tr>"
                b'<td rowspan="100000" colspan="6">bounded</td>'
                b"</tr></table></body></html>"
            ),
            context=parse_context,
        )


def test_malformed_ooxml_is_reported_as_stable_parse_failure(
    parse_context: ParseContext,
    docx_bytes: bytes,
) -> None:
    malformed = _rewrite_zip(
        docx_bytes,
        transform={"word/document.xml": lambda _value: b"<not-valid-xml"},
    )
    with pytest.raises(StructuredParseError) as failure:
        _parse(
            filename="malformed.docx",
            data=malformed,
            context=parse_context,
        )
    assert failure.value.code == "DOCX_PARSE_FAILED"


def test_docx_table_and_pptx_slides_keep_source_order_without_omission(
    parse_context: ParseContext,
    docx_bytes: bytes,
    pptx_bytes: bytes,
) -> None:
    docx = _parse(filename="order.docx", data=docx_bytes, context=parse_context)
    table_block = next(block for block in docx.blocks if block.type == BlockType.TABLE)
    assert table_block.table is not None
    first_row = sorted(
        (cell for cell in table_block.table.cells if cell.row_index0 == 0),
        key=lambda cell: cell.column_index0,
    )
    assert [cell.raw_text for cell in first_row] == ["구성", "점수", "비고"]

    pptx = _parse(filename="order.pptx", data=pptx_bytes, context=parse_context)
    assert [slide["pageIndex0"] for slide in pptx.metadata["slides"]] == [0, 1]
    pages = [block.source_refs[0].page_index0 for block in pptx.blocks]
    assert pages == sorted(pages)
    texts = [block.raw_text for block in pptx.blocks]
    assert texts.index("두 번째 슬라이드") < texts.index("슬라이드 순서를 보존합니다.")


def test_xlsx_keeps_sheet_order_state_sparse_cells_types_and_number_formats(
    parse_context: ParseContext,
    rich_xlsx_bytes: bytes,
) -> None:
    document = _parse(filename="fidelity.xlsx", data=rich_xlsx_bytes, context=parse_context)

    sheets = document.metadata["sheets"]
    assert [(sheet["name"], sheet["state"]) for sheet in sheets] == [
        ("Summary", "visible"),
        ("Archive", "hidden"),
        ("Notes", "veryHidden"),
    ]
    headings = [block for block in document.blocks if block.type == BlockType.HEADING]
    assert [block.raw_text for block in headings] == ["Summary", "Archive", "Notes"]
    assert [block.source_refs[0].page_index0 for block in headings] == [0, 1, 2]
    assert ["hidden_sheet" in block.quality_flags for block in headings] == [False, True, True]

    summary = _sheet_table(document, 0)
    assert summary.row_count == 12
    assert summary.column_count == 5
    assert len(summary.cells) == 19
    assert summary.source_refs[0].native_object_id == "xlsx/sheet/0000/range/A1:E12"
    assert not any(cell.row_index0 == 9 and cell.column_index0 == 3 for cell in summary.cells)

    header = _cell(summary, "xlsx/sheet/0000/cell/A1")
    assert (header.raw_text, header.row_span, header.column_span) == ("분기 실적", 1, 3)
    assert header.value_type == "string"
    sparse = _cell(summary, "xlsx/sheet/0000/cell/E12")
    assert (sparse.row_index0, sparse.column_index0) == (11, 4)

    # Each value keeps its stored text; the format code is carried verbatim
    # beside it and never applied, so 0.25 is not rendered as "25.00%" and the
    # quoted " kg" literal is not split out as an inferred unit.
    expected = {
        "B3": ("12.5", "number", '#,##0.0" kg"'),
        "B4": ("1234567", "number", "#,##0"),
        "B5": ("0.25", "number", "0.00%"),
        "B6": ("2026-03-31T00:00:00", "datetime", "yyyy-mm-dd"),
        "B7": ("TRUE", "boolean", None),
        "A3": ("중량", "string", None),
    }
    for coordinate, (text, value_type, number_format) in expected.items():
        cell = _cell(summary, f"xlsx/sheet/0000/cell/{coordinate}")
        assert (cell.raw_text, cell.normalized_text) == (text, text), coordinate
        assert cell.value_type == value_type, coordinate
        assert cell.number_format == number_format, coordinate
        assert cell.formula is None, coordinate

    archive = _sheet_table(document, 1)
    assert archive.cells[0].source_refs[0].native_object_id == "xlsx/sheet/0001/cell/A1"


def test_xlsx_formula_text_is_kept_and_only_an_existing_cache_is_displayed(
    parse_context: ParseContext,
    rich_xlsx_bytes: bytes,
) -> None:
    document = _parse(filename="formulas.xlsx", data=rich_xlsx_bytes, context=parse_context)
    summary = _sheet_table(document, 0)

    cached = _cell(summary, "xlsx/sheet/0000/cell/B8")
    assert cached.formula == "=SUM(B3:B4)"
    assert cached.raw_text == "=SUM(B3:B4)"
    assert cached.normalized_text == "1234579.5"
    assert cached.value_type == "number"
    assert cached.number_format == "#,##0.0"
    assert "formula_preserved_not_executed" in cached.quality_flags
    assert "formula_cached_value_missing" not in cached.quality_flags

    uncached = _cell(summary, "xlsx/sheet/0000/cell/B9")
    assert uncached.formula == "=B3*2"
    # Nothing computes 12.5 * 2: without a cache the display text stays the
    # formula and the value type stays absent.
    assert uncached.normalized_text == "=B3*2"
    assert uncached.value_type is None
    assert "formula_cached_value_missing" in uncached.quality_flags
    assert "25" not in uncached.normalized_text

    formulas = {item["cell"]: item for item in document.metadata["sheets"][0]["formulas"]}
    assert formulas["B8"]["cachedValuePresent"] is True
    assert formulas["B8"]["cachedValue"] == "1234579.5"
    assert formulas["B9"]["cachedValuePresent"] is False
    assert formulas["B9"]["cachedValue"] is None
    assert "xlsx_formulas_not_executed" in document.metadata["warnings"]


def test_xlsx_cell_fidelity_and_anchors_survive_canonical_json_round_trip(
    parse_context: ParseContext,
    rich_xlsx_bytes: bytes,
) -> None:
    first = _parse(filename="stable.xlsx", data=rich_xlsx_bytes, context=parse_context)
    second = _parse(filename="stable.xlsx", data=rich_xlsx_bytes, context=parse_context)
    wire = canonical_json(first)
    assert wire == canonical_json(second)

    restored = CanonicalDocument.model_validate_json(wire)
    assert restored == first
    original_cells = {
        cell.source_refs[0].native_object_id: cell
        for block in first.blocks
        if block.table is not None
        for cell in block.table.cells
    }
    restored_cells = {
        cell.source_refs[0].native_object_id: cell
        for block in restored.blocks
        if block.table is not None
        for cell in block.table.cells
    }
    assert restored_cells == original_cells
    for anchor in ("xlsx/sheet/0000/cell/B3", "xlsx/sheet/0000/cell/B8"):
        assert restored_cells[anchor].id == original_cells[anchor].id
    assert restored_cells["xlsx/sheet/0000/cell/B3"].number_format == '#,##0.0" kg"'
    assert restored_cells["xlsx/sheet/0000/cell/B8"].formula == "=SUM(B3:B4)"

    payload = json.loads(wire)
    validator = _cell_schema_validator()
    wire_cells = [
        cell for block in payload["blocks"] if "table" in block for cell in block["table"]["cells"]
    ]
    assert wire_cells
    for cell in wire_cells:
        validator.validate(cell)
    b3 = next(
        cell
        for cell in wire_cells
        if cell["sourceRefs"][0]["nativeObjectId"] == "xlsx/sheet/0000/cell/B3"
    )
    assert (b3["valueType"], b3["numberFormat"]) == ("number", '#,##0.0" kg"')
    assert "formula" not in b3


def test_xlsx_array_formula_object_keeps_its_ooxml_text_and_cached_value_apart(
    parse_context: ParseContext,
) -> None:
    # Synthetic workbook: one single-cell array formula, which openpyxl reads
    # back as an ArrayFormula object rather than a string.
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Arrays"
    sheet.append(["a", "b", "sumproduct"])
    sheet.append([2, 3, None])
    sheet.append([4, 5, None])
    sheet["C2"] = ArrayFormula("C2", "=SUM(A2:A3*B2:B3)")
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()

    def add_array_formula_cache(value: bytes) -> bytes:
        # openpyxl never writes a cached result; inject the one Excel would
        # have stored so the display value and the formula can be told apart.
        rewritten, count = re.subn(
            rb'(<f [^>]*t="array"[^>]*>[^<]*</f>)<v\s*(?:/>|></v>)',
            rb"\1<v>26</v>",
            value,
        )
        assert count == 1
        return rewritten

    data = _rewrite_zip(
        output.getvalue(),
        transform={"xl/worksheets/sheet1.xml": add_array_formula_cache},
    )
    document = _parse(filename="arrays.xlsx", data=data, context=parse_context)
    table = _sheet_table(document, 0)

    cell = _cell(table, "xlsx/sheet/0000/cell/C2")
    assert cell.formula == "=SUM(A2:A3*B2:B3)"
    assert cell.raw_text == cell.formula
    # The cached result is display text only; nothing evaluated the formula.
    assert cell.normalized_text == "26"
    assert cell.value_type == "number"
    assert "formula_preserved_not_executed" in cell.quality_flags
    assert "formula_text_unavailable" not in cell.quality_flags
    assert "formula_cached_value_missing" not in cell.quality_flags
    assert document.metadata["sheets"][0]["formulas"] == [
        {
            "cell": "C2",
            "formula": "=SUM(A2:A3*B2:B3)",
            "cachedValue": "26",
            "cachedValuePresent": True,
        }
    ]

    wire = canonical_json(document)
    assert "ArrayFormula" not in wire
    assert " object at 0x" not in wire
    assert canonical_json(_parse(filename="arrays.xlsx", data=data, context=parse_context)) == wire
    restored = CanonicalDocument.model_validate_json(wire)
    assert restored == document
    validator = _cell_schema_validator()
    for wire_cell in (
        wire_cell
        for block in json.loads(wire)["blocks"]
        if "table" in block
        for wire_cell in block["table"]["cells"]
    ):
        validator.validate(wire_cell)


def test_xlsx_data_table_formula_without_text_is_flagged_and_never_stringified(
    parse_context: ParseContext,
) -> None:
    # A data-table formula carries no formula text at all. The cell keeps its
    # anchor, says the text is unavailable, and invents nothing in its place.
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Sensitivity"
    sheet["A1"], sheet["B1"] = "rate", 0.05
    sheet["B2"] = DataTableFormula(ref="B2", r1="B1")
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()

    document = _parse(filename="table.xlsx", data=output.getvalue(), context=parse_context)
    cell = _cell(_sheet_table(document, 0), "xlsx/sheet/0000/cell/B2")
    assert cell.formula is None
    assert (cell.raw_text, cell.normalized_text) == ("", "")
    assert cell.value_type is None
    assert {
        "formula_preserved_not_executed",
        "formula_text_unavailable",
        "formula_cached_value_missing",
    } <= set(cell.quality_flags)
    assert document.metadata["sheets"][0]["formulas"] == [
        {
            "cell": "B2",
            "formula": None,
            "cachedValue": None,
            "cachedValuePresent": False,
        }
    ]
    wire = canonical_json(document)
    assert "DataTableFormula" not in wire
    assert " object at 0x" not in wire


def test_canonical_cell_fidelity_fields_are_optional_and_verbatim() -> None:
    legacy: dict[str, Any] = {
        "id": "cell_legacy",
        "rowIndex0": 0,
        "columnIndex0": 0,
        "rowSpan": 1,
        "columnSpan": 1,
        "rawText": "x",
        "normalizedText": "x",
        "origin": "native_extracted",
        "sourceRefs": [
            {
                "documentId": "document_fixture",
                "documentVersionId": "version_fixture",
                "pageIndex0": 0,
                "pageNumber1": 1,
            }
        ],
        "qualityFlags": [],
    }
    validator = _cell_schema_validator()
    validator.validate(legacy)
    cell = CanonicalCell.model_validate(legacy)
    assert (cell.value_type, cell.number_format, cell.formula) == (None, None, None)
    assert cell.model_dump(mode="json", by_alias=True, exclude_none=True) == legacy

    # The contract strips surrounding whitespace from ordinary strings; source
    # format codes and formulas must survive byte-for-byte instead.
    extended = {
        **legacy,
        "valueType": "number",
        "numberFormat": ' 0.0" kg" ',
        "formula": "=A1 ",
    }
    validator.validate(extended)
    restored = CanonicalCell.model_validate_json(
        canonical_json(CanonicalCell.model_validate(extended))
    )
    assert restored.number_format == ' 0.0" kg" '
    assert restored.formula == "=A1 "

    for invalid in ({"valueType": "currency"}, {"numberFormat": ""}, {"formula": ""}):
        with pytest.raises(ValidationError):
            CanonicalCell.model_validate({**legacy, **invalid})


def test_cell_fidelity_nullability_agrees_across_python_static_schema_and_typescript() -> None:
    static_cell = json.loads(CANONICAL_DOCUMENT_SCHEMA.read_text(encoding="utf-8"))["$defs"]["cell"]
    model_cell = CanonicalDocument.model_json_schema(by_alias=True, mode="serialization")["$defs"][
        "CanonicalCell"
    ]

    # The static schema states exactly what the Python model accepts:
    # nullability, the value-type enum and the non-empty verbatim strings.
    for field in (*NULLABLE_CELL_FIELDS, "rawText"):
        generated = {
            key: value
            for key, value in model_cell["properties"][field].items()
            if key not in {"default", "title"}
        }
        assert static_cell["properties"][field] == generated, field
    for field in NULLABLE_CELL_FIELDS:
        assert field not in static_cell["required"], field
        assert field not in model_cell.get("required", []), field

    # The checked-in TypeScript (kept current by test_contract_examples)
    # renders the same optional, nullable members.
    lines = GENERATED_CONTRACTS.read_text(encoding="utf-8").splitlines()
    start = lines.index("export namespace CanonicalDocumentContract {")
    cell_type = next(
        line for line in lines[start:] if line.startswith("  export type CanonicalCell = ")
    )
    for field in NULLABLE_CELL_FIELDS:
        members: list[str] = []
        for variant in static_cell["properties"][field]["anyOf"]:
            if "enum" in variant:
                members.extend(json.dumps(item) for item in variant["enum"])
            else:
                members.append(variant["type"])
        assert members[-1] == "null", field
        assert f"readonly {field}?: {' | '.join(members)};" in cell_type, field

    # Python serialization, with the fields both null and populated, is
    # accepted by the static schema and restores the same cell.
    validator = _cell_schema_validator()
    base: dict[str, Any] = {
        "id": "cell_nullability",
        "rowIndex0": 0,
        "columnIndex0": 0,
        "rawText": "x",
        "normalizedText": "x",
        "origin": "native_extracted",
        "sourceRefs": [
            {
                "documentId": "document_fixture",
                "documentVersionId": "version_fixture",
                "pageIndex0": 0,
                "pageNumber1": 1,
            }
        ],
    }
    cases: list[tuple[dict[str, Any], tuple[str | None, ...]]] = [
        ({}, (None, None, None)),
        (dict.fromkeys(NULLABLE_CELL_FIELDS), (None, None, None)),
        (
            {"valueType": "number", "numberFormat": "0.00%", "formula": "=A1*2"},
            ("number", "0.00%", "=A1*2"),
        ),
    ]
    for overrides, expected in cases:
        cell = CanonicalCell.model_validate({**base, **overrides})
        dumped = cell.model_dump(mode="json", by_alias=True)
        assert tuple(dumped[field] for field in NULLABLE_CELL_FIELDS) == expected
        # Only the three fidelity fields stay explicitly null on the wire;
        # unrelated optional nulls, including nested source refs, are omitted.
        wire = {
            key: value
            for key, value in dumped.items()
            if value is not None or key in NULLABLE_CELL_FIELDS
        }
        wire["sourceRefs"] = [
            ref.model_dump(mode="json", by_alias=True, exclude_none=True)
            for ref in cell.source_refs
        ]
        assert tuple(wire[field] for field in NULLABLE_CELL_FIELDS) == expected
        validator.validate(wire)
        assert CanonicalCell.model_validate_json(json.dumps(wire)) == cell

    # Both sides reject the same malformed values.
    for invalid in (
        {"valueType": "currency"},
        {"valueType": ""},
        {"numberFormat": ""},
        {"formula": ""},
        {"formula": 1},
    ):
        payload = {**base, "rowSpan": 1, "columnSpan": 1, "qualityFlags": [], **invalid}
        assert not validator.is_valid(payload), invalid
        with pytest.raises(ValidationError):
            CanonicalCell.model_validate(payload)


def test_csv_preserves_records_anchors_and_never_evaluates_formula_text(
    parse_context: ParseContext,
) -> None:
    source = CSV_SOURCE.encode("utf-8-sig")
    document = _parse(filename="ledger.csv", data=source, context=parse_context)

    assert document.metadata["documentType"] == "csv"
    assert document.metadata["sourceLocationScheme"].startswith("csv/")
    assert document.metadata["csv"]["dialect"]["delimiter"] == ","
    assert document.metadata["csv"]["recordCount"] == 6
    assert document.metadata["csv"]["recordWidths"] == [3, 4]
    assert "csv_formula_prefixed_text_not_executed" in document.metadata["warnings"]
    assert [block.type for block in document.blocks] == [BlockType.TABLE]
    table = document.blocks[0].table
    assert table is not None
    assert (table.row_count, table.column_count, table.header_row_count) == (6, 4, 0)
    assert table.source_refs[0].native_object_id == "csv/table/range/A1:D6"
    assert {"csv_header_not_declared", "csv_ragged_records"} <= set(table.quality_flags)

    def at(coordinate: str, record_index0: int) -> CanonicalCell:
        return _cell(table, f"csv/row/{record_index0:06d}/cell/{coordinate}")

    assert at("A1", 0).raw_text == "name"
    assert at("A2", 1).raw_text == "Kim, J."
    assert at("C2", 1).raw_text == "multi\nline"
    formula_like = at("B2", 1)
    assert (formula_like.raw_text, formula_like.normalized_text) == ("=1+2", "=1+2")
    assert "spreadsheet_formula_prefix_preserved_as_text" in formula_like.quality_flags
    assert at("C4", 3).raw_text == "@SUM(A1)"
    assert at("D6", 5).raw_text == "extra"
    padded = at("B5", 4)
    assert "csv_field_whitespace_normalized" in padded.quality_flags
    assert not any(cell.row_index0 == 2 for cell in table.cells)
    assert not any(cell.row_index0 == 4 and cell.column_index0 == 2 for cell in table.cells)
    assert all(cell.value_type == "string" for cell in table.cells)
    assert all(cell.number_format is None and cell.formula is None for cell in table.cells)
    joined = "\n".join(cell.normalized_text for cell in table.cells)
    assert "\n3\n" not in f"\n{joined}\n"

    again = _parse(filename="ledger.csv", data=source, context=parse_context)
    assert canonical_json(again) == canonical_json(document)
    restored = CanonicalDocument.model_validate_json(canonical_json(document))
    assert restored == document
    restored_table = restored.blocks[0].table
    assert restored_table is not None
    assert [cell.id for cell in restored_table.cells] == [cell.id for cell in table.cells]


def test_csv_fails_closed_on_limits_encoding_binary_and_malformed_quotes(
    parse_context: ParseContext,
) -> None:
    source = CSV_SOURCE.encode("utf-8")
    cases: list[tuple[ParserLimits, str]] = [
        (replace(ParserLimits(), max_csv_rows=5), "CSV_ROW_LIMIT"),
        (replace(ParserLimits(), max_csv_columns=3), "CSV_COLUMN_LIMIT"),
        (replace(ParserLimits(), max_csv_cells=4), "CSV_CELL_LIMIT"),
        (replace(ParserLimits(), max_csv_field_chars=4), "CSV_FIELD_LIMIT"),
    ]
    for limits, code in cases:
        with pytest.raises(StructuredParseError) as failure:
            _parse(filename="ledger.csv", data=source, context=parse_context, limits=limits)
        assert failure.value.code == code

    rejected: list[tuple[bytes, str]] = [
        (b'a,"never closed\n', "CSV_MALFORMED"),
        (b'"ab"c,d\n', "CSV_MALFORMED"),
        (b"a,\x00b\n", "BINARY_TEXT_FILE"),
        (b"a,\xff\xfe\n", "FILE_SIGNATURE_MISMATCH"),
        (b",,\r\n\r\n", "CSV_EMPTY_DOCUMENT"),
    ]
    for payload, code in rejected:
        with pytest.raises(StructuredParseError) as failure:
            _parse(filename="broken.csv", data=payload, context=parse_context)
        assert failure.value.code == code

    with pytest.raises(StructuredParseError, match="MIME_MISMATCH"):
        parse_non_pdf_to_cir(
            filename="ledger.csv",
            declared_mime="application/vnd.ms-excel",
            data=source,
            context=parse_context,
        )


def test_csv_trailing_empty_fields_keep_their_columns_without_cells(
    parse_context: ParseContext,
) -> None:
    document = _parse(
        filename="trailing.csv",
        data=b"a,b,,\r\nc,d,,\r\n",
        context=parse_context,
    )

    table = document.blocks[0].table
    assert table is not None
    assert (table.row_count, table.column_count) == (2, 4)
    assert table.source_refs[0].native_object_id == "csv/table/range/A1:D2"
    assert document.metadata["csv"]["columnCount"] == 4
    assert document.metadata["csv"]["range"] == "A1:D2"
    assert document.metadata["csv"]["recordWidths"] == [4]
    assert "csv_ragged_records" not in table.quality_flags
    # The empty trailing fields widen the grid but are never emitted as cells.
    assert document.metadata["csv"]["cellCount"] == 4
    assert sorted((cell.row_index0, cell.column_index0) for cell in table.cells) == [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    ]


def test_csv_cell_limit_counts_empty_fields(parse_context: ParseContext) -> None:
    # One non-empty field and three empty ones: four parsed fields.
    one_value = b"a,,,\r\n"
    accepted = _parse(
        filename="sparse.csv",
        data=one_value,
        context=parse_context,
        limits=replace(ParserLimits(), max_csv_cells=4),
    )
    table = accepted.blocks[0].table
    assert table is not None
    assert table.column_count == 4
    assert [cell.raw_text for cell in table.cells] == ["a"]

    # The single emitted cell is well under the bound; the empty fields
    # alone carry the parsed field count past it.
    with pytest.raises(StructuredParseError) as failure:
        _parse(
            filename="sparse.csv",
            data=one_value,
            context=parse_context,
            limits=replace(ParserLimits(), max_csv_cells=2),
        )
    assert failure.value.code == "CSV_CELL_LIMIT"

    # A record of nothing but empty fields hits the bound before the
    # empty-document check is ever reached.
    with pytest.raises(StructuredParseError) as failure:
        _parse(
            filename="blank.csv",
            data=b",,,,\r\n",
            context=parse_context,
            limits=replace(ParserLimits(), max_csv_cells=3),
        )
    assert failure.value.code == "CSV_CELL_LIMIT"


def test_csv_raw_text_is_the_exact_field_and_only_normalized_text_is_normalized(
    parse_context: ParseContext,
) -> None:
    # Synthetic CSV: padded fields, an embedded CRLF and an embedded LF, a
    # decomposed "e" + COMBINING ACUTE ACCENT, tabs, and a field that ends in
    # a quoted CRLF.
    decomposed = "Café"
    text = (
        '  lead,trail  ,"  both  "\r\n'
        f'"line one\r\nline two","lf\nonly",{decomposed}\r\n'
        '"\t tab \t",plain,"trailing line\r\n"\r\n'
    )
    data = text.encode("utf-8")
    document = _parse(filename="verbatim.csv", data=data, context=parse_context)
    table = document.blocks[0].table
    assert table is not None

    def at(coordinate: str, record_index0: int) -> CanonicalCell:
        return _cell(table, f"csv/row/{record_index0:06d}/cell/{coordinate}")

    expected = {
        ("A1", 0): ("  lead", "lead"),
        ("B1", 0): ("trail  ", "trail"),
        ("C1", 0): ("  both  ", "both"),
        ("A2", 1): ("line one\r\nline two", "line one\nline two"),
        ("B2", 1): ("lf\nonly", "lf\nonly"),
        ("C2", 1): ("Café", "Café"),
        ("A3", 2): ("\t tab \t", "tab"),
        ("B3", 2): ("plain", "plain"),
        ("C3", 2): ("trailing line\r\n", "trailing line"),
    }
    for (coordinate, record_index0), (raw, normalized) in expected.items():
        cell = at(coordinate, record_index0)
        assert (cell.raw_text, cell.normalized_text) == (raw, normalized), coordinate
        flagged = "csv_field_whitespace_normalized" in cell.quality_flags
        assert flagged is (raw != normalized), coordinate

    # No source value is lost: every non-empty field the stdlib reader yields
    # is a cell whose raw text is that field, character for character.
    records = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    fields = {
        f"csv/row/{row:06d}/cell/{chr(ord('A') + column)}{row + 1}": field
        for row, record in enumerate(records)
        for column, field in enumerate(record)
        if field
    }
    assert {cell.source_refs[0].native_object_id: cell.raw_text for cell in table.cells} == fields
    assert all(cell.normalized_text == normalize_text(cell.raw_text) for cell in table.cells)
    # Derived block text is built from normalized text only.
    block = document.blocks[0]
    assert block.normalized_text is not None
    assert "\r" not in block.normalized_text
    assert "Café" in block.normalized_text

    # IDs and anchors are deterministic, and the verbatim text survives the
    # wire round trip and the static schema.
    again = _parse(filename="verbatim.csv", data=data, context=parse_context)
    wire = canonical_json(document)
    assert canonical_json(again) == wire
    again_table = again.blocks[0].table
    assert again_table is not None
    assert [cell.id for cell in again_table.cells] == [cell.id for cell in table.cells]
    restored = CanonicalDocument.model_validate_json(wire)
    assert restored == document
    restored_table = restored.blocks[0].table
    assert restored_table is not None
    assert [
        (cell.id, cell.source_refs[0].native_object_id, cell.raw_text)
        for cell in restored_table.cells
    ] == [(cell.id, cell.source_refs[0].native_object_id, cell.raw_text) for cell in table.cells]
    validator = _cell_schema_validator()
    for wire_cell in json.loads(wire)["blocks"][0]["table"]["cells"]:
        validator.validate(wire_cell)


@pytest.mark.parametrize("text", CSV_BOUNDARY_SOURCES)
def test_csv_preflight_counts_the_same_records_and_fields_as_the_strict_reader(
    text: str,
) -> None:
    expected = _reader_shape(text)
    limits = ParserLimits()
    # One chunk, as parse_csv passes the text; then chunkings that split
    # CRLFs and doubled quotes. Single characters split every one of them.
    assert preflight_csv((text,), limits) == expected
    for size in (1, 2, 3):
        chunks = [text[start : start + size] for start in range(0, len(text), size)]
        assert preflight_csv(chunks, limits) == expected, size


def test_csv_preflight_stops_at_a_syntax_error_and_leaves_the_verdict_to_the_reader(
    parse_context: ParseContext,
) -> None:
    # A character after a closing quote, a quote never closed, and a space
    # after a closing quote in a later record.
    for text in ('"ab"c,d\n', 'a,"never closed\n', 'ok\r\n"x" ,y\r\n'):
        assert preflight_csv((text,), ParserLimits()).stopped_at_syntax_error, text
        with pytest.raises(csv.Error):
            list(csv.reader(io.StringIO(text, newline=""), strict=True))
        with pytest.raises(StructuredParseError) as failure:
            _parse(filename="broken.csv", data=text.encode("utf-8"), context=parse_context)
        assert failure.value.code == "CSV_MALFORMED", text


def test_csv_preflight_accepts_text_at_each_bound_and_refuses_one_past_it() -> None:
    # (limits, at the bound, one past the bound, code). Blank records count
    # as records, empty fields as fields, a doubled quote as one character
    # and a quoted CRLF as two.
    cases: list[tuple[ParserLimits, str, str, str]] = [
        (replace(ParserLimits(), max_csv_rows=2), "a\r\n\r\n", "a\r\n\r\n\r\n", "CSV_ROW_LIMIT"),
        (
            replace(ParserLimits(), max_csv_columns=3),
            'a,"b,c",\r\n',
            'a,"b,c",,\r\n',
            "CSV_COLUMN_LIMIT",
        ),
        (
            replace(ParserLimits(), max_csv_cells=4),
            "a,b\r\n,\r\n",
            "a,b\r\n,,\r\n",
            "CSV_CELL_LIMIT",
        ),
        (replace(ParserLimits(), max_csv_field_chars=3), '"a""b"', '"a""bc"', "CSV_FIELD_LIMIT"),
        (replace(ParserLimits(), max_csv_field_chars=3), '"\r\nx"', '"\r\nxy"', "CSV_FIELD_LIMIT"),
    ]
    for limits, at_bound, past_bound, code in cases:
        assert preflight_csv((at_bound,), limits) == _reader_shape(at_bound), at_bound
        with pytest.raises(StructuredParseError) as failure:
            preflight_csv((past_bound,), limits)
        assert failure.value.code == code, past_bound


def test_csv_preflight_refuses_a_delimiter_flood_after_reading_only_the_column_bound() -> None:
    limits = replace(ParserLimits(), max_csv_columns=16)
    consumed = 0

    def one_row_of_delimiters() -> Iterator[str]:
        # A single record of 10**12 delimiters, produced lazily: neither the
        # text nor any record of it is ever materialized.
        nonlocal consumed
        for _ in range(10**12):
            consumed += 1
            yield ","

    with pytest.raises(StructuredParseError) as failure:
        preflight_csv(one_row_of_delimiters(), limits)
    assert failure.value.code == "CSV_COLUMN_LIMIT"
    # The refusal comes at the delimiter that opens one field too many. Each
    # character here is one ASCII byte, so this bounds the bytes read too.
    assert 0 < consumed <= limits.max_csv_columns


def test_csv_preflight_refuses_an_oversized_quoted_field_without_reading_past_the_bound() -> None:
    limits = replace(ParserLimits(), max_csv_field_chars=64)
    consumed = 0

    def one_quoted_field(unit: str) -> Iterator[str]:
        # An opening quote, then field text that never ends, one character
        # at a time so every doubled quote is split across two chunks.
        nonlocal consumed
        consumed += 1
        yield '"'
        for _ in range(10**12):
            for char in unit:
                consumed += 1
                yield char

    with pytest.raises(StructuredParseError) as failure:
        preflight_csv(one_quoted_field("x"), limits)
    assert failure.value.code == "CSV_FIELD_LIMIT"
    # The opening quote plus one character more than a field may hold.
    assert 0 < consumed <= limits.max_csv_field_chars + 2

    # Doubled quotes are one field character for two source characters.
    consumed = 0
    with pytest.raises(StructuredParseError) as failure:
        preflight_csv(one_quoted_field('""'), limits)
    assert failure.value.code == "CSV_FIELD_LIMIT"
    assert 0 < consumed <= 2 * (limits.max_csv_field_chars + 1) + 1


def test_parse_csv_runs_the_preflight_before_the_reader_is_built(
    parse_context: ParseContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original_preflight = csv_parser.preflight_csv
    original_reader = csv.reader

    def recording_preflight(chunks: Iterable[str], limits: ParserLimits) -> CsvPreflight:
        calls.append("preflight")
        return original_preflight(chunks, limits)

    def recording_reader(*args: Any, **kwargs: Any) -> Any:
        calls.append("reader")
        return original_reader(*args, **kwargs)

    monkeypatch.setattr(csv_parser, "preflight_csv", recording_preflight)
    monkeypatch.setattr(csv, "reader", recording_reader)

    _parse(filename="ledger.csv", data=CSV_SOURCE.encode("utf-8"), context=parse_context)
    assert calls == ["preflight", "reader"]

    # Under the default bounds: one record of four million delimiters, and one
    # quoted field a character longer than a field may hold. Both are refused
    # by the preflight; the reader that would build them is never created.
    oversized: list[tuple[bytes, str]] = [
        (b"," * 4_000_000 + b"\r\n", "CSV_COLUMN_LIMIT"),
        (b'"' + b"x" * (ParserLimits().max_csv_field_chars + 1) + b'"\r\n', "CSV_FIELD_LIMIT"),
    ]
    for payload, code in oversized:
        calls.clear()
        with pytest.raises(StructuredParseError) as failure:
            _parse(filename="flood.csv", data=payload, context=parse_context)
        assert failure.value.code == code
        assert calls == ["preflight"]


def test_hwp_and_hwpx_remain_unsupported(
    parse_context: ParseContext,
    docx_bytes: bytes,
) -> None:
    assert "csv" in SUPPORTED_EXTENSIONS
    assert not {"hwp", "hwpx"} & SUPPORTED_EXTENSIONS
    sources = [
        ("report.hwp", "application/x-hwp", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504),
        ("report.hwpx", "application/hwp+zip", docx_bytes),
    ]
    for filename, declared_mime, payload in sources:
        with pytest.raises(StructuredParseError) as failure:
            parse_non_pdf_to_cir(
                filename=filename,
                declared_mime=declared_mime,
                data=payload,
                context=parse_context,
            )
        assert failure.value.code == "UNSUPPORTED_NON_PDF_TYPE"


def test_cfb_containers_are_unsupported_and_never_classified_by_content(
    parse_context: ParseContext,
) -> None:
    # The parser does not walk the compound file directory, so it cannot
    # tell an encrypted OOXML package from a legacy binary workbook or an HWP
    # file. A stream name appearing anywhere in the bytes proves nothing.
    cfb_header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 120
    payloads = {
        "encrypted_package_name": cfb_header
        + "EncryptedPackage".encode("utf-16-le")
        + b"\x00" * 64,
        "legacy_xls_workbook_name": cfb_header + "Workbook".encode("utf-16-le") + b"\x00" * 64,
        "hwp_file_header_name": cfb_header + "FileHeader".encode("utf-16-le") + b"\x00" * 64,
        "bare_header": cfb_header,
    }
    for filename in ("workbook.xlsx", "document.docx", "deck.pptx"):
        for label, payload in payloads.items():
            with pytest.raises(StructuredParseError) as failure:
                _parse(filename=filename, data=payload, context=parse_context)
            code = failure.value.code
            assert code == "OFFICE_CFB_CONTAINER_UNSUPPORTED", (filename, label)
            # No claim of encryption, and no claim of a decrypted or parsed body.
            assert "ENCRYPT" not in code, (filename, label)

    # Legacy binary XLS is not an accepted type at all; it is never parsed.
    assert "xls" not in SUPPORTED_EXTENSIONS
    with pytest.raises(StructuredParseError) as failure:
        parse_non_pdf_to_cir(
            filename="legacy.xls",
            declared_mime="application/vnd.ms-excel",
            data=payloads["legacy_xls_workbook_name"],
            context=parse_context,
        )
    assert failure.value.code == "UNSUPPORTED_NON_PDF_TYPE"


def test_encrypted_corrupt_macro_and_external_link_workbooks_fail_closed(
    parse_context: ParseContext,
    xlsx_bytes: bytes,
) -> None:
    rejected: list[tuple[bytes, str]] = [
        (_flag_first_zip_entry_encrypted(xlsx_bytes), "ARCHIVE_ENCRYPTED_ENTRY"),
        (xlsx_bytes[: len(xlsx_bytes) // 2], "INVALID_OFFICE_ARCHIVE"),
        (
            _rewrite_zip(
                xlsx_bytes,
                additions={"xl/externalLinks/externalLink1.xml": b"<externalLink/>"},
            ),
            "OFFICE_EMBEDDED_OBJECT",
        ),
        (
            _rewrite_zip(
                xlsx_bytes,
                transform={
                    "xl/_rels/workbook.xml.rels": lambda value: value.replace(
                        b"</Relationships>",
                        (
                            b'<Relationship Id="rIdExternal" '
                            b'Type="http://schemas.openxmlformats.org/officeDocument/'
                            b'2006/relationships/externalLink" '
                            b'Target="https://example.invalid/book.xlsx" '
                            b'TargetMode="External"/></Relationships>'
                        ),
                    )
                },
            ),
            "OFFICE_EXTERNAL_RELATION",
        ),
        (
            _rewrite_zip(xlsx_bytes, additions={"xl/vbaProject.bin": b"not a macro"}),
            "OFFICE_ACTIVE_CONTENT",
        ),
    ]
    for payload, code in rejected:
        with pytest.raises(StructuredParseError) as failure:
            _parse(filename="workbook.xlsx", data=payload, context=parse_context)
        assert failure.value.code == code, code


def _sheet_table(document: CanonicalDocument, sheet_index0: int) -> CanonicalTable:
    for block in document.blocks:
        if block.table is not None and block.source_refs[0].page_index0 == sheet_index0:
            return block.table
    raise AssertionError(f"no table for sheet {sheet_index0}")


def _cell(table: CanonicalTable, native_object_id: str) -> CanonicalCell:
    matches = [
        cell for cell in table.cells if cell.source_refs[0].native_object_id == native_object_id
    ]
    assert len(matches) == 1, native_object_id
    return matches[0]


def _cell_schema_validator() -> Draft202012Validator:
    schema = json.loads(CANONICAL_DOCUMENT_SCHEMA.read_text(encoding="utf-8"))
    return Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": "#/$defs/cell",
        }
    )


def _reader_shape(text: str) -> CsvPreflight:
    """The counts the preflight must reach, taken from what csv.reader yields."""

    records = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    return CsvPreflight(
        record_count=len(records),
        field_count=sum(len(record) for record in records),
        widest_record=max((len(record) for record in records), default=0),
        longest_field=max((len(field) for record in records for field in record), default=0),
        stopped_at_syntax_error=False,
    )


def _flag_first_zip_entry_encrypted(source: bytes) -> bytes:
    """Set the encryption bit on the first central-directory record only."""

    payload = bytearray(source)
    end_of_directory = payload.rfind(b"PK\x05\x06")
    assert end_of_directory >= 0
    (directory_offset,) = struct.unpack_from("<I", payload, end_of_directory + 16)
    assert payload[directory_offset : directory_offset + 4] == b"PK\x01\x02"
    (flags,) = struct.unpack_from("<H", payload, directory_offset + 8)
    struct.pack_into("<H", payload, directory_offset + 8, flags | 0x1)
    return bytes(payload)


def _rewrite_zip(
    source: bytes,
    *,
    transform: dict[str, Callable[[bytes], bytes]] | None = None,
    additions: dict[str, bytes] | None = None,
) -> bytes:
    transforms = transform or {}
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(source)) as archive,
        zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as rewritten,
    ):
        for entry in archive.infolist():
            payload = archive.read(entry)
            callback = transforms.get(entry.filename)
            if callback is not None:
                payload = callback(payload)
            rewritten.writestr(entry, payload)
        for name, payload in (additions or {}).items():
            rewritten.writestr(name, payload)
    return output.getvalue()
