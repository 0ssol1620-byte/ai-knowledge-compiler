"""Versioned real-time event contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, cast

from pydantic import ConfigDict, Field, field_validator

from .base import ContractModel, StableId
from .safe_payload import validate_public_payload


class ProcessingStage(StrEnum):
    UPLOAD = "upload"
    SECURITY_SCAN = "security_scan"
    PREFLIGHT = "preflight"
    EXTRACT = "extract"
    NORMALIZE = "normalize"
    KNOWLEDGE = "knowledge"
    VALIDATE = "validate"
    PACKAGE = "package"


class PageState(StrEnum):
    UPLOADED = "UPLOADED"
    SECURITY_SCANNING = "SECURITY_SCANNING"
    SECURITY_VERIFIED = "SECURITY_VERIFIED"
    PREFLIGHTING = "PREFLIGHTING"
    PREFLIGHTED = "PREFLIGHTED"
    NATIVE_EXTRACTING = "NATIVE_EXTRACTING"
    OCR_QUEUED = "OCR_QUEUED"
    OCR_RUNNING = "OCR_RUNNING"
    NORMALIZING = "NORMALIZING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    FAILED = "FAILED"


ALLOWED_PAGE_TRANSITIONS: dict[PageState, frozenset[PageState]] = {
    PageState.UPLOADED: frozenset({PageState.SECURITY_SCANNING}),
    PageState.SECURITY_SCANNING: frozenset({PageState.SECURITY_VERIFIED, PageState.FAILED}),
    PageState.SECURITY_VERIFIED: frozenset({PageState.PREFLIGHTING}),
    PageState.PREFLIGHTING: frozenset({PageState.PREFLIGHTED, PageState.FAILED}),
    PageState.PREFLIGHTED: frozenset(
        {PageState.NATIVE_EXTRACTING, PageState.OCR_QUEUED, PageState.FAILED}
    ),
    PageState.NATIVE_EXTRACTING: frozenset(
        {PageState.NORMALIZING, PageState.OCR_QUEUED, PageState.FAILED}
    ),
    PageState.OCR_QUEUED: frozenset({PageState.OCR_RUNNING, PageState.FAILED}),
    PageState.OCR_RUNNING: frozenset(
        {PageState.NORMALIZING, PageState.RETRY_SCHEDULED, PageState.FAILED}
    ),
    PageState.NORMALIZING: frozenset({PageState.VALIDATING, PageState.FAILED}),
    PageState.VALIDATING: frozenset(
        {
            PageState.COMPLETED,
            PageState.NEEDS_REVIEW,
            PageState.RETRY_SCHEDULED,
            PageState.FAILED,
        }
    ),
    PageState.RETRY_SCHEDULED: frozenset(
        {PageState.OCR_QUEUED, PageState.OCR_RUNNING, PageState.FAILED}
    ),
    PageState.COMPLETED: frozenset(),
    PageState.NEEDS_REVIEW: frozenset(),
    PageState.FAILED: frozenset(),
}


def page_transition_allowed(previous: PageState, current: PageState) -> bool:
    return current in ALLOWED_PAGE_TRANSITIONS[previous]


class EventType(StrEnum):
    JOB_CREATED = "job.created.v1"
    JOB_STAGE_STARTED = "job.stage.started.v1"
    JOB_STAGE_PROGRESS = "job.stage.progress.v1"
    JOB_STAGE_COMPLETED = "job.stage.completed.v1"
    PAGE_PREFLIGHT_COMPLETED = "page.preflight.completed.v1"
    PAGE_ROUTE_SELECTED = "page.route.selected.v1"
    PAGE_PROCESSING_STARTED = "page.processing.started.v1"
    PAGE_LAYOUT_DETECTED = "page.layout.detected.v1"
    PAGE_BLOCK_COMPLETED = "page.block.completed.v1"
    PAGE_MARKDOWN_UPDATED = "page.markdown.updated.v1"
    PAGE_QUALITY_UPDATED = "page.quality.updated.v1"
    PAGE_RETRY_SCHEDULED = "page.retry.scheduled.v1"
    PAGE_COMPLETED = "page.completed.v1"
    PAGE_NEEDS_REVIEW = "page.needs_review.v1"
    PAGE_FAILED = "page.failed.v1"
    DOCUMENT_KNOWLEDGE_NOTE_CREATED = "document.knowledge.note_created.v1"
    DOCUMENT_KNOWLEDGE_LINK_CREATED = "document.knowledge.link_created.v1"
    DOCUMENT_VALIDATION_COMPLETED = "document.validation.completed.v1"
    EXPORT_STARTED = "export.started.v1"
    EXPORT_COMPLETED = "export.completed.v1"
    JOB_COMPLETED = "job.completed.v1"
    JOB_FAILED = "job.failed.v1"
    JOB_CANCELLED = "job.cancelled.v1"
    CREDIT_RESERVED = "credit.reserved.v1"
    CREDIT_CONSUMED = "credit.consumed.v1"
    CREDIT_RELEASED = "credit.released.v1"


class ProcessingEvent(ContractModel):
    """SSE wire envelope.

    CIR artifacts use camelCase, but chapter 17 deliberately defines the
    HTTP/SSE envelope in snake_case.  The explicit config prevents the shared
    CIR alias generator from silently changing the public event contract.
    """

    model_config = ConfigDict(alias_generator=None, serialize_by_alias=False)

    schema_version: Literal["1.0"] = "1.0"
    event_id: StableId
    event_type: EventType
    sequence: Annotated[int, Field(ge=1)]
    occurred_at: datetime
    project_id: StableId
    job_id: StableId
    tenant_id: StableId | None = None
    document_id: StableId | None = None
    document_version_id: StableId | None = None
    page_id: StableId | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurredAt must be timezone-aware")
        return value

    @field_validator("payload")
    @classmethod
    def reject_document_content(cls, value: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], validate_public_payload(value))
