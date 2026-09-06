"""The two P0 reader providers.

`plain_text_v1` is new, deterministic and stdlib-only. `legacy_pdf_v1` **wraps**
`akc_native_parsers.parse_pdf_to_cir` without modifying it and declares only the
features that wrapper demonstrably produces. Neither is VERIFIED: no §27
qualification receipt exists yet, and a tier without a receipt is not claimed.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import akc_native_parsers
from akc_native_parsers import ParseContext, ParserLimits, parse_pdf_to_cir
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from .enums import CapabilityStatus, ReaderFeature, SourceFamily
from .inspector import inspect_source
from .models import (
    ExtractedUnit,
    NativeExtraction,
    ReaderCapability,
    ReaderHealth,
    ReaderInput,
    SourceInspection,
    digest_units,
    inprocess_runtime_digest,
)

_PARAGRAPH_BREAK = re.compile(r"\r?\n[ \t]*\r?\n")


def _locator_id(*parts: str) -> str:
    return "loc-" + hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()[:32]


class PlainTextV1:
    """TXT/Markdown → `native_text`. Byte offsets are real; nothing is paginated."""

    provider_id = "plain_text_v1"
    revision = "1.0.0"

    @property
    def runtime_digest(self) -> str:
        return inprocess_runtime_digest({"reader": self.provider_id, "revision": self.revision})

    def capabilities(self) -> tuple[ReaderCapability, ...]:
        return (
            ReaderCapability(
                mime_patterns=("text/plain", "text/markdown"),
                source_families=(SourceFamily.DOCUMENT,),
                features=(ReaderFeature.NATIVE_TEXT,),
                qualification_status=CapabilityStatus.BEST_EFFORT,
            ),
        )

    def inspect(self, source: ReaderInput) -> SourceInspection:
        return inspect_source(source)

    def can_read(self, source: ReaderInput, inspection: SourceInspection) -> bool:
        return (
            not inspection.encrypted
            and not inspection.corrupted
            and inspection.detected_mime in {"text/plain", "text/markdown"}
        )

    def extract_native(self, source: ReaderInput) -> NativeExtraction:
        bom = 3 if source.data.startswith(b"\xef\xbb\xbf") else 0
        text = source.data.decode("utf-8-sig")
        units: list[ExtractedUnit] = []
        cursor = 0
        for index, chunk in enumerate(_PARAGRAPH_BREAK.split(text)):
            start = bom + len(text[:cursor].encode("utf-8"))
            cursor += len(chunk)
            match = _PARAGRAPH_BREAK.search(text, cursor)
            cursor = match.end() if match else cursor
            if not chunk.strip():
                continue
            units.append(
                ExtractedUnit(
                    unit_id=f"{self.provider_id}:p{index:04d}",
                    text=chunk.strip(),
                    byte_range=(start, start + len(chunk.encode("utf-8"))),
                )
            )
        frozen = tuple(units)
        return NativeExtraction(
            provider_id=self.provider_id,
            revision=self.revision,
            source_version_id=source.source_version_id,
            representation_id=source.representation_id,
            units=frozen,
            output_digest=digest_units(frozen),
        )

    def emit_evidence_locators(self, output: NativeExtraction) -> tuple[dict[str, Any], ...]:
        """None, on purpose.

        EvidenceLocator v2's frozen `LocatorKind` list has no plain-text
        variant, and every existing variant requires an anchor a `.txt` file
        does not have (a page, a commit sha, a JSON pointer). Emitting one would
        mean inventing that anchor, so this reader emits nothing and the byte
        ranges stay on the units. The gap is in the lane report as a proposed
        `text` variant for enums v2.
        """
        return ()

    def health_check(self) -> ReaderHealth:
        return ReaderHealth(
            provider_id=self.provider_id,
            healthy=True,
            circuit_open=False,
            checked_at=datetime.now(UTC),
        )

    def probe_samples(self) -> tuple[ReaderInput, ...]:
        """One sample per declared mime pattern.

        Registration witnesses **patterns**, not capabilities, so `text/markdown`
        needs its own probe: before this, `text/markdown` rode into the registry
        on the `.txt` sample's back.
        """
        samples = (
            ("probe.txt", "text/plain", b"Probe paragraph one.\n\nProbe paragraph two.\n"),
            ("probe.md", "text/markdown", b"# Probe heading\n\nProbe markdown body.\n"),
        )
        return tuple(
            ReaderInput(
                source_version_id="probe-plain-text-v1",
                tenant_id="probe",
                representation_id="probe-representation",
                filename=filename,
                declared_mime=declared_mime,
                content_sha256="sha256:" + hashlib.sha256(data).hexdigest(),
                data=data,
            )
            for filename, declared_mime, data in samples
        )


@cache
def _wrapped_parser_digest() -> str:
    """sha256 over the wrapped parser package's own Python sources.

    `legacy_pdf_v1`'s behaviour comes from `akc_native_parsers`, which ships no
    version metadata inside this monorepo. Pinning only python + pypdf would
    leave the registry entry unchanged when the code the reader actually runs
    changes, and a §22 entry that does not move with its code is not a pin.
    """
    root = Path(akc_native_parsers.__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


@cache
def _probe_pdf_bytes() -> bytes:
    """A minimal one-page text PDF, built in memory with the pinned pypdf."""
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
    content.set_data(b"BT /F1 18 Tf 72 720 Td (Reader plane probe page.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    payload = io.BytesIO()
    writer.write(payload)
    return payload.getvalue()


class LegacyPdfV1:
    """Wraps today's native PDF path. It is not fixed here, only labelled.

    What it honestly produces: text blocks with page numbers and bbox1000
    rectangles, i.e. `native_text` and `layout`. It does **not** reconstruct
    tables, formulas, comments or track changes, so it declares none of them —
    and `ReaderRegistry.register` would refuse it if it did.
    """

    provider_id = "legacy_pdf_v1"
    revision = "akc_native_parsers.parse_pdf_to_cir"

    @property
    def runtime_digest(self) -> str:
        from pypdf import __version__ as pypdf_version

        return inprocess_runtime_digest(
            {
                "reader": self.provider_id,
                "revision": self.revision,
                "pypdf": pypdf_version,
                "akc_native_parsers": _wrapped_parser_digest(),
            }
        )

    def capabilities(self) -> tuple[ReaderCapability, ...]:
        return (
            ReaderCapability(
                mime_patterns=("application/pdf",),
                source_families=(SourceFamily.DOCUMENT,),
                features=(ReaderFeature.NATIVE_TEXT, ReaderFeature.LAYOUT),
                qualification_status=CapabilityStatus.BEST_EFFORT,
            ),
        )

    def inspect(self, source: ReaderInput) -> SourceInspection:
        return inspect_source(source)

    def can_read(self, source: ReaderInput, inspection: SourceInspection) -> bool:
        return (
            not inspection.encrypted
            and not inspection.corrupted
            and inspection.detected_mime == "application/pdf"
        )

    def extract_native(self, source: ReaderInput) -> NativeExtraction:
        # The filename never decides readability. `parse_pdf_to_cir` gates on the
        # extension (`UNSUPPORTED_PDF_TYPE`) and on the declared MIME
        # (`MIME_MISMATCH`) before it reads a byte, so handing it the caller's
        # two strings meant a content-detected PDF named `report.bin` came back
        # refused and was published in a §44 receipt as `CORRUPT_SOURCE` —
        # corruption asserted about a source that is not corrupt. It gets the
        # inspector's content-detected MIME and a filename whose extension
        # matches it instead; the caller's stem is kept for provenance, and the
        # parser's own `%PDF-` magic check still refuses bytes that are not one.
        detected_mime = self.inspect(source).detected_mime
        stem = Path(source.filename).stem or "source"
        document = parse_pdf_to_cir(
            filename=f"{stem}.pdf",
            declared_mime=detected_mime,
            data=source.data,
            # Campaign identity alias (contract §7 R-8): one SourceVersion per
            # document row, so the source version id is the document identity.
            context=ParseContext(
                tenant_id=source.tenant_id,
                document_id=source.source_version_id,
                document_version_id=source.source_version_id,
                created_at=datetime.now(UTC),
            ),
            limits=ParserLimits(),
        )
        units: list[ExtractedUnit] = []
        for block in document.blocks:
            reference = block.source_refs[0]
            bbox = reference.bbox1000.as_tuple() if reference.bbox1000 is not None else None
            text = block.normalized_text or block.raw_text or ""
            locator: dict[str, Any] | None = None
            if bbox is not None:
                locator = {
                    "schemaVersion": "tavonel.evidence_locator.v2",
                    "locatorId": _locator_id(source.source_version_id, block.id),
                    "sourceVersionId": source.source_version_id,
                    "representationId": source.representation_id,
                    "locatorKind": "pdf",
                    "page": reference.page_number1,
                    "bbox1000": list(bbox),
                }
                if reference.native_object_id is not None:
                    locator["objectId"] = reference.native_object_id
            units.append(
                ExtractedUnit(
                    unit_id=block.id,
                    text=text,
                    locator=locator,
                    bbox1000=bbox,
                    table_id=block.table.id if block.table is not None else None,
                    formula=block.formula_latex,
                )
            )
        frozen = tuple(units)
        return NativeExtraction(
            provider_id=self.provider_id,
            revision=self.revision,
            source_version_id=source.source_version_id,
            representation_id=source.representation_id,
            units=frozen,
            output_digest=digest_units(frozen),
        )

    def emit_evidence_locators(self, output: NativeExtraction) -> tuple[dict[str, Any], ...]:
        """`pdf` locators, and only for blocks that actually carry a rectangle.

        A block without a bbox yields no locator rather than a guessed one.
        """
        return tuple(unit.locator for unit in output.units if unit.locator is not None)

    def health_check(self) -> ReaderHealth:
        return ReaderHealth(
            provider_id=self.provider_id,
            healthy=True,
            circuit_open=False,
            checked_at=datetime.now(UTC),
        )

    def probe_samples(self) -> tuple[ReaderInput, ...]:
        data = _probe_pdf_bytes()
        return (
            ReaderInput(
                source_version_id="probe-legacy-pdf-v1",
                tenant_id="probe",
                representation_id="probe-representation",
                filename="probe.pdf",
                declared_mime="application/pdf",
                content_sha256="sha256:" + hashlib.sha256(data).hexdigest(),
                data=data,
            ),
        )


__all__ = ["LegacyPdfV1", "PlainTextV1"]
