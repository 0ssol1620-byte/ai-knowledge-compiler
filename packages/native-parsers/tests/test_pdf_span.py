from __future__ import annotations

import copy
import io
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from akc_cir import CanonicalDocument
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


@pytest.mark.parametrize("name", ["valid-text-pdf", "valid-scan-pdf", "valid-mixed-pdf"])
def test_fixture_matrix_pdfs_roundtrip(tmp_path, name: str) -> None:  # type: ignore[no-untyped-def]
    # Capitals are wider than the parser's 0.52 em estimate; the ledger widens only the
    # right edge of the box by the stated estimation error, so 'PDF' is not cut to 'PD'.
    from tests.fixtures.build_safe_fixture_matrix import build_fixture_matrix

    data = build_fixture_matrix(tmp_path)[name].read_bytes()
    document = _parse(data)
    ledger = build_ledger(data, document)
    assert ledger.resolved_mismatch == () and ledger.unresolvable == ()
    assert ledger.resolved_exact == len(document.blocks) > 0


def _fidelity_mixed_pdf() -> bytes:
    # copied from tests/unit/test_pdf_native_fidelity.py::_mixed_pdf (same bytes)
    text = _text_pdf(
        b"BT /F1 24 Tf 72 720 Td (Evidence Architecture) Tj "
        b"0 -48 Td /F1 11 Tf (Coordinate-aware native extraction.) Tj ET "
        b"0.5 w 72 500 240 90 re S"
    )
    image = Image.new("RGB", (180, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 170, 90), outline="black", width=3)
    draw.text((25, 42), "SAFE PDF IMAGE", fill="black")
    scan = io.BytesIO()
    image.save(scan, format="PDF", resolution=100)
    combined = PdfWriter()
    for source in (PdfReader(io.BytesIO(text)), PdfReader(io.BytesIO(scan.getvalue()))):
        for page in source.pages:
            combined.add_page(page)
    out = io.BytesIO()
    combined.write(out)
    return out.getvalue()


def test_fidelity_mixed_pdf_roundtrips() -> None:
    data = _fidelity_mixed_pdf()
    document = _parse(data)
    ledger = build_ledger(data, document)
    assert ledger.resolved_mismatch == () and ledger.unresolvable == ()
    assert ledger.resolved_exact == len(document.blocks) > 0


def test_geometry_block_on_missing_page_is_unresolvable() -> None:
    data = _mixed_pdf()
    document = _parse(data)
    geometry = next(
        b for b in document.blocks if "/image-placement/" in b.source_refs[0].native_object_id
    )
    # the 2-page original truncated to its first page: the image's page is gone
    one_page = PdfWriter()
    one_page.add_page(PdfReader(io.BytesIO(data)).pages[0])
    out = io.BytesIO()
    one_page.write(out)
    ledger = build_ledger(out.getvalue(), document)
    assert (geometry.id, "locator_out_of_range") in ledger.unresolvable


def test_geometry_locator_page_must_match_block_page() -> None:
    data = _mixed_pdf()
    document = _parse(data)
    block = next(b for b in document.blocks if "/drawing/" in b.source_refs[0].native_object_id)
    ref = block.source_refs[0]
    object.__setattr__(ref, "native_object_id", ref.native_object_id.replace("page/0/", "page/9/"))
    assert build_ledger(data, document).unresolvable == ((block.id, "locator_out_of_range"),)
    object.__setattr__(ref, "native_object_id", ref.native_object_id.replace("page/9/", "page/1/"))
    assert block.id in build_ledger(data, document).resolved_mismatch


def test_unrelated_original_does_not_pass_geometry() -> None:
    document = _parse(_mixed_pdf())
    ledger = build_ledger(_text_pdf(b"BT /F1 12 Tf 72 720 Td (other) Tj ET"), document)
    assert ledger.resolved_exact < len(document.blocks)
    assert any(r == "locator_out_of_range" for _, r in ledger.unresolvable)


def test_geometry_needs_an_object_of_its_kind_in_the_original() -> None:
    # same page count, unrelated content: the text page has a path and no image, the
    # scan page an image and no path, so neither geometry block may pass on the other
    text_document, scan_document = _parse(_text_pdf(_LINES)), _parse(_scan_pdf())
    drawing = next(
        b for b in text_document.blocks if "/drawing/" in b.source_refs[0].native_object_id
    )
    placement = scan_document.blocks[0]
    assert drawing.id in build_ledger(_scan_pdf(), text_document).resolved_mismatch
    assert placement.id in build_ledger(_text_pdf(_LINES), scan_document).resolved_mismatch
    # an ordinal past the page's last object of that kind is not in the original either
    object.__setattr__(drawing.source_refs[0], "native_object_id", "pdf/page/0/drawing/1")
    assert drawing.id in build_ledger(_text_pdf(_LINES), text_document).resolved_mismatch


def test_text_block_under_geometry_locator_is_mismatch() -> None:
    data = _text_pdf(_LINES)
    for forged in (None, "Totally invented sentence."):
        document = _parse(data)
        block = next(b for b in document.blocks if b.raw_text and "Second" in b.raw_text)
        if forged is not None:
            object.__setattr__(block, "raw_text", forged)
        object.__setattr__(block.source_refs[0], "native_object_id", "pdf/page/0/drawing/0")
        assert block.id in build_ledger(data, document).resolved_mismatch


def test_text_block_locator_page_must_match_block_page() -> None:
    data = _mixed_pdf()
    document = _parse(data)
    block = next(b for b in document.blocks if b.raw_text)
    object.__setattr__(block.source_refs[0], "page_index0", 1)
    assert block.id in build_ledger(data, document).resolved_mismatch


def test_geometry_block_without_bbox_is_unresolvable() -> None:
    data = _mixed_pdf()
    document = _parse(data)
    block = next(b for b in document.blocks if "/drawing/" in b.source_refs[0].native_object_id)
    object.__setattr__(block.source_refs[0], "bbox1000", None)
    assert (block.id, "no_bbox") in build_ledger(data, document).unresolvable


def _nonpdf_documents() -> list[tuple[bytes, CanonicalDocument]]:
    from akc_native_parsers import parse_non_pdf_to_cir
    from docx import Document as WordDocument
    from openpyxl import Workbook
    from pptx import Presentation
    from pptx.util import Inches

    word = WordDocument()
    word.add_paragraph("Revenue was -1,234.50 KRW.")
    word.add_table(rows=1, cols=1).cell(0, 0).text = "42.5%"
    docx = io.BytesIO()
    word.save(docx)
    book = Workbook()
    sheet: Any = book.active
    sheet["A1"] = "Total"
    sheet["B1"] = 1234.5
    xlsx = io.BytesIO()
    book.save(xlsx)
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "Plan 2026"
    slide.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1)).text_frame.text = "12.5%"
    pptx = io.BytesIO()
    deck.save(pptx)
    fixtures = Path(__file__).parents[3] / "tests" / "fixtures" / "nonpdf"
    sources = {
        "docx": docx.getvalue(),
        "xlsx": xlsx.getvalue(),
        "pptx": pptx.getvalue(),
        **{ext: (fixtures / f"sample.{ext}").read_bytes() for ext in ("html", "srt", "vtt")},
    }
    mime = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "html": "text/html",
        "srt": "application/x-subrip",
        "vtt": "text/vtt",
    }
    now = datetime(2026, 7, 30, tzinfo=UTC)
    context = ParseContext(
        tenant_id="tenant_fixture",
        document_id="document_fixture",
        document_version_id="version_fixture",
        created_at=now,
    )
    parse = parse_non_pdf_to_cir
    return [
        (data, parse(filename=f"s.{ext}", declared_mime=mime[ext], data=data, context=context))
        for ext, data in sources.items()
    ]


def _units(document: CanonicalDocument) -> Iterator[Any]:
    for block in document.blocks:
        yield from block.table.cells if block.table is not None else (block,)


def test_forged_text_is_never_exact_under_any_locator() -> None:
    # Property over every format and every locator shape the parsers emit (each format's
    # own locators, the other formats' locators, PDF text and geometry): a unit whose text
    # no original contains is never counted exact. A path that passes a unit without
    # comparing its text (the geometry bypass this guards) fails here for every format.
    forged = "Forged text that no source contains 4242."
    corpus = [(data, _parse(data)) for data in (_mixed_pdf(), _scan_pdf())]
    corpus += _nonpdf_documents()
    locators = sorted(
        {
            ref.native_object_id
            for _, document in corpus
            for unit in _units(document)
            for ref in unit.source_refs[:1]
            if ref.native_object_id
        }
    )
    assert any("/drawing/" in x for x in locators) and any(
        "/image-placement/" in x for x in locators
    )
    assert len({x.split("/", 1)[0] for x in locators}) == 7  # every format contributes
    for data, original in corpus:
        for locator in (None, *locators):  # None = each unit keeps its own locator
            document = copy.deepcopy(original)
            for unit in _units(document):
                object.__setattr__(unit, "raw_text", forged)
                if locator is not None and unit.source_refs:
                    object.__setattr__(unit.source_refs[0], "native_object_id", locator)
            ledger = build_ledger(data, document)
            assert ledger.resolved_exact == 0, (document.metadata["documentType"], locator)


def _verdict(ledger: Any, unit_id: str) -> str:
    if unit_id in ledger.resolved_mismatch:
        return "mismatch"
    if any(u == unit_id for u, _ in ledger.unresolvable):
        return "unresolvable"
    return "exact"


def _structural_failures() -> Iterator[tuple[str, bytes, CanonicalDocument, Any]]:
    # Units that must fail whatever their text says: the locator, page, object ordinal,
    # asset or cue range contradicts the original. Each yields (kind, data, document, unit).
    data = _text_pdf(_LINES)
    document = _parse(data)
    unit = next(b for b in document.blocks if "/drawing/" in b.source_refs[0].native_object_id)
    object.__setattr__(unit.source_refs[0], "native_object_id", "pdf/page/0/drawing/7")
    yield "pdf", data, document, unit  # object_not_in_original
    for field in ("text", "drawing"):
        data = _mixed_pdf()
        document = _parse(data)
        unit = next(
            b
            for b in document.blocks
            if f"/{field}/" in b.source_refs[0].native_object_id
            and b.source_refs[0].page_index0 == 0
        )
        object.__setattr__(unit.source_refs[0], "page_index0", 1)
        yield "pdf", data, document, unit  # locator_page_differs
    bad_assets: tuple[Any, ...] = ([], "abc")
    for assets in bad_assets:
        data = _scan_pdf()
        document = _parse(data)
        document.metadata["assets"] = assets
        yield "pdf", data, document, document.blocks[0]  # asset_unregistered
    srt_data, srt = next(
        (d, doc) for d, doc in _nonpdf_documents() if doc.metadata["documentType"] == "srt"
    )
    unit = srt.blocks[0]
    ref = unit.source_refs[0]
    # cues 0 and 1 say different things, so no single text is the range's text; the
    # timing is set to the range's own so only the text could decide the verdict
    object.__setattr__(ref, "native_object_id", "srt/cue/000000-000001")
    object.__setattr__(ref, "time_start_ms", 1000)
    object.__setattr__(ref, "time_end_ms", 5000)
    yield "srt", srt_data, srt, unit  # range_text_differs


def test_a_failure_is_never_spelled_as_text_a_forger_can_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Class property, not one input: whatever a resolver hands back as "the original's
    # text" for a unit that must fail, writing exactly that into raw_text must not turn it
    # exact. A failure returned as an in-band marker string (the "\x00..." sentinels this
    # guards) is caught by recording every string each resolver returns and forging it.
    from akc_native_parsers import span_ledger

    seen: set[str] = set()

    def spying(kind: str) -> None:
        real = span_ledger._FACTORIES[kind]

        def factory(data: bytes) -> Any:
            resolver = real(data)

            def spy(*args: Any) -> Any:
                text, span = resolver(*args)
                seen.add(text)
                return text, span

            spy.__dict__.update(vars(resolver))  # units, wants_ref
            return spy

        monkeypatch.setitem(span_ledger._FACTORIES, kind, factory)

    spying("pdf")
    spying("srt")
    reasons = (
        "locator_page_differs",
        "object_not_in_original",
        "asset_unregistered",
        "range_text_differs",
    )
    cases = list(_structural_failures())
    assert len(cases) == 6
    for _kind, data, document, unit in cases:
        seen.clear()
        assert _verdict(build_ledger(data, document), unit.id) == "mismatch"
        forgeries = {"", unit.raw_text or "", *seen, *("\x00" + r for r in reasons), *reasons}
        for forged in sorted(forgeries):
            object.__setattr__(unit, "raw_text", forged)
            verdict = _verdict(build_ledger(data, document), unit.id)
            assert verdict == "mismatch", (unit.source_refs[0].native_object_id, forged)


@pytest.mark.parametrize(
    "assets", [None, "abc", ["x"], [1], [{"id": None, "sha256": "sha256:" + "0" * 64}], {}]
)
def test_malformed_asset_metadata_fails_closed_without_raising(assets: Any) -> None:
    data = _scan_pdf()
    document = _parse(data)
    document.metadata["assets"] = assets
    assert build_ledger(data, document).resolved_mismatch == (document.blocks[0].id,)
    # no other format reads metadata.assets: its ledger is unchanged by it
    for data, other in _nonpdf_documents():
        before = build_ledger(data, other)
        other.metadata["assets"] = assets
        assert build_ledger(data, other) == before


def test_page_objects_are_scanned_once_per_page(monkeypatch: pytest.MonkeyPatch) -> None:
    pypdfium2 = pytest.importorskip("pypdfium2")

    data = _text_pdf(b"".join(b"%d 100 2 2 re S " % (10 + i) for i in range(60)))
    document = _parse(data)
    drawings = [b for b in document.blocks if "/drawing/" in b.source_refs[0].native_object_id]
    assert len(drawings) == 60
    calls: list[int] = []
    real = pypdfium2.PdfPage.get_objects

    def counting(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pypdfium2.PdfPage, "get_objects", counting)
    ledger = build_ledger(data, document)
    assert ledger.resolved_exact == len(document.blocks) and ledger.resolved_mismatch == ()
    assert len(calls) == 1


def test_non_pdf_unit_under_pdf_locator_is_unknown_grammar() -> None:
    for data, document in _nonpdf_documents():
        unit = next(u for u in _units(document) if u.source_refs and u.raw_text)
        for locator in ("pdf/page/0/drawing/0", "pdf/page/0/image-placement/0"):
            object.__setattr__(unit.source_refs[0], "native_object_id", locator)
            ledger = build_ledger(data, document)
            assert (unit.id, "unknown_locator_grammar") in ledger.unresolvable, locator
