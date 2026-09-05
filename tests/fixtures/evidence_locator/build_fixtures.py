"""Regenerate the committed EvidenceLocator v2 resolver fixtures.

Run: ``python tests/fixtures/evidence_locator/build_fixtures.py``

Everything here is synthetic. The XLSX is written with ``zipfile`` and literal
OOXML so the fixture stays a few hundred bytes and carries no third-party
writer's version drift; the PDF uses ``pypdf``, mirroring
``tests/fixtures/build_safe_fixture_matrix.py``.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

HERE = Path(__file__).resolve().parent

SAMPLE_JSON = {
    "report": {
        "title": "Q3 revenue",
        "rows": [
            {"region": "APAC", "revenue": 1000000},
            {"region": "EMEA", "revenue": 250000},
        ],
    },
    "a/b": "slash key",
    "m~n": "tilde key",
}

_OOXML = "http://schemas.openxmlformats.org/"
_CONTENT_TYPE_NS = f"{_OOXML}package/2006/content-types"
_PKG_REL_NS = f"{_OOXML}package/2006/relationships"
_OFFICE_REL = f"{_OOXML}officeDocument/2006/relationships"
_SML_NS = f"{_OOXML}spreadsheetml/2006/main"
_SML_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml"
_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def _override(part: str, kind: str) -> str:
    return f'<Override PartName="{part}" ContentType="{_SML_TYPE}.{kind}+xml"/>'


def _relationship(identifier: str, kind: str, target: str) -> str:
    return f'<Relationship Id="{identifier}" Type="{_OFFICE_REL}/{kind}" Target="{target}"/>'


_CONTENT_TYPES = (
    f"{_DECL}<Types xmlns=\"{_CONTENT_TYPE_NS}\">"
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    + _override("/xl/workbook.xml", "sheet.main")
    + _override("/xl/worksheets/sheet1.xml", "worksheet")
    + _override("/xl/sharedStrings.xml", "sharedStrings")
    + "</Types>"
)
_ROOT_RELS = (
    f'{_DECL}<Relationships xmlns="{_PKG_REL_NS}">'
    + _relationship("rId1", "officeDocument", "xl/workbook.xml")
    + "</Relationships>"
)
_WORKBOOK = (
    f'{_DECL}<workbook xmlns="{_SML_NS}" xmlns:r="{_OFFICE_REL}">'
    '<sheets><sheet name="Revenue" sheetId="1" r:id="rId1"/></sheets>'
    "</workbook>"
)
_WORKBOOK_RELS = (
    f'{_DECL}<Relationships xmlns="{_PKG_REL_NS}">'
    + _relationship("rId1", "worksheet", "worksheets/sheet1.xml")
    + _relationship("rId2", "sharedStrings", "sharedStrings.xml")
    + "</Relationships>"
)
_SHARED_STRINGS = (
    f'{_DECL}<sst xmlns="{_SML_NS}" count="3" uniqueCount="3">'
    "<si><t>Region</t></si><si><t>Revenue</t></si><si><t>APAC</t></si>"
    "</sst>"
)
# A1 "Region", B1 "Revenue" (shared strings); A2 "APAC" (shared), B2 1000000
# (number), B3 a formula cell whose cached value is 1250000. C2 is deliberately
# absent so a missing-cell failure path has something real to hit.
_SHEET = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
    '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>1000000</v></c></row>'
    '<row r="3"><c r="B3"><f>SUM(B2:B2)*1.25</f><v>1250000</v></c></row>'
    "</sheetData></worksheet>"
)


def write_xlsx(path: Path) -> None:
    parts = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _ROOT_RELS,
        "xl/workbook.xml": _WORKBOOK,
        "xl/_rels/workbook.xml.rels": _WORKBOOK_RELS,
        "xl/sharedStrings.xml": _SHARED_STRINGS,
        "xl/worksheets/sheet1.xml": _SHEET,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in parts.items():
            # Pinned mtime so rebuilding the fixture is a no-op in git.
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, body)


def write_pdf(path: Path, pages: tuple[str, ...]) -> None:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)


def main() -> None:
    (HERE / "sample.json").write_text(
        json.dumps(SAMPLE_JSON, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",  # git normalises to LF; without this a rebuild dirties the tree
    )
    write_xlsx(HERE / "sample.xlsx")
    write_pdf(HERE / "sample.pdf", ("SAFE SYNTHETIC PAGE ONE", "SAFE SYNTHETIC PAGE TWO"))
    (HERE / "corrupt.bin").write_bytes(b"not a document at all")


if __name__ == "__main__":
    main()
