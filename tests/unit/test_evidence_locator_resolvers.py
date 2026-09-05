"""Resolving EvidenceLocator v2 anchors against committed representation bytes.

Every failure path here is a real one: a page past the end, a sheet that is not
in the workbook, a pointer into a scalar, bytes that are not the format at all.
None of them may resolve to a plausible-looking guess.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
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
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "not a workbook")
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Revenue", cell="A1"), buffer.getvalue()
    )
    unresolved = expect_unresolved(result, FailureClass.EVIDENCE_BROKEN)
    assert "xl/workbook.xml" in unresolved.detail


def test_xlsx_workbook_part_that_is_not_xml_is_corrupt_source() -> None:
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<<< not xml")
    result = resolve_locator(
        locator(locatorKind="xlsx", sheet="Revenue", cell="A1"), buffer.getvalue()
    )
    expect_unresolved(result, FailureClass.CORRUPT_SOURCE)


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
