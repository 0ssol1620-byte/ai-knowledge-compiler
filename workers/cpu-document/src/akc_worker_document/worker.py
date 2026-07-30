"""Durable, lease-safe CPU document analysis worker."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

from akc_api.abuse_repository import reserve_free_usage
from akc_api.database import Database
from akc_api.free_tier import (
    FreeTierCapExceeded,
    FreeTierCaps,
    FreeUsageDelta,
)
from akc_api.models import (
    AnalysisTask,
    AuditEvent,
    Block,
    Document,
    DocumentVersion,
    OutboxEvent,
    Page,
    PageAsset,
    Project,
    ReviewItem,
    SourceFile,
    utcnow,
)
from akc_api.page_attempts import (
    create_page_attempt,
    transition_page_attempt,
)
from akc_api.page_quality import (
    PageQualityBlock,
    evaluate_page_quality,
    quality_block_from_canonical,
)
from akc_api.routing_runtime import load_routing_runtime
from akc_api.settings import Settings
from akc_api.storage import ObjectStore
from akc_cir import (
    NORMALIZATION_VERSION,
    CanonicalBlock,
    CanonicalDocument,
    NormalizationBlock,
    PageState,
    analyze_document_structure,
    detect_repeated_marginal_blocks,
    normalize_block_text,
    restore_cross_page_continuity,
)
from akc_router import (
    EscalationAction,
    PageMetrics,
    Route,
    classify_page,
    decide_escalation,
    detect_script_distribution,
    preflight_difficulty,
    select_first_route,
)
from akc_security import (
    PdfSecretBinding,
    PdfSecretError,
    PdfSecretLease,
    PdfSecretStore,
    SensitiveScan,
    detect_prompt_injection,
    detect_sensitive_data,
)
from akc_telemetry import record_abuse_control_decision, record_page_terminal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from akc_worker_document.settings import AnalysisWorkerSettings
from akc_worker_document.telemetry import (
    ANALYSIS_DLQ,
    ANALYSIS_DURATION,
    ANALYSIS_QUEUE_DEPTH,
    record_attempt,
    record_preview,
    record_sandbox_termination,
)

logger = logging.getLogger(__name__)
_EVENT_TYPE = "document.analysis.requested.v1"
_SAFE_ERROR_CODES = frozenset(
    {
        "ARCHIVE_FILE_LIMIT",
        "ARCHIVE_SIZE_LIMIT",
        "ARCHIVE_RATIO_LIMIT",
        "ARCHIVE_PATH_TRAVERSAL",
        "OFFICE_EXTERNAL_RELATION",
        "INVALID_OFFICE_ARCHIVE",
        "UNSUPPORTED_FILE",
        "FILE_TOO_LARGE",
        "CHECKSUM_MISMATCH",
        "MIME_MISMATCH",
        "MAGIC_MISMATCH",
        "BINARY_TEXT_FILE",
        "TEXT_ENCODING",
        "ENCRYPTED_PDF",
        "PDF_PASSWORD_ATTEMPTS_EXHAUSTED",
        "PDF_PASSWORD_CHANNEL_INVALID",
        "PDF_PASSWORD_EXPIRED",
        "PDF_PASSWORD_INVALID",
        "PDF_PASSWORD_REQUIRED",
        "PDF_SECRET_STORE_CORRUPT",
        "PDF_SECRET_STORE_UNAVAILABLE",
        "PAGE_LIMIT",
        "IMAGE_DIMENSIONS",
        "INVALID_IMAGE",
        "EXTRACTED_TEXT_LIMIT",
        "PARSER_INTERNAL_ERROR",
        "PARSER_PROCESS_CRASH",
        "PARSER_TIMEOUT",
        "PARSER_RESULT_INVALID",
        "PARSER_RESULT_TOO_LARGE",
        "PARSER_SANDBOX_UNAVAILABLE",
        "SOURCE_CONTEXT_INVALID",
        "SOURCE_OBJECT_INVALID",
        "DOCUMENT_DELETED",
        "FREE_DAILY_PAGE_CAP",
    }
) | frozenset(
    {
        "ARCHIVE_DUPLICATE_ENTRY",
        "ARCHIVE_ENCRYPTED_ENTRY",
        "ARCHIVE_ENTRY_LIMIT",
        "ARCHIVE_MEMBER_LIMIT",
        "ARCHIVE_SYMLINK",
        "BLOCK_LIMIT",
        "DOCX_BODY_ELEMENT_LIMIT",
        "DOCX_EMPTY_DOCUMENT",
        "DOCX_PARSE_FAILED",
        "DOCX_TABLE_LIMIT",
        "EMPTY_TABLE",
        "FILE_EMPTY",
        "HTML_DEPTH_LIMIT",
        "HTML_EMPTY_DOCUMENT",
        "HTML_NODE_LIMIT",
        "HTML_PARSE_FAILED",
        "HTML_SIGNATURE_MISMATCH",
        "HTML_TABLE_INVALID_SPAN",
        "HTML_TABLE_OVERLAP",
        "HTML_TEXT_UNAVAILABLE",
        "OFFICE_ACTIVE_CONTENT",
        "OFFICE_EMBEDDED_OBJECT",
        "OOXML_CONTENT_TYPES_MISSING",
        "OOXML_PACKAGE_KIND_MISMATCH",
        "OOXML_UNSAFE_XML",
        "PPTX_EMPTY_PRESENTATION",
        "PPTX_PARSE_FAILED",
        "SHEET_CELL_LIMIT",
        "SHEET_COLUMN_LIMIT",
        "SHEET_LIMIT",
        "SHEET_ROW_LIMIT",
        "SLIDE_LIMIT",
        "SLIDE_SHAPE_LIMIT",
        "SRT_INVALID_CUE",
        "SRT_INVALID_TIMING",
        "SRT_NO_CUES",
        "SUBTITLE_CUE_LIMIT",
        "SUBTITLE_CUE_TEXT_LIMIT",
        "SUBTITLE_EMPTY_CUE",
        "SUBTITLE_INVALID_TIMESTAMP",
        "SUBTITLE_TEXT_UNAVAILABLE",
        "SUBTITLE_TIME_ORDER",
        "TABLE_CELL_BOUNDS",
        "TABLE_CELL_LIMIT",
        "TABLE_CELL_OVERLAP",
        "TABLE_COLUMN_LIMIT",
        "TABLE_ROW_LIMIT",
        "UNHANDLED_NON_PDF_TYPE",
        "UNSUPPORTED_NON_PDF_TYPE",
        "UNSUPPORTED_SUBTITLE_TYPE",
        "VTT_INVALID_CUE",
        "VTT_INVALID_TIMING",
        "VTT_NO_CUES",
        "VTT_SIGNATURE_MISMATCH",
        "XLSX_EMPTY_WORKBOOK",
        "XLSX_INVALID_CELL_REFERENCE",
        "XLSX_INVALID_RANGE",
        "XLSX_PARSE_FAILED",
        "XLSX_UNSAFE_XML",
    }
)

_STRUCTURED_NATIVE_TYPES = frozenset({"pdf", "docx", "pptx", "xlsx", "html", "srt", "vtt"})
_PERSISTED_BLOCK_NAMESPACE = uuid.UUID("d7552336-25a5-5c70-8f6d-2d133c8378e9")


async def verify_sandbox_launcher(runtime: AnalysisRuntime) -> None:
    """Prove the production namespace launcher works before claiming work."""

    if runtime.sandbox_launcher == "direct":
        if runtime.env == "production":
            raise RuntimeError("production_parser_sandbox_unavailable")
        return
    launcher = shutil.which("bwrap")
    if launcher is None or os.name == "nt":
        raise RuntimeError("bubblewrap_not_available")
    process = await asyncio.create_subprocess_exec(
        launcher,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--",
        "/bin/true",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        return_code = await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError("bubblewrap_self_test_timeout") from exc
    if return_code != 0:
        raise RuntimeError("bubblewrap_self_test_failed")


class _WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AssetManifest(_WireModel):
    filename: str = Field(pattern=r"^page-[1-9][0-9]{0,4}-(preview|thumbnail)\.png$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    content_type: Literal["image/png"]


class OrientationTransform(_WireModel):
    applied: bool
    method: Literal["exif_orientation_v1", "trusted_metadata_only_v1"]
    exif_orientation: int = Field(ge=1, le=8)
    operation: Literal[
        "identity",
        "flip_horizontal",
        "rotate_180",
        "flip_vertical",
        "transpose",
        "rotate_90_clockwise",
        "transverse",
        "rotate_270_clockwise",
    ]
    angle_degrees: Literal[0, 90, 180, 270]
    reason: str = Field(min_length=1, max_length=100)


class DeskewTransform(_WireModel):
    applied: bool
    method: Literal["bounded_projection_profile_v1"]
    angle_degrees: float = Field(ge=-5.0, le=5.0)
    score_before: float = Field(ge=0.0)
    score_after: float = Field(ge=0.0)
    foreground_ratio: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=100)


class BorderCropTransform(_WireModel):
    applied: bool
    method: Literal["foreground_bbox_v1"]
    crop_box_px: tuple[int, int, int, int] | None = None
    retained_area_ratio: float = Field(gt=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=100)


class ContrastTransform(_WireModel):
    applied: bool
    method: Literal["bounded_autocontrast_1pct_v1"]
    stddev_before: float = Field(ge=0.0, le=255.0)
    dynamic_range_before: int = Field(ge=0, le=255)
    reason: str = Field(min_length=1, max_length=100)


class DewarpTransform(_WireModel):
    applied: Literal[False]
    method: Literal["none"]
    reason: Literal["no_calibrated_curvature_evidence_or_immutable_dewarp_model"]


class PageTransformManifest(_WireModel):
    schema_version: Literal["akc-page-preprocessing-1.0.0"]
    source_immutable: Literal[True]
    input_dimensions_px: tuple[int, int]
    oriented_dimensions_px: tuple[int, int]
    output_dimensions_px: tuple[int, int]
    orientation: OrientationTransform
    deskew: DeskewTransform
    border_crop: BorderCropTransform
    contrast: ContrastTransform
    dewarp: DewarpTransform
    transform_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_transform(self) -> PageTransformManifest:
        if any(value <= 0 or value > 20_000 for value in self.input_dimensions_px):
            raise ValueError("invalid preprocessing input dimensions")
        if any(value <= 0 or value > 20_000 for value in self.oriented_dimensions_px):
            raise ValueError("invalid preprocessing oriented dimensions")
        if any(value <= 0 or value > 20_000 for value in self.output_dimensions_px):
            raise ValueError("invalid preprocessing output dimensions")
        crop = self.border_crop.crop_box_px
        if self.border_crop.applied != (crop is not None):
            raise ValueError("crop application and crop box disagree")
        if crop is not None:
            left, top, right, bottom = crop
            width, height = self.oriented_dimensions_px
            if (
                left < 0
                or top < 0
                or left >= right
                or top >= bottom
                or right > width
                or bottom > height
            ):
                raise ValueError("invalid preprocessing crop box")
        payload = self.model_dump(mode="json", exclude={"transform_sha256"})
        actual = hashlib.sha256(
            json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if actual != self.transform_sha256:
            raise ValueError("preprocessing transform checksum mismatch")
        return self


class InferenceRasterManifest(_WireModel):
    filename: str = Field(pattern=r"^page-[1-9][0-9]{0,4}-inference-(?:200|300)\.png$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    content_type: Literal["image/png"]
    dpi: Literal[200, 300]
    colorspace: Literal["RGB"]
    transform: PageTransformManifest


class PreviewManifest(_WireModel):
    status: Literal["available", "unavailable"]
    reason: str | None = Field(default=None, max_length=80)
    preview: AssetManifest | None = None
    thumbnail: AssetManifest | None = None
    inference_rasters: (
        tuple[
            InferenceRasterManifest,
            InferenceRasterManifest,
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def consistent_state(self) -> PreviewManifest:
        if self.status == "available" and (
            self.preview is None
            or self.thumbnail is None
            or self.inference_rasters is None
            or self.reason is not None
        ):
            raise ValueError("available preview requires UI and inference assets with no reason")
        if self.status == "unavailable" and (
            self.preview is not None
            or self.thumbnail is not None
            or self.inference_rasters is not None
            or not self.reason
        ):
            raise ValueError("unavailable preview requires a reason and no assets")
        if self.inference_rasters is not None and {
            raster.dpi for raster in self.inference_rasters
        } != {200, 300}:
            raise ValueError("inference rasters must include exact 200 and 300 DPI assets")
        return self


class TextNormalizationManifest(_WireModel):
    version: Literal["akc-normalization-1.1.0"]
    raw_text_preserved: Literal[True] = Field(alias="rawTextPreserved")
    operations: tuple[str, ...] = Field(max_length=16)
    quality_flags: tuple[str, ...] = Field(alias="qualityFlags", max_length=16)


class ParsedPageManifest(_WireModel):
    page_number: int = Field(ge=1, le=10_000)
    text: str
    normalized_text: str
    normalization: TextNormalizationManifest
    width_pt: float | None = Field(default=None, gt=0)
    height_pt: float | None = Field(default=None, gt=0)
    image_coverage: float = Field(ge=0, le=1)
    preview: PreviewManifest

    @model_validator(mode="after")
    def validate_normalization(self) -> ParsedPageManifest:
        expected = normalize_block_text(self.text, block_type="paragraph")
        if (
            self.normalized_text != expected.normalized_text
            or self.normalization.model_dump(mode="json", by_alias=True) != expected.payload()
        ):
            raise ValueError("page normalization does not reproduce deterministically")
        return self


class SuccessfulManifest(_WireModel):
    schema_version: Literal["1.0"]
    ok: Literal[True]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document_type: str = Field(min_length=1, max_length=80)
    pages: list[ParsedPageManifest] = Field(min_length=1, max_length=10_000)
    canonical_document: CanonicalDocument | None = None


class FailedManifest(_WireModel):
    schema_version: Literal["1.0"]
    ok: Literal[False]
    error_code: str = Field(min_length=1, max_length=80)
    retryable: bool


class AnalysisAttemptError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        safe_code = code if code in _SAFE_ERROR_CODES else "PARSER_INTERNAL_ERROR"
        super().__init__(safe_code)
        self.code = safe_code
        self.retryable = retryable


class StaleAnalysisLease(RuntimeError):
    """Another worker owns the task lease or completed it first."""


def _analysis_input_revision_hash(manifest: SuccessfulManifest) -> str:
    canonical = manifest.canonical_document
    payload = {
        "schema_version": "analysis-input-revision-1.0.0",
        "source_sha256": manifest.source_sha256,
        "document_type": manifest.document_type,
        "pages": [
            {
                "page_number": page.page_number,
                "text_sha256": hashlib.sha256(page.text.encode("utf-8")).hexdigest(),
                "normalized_text_sha256": hashlib.sha256(
                    page.normalized_text.encode("utf-8")
                ).hexdigest(),
                "normalization_version": page.normalization.version,
                "preprocessing_transform_sha256": (
                    sorted(
                        raster.transform.transform_sha256
                        for raster in page.preview.inference_rasters
                    )
                    if page.preview.inference_rasters is not None
                    else []
                ),
                "width_pt": page.width_pt,
                "height_pt": page.height_pt,
                "image_coverage": page.image_coverage,
            }
            for page in manifest.pages
        ],
        "canonical_schema_version": (canonical.schema_version if canonical is not None else None),
        "canonical_blocks": (
            [
                {
                    "id": block.id,
                    "content_hash": block.content_hash,
                    "revision": block.revision,
                }
                for block in canonical.ordered_blocks()
            ]
            if canonical is not None
            else []
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AnalysisRuntime:
    env: str
    max_upload_bytes: int
    max_pages: int
    max_archive_files: int
    max_archive_uncompressed_bytes: int
    max_archive_ratio: float
    max_extracted_chars_per_page: int
    max_extracted_chars_total: int
    private_mode: bool
    default_retention_days: int
    free_daily_file_cap: int
    free_daily_page_cap: int
    free_daily_gpu_cost_usd_cap: Decimal
    max_attempts: int
    lease_seconds: float
    attempt_timeout_seconds: float
    backoff_base_seconds: float
    backoff_max_seconds: float
    backoff_jitter_ratio: float
    sandbox_launcher: str
    child_memory_bytes: int
    child_file_bytes: int
    child_open_files: int
    max_result_bytes: int
    preview_enabled: bool
    preview_dpi: int
    preview_max_long_edge: int
    preview_thumbnail_long_edge: int
    preview_max_pixels: int
    preview_max_bytes_per_asset: int
    preview_max_total_bytes: int
    inference_raster_max_pixels: int
    inference_raster_max_bytes_per_asset: int
    inference_raster_max_total_bytes: int
    poll_seconds: float

    @classmethod
    def from_worker_settings(
        cls,
        settings: AnalysisWorkerSettings,
    ) -> AnalysisRuntime:
        return cls(
            env=settings.env,
            max_upload_bytes=settings.analysis_max_source_bytes,
            max_pages=settings.max_pages,
            max_archive_files=settings.max_archive_files,
            max_archive_uncompressed_bytes=settings.max_archive_uncompressed_bytes,
            max_archive_ratio=settings.max_archive_ratio,
            max_extracted_chars_per_page=settings.max_extracted_chars_per_page,
            max_extracted_chars_total=settings.max_extracted_chars_total,
            private_mode=settings.private_mode,
            default_retention_days=settings.default_retention_days,
            free_daily_file_cap=settings.free_daily_file_cap,
            free_daily_page_cap=settings.free_daily_page_cap,
            free_daily_gpu_cost_usd_cap=settings.free_daily_gpu_cost_usd_cap,
            max_attempts=settings.analysis_max_attempts,
            lease_seconds=settings.analysis_lease_seconds,
            attempt_timeout_seconds=settings.analysis_attempt_timeout_seconds,
            backoff_base_seconds=settings.analysis_backoff_base_seconds,
            backoff_max_seconds=settings.analysis_backoff_max_seconds,
            backoff_jitter_ratio=settings.analysis_backoff_jitter_ratio,
            sandbox_launcher=settings.analysis_sandbox_launcher,
            child_memory_bytes=settings.analysis_child_memory_bytes,
            child_file_bytes=settings.analysis_child_file_bytes,
            child_open_files=settings.analysis_child_open_files,
            max_result_bytes=settings.analysis_max_result_bytes,
            preview_enabled=settings.preview_enabled,
            preview_dpi=settings.preview_dpi,
            preview_max_long_edge=settings.preview_max_long_edge,
            preview_thumbnail_long_edge=settings.preview_thumbnail_long_edge,
            preview_max_pixels=settings.preview_max_pixels,
            preview_max_bytes_per_asset=settings.preview_max_bytes_per_asset,
            preview_max_total_bytes=settings.preview_max_total_bytes,
            inference_raster_max_pixels=settings.inference_raster_max_pixels,
            inference_raster_max_bytes_per_asset=(settings.inference_raster_max_bytes_per_asset),
            inference_raster_max_total_bytes=(settings.inference_raster_max_total_bytes),
            poll_seconds=settings.analysis_poll_interval_seconds,
        )

    @classmethod
    def from_api_settings(cls, settings: Settings) -> AnalysisRuntime:
        return cls(
            env=settings.env,
            max_upload_bytes=settings.analysis_max_source_bytes,
            max_pages=settings.max_pages,
            max_archive_files=settings.max_archive_files,
            max_archive_uncompressed_bytes=settings.max_archive_uncompressed_bytes,
            max_archive_ratio=settings.max_archive_ratio,
            max_extracted_chars_per_page=2_000_000,
            max_extracted_chars_total=20_000_000,
            private_mode=settings.private_mode,
            default_retention_days=settings.default_retention_days,
            free_daily_file_cap=settings.free_daily_file_cap,
            free_daily_page_cap=settings.free_daily_page_cap,
            free_daily_gpu_cost_usd_cap=settings.free_daily_gpu_cost_usd_cap,
            max_attempts=settings.analysis_max_attempts,
            lease_seconds=settings.analysis_lease_seconds,
            attempt_timeout_seconds=settings.analysis_attempt_timeout_seconds,
            backoff_base_seconds=settings.analysis_backoff_base_seconds,
            backoff_max_seconds=settings.analysis_backoff_max_seconds,
            backoff_jitter_ratio=0,
            sandbox_launcher="direct",
            child_memory_bytes=1536 * 1024 * 1024,
            child_file_bytes=512 * 1024 * 1024,
            child_open_files=128,
            max_result_bytes=128 * 1024 * 1024,
            preview_enabled=True,
            preview_dpi=110,
            preview_max_long_edge=1800,
            preview_thumbnail_long_edge=360,
            preview_max_pixels=20_000_000,
            preview_max_bytes_per_asset=8 * 1024 * 1024,
            preview_max_total_bytes=256 * 1024 * 1024,
            inference_raster_max_pixels=40_000_000,
            inference_raster_max_bytes_per_asset=32 * 1024 * 1024,
            inference_raster_max_total_bytes=1024 * 1024 * 1024,
            poll_seconds=0.1,
        )


@dataclass(frozen=True, slots=True)
class AnalysisClaim:
    event_id: uuid.UUID
    task_id: uuid.UUID
    tenant_id: uuid.UUID
    document_id: uuid.UUID
    document_version: int
    source_file_id: uuid.UUID
    lease_token: uuid.UUID
    attempt: int


@dataclass(frozen=True, slots=True)
class SourceContext:
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: str
    source_file_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_key: str
    storage_bucket: Literal["source", "derived"]
    original_sha256: str
    cdr_status: str
    cdr_provider: str | None
    cdr_revision: str | None
    created_at: datetime
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class UploadedAssets:
    preview_key: str | None
    thumbnail_key: str | None
    preview: AssetManifest | None
    thumbnail: AssetManifest | None
    inference_raster_keys: tuple[str, ...]
    inference_rasters: tuple[InferenceRasterManifest, ...]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _read_sandbox_result(path: Path) -> tuple[bool, int, str]:
    if not path.is_file():
        return False, 0, ""
    return True, path.stat().st_size, path.read_text(encoding="utf-8")


def _inspect_downloaded_source(path: Path) -> tuple[int, str]:
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return size, digest


def _canonical_block_text(block: CanonicalBlock) -> str:
    return block.normalized_text or block.raw_text or block.markdown or ""


def _persisted_block_id(document_id: uuid.UUID, canonical_block_id: str) -> uuid.UUID:
    return uuid.uuid5(
        _PERSISTED_BLOCK_NAMESPACE,
        f"{document_id}:{canonical_block_id}",
    )


def _persisted_page_block_id(document_id: uuid.UUID, page_number: int) -> uuid.UUID:
    return uuid.uuid5(
        _PERSISTED_BLOCK_NAMESPACE,
        f"{document_id}:native-page:{page_number}",
    )


def _full_page_source_ref(
    context: SourceContext,
    *,
    page_number: int,
) -> dict[str, Any]:
    return {
        "documentId": str(context.document_id),
        "documentVersionId": context.document_version_id,
        "pageIndex0": page_number - 1,
        "pageNumber1": page_number,
        "bbox1000": [1, 1, 999, 999],
    }


def _source_ref_id(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "src_" + hashlib.sha256(encoded).hexdigest()[:32]


def _normalization_bbox(value: list[int] | None) -> tuple[int, int, int, int] | None:
    if value is None or len(value) != 4:
        return None
    return value[0], value[1], value[2], value[3]


def _normalization_view(
    row: Block,
    *,
    page_number: int,
) -> NormalizationBlock:
    structured = row.structured_content or {}
    source_refs = structured.get("sourceRefs")
    safe_refs = (
        tuple(item for item in source_refs if isinstance(item, dict))
        if isinstance(source_refs, list)
        else ()
    )
    return NormalizationBlock(
        block_id=str(row.id),
        page_number=page_number,
        order=row.block_order,
        block_type=row.block_type,
        raw_text=row.source_text or "",
        normalized_text=row.normalized_text or "",
        bbox1000=_normalization_bbox(row.bbox1000),
        source_ref_ids=tuple(_source_ref_id(value) for value in safe_refs),
        provider_order=(
            int(structured["providerOrder"])
            if isinstance(structured.get("providerOrder"), int)
            else None
        ),
        provider_label=(
            str(structured["providerLabel"])
            if isinstance(structured.get("providerLabel"), str)
            else None
        ),
        font_size_pt=(
            float(structured["fontSizePt"])
            if isinstance(structured.get("fontSizePt"), (int, float))
            else None
        ),
        font_weight=(
            int(structured["fontWeight"]) if isinstance(structured.get("fontWeight"), int) else None
        ),
        whitespace_before=(
            float(structured["whitespaceBefore"])
            if isinstance(structured.get("whitespaceBefore"), (int, float))
            else None
        ),
        whitespace_after=(
            float(structured["whitespaceAfter"])
            if isinstance(structured.get("whitespaceAfter"), (int, float))
            else None
        ),
        explicit_heading_level=(
            int(structured["headingLevel"])
            if isinstance(structured.get("headingLevel"), int)
            else None
        ),
        is_toc_entry=structured.get("isTocEntry") is True,
        toc_level=(
            int(structured["tocLevel"]) if isinstance(structured.get("tocLevel"), int) else None
        ),
        markdown=row.markdown,
    )


def _apply_document_normalization_annotations(
    rows: Mapping[str, Block],
    views: list[NormalizationBlock],
    *,
    total_pages: int,
) -> None:
    reading_order, heading_hierarchy = analyze_document_structure(views)
    heading_by_id = {record.block_id: record for record in heading_hierarchy.records}
    for record in reading_order.records:
        row = rows[record.block_id]
        structured = dict(row.structured_content or {})
        normalization = dict(structured.get("normalization") or {})
        normalization["readingOrder"] = record.payload()
        heading = heading_by_id[record.block_id]
        normalization["headingInference"] = heading.payload()
        structured["normalization"] = normalization
        row.structured_content = structured
        row.warnings = sorted(
            {
                *row.warnings,
                *record.quality_flags,
                *heading.warnings,
            }
        )
        if heading.is_heading:
            row.block_type = heading.inferred_type
            if heading.parent_id is not None:
                row.parent_block_id = uuid.UUID(heading.parent_id)

    marginal_annotations = detect_repeated_marginal_blocks(
        views,
        total_pages=total_pages,
    )
    marginal_block_ids = {annotation.block_id for annotation in marginal_annotations}
    for annotation in marginal_annotations:
        row = rows[annotation.block_id]
        structured = dict(row.structured_content or {})
        normalization = dict(structured.get("normalization") or {})
        normalization["repeatedMarginal"] = annotation.payload()
        structured["normalization"] = normalization
        row.structured_content = structured
        row.block_type = annotation.classified_type
        row.warnings = sorted(
            {
                *row.warnings,
                f"repeated_{annotation.classified_type}_detected",
            }
        )

    source_ref_payloads = {
        block_id: tuple(
            item
            for item in ((row.structured_content or {}).get("sourceRefs") or ())
            if isinstance(item, dict)
        )
        for block_id, row in rows.items()
    }
    continuity_views = [view for view in views if view.block_id not in marginal_block_ids]
    for restoration in restore_cross_page_continuity(continuity_views):
        combined_refs: list[dict[str, Any]] = []
        seen_refs: set[str] = set()
        for block_id in restoration.block_ids:
            for source_ref in source_ref_payloads.get(block_id, ()):
                identity = _source_ref_id(source_ref)
                if identity not in seen_refs:
                    combined_refs.append(source_ref)
                    seen_refs.add(identity)
        if len(combined_refs) < 2:
            continue
        payload = restoration.payload() | {"sourceRefs": combined_refs}
        for block_id in restoration.block_ids:
            row = rows[block_id]
            structured = dict(row.structured_content or {})
            normalization = dict(structured.get("normalization") or {})
            existing = normalization.get("crossPageRestorations")
            restorations = list(existing) if isinstance(existing, list) else []
            restorations.append(payload)
            normalization["crossPageRestorations"] = restorations
            structured["normalization"] = normalization
            row.structured_content = structured
            row.warnings = sorted({*row.warnings, *restoration.quality_flags})


def _canonical_structured_content(block: CanonicalBlock) -> dict[str, Any]:
    return {
        "schemaVersion": "akc-native-block-1.0",
        "canonicalBlockId": block.id,
        "canonicalParentId": block.parent_id,
        "contentLayer": block.content_layer.value,
        "sanitizedHtml": block.sanitized_html,
        "formulaLatex": block.formula_latex,
        "table": (
            block.table.model_dump(mode="json", by_alias=True, exclude_none=True)
            if block.table is not None
            else None
        ),
        "sourceRefs": [
            source_ref.model_dump(mode="json", by_alias=True, exclude_none=True)
            for source_ref in block.source_refs
        ],
    }


def _sensitive_counts(scan: SensitiveScan) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in scan.findings:
        key = finding.kind.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def _validate_canonical_manifest(
    manifest: SuccessfulManifest,
    context: SourceContext,
) -> None:
    canonical = manifest.canonical_document
    requires_canonical = manifest.document_type in _STRUCTURED_NATIVE_TYPES
    if requires_canonical != (canonical is not None):
        raise ValueError("structured native manifest shape is inconsistent")
    if canonical is None:
        return
    if (
        canonical.tenant_id != str(context.tenant_id)
        or canonical.document_id != str(context.document_id)
        or canonical.document_version_id != context.document_version_id
        or canonical.source_sha256 != f"sha256:{context.sha256}"
        or canonical.metadata.get("documentType") != manifest.document_type
    ):
        raise ValueError("canonical document identity is inconsistent")
    expected_text: dict[int, list[str]] = {}
    geometry_rows = canonical.metadata.get("pages")
    if isinstance(geometry_rows, list):
        for item in geometry_rows:
            if isinstance(item, dict) and isinstance(item.get("pageIndex0"), int):
                expected_text.setdefault(int(item["pageIndex0"]) + 1, [])
    for block in canonical.ordered_blocks():
        for source_ref in block.source_refs:
            if (
                source_ref.document_id != str(context.document_id)
                or source_ref.document_version_id != context.document_version_id
            ):
                raise ValueError("canonical block provenance is inconsistent")
        primary_ref = block.source_refs[0]
        text_value = _canonical_block_text(block)
        if text_value:
            expected_text.setdefault(primary_ref.page_number1, []).append(text_value)
        if block.table is not None:
            for cell in block.table.cells:
                if any(
                    source_ref.document_id != str(context.document_id)
                    or source_ref.document_version_id != context.document_version_id
                    for source_ref in cell.source_refs
                ):
                    raise ValueError("canonical table provenance is inconsistent")
    pages = {page.page_number: page for page in manifest.pages}
    if sorted(pages) != sorted(expected_text):
        raise ValueError("canonical page coverage is inconsistent")
    for page_number, parts in expected_text.items():
        if pages[page_number].text != "\n\n".join(parts):
            raise ValueError("canonical page text is inconsistent")


def _read_preview_asset(
    preview_dir: Path,
    filename: str,
) -> tuple[Path, bytes]:
    root = preview_dir.resolve(strict=True)
    candidate = (root / filename).resolve(strict=True)
    if root not in candidate.parents:
        raise ValueError("preview path escaped workspace")
    return candidate, candidate.read_bytes()


def analysis_advisory_lock_key(task_id: uuid.UUID) -> int:
    digest = hashlib.sha256(b"akc-analysis-task-v1\0" + task_id.bytes).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def analysis_claim_statement(
    *,
    now: datetime,
    dialect_name: str,
    task_id: uuid.UUID | None = None,
) -> Any:
    statement = (
        select(OutboxEvent)
        .join(
            AnalysisTask,
            AnalysisTask.id == OutboxEvent.aggregate_id,
        )
        .where(
            OutboxEvent.event_type == _EVENT_TYPE,
            OutboxEvent.published_at.is_(None),
            OutboxEvent.dead_lettered_at.is_(None),
            OutboxEvent.available_at <= now,
            AnalysisTask.status.in_(("queued", "running")),
            AnalysisTask.available_at <= now,
            or_(
                AnalysisTask.status == "queued",
                AnalysisTask.lease_expires_at.is_(None),
                AnalysisTask.lease_expires_at <= now,
            ),
        )
        .order_by(OutboxEvent.available_at, OutboxEvent.created_at, OutboxEvent.id)
        .limit(1)
    )
    if task_id is not None:
        statement = statement.where(AnalysisTask.id == task_id)
    if dialect_name == "postgresql":
        statement = statement.with_for_update(of=OutboxEvent, skip_locked=True)
    return statement


class AnalysisWorker:
    """Claim, sandbox, and atomically persist native analysis tasks."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        store: ObjectStore,
        runtime: AnalysisRuntime,
        pdf_secret_store: PdfSecretStore | None = None,
    ) -> None:
        if runtime.env == "production" and engine.dialect.name != "postgresql":
            raise RuntimeError("production_analysis_requires_postgresql")
        self._engine = engine
        self._store = store
        self._runtime = runtime
        self._pdf_secret_store = pdf_secret_store
        self._sessions = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self._stopping = False
        self._sqlite_lock = asyncio.Lock()

    @property
    def stopping(self) -> bool:
        return self._stopping

    def request_stop(self) -> None:
        self._stopping = True

    def _retry_delay(self, task_id: uuid.UUID, attempt: int) -> float:
        base = float(
            min(
                self._runtime.backoff_max_seconds,
                self._runtime.backoff_base_seconds * (2 ** max(0, attempt - 1)),
            )
        )
        if self._runtime.backoff_jitter_ratio == 0:
            return base
        digest = hashlib.sha256(task_id.bytes + attempt.to_bytes(4, "big")).digest()
        fraction = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
        multiplier = 1 + ((fraction * 2) - 1) * self._runtime.backoff_jitter_ratio
        return max(0.1, base * multiplier)

    async def _claim(
        self,
        connection: AsyncConnection,
        *,
        task_id: uuid.UUID | None,
    ) -> tuple[AnalysisClaim | None, int | None]:
        now = utcnow()
        async with AsyncSession(
            bind=connection,
            expire_on_commit=False,
            autoflush=False,
        ) as session:
            event = await session.scalar(
                analysis_claim_statement(
                    now=now,
                    dialect_name=connection.dialect.name,
                    task_id=task_id,
                )
            )
            if event is None:
                await session.commit()
                return None, None
            task = await session.scalar(
                select(AnalysisTask).where(AnalysisTask.id == event.aggregate_id).with_for_update()
            )
            if (
                task is None
                or task.tenant_id != event.tenant_id
                or str(event.payload.get("task_id", "")) != str(event.aggregate_id)
            ):
                event.attempts += 1
                event.last_error = "analysis_task_missing_or_mismatched"
                event.dead_lettered_at = now
                event.published_at = now
                await session.commit()
                record_attempt("dead_letter")
                return None, None
            if task.attempt_count >= task.max_attempts:
                await self._terminal_failure_in_session(
                    session,
                    task=task,
                    event=event,
                    code="PARSER_PROCESS_CRASH",
                    now=now,
                )
                await session.commit()
                record_attempt("dead_letter")
                return None, None
            lock_key: int | None = None
            if connection.dialect.name == "postgresql":
                lock_key = analysis_advisory_lock_key(task.id)
                acquired = bool(
                    await session.scalar(
                        text("SELECT pg_try_advisory_lock(:lock_key)"),
                        {"lock_key": lock_key},
                    )
                )
                if not acquired:
                    defer_until = now + timedelta(seconds=1)
                    event.available_at = defer_until
                    task.available_at = defer_until
                    await session.commit()
                    return None, None
            token = uuid.uuid4()
            attempt = task.attempt_count + 1
            lease_until = now + timedelta(seconds=self._runtime.lease_seconds)
            task.status = "running"
            task.attempt_count = attempt
            task.lease_token = token
            task.lease_expires_at = lease_until
            task.available_at = lease_until
            task.last_error_code = None
            task.started_at = task.started_at or now
            task.updated_at = now
            event.attempts = attempt
            event.available_at = lease_until
            event.last_error = None
            document = await session.scalar(
                select(Document)
                .where(
                    Document.tenant_id == task.tenant_id,
                    Document.id == task.document_id,
                )
                .with_for_update()
            )
            project = (
                await session.scalar(
                    select(Project)
                    .where(
                        Project.tenant_id == task.tenant_id,
                        Project.id == task.project_id,
                    )
                    .with_for_update()
                )
                if document is not None
                else None
            )
            if (
                document is None
                or project is None
                or getattr(document, "deletion_requested_at", None) is not None
                or getattr(project, "deletion_requested_at", None) is not None
            ):
                await self._terminal_failure_in_session(
                    session,
                    task=task,
                    event=event,
                    code="DOCUMENT_DELETED",
                    now=now,
                )
                await session.commit()
                if lock_key is not None:
                    await self._release_advisory_lock(connection, lock_key)
                record_attempt("dead_letter")
                return None, None
            if (
                task.document_version != document.active_version
                or task.source_file_id != document.source_file_id
            ):
                task.status = "dead_letter"
                task.last_error_code = "SOURCE_VERSION_CHANGED"
                task.lease_token = None
                task.lease_expires_at = None
                task.completed_at = now
                task.updated_at = now
                event.last_error = "SOURCE_VERSION_CHANGED"
                event.dead_lettered_at = now
                event.published_at = now
                await session.commit()
                if lock_key is not None:
                    await self._release_advisory_lock(connection, lock_key)
                record_attempt("stale")
                return None, None
            document.status = "PREFLIGHTING"
            await session.commit()
            return (
                AnalysisClaim(
                    event_id=event.id,
                    task_id=task.id,
                    tenant_id=task.tenant_id,
                    document_id=task.document_id,
                    document_version=task.document_version,
                    source_file_id=task.source_file_id,
                    lease_token=token,
                    attempt=attempt,
                ),
                lock_key,
            )

    async def _release_advisory_lock(
        self,
        connection: AsyncConnection,
        lock_key: int,
    ) -> None:
        try:
            released = bool(
                await connection.scalar(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            )
            if not released:
                raise RuntimeError("analysis_advisory_unlock_failed")
        except BaseException:
            await connection.invalidate()
            raise

    async def _source_context(self, claim: AnalysisClaim) -> SourceContext:
        async with self._sessions() as session:
            task = await session.scalar(
                select(AnalysisTask).where(
                    AnalysisTask.id == claim.task_id,
                    AnalysisTask.tenant_id == claim.tenant_id,
                    AnalysisTask.lease_token == claim.lease_token,
                    AnalysisTask.status == "running",
                )
            )
            if task is None:
                raise StaleAnalysisLease
            document = await session.scalar(
                select(Document).where(
                    Document.id == claim.document_id,
                    Document.tenant_id == claim.tenant_id,
                )
            )
            project = await session.scalar(
                select(Project).where(
                    Project.id == task.project_id,
                    Project.tenant_id == claim.tenant_id,
                )
            )
            source = await session.scalar(
                select(SourceFile).where(
                    SourceFile.id == claim.source_file_id,
                    SourceFile.tenant_id == claim.tenant_id,
                )
            )
        if task is None:
            raise StaleAnalysisLease
        if (
            document is None
            or project is None
            or source is None
            or task.document_version != claim.document_version
            or document.active_version != claim.document_version
            or document.source_file_id != source.id
            or source.project_id != document.project_id
            or getattr(document, "deletion_requested_at", None) is not None
            or getattr(project, "deletion_requested_at", None) is not None
        ):
            raise AnalysisAttemptError("SOURCE_CONTEXT_INVALID", retryable=False)
        use_derivative = (
            source.cdr_status == "sanitized"
            and source.sanitized_storage_key is not None
            and source.sanitized_sha256 is not None
            and source.sanitized_size_bytes is not None
        )
        if use_derivative:
            assert source.sanitized_storage_key is not None
            assert source.sanitized_sha256 is not None
            assert source.sanitized_size_bytes is not None
            storage_key = source.sanitized_storage_key
            input_sha256 = source.sanitized_sha256
            input_size = source.sanitized_size_bytes
            storage_bucket: Literal["source", "derived"] = "derived"
            expected_prefix = (
                f"tenants/{claim.tenant_id}/projects/{document.project_id}/derived/cdr/"
            )
        else:
            storage_key = source.storage_key
            input_sha256 = source.sha256
            input_size = source.size_bytes
            storage_bucket = "source"
            expected_prefix = f"tenants/{claim.tenant_id}/projects/{document.project_id}/sources/"
        if not storage_key.startswith(expected_prefix):
            raise AnalysisAttemptError("SOURCE_CONTEXT_INVALID", retryable=False)
        return SourceContext(
            tenant_id=claim.tenant_id,
            project_id=document.project_id,
            document_id=document.id,
            document_version_id=f"{document.id}:v{claim.document_version}",
            source_file_id=source.id,
            filename=source.safe_filename,
            content_type=source.mime_type,
            size_bytes=input_size,
            sha256=input_sha256,
            storage_key=storage_key,
            storage_bucket=storage_bucket,
            original_sha256=source.sha256,
            cdr_status=source.cdr_status,
            cdr_provider=source.cdr_provider,
            cdr_revision=source.cdr_revision,
            created_at=_aware(document.created_at),
            retrieved_at=_aware(source.created_at),
        )

    def _sandbox_request(
        self,
        *,
        workspace: Path,
        source_path: Path,
        preview_dir: Path,
        context: SourceContext,
    ) -> dict[str, Any]:
        runtime = self._runtime
        return {
            "workspace": str(workspace),
            "source_path": str(source_path),
            "preview_dir": str(preview_dir),
            "filename": context.filename,
            "content_type": context.content_type,
            "sha256": context.sha256,
            "original_source_sha256": context.original_sha256,
            "cdr": {
                "status": context.cdr_status,
                "provider": context.cdr_provider,
                "revision": context.cdr_revision,
                "input_bucket": context.storage_bucket,
            },
            "tenant_id": str(context.tenant_id),
            "document_id": str(context.document_id),
            "document_version_id": context.document_version_id,
            "created_at": context.created_at.isoformat(),
            "retrieved_at": context.retrieved_at.isoformat(),
            "max_upload_bytes": runtime.max_upload_bytes,
            "max_pages": runtime.max_pages,
            "max_archive_files": runtime.max_archive_files,
            "max_archive_uncompressed_bytes": runtime.max_archive_uncompressed_bytes,
            "max_archive_ratio": runtime.max_archive_ratio,
            "max_extracted_chars_per_page": runtime.max_extracted_chars_per_page,
            "max_extracted_chars_total": runtime.max_extracted_chars_total,
            "preview_enabled": runtime.preview_enabled,
            "preview_dpi": runtime.preview_dpi,
            "preview_max_long_edge": runtime.preview_max_long_edge,
            "preview_thumbnail_long_edge": runtime.preview_thumbnail_long_edge,
            "preview_max_pixels": runtime.preview_max_pixels,
            "preview_max_bytes_per_asset": runtime.preview_max_bytes_per_asset,
            "preview_max_total_bytes": runtime.preview_max_total_bytes,
            "inference_raster_dpis": [200, 300],
            "inference_raster_max_pixels": runtime.inference_raster_max_pixels,
            "inference_raster_max_bytes_per_asset": (runtime.inference_raster_max_bytes_per_asset),
            "inference_raster_max_total_bytes": (runtime.inference_raster_max_total_bytes),
            "child_memory_bytes": runtime.child_memory_bytes,
            "child_file_bytes": runtime.child_file_bytes,
            "child_open_files": runtime.child_open_files,
            "timeout_seconds": runtime.attempt_timeout_seconds,
        }

    @staticmethod
    def _sanitized_subprocess_environment(workspace: Path) -> dict[str, str]:
        allowed = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}
        }
        allowed.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "HOME": str(workspace),
                "TMPDIR": str(workspace),
                "TMP": str(workspace),
                "TEMP": str(workspace),
            }
        )
        return allowed

    async def _invoke_sandbox(
        self,
        *,
        request_path: Path,
        result_path: Path,
        workspace: Path,
        pdf_password: bytes | None,
    ) -> SuccessfulManifest | FailedManifest:
        child_command = [
            sys.executable,
            "-I",
            "-m",
            "akc_worker_document.sandbox_runner",
            str(request_path),
            str(result_path),
        ]
        if self._runtime.sandbox_launcher == "bubblewrap":
            launcher = shutil.which("bwrap")
            if launcher is None or os.name == "nt":
                raise AnalysisAttemptError(
                    "PARSER_SANDBOX_UNAVAILABLE",
                    retryable=False,
                )
            child_command = [
                launcher,
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--ro-bind",
                "/",
                "/",
                "--bind",
                str(workspace),
                str(workspace),
                "--chdir",
                str(workspace),
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--",
                *child_command,
            ]
        process = await asyncio.create_subprocess_exec(
            *child_command,
            cwd=workspace,
            env=self._sanitized_subprocess_environment(workspace),
            stdin=(
                asyncio.subprocess.PIPE if pdf_password is not None else asyncio.subprocess.DEVNULL
            ),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            password_payload = (
                len(pdf_password).to_bytes(4, "big") + pdf_password
                if pdf_password is not None
                else None
            )
            await asyncio.wait_for(
                process.communicate(password_payload),
                timeout=self._runtime.attempt_timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            record_sandbox_termination("timeout")
            raise AnalysisAttemptError("PARSER_TIMEOUT", retryable=True) from exc
        exists, result_size, result_text = await asyncio.to_thread(
            _read_sandbox_result,
            result_path,
        )
        if process.returncode != 0 or not exists:
            record_sandbox_termination("crash")
            raise AnalysisAttemptError("PARSER_PROCESS_CRASH", retryable=True)
        if result_size <= 0 or result_size > self._runtime.max_result_bytes:
            record_sandbox_termination("oversize")
            raise AnalysisAttemptError("PARSER_RESULT_TOO_LARGE", retryable=False)
        try:
            payload = json.loads(result_text)
            if not isinstance(payload, dict):
                raise ValueError("manifest must be an object")
            if payload.get("ok") is True:
                manifest: SuccessfulManifest | FailedManifest = SuccessfulManifest.model_validate(
                    payload
                )
            else:
                manifest = FailedManifest.model_validate(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            raise AnalysisAttemptError("PARSER_RESULT_INVALID", retryable=False) from exc
        return manifest

    async def _sandbox_analysis(
        self,
        context: SourceContext,
    ) -> tuple[SuccessfulManifest, Path, tempfile.TemporaryDirectory[str]]:
        temporary = tempfile.TemporaryDirectory(prefix="akc-analysis-")
        workspace = Path(temporary.name)
        source_path = workspace / "source.bin"
        preview_dir = workspace / "previews"
        request_path = workspace / "request.json"
        result_path = workspace / "result.json"
        secret_lease: PdfSecretLease | None = None
        try:
            with source_path.open("w+b") as stream:
                if context.storage_bucket == "derived":
                    payload = await self._store.read_derived(context.storage_key)
                    stream.write(payload)
                else:
                    await self._store.download_source(context.storage_key, stream)
            observed_size, digest = await asyncio.to_thread(
                _inspect_downloaded_source,
                source_path,
            )
            if observed_size != context.size_bytes or digest != context.sha256:
                raise AnalysisAttemptError("SOURCE_OBJECT_INVALID", retryable=False)
            if context.filename.casefold().endswith(".pdf") and self._pdf_secret_store is not None:
                binding = PdfSecretBinding(
                    tenant_id=context.tenant_id,
                    document_id=context.document_id,
                    source_sha256=context.original_sha256,
                )
                try:
                    secret_lease = await self._pdf_secret_store.acquire(binding)
                except PdfSecretError as exc:
                    if exc.code not in {"PDF_PASSWORD_REQUIRED", "PDF_PASSWORD_EXPIRED"}:
                        raise AnalysisAttemptError(
                            exc.code,
                            retryable=exc.code == "PDF_SECRET_STORE_UNAVAILABLE",
                        ) from exc
            await asyncio.to_thread(
                request_path.write_text,
                json.dumps(
                    self._sandbox_request(
                        workspace=workspace,
                        source_path=source_path,
                        preview_dir=preview_dir,
                        context=context,
                    )
                    | {"pdf_password_from_stdin": secret_lease is not None},
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            manifest = await self._invoke_sandbox(
                request_path=request_path,
                result_path=result_path,
                workspace=workspace,
                pdf_password=(secret_lease.reveal() if secret_lease is not None else None),
            )
            if isinstance(manifest, FailedManifest):
                if secret_lease is not None and self._pdf_secret_store is not None:
                    await self._pdf_secret_store.finish(secret_lease, success=False)
                    secret_lease = None
                raise AnalysisAttemptError(
                    manifest.error_code,
                    retryable=manifest.retryable,
                )
            page_numbers = [page.page_number for page in manifest.pages]
            if (
                manifest.source_sha256 != context.sha256
                or len(page_numbers) > self._runtime.max_pages
                or page_numbers != list(range(1, len(page_numbers) + 1))
            ):
                raise AnalysisAttemptError("PARSER_RESULT_INVALID", retryable=False)
            try:
                _validate_canonical_manifest(manifest, context)
            except ValueError as exc:
                raise AnalysisAttemptError(
                    "PARSER_RESULT_INVALID",
                    retryable=False,
                ) from exc
            if secret_lease is not None and self._pdf_secret_store is not None:
                await self._pdf_secret_store.finish(secret_lease, success=True)
                secret_lease = None
            return manifest, preview_dir, temporary
        except BaseException:
            if secret_lease is not None and self._pdf_secret_store is not None:
                await self._pdf_secret_store.finish(secret_lease, success=False)
            temporary.cleanup()
            raise

    async def _upload_assets(
        self,
        *,
        manifest: SuccessfulManifest,
        preview_dir: Path,
        context: SourceContext,
        claim: AnalysisClaim,
    ) -> dict[int, UploadedAssets]:
        uploaded: dict[int, UploadedAssets] = {}
        for page in manifest.pages:
            preview = page.preview
            if preview.status != "available":
                record_preview(available=False)
                uploaded[page.page_number] = UploadedAssets(
                    None,
                    None,
                    None,
                    None,
                    (),
                    (),
                )
                continue
            assert (
                preview.preview is not None
                and preview.thumbnail is not None
                and preview.inference_rasters is not None
            )
            base_key = (
                f"tenants/{context.tenant_id}/projects/{context.project_id}/"
                f"documents/{context.document_id}/analysis/{context.sha256}/"
                f"tasks/{claim.task_id}/leases/{claim.lease_token}/"
                f"pages/{page.page_number}"
            )
            assets: dict[str, tuple[AssetManifest, str]] = {}
            for kind, descriptor in (
                ("preview", preview.preview),
                ("thumbnail", preview.thumbnail),
            ):
                try:
                    _candidate, data = await asyncio.to_thread(
                        _read_preview_asset,
                        preview_dir,
                        descriptor.filename,
                    )
                except (OSError, ValueError) as exc:
                    raise AnalysisAttemptError(
                        "PARSER_RESULT_INVALID",
                        retryable=False,
                    ) from exc
                if (
                    len(data) != descriptor.size_bytes
                    or hashlib.sha256(data).hexdigest() != descriptor.sha256
                    or len(data) > self._runtime.preview_max_bytes_per_asset
                ):
                    raise AnalysisAttemptError(
                        "PARSER_RESULT_INVALID",
                        retryable=False,
                    )
                key = f"{base_key}/{kind}.png"
                await self._store.put_derived(key, data)
                assets[kind] = (descriptor, key)
            inference_assets: list[tuple[InferenceRasterManifest, str]] = []
            for inference_descriptor in preview.inference_rasters:
                try:
                    _candidate, data = await asyncio.to_thread(
                        _read_preview_asset,
                        preview_dir,
                        inference_descriptor.filename,
                    )
                except (OSError, ValueError) as exc:
                    raise AnalysisAttemptError(
                        "PARSER_RESULT_INVALID",
                        retryable=False,
                    ) from exc
                if (
                    len(data) != inference_descriptor.size_bytes
                    or hashlib.sha256(data).hexdigest() != inference_descriptor.sha256
                    or len(data) > self._runtime.inference_raster_max_bytes_per_asset
                    or inference_descriptor.width * inference_descriptor.height
                    > self._runtime.inference_raster_max_pixels
                ):
                    raise AnalysisAttemptError(
                        "PARSER_RESULT_INVALID",
                        retryable=False,
                    )
                key = f"{base_key}/inference-{inference_descriptor.dpi}.png"
                await self._store.put_derived(key, data)
                inference_assets.append((inference_descriptor, key))
            record_preview(available=True)
            uploaded[page.page_number] = UploadedAssets(
                preview_key=assets["preview"][1],
                thumbnail_key=assets["thumbnail"][1],
                preview=assets["preview"][0],
                thumbnail=assets["thumbnail"][0],
                inference_raster_keys=tuple(key for _descriptor, key in inference_assets),
                inference_rasters=tuple(descriptor for descriptor, _key in inference_assets),
            )
        return uploaded

    async def _delete_uploaded_assets(
        self,
        assets: Mapping[int, UploadedAssets],
    ) -> None:
        """Remove only this lease's objects after a fenced persistence failure."""

        for page_assets in assets.values():
            for key in (
                page_assets.preview_key,
                page_assets.thumbnail_key,
                *page_assets.inference_raster_keys,
            ):
                if key is None:
                    continue
                try:
                    await self._store.delete("derived", key)
                except Exception:
                    # Never include the object key because it embeds tenant IDs.
                    logger.exception("failed to clean fenced analysis preview")

    @staticmethod
    def _page_preflight(
        text_value: str,
        *,
        image_coverage: float,
        width_pt: float | None,
        height_pt: float | None,
        canonical_blocks: list[CanonicalBlock],
    ) -> dict[str, Any]:
        replacement = text_value.count("\ufffd") / max(1, len(text_value))
        controls = sum(ord(char) < 32 and char not in "\n\r\t" for char in text_value)
        lines = [line.strip() for line in text_value.splitlines() if line.strip()]
        fragmented = sum(len(line) <= 1 for line in lines) / len(lines) if lines else 1.0
        whitespace_runs = len(re.findall(r"[ \t]{8,}|\n{4,}", text_value))
        whitespace_anomaly = min(
            1.0,
            whitespace_runs / max(1, len(lines)) + controls / max(1, len(text_value)),
        )
        reading_order_score = (
            max(
                0.0,
                1.0 - fragmented * 0.25 - whitespace_anomaly * 0.50 - replacement * 10,
            )
            if text_value
            else 0.0
        )
        page_area = max(1.0, (width_pt or 612.0) * (height_pt or 792.0))
        expected_capacity = max(800.0, 3_500.0 * page_area / (612.0 * 792.0))
        native_coverage = min(
            1.0,
            sum(not character.isspace() for character in text_value) / expected_capacity,
        )
        bboxes = [
            block.source_refs[0].bbox1000.as_tuple()
            for block in canonical_blocks
            if block.source_refs and block.source_refs[0].bbox1000 is not None
        ]
        estimated_columns = 0
        if text_value:
            estimated_columns = 1
        if len(bboxes) >= 4:
            centers = sorted((bbox[0] + bbox[2]) / 2 for bbox in bboxes)
            widest_gap = max(
                (right - left for left, right in pairwise(centers)),
                default=0,
            )
            if widest_gap >= 250:
                estimated_columns = 2
        return {
            "native_text_chars": len(text_value),
            "native_words": len(text_value.split()),
            "invalid_char_ratio": controls / max(1, len(text_value)),
            "replacement_char_ratio": replacement,
            "image_coverage": image_coverage,
            "suspicious_text_layer": replacement > 0.001,
            "native_text_coverage": native_coverage,
            "whitespace_anomaly_score": whitespace_anomaly,
            "native_reading_order_score": reading_order_score,
            "estimated_columns": estimated_columns,
            "script_distribution": detect_script_distribution(text_value),
            "unknown_visual_metrics": [
                "handwriting_probability",
                "rotation_degrees",
                "skew_degrees",
                "blur_score",
                "contrast_score",
                "small_text_score",
            ],
        }

    async def _persist_success(
        self,
        *,
        claim: AnalysisClaim,
        context: SourceContext,
        manifest: SuccessfulManifest,
        assets: Mapping[int, UploadedAssets],
    ) -> None:
        now = utcnow()
        async with self._sessions.begin() as session:
            task = await session.scalar(
                select(AnalysisTask)
                .where(
                    AnalysisTask.id == claim.task_id,
                    AnalysisTask.tenant_id == claim.tenant_id,
                )
                .with_for_update()
            )
            if task is None or task.status != "running" or task.lease_token != claim.lease_token:
                raise StaleAnalysisLease
            document = await session.scalar(
                select(Document)
                .where(
                    Document.id == claim.document_id,
                    Document.tenant_id == claim.tenant_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            try:
                routing_runtime = await load_routing_runtime(
                    session,
                    tenant_id=claim.tenant_id,
                    project_id=context.project_id,
                    dominant_language=(
                        document.language_codes[0]
                        if document is not None and document.language_codes
                        else None
                    ),
                )
            except LookupError as exc:
                raise AnalysisAttemptError(
                    "DOCUMENT_DELETED",
                    retryable=False,
                ) from exc
            project = routing_runtime.project
            if (
                document is None
                or getattr(document, "deletion_requested_at", None) is not None
                or getattr(project, "deletion_requested_at", None) is not None
            ):
                raise AnalysisAttemptError("DOCUMENT_DELETED", retryable=False)
            if (
                document.source_file_id != claim.source_file_id
                or context.document_version_id != f"{document.id}:v{document.active_version}"
            ):
                raise StaleAnalysisLease
            document_version = await session.scalar(
                select(DocumentVersion)
                .where(
                    DocumentVersion.tenant_id == claim.tenant_id,
                    DocumentVersion.document_id == claim.document_id,
                    DocumentVersion.version == document.active_version,
                )
                .with_for_update()
            )
            if (
                document_version is None
                or document_version.source_file_id != claim.source_file_id
                or (
                    document_version.source_sha256 is not None
                    and document_version.source_sha256 != context.original_sha256
                )
            ):
                raise StaleAnalysisLease
            tenant = routing_runtime.tenant
            try:
                await reserve_free_usage(
                    session,
                    tenant_id=claim.tenant_id,
                    plan_code=tenant.plan_code,
                    operation_key=f"analyze:{task.id}:pages",
                    delta=FreeUsageDelta(pages=len(manifest.pages)),
                    caps=FreeTierCaps(
                        files=self._runtime.free_daily_file_cap,
                        pages=self._runtime.free_daily_page_cap,
                        gpu_cost_usd=(self._runtime.free_daily_gpu_cost_usd_cap),
                    ),
                    now=now,
                )
            except FreeTierCapExceeded as exc:
                record_abuse_control_decision(
                    control="free_page_cap",
                    result="capped",
                )
                raise AnalysisAttemptError(
                    "FREE_DAILY_PAGE_CAP",
                    retryable=False,
                ) from exc
            old_page_ids = list(
                (
                    await session.scalars(
                        select(Page.id).where(
                            Page.tenant_id == claim.tenant_id,
                            Page.document_id == claim.document_id,
                        )
                    )
                ).all()
            )
            if old_page_ids:
                await session.execute(
                    delete(ReviewItem).where(
                        ReviewItem.tenant_id == claim.tenant_id,
                        ReviewItem.document_id == claim.document_id,
                    )
                )
                await session.execute(
                    delete(PageAsset).where(
                        PageAsset.tenant_id == claim.tenant_id,
                        PageAsset.page_id.in_(old_page_ids),
                    )
                )
            await session.execute(
                delete(Block).where(
                    Block.tenant_id == claim.tenant_id,
                    Block.document_id == claim.document_id,
                )
            )
            await session.execute(
                delete(Page).where(
                    Page.tenant_id == claim.tenant_id,
                    Page.document_id == claim.document_id,
                )
            )
            canonical = manifest.canonical_document
            canonical_blocks_by_page: dict[int, list[CanonicalBlock]] = {}
            if canonical is not None:
                for canonical_block in canonical.ordered_blocks():
                    page_number = canonical_block.source_refs[0].page_number1
                    canonical_blocks_by_page.setdefault(page_number, []).append(canonical_block)
            block_count = 0
            preview_count = 0
            route_policy_versions: set[str] = set()
            pages_by_number: dict[int, Page] = {}
            normalization_rows: dict[str, Block] = {}
            normalization_views: list[NormalizationBlock] = []
            for parsed_page in manifest.pages:
                canonical_page_blocks = canonical_blocks_by_page.get(
                    parsed_page.page_number,
                    [],
                )
                injection = detect_prompt_injection(parsed_page.text)
                sensitive_scan = detect_sensitive_data(parsed_page.text)
                sensitive_counts = _sensitive_counts(sensitive_scan)
                page_context = routing_runtime.context
                if sensitive_scan.has_secret:
                    # Secret-bearing content may continue through local processing,
                    # but it cannot be sent to an external fallback without a new,
                    # explicit confirmation made after the warning is shown.
                    page_context = page_context.model_copy(
                        update={
                            "data_policy": page_context.data_policy.model_copy(
                                update={"external_api_allowed": False}
                            ),
                            "ready_routes": frozenset(
                                route
                                for route in page_context.ready_routes
                                if route != Route.MISTRAL_FALLBACK
                            ),
                        }
                    )
                metrics = self._page_preflight(
                    parsed_page.text,
                    image_coverage=parsed_page.image_coverage,
                    width_pt=parsed_page.width_pt,
                    height_pt=parsed_page.height_pt,
                    canonical_blocks=canonical_page_blocks,
                )
                page_assets = assets.get(
                    parsed_page.page_number,
                    UploadedAssets(None, None, None, None, (), ()),
                )
                preprocessing_transform = (
                    page_assets.inference_rasters[0].transform
                    if page_assets.inference_rasters
                    else None
                )
                if preprocessing_transform is not None:
                    unknown_metrics = metrics.get("unknown_visual_metrics")
                    if isinstance(unknown_metrics, list):
                        metrics["unknown_visual_metrics"] = [
                            value
                            for value in unknown_metrics
                            if value not in {"rotation_degrees", "skew_degrees", "contrast_score"}
                        ]
                native_block_count = (
                    len(canonical_page_blocks)
                    if canonical is not None
                    else (1 if parsed_page.text else 0)
                )
                table_density = sum(
                    block.type.value == "table" for block in canonical_page_blocks
                ) / max(1, native_block_count)
                formula_density = sum(
                    block.type.value == "formula" for block in canonical_page_blocks
                ) / max(1, native_block_count)
                router_metrics = PageMetrics(
                    page_index0=parsed_page.page_number - 1,
                    width=max(1, round(parsed_page.width_pt or 1000)),
                    height=max(1, round(parsed_page.height_pt or 1000)),
                    native_text_chars=int(metrics["native_text_chars"]),
                    native_word_count=int(metrics["native_words"]),
                    native_block_count=native_block_count,
                    native_text_coverage=float(metrics["native_text_coverage"]),
                    image_coverage=parsed_page.image_coverage,
                    invalid_unicode_ratio=float(metrics["invalid_char_ratio"]),
                    replacement_char_ratio=float(metrics["replacement_char_ratio"]),
                    whitespace_anomaly_score=float(metrics["whitespace_anomaly_score"]),
                    native_reading_order_score=float(metrics["native_reading_order_score"]),
                    estimated_columns=int(metrics["estimated_columns"]),
                    table_density=table_density,
                    formula_density=formula_density,
                    chart_probability=(
                        sum(block.type.value == "figure" for block in canonical_page_blocks)
                        / max(1, native_block_count)
                    ),
                    # The native manifest has no visual estimator for these
                    # fields. Neutral conservative sentinels are persisted with
                    # an explicit unknown-metric list rather than fake 1.0s.
                    handwriting_probability=0.5,
                    rotation_degrees=(
                        preprocessing_transform.orientation.angle_degrees
                        if preprocessing_transform is not None
                        else 0
                    ),
                    skew_degrees=(
                        abs(preprocessing_transform.deskew.angle_degrees)
                        if preprocessing_transform is not None
                        else 0.0
                    ),
                    blur_score=0.5,
                    contrast_score=0.5,
                    small_text_score=0.5,
                    script_distribution=dict(metrics["script_distribution"]),
                    suspected_prompt_injection=injection.suspected,
                )
                route_decision = select_first_route(
                    page_context,
                    router_metrics,
                )
                route_policy_versions.add(route_decision.policy_version)
                technical_class = classify_page(router_metrics)
                difficulty_score = preflight_difficulty(router_metrics)
                quality_blocks = [
                    quality_block_from_canonical(block) for block in canonical_page_blocks
                ]
                if not quality_blocks and parsed_page.text:
                    quality_blocks = [
                        PageQualityBlock(
                            block_id=f"native-page-{parsed_page.page_number}",
                            block_type="paragraph",
                            source_text=parsed_page.text,
                            candidate_text=parsed_page.text,
                            bbox1000=(1, 1, 999, 999),
                            has_provenance=True,
                        )
                    ]
                quality = evaluate_page_quality(
                    quality_blocks,
                    high_risk=(page_context.risk_tier.value == "high"),
                    failed_attempts=max(0, claim.attempt - 1),
                )
                native_signal = quality.signal
                native_attempt_number = 1
                native_max_attempts = min(5, max(2, route_decision.max_attempts))
                if route_decision.route != Route.NATIVE:
                    native_signal = native_signal.model_copy(
                        update={
                            "passed": False,
                            "empty_output": False,
                            "repetition_failure": False,
                            "engine_specific_failure": False,
                        }
                    )
                escalation = decide_escalation(
                    current_route=Route.NATIVE,
                    signal=native_signal,
                    attempt_number=native_attempt_number,
                    max_attempts=native_max_attempts,
                    context=page_context,
                )
                effective_route = route_decision.route
                if route_decision.route == Route.NATIVE and escalation.route is not None:
                    effective_route = escalation.route
                accepted_native = (
                    route_decision.route == Route.NATIVE
                    and escalation.action == EscalationAction.ACCEPT
                )
                preview_reason = (
                    parsed_page.preview.reason
                    if parsed_page.preview.status == "unavailable"
                    else None
                )
                native_structure: dict[str, Any] | None = None
                if canonical is not None:
                    native_structure = {
                        "schemaVersion": canonical.schema_version,
                        "blockCount": len(canonical_page_blocks),
                        "sourceLocationScheme": canonical.metadata.get("sourceLocationScheme"),
                    }
                    if parsed_page.page_number == 1:
                        native_structure["documentMetadata"] = canonical.metadata
                preprocessing = (
                    preprocessing_transform.model_dump(mode="json")
                    if preprocessing_transform is not None
                    else None
                )
                page = Page(
                    tenant_id=claim.tenant_id,
                    document_id=claim.document_id,
                    page_number=parsed_page.page_number,
                    width_pt=parsed_page.width_pt,
                    height_pt=parsed_page.height_pt,
                    rotation=(
                        preprocessing_transform.orientation.angle_degrees
                        if preprocessing_transform is not None
                        else 0
                    ),
                    status="COMPLETED" if accepted_native else "NEEDS_REVIEW",
                    route=effective_route.value,
                    route_policy_version=route_decision.policy_version,
                    thumbnail_key=page_assets.thumbnail_key,
                    preflight_metrics={
                        **metrics,
                        "suspected_prompt_injection": injection.suspected,
                        "prompt_injection_risk": injection.risk.value,
                        "prompt_injection_rules": [signal.rule_id for signal in injection.signals],
                        "sensitive_data": {
                            "has_pii": sensitive_scan.has_pii,
                            "has_secret": sensitive_scan.has_secret,
                            "external_transfer_requires_confirmation": (
                                sensitive_scan.external_transfer_requires_confirmation
                            ),
                            "counts": sensitive_counts,
                            "detector_limitations": [
                                "pattern detection can miss sensitive data",
                                "pattern detection can produce false positives",
                            ],
                        },
                        "route_reasons": list(route_decision.reason_codes),
                        "route_profile": route_decision.route_profile.value,
                        "expected_credits": route_decision.expected_credits,
                        "table_density": table_density,
                        "formula_density": formula_density,
                        "chart_probability": router_metrics.chart_probability,
                        "preprocessing": preprocessing,
                        "normalization": parsed_page.normalization.model_dump(
                            mode="json",
                            by_alias=True,
                        ),
                        "technical_class": technical_class.value,
                        "difficulty_score": difficulty_score,
                        "router_metrics": router_metrics.model_dump(
                            mode="json",
                            by_alias=False,
                        ),
                        "processing_mode": page_context.mode.value,
                        "ready_routes": sorted(route.value for route in page_context.ready_routes),
                        "preview_status": parsed_page.preview.status,
                        "preview_unavailable_reason": preview_reason,
                        **(
                            {"native_structure": native_structure}
                            if native_structure is not None
                            else {}
                        ),
                    },
                    quality_metrics={
                        "schema_valid": bool(quality_blocks),
                        "source_coverage": (quality.evaluation.vector.provenance_coverage),
                        "state": (
                            "verified"
                            if accepted_native
                            and quality.evaluation.status.value == "PASS"
                            and not injection.suspected
                            else "warning"
                            if accepted_native
                            else "review"
                        ),
                        "vector": quality.vector_payload,
                        "findings": quality.findings_payload,
                        "evaluation": quality.evaluation_payload,
                        "escalation": escalation.model_dump(
                            mode="json",
                            by_alias=False,
                        ),
                        "prompt_injection_advisory": injection.suspected,
                    },
                )
                session.add(page)
                await session.flush()
                page_attempt = await create_page_attempt(
                    session,
                    tenant_id=claim.tenant_id,
                    page_id=page.id,
                    attempt_number=1,
                    trigger="analysis",
                    initial_state=PageState.VALIDATING,
                    route=Route.NATIVE.value,
                    route_profile=route_decision.route_profile.value,
                    route_policy_version=route_decision.policy_version,
                    max_attempts=native_max_attempts,
                    analysis_task_id=task.id,
                    quality_vector=quality.vector_payload,
                    quality_findings=quality.findings_payload,
                    quality_evaluation=quality.evaluation_payload,
                    escalation_decision=escalation.model_dump(
                        mode="json",
                        by_alias=False,
                    ),
                    reason="native_result_ready_for_validation",
                    payload={
                        "selected_route": route_decision.route.value,
                        "effective_route": effective_route.value,
                    },
                    now=now,
                )
                await transition_page_attempt(
                    session,
                    page_attempt,
                    (PageState.COMPLETED if accepted_native else PageState.NEEDS_REVIEW),
                    reason=(
                        "quality_gate_accepted"
                        if accepted_native
                        else "quality_gate_requires_followup"
                    ),
                    payload={
                        "quality_status": quality.evaluation.status.value,
                        "escalation_action": escalation.action.value,
                        "effective_route": effective_route.value,
                    },
                    quality_vector=quality.vector_payload,
                    quality_findings=quality.findings_payload,
                    quality_evaluation=quality.evaluation_payload,
                    escalation_decision=escalation.model_dump(
                        mode="json",
                        by_alias=False,
                    ),
                    now=now,
                )
                pages_by_number[parsed_page.page_number] = page
                for asset_type, key, descriptor in (
                    ("preview", page_assets.preview_key, page_assets.preview),
                    ("thumbnail", page_assets.thumbnail_key, page_assets.thumbnail),
                ):
                    if key is None or descriptor is None:
                        continue
                    session.add(
                        PageAsset(
                            tenant_id=claim.tenant_id,
                            page_id=page.id,
                            asset_type=asset_type,
                            storage_key=key,
                            sha256=descriptor.sha256,
                            metadata_json={
                                "content_type": descriptor.content_type,
                                "size_bytes": descriptor.size_bytes,
                                "width": descriptor.width,
                                "height": descriptor.height,
                                "dpi": (
                                    self._runtime.preview_dpi if asset_type == "preview" else None
                                ),
                                "colorspace": "RGB",
                                "page_index0": parsed_page.page_number - 1,
                                "source_sha256": context.sha256,
                                "retention_class": "derived_page_asset",
                            },
                        )
                    )
                    if asset_type == "preview":
                        preview_count += 1
                for key, inference_descriptor in zip(
                    page_assets.inference_raster_keys,
                    page_assets.inference_rasters,
                    strict=True,
                ):
                    session.add(
                        PageAsset(
                            tenant_id=claim.tenant_id,
                            page_id=page.id,
                            asset_type="inference_raster",
                            storage_key=key,
                            sha256=inference_descriptor.sha256,
                            metadata_json={
                                "content_type": inference_descriptor.content_type,
                                "size_bytes": inference_descriptor.size_bytes,
                                "width": inference_descriptor.width,
                                "height": inference_descriptor.height,
                                "dpi": inference_descriptor.dpi,
                                "colorspace": inference_descriptor.colorspace,
                                "page_index0": parsed_page.page_number - 1,
                                "source_sha256": context.sha256,
                                "preprocessing": inference_descriptor.transform.model_dump(
                                    mode="json"
                                ),
                                "retention_class": "derived_page_asset",
                            },
                        )
                    )
                if canonical is None and parsed_page.text:
                    content_hash = hashlib.sha256(parsed_page.text.encode("utf-8")).hexdigest()
                    source_ref = _full_page_source_ref(
                        context,
                        page_number=parsed_page.page_number,
                    )
                    row = Block(
                        id=_persisted_page_block_id(
                            claim.document_id,
                            parsed_page.page_number,
                        ),
                        tenant_id=claim.tenant_id,
                        document_id=claim.document_id,
                        page_id=page.id,
                        block_order=block_count,
                        block_type="paragraph",
                        origin="native_extracted",
                        bbox1000=[1, 1, 999, 999],
                        source_text=parsed_page.text,
                        normalized_text=parsed_page.normalized_text,
                        markdown=parsed_page.normalized_text,
                        structured_content={
                            "schemaVersion": "akc-normalized-block-1.0",
                            "contentLayer": "structured",
                            "sourceRefs": [source_ref],
                            "normalization": parsed_page.normalization.model_dump(
                                mode="json",
                                by_alias=True,
                            ),
                        },
                        engine="native",
                        engine_revision="cpu-document-sandbox-1",
                        confidence=1.0,
                        content_hash=content_hash,
                        warnings=sorted(
                            {
                                *(f"sensitive_{kind}_detected" for kind in sensitive_counts),
                                *parsed_page.normalization.quality_flags,
                            }
                        ),
                    )
                    session.add(row)
                    normalization_rows[str(row.id)] = row
                    normalization_views.append(
                        _normalization_view(
                            row,
                            page_number=parsed_page.page_number,
                        )
                    )
                    block_count += 1
                if not accepted_native:
                    finding_codes = {finding["code"] for finding in quality.findings_payload}
                    critical_quality = bool(
                        {
                            "numeric.token_mismatch",
                            "table.structure_invalid",
                            "table.integrity_critical",
                        }
                        & finding_codes
                    )
                    provider_unavailable = effective_route == Route.MANUAL_REVIEW
                    session.add(
                        ReviewItem(
                            tenant_id=claim.tenant_id,
                            project_id=context.project_id,
                            document_id=claim.document_id,
                            page_id=page.id,
                            severity="high",
                            category=(
                                "quality_critical"
                                if critical_quality
                                else "provider_unavailable"
                                if provider_unavailable
                                else "visual_parse_required"
                            ),
                            evidence={
                                "message": (
                                    "A critical numeric or table integrity check failed."
                                    if critical_quality
                                    else (
                                        "Visual parsing is required, but no verified "
                                        "provider is enabled."
                                        if provider_unavailable
                                        else "A verified visual parser is required."
                                    )
                                ),
                                "route_reasons": list(route_decision.reason_codes),
                                "quality_findings": quality.findings_payload,
                                "attempt_id": str(page_attempt.id),
                                "attempt_number": page_attempt.attempt_number,
                                "candidates": [],
                            },
                        )
                    )
                elif injection.suspected:
                    session.add(
                        ReviewItem(
                            tenant_id=claim.tenant_id,
                            project_id=context.project_id,
                            document_id=claim.document_id,
                            page_id=page.id,
                            severity=("high" if injection.risk.value == "high" else "medium"),
                            category="prompt_injection",
                            evidence={
                                "message": (
                                    "Potential indirect prompt injection was "
                                    "detected in source content."
                                ),
                                "rules": [signal.rule_id for signal in injection.signals],
                                "candidates": [],
                            },
                        )
                    )
                if sensitive_scan.has_secret:
                    session.add(
                        ReviewItem(
                            tenant_id=claim.tenant_id,
                            project_id=context.project_id,
                            document_id=claim.document_id,
                            page_id=page.id,
                            severity="high",
                            category="secret_detected",
                            evidence={
                                "message": (
                                    "Potential secret material was detected. External "
                                    "fallback is disabled until explicit confirmation."
                                ),
                                "counts": sensitive_counts,
                                "false_positive_notice": (
                                    "Pattern detection can produce false positives and "
                                    "can miss secret material."
                                ),
                                "external_fallback_disabled": True,
                                "candidates": [],
                            },
                        )
                    )
                record_page_terminal(
                    "completed" if accepted_native else "needs_review",
                    effective_route.value,
                )
            if canonical is not None:
                persisted_ids = {
                    block.id: _persisted_block_id(document.id, block.id)
                    for block in canonical.ordered_blocks()
                }
                persisted_rows: dict[str, Block] = {}
                for canonical_block in canonical.ordered_blocks():
                    primary_ref = canonical_block.source_refs[0]
                    persisted_page = pages_by_number.get(primary_ref.page_number1)
                    if persisted_page is None:
                        raise AnalysisAttemptError(
                            "PARSER_RESULT_INVALID",
                            retryable=False,
                        )
                    block_scan = detect_sensitive_data(
                        canonical_block.raw_text
                        or canonical_block.normalized_text
                        or canonical_block.markdown
                        or ""
                    )
                    block_sensitive_counts = _sensitive_counts(block_scan)
                    normalized = normalize_block_text(
                        canonical_block.raw_text
                        or canonical_block.normalized_text
                        or canonical_block.markdown
                        or "",
                        block_type=canonical_block.type.value,
                    )
                    structured_content = _canonical_structured_content(canonical_block)
                    structured_content["normalization"] = normalized.payload()
                    block_row = Block(
                        id=persisted_ids[canonical_block.id],
                        tenant_id=claim.tenant_id,
                        document_id=claim.document_id,
                        page_id=persisted_page.id,
                        parent_block_id=None,
                        block_order=canonical_block.order,
                        block_type=canonical_block.type.value,
                        origin=canonical_block.origin.value,
                        bbox1000=(
                            list(primary_ref.bbox1000.as_tuple())
                            if primary_ref.bbox1000 is not None
                            else None
                        ),
                        source_text=canonical_block.raw_text,
                        normalized_text=normalized.normalized_text,
                        markdown=canonical_block.markdown,
                        structured_content=structured_content,
                        engine="akc-native-parsers",
                        engine_revision=str(
                            canonical.metadata.get(
                                "nativeParserVersion",
                                "1.0.0",
                            )
                        ),
                        confidence=canonical_block.confidence,
                        content_hash=canonical_block.content_hash.removeprefix("sha256:"),
                        warnings=sorted(
                            {
                                *canonical_block.quality_flags,
                                *normalized.quality_flags,
                                *(f"sensitive_{kind}_detected" for kind in block_sensitive_counts),
                            }
                        ),
                        revision=canonical_block.revision,
                    )
                    persisted_rows[canonical_block.id] = block_row
                    normalization_rows[str(block_row.id)] = block_row
                    normalization_views.append(
                        _normalization_view(
                            block_row,
                            page_number=primary_ref.page_number1,
                        )
                    )
                    session.add(block_row)
                    block_count += 1
                await session.flush()
                for canonical_block in canonical.ordered_blocks():
                    if canonical_block.parent_id is None:
                        continue
                    persisted_rows[canonical_block.id].parent_block_id = persisted_ids[
                        canonical_block.parent_id
                    ]
                document.title = canonical.title
                document.cir_schema_version = canonical.schema_version
            _apply_document_normalization_annotations(
                normalization_rows,
                normalization_views,
                total_pages=len(manifest.pages),
            )
            document.document_type = manifest.document_type
            document.page_count = len(manifest.pages)
            document.status = "COMPLETED"
            document.updated_at = now
            policy_versions = sorted(route_policy_versions)
            if len(policy_versions) == 1 and len(policy_versions[0]) <= 120:
                document_version.policy_version = policy_versions[0]
            else:
                policy_digest = hashlib.sha256(
                    "\n".join(policy_versions).encode("utf-8")
                ).hexdigest()
                document_version.policy_version = f"analysis-route-set:{policy_digest}"
            native_parser_version = (
                str(canonical.metadata.get("nativeParserVersion", "1.0.0"))
                if canonical is not None
                else "1.0.0"
            )
            parser_revision = f"akc-native-parsers/{native_parser_version}"
            if len(parser_revision) > 200:
                parser_revision = (
                    "akc-native-parsers/sha256:"
                    + hashlib.sha256(native_parser_version.encode("utf-8")).hexdigest()
                )
            document_version.model_revision = parser_revision
            normalization_revision = (
                str(
                    canonical.metadata.get(
                        "normalizationVersion",
                        NORMALIZATION_VERSION,
                    )
                )
                if canonical is not None
                else NORMALIZATION_VERSION
            )
            if len(normalization_revision) > 120:
                normalization_revision = (
                    "sha256:" + hashlib.sha256(normalization_revision.encode("utf-8")).hexdigest()
                )
            document_version.normalization_revision = normalization_revision
            document_version.akmp_schema_version = "1.0"
            document_version.input_revision_hash = _analysis_input_revision_hash(manifest)
            document_version.status = "processed"
            task.status = "completed"
            task.page_count = len(manifest.pages)
            task.block_count = block_count
            task.preview_count = preview_count
            task.last_error_code = None
            task.lease_token = None
            task.lease_expires_at = None
            task.completed_at = now
            task.updated_at = now
            event = await session.scalar(
                select(OutboxEvent)
                .where(
                    OutboxEvent.id == claim.event_id,
                    OutboxEvent.tenant_id == claim.tenant_id,
                )
                .with_for_update()
            )
            if event is None:
                raise StaleAnalysisLease
            event.published_at = now
            event.dead_lettered_at = None
            event.last_error = None
            session.add(
                AuditEvent(
                    tenant_id=claim.tenant_id,
                    actor_id=task.requested_by,
                    action="document.analyzed",
                    target_type="document",
                    target_id=str(document.id),
                    metadata_json={
                        "task_id": str(task.id),
                        "pages": len(manifest.pages),
                        "blocks": block_count,
                        "previews": preview_count,
                        "worker": "cpu-document-sandbox-1",
                    },
                )
            )

    async def _terminal_failure_in_session(
        self,
        session: AsyncSession,
        *,
        task: AnalysisTask,
        event: OutboxEvent,
        code: str,
        now: datetime,
    ) -> None:
        safe_code = code if code in _SAFE_ERROR_CODES else "PARSER_INTERNAL_ERROR"
        task.status = "dead_letter"
        task.last_error_code = safe_code
        task.lease_token = None
        task.lease_expires_at = None
        task.available_at = now
        task.completed_at = now
        task.updated_at = now
        event.last_error = safe_code
        event.dead_lettered_at = now
        event.published_at = now
        document = await session.scalar(
            select(Document)
            .where(
                Document.tenant_id == task.tenant_id,
                Document.id == task.document_id,
            )
            .with_for_update()
        )
        project = await session.scalar(
            select(Project)
            .where(
                Project.tenant_id == task.tenant_id,
                Project.id == task.project_id,
            )
            .with_for_update()
        )
        if (
            document is not None
            and project is not None
            and getattr(document, "deletion_requested_at", None) is None
            and getattr(project, "deletion_requested_at", None) is None
        ):
            document.status = "PARSE_FAILED"
            document.updated_at = now
        session.add(
            AuditEvent(
                tenant_id=task.tenant_id,
                actor_id=task.requested_by,
                action="document.analysis_dead_lettered",
                target_type="document",
                target_id=str(task.document_id),
                metadata_json={
                    "task_id": str(task.id),
                    "code": safe_code,
                    "attempts": task.attempt_count,
                },
            )
        )

    async def _record_failure(
        self,
        *,
        claim: AnalysisClaim,
        error: AnalysisAttemptError,
    ) -> None:
        now = utcnow()
        async with self._sessions.begin() as session:
            task = await session.scalar(
                select(AnalysisTask)
                .where(
                    AnalysisTask.id == claim.task_id,
                    AnalysisTask.tenant_id == claim.tenant_id,
                )
                .with_for_update()
            )
            event = await session.scalar(
                select(OutboxEvent)
                .where(
                    OutboxEvent.id == claim.event_id,
                    OutboxEvent.tenant_id == claim.tenant_id,
                )
                .with_for_update()
            )
            if (
                task is None
                or event is None
                or task.status != "running"
                or task.lease_token != claim.lease_token
            ):
                raise StaleAnalysisLease
            terminal = not error.retryable or task.attempt_count >= task.max_attempts
            if terminal:
                await self._terminal_failure_in_session(
                    session,
                    task=task,
                    event=event,
                    code=error.code,
                    now=now,
                )
                record_attempt("dead_letter")
                return
            available = now + timedelta(seconds=self._retry_delay(task.id, task.attempt_count))
            task.status = "queued"
            task.last_error_code = error.code
            task.lease_token = None
            task.lease_expires_at = None
            task.available_at = available
            task.updated_at = now
            event.available_at = available
            event.last_error = error.code
            document = await session.scalar(
                select(Document)
                .where(
                    Document.tenant_id == claim.tenant_id,
                    Document.id == claim.document_id,
                )
                .with_for_update()
            )
            project = await session.scalar(
                select(Project)
                .where(
                    Project.tenant_id == claim.tenant_id,
                    Project.id == task.project_id,
                )
                .with_for_update()
            )
            if (
                document is not None
                and project is not None
                and getattr(document, "deletion_requested_at", None) is None
                and getattr(project, "deletion_requested_at", None) is None
            ):
                document.status = "ANALYSIS_QUEUED"
                document.updated_at = now
            record_attempt("retry")

    async def _execute_claim(self, claim: AnalysisClaim) -> None:
        started = time.monotonic()
        temporary: tempfile.TemporaryDirectory[str] | None = None
        try:
            context = await self._source_context(claim)
            manifest, preview_dir, temporary = await self._sandbox_analysis(context)
            assets = await self._upload_assets(
                manifest=manifest,
                preview_dir=preview_dir,
                context=context,
                claim=claim,
            )
            try:
                await self._persist_success(
                    claim=claim,
                    context=context,
                    manifest=manifest,
                    assets=assets,
                )
            except BaseException:
                await self._delete_uploaded_assets(assets)
                raise
            record_attempt("completed")
        except StaleAnalysisLease:
            record_attempt("stale")
        except AnalysisAttemptError as exc:
            try:
                await self._record_failure(claim=claim, error=exc)
            except StaleAnalysisLease:
                record_attempt("stale")
        except Exception:
            logger.exception(
                "analysis attempt failed",
                extra={"attempt": claim.attempt},
            )
            try:
                await self._record_failure(
                    claim=claim,
                    error=AnalysisAttemptError(
                        "PARSER_INTERNAL_ERROR",
                        retryable=True,
                    ),
                )
            except StaleAnalysisLease:
                record_attempt("stale")
        finally:
            if temporary is not None:
                temporary.cleanup()
            ANALYSIS_DURATION.observe(max(0.0, time.monotonic() - started))

    async def _run_once_on_connection(
        self,
        *,
        task_id: uuid.UUID | None,
    ) -> bool:
        async with self._engine.connect() as connection:
            claim: AnalysisClaim | None = None
            lock_key: int | None = None
            try:
                claim, lock_key = await self._claim(connection, task_id=task_id)
                if claim is None:
                    return False
                await self._execute_claim(claim)
                return True
            finally:
                if lock_key is not None:
                    await self._release_advisory_lock(connection, lock_key)

    async def run_once(self, *, task_id: uuid.UUID | None = None) -> bool:
        if self._engine.dialect.name == "sqlite":
            async with self._sqlite_lock:
                return await self._run_once_on_connection(task_id=task_id)
        return await self._run_once_on_connection(task_id=task_id)

    async def refresh_metrics(self) -> None:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(AnalysisTask.status, func.count(AnalysisTask.id))
                    .where(AnalysisTask.status.in_(("queued", "running")))
                    .group_by(AnalysisTask.status)
                )
            ).all()
            dead = await session.scalar(
                select(func.count(AnalysisTask.id)).where(AnalysisTask.status == "dead_letter")
            )
        counts = {str(status): int(count) for status, count in rows}
        for status in ("queued", "running"):
            ANALYSIS_QUEUE_DEPTH.labels(status).set(counts.get(status, 0))
        ANALYSIS_DLQ.set(int(dead or 0))

    async def run(self) -> None:
        while not self._stopping:
            processed = await self.run_once()
            await self.refresh_metrics()
            if not processed and not self._stopping:
                await asyncio.sleep(self._runtime.poll_seconds)


async def run_local_analysis_task(
    *,
    database: Database,
    store: ObjectStore,
    settings: Settings,
    task_id: uuid.UUID,
    pdf_secret_store: PdfSecretStore | None = None,
) -> None:
    """Run one task through the real sandbox under an explicit local gate."""

    if settings.env == "production" or not settings.local_analysis_worker_enabled:
        raise RuntimeError("local_analysis_worker_forbidden")
    worker = AnalysisWorker(
        engine=database.engine,
        store=store,
        runtime=AnalysisRuntime.from_api_settings(settings),
        pdf_secret_store=pdf_secret_store,
    )
    await worker.run_once(task_id=task_id)


class DocumentWorker:
    """Compatibility byte-in adapter, restricted to non-production smoke tests."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        if self.settings.env == "production":
            raise RuntimeError("in_process_document_worker_forbidden")

    def process(
        self,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        sha256: str,
    ) -> dict[str, Any]:
        from akc_api.parsers import parse_document, validate_file

        extension, digest = validate_file(
            filename=filename,
            declared_mime=content_type,
            data=data,
            expected_sha256=sha256,
            settings=self.settings,
        )
        parsed = parse_document(filename, data, self.settings)
        return {
            "schema_version": "1.0",
            "source_sha256": digest,
            "document_type": extension.removeprefix("."),
            "pages": [asdict(page) for page in parsed.pages],
        }
