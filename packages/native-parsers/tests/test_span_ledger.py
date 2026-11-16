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


_YT = (
    "WEBVTT\nKind: captions\n\n"
    "00:00:00.000 --> 00:00:02.000\nrevenue<00:00:00.500><c> was</c> 42\n\n"
    "00:00:02.000 --> 00:00:02.010\nrevenue was 42\n\n"
    "00:00:02.010 --> 00:00:04.000\nnext line 7\n"
)


def test_markup_only_repeat_cue_merges_exact_and_tamper_is_caught() -> None:
    data = _YT.encode()
    document = _parse("vtt", data)
    assert any("-" in b.source_refs[0].native_object_id for b in document.blocks if b.source_refs)
    ledger = build_ledger(data, document)
    assert ledger.resolved_mismatch == ()
    assert ledger.resolved_exact == 2
    tampered = build_ledger(
        _YT.replace("\nrevenue was 42\n", "\nrevenue was 43\n").encode(), document
    )
    assert tampered.resolved_mismatch


def test_vtt_note_style_blocks_do_not_shift_cue_numbering() -> None:
    data = (
        b"WEBVTT\n\nNOTE\n00:00:09.000 --> 00:00:09.500\nignored 9\n\n"
        b"STYLE\n::cue { color: red }\n\n"
        b"00:00:00.000 --> 00:00:01.000\nfirst 1\n\n"
        b"00:00:02.000 --> 00:00:03.000\nsecond 2\n"
    )
    document = _parse("vtt", data)
    ledger = build_ledger(data, document)
    assert ledger.resolved_mismatch == ()
    assert {r for _, r in ledger.unresolvable} == {"parser_generated_text"}


def _cues(kind: str, texts: list[str]) -> bytes:
    sep = "," if kind == "srt" else "."
    cues = [
        f"{i + 1}\n00:00:0{i}{sep}000 --> 00:00:0{i + 1}{sep}000\n{t}"
        if kind == "srt"
        else f"00:00:0{i}{sep}000 --> 00:00:0{i + 1}{sep}000\n{t}"
        for i, t in enumerate(texts)
    ]
    return (("" if kind == "srt" else "WEBVTT\n\n") + "\n\n".join(cues) + "\n").encode()


def _merged_block(document: object) -> object:
    merged = [
        b
        for b in document.blocks  # type: ignore[attr-defined]
        if b.source_refs
        and "/cue/" in b.source_refs[0].native_object_id
        and "-" in b.source_refs[0].native_object_id
    ]
    assert len(merged) == 1, "parser should merge the first two cues"
    return merged[0]


@pytest.mark.parametrize("kind", ["srt", "vtt"])
@pytest.mark.parametrize(
    ("first", "second"),
    [("rate 5", "rate<10%> 5"), ("total due", "total<USD -1,234.50> due")],
)
def test_angle_bracket_text_is_not_markup_so_a_lossy_merge_is_mismatch(
    kind: str, first: str, second: str
) -> None:
    # The parser strips anything in <...> and merges; the number is gone from the CIR.
    data = _cues(kind, [first, second, "other 1"])
    document = _parse(kind, data)
    block = _merged_block(document)
    assert block.id in build_ledger(data, document).resolved_mismatch  # type: ignore[attr-defined]


@pytest.mark.parametrize("kind", ["srt", "vtt"])
def test_angle_bracket_tamper_of_a_clean_merged_cue_is_mismatch(kind: str) -> None:
    clean = _cues(kind, ["total due", "total due", "x 1"])
    document = _parse(kind, clean)
    block = _merged_block(document)
    tampered = _cues(kind, ["total due", "total<999> due", "x 1"])
    assert block.id in build_ledger(tampered, document).resolved_mismatch  # type: ignore[attr-defined]


@pytest.mark.parametrize("kind", ["srt", "vtt"])
def test_grid_non_markup_angle_text_in_a_merged_cue_never_passes(kind: str) -> None:
    # every word x sign x number x suffix x position: angle-bracketed cue text the
    # parser drops must never let the merged block through as exact
    import itertools

    clean = _cues(kind, ["sold due", "sold due", "x 1"])
    document = _parse(kind, clean)
    block = _merged_block(document)
    grid = itertools.product(
        ["", "USD ", "rate ", "v ", "i ", "font"],
        ["", "-", "+"],
        ["0", "7", "1,234", "99999"],
        ["", "%", ".50", " KRW"],
        [0, 4, 8],
    )
    for word, sign, number, suffix, at in grid:
        middle = "sold due"[:at] + f"<{word}{sign}{number}{suffix}>" + "sold due"[at:]
        ledger = build_ledger(_cues(kind, ["sold due", middle, "x 1"]), document)
        assert block.id in ledger.resolved_mismatch, middle  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("kind", "second"),
    [
        ("srt", '<i>sold</i> <font color="#ff0000">due</font>'),
        ("srt", "<B>sold due</B>"),
        ("vtt", "sold<00:00:01.500><c.yellow> due</c>"),
        ("vtt", "<ruby>sold<rt></rt></ruby> <lang en>due</lang>"),
    ],
)
def test_format_markup_only_differences_stay_exact(kind: str, second: str) -> None:
    data = _cues(kind, ["sold due", second, "x 1"])
    document = _parse(kind, data)
    _merged_block(document)
    ledger = build_ledger(data, document)
    assert ledger.resolved_mismatch == ()


def test_vtt_voice_names_stay_in_the_merge_key() -> None:
    clean = _cues("vtt", ["<v Alice>sold 42", "<v Alice>sold 42", "x 1"])
    document = _parse("vtt", clean)
    block = _merged_block(document)
    assert build_ledger(clean, document).resolved_mismatch == ()
    tampered = _cues("vtt", ["<v Alice>sold 42", "<v Alice>sold <v Bob>42", "x 1"])
    assert block.id in build_ledger(tampered, document).resolved_mismatch  # type: ignore[attr-defined]


def test_reversed_cue_range_and_missing_vtt_signature_are_named() -> None:
    data = _cues("vtt", ["a 1", "b 2"])
    document = _parse("vtt", data)
    cue = next(b for b in document.blocks if "/cue/" in b.source_refs[0].native_object_id)
    ref = cue.source_refs[0].model_copy(update={"native_object_id": "vtt/cue/000001-000000"})
    odd = document.model_copy(
        update={
            "blocks": tuple(
                b.model_copy(update={"source_refs": (ref,)}) if b.id == cue.id else b
                for b in document.blocks
            )
        }
    )
    assert (cue.id, "locator_range_reversed") in build_ledger(data, odd).unresolvable
    unsigned = build_ledger(data.replace(b"WEBVTT", b"WEBVTX"), document)
    assert unsigned.resolved_exact == 0
    assert {r for _, r in unsigned.unresolvable} == {"vtt_signature_missing"}


def test_resolver_imports_no_parser_module() -> None:
    # The resolver must not inherit the parser's blind spots through its code.
    import ast

    import akc_native_parsers.span_ledger as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    own = {
        (node.level, node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.level or "native_parsers" in (node.module or ""))
    }
    assert own <= {(1, "models")}, own
