"""Native Office readers (lane C-2): registration, locator truth, fail-closed.

Every hostile case runs through ``ReaderRegistry.read`` rather than the provider
directly, because "refused" is only a product fact if the path a caller uses
refuses it.
"""

from __future__ import annotations

import hashlib
import io
import struct
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest
from akc_native_parsers.models import StructuredParseError
from akc_readers import (
    CapabilityStatus,
    FailureClass,
    NativeDocxV1,
    NativePptxV1,
    NativeXlsxV1,
    ReaderFeature,
    ReaderInput,
    ReaderRegistrationError,
    ReaderRegistry,
    inspect_source,
    validate_evidence_locator,
)
from akc_readers.office import (
    DOCX_MIME,
    PPTX_MIME,
    XLSX_MIME,
    _NativeOfficeV1,
    probe_docx_bytes,
    probe_pptx_bytes,
    probe_xlsx_bytes,
)

from tests.fixtures.build_safe_fixture_matrix import (
    _write_bounded_compression_fixture,
    _write_external_relationship_fixture,
)

PROVIDERS: tuple[type[_NativeOfficeV1], ...] = (NativeXlsxV1, NativeDocxV1, NativePptxV1)


def _input(
    data: bytes,
    *,
    filename: str,
    declared_mime: str,
) -> ReaderInput:
    return ReaderInput(
        source_version_id="sv-office-0001",
        tenant_id="tenant-office",
        representation_id="rep-office-0001",
        filename=filename,
        declared_mime=declared_mime,
        content_sha256="sha256:" + hashlib.sha256(data).hexdigest(),
        data=data,
    )


def _registry() -> ReaderRegistry:
    registry = ReaderRegistry()
    for provider in PROVIDERS:
        registry.register(provider())
    return registry


def _probe_input(provider: _NativeOfficeV1) -> ReaderInput:
    return provider.probe_samples()[0]


def _macro_enabled_xlsx() -> bytes:
    """An OOXML spreadsheet package carrying a VBA project part.

    Inert bytes: the part is a marker, not a macro. `validate_source()` refuses
    the package on the part's name, which is the behaviour under test.
    """
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"/>',
        )
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships/>')
        archive.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook/>')
        archive.writestr("xl/vbaProject.bin", b"\x00inert-marker\x00")
    return payload.getvalue()


def _malformed_docx_part() -> bytes:
    """A well-formed OOXML package whose main document part is not XML."""
    source = probe_docx_bytes()
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(source)) as original,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in original.infolist():
            payload = original.read(info.filename)
            if info.filename == "word/document.xml":
                payload = b"this part is not xml"
            target.writestr(info.filename, payload)
    return out.getvalue()


def _password_protected_office() -> bytes:
    """MS-OFFCRYPTO signature bytes, not a real encrypted Office file.

    A password-protected .docx is an OLE/CFB container, never a ZIP. These bytes
    carry the CFB magic and the UTF-16LE ``EncryptedPackage`` directory name a
    real one carries; nothing else about them is claimed to be genuine. Real
    encrypted fixtures belong to the P1-B qualification suite (contract §8.1).
    """
    return (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        + b"\x00" * 500
        + "EncryptedPackage".encode("utf-16-le")
        + b"\x00" * 100
    )


# -- byte-level hostile OOXML packages ---------------------------------
#
# Every fixture below is `probe_docx_bytes()` with a few bytes of
# `word/document.xml` rewritten, so the package is a real DOCX in every other
# respect and the only thing under test is what happens when a member cannot be
# decompressed. Before the guard in `akc_native_parsers.security._read_member`,
# each of these left the reader plane as a raw `zipfile`/`zlib` exception rather
# than as a receipt: `_malformed_docx_part()` above only covers a member that
# decompresses cleanly and then fails to parse as XML.

_DOCUMENT_PART = b"word/document.xml"


def _local_headers(data: bytes, name: bytes) -> list[int]:
    offsets, cursor = [], 0
    while (index := data.find(b"PK\x03\x04", cursor)) >= 0:
        length = struct.unpack_from("<H", data, index + 26)[0]
        if data[index + 30 : index + 30 + length] == name:
            offsets.append(index)
        cursor = index + 4
    return offsets


def _central_headers(data: bytes, name: bytes) -> list[int]:
    offsets, cursor = [], 0
    while (index := data.find(b"PK\x01\x02", cursor)) >= 0:
        length = struct.unpack_from("<H", data, index + 28)[0]
        if data[index + 46 : index + 46 + length] == name:
            offsets.append(index)
        cursor = index + 4
    return offsets


def _local_name_mismatch() -> bytes:
    """The local header names a member the central directory does not."""
    data = bytearray(probe_docx_bytes())
    for offset in _local_headers(bytes(data), _DOCUMENT_PART):
        start = offset + 30
        data[start : start + len(_DOCUMENT_PART)] = b"word/documenX.xml"
    return bytes(data)


def _unsupported_compression_method() -> bytes:
    """Method 20 (deflate64/zstd territory) — declared, not implemented."""
    data = bytearray(probe_docx_bytes())
    for offset in _local_headers(bytes(data), _DOCUMENT_PART):
        struct.pack_into("<H", data, offset + 8, 20)
    for offset in _central_headers(bytes(data), _DOCUMENT_PART):
        struct.pack_into("<H", data, offset + 10, 20)
    return bytes(data)


def _corrupted_deflate_stream() -> bytes:
    """35 flipped bytes inside the member's compressed payload."""
    data = bytearray(probe_docx_bytes())
    offset = _local_headers(bytes(data), _DOCUMENT_PART)[0]
    name_length = struct.unpack_from("<H", data, offset + 26)[0]
    extra_length = struct.unpack_from("<H", data, offset + 28)[0]
    start = offset + 30 + name_length + extra_length
    for index in range(start + 5, start + 40):
        data[index] ^= 0xFF
    return bytes(data)


def _central_directory_size_lie() -> bytes:
    """The central directory understates the member's uncompressed size.

    `ZipFile.read` then stops short of the deflate stream's end and the CRC it
    computes is not the one recorded — `BadZipFile("Bad CRC-32 ...")`.
    """
    data = bytearray(probe_docx_bytes())
    for offset in _central_headers(bytes(data), _DOCUMENT_PART):
        struct.pack_into("<I", data, offset + 24, 10)
    return bytes(data)



# -- registration ------------------------------------------------------


def test_registry_accepts_all_three_native_office_readers() -> None:
    entries = {entry.reader_id for entry in _registry().entries()}
    assert entries == {"native_xlsx_v1", "native_docx_v1", "native_pptx_v1"}


@pytest.mark.parametrize("provider_type", PROVIDERS)
def test_each_provider_declares_one_concrete_mime_and_claims_no_qualification(
    provider_type: type[_NativeOfficeV1],
) -> None:
    capabilities = provider_type().capabilities()
    assert len(capabilities) == 1
    capability = capabilities[0]
    assert len(capability.mime_patterns) == 1
    assert "*" not in capability.mime_patterns[0]
    assert capability.mime_patterns[0] in {XLSX_MIME, DOCX_MIME, PPTX_MIME}
    assert capability.qualification_status is CapabilityStatus.BEST_EFFORT
    assert capability.qualification_receipt is None
    assert capability.qualification_receipt_path is None


@pytest.mark.parametrize(
    ("provider_type", "over_declared"),
    [
        (NativeDocxV1, ReaderFeature.FORMULA),
        (NativeDocxV1, ReaderFeature.LAYOUT),
        (NativeXlsxV1, ReaderFeature.LAYOUT),
        (NativePptxV1, ReaderFeature.FORMULA),
    ],
)
def test_over_declaration_is_refused_at_registration(
    provider_type: type[_NativeOfficeV1],
    over_declared: ReaderFeature,
) -> None:
    class _OverDeclaring(provider_type):  # type: ignore[valid-type,misc]
        def capabilities(self) -> tuple[object, ...]:  # type: ignore[override]
            base = super().capabilities()[0]
            return (base.model_copy(update={"features": (*base.features, over_declared)}),)

    with pytest.raises(ReaderRegistrationError, match="did not produce"):
        ReaderRegistry().register(_OverDeclaring())


def test_a_feature_the_extraction_model_cannot_witness_is_refused() -> None:
    """`comments`/`track_changes`/`chart_data` are produced by the wrapped
    parsers but carried by no `ExtractedUnit` field, so they stay undeclared."""

    class _ClaimsComments(NativeDocxV1):
        def capabilities(self) -> tuple[object, ...]:  # type: ignore[override]
            base = super().capabilities()[0]
            return (base.model_copy(update={"features": (*base.features, ReaderFeature.COMMENTS)}),)

    with pytest.raises(ReaderRegistrationError, match="cannot witness"):
        ReaderRegistry().register(_ClaimsComments())


@pytest.mark.parametrize("builder", [probe_xlsx_bytes, probe_docx_bytes, probe_pptx_bytes])
def test_probe_samples_are_byte_deterministic(builder: Callable[[], bytes]) -> None:
    assert builder() == builder()


# -- locator truth -----------------------------------------------------


@pytest.mark.parametrize("provider_type", PROVIDERS)
def test_every_emitted_locator_validates_and_binds_to_the_source(
    provider_type: type[_NativeOfficeV1],
) -> None:
    provider = provider_type()
    source = _probe_input(provider)
    output, receipt = _registry().read(source)
    assert receipt.accepted is True
    assert output is not None
    assert output.provider_id == provider.provider_id

    locators = [unit.locator for unit in output.units if unit.locator is not None]
    assert locators, "the probe must exercise at least one locator"
    assert list(provider.emit_evidence_locators(output)) == locators
    for locator in locators:
        validate_evidence_locator(locator)
        assert locator["locatorKind"] == provider.locator_kind.value
        assert locator["sourceVersionId"] == source.source_version_id
        assert locator["representationId"] == source.representation_id


def test_xlsx_units_carry_sheet_anchored_cell_range_and_formula_evidence() -> None:
    provider = NativeXlsxV1()
    output = provider.extract_native(_probe_input(provider))
    anchors = {
        unit.locator["cell"]: unit for unit in output.units if (unit.locator or {}).get("cell")
    }
    assert set(anchors) == {"A1", "B1", "C1", "A2", "B2", "C2"}
    assert all(unit.locator["sheet"] == "Probe" for unit in anchors.values())
    assert anchors["C2"].formula == "=B2*2"
    assert anchors["A1"].formula is None
    assert all(unit.table_id for unit in anchors.values())
    ranges = [unit.locator["range"] for unit in output.units if (unit.locator or {}).get("range")]
    assert ranges == ["A1:C2"]


def test_docx_table_cells_carry_table_and_cell_ids() -> None:
    provider = NativeDocxV1()
    output = provider.extract_native(_probe_input(provider))
    cells = [unit for unit in output.units if (unit.locator or {}).get("cellId")]
    assert len(cells) == 4
    assert {unit.locator["tableId"] for unit in cells} == {"docx/body/table/000001"}
    assert {unit.locator["cellId"] for unit in cells} == {
        "r/000000/c/000000",
        "r/000000/c/000001",
        "r/000001/c/000000",
        "r/000001/c/000001",
    }
    paragraphs = [
        unit.locator["paragraphId"]
        for unit in output.units
        if (unit.locator or {}).get("paragraphId")
    ]
    assert paragraphs == ["docx/body/p/000000"]


def test_pptx_units_carry_slide_numbers_shape_ids_and_layout() -> None:
    provider = NativePptxV1()
    output = provider.extract_native(_probe_input(provider))
    assert all(unit.locator is not None for unit in output.units)
    assert {unit.locator["slideNumber1"] for unit in output.units} == {1}
    assert any("shapeId" in unit.locator for unit in output.units)
    assert all(unit.bbox1000 is not None for unit in output.units)


@pytest.mark.parametrize(
    ("provider_type", "native_object_id", "index"),
    [
        # A worksheet as a whole has no v2 anchor: the variant needs a cell,
        # range, named range, table or chart.
        (NativeXlsxV1, "xlsx/sheet/0000", {0: "Probe"}),
        # An embedded image is addressable by none of them either.
        (NativeXlsxV1, "xlsx/sheet/0000/image/0000", {0: "Probe"}),
        # A sheet the parser's own metadata does not list is not guessed at.
        (NativeXlsxV1, "xlsx/sheet/0007/cell/A1", {0: "Probe"}),
        # A DOCX table as a whole needs tableId *and* cellId.
        (NativeDocxV1, "docx/body/table/000001", {}),
        # A drawing is not a paragraph.
        (NativeDocxV1, "docx/body/p/000003/drawing/0000", {}),
        # A slide the presentation metadata does not list is not guessed at.
        (NativePptxV1, "pptx/slide/0009/shape/0000", {0: ""}),
    ],
)
def test_an_unmappable_native_object_id_yields_no_locator(
    provider_type: type[_NativeOfficeV1],
    native_object_id: str,
    index: dict[int, str],
) -> None:
    assert provider_type()._anchor(native_object_id, index) is None


def test_a_unit_without_a_native_object_id_yields_no_locator() -> None:
    provider = NativeXlsxV1()
    source = _probe_input(provider)
    assert provider._locator(source, "unit-0001", None, {0: "Probe"}) is None


def test_the_probe_output_actually_contains_an_unmappable_unit() -> None:
    """The negative path is exercised by real output, not only by a unit test.

    The XLSX sheet heading and the DOCX table block are both real CIR blocks
    with no EvidenceLocator v2 anchor; they are emitted with their text and
    without a locator rather than dropped or anchored to a neighbour.
    """
    xlsx = NativeXlsxV1()
    sheet_headings = [
        unit for unit in xlsx.extract_native(_probe_input(xlsx)).units if unit.text == "Probe"
    ]
    assert len(sheet_headings) == 1
    assert sheet_headings[0].locator is None

    docx = NativeDocxV1()
    table_blocks = [
        unit
        for unit in docx.extract_native(_probe_input(docx)).units
        if unit.table_id is not None and unit.unit_id.startswith("blk_")
    ]
    assert len(table_blocks) == 1
    assert table_blocks[0].locator is None


# -- content decides, the filename and the declared MIME do not --------


def test_a_content_detected_xlsx_named_report_bin_is_read() -> None:
    source = _input(
        probe_xlsx_bytes(), filename="report.bin", declared_mime="application/octet-stream"
    )
    output, receipt = _registry().read(source)
    assert receipt.accepted is True
    assert receipt.provider_id == "native_xlsx_v1"
    assert output is not None
    assert any((unit.locator or {}).get("cell") == "A1" for unit in output.units)


def test_a_declared_mime_that_lies_does_not_decide_the_reader() -> None:
    source = _input(probe_docx_bytes(), filename="deck.pptx", declared_mime=XLSX_MIME)
    inspection = inspect_source(source)
    assert inspection.detected_mime == DOCX_MIME
    assert NativeXlsxV1().can_read(source, inspection) is False
    assert NativePptxV1().can_read(source, inspection) is False
    assert NativeDocxV1().can_read(source, inspection) is True

    output, receipt = _registry().read(source)
    assert receipt.accepted is True
    assert receipt.provider_id == "native_docx_v1"
    assert output is not None


def test_a_provider_handed_another_formats_bytes_refuses_rather_than_parses() -> None:
    """`extract_native` is public, so `can_read` cannot be the only gate.

    Without the check inside `extract_native`, a caller reaching past the
    registry would get presentation content back under the spreadsheet reader's
    provider id — a receipt naming a reader that did not read that format.
    """
    presentation = _input(probe_pptx_bytes(), filename="book.xlsx", declared_mime=XLSX_MIME)
    with pytest.raises(StructuredParseError) as raised:
        NativeXlsxV1().extract_native(presentation)
    assert raised.value.code == "MIME_MISMATCH"

    # Through the registry the same bytes reach the reader whose format they are.
    output, receipt = _registry().read(presentation)
    assert receipt.accepted is True
    assert receipt.provider_id == "native_pptx_v1"
    assert output is not None
    assert output.provider_id == "native_pptx_v1"

    # And with no Office reader registered at all, the source is unsupported
    # rather than force-fitted to a reader that declares another MIME.
    _, refusal = ReaderRegistry().read(presentation)
    assert refusal.accepted is False
    assert refusal.failure_class is FailureClass.UNSUPPORTED_FORMAT


# -- hostile input -----------------------------------------------------


def test_a_zip_bomb_office_package_is_refused_not_partially_extracted(
    tmp_path: Path,
) -> None:
    target = tmp_path / "bomb.docx"
    _write_bounded_compression_fixture(target)
    output, receipt = _registry().read(
        _input(target.read_bytes(), filename="bomb.docx", declared_mime=DOCX_MIME)
    )
    assert output is None
    assert receipt.accepted is False
    assert receipt.failure_class is FailureClass.MALWARE_QUARANTINED


def test_an_external_relationship_is_refused_not_partially_extracted(
    tmp_path: Path,
) -> None:
    target = tmp_path / "external.docx"
    _write_external_relationship_fixture(target)
    output, receipt = _registry().read(
        _input(target.read_bytes(), filename="external.docx", declared_mime=DOCX_MIME)
    )
    assert output is None
    assert receipt.accepted is False
    assert receipt.failure_class is FailureClass.MALWARE_QUARANTINED


def test_macro_enabled_bytes_are_refused_not_partially_extracted() -> None:
    output, receipt = _registry().read(
        _input(_macro_enabled_xlsx(), filename="budget.xlsx", declared_mime=XLSX_MIME)
    )
    assert output is None
    assert receipt.accepted is False
    assert receipt.failure_class is FailureClass.MALWARE_QUARANTINED


def test_a_malformed_main_part_is_refused_not_partially_extracted() -> None:
    output, receipt = _registry().read(
        _input(_malformed_docx_part(), filename="memo.docx", declared_mime=DOCX_MIME)
    )
    assert output is None
    assert receipt.accepted is False
    assert receipt.failure_class is FailureClass.CORRUPT_SOURCE


def test_a_password_protected_office_container_is_locked_not_corrupt() -> None:
    source = _input(_password_protected_office(), filename="salary.docx", declared_mime=DOCX_MIME)
    inspection = inspect_source(source)
    assert inspection.encrypted is True
    assert inspection.corrupted is False

    output, receipt = _registry().read(source)
    assert output is None
    assert receipt.accepted is False
    assert receipt.failure_class is FailureClass.ENCRYPTED_SOURCE


def test_a_docx_footnote_becomes_a_unit_with_a_footnote_locator() -> None:
    """Lane C-3 fidelity gap: footnotes were not extracted at all.

    A footnote carries the sentence's source, so dropping it makes a claim look
    unsourced. The locator variant already had a ``footnoteId`` anchor; nothing
    produced an id for it. Word's separator and continuation footnotes are
    layout furniture and stay out of the unit stream.
    """
    corpus = Path(__file__).resolve().parents[1] / "fixtures/office_corpus/docx/08-footnotes.docx"
    output = NativeDocxV1().extract_native(
        _input(corpus.read_bytes(), filename="08-footnotes.docx", declared_mime=DOCX_MIME)
    )
    footnotes = [
        unit for unit in output.units if unit.locator and "footnoteId" in unit.locator
    ]
    assert [unit.text for unit in footnotes] == ["Source: the internal revenue ledger."]
    assert footnotes[0].locator is not None
    assert footnotes[0].locator["footnoteId"] == "2"
    validate_evidence_locator(footnotes[0].locator)


@pytest.mark.parametrize(
    ("case", "builder"),
    [
        ("local/central filename mismatch", _local_name_mismatch),
        ("unsupported compression method", _unsupported_compression_method),
        ("corrupted deflate stream", _corrupted_deflate_stream),
        ("central-directory size lie", _central_directory_size_lie),
    ],
)
def test_an_undecompressable_package_member_is_a_receipt_not_an_exception(
    case: str,
    builder: Callable[[], bytes],
) -> None:
    """G-C5: hostile input leaves the reader plane classified, never raised.

    Each of these four packages passes every structural check the validator
    makes from the ZIP directory alone and only fails when a member is actually
    decompressed. `ReaderRegistry.read()` calls `inspect_source()` outside its
    own `try`, so an exception raised there is not caught anywhere: a caller got
    a traceback where the contract promises a `FailureClass`.
    """
    payload = builder()
    output, receipt = _registry().read(
        _input(payload, filename="memo.docx", declared_mime=DOCX_MIME)
    )
    assert output is None
    assert receipt.accepted is False
    assert receipt.failure_class is FailureClass.CORRUPT_SOURCE, case

    # And the inspector itself — the half of the path that is outside the
    # registry's exception handling — describes the source rather than raising.
    inspection = inspect_source(_input(payload, filename="memo.docx", declared_mime=DOCX_MIME))
    assert inspection.corrupted is True
    assert "INVALID_OFFICE_ARCHIVE" in inspection.review_reasons


def test_the_inspector_never_raises_even_for_an_unclassified_scan_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second boundary, exercised directly.

    `_read_member` classifies every decompression failure the current library
    set produces, so nothing reaches the inspector's non-`StructuredParseError`
    branch today. That branch is what keeps "inspect_source never raises" true
    of a *future* scan failure as well, and an unexercised promise is not one.
    """

    def _raise(**_: object) -> None:
        raise zlib.error("invalid code lengths set")

    monkeypatch.setattr("akc_readers.inspector.validate_source", _raise)
    inspection = inspect_source(
        _input(probe_docx_bytes(), filename="memo.docx", declared_mime=DOCX_MIME)
    )
    assert inspection.corrupted is True
    assert "ARCHIVE_MEMBER_UNREADABLE:error" in inspection.review_reasons


def test_a_blank_layout_slide_emits_no_text_the_package_does_not_contain() -> None:
    """Synthesised text never leaves the reader with a locator and a bbox.

    A slide with no title placeholder gets an invented heading from the pptx
    parser (`Slide 3`), flagged `slide_title_inferred`. The flag does not
    survive into `ExtractedUnit`, so a caller who saw that unit would read text
    that is in no part of the package, anchored to `slideNumber1` and boxed at
    the whole slide — a fabricated locator and bbox for source that does not
    exist. `probe_pptx_bytes()` is a Blank-layout slide, so it is exactly that
    case.
    """
    payload = probe_pptx_bytes()
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        slide_xml = b"".join(
            package.read(name)
            for name in package.namelist()
            if name.startswith("ppt/slides/slide")
        ).decode("utf-8")
    assert "Slide" not in slide_xml

    output = NativePptxV1().extract_native(
        _input(payload, filename="deck.pptx", declared_mime=PPTX_MIME)
    )
    assert output.units
    for unit in output.units:
        for token in unit.text.split():
            assert token in slide_xml, (
                f"{unit.unit_id} reports {unit.text!r}, which the slide XML does not contain"
            )
