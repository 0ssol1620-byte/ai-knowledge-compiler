from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from . import acquire_selected_sources
from .acquire_selected_sources import AcquisitionError, _validate_and_locate


def _zip(path: Path, members: dict[str, bytes | str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in members.items():
            archive.writestr(name, value)


def test_docx_locator_uses_first_meaningful_body_child(tmp_path: Path) -> None:
    path = tmp_path / "source.bin"
    _zip(
        path,
        {
            "[Content_Types].xml": "<Types/>",
            "word/document.xml": """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body><w:sectPr/><w:p><w:r><w:t>evidence</w:t></w:r></w:p></w:body>
                </w:document>
            """,
        },
    )
    media_type, locator = _validate_and_locate(
        row={
            "source_class": "office_korean_docx",
            "target_locator_rule": "first_native_object",
        },
        path=path,
        transport_content_type="application/octet-stream",
    )
    assert media_type.startswith("application/vnd.openxmlformats")
    assert locator == "ooxml:word/document.xml#body/*[2]"


def test_docx_empty_body_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "source.bin"
    _zip(
        path,
        {
            "[Content_Types].xml": "<Types/>",
            "word/document.xml": """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body><w:p><w:r/></w:p><w:sectPr/></w:body>
                </w:document>
            """,
        },
    )
    with pytest.raises(AcquisitionError, match="DOCX_BODY_EMPTY"):
        _validate_and_locate(
            row={
                "source_class": "office_korean_docx",
                "target_locator_rule": "first_native_object",
            },
            path=path,
            transport_content_type="application/octet-stream",
        )


def test_pptx_locator_resolves_actual_first_slide(tmp_path: Path) -> None:
    path = tmp_path / "source.bin"
    _zip(
        path,
        {
            "[Content_Types].xml": "<Types/>",
            "ppt/presentation.xml": """
                <p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <p:sldIdLst><p:sldId id="256" r:id="rId7"/></p:sldIdLst>
                </p:presentation>
            """,
            "ppt/_rels/presentation.xml.rels": """
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId7" Target="slides/slide2.xml"/>
                </Relationships>
            """,
            "ppt/slides/slide2.xml": "<p:sld xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"/>",
        },
    )
    _, locator = _validate_and_locate(
        row={
            "source_class": "office_korean_pptx",
            "target_locator_rule": "first_native_object",
        },
        path=path,
        transport_content_type="application/octet-stream",
    )
    assert locator == "ooxml:ppt/slides/slide2.xml"


def test_xlsx_locator_resolves_actual_first_sheet(tmp_path: Path) -> None:
    path = tmp_path / "source.bin"
    _zip(
        path,
        {
            "[Content_Types].xml": "<Types/>",
            "xl/workbook.xml": """
                <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <sheets><sheet name="Data" sheetId="1" r:id="rId3"/></sheets>
                </workbook>
            """,
            "xl/_rels/workbook.xml.rels": """
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId3" Target="worksheets/sheet7.xml"/>
                </Relationships>
            """,
            "xl/worksheets/sheet7.xml": "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"/>",
        },
    )
    _, locator = _validate_and_locate(
        row={
            "source_class": "office_korean_xlsx",
            "target_locator_rule": "first_native_object",
        },
        path=path,
        transport_content_type="application/octet-stream",
    )
    assert locator == "ooxml:xl/worksheets/sheet7.xml"


@pytest.mark.parametrize(
    ("source_class", "main_member", "main_xml", "rels_member", "missing_target"),
    [
        (
            "office_korean_pptx",
            "ppt/presentation.xml",
            """<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                <p:sldIdLst><p:sldId id="256" r:id="rId9"/></p:sldIdLst></p:presentation>""",
            "ppt/_rels/presentation.xml.rels",
            "slides/slide99.xml",
        ),
        (
            "office_korean_xlsx",
            "xl/workbook.xml",
            """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                <sheets><sheet name="Data" sheetId="1" r:id="rId9"/></sheets></workbook>""",
            "xl/_rels/workbook.xml.rels",
            "worksheets/sheet99.xml",
        ),
    ],
)
def test_ooxml_missing_relationship_target_fails_closed(
    tmp_path: Path,
    source_class: str,
    main_member: str,
    main_xml: str,
    rels_member: str,
    missing_target: str,
) -> None:
    path = tmp_path / "source.bin"
    _zip(
        path,
        {
            "[Content_Types].xml": "<Types/>",
            main_member: main_xml,
            rels_member: f"""
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId9" Target="{missing_target}"/>
                </Relationships>
            """,
        },
    )
    with pytest.raises(AcquisitionError, match="OOXML_RELATIONSHIP_TARGET_MISSING"):
        _validate_and_locate(
            row={"source_class": source_class, "target_locator_rule": "first_native_object"},
            path=path,
            transport_content_type="application/octet-stream",
        )


def test_ooxml_missing_relationship_part_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "source.bin"
    _zip(
        path,
        {
            "[Content_Types].xml": "<Types/>",
            "ppt/presentation.xml": """
                <p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <p:sldIdLst><p:sldId id="256" r:id="rId7"/></p:sldIdLst>
                </p:presentation>
            """,
        },
    )
    with pytest.raises(AcquisitionError, match="OOXML_STRUCTURE_INVALID"):
        _validate_and_locate(
            row={
                "source_class": "office_korean_pptx",
                "target_locator_rule": "first_native_object",
            },
            path=path,
            transport_content_type="application/octet-stream",
        )


def test_ooxml_entry_limit_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "source.bin"
    _zip(
        path,
        {
            "[Content_Types].xml": "<Types/>",
            "word/document.xml": """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body><w:p><w:r><w:t>evidence</w:t></w:r></w:p></w:body>
                </w:document>
            """,
        },
    )
    monkeypatch.setattr(acquire_selected_sources, "MAX_ZIP_ENTRIES", 1)
    with pytest.raises(AcquisitionError, match="OOXML_ENTRY_LIMIT_EXCEEDED"):
        _validate_and_locate(
            row={
                "source_class": "office_korean_docx",
                "target_locator_rule": "first_native_object",
            },
            path=path,
            transport_content_type="application/octet-stream",
        )


def test_ooxml_wrong_package_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "source.bin"
    _zip(path, {"[Content_Types].xml": "<Types/>", "ppt/presentation.xml": "<x/>"})
    with pytest.raises(AcquisitionError, match="OOXML_STRUCTURE_INVALID"):
        _validate_and_locate(
            row={
                "source_class": "office_korean_docx",
                "target_locator_rule": "first_native_object",
            },
            path=path,
            transport_content_type="application/octet-stream",
        )


def test_pdf_first_page_locator(tmp_path: Path) -> None:
    path = tmp_path / "source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)
    media_type, locator = _validate_and_locate(
        row={"source_class": "scanned_pdf", "target_locator_rule": "first_page_full_bbox1000"},
        path=path,
        transport_content_type="application/pdf",
    )
    assert media_type == "application/pdf"
    assert locator == "page:1:bbox1000:0,0,1000,1000"


def test_native_html_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    path.write_text("<html>blocked</html>", encoding="utf-8")
    with pytest.raises(AcquisitionError, match="NATIVE_SOURCE_RETURNED_HTML"):
        _validate_and_locate(
            row={
                "source_class": "native_structured",
                "source_filename": "source.csv",
                "target_locator_rule": "whole_source",
            },
            path=path,
            transport_content_type="text/html",
        )


def test_native_csv_requires_a_parseable_header(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    path.write_bytes(b"\x81\x81\x81")
    with pytest.raises(AcquisitionError, match="CSV_ENCODING_UNSUPPORTED"):
        _validate_and_locate(
            row={
                "source_class": "native_structured",
                "source_filename": "source.csv",
                "target_locator_rule": "whole_source",
            },
            path=path,
            transport_content_type="text/csv",
        )
