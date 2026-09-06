"""Resolving EvidenceLocator v2 anchors against committed representation bytes.

Every failure path here is a real one: a page past the end, a sheet that is not
in the workbook, a pointer into a scalar, bytes that are not the format at all.
None of them may resolve to a plausible-looking guess.
"""

from __future__ import annotations

import io
import warnings
import zipfile
from pathlib import Path
from typing import Any

import pytest
from akc_cir import evidence_locator_resolvers as resolvers
from akc_cir.base import sha256_digest
from akc_cir.evidence_locator import EVIDENCE_LOCATOR_SCHEMA, AnyEvidenceLocator, parse_locator
from akc_cir.evidence_locator_resolvers import (
    FailureClass,
    JsonLocatorResolver,
    PdfLocatorResolver,
    Resolved,
    Unresolved,
    XlsxLocatorResolver,
    resolve_locator,
)
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "evidence_locator"
BASE = {
    "schemaVersion": EVIDENCE_LOCATOR_SCHEMA,
    "sourceVersionId": "sv_0001",
    "representationId": "rep_0001",
}


def locator(**fields: Any) -> AnyEvidenceLocator:
    return parse_locator({**BASE, "locatorId": "loc_1", **fields})


@pytest.fixture(scope="module")
def pdf_bytes() -> bytes:
    return (FIXTURES / "sample.pdf").read_bytes()


@pytest.fixture(scope="module")
def xlsx_bytes() -> bytes:
    return (FIXTURES / "sample.xlsx").read_bytes()


@pytest.fixture(scope="module")
def json_bytes() -> bytes:
    return (FIXTURES / "sample.json").read_bytes()


@pytest.fixture(scope="module")
def junk_bytes() -> bytes:
    return (FIXTURES / "corrupt.bin").read_bytes()


def expect_unresolved(result: Any, reason: FailureClass) -> Unresolved:
    assert isinstance(result, Unresolved), result
    assert result.reason is reason, result
    assert result.detail
    return result


# --------------------------------------------------------------------------- pdf


def test_pdf_locator_resolves_the_page_it_names(pdf_bytes: bytes) -> None:
    result = resolve_locator(
        locator(locatorKind="pdf", page=2, bbox1000=[10, 10, 900, 100]), pdf_bytes
    )
    assert isinstance(result, Resolved)
    assert result.excerpt == "SAFE SYNTHETIC PAGE TWO"
    assert result.digest == sha256_digest("SAFE SYNTHETIC PAGE TWO")


def test_pdf_page_past_the_end_is_unresolved_not_clamped(pdf_bytes: bytes) -> None:
    result = resolve_locator(
        locator(locatorKind="pdf", page=9, bbox1000=[10, 10, 900, 100]), pdf_bytes
    )
    unresolved = expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)
    assert "2-page" in unresolved.detail


def test_pdf_bytes_that_are_not_a_pdf_are_corrupt_source(junk_bytes: bytes) -> None:
    resolve = resolve_locator(
        locator(locatorKind="pdf", page=1, bbox1000=[10, 10, 900, 100]), junk_bytes
    )
    expect_unresolved(resolve, FailureClass.CORRUPT_SOURCE)


def test_encrypted_pdf_is_reported_as_encrypted_not_broken() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("fixture-password")
    buffer = io.BytesIO()
    writer.write(buffer)
    result = resolve_locator(
        locator(locatorKind="pdf", page=1, bbox1000=[10, 10, 900, 100]), buffer.getvalue()
    )
    expect_unresolved(result, FailureClass.ENCRYPTED_SOURCE)


def test_a_page_with_no_extractable_text_is_empty_output_not_a_digest_of_nothing() -> None:
    """A scanned page extracts to ``''``; sha256('') is not evidence of anything.

    Every blank page of every document would otherwise share one digest, so a
    ``contentDigest`` receipt taken from one would verify against another.
    """
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    blank = buffer.getvalue()
    for page in (1, 2):
        result = resolve_locator(
            locator(locatorKind="pdf", page=page, bbox1000=[10, 10, 900, 100]), blank
        )
        unresolved = expect_unresolved(result, FailureClass.EMPTY_OUTPUT)
        assert str(page) in unresolved.detail
    borrowed_receipt = resolve_locator(
        locator(
            locatorKind="pdf",
            page=2,
            bbox1000=[10, 10, 900, 100],
            contentDigest=sha256_digest(""),
        ),
        blank,
    )
    expect_unresolved(borrowed_receipt, FailureClass.EMPTY_OUTPUT)


# -------------------------------------------------------------------------- json


@pytest.mark.parametrize(
    ("pointer", "excerpt"),
    [
        ("/report/title", '"Q3 revenue"'),
        ("/report/rows/1/region", '"EMEA"'),
        ("/report/rows/0/revenue", "1000000"),
        ("/a~1b", '"slash key"'),
        ("/m~0n", '"tilde key"'),
    ],
)
def test_json_pointer_resolves_an_exact_location(
    pointer: str, excerpt: str, json_bytes: bytes
) -> None:
    result = resolve_locator(locator(locatorKind="json", pointer=pointer), json_bytes)
    assert isinstance(result, Resolved)
    assert result.excerpt == excerpt


def test_empty_json_pointer_is_the_whole_document(json_bytes: bytes) -> None:
    result = resolve_locator(locator(locatorKind="json", pointer=""), json_bytes)
    assert isinstance(result, Resolved)
    assert result.excerpt.startswith('{"a/b":')


@pytest.mark.parametrize(
    "pointer",
    [
        "/report/missing",
        "/report/rows/9",
        "/report/rows/01",
        "/report/title/nested",
        "/report/rows/last",
    ],
)
def test_json_pointer_that_does_not_exist_is_unresolved(pointer: str, json_bytes: bytes) -> None:
    result = resolve_locator(locator(locatorKind="json", pointer=pointer), json_bytes)
    expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)


def test_json_bytes_that_do_not_parse_are_corrupt_source(junk_bytes: bytes) -> None:
    result = resolve_locator(locator(locatorKind="json", pointer="/report"), junk_bytes)
    expect_unresolved(result, FailureClass.CORRUPT_SOURCE)


def test_json_bytes_that_are_not_utf8_are_corrupt_source() -> None:
    result = resolve_locator(locator(locatorKind="json", pointer=""), b"\xff\xfe{}")
    expect_unresolved(result, FailureClass.CORRUPT_SOURCE)


# -------------------------------------------------------------------------- xlsx


@pytest.mark.parametrize(
    ("cell", "excerpt"),
    [("A1", "Region"), ("A2", "APAC"), ("B2", "1000000"), ("$B$3", "1250000")],
)
def test_xlsx_cell_resolves_through_shared_strings_and_cached_values(
    cell: str, excerpt: str, xlsx_bytes: bytes
) -> None:
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Revenue", cell=cell), xlsx_bytes
    )
    assert isinstance(result, Resolved)
    assert result.excerpt == excerpt


def test_xlsx_range_resolves_row_major(xlsx_bytes: bytes) -> None:
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Revenue", range="A1:B2"), xlsx_bytes
    )
    assert isinstance(result, Resolved)
    assert result.excerpt == "Region\tRevenue\nAPAC\t1000000"


def test_xlsx_missing_cell_is_unresolved(xlsx_bytes: bytes) -> None:
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Revenue", cell="C2"), xlsx_bytes
    )
    expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)


def test_xlsx_empty_range_is_unresolved(xlsx_bytes: bytes) -> None:
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Revenue", range="D10:E12"), xlsx_bytes
    )
    expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)


def test_xlsx_reversed_range_is_unresolved(xlsx_bytes: bytes) -> None:
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Revenue", range="B2:A1"), xlsx_bytes
    )
    expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)


def test_xlsx_oversized_range_is_refused_before_it_is_expanded(xlsx_bytes: bytes) -> None:
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Revenue", range="A1:Z9999"), xlsx_bytes
    )
    unresolved = expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)
    assert "4096" in unresolved.detail


def test_xlsx_sheet_that_is_not_in_the_workbook_is_unresolved(xlsx_bytes: bytes) -> None:
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Ledger", cell="A1"), xlsx_bytes
    )
    unresolved = expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)
    assert "Ledger" in unresolved.detail


def test_xlsx_bytes_that_are_not_a_package_are_corrupt_source(junk_bytes: bytes) -> None:
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Revenue", cell="A1"), junk_bytes
    )
    expect_unresolved(result, FailureClass.CORRUPT_SOURCE)


def test_xlsx_named_range_has_no_resolver_yet(xlsx_bytes: bytes) -> None:
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Revenue", namedRange="Totals"), xlsx_bytes
    )
    expect_unresolved(result, FailureClass.UNSUPPORTED_FORMAT)


def test_xlsx_package_without_a_workbook_part_is_unresolved() -> None:
    data = _ooxml_package({"xl/sharedStrings.xml": f'<sst xmlns="{_MAIN}"/>'})
    result = resolve_locator(locator(locatorKind="xlsx", sheet="Revenue", cell="A1"), data)
    unresolved = expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)
    assert "xl/workbook.xml" in unresolved.detail


def test_xlsx_workbook_part_that_is_not_xml_is_corrupt_source() -> None:
    data = _ooxml_package({"xl/workbook.xml": "<<< not xml"})
    result = resolve_locator(locator(locatorKind="xlsx", sheet="Revenue", cell="A1"), data)
    expect_unresolved(result, FailureClass.CORRUPT_SOURCE)


def test_xlsx_with_an_unsupported_zip_version_is_refused_not_a_crash(xlsx_bytes: bytes) -> None:
    """Two hostile bytes: the central directory's "version needed to extract".

    ``zipfile`` raises ``NotImplementedError`` for this, not ``BadZipFile``, so
    a resolver that guards only ``BadZipFile`` lets hostile bytes crash it.
    """
    blob = bytearray(xlsx_bytes)
    central = blob.rindex(b"PK\x01\x02")
    blob[central + 6] = 99  # version needed to extract = 9.9
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Revenue", cell="A1"), bytes(blob)
    )
    unresolved = expect_unresolved(result, FailureClass.CORRUPT_SOURCE)
    assert "NotImplementedError" in unresolved.detail


_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES = (
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/></Types>'
)
_ROOT_RELS = (
    f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" '
    f'Type="{_OFFICE_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
)


def _ooxml_package(parts: dict[str, str]) -> bytes:
    """A package the repo's archive guards accept, plus whatever ``parts`` say.

    Since the resolver runs ``akc_native_parsers.security.validate_source``
    first, a bare zip of one text file no longer reaches the workbook code at
    all — it is refused as a package. These tests are about what the *resolver*
    does with a well-formed package, so the base parts are the ones the guards
    require: ``[Content_Types].xml``, the root relationships and an ``xl/``
    member.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in {
            "[Content_Types].xml": _CONTENT_TYPES,
            "_rels/.rels": _ROOT_RELS,
            **parts,
        }.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def _minimal_xlsx(sheet_xml: str, shared_strings_xml: str) -> bytes:
    return _ooxml_package(
        {
            "xl/workbook.xml": (
                f'<workbook xmlns="{_MAIN}" xmlns:r="{_OFFICE_REL}"><sheets>'
                '<sheet name="Revenue" sheetId="1" r:id="rId1"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" '
                f'Type="{_OFFICE_REL}/worksheet" Target="worksheets/sheet1.xml"/>'
                "</Relationships>"
            ),
            "xl/worksheets/sheet1.xml": sheet_xml,
            "xl/sharedStrings.xml": shared_strings_xml,
        }
    )


@pytest.mark.parametrize("anchor", [{"cell": "A1"}, {"range": "A1:A1"}])
def test_a_cell_that_holds_an_empty_string_is_empty_output(anchor: dict[str, str]) -> None:
    """Present but empty is not absent, and it is not evidence either."""
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    data = _minimal_xlsx(
        f'<worksheet xmlns="{main}"><sheetData><row r="1">'
        '<c r="A1" t="s"><v>0</v></c><c r="B1"><v>7</v></c>'
        "</row></sheetData></worksheet>",
        f'<sst xmlns="{main}" count="1" uniqueCount="1"><si><t></t></si></sst>',
    )
    result = resolve_locator(locator(locatorKind="xlsx", sheet="Revenue", **anchor), data)
    unresolved = expect_unresolved(result, FailureClass.EMPTY_OUTPUT)
    assert "Revenue" in unresolved.detail
    # The same workbook still resolves a cell that does hold something.
    populated = resolve_locator(locator(locatorKind="xlsx", sheet="Revenue", cell="B1"), data)
    assert isinstance(populated, Resolved)
    assert populated.excerpt == "7"


# ---------------------------------------------------------------- dispatch + digest


def test_a_kind_without_a_resolver_is_unsupported_never_a_guess(json_bytes: bytes) -> None:
    result = resolve_locator(locator(locatorKind="docx", paragraphId="p-1"), json_bytes)
    unresolved = expect_unresolved(result, FailureClass.UNSUPPORTED_FORMAT)
    assert "docx" in unresolved.detail


def test_matching_content_digest_passes_through(json_bytes: bytes) -> None:
    digest = sha256_digest('"Q3 revenue"')
    result = resolve_locator(
        locator(locatorKind="json", pointer="/report/title", contentDigest=digest), json_bytes
    )
    assert isinstance(result, Resolved)
    assert result.digest == digest


def test_content_digest_that_disagrees_with_the_bytes_fails_closed(json_bytes: bytes) -> None:
    result = resolve_locator(
        locator(
            locatorKind="json", pointer="/report/title", contentDigest=f"sha256:{'0' * 64}"
        ),
        json_bytes,
    )
    expect_unresolved(result, FailureClass.RECEIPT_MISMATCH)


@pytest.mark.parametrize(
    ("resolver", "expected"),
    [
        (PdfLocatorResolver(), "pdf"),
        (JsonLocatorResolver(), "json"),
        (XlsxLocatorResolver(), "xlsx"),
    ],
)
def test_a_resolver_handed_the_wrong_variant_refuses_it(resolver: Any, expected: str) -> None:
    wrong = locator(locatorKind="xml", xpath="/a")
    result = resolver.resolve(wrong, b"")
    unresolved = expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)
    assert expected in unresolved.detail


# ------------------------------------------------- repair round 2 failure paths


def test_a_shadow_workbook_part_cannot_supply_evidence() -> None:
    """A duplicate ``xl/workbook.xml`` appended to a real workbook.

    ``zipfile`` reads whichever copy the central directory lists last, so the
    attacker's shadow workbook decides which sheets exist and where they live,
    while the genuine sheet reports ``EVIDENCE_BROKEN``. Every other door into
    this product refuses that package (``ARCHIVE_DUPLICATE_ENTRY``); the
    resolver must too, rather than resolving evidence out of a part no viewer
    would ever open.
    """
    buffer = io.BytesIO((FIXTURES / "sample.xlsx").read_bytes())
    with warnings.catch_warnings():  # zipfile warns about the duplicate name
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(buffer, "a", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "xl/workbook.xml",
                f'<workbook xmlns="{_MAIN}" xmlns:r="{_OFFICE_REL}"><sheets>'
                '<sheet name="Payroll" sheetId="9" r:id="rId9"/></sheets></workbook>',
            )
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId9" '
                f'Type="{_OFFICE_REL}/worksheet" Target="worksheets/shadow.xml"/>'
                "</Relationships>",
            )
            archive.writestr(
                "xl/worksheets/shadow.xml",
                f'<worksheet xmlns="{_MAIN}"><sheetData><row r="1">'
                '<c r="A1" t="inlineStr"><is><t>ATTACKER SUPPLIED</t></is></c>'
                "</row></sheetData></worksheet>",
            )
    tampered = buffer.getvalue()
    for sheet in ("Payroll", "Revenue"):
        result = resolve_locator(locator(locatorKind="xlsx", sheet=sheet, cell="A1"), tampered)
        unresolved = expect_unresolved(result, FailureClass.CORRUPT_SOURCE)
        assert "ARCHIVE_DUPLICATE_ENTRY" in unresolved.detail


def test_an_encrypted_package_member_is_encrypted_source_not_corruption() -> None:
    """The guards separate "cannot read" from "not allowed to read"."""
    data = bytearray(_minimal_xlsx(f'<worksheet xmlns="{_MAIN}"/>', f'<sst xmlns="{_MAIN}"/>'))
    for header in (b"PK\x03\x04", b"PK\x01\x02"):
        offset = data.index(header) + (6 if header == b"PK\x03\x04" else 8)
        data[offset] |= 0x01  # the general-purpose "encrypted" flag bit
    result = resolve_locator(locator(locatorKind="xlsx", sheet="Revenue", cell="A1"), bytes(data))
    unresolved = expect_unresolved(result, FailureClass.ENCRYPTED_SOURCE)
    assert "ARCHIVE_ENCRYPTED_ENTRY" in unresolved.detail


def test_a_sheet_the_workbook_relationships_do_not_name_is_evidence_broken() -> None:
    """`<sheet r:id="rId9">` with no rId9 in the rels part: the anchor is broken."""
    data = _ooxml_package(
        {
            "xl/workbook.xml": (
                f'<workbook xmlns="{_MAIN}" xmlns:r="{_OFFICE_REL}"><sheets>'
                '<sheet name="Revenue" sheetId="1" r:id="rId9"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" '
                f'Type="{_OFFICE_REL}/worksheet" Target="worksheets/sheet1.xml"/>'
                "</Relationships>"
            ),
            "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{_MAIN}"/>',
        }
    )
    result = resolve_locator(locator(locatorKind="xlsx", sheet="Revenue", cell="A1"), data)
    unresolved = expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)
    assert "no package relationship" in unresolved.detail


def test_a_package_part_over_the_resolver_limit_is_refused(
    monkeypatch: pytest.MonkeyPatch, xlsx_bytes: bytes
) -> None:
    """The 8 MiB per-part cap, exercised by lowering it rather than by shipping
    an 8 MiB fixture. The guard reads ``ZipInfo.file_size`` — the declared size,
    before any part is decompressed — so nothing here depends on the number."""
    monkeypatch.setattr(resolvers, "_MAX_PART_BYTES", 8)
    result = resolve_locator(locator(locatorKind="xlsx", sheet="Revenue", cell="A1"), xlsx_bytes)
    unresolved = expect_unresolved(result, FailureClass.CORRUPT_SOURCE)
    assert "over the resolver limit" in unresolved.detail


class _BrokenPageTree:
    """A ``PdfReader`` that constructs and then fails, as hostile PDFs do."""

    is_encrypted = False

    @property
    def pages(self) -> list[Any]:
        raise ValueError("page tree is a cycle")


class _BrokenContentStream:
    is_encrypted = False

    class _Page:
        def extract_text(self) -> str:
            raise ValueError("content stream is not decodable")

    @property
    def pages(self) -> list[Any]:
        return [self._Page()]


@pytest.mark.parametrize("reader", [_BrokenPageTree, _BrokenContentStream])
def test_a_pdf_that_fails_after_it_opens_is_corrupt_source_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, reader: type
) -> None:
    """``pypdf`` raises lazily: the reader opens, then the page tree or the
    content stream blows up. Both are ``CORRUPT_SOURCE``, never an exception
    out of ``resolve_locator``."""
    monkeypatch.setattr(resolvers, "PdfReader", lambda *_a, **_k: reader())
    result = resolve_locator(
        locator(locatorKind="pdf", page=1, bbox1000=[10, 10, 900, 100]), b"%PDF-1.7"
    )
    unresolved = expect_unresolved(result, FailureClass.CORRUPT_SOURCE)
    assert "ValueError" in unresolved.detail


def _pdf_with_one_text_run(body: str) -> bytes:
    writer = PdfWriter()
    font_reference = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
    )
    stream = DecodedStreamObject()
    stream.set_data(body.encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_a_page_whose_only_text_is_whitespace_is_empty_output() -> None:
    """Whitespace holds nothing, and it digests identically across documents.

    Two structurally different PDFs whose only text run is a single space
    resolved to the same digest before this guard, so a ``contentDigest``
    receipt taken from one verified against the other — the "receipt that
    proves nothing" the module refuses.
    """
    first = _pdf_with_one_text_run("BT /F1 12 Tf 10 100 Td ( ) Tj ET")
    second = _pdf_with_one_text_run("BT /F1 24 Tf 50 50 Td ( ) Tj ET")
    assert first != second  # different documents, identical extracted text
    for blob in (first, second):
        result = resolve_locator(
            locator(locatorKind="pdf", page=1, bbox1000=[10, 10, 900, 100]), blob
        )
        expect_unresolved(result, FailureClass.EMPTY_OUTPUT)
    borrowed_receipt = resolve_locator(
        locator(
            locatorKind="pdf",
            page=1,
            bbox1000=[10, 10, 900, 100],
            contentDigest=sha256_digest(" "),
        ),
        second,
    )
    expect_unresolved(borrowed_receipt, FailureClass.EMPTY_OUTPUT)


@pytest.mark.parametrize("anchor", [{"cell": "A1"}, {"range": "A1:A1"}])
def test_a_cell_that_holds_only_whitespace_is_empty_output(anchor: dict[str, str]) -> None:
    data = _minimal_xlsx(
        f'<worksheet xmlns="{_MAIN}"><sheetData><row r="1">'
        '<c r="A1" t="s"><v>0</v></c><c r="B1"><v>7</v></c>'
        '<c r="C1" t="inlineStr"><is><t>inline</t></is></c>'
        "</row></sheetData></worksheet>",
        f'<sst xmlns="{_MAIN}" count="1" uniqueCount="1">'
        '<si><t xml:space="preserve">   </t></si></sst>',
    )
    result = resolve_locator(locator(locatorKind="xlsx", sheet="Revenue", **anchor), data)
    expect_unresolved(result, FailureClass.EMPTY_OUTPUT)
    for cell, excerpt in (("B1", "7"), ("C1", "inline")):
        populated = resolve_locator(locator(locatorKind="xlsx", sheet="Revenue", cell=cell), data)
        assert isinstance(populated, Resolved)
        assert populated.excerpt == excerpt


def test_cells_the_sheet_cannot_supply_a_value_for_are_absent_not_guessed() -> None:
    """Every shape ``_cell_text`` gives up on lands in the one honest place: the
    cell is not in the map, so the anchor is ``EVIDENCE_BROKEN``. A boolean cell
    is the one shape that does resolve, and had no test."""
    data = _minimal_xlsx(
        f'<worksheet xmlns="{_MAIN}"><sheetData><row r="1">'
        '<c r="A1" t="inlineStr"></c>'  # inlineStr with no <is>
        '<c r="B1" t="s"></c>'  # shared string with no <v>
        '<c r="C1" t="s"><v>99</v></c>'  # shared index past the table
        '<c t="b"><v>1</v></c>'  # no cell reference at all
        '<c r="E1" t="b"><v>1</v></c>'
        "</row></sheetData></worksheet>",
        f'<sst xmlns="{_MAIN}" count="1" uniqueCount="1"><si><t>only</t></si></sst>',
    )
    for reference in ("A1", "B1", "C1", "D1"):
        result = resolve_locator(
            locator(locatorKind="xlsx", sheet="Revenue", cell=reference), data
        )
        expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)
    boolean = resolve_locator(locator(locatorKind="xlsx", sheet="Revenue", cell="E1"), data)
    assert isinstance(boolean, Resolved)
    assert boolean.excerpt == "TRUE"


def test_a_range_endpoint_that_is_not_an_a1_reference_is_refused() -> None:
    """Unreachable through ``resolve_locator`` — ``A1Range`` pins the same
    pattern the helper re-checks — so the guard is tested where it lives. It
    stays because the day the two patterns drift, this is the branch that
    decides between ``Unresolved`` and a wrong cell."""
    with pytest.raises(resolvers._XlsxError) as raised:
        resolvers._range_references("ZZZZ1", "A1")
    assert raised.value.reason is FailureClass.EVIDENCE_BROKEN
