"""Shared limits, provenance locations, and deterministic CIR construction."""

from __future__ import annotations

import hashlib
import html
import unicodedata
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from akc_cir import (
    BBox1000,
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalCell,
    CanonicalDocument,
    CanonicalTable,
    ContentLayer,
    ContractModel,
    SourceRef,
    canonical_json,
    sha256_digest,
)
from pydantic import field_validator


class StructuredParseError(ValueError):
    """A stable, body-free parser failure safe to expose at a job boundary."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class ParseContext(ContractModel):
    """Caller-owned identity and timestamps required by the CIR contract."""

    tenant_id: str
    document_id: str
    document_version_id: str
    created_at: datetime
    source_url: str | None = None
    retrieved_at: datetime | None = None

    @field_validator("created_at", "retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("parser timestamps must be timezone-aware")
        return value


@dataclass(frozen=True, slots=True)
class ParserLimits:
    """Hard parser limits, independent from upload-plan quotas."""

    max_input_bytes: int = 50 * 1024 * 1024
    max_archive_entries: int = 2_000
    max_archive_uncompressed_bytes: int = 250 * 1024 * 1024
    max_archive_member_bytes: int = 64 * 1024 * 1024
    max_compression_ratio: float = 100.0
    max_blocks: int = 50_000
    max_total_text_chars: int = 10_000_000
    max_docx_body_elements: int = 25_000
    max_docx_tables: int = 2_000
    max_table_rows: int = 100_000
    max_table_columns: int = 1_024
    max_table_cells: int = 500_000
    max_slides: int = 2_000
    max_shapes_per_slide: int = 5_000
    max_sheets: int = 512
    max_rows_per_sheet: int = 100_000
    max_columns_per_sheet: int = 1_024
    max_cells_per_sheet: int = 500_000
    max_html_nodes: int = 150_000
    max_html_depth: int = 256
    max_subtitle_cues: int = 100_000
    max_cue_chars: int = 20_000

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{item.name} must be positive")
        if self.max_compression_ratio < 1:
            raise ValueError("max_compression_ratio must be at least one")


@dataclass(frozen=True, slots=True)
class SourceLocation:
    page_index0: int
    native_object_id: str
    bbox1000: tuple[int, int, int, int] | None = None
    image_asset_id: str | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None


@dataclass(frozen=True, slots=True)
class TableCellSpec:
    row_index0: int
    column_index0: int
    raw_text: str
    location: SourceLocation
    row_span: int = 1
    column_span: int = 1
    normalized_text: str | None = None
    quality_flags: tuple[str, ...] = ()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.splitlines()).strip()


def deterministic_id(prefix: str, *parts: str) -> str:
    material = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(material).hexdigest()[:32]}"


class CirBuilder:
    """Mutable construction helper whose public result is immutable CIR."""

    def __init__(
        self,
        *,
        context: ParseContext,
        source_filename: str,
        source_sha256: str,
        document_type: str,
        limits: ParserLimits,
    ) -> None:
        self.context = context
        self.source_filename = source_filename
        self.source_sha256 = source_sha256
        self.document_type = document_type
        self.limits = limits
        self.blocks: list[CanonicalBlock] = []
        self.warnings: set[str] = set()
        self.metadata: dict[str, Any] = {}
        self.assets: dict[str, dict[str, Any]] = {}
        self._text_chars = 0

    def add_warning(self, warning: str) -> None:
        self.warnings.add(warning)

    def source_ref(self, location: SourceLocation) -> SourceRef:
        bbox = BBox1000(location.bbox1000) if location.bbox1000 is not None else None
        return SourceRef(
            document_id=self.context.document_id,
            document_version_id=self.context.document_version_id,
            page_index0=location.page_index0,
            page_number1=location.page_index0 + 1,
            bbox1000=bbox,
            native_object_id=location.native_object_id,
            image_asset_id=location.image_asset_id,
            time_start_ms=location.time_start_ms,
            time_end_ms=location.time_end_ms,
        )

    def register_asset(
        self,
        *,
        payload: bytes,
        native_part: str,
        media_type: str,
        kind: str,
        filename: str | None = None,
        width_px: int | None = None,
        height_px: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Register immutable embedded bytes without placing binary data in public CIR."""

        digest = sha256_digest(payload)
        asset_id = deterministic_id(
            "asset",
            self.source_sha256,
            native_part,
            digest,
        )
        descriptor: dict[str, Any] = {
            "id": asset_id,
            "kind": normalize_text(kind),
            "mediaType": normalize_text(media_type),
            "nativePart": normalize_text(native_part),
            "sha256": digest,
            "sizeBytes": len(payload),
        }
        if filename:
            descriptor["filename"] = normalize_text(filename)
        if width_px is not None and width_px > 0:
            descriptor["widthPx"] = width_px
        if height_px is not None and height_px > 0:
            descriptor["heightPx"] = height_px
        if metadata:
            self.reserve_metadata_text(canonical_json(metadata))
            descriptor["metadata"] = metadata
        existing = self.assets.get(asset_id)
        if existing is not None and existing != descriptor:
            raise StructuredParseError("PARSER_RESULT_INVALID")
        self.assets[asset_id] = descriptor
        return asset_id

    def reserve_metadata_text(self, value: str) -> None:
        """Apply the extracted-text budget to parser-generated metadata text."""

        self._text_chars += len(value)
        if self._text_chars > self.limits.max_total_text_chars:
            raise StructuredParseError("EXTRACTED_TEXT_LIMIT")

    def _reserve(self, text: str) -> None:
        if len(self.blocks) >= self.limits.max_blocks:
            raise StructuredParseError("BLOCK_LIMIT")
        self._text_chars += len(text)
        if self._text_chars > self.limits.max_total_text_chars:
            raise StructuredParseError("EXTRACTED_TEXT_LIMIT")

    def add_block(
        self,
        *,
        block_type: BlockType,
        location: SourceLocation,
        raw_text: str | None = None,
        normalized_text: str | None = None,
        markdown: str | None = None,
        sanitized_html: str | None = None,
        table: CanonicalTable | None = None,
        parent_id: str | None = None,
        quality_flags: tuple[str, ...] = (),
    ) -> CanonicalBlock:
        raw = normalize_text(raw_text) if raw_text is not None else None
        normalized = normalize_text(normalized_text) if normalized_text is not None else raw
        text_for_limit = normalized or raw or markdown or sanitized_html or ""
        self._reserve(text_for_limit)
        order = len(self.blocks)
        block_id = deterministic_id(
            "blk",
            self.source_sha256,
            location.native_object_id,
            block_type.value,
        )
        content_material = {
            "type": block_type.value,
            "rawText": raw,
            "normalizedText": normalized,
            "markdown": markdown,
            "sanitizedHtml": sanitized_html,
            "table": (
                table.model_dump(mode="json", by_alias=True, exclude_none=True)
                if table is not None
                else None
            ),
        }
        block = CanonicalBlock(
            id=block_id,
            parent_id=parent_id,
            order=order,
            type=block_type,
            content_layer=ContentLayer.STRUCTURED,
            raw_text=raw,
            normalized_text=normalized,
            markdown=markdown,
            sanitized_html=sanitized_html,
            table=table,
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(self.source_ref(location),),
            quality_flags=tuple(sorted(set(quality_flags))),
            content_hash=sha256_digest(canonical_json(content_material)),
        )
        self.blocks.append(block)
        return block

    def add_table(
        self,
        *,
        location: SourceLocation,
        row_count: int,
        column_count: int,
        cells: tuple[TableCellSpec, ...],
        header_row_count: int = 0,
        caption: str | None = None,
        parent_id: str | None = None,
        quality_flags: tuple[str, ...] = (),
    ) -> CanonicalBlock:
        if row_count > self.limits.max_table_rows:
            raise StructuredParseError("TABLE_ROW_LIMIT")
        if column_count > self.limits.max_table_columns:
            raise StructuredParseError("TABLE_COLUMN_LIMIT")
        if len(cells) > self.limits.max_table_cells:
            raise StructuredParseError("TABLE_CELL_LIMIT")
        if row_count <= 0 or column_count <= 0 or not cells:
            raise StructuredParseError("EMPTY_TABLE")
        if row_count * column_count > self.limits.max_table_cells:
            raise StructuredParseError("TABLE_CELL_LIMIT")

        occupied: set[tuple[int, int]] = set()
        occupied_area = 0
        for cell in cells:
            row_end = cell.row_index0 + cell.row_span
            column_end = cell.column_index0 + cell.column_span
            if (
                cell.row_index0 < 0
                or cell.column_index0 < 0
                or cell.row_span < 1
                or cell.column_span < 1
                or row_end > row_count
                or column_end > column_count
            ):
                raise StructuredParseError("TABLE_CELL_BOUNDS")
            occupied_area += cell.row_span * cell.column_span
            if occupied_area > self.limits.max_table_cells:
                raise StructuredParseError("TABLE_CELL_LIMIT")
            for row in range(cell.row_index0, row_end):
                for column in range(cell.column_index0, column_end):
                    coordinate = (row, column)
                    if coordinate in occupied:
                        raise StructuredParseError("TABLE_CELL_OVERLAP")
                    occupied.add(coordinate)

        table_id = deterministic_id(
            "tbl",
            self.source_sha256,
            location.native_object_id,
        )
        canonical_cells = tuple(
            CanonicalCell(
                id=deterministic_id(
                    "cell",
                    table_id,
                    str(cell.row_index0),
                    str(cell.column_index0),
                    cell.location.native_object_id,
                ),
                row_index0=cell.row_index0,
                column_index0=cell.column_index0,
                row_span=cell.row_span,
                column_span=cell.column_span,
                raw_text=normalize_text(cell.raw_text),
                normalized_text=normalize_text(
                    cell.normalized_text if cell.normalized_text is not None else cell.raw_text
                ),
                origin=BlockOrigin.NATIVE_EXTRACTED,
                source_refs=(self.source_ref(cell.location),),
                quality_flags=tuple(sorted(set(cell.quality_flags))),
            )
            for cell in sorted(
                cells,
                key=lambda value: (
                    value.row_index0,
                    value.column_index0,
                    value.location.native_object_id,
                ),
            )
        )
        table = CanonicalTable(
            id=table_id,
            row_count=row_count,
            column_count=column_count,
            header_row_count=header_row_count,
            cells=canonical_cells,
            caption=normalize_text(caption) if caption else None,
            source_refs=(self.source_ref(location),),
            quality_flags=tuple(sorted(set(quality_flags))),
        )
        raw_text = _table_plain_text(table)
        markdown = _table_markdown(table) if table.is_simple_gfm else None
        return self.add_block(
            block_type=BlockType.TABLE,
            location=location,
            raw_text=raw_text,
            normalized_text=raw_text,
            markdown=markdown,
            sanitized_html=_table_html(table),
            table=table,
            parent_id=parent_id,
            quality_flags=quality_flags,
        )

    def build(self, *, title: str) -> CanonicalDocument:
        metadata: dict[str, Any] = {
            "documentType": self.document_type,
            "nativeParser": "akc-native-parsers",
            "nativeParserVersion": "1.1.0",
            "sourceLocationScheme": _location_scheme(self.document_type),
            "warnings": sorted(self.warnings),
            **self.metadata,
        }
        if self.assets:
            metadata["assetManifestVersion"] = "1.0.0"
            metadata["assets"] = sorted(
                self.assets.values(),
                key=lambda asset: (str(asset["nativePart"]), str(asset["id"])),
            )
        if self.context.source_url:
            metadata["sourceUrl"] = self.context.source_url
        if self.context.retrieved_at:
            metadata["retrievedAt"] = self.context.retrieved_at.isoformat()
        return CanonicalDocument(
            tenant_id=self.context.tenant_id,
            document_id=self.context.document_id,
            document_version_id=self.context.document_version_id,
            title=normalize_text(title) or self.source_filename,
            source_filename=self.source_filename,
            source_sha256=self.source_sha256,
            content_layer=ContentLayer.STRUCTURED,
            blocks=tuple(self.blocks),
            metadata=metadata,
            created_at=self.context.created_at,
        )


def _location_scheme(document_type: str) -> str:
    return {
        "docx": "docx/body|section|comments|revision/{index}/...",
        "pptx": "pptx/slide/{index}/shape/{z}/...",
        "xlsx": "xlsx/sheet/{index}/{A1-reference|asset}",
        "html": "html/{DOM-path}",
        "srt": "srt/{segment|cue}/{index}",
        "vtt": "vtt/{segment|cue}/{index}",
        "pdf": "pdf/page/{index}/{text|drawing|image-placement}/{object-id}",
    }.get(document_type, f"{document_type}/native-object")


def _table_grid(table: CanonicalTable) -> list[list[str]]:
    grid = [["" for _ in range(table.column_count)] for _ in range(table.row_count)]
    for cell in table.cells:
        grid[cell.row_index0][cell.column_index0] = cell.normalized_text
    return grid


def _table_plain_text(table: CanonicalTable) -> str:
    return "\n".join("\t".join(row).rstrip() for row in _table_grid(table)).rstrip()


def _escape_markdown_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _table_markdown(table: CanonicalTable) -> str:
    grid = _table_grid(table)
    if not grid:
        return ""
    header = grid[0]
    body = grid[1:]
    lines = [
        "| " + " | ".join(_escape_markdown_cell(value) for value in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_escape_markdown_cell(value) for value in row) + " |" for row in body
    )
    return "\n".join(lines)


def _table_html(table: CanonicalTable) -> str:
    by_position = {(cell.row_index0, cell.column_index0): cell for cell in table.cells}
    covered: set[tuple[int, int]] = set()
    rows: list[str] = []
    for row_index in range(table.row_count):
        parts: list[str] = []
        for column_index in range(table.column_count):
            if (row_index, column_index) in covered:
                continue
            cell = by_position.get((row_index, column_index))
            if cell is None:
                parts.append("<td></td>")
                continue
            tag = "th" if row_index < table.header_row_count else "td"
            attributes: list[str] = []
            if cell.row_span > 1:
                attributes.append(f' rowspan="{cell.row_span}"')
            if cell.column_span > 1:
                attributes.append(f' colspan="{cell.column_span}"')
            if tag == "th":
                attributes.append(' scope="col"')
            parts.append(f"<{tag}{''.join(attributes)}>{html.escape(cell.normalized_text)}</{tag}>")
            for row in range(row_index, row_index + cell.row_span):
                for column in range(column_index, column_index + cell.column_span):
                    if (row, column) != (row_index, column_index):
                        covered.add((row, column))
        rows.append(f"<tr>{''.join(parts)}</tr>")
    caption = f"<caption>{html.escape(table.caption)}</caption>" if table.caption else ""
    return f"<table>{caption}{''.join(rows)}</table>"
