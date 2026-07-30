"""Export and provenance sidecar contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator

from .base import Confidence, ContractModel, NonEmptyStr, Sha256, StableId
from .knowledge import ReviewStatus
from .models import BlockOrigin, ContentLayer, SourceRef


class ExportProfile(StrEnum):
    BUNDLE = "bundle"
    PORTABLE_RAW = "portable_raw"
    PORTABLE_STRUCTURED = "portable_structured"
    OBSIDIAN = "obsidian"
    RAG = "rag"
    JSON_LD = "json_ld"


class MarkdownRange(ContractModel):
    start_line1: Annotated[int, Field(ge=1)]
    end_line1: Annotated[int, Field(ge=1)]
    start_codepoint0: Annotated[int, Field(ge=0)]
    end_codepoint0: Annotated[int, Field(ge=0)]
    offset_encoding: str = "unicode_code_points"

    @model_validator(mode="after")
    def validate_range(self) -> MarkdownRange:
        if self.end_line1 < self.start_line1:
            raise ValueError("line range is reversed")
        if self.end_codepoint0 < self.start_codepoint0:
            raise ValueError("code point range is reversed")
        return self


class SourceMapEntry(ContractModel):
    block_id: StableId
    revision: Annotated[int, Field(ge=1)]
    content_hash: Sha256
    markdown_path: NonEmptyStr
    markdown_range: MarkdownRange
    source_refs: tuple[SourceRef, ...]
    origin: BlockOrigin
    confidence: Confidence | None = None

    @field_validator("source_refs")
    @classmethod
    def require_source_refs(cls, value: tuple[SourceRef, ...]) -> tuple[SourceRef, ...]:
        if not value:
            raise ValueError("source map entries require provenance")
        return value


class SourceMap(ContractModel):
    schema_version: str = "source-map-1.0.0"
    document_id: StableId
    document_version_id: StableId
    source_sha256: Sha256
    entries: tuple[SourceMapEntry, ...]


class RagChunk(ContractModel):
    schema_version: str = "rag-chunk-1.0.0"
    chunk_id: StableId
    document_id: StableId
    document_version: StableId
    title: NonEmptyStr
    heading_path: tuple[str, ...]
    content: NonEmptyStr
    content_type: NonEmptyStr
    language: NonEmptyStr
    token_count: Annotated[int, Field(ge=1)]
    tokenizer: NonEmptyStr
    source_refs: tuple[SourceRef, ...]
    origin: BlockOrigin
    content_layer: ContentLayer
    quality: Confidence | None = None
    previous_chunk_id: StableId | None = None
    next_chunk_id: StableId | None = None
    content_hash: Sha256

    @field_validator("source_refs")
    @classmethod
    def require_provenance(cls, value: tuple[SourceRef, ...]) -> tuple[SourceRef, ...]:
        if not value:
            raise ValueError("RAG chunks require source references")
        return value


class Frontmatter(ContractModel):
    akmp_version: str = "1.0"
    id: StableId
    title: NonEmptyStr
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    document_type: NonEmptyStr
    semantic_type: str | None = None
    topics: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    semantic_evidence_block_ids: tuple[StableId, ...] = ()
    semantic_model_attestation: dict[str, str] = Field(default_factory=dict)
    content_layer: ContentLayer
    status: NonEmptyStr = "active"
    review_status: ReviewStatus
    language: NonEmptyStr
    languages: tuple[str, ...]
    source_file: NonEmptyStr
    source_sha256: Sha256
    source_pages: NonEmptyStr
    source_document_id: StableId
    created_at: datetime
    processed_at: datetime
    model_policy: NonEmptyStr
    provenance_file: NonEmptyStr
    quality_file: NonEmptyStr

    @field_validator("created_at", "processed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("frontmatter timestamps must be timezone-aware")
        return value


class QualityReport(ContractModel):
    schema_version: str = "quality-report-1.0.0"
    document_id: StableId
    overall_score: Confidence
    status: NonEmptyStr
    component_scores: dict[str, Confidence]
    findings: tuple[dict[str, Any], ...] = ()
    review_item_count: Annotated[int, Field(ge=0)] = 0


class ExportFile(ContractModel):
    path: NonEmptyStr
    media_type: NonEmptyStr
    sha256: Sha256
    size_bytes: Annotated[int, Field(ge=0)]


class ExportManifest(ContractModel):
    schema_version: str = "export-manifest-1.0.0"
    export_id: StableId
    tenant_id: StableId
    project_id: StableId
    document_id: StableId
    document_version_id: StableId
    profile: ExportProfile
    source_sha256: Sha256
    generated_at: datetime
    files: tuple[ExportFile, ...]
    model_provenance: dict[str, Any] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @field_validator("generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generatedAt must be timezone-aware")
        return value


class FigureDescription(ContractModel):
    asset_id: StableId
    caption_extracted: str | None = None
    description_ai: str | None = None
    description_origin: BlockOrigin | None = None
    source_refs: tuple[SourceRef, ...]
    chart_data: dict[str, Any] | None = None
    quality_flags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_evidence_for_ai_description(self) -> FigureDescription:
        if self.description_ai and not self.source_refs:
            raise ValueError("AI figure descriptions require source evidence")
        if self.description_ai and self.description_origin not in {
            BlockOrigin.AI_SUMMARIZED,
            BlockOrigin.AI_INFERRED,
        }:
            raise ValueError("AI descriptions require an AI origin")
        return self
