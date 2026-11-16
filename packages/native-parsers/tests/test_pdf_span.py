from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from akc_native_parsers import ParseContext, parse_pdf_to_cir
from akc_native_parsers.span_ledger import build_ledger
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

pytest.importorskip("pypdfium2")


def _text_pdf(content: bytes, *, rotate: int = 0) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    if rotate:
        page.rotate(rotate)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


_LINES = (
    b"BT /F1 24 Tf 72 720 Td (Evidence Architecture) Tj "
    b"0 -48 Td /F1 11 Tf (Revenue was -1,234.50 KRW, up 3.5 percent.) Tj "
    b"0 -40 Td (Second paragraph on its own line.) Tj ET "
    b"0.5 w 72 400 240 90 re S"
)


def _scan_pdf() -> bytes:
    image = Image.new("RGB", (320, 180), "white")
    ImageDraw.Draw(image).rectangle((20, 20, 300, 160), outline="black", width=2)
    out = io.BytesIO()
    image.save(out, format="PDF", resolution=100)
    return out.getvalue()


def _mixed_pdf() -> bytes:
    combined = PdfWriter()
    for source in (PdfReader(io.BytesIO(_text_pdf(_LINES))), PdfReader(io.BytesIO(_scan_pdf()))):
        for page in source.pages:
            combined.add_page(page)
    out = io.BytesIO()
    combined.write(out)
    return out.getvalue()


def _parse(data: bytes):  # type: ignore[no-untyped-def]
    now = datetime(2026, 7, 30, tzinfo=UTC)
    return parse_pdf_to_cir(
        filename="s.pdf",
        declared_mime="application/pdf",
        data=data,
        context=ParseContext(
            tenant_id="tenant_pdf",
            document_id="doc_pdf",
            document_version_id="doc_pdf:v1",
            created_at=now,
            retrieved_at=now,
        ),
    )


def test_pdf_text_blocks_resolve_inside_their_bbox() -> None:
    data = _mixed_pdf()
    document = _parse(data)
    ledger = build_ledger(data, document)
    assert ledger.resolved_mismatch == ()
    assert ledger.unresolvable == ()
    assert ledger.units_expected == 2 and ledger.units_missing == ()
    texts = [b for b in document.blocks if b.raw_text]
    assert len(texts) == 3
    # 3 text + 1 vector drawing + 1 image placement, all judged
    assert ledger.resolved_exact == len(document.blocks) == 5
    assert ledger.numeric_tokens_total == ledger.numeric_tokens_roundtripped > 0


def test_scan_page_has_no_text_blocks_and_one_image_block() -> None:
    data = _scan_pdf()
    document = _parse(data)
    assert [b for b in document.blocks if b.raw_text] == []
    assert len(document.blocks) == 1
    ledger = build_ledger(data, document)
    assert ledger.resolved_exact == 1 and ledger.resolved_mismatch == ()
    assert ledger.numeric_tokens_total == 0


def test_rotated_page_resolves() -> None:
    data = _text_pdf(_LINES, rotate=90)
    ledger = build_ledger(data, _parse(data))
    assert ledger.resolved_mismatch == () and ledger.unresolvable == ()
    assert ledger.resolved_exact >= 3


def test_shifted_bbox_is_reported_as_mismatch() -> None:
    data = _text_pdf(_LINES)
    document = _parse(data)
    target = next(b for b in document.blocks if b.raw_text and "Second" in b.raw_text)
    ref = target.source_refs[0]
    x1, y1, x2, y2 = ref.bbox1000.root
    shifted = type(ref.bbox1000)((x1, y1 + 400, x2, y2 + 400))
    object.__setattr__(ref, "bbox1000", shifted)
    ledger = build_ledger(data, document)
    assert target.id in ledger.resolved_mismatch
    assert ledger.resolved_exact < len(document.blocks)


def test_missing_asset_hash_is_reported_as_mismatch() -> None:
    data = _scan_pdf()
    document = _parse(data)
    document.metadata["assets"] = []
    ledger = build_ledger(data, document)
    assert len(ledger.resolved_mismatch) == 1


def test_unknown_pdf_locator_is_unresolvable() -> None:
    data = _text_pdf(_LINES)
    document = _parse(data)
    block = next(b for b in document.blocks if b.raw_text)
    object.__setattr__(block.source_refs[0], "native_object_id", "pdf/page/9/text/" + "0" * 20)
    ledger = build_ledger(data, document)
    assert (block.id, "locator_out_of_range") in ledger.unresolvable
