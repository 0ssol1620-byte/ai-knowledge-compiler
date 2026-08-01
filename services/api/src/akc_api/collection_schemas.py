"""Strict wire contracts for the v4 collection control-plane API."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any, Literal

from akc_cir import CollectionEventType
from akc_security import safe_relative_path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_COLLECTION_FILES = 5_000
MAX_COLLECTION_BYTES = 10 * 1024 * 1024 * 1024

CollectionState = Literal[
    "CREATED",
    "DISCOVERING",
    "HASHING",
    "UPLOADING",
    "VERIFYING",
    "SECURITY_SCAN",
    "DEDUPLICATING",
    "INGESTED",
    "PREFLIGHTING",
    "ESTIMATED",
    "AWAITING_APPROVAL",
    "PROCESSING",
    "VERIFYING_OUTPUT",
    "KNOWLEDGE_COMPILING",
    "PACKAGING",
    "COMPLETED",
    "PAUSED",
    "PARTIAL",
    "FAILED_RETRYABLE",
    "UNRESOLVED",
    "QUARANTINED",
    "CANCEL_REQUESTED",
    "CANCELED",
    "PURGED",
]

CollectionFileStatus = Literal[
    "planned",
    "uploading",
    "duplicate_pending",
    "uploaded",
    "verified",
    "duplicate",
    "password_required",
    "unsupported",
    "corrupted",
    "failed",
    "unresolved",
    "quarantined",
    "rejected",
    "purged",
]

CollectionProcessingState = Literal[
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
]

BlueprintKey = Literal[
    "source_index",
    "document_catalog",
    "knowledge_notes",
    "entities",
    "relations",
    "integrity",
    "export_manifest",
]

KnowledgeBlueprintId = Literal[
    "corporate-filings",
    "research-library",
    "technical-documentation",
    "course-materials",
    "personal-knowledge",
    "legal-contracts",
    "generic-mixed-corpus",
]


def _default_blueprint_modules() -> list[BlueprintKey]:
    return [
        "source_index",
        "document_catalog",
        "knowledge_notes",
        "entities",
        "relations",
        "integrity",
        "export_manifest",
    ]


_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|credential|api[_-]?key|access[_-]?token|refresh[_-]?token)",
    re.IGNORECASE,
)
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,119}$")


class CollectionWireModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


def _validate_bounded_json(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
    if any(_SENSITIVE_KEY.search(str(key)) for key in value):
        raise ValueError(f"{field_name} must not contain secret-bearing keys")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be canonical JSON") from exc
    if len(encoded) > 16_384:
        raise ValueError(f"{field_name} exceeds 16 KiB")
    return value


class CollectionCreate(CollectionWireModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    profile: dict[str, Any] = Field(default_factory=dict)

    @field_validator("profile")
    @classmethod
    def bounded_profile(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_bounded_json(value, field_name="profile")


class CollectionResponse(CollectionWireModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    status: CollectionState
    status_reason: str | None
    paused_from: Literal["UPLOADING", "PROCESSING"] | None
    profile: dict[str, Any]
    manifest_revision: int = Field(ge=0)
    event_sequence: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class LocalSourceCreate(CollectionWireModel):
    display_name: str = Field(min_length=1, max_length=500)
    source_fingerprint: str = Field(pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("display_name")
    @classmethod
    def safe_display_name(cls, value: str) -> str:
        if any(ord(character) < 32 for character in value):
            raise ValueError("display_name must not contain control characters")
        return value

    @field_validator("source_fingerprint")
    @classmethod
    def normalize_fingerprint(cls, value: str) -> str:
        return value.casefold()


class SourceRootResponse(CollectionWireModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    source_type: Literal["local", "google_drive", "onedrive"]
    display_name: str
    source_fingerprint: str
    status: Literal["active", "purged"]
    created_at: datetime


class CollectionFilePlanEntry(CollectionWireModel):
    relative_path: str = Field(min_length=1, max_length=2_000)
    display_name: str = Field(min_length=1, max_length=500)
    size_bytes: int = Field(ge=0, le=MAX_COLLECTION_BYTES)
    last_modified_ms: int | None = Field(default=None, ge=0)
    expected_mime: str = Field(min_length=1, max_length=160)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    quick_fingerprint: str | None = Field(
        default=None,
        min_length=16,
        max_length=128,
        pattern=r"^[0-9a-zA-Z:_-]+$",
    )

    @field_validator("relative_path")
    @classmethod
    def normalized_relative_path(cls, value: str) -> str:
        return safe_relative_path(value)

    @field_validator("sha256")
    @classmethod
    def normalize_sha256(cls, value: str) -> str:
        return value.casefold()

    @field_validator("expected_mime")
    @classmethod
    def safe_mime(cls, value: str) -> str:
        if any(ord(character) < 33 or ord(character) > 126 for character in value):
            raise ValueError("expected_mime must be printable ASCII")
        return value.casefold()

    @model_validator(mode="after")
    def display_name_matches_path(self) -> CollectionFilePlanEntry:
        if self.display_name != PurePosixPath(self.relative_path).name:
            raise ValueError("display_name must equal the final relative_path component")
        return self


class CollectionFilesPlan(CollectionWireModel):
    source_root_id: uuid.UUID
    files: list[CollectionFilePlanEntry] = Field(
        min_length=1,
        max_length=MAX_COLLECTION_FILES,
    )

    @model_validator(mode="after")
    def bounded_unique_manifest(self) -> CollectionFilesPlan:
        keys = [unicodedata.normalize("NFC", item.relative_path).casefold() for item in self.files]
        if len(keys) != len(set(keys)):
            raise ValueError("relative_path values must be case-insensitively unique")
        if sum(item.size_bytes for item in self.files) > MAX_COLLECTION_BYTES:
            raise ValueError("collection manifest exceeds 10 GiB")
        return self


class CollectionFileResponse(CollectionWireModel):
    id: uuid.UUID
    source_root_id: uuid.UUID
    source_file_id: uuid.UUID | None
    relative_path: str
    display_name: str
    size_bytes: int = Field(ge=0)
    last_modified_ms: int | None = Field(default=None, ge=0)
    expected_mime: str
    detected_mime: str | None
    sha256: str
    quick_fingerprint: str | None
    status: CollectionFileStatus
    error_code: str | None
    upload_required: bool
    upload_endpoint: str | None


class CollectionUploadSummary(CollectionWireModel):
    upload_session_id: uuid.UUID
    manifest_revision: int = Field(ge=1)
    resume_version: int = Field(ge=1)
    status: Literal["planned", "uploading", "completed", "partial", "expired", "aborted"]
    total_files: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    completed_files: int = Field(ge=0)
    active_files: int = Field(ge=0)
    failed_files: int = Field(ge=0)
    duplicate_files: int = Field(ge=0)
    source_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime


class CollectionFilesPlanResponse(CollectionWireModel):
    collection: CollectionResponse
    upload: CollectionUploadSummary
    browser_resume_token: str = Field(min_length=32, max_length=256, repr=False)
    files: list[CollectionFileResponse]
    limitations: list[str]


class CollectionUploadStatusResponse(CollectionWireModel):
    collection: CollectionResponse
    upload: CollectionUploadSummary
    files: list[CollectionFileResponse]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    next_offset: int | None = Field(default=None, ge=0)


class CollectionUploadControlRequest(CollectionWireModel):
    action: Literal["pause", "resume"]
    browser_resume_token: str | None = Field(
        default=None, min_length=32, max_length=256, repr=False
    )

    @model_validator(mode="after")
    def resume_requires_token(self) -> CollectionUploadControlRequest:
        if self.action == "resume" and self.browser_resume_token is None:
            raise ValueError("resume requires browser_resume_token")
        if self.action == "pause" and self.browser_resume_token is not None:
            raise ValueError("pause must not submit browser_resume_token")
        return self


class CollectionUploadControlResponse(CollectionWireModel):
    collection: CollectionResponse
    upload: CollectionUploadSummary
    browser_resume_token: str | None = Field(
        default=None, min_length=32, max_length=256, repr=False
    )


UploadReceiptOutcome = Literal[
    "completed",
    "failed",
    "password_required",
    "corrupted",
    "quarantined",
    "unsupported",
]


class CollectionUploadReceipt(CollectionWireModel):
    file_id: uuid.UUID
    outcome: UploadReceiptOutcome
    source_file_id: uuid.UUID | None = None
    error_code: str | None = Field(default=None, max_length=120)

    @field_validator("error_code")
    @classmethod
    def safe_error_code(cls, value: str | None) -> str | None:
        if value is not None and not _ERROR_CODE.fullmatch(value):
            raise ValueError("error_code must be a bounded machine code")
        return value

    @model_validator(mode="after")
    def receipt_shape(self) -> CollectionUploadReceipt:
        if self.outcome == "completed":
            if self.source_file_id is None or self.error_code is not None:
                raise ValueError("completed receipt requires source_file_id and no error_code")
        elif self.source_file_id is not None:
            raise ValueError("failed receipt must not contain source_file_id")
        return self


class CollectionUploadComplete(CollectionWireModel):
    receipts: list[CollectionUploadReceipt] = Field(min_length=1, max_length=MAX_COLLECTION_FILES)

    @model_validator(mode="after")
    def unique_file_receipts(self) -> CollectionUploadComplete:
        identifiers = [receipt.file_id for receipt in self.receipts]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("each file_id may appear only once")
        return self


class CollectionUploadCompleteResponse(CollectionWireModel):
    collection: CollectionResponse
    upload: CollectionUploadSummary
    accepted_receipts: int = Field(ge=0)
    duplicate_reuses: int = Field(ge=0)
    unresolved_files: int = Field(ge=0)


class ClusterResponse(CollectionWireModel):
    id: uuid.UUID
    cluster_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategy: str
    member_count: int = Field(ge=1)
    representative_file_ids: list[uuid.UUID]
    outlier_file_ids: list[uuid.UUID]
    feature_summary: dict[str, Any]


class KnowledgeBlueprintCandidate(CollectionWireModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,119}$")
    module_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CollectionEstimateResponse(CollectionWireModel):
    collection_id: uuid.UUID
    preflight_id: uuid.UUID
    manifest_revision: int = Field(ge=1)
    status: Literal["fast_ready", "sampled_ready", "incomplete"]
    basis: Literal["repository_rule_v1", "adaptive_sample_rules_quantile_v1"]
    p50_credits: Decimal | None = Field(default=None, ge=0)
    p95_credits: Decimal | None = Field(default=None, ge=0)
    reserve_ceiling: Decimal | None = Field(default=None, ge=0)
    duration_p50_seconds: int | None = Field(default=None, ge=0)
    duration_p95_seconds: int | None = Field(default=None, ge=0)
    confidence: Decimal = Field(ge=0, le=1)
    confidence_band: Literal["low", "medium", "high"]
    route_mix: dict[str, float]
    known_pages: int = Field(ge=0)
    unestimated_files: int = Field(ge=0)
    sampled_pages: int = Field(ge=0)
    billable_pages: int = Field(ge=0)
    duplicate_pages: int = Field(ge=0)
    unbillable_pages: int = Field(ge=0)
    predictor_revision: str
    predictor_evidence_revision: str
    predictor_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    measured_signal_fields: list[str]
    predictor_input: dict[str, Any]
    estimate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_blueprint_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,119}$")
    knowledge_blueprint_registry_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    knowledge_blueprint_module_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    knowledge_blueprint_candidates: list[KnowledgeBlueprintCandidate]
    knowledge_blueprint_rationale_codes: list[str]
    output_modules: list[BlueprintKey]
    export_profiles: list[str]
    learned_router_shadow: dict[str, Any]
    calibration_required: bool
    warnings: list[str]


class CollectionPreflightResponse(CollectionWireModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    manifest_revision: int = Field(ge=1)
    status: Literal["complete", "partial", "stale"]
    coverage_ratio: Decimal = Field(ge=0, le=1)
    total_files: int = Field(ge=0)
    bound_files: int = Field(ge=0)
    known_pages: int = Field(ge=0)
    input_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    features: dict[str, Any]
    limitations: list[str]
    clusters: list[ClusterResponse]
    estimate: CollectionEstimateResponse
    created_at: datetime


class CollectionCompileRequest(CollectionWireModel):
    approve_estimate: Literal[True]
    mode: Literal["collection_processing_runtime", "deterministic_existing_artifacts"] = (
        "collection_processing_runtime"
    )
    approved_preflight_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    approved_estimate_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    credit_hard_cap: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    overage_policy: Literal["stop_at_cap", "allow_10_percent", "continue_within_balance"] = (
        "stop_at_cap"
    )
    knowledge_blueprint_id: str = Field(
        default="generic-mixed-corpus", pattern=r"^[a-z0-9][a-z0-9-]{1,119}$"
    )
    knowledge_blueprint_registry_sha256: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    knowledge_blueprint_module_sha256: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    output_modules: list[BlueprintKey] = Field(
        default_factory=_default_blueprint_modules,
        min_length=1,
        max_length=7,
    )
    blueprint_modules: list[BlueprintKey] | None = Field(
        default=None,
        min_length=1,
        max_length=7,
        description="Deprecated compatibility alias for output_modules.",
    )

    @field_validator("output_modules", "blueprint_modules")
    @classmethod
    def unique_modules(cls, value: list[BlueprintKey] | None) -> list[BlueprintKey] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("output modules must be unique")
        return value

    @model_validator(mode="after")
    def compatibility_output_modules(self) -> CollectionCompileRequest:
        if self.blueprint_modules is not None:
            default_modules = _default_blueprint_modules()
            if (
                self.output_modules != default_modules
                and self.output_modules != self.blueprint_modules
            ):
                raise ValueError("output_modules and blueprint_modules conflict")
            self.output_modules = list(self.blueprint_modules)
        return self


class BlueprintModuleResponse(CollectionWireModel):
    id: uuid.UUID
    module_key: BlueprintKey
    module_version: str
    status: Literal["planned", "compiled", "skipped", "failed"]
    config: dict[str, Any]
    output_summary: dict[str, Any]


class ArchitecturePlanResponse(CollectionWireModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    plan_version: int = Field(ge=1)
    status: Literal["planned", "compiled", "stale", "failed"]
    input_integrity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan: dict[str, Any]
    modules: list[BlueprintModuleResponse]
    processing_job_id: uuid.UUID | None = None
    processing_status: CollectionProcessingState | None = None
    processing_resume_token: str | None = Field(
        default=None, min_length=32, max_length=256, repr=False
    )
    credits_reserved: Decimal = Field(default=Decimal("0"), ge=0)
    credits_consumed: Decimal = Field(default=Decimal("0"), ge=0)
    credits_refunded: Decimal = Field(default=Decimal("0"), ge=0)
    credits_released: Decimal = Field(default=Decimal("0"), ge=0)
    execution_scope: Literal[
        "existing_verified_artifacts_only", "collection_processing_runtime"
    ] = "existing_verified_artifacts_only"
    created_at: datetime


class CollectionEventResponse(CollectionWireModel):
    event_id: uuid.UUID
    collection_id: uuid.UUID
    job_id: uuid.UUID | None
    sequence: int = Field(ge=1)
    event_type: CollectionEventType
    timestamp: datetime
    payload: dict[str, Any]
    schema_version: Literal["1.0"] = "1.0"


class CollectionProcessingControlRequest(CollectionWireModel):
    action: Literal["pause", "resume"]
    processing_resume_token: str | None = Field(
        default=None, min_length=32, max_length=256, repr=False
    )

    @model_validator(mode="after")
    def resume_requires_token(self) -> CollectionProcessingControlRequest:
        if self.action == "resume" and self.processing_resume_token is None:
            raise ValueError("resume requires processing_resume_token")
        if self.action == "pause" and self.processing_resume_token is not None:
            raise ValueError("pause must not submit processing_resume_token")
        return self


class CollectionProcessingRetryRequest(CollectionWireModel):
    credit_hard_cap: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=6,
    )


class CollectionProcessingResponse(CollectionWireModel):
    collection_id: uuid.UUID
    architecture_plan_id: uuid.UUID
    processing_job_id: uuid.UUID
    collection_status: CollectionState
    processing_status: CollectionProcessingState
    immutable_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_preflight_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_estimate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    credit_hard_cap: Decimal = Field(ge=0)
    overage_policy: Literal["stop_at_cap", "allow_10_percent", "continue_within_balance"]
    total_tasks: int = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    failed_tasks: int = Field(ge=0)
    billable_pages: int = Field(ge=0)
    unbillable_pages: int = Field(ge=0)
    credits_reserved: Decimal = Field(ge=0)
    credits_consumed: Decimal = Field(ge=0)
    credits_refunded: Decimal = Field(ge=0)
    credits_released: Decimal = Field(ge=0)
    processing_resume_token: str | None = Field(
        default=None, min_length=32, max_length=256, repr=False
    )


class CollectionEventSnapshot(CollectionWireModel):
    collection_id: uuid.UUID
    status: CollectionState
    manifest_revision: int = Field(ge=0)
    latest_sequence: int = Field(ge=0)
    upload: CollectionUploadSummary | None
    processing_job_id: uuid.UUID | None = None
    processing_status: CollectionProcessingState | None = None
    processing_stage: str | None = None
    total_tasks: int = Field(default=0, ge=0)
    completed_tasks: int = Field(default=0, ge=0)
    failed_tasks: int = Field(default=0, ge=0)
    credits_reserved: Decimal = Field(default=Decimal("0"), ge=0)
    credits_consumed: Decimal = Field(default=Decimal("0"), ge=0)
    credit_hard_cap: Decimal = Field(default=Decimal("0"), ge=0)
    terminal_result_ids: list[uuid.UUID] = Field(default_factory=list)


class CollectionEventsResponse(CollectionWireModel):
    snapshot: CollectionEventSnapshot
    events: list[CollectionEventResponse]
    next_sequence: int = Field(ge=0)


class CollectionIntegrityResponse(CollectionWireModel):
    collection_id: uuid.UUID
    collection_status: CollectionState
    manifest_hash: str | None
    integrity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_status_counts: dict[str, int]
    verification_status_counts: dict[str, int]
    authority_mapping_status_counts: dict[str, int]
    package_status_counts: dict[str, int]
    ready_for_compile: bool
    ready_for_full_package: bool
    blockers: list[str]


class KnowledgeNoteProjection(CollectionWireModel):
    id: uuid.UUID
    document_id: uuid.UUID
    stable_key: str
    title: str
    note_type: str
    content_origin: str
    review_status: str
    evidence_block_ids: list[str]


class RelationProjection(CollectionWireModel):
    id: uuid.UUID
    document_id: uuid.UUID
    subject_id: str
    predicate: str
    object_id: str
    assertion_status: str
    review_status: str
    evidence_block_ids: list[str]


class EntityProjection(CollectionWireModel):
    id: uuid.UUID
    stable_key: str
    entity_type: str
    label: str
    evidence_block_ids: list[str]


class CollectionKnowledgeResponse(CollectionWireModel):
    collection_id: uuid.UUID
    architecture_plan_id: uuid.UUID | None
    document_ids: list[uuid.UUID]
    notes: list[KnowledgeNoteProjection]
    entities: list[EntityProjection]
    relations: list[RelationProjection]
    note_count: int = Field(ge=0)
    entity_count: int = Field(ge=0)
    relation_count: int = Field(ge=0)
    ready_for_package: bool
    limitations: list[str]


class CollectionExportRequest(CollectionWireModel):
    profiles: list[str] = Field(
        default_factory=lambda: ["collection_manifest_v1"],
        min_length=1,
        max_length=8,
    )

    @field_validator("profiles")
    @classmethod
    def bounded_unique_profiles(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("profiles must be unique")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{2,79}", item) for item in value):
            raise ValueError("profile is not a bounded identifier")
        return value


class CollectionFinalizerRequest(CollectionWireModel):
    event_id: uuid.UUID
    tenant_id: uuid.UUID
    collection_id: uuid.UUID
    processing_job_id: uuid.UUID
    architecture_plan_id: uuid.UUID
    actor_user_id: uuid.UUID


class PackageFileResponse(CollectionWireModel):
    path: str
    role: str
    media_type: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class CollectionExportResponse(CollectionWireModel):
    export_id: uuid.UUID
    package_manifest_id: uuid.UUID
    collection_id: uuid.UUID
    status: Literal["completed"]
    profile: Literal["collection_manifest_v1", "complete_knowledge_v1"]
    download_url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    signature_status: Literal[
        "unsigned_external_key_required", "external_signer_required", "verified"
    ]
    completion_scope: Literal["repository_manifest_only", "complete_knowledge_package"]
    files: list[PackageFileResponse]
    warnings: list[str]


class CollectionDeleteResponse(CollectionWireModel):
    collection_id: uuid.UUID
    status: Literal["PURGED"]
    purged_package_objects: int = Field(ge=0)
    shared_source_objects_retained: Literal[True] = True
    message: str
