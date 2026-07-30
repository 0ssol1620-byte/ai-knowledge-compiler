from __future__ import annotations

import io
from datetime import UTC, datetime

from akc_native_parsers import ParseContext, ParserLimits, parse_pdf_to_cir
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def _mixed_pdf() -> bytes:
    text_payload = io.BytesIO()
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
    content = DecodedStreamObject()
    content.set_data(
        b"BT /F1 24 Tf 72 720 Td (Evidence Architecture) Tj "
        b"0 -48 Td /F1 11 Tf (Coordinate-aware native extraction.) Tj ET "
        b"0.5 w 72 500 240 90 re S"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(text_payload)

    image = Image.new("RGB", (180, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 170, 90), outline="black", width=3)
    draw.text((25, 42), "SAFE PDF IMAGE", fill="black")
    image_payload = io.BytesIO()
    image.save(image_payload, format="PDF", resolution=100)

    combined = PdfWriter()
    for source in (
        PdfReader(io.BytesIO(text_payload.getvalue())),
        PdfReader(io.BytesIO(image_payload.getvalue())),
    ):
        for source_page in source.pages:
            combined.add_page(source_page)
    output = io.BytesIO()
    combined.write(output)
    return output.getvalue()


def _context() -> ParseContext:
    now = datetime(2026, 7, 30, tzinfo=UTC)
    return ParseContext(
        tenant_id="tenant-pdf",
        document_id="document-pdf",
        document_version_id="document-pdf:v1",
        created_at=now,
        retrieved_at=now,
    )


def test_pdf_native_parser_preserves_coordinates_boxes_drawings_and_assets() -> None:
    payload = _mixed_pdf()
    document = parse_pdf_to_cir(
        filename="evidence.pdf",
        declared_mime="application/pdf",
        data=payload,
        context=_context(),
        limits=ParserLimits(max_input_bytes=5 * 1024 * 1024),
        max_pages=4,
    )

    assert document.metadata["documentType"] == "pdf"
    assert document.metadata["sourceLocationScheme"].startswith("pdf/page/")
    pages = document.metadata["pages"]
    assert len(pages) == 2
    assert pages[0]["mediaBox"] == [0.0, 0.0, 612.0, 792.0]
    assert pages[0]["cropBox"] == [0.0, 0.0, 612.0, 792.0]
    assert pages[0]["nativeTextObjectCount"] >= 2

    text_blocks = [
        block
        for block in document.blocks
        if block.raw_text and "native extraction" in block.raw_text
    ]
    assert len(text_blocks) == 1
    source = text_blocks[0].source_refs[0]
    assert source.page_number1 == 1
    assert source.bbox1000 is not None
    assert 0 <= source.bbox1000.root[0] < source.bbox1000.root[2] <= 1000

    vector_blocks = [
        block for block in document.blocks if "vector_drawing_native" in block.quality_flags
    ]
    assert len(vector_blocks) == 1
    assert vector_blocks[0].source_refs[0].bbox1000 is not None

    assets = document.metadata["assets"]
    assert len(assets) >= 1
    assert all(asset["sha256"].startswith("sha256:") for asset in assets)
    image_blocks = [
        block for block in document.blocks if "embedded_image_native" in block.quality_flags
    ]
    assert len(image_blocks) >= 1
    assert image_blocks[0].source_refs[0].image_asset_id is not None
    assert image_blocks[0].source_refs[0].page_number1 == 2


def test_pdf_native_parser_is_byte_deterministic() -> None:
    payload = _mixed_pdf()
    first = parse_pdf_to_cir(
        filename="evidence.pdf",
        declared_mime="application/pdf",
        data=payload,
        context=_context(),
        max_pages=4,
    )
    second = parse_pdf_to_cir(
        filename="evidence.pdf",
        declared_mime="application/pdf",
        data=payload,
        context=_context(),
        max_pages=4,
    )

    assert first.model_dump(mode="json", by_alias=True) == second.model_dump(
        mode="json",
        by_alias=True,
    )
