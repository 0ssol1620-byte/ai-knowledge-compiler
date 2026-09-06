"""Native Office readers — XLSX, DOCX, PPTX (lane C-2).

Each provider **wraps** `akc_native_parsers.parse_non_pdf_to_cir` the way
`LegacyPdfV1` wraps `parse_pdf_to_cir`: the parser package is not modified, the
content-detected MIME (never the filename) decides `can_read` and the name the
parser is handed, and only the features a probe sample demonstrably produces are
declared.

None of the three is VERIFIED. Lane C-3 qualified all three against a committed
corpus and every one of them failed rows, so every capability stays
`BEST_EFFORT` and carries no `qualification_receipt`:

* `docs/evidence/receipts/office_reader_qualification_xlsx_2026-09-06.json` — 18/22
* `docs/evidence/receipts/office_reader_qualification_docx_2026-09-06.json` — 10/14
* `docs/evidence/receipts/office_reader_qualification_pptx_2026-09-06.json` — 10/13

Each class below lists the rows it failed. They share one cause: `ExtractedUnit`
has fields for text, an anchor, a bbox, a table id and a formula, and a fact the
wrapped parser knows that fits none of them cannot reach a caller at all.

Two consequences of the frozen contracts are worth stating rather than
discovering:

* `ReaderFeature.COMMENTS`, `TRACK_CHANGES` and `CHART_DATA` are **not**
  declared, although the wrapped parsers produce all three. `NativeExtraction`
  carries no field that witnesses them, so `PROBEABLE_FEATURES` excludes them
  and `ReaderRegistry.register` refuses any provider that declares one. A
  declaration the registry cannot measure is exactly the over-declaration the
  probe exists to stop; the gap belongs to the extraction model, not here.
* EvidenceLocator v2 cannot address every CIR unit. A worksheet as a whole, a
  DOCX table as a whole, an embedded image — none of them has a variant anchor.
  Those units are emitted with ``locator=None``. Nothing is rounded to the
  nearest addressable neighbour.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, ClassVar, Final

import jsonschema
from akc_cir.models import CanonicalCell, CanonicalDocument
from akc_native_parsers import ParseContext, ParserLimits, parse_non_pdf_to_cir
from akc_native_parsers.models import StructuredParseError
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from .enums import CapabilityStatus, LocatorKind, ReaderFeature, SourceFamily
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

# `providers.py` belongs to P1A-C and is read-only here. These two helpers are
# the definitions `LegacyPdfV1` already uses; re-deriving them beside it would
# leave two definitions of one runtime pin and one locator-id scheme.
from .providers import _locator_id, _wrapped_parser_digest
from .registry import validate_evidence_locator

XLSX_MIME: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_MIME: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME: Final = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

#: The parser writes the cell's **absolute** A1 coordinate into
#: ``native_object_id``. Recomputing it from ``CanonicalCell.row_index0`` with
#: ``get_column_letter`` would be table-relative and therefore wrong for every
#: sheet whose used range does not start at A1, so the parser's own coordinate
#: is what the locator carries.
_A1 = r"\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}"
_XLSX_CELL = re.compile(rf"^xlsx/sheet/(\d+)/cell/({_A1})$")
_XLSX_RANGE = re.compile(rf"^xlsx/sheet/(\d+)/range/({_A1}:{_A1})$")
_XLSX_CHART = re.compile(r"^xlsx/sheet/(\d+)/chart/(\d+)$")

_DOCX_PARAGRAPH = re.compile(
    r"^docx/(?:body/p/\d+(?:/textbox/\d+/p/\d+)?|section/\d+/(?:header|footer)/p/\d+)$"
)
_DOCX_CELL = re.compile(r"^(docx/body/table/\d+)/(r/\d+/c/\d+)$")
_DOCX_COMMENT = re.compile(r"^docx/comments/(\S+)$")
_DOCX_FOOTNOTE = re.compile(r"^docx/footnotes/(\S+)$")

_PPTX_SHAPE = re.compile(r"^pptx/slide/(\d+)(?:/shape/([0-9.]+))?(?:/.*)?$")

#: The parser's flag for a cell whose formula text was preserved and never
#: executed. It is the only place formula text survives into the CIR.
_FORMULA_FLAG: Final = "formula_preserved_not_executed"

_LOCATOR_SCHEMA: Final = "tavonel.evidence_locator.v2"

#: A fixed timestamp for every probe sample, so the samples a registration
#: witnesses are the same bytes on every run.
_PROBE_TIME: Final = datetime(2026, 1, 1, 0, 0, 0)


def _stable_zip(payload: bytes) -> bytes:
    """Rewrite an OOXML package with one fixed member timestamp.

    openpyxl, python-docx and python-pptx stamp the local clock into every ZIP
    entry, so two runs of the same builder differ byte for byte. Member order
    and content are preserved; only the timestamps move.
    """
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(payload)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            entry = zipfile.ZipInfo(info.filename, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = info.external_attr
            target.writestr(entry, source.read(info.filename))
    return out.getvalue()


def probe_xlsx_bytes() -> bytes:
    """A one-sheet workbook with a table and one preserved formula."""
    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.title = "Probe"
    sheet.append(["Item", "Count", "Doubled"])
    sheet.append(["alpha", 2, "=B2*2"])
    workbook.properties.created = _PROBE_TIME
    workbook.properties.modified = _PROBE_TIME
    payload = io.BytesIO()
    workbook.save(payload)
    return _stable_zip(payload.getvalue())


def probe_docx_bytes() -> bytes:
    """A heading plus a two-by-two table."""
    document = Document()
    document.add_heading("Probe heading", level=1)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Name"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "alpha"
    table.cell(1, 1).text = "42"
    document.core_properties.created = _PROBE_TIME
    document.core_properties.modified = _PROBE_TIME
    payload = io.BytesIO()
    document.save(payload)
    return _stable_zip(payload.getvalue())


def probe_pptx_bytes() -> bytes:
    """One blank-layout slide carrying a text box and a table."""
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.text = "Probe shape text"
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(3), Inches(4), Inches(1)).table
    table.cell(0, 0).text = "Name"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "alpha"
    table.cell(1, 1).text = "42"
    presentation.core_properties.created = _PROBE_TIME
    presentation.core_properties.modified = _PROBE_TIME
    payload = io.BytesIO()
    presentation.save(payload)
    return _stable_zip(payload.getvalue())


def _cell_formula(cell: CanonicalCell) -> str | None:
    """The cell's formula text, or None where the parser kept none."""
    return cell.raw_text if _FORMULA_FLAG in cell.quality_flags else None


class _NativeOfficeV1:
    """Shared body of the three native Office readers."""

    provider_id: ClassVar[str]
    mime: ClassVar[str]
    extension: ClassVar[str]
    family: ClassVar[SourceFamily]
    features: ClassVar[tuple[ReaderFeature, ...]]
    locator_kind: ClassVar[LocatorKind]
    library: ClassVar[str]

    #: Every provider here runs the same wrapped entry point.
    revision = "akc_native_parsers.parse_non_pdf_to_cir"

    @property
    def runtime_digest(self) -> str:
        return inprocess_runtime_digest(
            {
                "reader": self.provider_id,
                "revision": self.revision,
                self.library: version(self.library),
                "akc_native_parsers": _wrapped_parser_digest(),
            }
        )

    def capabilities(self) -> tuple[ReaderCapability, ...]:
        return (
            ReaderCapability(
                mime_patterns=(self.mime,),
                source_families=(self.family,),
                features=self.features,
                qualification_status=CapabilityStatus.BEST_EFFORT,
            ),
        )

    def inspect(self, source: ReaderInput) -> SourceInspection:
        return inspect_source(source)

    def can_read(self, source: ReaderInput, inspection: SourceInspection) -> bool:
        return (
            not inspection.encrypted
            and not inspection.corrupted
            and inspection.detected_mime == self.mime
        )

    def extract_native(self, source: ReaderInput) -> NativeExtraction:
        # The filename decides nothing. `parse_non_pdf_to_cir` gates on the
        # extension and the declared MIME before it reads a byte, so it is
        # handed the extension the **content** implies and the inspector's
        # detected MIME; the caller's stem is kept only for provenance. A source
        # whose content is not this provider's format is refused here rather
        # than parsed as some other format under this provider's name.
        detected = self.inspect(source).detected_mime
        if detected != self.mime:
            raise StructuredParseError("MIME_MISMATCH")
        stem = Path(source.filename).stem or "source"
        document = parse_non_pdf_to_cir(
            filename=f"{stem}.{self.extension}",
            declared_mime=detected,
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
        units = tuple(self._units(document, source))
        return NativeExtraction(
            provider_id=self.provider_id,
            revision=self.revision,
            source_version_id=source.source_version_id,
            representation_id=source.representation_id,
            units=units,
            output_digest=digest_units(units),
        )

    def emit_evidence_locators(self, output: NativeExtraction) -> tuple[dict[str, Any], ...]:
        """Only the units that carry a schema-valid anchor. No guesses."""
        return tuple(unit.locator for unit in output.units if unit.locator is not None)

    def health_check(self) -> ReaderHealth:
        return ReaderHealth(
            provider_id=self.provider_id,
            healthy=True,
            circuit_open=False,
            checked_at=datetime.now(UTC),
        )

    def probe_samples(self) -> tuple[ReaderInput, ...]:
        data = self._probe_bytes()
        return (
            ReaderInput(
                source_version_id=f"probe-{self.provider_id.replace('_', '-')}",
                tenant_id="probe",
                representation_id="probe-representation",
                filename=f"probe.{self.extension}",
                declared_mime=self.mime,
                content_sha256="sha256:" + hashlib.sha256(data).hexdigest(),
                data=data,
            ),
        )

    # -- unit and locator construction ----------------------------------

    def _units(self, document: CanonicalDocument, source: ReaderInput) -> Iterator[ExtractedUnit]:
        """One unit per CIR block, plus one per cell of every table."""
        index = self._index(document)
        for block in document.blocks:
            if "slide_title_inferred" in block.quality_flags:
                # The pptx parser invents a heading - `Slide 3` - for a slide
                # with no title placeholder, and flags it. `ExtractedUnit` has
                # no field for that flag, so the invention would leave here as
                # ordinary evidence: text that appears nowhere in the package,
                # carrying a slideNumber1 locator and a full-slide bbox. A
                # fabricated locator over synthesised text is exactly what the
                # constitution forbids, so the block is not emitted at all.
                continue
            reference = block.source_refs[0]
            table_id = block.table.id if block.table is not None else None
            yield ExtractedUnit(
                unit_id=block.id,
                text=block.normalized_text or block.raw_text or "",
                locator=self._locator(source, block.id, reference.native_object_id, index),
                bbox1000=reference.bbox1000.as_tuple() if reference.bbox1000 is not None else None,
                table_id=table_id,
                formula=block.formula_latex,
            )
            if block.table is None:
                continue
            for cell in block.table.cells:
                cell_reference = cell.source_refs[0]
                yield ExtractedUnit(
                    unit_id=cell.id,
                    text=cell.normalized_text or cell.raw_text,
                    locator=self._locator(source, cell.id, cell_reference.native_object_id, index),
                    bbox1000=(
                        cell_reference.bbox1000.as_tuple()
                        if cell_reference.bbox1000 is not None
                        else None
                    ),
                    table_id=block.table.id,
                    formula=_cell_formula(cell),
                )

    def _locator(
        self,
        source: ReaderInput,
        unit_id: str,
        native_object_id: str | None,
        index: dict[int, str],
    ) -> dict[str, Any] | None:
        """One EvidenceLocator v2 dict, or None where the unit is unaddressable."""
        if native_object_id is None:
            return None
        anchor = self._anchor(native_object_id, index)
        if anchor is None:
            return None
        locator: dict[str, Any] = {
            "schemaVersion": _LOCATOR_SCHEMA,
            "locatorId": _locator_id(source.source_version_id, unit_id),
            "sourceVersionId": source.source_version_id,
            "representationId": source.representation_id,
            "locatorKind": self.locator_kind.value,
            **anchor,
        }
        try:
            validate_evidence_locator(locator)
        except jsonschema.ValidationError:
            # A locator the frozen schema rejects is a unit this reader could
            # not address, not a locator to publish with a caveat.
            return None
        return locator

    def _probe_bytes(self) -> bytes:
        raise NotImplementedError

    def _index(self, document: CanonicalDocument) -> dict[int, str]:
        """`page_index0` → the name the locator needs, from `builder.metadata`."""
        raise NotImplementedError

    def _anchor(self, native_object_id: str, index: dict[int, str]) -> dict[str, Any] | None:
        raise NotImplementedError


class NativeXlsxV1(_NativeOfficeV1):
    """XLSX → sheet-anchored cell, range and chart locators.

    A worksheet *as a whole* has no v2 anchor (the variant requires a cell,
    range, named range, table or chart), and neither does an embedded image, so
    those units carry `locator=None`.

    Known limitations — the rows this reader failed in the 2026-09-06
    qualification, verbatim from the receipt:

    * `xlsx_merged_ranges` — a merged range's extent never reaches a caller;
      `CanonicalCell` has the spans, `ExtractedUnit` has no field for them.
    * `xlsx_hidden_sheets` — sheet visibility stays in the parser's metadata.
    * `xlsx_named_ranges` — the parser reads no defined names at all, so the v2
      `namedRange` anchor has nothing to fill it.
    * `xlsx_chart_series_names` — a chart series is named by its cell reference
      (`'Data'!B1`) rather than by the label that cell holds (`Revenue`).
    """

    provider_id = "native_xlsx_v1"
    mime = XLSX_MIME
    extension = "xlsx"
    family = SourceFamily.SPREADSHEET
    features = (ReaderFeature.NATIVE_TEXT, ReaderFeature.TABLES, ReaderFeature.FORMULA)
    locator_kind = LocatorKind.XLSX
    library = "openpyxl"

    def _probe_bytes(self) -> bytes:
        return probe_xlsx_bytes()

    def _index(self, document: CanonicalDocument) -> dict[int, str]:
        sheets = document.metadata.get("sheets")
        if not isinstance(sheets, list):
            return {}
        return {
            int(sheet["pageIndex0"]): str(sheet["name"])
            for sheet in sheets
            if isinstance(sheet, dict) and "pageIndex0" in sheet and "name" in sheet
        }

    def _anchor(self, native_object_id: str, index: dict[int, str]) -> dict[str, Any] | None:
        for pattern, field in (
            (_XLSX_CELL, "cell"),
            (_XLSX_RANGE, "range"),
            (_XLSX_CHART, "chartId"),
        ):
            match = pattern.match(native_object_id)
            if match is None:
                continue
            sheet = index.get(int(match.group(1)))
            if sheet is None:
                # The parser named a sheet its own metadata does not list.
                return None
            return {"sheet": sheet, field: match.group(2)}
        return None


class NativeDocxV1(_NativeOfficeV1):
    """DOCX → paragraph, table-cell, comment and footnote locators.

    A table *as a whole* has no v2 anchor (the variant requires `tableId` **and**
    `cellId`), and a drawing is not a paragraph, so those units carry
    `locator=None`. Every anchor is derived from the parser's own
    `native_object_id`; `metadata["docx"]` carries counts, not addresses.

    Known limitations — the rows this reader failed in the 2026-09-06
    qualification, verbatim from the receipt:

    * `docx_comment_author` — the author is kept as a quality flag on the
      comment block, so a caller reads the comment without knowing who wrote it.
    * `docx_tracked_changes` — insertions are folded into the visible paragraph
      text and deletions live only in `metadata["docx"]["trackedChanges"]`;
      neither the change list nor the deleted text is a unit.
    * `docx_merged_cell_spans` — as for XLSX: the span is computed and dropped.
    * `docx_equation_formula` — OMML is flattened to its run text, so `E²=mc`
      arrives as `E2=mc` and no `formula` is emitted.
    """

    provider_id = "native_docx_v1"
    mime = DOCX_MIME
    extension = "docx"
    family = SourceFamily.DOCUMENT
    features = (ReaderFeature.NATIVE_TEXT, ReaderFeature.TABLES)
    locator_kind = LocatorKind.DOCX
    library = "python-docx"

    def _probe_bytes(self) -> bytes:
        return probe_docx_bytes()

    def _index(self, document: CanonicalDocument) -> dict[int, str]:
        return {}

    def _anchor(self, native_object_id: str, index: dict[int, str]) -> dict[str, Any] | None:
        if _DOCX_PARAGRAPH.match(native_object_id) is not None:
            return {"paragraphId": native_object_id}
        cell = _DOCX_CELL.match(native_object_id)
        if cell is not None:
            return {"tableId": cell.group(1), "cellId": cell.group(2)}
        comment = _DOCX_COMMENT.match(native_object_id)
        if comment is not None:
            return {"commentId": comment.group(1)}
        footnote = _DOCX_FOOTNOTE.match(native_object_id)
        if footnote is not None:
            return {"footnoteId": footnote.group(1)}
        return None


class NativePptxV1(_NativeOfficeV1):
    """PPTX → slide-anchored locators, with the shape id where one is known.

    Known limitations — the rows this reader failed in the 2026-09-06
    qualification, verbatim from the receipt:

    * `pptx_speaker_notes` — the notes block's native id is
      `pptx/slide/NNNN/notes`, but the v2 pptx variant has no notes field, so
      the anchor collapses to `slideNumber1` — which is also what the
      slide-heading unit carries. A caller cannot tell a speaker note from a
      slide title. This one is a schema gap, not a parser gap.
    * `pptx_merged_cell_spans` — as for XLSX, plus the pptx variant has no cell
      anchor at all: a cell is addressed no finer than its shape.
    """

    provider_id = "native_pptx_v1"
    mime = PPTX_MIME
    extension = "pptx"
    family = SourceFamily.PRESENTATION
    features = (ReaderFeature.NATIVE_TEXT, ReaderFeature.LAYOUT, ReaderFeature.TABLES)
    locator_kind = LocatorKind.PPTX
    library = "python-pptx"

    def _probe_bytes(self) -> bytes:
        return probe_pptx_bytes()

    def _index(self, document: CanonicalDocument) -> dict[int, str]:
        slides = document.metadata.get("slides")
        if not isinstance(slides, list):
            return {}
        return {
            int(slide["pageIndex0"]): ""
            for slide in slides
            if isinstance(slide, dict) and "pageIndex0" in slide
        }

    def _anchor(self, native_object_id: str, index: dict[int, str]) -> dict[str, Any] | None:
        match = _PPTX_SHAPE.match(native_object_id)
        if match is None:
            return None
        slide_index0 = int(match.group(1))
        if slide_index0 not in index:
            # The parser named a slide its own metadata does not list.
            return None
        anchor: dict[str, Any] = {"slideNumber1": slide_index0 + 1}
        shape_id = match.group(2)
        if shape_id is not None:
            # A table cell is addressed no finer than its shape: the pptx
            # variant has no row/column field. The unit still carries its
            # `table_id`, so nothing about the cell's identity is lost.
            anchor["shapeId"] = shape_id
        return anchor


__all__ = [
    "DOCX_MIME",
    "PPTX_MIME",
    "XLSX_MIME",
    "NativeDocxV1",
    "NativePptxV1",
    "NativeXlsxV1",
    "probe_docx_bytes",
    "probe_pptx_bytes",
    "probe_xlsx_bytes",
]
