"""Reader plane: inspection, capability resolution, receipts, failure paths."""

from __future__ import annotations

import hashlib
import inspect as inspect_module
import io
import time
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

import jsonschema
import pytest
from akc_readers import (
    CapabilityStatus,
    FailureClass,
    LegacyPdfV1,
    NativeExtraction,
    PlainTextV1,
    ReaderCapability,
    ReaderFeature,
    ReaderHealth,
    ReaderInput,
    ReaderRegistrationError,
    ReaderRegistry,
    ReaderRegistryEntry,
    ReaderRegistryStatus,
    SourceFamily,
    SourceInspection,
    digest_units,
    inspect_source,
    validate_evidence_locator,
)
from pydantic import ValidationError

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _input(
    data: bytes,
    *,
    filename: str,
    declared_mime: str,
    content_sha256: str | None = None,
) -> ReaderInput:
    return ReaderInput(
        source_version_id="sv-test-0001",
        tenant_id="tenant-test",
        representation_id="rep-test-0001",
        filename=filename,
        declared_mime=declared_mime,
        content_sha256=content_sha256 or "sha256:" + hashlib.sha256(data).hexdigest(),
        data=data,
    )


def _docx_bytes() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"/>',
        )
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships/>')
        archive.writestr("word/document.xml", '<?xml version="1.0"?><document/>')
    return payload.getvalue()


def _mark_zip_entries_encrypted(data: bytes) -> bytes:
    """Set the ZIP general-purpose encryption bit in both header copies."""
    patched = bytearray(data)
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while (index := patched.find(signature, start)) != -1:
            patched[index + flag_offset : index + flag_offset + 2] = b"\x01\x00"
            start = index + 4
    return bytes(patched)


def _registry() -> ReaderRegistry:
    registry = ReaderRegistry()
    registry.register(PlainTextV1())
    registry.register(LegacyPdfV1())
    return registry


# -- inspector ----------------------------------------------------------


def test_inspector_ignores_the_extension_and_reads_the_magic_bytes() -> None:
    inspection = inspect_source(
        _input(
            LegacyPdfV1().probe_samples()[0].data,
            filename="invoice.txt",
            declared_mime="text/plain",
        )
    )
    assert inspection.detected_mime == "application/pdf"
    assert inspection.source_family is SourceFamily.DOCUMENT
    assert inspection.page_like_units == 1
    assert "DECLARED_MIME_MISMATCH" in inspection.review_reasons


def test_inspector_identifies_an_ooxml_package_by_its_internal_structure() -> None:
    inspection = inspect_source(_docx_input())
    assert inspection.detected_mime == DOCX_MIME
    assert inspection.container_kind == "docx"
    assert inspection.source_family is SourceFamily.DOCUMENT


def _docx_input() -> ReaderInput:
    return _input(_docx_bytes(), filename="memo.docx", declared_mime=DOCX_MIME)


def test_truncated_ooxml_is_review_required_not_a_crash() -> None:
    truncated = _docx_bytes()[:-200]
    inspection = inspect_source(_input(truncated, filename="memo.docx", declared_mime=DOCX_MIME))
    assert inspection.corrupted is True
    assert "ZIP_TRUNCATED" in inspection.review_reasons
    resolution = _registry().resolve(inspection)
    assert resolution.status is CapabilityStatus.REVIEW_REQUIRED
    assert resolution.failure_class is FailureClass.CORRUPT_SOURCE
    assert resolution.provider_id is None


def test_encrypted_ooxml_is_review_required_not_a_crash() -> None:
    encrypted = _mark_zip_entries_encrypted(_docx_bytes())
    inspection = inspect_source(_input(encrypted, filename="memo.docx", declared_mime=DOCX_MIME))
    assert inspection.encrypted is True
    assert "ARCHIVE_ENCRYPTED_ENTRY" in inspection.review_reasons
    resolution = _registry().resolve(inspection)
    assert resolution.status is CapabilityStatus.REVIEW_REQUIRED
    assert resolution.failure_class is FailureClass.ENCRYPTED_SOURCE


def test_unknown_binary_is_described_not_raised() -> None:
    inspection = inspect_source(_input(b"\x00\x01\x02\x03", filename="x.bin", declared_mime=""))
    assert inspection.detected_mime == "application/octet-stream"
    assert inspection.source_family is SourceFamily.UNKNOWN
    assert "UNRECOGNIZED_BINARY" in inspection.review_reasons


# -- resolution ---------------------------------------------------------


def test_unknown_mime_resolves_to_unsupported() -> None:
    png = _input(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, filename="s.png", declared_mime="image/png")
    inspection = inspect_source(png)
    resolution = _registry().resolve(inspection)
    assert resolution.status is CapabilityStatus.UNSUPPORTED
    assert resolution.failure_class is FailureClass.UNSUPPORTED_FORMAT

    output, receipt = _registry().read(png, inspection=inspection)
    assert output is None
    assert receipt.accepted is False
    assert receipt.failure_class is FailureClass.UNSUPPORTED_FORMAT


def test_a_required_feature_no_reader_declares_resolves_to_unsupported() -> None:
    source = _input(b"# Title\n\nBody.\n", filename="notes.md", declared_mime="text/markdown")
    inspection = inspect_source(source)
    assert _registry().resolve(inspection).provider_id == "plain_text_v1"
    refused = _registry().resolve(inspection, required_features=[ReaderFeature.TABLES])
    assert refused.status is CapabilityStatus.UNSUPPORTED
    assert refused.provider_id is None


def test_the_registry_offers_no_way_to_resolve_by_provider_name() -> None:
    name_like = {"provider_id", "reader_id", "model", "model_name", "name", "provider_name"}
    for attribute in dir(ReaderRegistry):
        if attribute.startswith("_"):
            continue
        member = getattr(ReaderRegistry, attribute)
        if not callable(member):
            continue
        parameters = set(inspect_module.signature(member).parameters)
        assert not (parameters & name_like), f"{attribute} accepts a name-keyed lookup"


# -- providers ----------------------------------------------------------


def test_plain_text_units_carry_byte_ranges_that_address_the_real_bytes() -> None:
    data = b"First paragraph.\n\nSecond paragraph.\n"
    source = _input(data, filename="notes.txt", declared_mime="text/plain")
    output = PlainTextV1().extract_native(source)
    assert [unit.text for unit in output.units] == ["First paragraph.", "Second paragraph."]
    for unit in output.units:
        assert unit.byte_range is not None
        start, end = unit.byte_range
        assert data[start:end].decode().strip() == unit.text


def test_plain_text_emits_no_locator_because_the_frozen_kinds_have_no_text_variant() -> None:
    source = _input(b"Only paragraph.\n", filename="notes.txt", declared_mime="text/plain")
    provider = PlainTextV1()
    assert provider.emit_evidence_locators(provider.extract_native(source)) == ()


def test_legacy_pdf_locators_validate_against_the_frozen_schema() -> None:
    provider = LegacyPdfV1()
    sample = provider.probe_samples()[0]
    locators = provider.emit_evidence_locators(provider.extract_native(sample))
    assert locators
    for locator in locators:
        validate_evidence_locator(locator)
        assert locator["locatorKind"] == "pdf"
        assert locator["page"] >= 1


def test_a_locator_missing_its_anchor_is_rejected_by_the_frozen_schema() -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_evidence_locator(
            {
                "schemaVersion": "tavonel.evidence_locator.v2",
                "locatorId": "loc-1",
                "sourceVersionId": "sv-1",
                "representationId": "rep-1",
                "locatorKind": "pdf",
                "page": 1,
            }
        )


def test_a_verified_tier_without_a_qualification_receipt_is_refused() -> None:
    with pytest.raises(ValidationError, match="qualification receipt"):
        ReaderCapability(
            mime_patterns=("application/pdf",),
            source_families=(SourceFamily.DOCUMENT,),
            features=(ReaderFeature.NATIVE_TEXT,),
            qualification_status=CapabilityStatus.VERIFIED_NATIVE,
        )


def test_no_p0_provider_claims_a_verified_tier() -> None:
    for provider in (PlainTextV1(), LegacyPdfV1()):
        for capability in provider.capabilities():
            assert capability.qualification_status is CapabilityStatus.BEST_EFFORT
            assert capability.qualification_receipt is None


# -- registration probe -------------------------------------------------


class _OverclaimingPdf(LegacyPdfV1):
    provider_id = "overclaiming_pdf_v1"

    def capabilities(self) -> tuple[ReaderCapability, ...]:
        return (
            ReaderCapability(
                mime_patterns=("application/pdf",),
                source_families=(SourceFamily.DOCUMENT,),
                features=(ReaderFeature.NATIVE_TEXT, ReaderFeature.LAYOUT, ReaderFeature.TABLES),
                qualification_status=CapabilityStatus.BEST_EFFORT,
            ),
        )


class _UnprobeablePdf(LegacyPdfV1):
    provider_id = "unprobeable_pdf_v1"

    def capabilities(self) -> tuple[ReaderCapability, ...]:
        return (
            ReaderCapability(
                mime_patterns=("application/pdf",),
                source_families=(SourceFamily.DOCUMENT,),
                features=(ReaderFeature.TRACK_CHANGES,),
                qualification_status=CapabilityStatus.BEST_EFFORT,
            ),
        )


def test_a_provider_declaring_tables_it_cannot_produce_is_refused() -> None:
    with pytest.raises(ReaderRegistrationError, match="probe did not produce: tables"):
        ReaderRegistry().register(_OverclaimingPdf())


def test_a_feature_the_registry_cannot_witness_is_refused() -> None:
    with pytest.raises(ReaderRegistrationError, match="cannot witness: track_changes"):
        ReaderRegistry().register(_UnprobeablePdf())


def test_duplicate_registration_is_refused() -> None:
    registry = ReaderRegistry()
    registry.register(PlainTextV1())
    with pytest.raises(ReaderRegistrationError, match="duplicate"):
        registry.register(PlainTextV1())


# -- receipts and the circuit breaker -----------------------------------


def test_an_accepted_run_produces_a_receipt_bound_to_both_digests() -> None:
    source = _input(b"Paragraph.\n", filename="notes.txt", declared_mime="text/plain")
    output, receipt = _registry().read(source, inspection=inspect_source(source), queue_wait_ms=12)
    assert output is not None
    assert receipt.accepted is True
    assert receipt.provider_id == "plain_text_v1"
    assert receipt.input_digest == source.content_sha256
    assert receipt.output_digest == output.output_digest
    assert receipt.queue_wait_ms == 12
    assert receipt.failure_class is None
    # Never invented: no GPU ran and no price was snapshotted.
    assert receipt.gpu_seconds is None
    assert receipt.provider_cost_usd is None


def test_a_digest_that_does_not_match_the_bytes_is_refused_before_any_parse() -> None:
    source = _input(
        b"Paragraph.\n",
        filename="notes.txt",
        declared_mime="text/plain",
        content_sha256="sha256:" + "0" * 64,
    )
    output, receipt = _registry().read(source, inspection=inspect_source(source))
    assert output is None
    assert receipt.failure_class is FailureClass.RECEIPT_MISMATCH


def test_a_reader_that_produces_nothing_is_a_failed_run_not_an_empty_success() -> None:
    source = _input(b"   \n\n  \n", filename="blank.txt", declared_mime="text/plain")
    output, receipt = _registry().read(source, inspection=inspect_source(source))
    assert output is None
    assert receipt.failure_class is FailureClass.EMPTY_OUTPUT


class _SlowText(PlainTextV1):
    provider_id = "slow_text_v1"

    def extract_native(self, source: ReaderInput) -> NativeExtraction:
        if source.filename != "probe.txt":
            time.sleep(0.5)
        return super().extract_native(source)


def test_a_timeout_yields_a_parser_timeout_receipt_and_opens_the_circuit() -> None:
    clock = _Clock()
    registry = ReaderRegistry(
        timeout_seconds=0.05, failure_threshold=1, cooldown_seconds=60.0, clock=clock
    )
    registry.register(_SlowText())
    source = _input(b"Paragraph.\n", filename="notes.txt", declared_mime="text/plain")
    inspection = inspect_source(source)

    output, receipt = registry.read(source, inspection=inspection)
    assert output is None
    assert receipt.failure_class is FailureClass.PARSER_TIMEOUT
    assert receipt.provider_id == "slow_text_v1"

    blocked = registry.resolve(inspection)
    assert blocked.status is CapabilityStatus.REVIEW_REQUIRED
    assert blocked.failure_class is FailureClass.PROVIDER_UNAVAILABLE
    assert registry.health()[0].circuit_open is True

    clock.advance(seconds=61)
    assert registry.resolve(inspection).provider_id == "slow_text_v1"


class _Clock:
    def __init__(self) -> None:
        self._now = datetime(2026, 9, 6, tzinfo=UTC)

    def __call__(self) -> datetime:
        self._now += timedelta(microseconds=1)
        return self._now

    def advance(self, *, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def test_a_reader_that_raises_is_recorded_as_provider_unavailable() -> None:
    class _Broken(PlainTextV1):
        provider_id = "broken_text_v1"

        def extract_native(self, source: ReaderInput) -> NativeExtraction:
            if source.filename != "probe.txt":
                raise RuntimeError("reader exploded")
            return super().extract_native(source)

    registry = ReaderRegistry()
    registry.register(_Broken())
    source = _input(b"Paragraph.\n", filename="notes.txt", declared_mime="text/plain")
    output, receipt = registry.read(source, inspection=inspect_source(source))
    assert output is None
    assert receipt.failure_class is FailureClass.PROVIDER_UNAVAILABLE
    assert receipt.escalation_reason == "RuntimeError"


# -- registry entries ---------------------------------------------------


def test_registry_entries_are_candidates_with_no_invented_measurements() -> None:
    entries = _registry().entries()
    assert [entry.reader_id for entry in entries] == ["legacy_pdf_v1", "plain_text_v1"]
    for entry in entries:
        assert entry.status is ReaderRegistryStatus.CANDIDATE
        assert entry.evaluator_receipts == ()
        assert entry.p50_latency_ms is None
        assert entry.p95_latency_ms is None
        assert entry.cost_per_unit is None
        assert entry.runtime_digest.startswith("sha256:")


def test_a_qualified_registry_entry_without_an_evaluator_receipt_is_refused() -> None:
    with pytest.raises(ValidationError, match="evaluator receipt"):
        ReaderRegistryEntry(
            reader_id="legacy_pdf_v1",
            model_revision="r1",
            runtime_digest="sha256:" + "a" * 64,
            status=ReaderRegistryStatus.QUALIFIED,
        )


def test_health_reports_every_registered_reader() -> None:
    health = _registry().health()
    assert {item.provider_id for item in health} == {"legacy_pdf_v1", "plain_text_v1"}
    assert all(isinstance(item, ReaderHealth) and item.healthy for item in health)


def test_source_inspection_is_the_blueprint_field_set() -> None:
    expected: set[str] = {
        "detected_mime",
        "source_family",
        "container_kind",
        "encrypted",
        "corrupted",
        "has_native_text",
        "has_native_structure",
        "has_visual_content",
        "page_like_units",
        "confidence",
        "review_reasons",
    }
    assert set(SourceInspection.model_fields) == expected


def test_extraction_features_are_observed_never_declared() -> None:
    provider = LegacyPdfV1()
    output: NativeExtraction = provider.extract_native(provider.probe_samples()[0])
    observed: Any = output.observed_features()
    assert ReaderFeature.NATIVE_TEXT in observed
    assert ReaderFeature.LAYOUT in observed
    assert ReaderFeature.TABLES not in observed


# -- repair pass: the failure paths the review found open ----------------


def test_blank_sources_never_take_a_healthy_reader_offline() -> None:
    """Semantic failure is not operational failure (CLAUDE.md runtime invariant).

    Three whitespace-only uploads used to open the breaker and report a working
    stdlib reader as PROVIDER_UNAVAILABLE for the next 30 seconds.
    """
    registry = _registry()
    blank = _input(b"   \n\n  \n", filename="blank.txt", declared_mime="text/plain")
    for _ in range(3):
        _, receipt = registry.read(blank, inspection=inspect_source(blank))
        assert receipt.failure_class is FailureClass.EMPTY_OUTPUT

    assert all(item.circuit_open is False for item in registry.health())
    good = _input(b"Real paragraph.\n", filename="notes.txt", declared_mime="text/plain")
    output, receipt = registry.read(good, inspection=inspect_source(good))
    assert output is not None
    assert receipt.accepted is True


def test_a_source_that_is_not_utf8_is_the_sources_failure_not_the_readers() -> None:
    """The 8 KB text sniff cannot see a CP949 tail; the run must still be honest."""
    data = b"legacy note line\n" * 600 + "프로젝트 요약".encode("cp949")
    source = _input(data, filename="notes.txt", declared_mime="text/plain")
    inspection = inspect_source(source)
    assert inspection.detected_mime == "text/plain"

    registry = _registry()
    for _ in range(3):
        output, receipt = registry.read(source, inspection=inspection)
        assert output is None
        assert receipt.failure_class is FailureClass.CORRUPT_SOURCE
        assert receipt.escalation_reason is not None
        assert receipt.escalation_reason.startswith("UnicodeDecodeError")
    assert all(item.circuit_open is False for item in registry.health())


class _TwoFacedText(PlainTextV1):
    """Declares PDF tables on the strength of a .txt probe."""

    provider_id = "two_faced_v1"

    def capabilities(self) -> tuple[ReaderCapability, ...]:
        return (
            ReaderCapability(
                mime_patterns=("text/plain",),
                source_families=(SourceFamily.DOCUMENT,),
                features=(ReaderFeature.NATIVE_TEXT,),
                qualification_status=CapabilityStatus.BEST_EFFORT,
            ),
            ReaderCapability(
                mime_patterns=("application/pdf",),
                source_families=(SourceFamily.DOCUMENT,),
                features=(ReaderFeature.TABLES,),
                qualification_status=CapabilityStatus.BEST_EFFORT,
            ),
        )

    def extract_native(self, source: ReaderInput) -> NativeExtraction:
        output = super().extract_native(source)
        units = tuple(unit.model_copy(update={"table_id": "t1"}) for unit in output.units)
        return output.model_copy(
            update={"units": units, "output_digest": digest_units(units)}
        )


def test_a_capability_no_probe_sample_exercises_is_refused() -> None:
    with pytest.raises(ReaderRegistrationError, match="no probe sample exercises: application/pdf"):
        ReaderRegistry().register(_TwoFacedText())


class _TwoSampleText(PlainTextV1):
    """The legitimate multi-capability shape: one probe sample per capability."""

    provider_id = "two_sample_text_v1"

    def capabilities(self) -> tuple[ReaderCapability, ...]:
        return (
            ReaderCapability(
                mime_patterns=("text/plain",),
                source_families=(SourceFamily.DOCUMENT,),
                features=(ReaderFeature.NATIVE_TEXT,),
                qualification_status=CapabilityStatus.BEST_EFFORT,
            ),
            ReaderCapability(
                mime_patterns=("text/markdown",),
                source_families=(SourceFamily.DOCUMENT,),
                features=(ReaderFeature.NATIVE_TEXT,),
                qualification_status=CapabilityStatus.BEST_EFFORT,
            ),
        )

    def probe_samples(self) -> tuple[ReaderInput, ...]:
        markdown = b"# Probe\n\nProbe body.\n"
        return (
            *super().probe_samples(),
            _input(markdown, filename="probe.md", declared_mime="text/markdown"),
        )


def test_a_capability_with_its_own_probe_sample_registers() -> None:
    registry = ReaderRegistry()
    registry.register(_TwoSampleText())
    assert [entry.reader_id for entry in registry.entries()] == ["two_sample_text_v1"]


def test_an_invalid_evidence_locator_is_refused_at_read_time_not_only_at_registration() -> None:
    """The frozen schema's Identifier pattern rejects a slash-bearing id."""
    registry = _registry()
    data = LegacyPdfV1().probe_samples()[0].data
    source = ReaderInput(
        source_version_id="tenant/9f21 doc#3",
        tenant_id="tenant-test",
        representation_id="rep 1/2",
        filename="report.pdf",
        declared_mime="application/pdf",
        content_sha256="sha256:" + hashlib.sha256(data).hexdigest(),
        data=data,
    )
    output, receipt = registry.read(source, inspection=inspect_source(source))
    assert output is None
    assert receipt.failure_class is FailureClass.EVIDENCE_BROKEN
    assert receipt.escalation_reason is not None
    assert "evidence locator" in receipt.escalation_reason


class _WrongSource(PlainTextV1):
    provider_id = "wrong_source_v1"

    def extract_native(self, source: ReaderInput) -> NativeExtraction:
        output = super().extract_native(source)
        if source.filename == "probe.txt":
            return output
        return output.model_copy(
            update={
                "source_version_id": "SOME-OTHER-SOURCE-VERSION",
                "representation_id": "SOME-OTHER-REPRESENTATION",
            }
        )


def test_an_extraction_bound_to_another_source_is_refused() -> None:
    registry = ReaderRegistry()
    registry.register(_WrongSource())
    source = _input(b"Paragraph.\n", filename="notes.txt", declared_mime="text/plain")
    output, receipt = registry.read(source, inspection=inspect_source(source))
    assert output is None
    assert receipt.failure_class is FailureClass.RECEIPT_MISMATCH


class _LyingDigest(PlainTextV1):
    provider_id = "lying_digest_v1"

    def extract_native(self, source: ReaderInput) -> NativeExtraction:
        output = super().extract_native(source)
        if source.filename == "probe.txt":
            return output
        return output.model_copy(update={"output_digest": "sha256:" + "f" * 64})


def test_a_self_asserted_output_digest_is_recomputed_not_believed() -> None:
    registry = ReaderRegistry()
    registry.register(_LyingDigest())
    source = _input(b"Paragraph.\n", filename="notes.txt", declared_mime="text/plain")
    output, receipt = registry.read(source, inspection=inspect_source(source))
    assert output is None
    assert receipt.failure_class is FailureClass.RECEIPT_MISMATCH
    assert receipt.output_digest is None


class _ClaimsLayout(PlainTextV1):
    """Its probe carries a bbox; its real output does not."""

    provider_id = "claims_layout_v1"

    def capabilities(self) -> tuple[ReaderCapability, ...]:
        return (
            ReaderCapability(
                mime_patterns=("text/plain",),
                source_families=(SourceFamily.DOCUMENT,),
                features=(ReaderFeature.NATIVE_TEXT, ReaderFeature.LAYOUT),
                qualification_status=CapabilityStatus.BEST_EFFORT,
            ),
        )

    def extract_native(self, source: ReaderInput) -> NativeExtraction:
        output = super().extract_native(source)
        if source.filename != "probe.txt":
            return output
        units = tuple(
            unit.model_copy(update={"bbox1000": (0, 0, 100, 100)}) for unit in output.units
        )
        return output.model_copy(
            update={"units": units, "output_digest": digest_units(units)}
        )


def test_a_required_feature_absent_from_the_output_is_refused() -> None:
    registry = ReaderRegistry()
    registry.register(_ClaimsLayout())
    source = _input(b"Paragraph.\n", filename="notes.txt", declared_mime="text/plain")
    output, receipt = registry.read(
        source, inspection=inspect_source(source), required_features=[ReaderFeature.LAYOUT]
    )
    assert output is None
    assert receipt.failure_class is FailureClass.LAYOUT_FAILURE


def test_the_legacy_pdf_runtime_digest_pins_the_wrapped_parser_source() -> None:
    """A §22 pin that ignores the code the reader runs is not a pin."""
    from akc_readers.providers import _wrapped_parser_digest

    digest = _wrapped_parser_digest()
    assert digest.startswith("sha256:")
    moved = LegacyPdfV1().runtime_digest
    assert moved != PlainTextV1().runtime_digest
    _wrapped_parser_digest.cache_clear()
    assert _wrapped_parser_digest() == digest  # deterministic over the same tree


def test_active_content_is_published_as_malware_not_as_ordinary_corruption() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"/>',
        )
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships/>')
        archive.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook/>')
        archive.writestr("xl/vbaProject.bin", b"\x00macro\x00")
    source = _input(
        payload.getvalue(),
        filename="book.xlsx",
        declared_mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    inspection = inspect_source(source)
    assert "OFFICE_ACTIVE_CONTENT" in inspection.review_reasons
    resolution = _registry().resolve(inspection)
    assert resolution.status is CapabilityStatus.REVIEW_REQUIRED
    assert resolution.failure_class is FailureClass.MALWARE_QUARANTINED


def test_a_cfb_office_container_holding_an_encrypted_package_is_locked_not_corrupt() -> None:
    """MS-OFFCRYPTO signature test, not a real Office file.

    A password-protected .docx is an OLE/CFB container, never a ZIP, so the
    ZIP-level encryption bit never fires for it. The bytes below carry the CFB
    magic and the UTF-16LE ``EncryptedPackage`` directory name that a real one
    carries; nothing else about them is claimed to be a genuine Office file.
    """
    data = (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        + b"\x00" * 500
        + "EncryptedPackage".encode("utf-16-le")
        + b"\x00" * 100
    )
    source = _input(data, filename="salary.docx", declared_mime=DOCX_MIME)
    inspection = inspect_source(source)
    assert inspection.encrypted is True
    assert inspection.corrupted is False
    assert "OOXML_ENCRYPTED_PACKAGE" in inspection.review_reasons
    resolution = _registry().resolve(inspection)
    assert resolution.failure_class is FailureClass.ENCRYPTED_SOURCE
