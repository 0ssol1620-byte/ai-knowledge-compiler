from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_native_parsers import ParseContext, StructuredParseError, parse_non_pdf_to_cir
from akc_native_parsers.span_ledger import SpanLedger, build_ledger
from akc_quality.numeric import extract_numeric_tokens
from docx import Document as WordDocument
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures" / "nonpdf"
MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
}


def _parse(ext: str, data: bytes):  # type: ignore[no-untyped-def]
    return parse_non_pdf_to_cir(
        filename=f"s.{ext}",
        declared_mime=MIME[ext],
        data=data,
        context=ParseContext(
            tenant_id="tenant_fixture",
            document_id="document_fixture",
            document_version_id="version_fixture",
            created_at=datetime(2026, 7, 29, tzinfo=UTC),
        ),
    )


def _ledger(ext: str, data: bytes) -> tuple[SpanLedger, object]:
    document = _parse(ext, data)
    return build_ledger(data, document), document


def _docx() -> bytes:
    word = WordDocument()
    word.add_heading("Quarterly report", level=1)
    word.add_paragraph("Revenue was -1,234.50 KRW, up 3.5% on 2026-03-31.")
    table = word.add_table(rows=2, cols=2)
    for r, row in enumerate((("Item", "Value"), ("Margin", "42.5%"))):
        for c, text in enumerate(row):
            table.cell(r, c).text = text
    buf = io.BytesIO()
    word.save(buf)
    return buf.getvalue()


def _clean(ledger: SpanLedger) -> None:
    assert ledger.resolved_mismatch == ()
    assert ledger.unresolvable == ()
    assert ledger.numeric_tokens_roundtripped == ledger.numeric_tokens_total


def test_docx_paragraph_and_table_cell_locators_resolve_exactly() -> None:
    ledger, document = _ledger("docx", _docx())
    _clean(ledger)
    assert ledger.document_type == "docx"
    assert ledger.locator_page_semantics == "container_ordinal"
    assert ledger.source_hash_matches
    assert ledger.table_blocks_derived == 1
    # 2 text blocks + 4 cells, all exact
    assert ledger.resolved_exact == 6
    assert ledger.blocks_with_locator == ledger.blocks_total == len(document.blocks)  # type: ignore[attr-defined]
    assert (ledger.units_expected, ledger.units_observed, ledger.units_missing) == (1, 1, ())


def test_xlsx_cell_locator_resolves_raw_and_formula_text() -> None:
    book = Workbook()
    sheet = book.active
    sheet["A1"] = "Total"
    sheet["B1"] = 1234.5
    sheet["A2"] = "Sum"
    sheet["B2"] = "=B1*2"
    buf = io.BytesIO()
    book.save(buf)
    ledger, _ = _ledger("xlsx", buf.getvalue())
    _clean(ledger)
    assert ledger.resolved_exact == 5  # sheet heading + 4 cells; formula kept as raw text
    assert (ledger.units_expected, ledger.units_observed) == (1, 1)


def test_pptx_shape_and_notes_resolve() -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "Plan 2026"
    box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
    box.text_frame.text = "Cost fell 12.5% to $1,200"
    slide.notes_slide.notes_text_frame.text = "Speaker note: 7 items"
    buf = io.BytesIO()
    deck.save(buf)
    ledger, _ = _ledger("pptx", buf.getvalue())
    _clean(ledger)
    assert ledger.resolved_exact == 3
    assert (ledger.units_expected, ledger.units_observed) == (1, 1)


def test_html_text_node_path_resolves() -> None:
    ledger, _ = _ledger("html", (FIXTURES / "sample.html").read_bytes())
    assert ledger.resolved_mismatch == ()
    # only the figure and its alt label are non-text objects
    assert {reason for _, reason in ledger.unresolvable} == {"non_text_object"}
    assert ledger.resolved_exact >= 8
    ledger, _ = _ledger("html", b"<html><body><p>one <b>2</b></p>tail 3</body></html>")
    assert ledger.resolved_mismatch == ()


def test_subtitle_time_range_resolves() -> None:
    for ext in ("srt", "vtt"):
        ledger, _ = _ledger(ext, (FIXTURES / f"sample.{ext}").read_bytes())
        assert ledger.resolved_mismatch == ()
        # document title and segment heading are parser-generated, never source text
        assert {reason for _, reason in ledger.unresolvable} == {"parser_generated_text"}
        assert ledger.units_missing == () and ledger.units_observed == ledger.units_expected
        assert ledger.resolved_exact >= 2


def test_numeric_tokens_roundtrip_with_units_and_signs() -> None:
    assert extract_numeric_tokens("-1,234.50 KRW and 3.5%") == ("-1,234.50", "3.5%")
    ledger, _ = _ledger("docx", _docx())
    assert ledger.numeric_tokens_total == 4
    assert ledger.numeric_tokens_roundtripped == ledger.numeric_tokens_total


def test_tampered_original_is_reported_as_mismatch_not_passed() -> None:
    data = _docx()
    document = _parse("docx", data)
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "word/document.xml":
                assert b"-1,234.50" in payload
                payload = payload.replace(b"-1,234.50", b"-1,284.50")
            target.writestr(item, payload)
    ledger = build_ledger(out.getvalue(), document)
    paragraph = next(b for b in document.blocks if "1,234.50" in (b.raw_text or ""))
    assert paragraph.id in ledger.resolved_mismatch
    assert not ledger.source_hash_matches
    assert ledger.numeric_tokens_roundtripped < ledger.numeric_tokens_total


def test_missing_slide_is_counted_missing() -> None:
    deck = Presentation()
    for title in ("One", "Two"):
        deck.slides.add_slide(deck.slide_layouts[5]).shapes.title.text = title
    buf = io.BytesIO()
    deck.save(buf)
    data = buf.getvalue()
    document = _parse("pptx", data)
    trimmed = document.model_copy(
        update={"blocks": tuple(b for b in document.blocks if b.source_refs[0].page_index0 != 1)}
    )
    ledger = build_ledger(data, trimmed)
    assert ledger.units_expected == 2 and ledger.units_observed == 1
    assert ledger.units_missing == (1,)


def test_unknown_locator_grammar_is_unresolvable_with_reason() -> None:
    data = _docx()
    document = _parse("docx", data)
    block = document.blocks[0]
    ref = block.source_refs[0].model_copy(update={"native_object_id": "docx/odd/locator"})
    odd = document.model_copy(
        update={"blocks": (block.model_copy(update={"source_refs": (ref,)}), *document.blocks[1:])}
    )
    ledger = build_ledger(data, odd)
    assert (block.id, "unknown_locator_grammar") in ledger.unresolvable
    assert block.id not in ledger.resolved_mismatch


def test_unreadable_original_and_unsupported_type_fail_closed() -> None:
    data = _docx()
    document = _parse("docx", data)
    ledger = build_ledger(b"not a zip", document)
    assert ledger.resolved_exact == 0 and ledger.unresolvable
    assert {reason for _, reason in ledger.unresolvable} == {"original_unreadable"}
    pdf_like = document.model_copy(
        update={"metadata": {**document.metadata, "documentType": "pdf"}}
    )
    with pytest.raises(StructuredParseError) as raised:
        build_ledger(data, pdf_like)
    assert raised.value.code == "LEDGER_TYPE_UNSUPPORTED"


def _srt(middle: str) -> bytes:
    cues = ("Hello 5", middle, "Hello 5")
    return "\n\n".join(
        f"{i + 1}\n00:00:0{i + 1},000 --> 00:00:0{i + 1},900\n{t}" for i, t in enumerate(cues)
    ).encode()


def test_srt_merged_range_with_tampered_middle_cue_is_mismatch() -> None:
    data = _srt("Hello 5")
    document = _parse("srt", data)
    merged = [
        b for b in document.blocks if b.source_refs and "-" in b.source_refs[0].native_object_id
    ]
    assert merged, "parser should merge the three identical cues"
    assert build_ledger(data, document).resolved_mismatch == ()
    ledger = build_ledger(_srt("Hello 6"), document)
    assert merged[0].id in ledger.resolved_mismatch
    assert not ledger.source_hash_matches


def test_html_zero_index_and_navigation_nodes_follow_the_parser() -> None:
    data = b"<html><body><p>one 1</p><p>two 2</p></body></html>"
    document = _parse("html", data)
    block = next(b for b in document.blocks if (b.raw_text or "").startswith("one"))
    ref = block.source_refs[0]
    zero = ref.native_object_id.replace("p[1]", "p[0]")
    assert zero != ref.native_object_id
    bad = document.model_copy(
        update={
            "blocks": (
                block.model_copy(
                    update={"source_refs": (ref.model_copy(update={"native_object_id": zero}),)}
                ),
            )
        }
    )
    assert (block.id, "path_not_found") in build_ledger(data, bad).unresolvable
    nav = b"<html><body><div role=navigation>menu</div><div>body 7</div></body></html>"
    ledger, _ = _ledger("html", nav)
    assert ledger.resolved_mismatch == () and ledger.unresolvable == ()
    assert ledger.resolved_exact >= 1


def test_pptx_table_cell_resolves_and_tamper_is_caught() -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(2)).table
    for r, row in enumerate((("Item", "Value"), ("Margin", "42.5%"))):
        for c, text in enumerate(row):
            table.cell(r, c).text = text
    buf = io.BytesIO()
    deck.save(buf)
    data = buf.getvalue()
    ledger, document = _ledger("pptx", data)
    assert ledger.table_blocks_derived == 1 and ledger.resolved_exact >= 4
    assert ledger.resolved_mismatch == ()
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "ppt/slides/slide1.xml":
                assert b"42.5%" in payload
                payload = payload.replace(b"42.5%", b"47.5%")
            target.writestr(item, payload)
    tampered = build_ledger(out.getvalue(), document)  # type: ignore[arg-type]
    assert tampered.resolved_mismatch and not tampered.source_hash_matches
