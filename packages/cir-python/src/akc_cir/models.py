"""Canonical Intermediate Representation (CIR)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, RootModel, field_validator, model_validator

from .base import Confidence, ContractModel, NonEmptyStr, Sha256, StableId

Coordinate1000 = Annotated[int, Field(ge=0, le=1000)]


class BBox1000(RootModel[tuple[Coordinate1000, Coordinate1000, Coordinate1000, Coordinate1000]]):
    """A normalized [x1, y1, x2, y2] rectangle on a 0..1000 integer grid."""

    @model_validator(mode="after")
    def validate_order(self) -> BBox1000:
        x1, y1, x2, y2 = self.root
        if x1 > x2 or y1 > y2:
            raise ValueError("bbox1000 must satisfy x1 <= x2 and y1 <= y2")
        if x1 == x2 or y1 == y2:
            raise ValueError("bbox1000 must have positive area")
        return self

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.root

    def as_unit_interval(self) -> tuple[float, float, float, float]:
        return tuple(value / 1000 for value in self.root)  # type: ignore[return-value]


class BlockOrigin(StrEnum):
    """Single canonical DB and wire enum for content origin."""

    NATIVE_EXTRACTED = "native_extracted"
    OCR_EXTRACTED = "ocr_extracted"
    RULE_RECONSTRUCTED = "rule_reconstructed"
    AI_RECONSTRUCTED = "ai_reconstructed"
    AI_SUMMARIZED = "ai_summarized"
    AI_INFERRED = "ai_inferred"
    USER_EDITED = "user_edited"


class ContentLayer(StrEnum):
    SOURCE = "source"
    EXTRACTED = "extracted"
    STRUCTURED = "structured"
    KNOWLEDGE = "knowledge"
    INDEX = "index"


class BlockType(StrEnum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    FIGURE = "figure"
    CAPTION = "caption"
    FORMULA = "formula"
    CODE = "code"
    QUOTE = "quote"
    FOOTNOTE = "footnote"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    UNKNOWN = "unknown"


class SourceRef(ContractModel):
    document_id: StableId
    document_version_id: StableId
    page_index0: Annotated[int, Field(ge=0)]
    page_number1: Annotated[int, Field(ge=1)]
    bbox1000: BBox1000 | None = None
    native_object_id: StableId | None = None
    image_asset_id: StableId | None = None
    time_start_ms: Annotated[int, Field(ge=0)] | None = None
    time_end_ms: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def validate_page_and_time(self) -> SourceRef:
        if self.page_number1 != self.page_index0 + 1:
            raise ValueError("pageNumber1 must equal pageIndex0 + 1")
        if (self.time_start_ms is None) != (self.time_end_ms is None):
            raise ValueError("time range requires both start and end")
        if (
            self.time_start_ms is not None
            and self.time_end_ms is not None
            and self.time_start_ms > self.time_end_ms
        ):
            raise ValueError("timeStartMs must not exceed timeEndMs")
        return self


class CanonicalCell(ContractModel):
    id: StableId
    row_index0: Annotated[int, Field(ge=0)]
    column_index0: Annotated[int, Field(ge=0)]
    row_span: Annotated[int, Field(ge=1)] = 1
    column_span: Annotated[int, Field(ge=1)] = 1
    raw_text: str = ""
    normalized_text: str = ""
    origin: BlockOrigin
    source_refs: tuple[SourceRef, ...]
    confidence: Confidence | None = None
    quality_flags: tuple[str, ...] = ()

    @field_validator("source_refs")
    @classmethod
    def require_cell_provenance(cls, value: tuple[SourceRef, ...]) -> tuple[SourceRef, ...]:
        if not value:
            raise ValueError("table cells require at least one source reference")
        return value


class CanonicalTable(ContractModel):
    id: StableId
    row_count: Annotated[int, Field(ge=1)]
    column_count: Annotated[int, Field(ge=1)]
    header_row_count: Annotated[int, Field(ge=0)] = 0
    cells: tuple[CanonicalCell, ...]
    caption: str | None = None
    source_refs: tuple[SourceRef, ...]
    quality_flags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_grid(self) -> CanonicalTable:
        if self.header_row_count > self.row_count:
            raise ValueError("headerRowCount exceeds rowCount")
        if not self.cells:
            raise ValueError("table must contain at least one cell")
        occupied: dict[tuple[int, int], str] = {}
        for cell in self.cells:
            row_end = cell.row_index0 + cell.row_span
            column_end = cell.column_index0 + cell.column_span
            if row_end > self.row_count or column_end > self.column_count:
                raise ValueError(f"cell {cell.id} span exceeds table dimensions")
            for row in range(cell.row_index0, row_end):
                for column in range(cell.column_index0, column_end):
                    key = (row, column)
                    if key in occupied:
                        raise ValueError(
                            f"cell {cell.id} overlaps {occupied[key]} at {row},{column}"
                        )
                    occupied[key] = cell.id
        if not self.source_refs:
            raise ValueError("table requires at least one source reference")
        return self

    @property
    def is_simple_gfm(self) -> bool:
        return all(cell.row_span == 1 and cell.column_span == 1 for cell in self.cells)


class CanonicalBlock(ContractModel):
    id: StableId
    parent_id: StableId | None = None
    order: Annotated[int, Field(ge=0)]
    type: BlockType
    content_layer: ContentLayer
    raw_text: str | None = None
    normalized_text: str | None = None
    markdown: str | None = None
    sanitized_html: str | None = None
    table: CanonicalTable | None = None
    formula_latex: str | None = None
    origin: BlockOrigin
    source_refs: tuple[SourceRef, ...]
    model_run_ids: tuple[StableId, ...] = ()
    confidence: Confidence | None = None
    quality_flags: tuple[str, ...] = ()
    content_hash: Sha256
    revision: Annotated[int, Field(ge=1)] = 1

    @model_validator(mode="after")
    def validate_content_contract(self) -> CanonicalBlock:
        if not self.source_refs:
            raise ValueError("canonical blocks require provenance")
        if self.type == BlockType.TABLE and self.table is None:
            raise ValueError("table block requires canonical table")
        if self.table is not None and self.type != BlockType.TABLE:
            raise ValueError("canonical table is only valid on table blocks")
        if self.type == BlockType.FORMULA and not self.formula_latex:
            raise ValueError("formula block requires formulaLatex")
        if self.origin in {
            BlockOrigin.AI_SUMMARIZED,
            BlockOrigin.AI_INFERRED,
        } and self.content_layer in {ContentLayer.SOURCE, ContentLayer.EXTRACTED}:
            raise ValueError("AI-derived content cannot be labeled source or extracted")
        if not any(
            value is not None
            for value in (
                self.raw_text,
                self.normalized_text,
                self.markdown,
                self.sanitized_html,
                self.table,
                self.formula_latex,
            )
        ):
            raise ValueError("block must contain content")
        return self


class ModelRunRecord(ContractModel):
    id: StableId
    provider: NonEmptyStr
    model: NonEmptyStr
    revision: NonEmptyStr
    runtime: NonEmptyStr
    runtime_version: NonEmptyStr
    prompt_sha256: Sha256
    quantization: NonEmptyStr | None = None
    hardware: NonEmptyStr
    container_digest: NonEmptyStr
    route_profile: NonEmptyStr
    started_at: datetime
    completed_at: datetime | None = None

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("model run timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_time_order(self) -> ModelRunRecord:
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completedAt precedes startedAt")
        return self


class CanonicalDocument(ContractModel):
    schema_version: str = "cir-1.0.0"
    tenant_id: StableId
    document_id: StableId
    document_version_id: StableId
    title: NonEmptyStr
    source_filename: NonEmptyStr
    source_sha256: Sha256
    content_layer: ContentLayer
    blocks: tuple[CanonicalBlock, ...]
    model_runs: tuple[ModelRunRecord, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("createdAt must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_graph(self) -> CanonicalDocument:
        block_ids = [block.id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("block IDs must be unique")
        run_ids = {run.id for run in self.model_runs}
        missing_runs = {
            run_id
            for block in self.blocks
            for run_id in block.model_run_ids
            if run_id not in run_ids
        }
        if missing_runs:
            raise ValueError(f"blocks reference unknown model runs: {sorted(missing_runs)}")
        known_blocks = set(block_ids)
        missing_parents = {
            block.parent_id
            for block in self.blocks
            if block.parent_id is not None and block.parent_id not in known_blocks
        }
        if missing_parents:
            raise ValueError(f"blocks reference unknown parents: {sorted(missing_parents)}")
        orders = [block.order for block in self.blocks]
        if len(orders) != len(set(orders)):
            raise ValueError("block order values must be unique within a document")
        return self

    def ordered_blocks(self) -> tuple[CanonicalBlock, ...]:
        return tuple(sorted(self.blocks, key=lambda block: (block.order, block.id)))
