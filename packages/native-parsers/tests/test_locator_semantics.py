from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_native_parsers import ParseContext, ParserLimits, parse_non_pdf_to_cir
from akc_native_parsers.models import (
    LOCATOR_PAGE_SEMANTICS,
    CirBuilder,
    StructuredParseError,
)
from docx import Document as WordDocument
from openpyxl import Workbook
from pptx import Presentation

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures" / "nonpdf"
MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
}


def _context() -> ParseContext:
    return ParseContext(
        tenant_id="tenant_fixture",
        document_id="document_fixture",
        document_version_id="version_fixture",
        created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
    )


def _office_bytes() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    word = WordDocument()
    word.add_paragraph("Hello")
    buf = io.BytesIO()
    word.save(buf)
    out["docx"] = buf.getvalue()
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "Title"
    buf = io.BytesIO()
    deck.save(buf)
    out["pptx"] = buf.getvalue()
    book = Workbook()
    book.active["A1"] = "x"
    buf = io.BytesIO()
    book.save(buf)
    book.close()
    out["xlsx"] = buf.getvalue()
    return out


def _builder(document_type: str) -> CirBuilder:
    return CirBuilder(
        context=_context(),
        source_filename=f"s.{document_type}",
        source_sha256="sha256:" + "0" * 64,
        document_type=document_type,
        limits=ParserLimits(),
    )


def _samples() -> dict[str, bytes]:
    samples = _office_bytes()
    for ext in ("html", "srt", "vtt"):
        samples[ext] = (FIXTURES / f"sample.{ext}").read_bytes()
    return samples


def test_each_native_type_declares_page_semantics() -> None:
    for ext, data in _samples().items():
        document = parse_non_pdf_to_cir(
            filename=f"sample.{ext}",
            declared_mime=MIME[ext],
            data=data,
            context=_context(),
        )
        assert document.metadata["locatorPageSemantics"] == LOCATOR_PAGE_SEMANTICS[ext]
    assert _builder("pdf").build(title="t").metadata["locatorPageSemantics"] == "layout_page"


def test_reflowable_formats_never_claim_layout_pages() -> None:
    for ext in ("docx", "html", "srt", "vtt", "hwp", "hwpx", "hwpml"):
        assert LOCATOR_PAGE_SEMANTICS[ext] == "container_ordinal"
    assert LOCATOR_PAGE_SEMANTICS["pdf"] == "layout_page"
    assert [k for k, v in LOCATOR_PAGE_SEMANTICS.items() if v == "layout_page"] == ["pdf"]


def test_unknown_document_type_fails_closed() -> None:
    with pytest.raises(StructuredParseError) as raised:
        _builder("rtf").build(title="t")
    assert str(raised.value) == "LOCATOR_SEMANTICS_UNKNOWN"
