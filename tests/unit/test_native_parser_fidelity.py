from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from akc_cir import BlockType
from akc_native_parsers import (
    ParseContext,
    StructuredParseError,
    parse_non_pdf_to_cir,
)
from docx import Document as WordDocument
from lxml import etree
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment as SpreadsheetComment
from openpyxl.drawing.image import Image as SpreadsheetImage
from openpyxl.workbook.defined_name import DefinedName
from PIL import Image
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_CONNECTOR
from pptx.util import Inches

_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
#: A Korean finance number format: thousands separator, the 원 suffix, and a
#: negative shown in parentheses rather than with a minus sign.
KRW_FORMAT = '#,##0"원";(#,##0)"원"'
_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "srt": "application/x-subrip",
}


def _context() -> ParseContext:
    return ParseContext(
        tenant_id="tenant_fidelity",
        document_id="document_fidelity",
        document_version_id="version_fidelity",
        created_at=datetime(2026, 7, 30, 1, 0, tzinfo=UTC),
    )


def _parse(filename: str, payload: bytes):
    extension = filename.rsplit(".", 1)[-1]
    return parse_non_pdf_to_cir(
        filename=filename,
        declared_mime=_MIME[extension],
        data=payload,
        context=_context(),
    )


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (24, 12), color=(33, 96, 144)).save(output, format="PNG")
    return output.getvalue()


def _docx_with_assets_comments_and_revisions() -> bytes:
    document = WordDocument()
    document.add_paragraph("Native fidelity", style="Title")
    image_paragraph = document.add_paragraph()
    run = image_paragraph.add_run()
    run.add_picture(io.BytesIO(_png_bytes()), width=Inches(1))
    doc_properties = run._r.xpath(".//wp:docPr")[0]
    doc_properties.set("descr", "Architecture overview")
    document.add_paragraph("Figure 1. Architecture", style="Caption")
    commented = document.add_paragraph("Review this statement")
    document.add_comment(
        runs=commented.runs,
        text="Verified reviewer note",
        author="Reviewer",
        initials="RV",
    )
    document.add_paragraph("revision target")
    document.sections[0].header.paragraphs[0].text = "Confidential"
    document.sections[0].footer.paragraphs[0].text = "Page footer"
    output = io.BytesIO()
    document.save(output)

    def add_revisions(value: bytes) -> bytes:
        root = etree.fromstring(value)
        namespace = {"w": _WORD_NS}
        target = root.xpath("//w:t[text()='revision target']", namespaces=namespace)[0]
        run_element = target.getparent()
        paragraph = run_element.getparent()
        target.text = "base "
        insertion = etree.Element(f"{{{_WORD_NS}}}ins")
        insertion.set(f"{{{_WORD_NS}}}author", "Editor")
        insertion_run = etree.SubElement(insertion, f"{{{_WORD_NS}}}r")
        insertion_text = etree.SubElement(insertion_run, f"{{{_WORD_NS}}}t")
        insertion_text.text = "visible insertion"
        deletion = etree.Element(f"{{{_WORD_NS}}}del")
        deletion.set(f"{{{_WORD_NS}}}author", "Editor")
        deletion_run = etree.SubElement(deletion, f"{{{_WORD_NS}}}r")
        deletion_text = etree.SubElement(deletion_run, f"{{{_WORD_NS}}}delText")
        deletion_text.text = "deleted text"
        index = paragraph.index(run_element)
        paragraph.insert(index + 1, insertion)
        paragraph.insert(index + 2, deletion)
        return etree.tostring(
            root,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )

    return _rewrite_zip(
        output.getvalue(),
        transform={"word/document.xml": add_revisions},
    )


def test_docx_extracts_embedded_asset_caption_comment_and_revision_views() -> None:
    document = _parse(
        "fidelity.docx",
        _docx_with_assets_comments_and_revisions(),
    )
    assets = document.metadata["assets"]
    assert len(assets) == 1
    assert assets[0]["kind"] == "image"
    assert assets[0]["mediaType"] == "image/png"
    assert assets[0]["widthPx"] == 24
    assert assets[0]["heightPx"] == 12
    assert assets[0]["sha256"].startswith("sha256:")
    figure = next(block for block in document.blocks if block.type == BlockType.FIGURE)
    assert figure.source_refs[0].image_asset_id == assets[0]["id"]
    assert "alt_text_preserved" in figure.quality_flags
    caption = next(block for block in document.blocks if block.type == BlockType.CAPTION)
    assert caption.parent_id == figure.id
    comment = next(block for block in document.blocks if "docx_comment" in block.quality_flags)
    assert comment.raw_text == "Verified reviewer note"
    assert comment.parent_id is not None
    visible = "\n".join(block.raw_text or "" for block in document.blocks)
    assert "base visible insertion" in visible
    assert "deleted text" not in visible
    revisions = document.metadata["docx"]["trackedChanges"]
    assert [revision["kind"] for revision in revisions] == ["insertion", "deletion"]
    assert revisions[0]["visible"] is True
    assert revisions[1]["text"] == "deleted text"
    assert document.metadata["docx"]["trackedChangeView"] == (
        "insertions-visible-deletions-metadata-only"
    )
    assert any(block.type == BlockType.HEADER for block in document.blocks)
    assert any(block.type == BlockType.FOOTER for block in document.blocks)


def _pptx_with_assets_chart_group_and_connector() -> bytes:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "Visual evidence"
    picture = slide.shapes.add_picture(
        io.BytesIO(_png_bytes()),
        Inches(0.5),
        Inches(1.5),
        Inches(1.5),
        Inches(0.75),
    )
    picture._pic.nvPicPr.cNvPr.set("descr", "System architecture")

    chart_data = ChartData()
    chart_data.categories = ["Baseline", "Candidate"]
    chart_data.add_series("Accuracy", (0.82, 0.94))
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        Inches(3),
        Inches(1.5),
        Inches(4),
        Inches(2.5),
        chart_data,
    ).chart
    chart.has_title = True
    chart.chart_title.text_frame.text = "Accuracy"

    group = slide.shapes.add_group_shape()
    grouped_first = group.shapes.add_textbox(
        Inches(1),
        Inches(4.5),
        Inches(2),
        Inches(0.5),
    )
    grouped_first.text_frame.text = "Grouped source"
    grouped_second = group.shapes.add_textbox(
        Inches(4),
        Inches(4.5),
        Inches(2),
        Inches(0.5),
    )
    grouped_second.text_frame.text = "Grouped target"
    connector = group.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT,
        Inches(3),
        Inches(4.7),
        Inches(4),
        Inches(4.7),
    )
    connector.begin_connect(grouped_first, 3)
    connector.end_connect(grouped_second, 1)
    slide.notes_slide.notes_text_frame.text = "Speaker-only context"
    output = io.BytesIO()
    deck.save(output)
    return output.getvalue()


def test_pptx_extracts_image_chart_notes_and_group_connector_reading_order() -> None:
    document = _parse(
        "visuals.pptx",
        _pptx_with_assets_chart_group_and_connector(),
    )
    assets = document.metadata["assets"]
    assert {asset["kind"] for asset in assets} == {"image", "chart"}
    picture = next(
        block
        for block in document.blocks
        if block.type == BlockType.FIGURE and "alt_text_preserved" in block.quality_flags
    )
    assert picture.source_refs[0].image_asset_id is not None
    chart = next(
        block for block in document.blocks if "chart_structure_extracted" in block.quality_flags
    )
    assert "Accuracy" in (chart.raw_text or "")
    chart_asset = next(asset for asset in assets if asset["kind"] == "chart")
    chart_data = chart_asset["metadata"]["chartData"]
    assert chart_data["series"][0]["name"] == "Accuracy"
    assert chart_data["series"][0]["values"] == [0.82, 0.94]
    slide = document.metadata["slides"][0]
    assert slide["groupCount"] == 1
    assert slide["connectorCount"] == 1
    assert slide["readingOrderStrategy"] == "connector-topology-group-position-z"
    assert any("shape_group:" in flag for block in document.blocks for flag in block.quality_flags)
    assert any(
        block.type == BlockType.FOOTNOTE and "speaker_notes" in block.quality_flags
        for block in document.blocks
    )


def test_pptx_chart_workbook_is_relationship_scoped_and_recursively_validated() -> None:
    source = _pptx_with_assets_chart_group_and_connector()
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        embedding_name = next(
            name
            for name in archive.namelist()
            if name.casefold().startswith("ppt/embeddings/") and name.casefold().endswith(".xlsx")
        )
        embedded_workbook = archive.read(embedding_name)

    unrelated = _rewrite_zip(
        source,
        additions={"ppt/embeddings/unrelated.xlsx": embedded_workbook},
    )
    with pytest.raises(StructuredParseError, match="OFFICE_EMBEDDED_OBJECT"):
        _parse("unrelated.pptx", unrelated)

    def add_external_relationship(value: bytes) -> bytes:
        return value.replace(
            b"</Relationships>",
            (
                b'<Relationship Id="unsafe" '
                b'Type="http://schemas.openxmlformats.org/officeDocument/'
                b'2006/relationships/externalLink" '
                b'Target="https://example.invalid/" TargetMode="External"/>'
                b"</Relationships>"
            ),
        )

    unsafe_workbook = _rewrite_zip(
        embedded_workbook,
        transform={"xl/_rels/workbook.xml.rels": add_external_relationship},
    )
    unsafe_chart = _rewrite_zip(
        source,
        transform={embedding_name: lambda _value: unsafe_workbook},
    )
    with pytest.raises(StructuredParseError, match="OFFICE_EXTERNAL_RELATION"):
        _parse("unsafe-chart.pptx", unsafe_chart)


def _xlsx_with_assets_chart_formula_and_hidden_state() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Evidence"
    sheet.append(["Category", "Value", "Formula"])
    sheet.append(["Baseline", 1, "=SUM(B2:B3)"])
    sheet.append(["Candidate", 2, None])
    sheet.row_dimensions[3].hidden = True
    sheet.column_dimensions["B"].hidden = True
    image = SpreadsheetImage(io.BytesIO(_png_bytes()))
    image.anchor = "E2"
    sheet.add_image(image)
    chart = BarChart()
    chart.title = "Comparison"
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=3))
    sheet.add_chart(chart, "E8")
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()

    def add_formula_cache(value: bytes) -> bytes:
        return value.replace(
            b"<f>SUM(B2:B3)</f><v></v>",
            b"<f>SUM(B2:B3)</f><v>3</v>",
        )

    return _rewrite_zip(
        output.getvalue(),
        transform={"xl/worksheets/sheet1.xml": add_formula_cache},
    )


def test_xlsx_extracts_assets_chart_formula_cache_and_hidden_state() -> None:
    document = _parse(
        "evidence.xlsx",
        _xlsx_with_assets_chart_formula_and_hidden_state(),
    )
    sheet = document.metadata["sheets"][0]
    assert sheet["hiddenRows"] == [3]
    assert sheet["hiddenColumns"] == ["B"]
    assert sheet["formulas"] == [
        {
            "cell": "C2",
            "formula": "=SUM(B2:B3)",
            "cachedValue": "3",
            "cachedValuePresent": True,
        }
    ]
    assert sheet["imageCount"] == 1
    assert sheet["chartCount"] == 1
    assets = document.metadata["assets"]
    assert {asset["kind"] for asset in assets} == {"image", "chart"}
    assert all(asset["sha256"].startswith("sha256:") for asset in assets)
    figures = [block for block in document.blocks if block.type == BlockType.FIGURE]
    assert len(figures) == 2
    assert all(block.source_refs[0].image_asset_id for block in figures)
    chart_asset = next(asset for asset in assets if asset["kind"] == "chart")
    assert chart_asset["metadata"]["chartData"]["series"][0]["valueReference"].endswith("$B$2:$B$3")


def test_subtitle_segments_preserve_cues_with_deterministic_topic_boundaries() -> None:
    payload = (
        b"1\n00:00:00,000 --> 00:00:20,000\nOpening context.\n\n"
        b"2\n00:00:20,000 --> 00:00:40,000\nSupporting detail.\n\n"
        b"3\n00:00:40,000 --> 00:01:05,000\nFirst topic closes.\n\n"
        b"4\n00:01:10,000 --> 00:01:20,000\nNew topic starts.\n\n"
        b"5\n00:01:20,000 --> 00:01:45,000\nNew topic develops.\n"
    )
    document = _parse("topics.srt", payload)
    segmentation = document.metadata["subtitles"]["segmentation"]
    assert segmentation["segmentCount"] == 2
    assert [segment["durationMs"] for segment in segmentation["segments"]] == [
        65_000,
        35_000,
    ]
    assert all(segment["within30To90Seconds"] for segment in segmentation["segments"])
    segment_blocks = [
        block for block in document.blocks if "subtitle_segment" in block.quality_flags
    ]
    cue_blocks = [block for block in document.blocks if block.type == BlockType.PARAGRAPH]
    assert len(segment_blocks) == 2
    assert len(cue_blocks) == 5
    assert {block.parent_id for block in cue_blocks} == {block.id for block in segment_blocks}
    assert segment_blocks[0].source_refs[0].time_start_ms == 0
    assert segment_blocks[-1].source_refs[0].time_end_ms == 105_000


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


_ENDNOTES_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"
_ENDNOTES_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes"
_DIAGRAM_URI = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
_OLE_URI = "http://schemas.openxmlformats.org/presentationml/2006/ole"
_PPTX_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _docx_with_endnotes() -> bytes:
    document = WordDocument()
    document.add_paragraph("Costs fell four percent.")
    output = io.BytesIO()
    document.save(output)
    endnotes = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:endnotes xmlns:w="{_WORD_NS}">'
        '<w:endnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p>'
        "</w:endnote>"
        '<w:endnote w:id="2"><w:p><w:r>'
        "<w:t>Source: the board minutes of 2 January.</w:t></w:r></w:p></w:endnote>"
        "</w:endnotes>"
    ).encode()

    def declare_type(value: bytes) -> bytes:
        return value.replace(
            b"</Types>",
            b'<Override PartName="/word/endnotes.xml" ContentType="'
            + _ENDNOTES_TYPE.encode()
            + b'"/></Types>',
            1,
        )

    def declare_relationship(value: bytes) -> bytes:
        return value.replace(
            b"</Relationships>",
            b'<Relationship Id="rIdEndnotes" Type="'
            + _ENDNOTES_REL.encode()
            + b'" Target="endnotes.xml"/></Relationships>',
            1,
        )

    return _rewrite_zip(
        output.getvalue(),
        transform={
            "[Content_Types].xml": declare_type,
            "word/_rels/document.xml.rels": declare_relationship,
        },
        additions={"word/endnotes.xml": endnotes},
    )


def test_docx_extracts_endnote_bodies_and_says_they_are_unanchored() -> None:
    """`word/endnotes.xml` used to be read by nothing at all.

    The separator endnote Word writes into every file is layout furniture and
    must not become a block; the one real endnote must, and the document must
    say the text arrives without an EvidenceLocator v2 anchor rather than let a
    caller assume one exists.
    """
    document = _parse("endnotes.docx", _docx_with_endnotes())

    endnotes = [block for block in document.blocks if "docx_endnote" in block.quality_flags]
    assert [block.raw_text for block in endnotes] == ["Source: the board minutes of 2 January."]
    assert endnotes[0].source_refs[0].native_object_id == "docx/endnotes/2"
    assert endnotes[0].type == BlockType.FOOTNOTE
    assert document.metadata["docx"]["endnoteCount"] == 1
    assert "docx_endnotes_extracted_without_anchor" in document.metadata["warnings"]


def _pptx_with_graphic_frame(uri: str) -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.text = "Delivery model"
    output = io.BytesIO()
    presentation.save(output)
    frame = (
        f'<p:graphicFrame xmlns:p="{_PPTX_NS}" xmlns:a="{_DRAWING_NS}">'
        "<p:nvGraphicFramePr>"
        '<p:cNvPr id="9" name="Frame 9"/><p:cNvGraphicFramePr/><p:nvPr/>'
        "</p:nvGraphicFramePr>"
        '<p:xfrm><a:off x="914400" y="3200400"/><a:ext cx="3657600" cy="1828800"/></p:xfrm>'
        f'<a:graphic><a:graphicData uri="{uri}"/></a:graphic></p:graphicFrame>'
    ).encode()

    def inject(value: bytes) -> bytes:
        assert b"</p:spTree>" in value
        return value.replace(b"</p:spTree>", frame + b"</p:spTree>", 1)

    return _rewrite_zip(output.getvalue(), transform={"ppt/slides/slide1.xml": inject})


@pytest.mark.parametrize(
    ("uri", "warning"),
    [
        (_DIAGRAM_URI, "pptx_smartart_not_extracted"),
        (_OLE_URI, "pptx_embedded_object_not_extracted"),
    ],
)
def test_pptx_flags_smartart_and_embedded_objects_instead_of_dropping_them(
    uri: str,
    warning: str,
) -> None:
    """A graphic frame that is neither a table nor a chart used to vanish.

    The DOCX parser has flagged the same content since lane C-2
    (`docx_smartart_not_extracted`); PPTX returned `None` from `_add_shape` and
    said nothing, which is the silent drop the constitution forbids. The diagram
    is still not extracted — that is the honest half — and the slide's real text
    is unaffected.
    """
    document = _parse("frame.pptx", _pptx_with_graphic_frame(uri))

    assert warning in document.metadata["warnings"]
    assert any(block.raw_text == "Delivery model" for block in document.blocks)


def test_pptx_without_a_graphic_frame_raises_no_diagram_warning() -> None:
    """The flag is a fact about the file, not a constant."""
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.text = "Delivery model"
    output = io.BytesIO()
    presentation.save(output)

    document = _parse("plain.pptx", output.getvalue())

    assert "pptx_smartart_not_extracted" not in document.metadata["warnings"]
    assert "pptx_embedded_object_not_extracted" not in document.metadata["warnings"]


def _xlsx_with_comments_names_and_formats() -> bytes:
    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.title = "Data"
    sheet["A1"] = "항목"
    sheet["B1"] = "금액"
    sheet["A2"] = "매출"
    sheet["B2"] = 1234
    sheet["A3"] = "영업손실"
    sheet["B3"] = -1234
    sheet["B2"].number_format = KRW_FORMAT
    sheet["B3"].number_format = KRW_FORMAT
    sheet["B2"].comment = SpreadsheetComment("2분기 마감 후 재작성.", "reviewer")
    workbook.defined_names.add(DefinedName("금액열", attr_text="Data!$B$2:$B$3"))
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_xlsx_extracts_cell_comments_defined_names_and_number_formats() -> None:
    """Three facts `xlsx_parser.py` matched zero greps for before this change.

    A note, a named range and a number format each survive differently: the note
    and the name become blocks addressable by the v2 xlsx variant's `cell` and
    `namedRange` anchors, while the format reaches CIR only — recorded per cell
    in metadata and flagged on the cell — because `ExtractedUnit` has no
    formatting field. The Korean literals are here because the anchor has to
    carry a Hangul defined name without mangling it.
    """
    document = _parse("finance.xlsx", _xlsx_with_comments_names_and_formats())

    comments = [block for block in document.blocks if "xlsx_cell_comment" in block.quality_flags]
    assert [block.raw_text for block in comments] == ["2분기 마감 후 재작성."]
    assert comments[0].source_refs[0].native_object_id == "xlsx/sheet/0000/comment/B2"
    assert "comment_author_preserved" in comments[0].quality_flags

    names = [block for block in document.blocks if "xlsx_defined_name" in block.quality_flags]
    assert [block.raw_text for block in names] == ["Data!$B$2:$B$3"]
    assert (
        names[0].source_refs[0].native_object_id
        == "xlsx/sheet/0000/definedName/금액열"
    )
    assert document.metadata["definedNames"] == [
        {
            "name": "금액열",
            "reference": "Data!$B$2:$B$3",
            "type": "RANGE",
            "scopeSheetIndex0": None,
            "extracted": True,
            "sheetIndex0": 0,
        }
    ]

    sheet_metadata = document.metadata["sheets"][0]
    assert sheet_metadata["commentCount"] == 1
    assert sheet_metadata["numberFormats"] == {"B2": KRW_FORMAT, "B3": KRW_FORMAT}
    table = next(block for block in document.blocks if block.table is not None)
    formatted = next(
        cell
        for cell in table.table.cells
        if cell.source_refs[0].native_object_id == "xlsx/sheet/0000/cell/B3"
    )
    assert "number_format_not_applied" in formatted.quality_flags
    assert formatted.raw_text == "-1234"


def test_xlsx_flags_a_threaded_comment_part_it_cannot_read() -> None:
    """openpyxl reads `xl/comments*.xml` and not `xl/threadedComments/*`.

    Both are comments to the person who wrote them, so a workbook whose review
    thread is dropped has to say so instead of reporting the notes it happens to
    understand as the whole of its comments.
    """
    threaded = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<ThreadedComments xmlns="http://schemas.microsoft.com/office/spreadsheetml/2018/'
        b'threadedcomments"/>'
    )
    payload = _rewrite_zip(
        _xlsx_with_comments_names_and_formats(),
        additions={"xl/threadedComments/threadedComment1.xml": threaded},
    )

    document = _parse("threaded.xlsx", payload)

    assert "xlsx_threaded_comments_not_extracted" in document.metadata["warnings"]


def test_a_corrupt_docx_zip_is_a_stable_refusal_not_a_traceback() -> None:
    """The failure path of every fixture above: bytes that are not a package."""
    payload = bytearray(_docx_with_endnotes())
    payload[40:120] = b"\x00" * 80

    with pytest.raises(StructuredParseError) as failure:
        _parse("corrupt.docx", bytes(payload))
    assert failure.value.code.startswith(("INVALID_OFFICE", "DOCX_"))


def test_an_xlsx_hidden_sheet_with_an_external_link_is_refused_whole() -> None:
    """A hidden sheet is read; an external relationship refuses the package.

    The two facts belong in one test because the tempting behaviour is to read
    the visible sheets and quietly skip the link — a partial extraction of a
    workbook that points somewhere this parser will not follow.
    """
    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.title = "Visible"
    sheet["A1"] = "Item"
    draft = workbook.create_sheet("Draft")
    draft["A1"] = "not for release"
    draft.sheet_state = "hidden"
    output = io.BytesIO()
    workbook.save(output)

    document = _parse("hidden.xlsx", output.getvalue())
    assert [sheet["state"] for sheet in document.metadata["sheets"]] == ["visible", "hidden"]

    def add_external_relationship(value: bytes) -> bytes:
        return value.replace(
            b"</Relationships>",
            b'<Relationship Id="rIdExternal" Type="http://schemas.openxmlformats.org/'
            b'officeDocument/2006/relationships/hyperlink" Target="https://example.invalid/"'
            b' TargetMode="External"/></Relationships>',
            1,
        )

    linked = _rewrite_zip(
        output.getvalue(),
        transform={"xl/worksheets/_rels/sheet1.xml.rels": add_external_relationship},
        additions={
            "xl/worksheets/_rels/sheet1.xml.rels": (
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                b'relationships"><Relationship Id="rIdExternal" Type="http://schemas.'
                b'openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                b'Target="https://example.invalid/" TargetMode="External"/></Relationships>'
            )
        },
    )
    with pytest.raises(StructuredParseError) as failure:
        _parse("linked.xlsx", linked)
    assert failure.value.code == "OFFICE_EXTERNAL_RELATION"
