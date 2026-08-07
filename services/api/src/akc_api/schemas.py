"""Pydantic wire contracts for the versioned REST API."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)

ExportProfileName = Literal["portable", "obsidian", "rag", "jsonld"]


def _default_output_profiles() -> list[ExportProfileName]:
    return ["portable"]


class WireModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class RegisterRequest(WireModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=1024)
    display_name: str = Field(min_length=1, max_length=200)
    tenant_name: str = Field(min_length=1, max_length=200)


class LoginRequest(WireModel):
    email: str
    password: str
    tenant_slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )


class SessionResponse(WireModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    display_name: str
    roles: list[str]
    email_verified: bool


class MfaRequiredResponse(WireModel):
    mfa_required: Literal[True] = True
    action: Literal["enroll", "challenge"]
    mfa_token: str = Field(min_length=32, max_length=4096, repr=False)
    expires_in_seconds: int = Field(ge=60, le=900)


class MfaEnrollmentRequest(WireModel):
    mfa_token: SecretStr = Field(min_length=32, max_length=4096, repr=False)


class MfaEnrollmentResponse(WireModel):
    credential_id: uuid.UUID
    secret: str = Field(min_length=16, max_length=128, repr=False)
    otpauth_uri: str = Field(min_length=20, max_length=2048, repr=False)
    algorithm: Literal["SHA1"] = "SHA1"
    digits: Literal[6] = 6
    period_seconds: Literal[30] = 30


class MfaEnrollmentConfirmRequest(WireModel):
    mfa_token: SecretStr = Field(min_length=32, max_length=4096, repr=False)
    code: SecretStr = Field(min_length=6, max_length=6, repr=False)


class MfaEnrollmentConfirmedResponse(SessionResponse):
    recovery_codes: list[str] = Field(min_length=8, max_length=12, repr=False)


class MfaChallengeRequest(WireModel):
    mfa_token: SecretStr = Field(min_length=32, max_length=4096, repr=False)
    code: SecretStr | None = Field(
        default=None,
        min_length=6,
        max_length=6,
        repr=False,
    )
    recovery_code: SecretStr | None = Field(
        default=None,
        min_length=12,
        max_length=64,
        repr=False,
    )

    @model_validator(mode="after")
    def exactly_one_factor(self) -> MfaChallengeRequest:
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError("provide exactly one MFA factor")
        return self


class MfaRecoveryRegenerateRequest(WireModel):
    code: SecretStr = Field(min_length=6, max_length=6, repr=False)


class MfaRecoveryCodesResponse(WireModel):
    recovery_codes: list[str] = Field(min_length=8, max_length=12, repr=False)


class MfaStatusResponse(WireModel):
    required_for_plan: bool
    enrolled: bool
    recovery_codes_remaining: int = Field(ge=0)


class OidcAuthorizeResponse(WireModel):
    authorization_url: str
    expires_in_seconds: int = Field(ge=60, le=900)


class VerifyEmailRequest(WireModel):
    token: SecretStr = Field(min_length=64, max_length=256, repr=False)


class ResendVerificationRequest(WireModel):
    email: str = Field(min_length=3, max_length=320)


class VerificationDispatchResponse(WireModel):
    status: Literal["accepted"] = "accepted"


class ApiKeyCreate(WireModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(
        default_factory=lambda: ["api:read"],
        min_length=1,
        max_length=8,
    )

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, scopes: list[str]) -> list[str]:
        if len(scopes) != len(set(scopes)):
            raise ValueError("API key scopes must be unique")
        return scopes


class ApiKeyCreated(WireModel):
    id: uuid.UUID
    name: str
    prefix: str
    key: str
    scopes: list[str]
    created_at: datetime


class ProjectCreate(WireModel):
    name: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    classification: str = Field(default="general", max_length=40)
    output_profile: dict[str, Any] = Field(default_factory=dict)


class ProjectPatch(WireModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    classification: str | None = Field(default=None, max_length=40)
    output_profile: dict[str, Any] | None = None


class ProjectResponse(WireModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    classification: str
    output_profile: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class UploadInitiate(WireModel):
    project_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    filename: str = Field(min_length=1, max_length=500)
    size: int = Field(ge=0)
    content_type: str = Field(min_length=1, max_length=160)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class MultipartUploadPlan(WireModel):
    part_size: int = Field(gt=0)
    part_count: int = Field(gt=0)
    presign_batch_size: int = Field(ge=1, le=100)
    max_concurrency: int = Field(ge=1, le=8)
    max_retries: int = Field(ge=0, le=8)
    sign_parts_url: str
    list_parts_url: str


class UploadInitiated(WireModel):
    upload_id: uuid.UUID
    document_id: uuid.UUID
    document_version: int = Field(ge=1)
    method: Literal["PUT", "MULTIPART"]
    upload_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    multipart: MultipartUploadPlan | None = None
    expires_at: datetime


class UploadPartSignRequest(WireModel):
    part_numbers: list[int] = Field(min_length=1, max_length=100)

    @field_validator("part_numbers")
    @classmethod
    def unique_part_numbers(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("part numbers must be positive")
        if len(values) != len(set(values)):
            raise ValueError("part numbers must be unique")
        return values


class UploadPartTargetResponse(WireModel):
    part_number: int = Field(gt=0)
    upload_url: str
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


class UploadPartTargetsResponse(WireModel):
    upload_id: uuid.UUID
    parts: list[UploadPartTargetResponse]


class UploadedPartResponse(WireModel):
    part_number: int = Field(gt=0)
    etag: str = Field(pattern=r"^[a-f0-9]{32,128}$")
    size: int = Field(gt=0)


class UploadedPartsResponse(WireModel):
    upload_id: uuid.UUID
    parts: list[UploadedPartResponse]
    assembly_completed: bool = False


class UploadPartCompleted(WireModel):
    part_number: int = Field(gt=0)
    etag: str = Field(pattern=r"^[a-f0-9]{32,128}$")

    @field_validator("etag", mode="before")
    @classmethod
    def normalize_etag(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("ETag must be a string")
        return value.strip().strip('"').lower()


class UploadComplete(WireModel):
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    parts: list[UploadPartCompleted] = Field(default_factory=list, max_length=10_000)


class UploadSessionResponse(WireModel):
    upload_id: uuid.UUID
    document_id: uuid.UUID
    document_version: int = Field(ge=1)
    project_id: uuid.UUID
    method: Literal["PUT", "MULTIPART"]
    status: str
    expected_size: int
    expected_content_type: str
    expected_sha256: str
    expires_at: datetime
    multipart: MultipartUploadPlan | None = None


class UploadCompleted(WireModel):
    upload_id: uuid.UUID
    source_file_id: uuid.UUID
    document_id: uuid.UUID
    document_version: int = Field(ge=1)
    status: str


class SemanticClassificationSummary(WireModel):
    semantic_type: str
    languages: list[str]
    topics: list[str]
    domains: list[str]
    evidence_block_ids: list[str]
    confidence: float = Field(ge=0, le=1)
    model_attestation: dict[str, str]


class DocumentResponse(WireModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    document_type: str
    language_codes: list[str] = Field(default_factory=list)
    semantic_classification: SemanticClassificationSummary | None = None
    page_count: int | None
    active_version: int = Field(ge=1)
    status: str
    created_at: datetime


class DocumentVersionSummary(WireModel):
    document_id: uuid.UUID
    version: int = Field(ge=1)
    source_file_id: uuid.UUID | None
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_filename: str | None
    source_mime_type: str | None
    source_size_bytes: int | None = Field(default=None, ge=0)
    cir_snapshot_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    input_revision_hash: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    policy_version: str
    model_revision: str
    prompt_revision: str | None
    normalization_revision: str | None
    akmp_schema_version: str
    status: Literal["source_verified", "processed", "archived"]
    archived_at: datetime | None
    created_at: datetime


class DocumentVersionListResponse(WireModel):
    document_id: uuid.UUID
    active_version: int = Field(ge=1)
    versions: list[DocumentVersionSummary]


class DocumentVersionDiffResponse(WireModel):
    schema_version: Literal["document-version-diff-1.0.0"]
    document_id: uuid.UUID
    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)
    changes: dict[str, dict[str, str | int | None]]


class AnalyzeResponse(WireModel):
    task_id: uuid.UUID
    document_id: uuid.UUID
    status: Literal["queued", "running", "completed", "failed", "dead_letter"]
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    page_count: int = Field(ge=0)
    block_count: int = Field(ge=0)
    preview_count: int = Field(ge=0)
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class ReprocessRequest(WireModel):
    expected_active_version: int = Field(ge=1)
    reason: str = Field(default="user_requested", min_length=1, max_length=160)


class EstimateResponse(WireModel):
    total_pages: int = Field(ge=0)
    native_pages: int = Field(ge=0)
    visual_pages: int = Field(ge=0)
    precision_candidate_pages: int = Field(ge=0)
    tables: int = Field(ge=0)
    formulas: int = Field(ge=0)
    figures: int = Field(ge=0)
    credit_min: Decimal = Field(ge=0)
    credit_max: Decimal = Field(ge=0)
    third_party_model_api: bool
    expected_duration_min: int = Field(ge=0)
    expected_duration_max: int = Field(ge=0)
    expected: Decimal
    upper_bound: Decimal
    reserved: Decimal
    breakdown: dict[str, Decimal]


class CompileRequest(WireModel):
    route_profile: Literal[
        "parse_fast_v1",
        "parse_balanced_v1",
        "parse_precision_v1",
        "parse_private_v1",
        "parse_long_v1",
    ] = "parse_balanced_v1"
    max_credits: Decimal | None = Field(default=None, gt=0)
    external_processing_consent: bool = False
    output_profiles: list[ExportProfileName] = Field(default_factory=_default_output_profiles)


class JobResponse(WireModel):
    id: uuid.UUID
    document_id: uuid.UUID | None
    job_type: str
    status: str
    progress: dict[str, Any]
    cost_estimate: dict[str, Any]
    cost_actual: dict[str, Any]
    error: dict[str, Any] | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def job_id(self) -> uuid.UUID:
        return self.id


class PageResponse(WireModel):
    id: uuid.UUID
    document_id: uuid.UUID
    page_number: int
    status: str
    route: str | None
    preflight_metrics: dict[str, Any]
    quality_metrics: dict[str, Any]
    latest_attempt_id: uuid.UUID | None = None
    latest_attempt_number: int | None = None
    latest_attempt_status: str | None = None


class BlockResponse(WireModel):
    id: uuid.UUID
    document_id: uuid.UUID
    page_id: uuid.UUID | None
    block_order: int
    block_type: str
    origin: str
    bbox1000: tuple[int, int, int, int] | None
    source_text: str | None
    normalized_text: str | None
    markdown: str | None
    warnings: list[str]
    user_locked: bool
    revision: int

    @field_validator("bbox1000")
    @classmethod
    def validate_bbox1000(
        cls, value: tuple[int, int, int, int] | None
    ) -> tuple[int, int, int, int] | None:
        if value is None:
            return value
        x1, y1, x2, y2 = value
        if not all(0 <= coordinate <= 1000 for coordinate in value):
            raise ValueError("bbox1000 coordinates must be within 0..1000")
        if x1 >= x2 or y1 >= y2:
            raise ValueError("bbox1000 must have positive area")
        return value


class BlockPatch(WireModel):
    markdown: str = Field(max_length=2_000_000)
    user_locked: bool = True


class BlockModelMergeRequest(WireModel):
    base_revision: int = Field(ge=1)
    new_model_markdown: str = Field(max_length=2_000_000)
    model_revision: str = Field(min_length=1, max_length=200)
    apply_non_conflicting: bool = True


class BlockModelMergeResponse(WireModel):
    block_id: uuid.UUID
    status: Literal[
        "unchanged",
        "model_replaced",
        "kept_user",
        "auto_merged",
        "conflict",
    ]
    base_revision: int
    current_revision: int
    applied: bool
    user_locked: bool
    base: str
    user: str
    new_model: str
    merged: str | None
    conflict_count: int = Field(ge=0)
    etag: str


class ReviewResolve(WireModel):
    action: Literal["accept", "adopt_source", "replace", "reject"]
    value: str | None = Field(default=None, max_length=2_000_000)
    note: str | None = Field(default=None, max_length=10_000)


class ReviewRuleApply(WireModel):
    action: Literal["accept", "adopt_source", "reject"]
    preview_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=10_000)


class DispatchDlqClose(WireModel):
    expected_state_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    reason_code: Literal[
        "duplicate",
        "invalid_payload",
        "superseded",
        "manual_resolution",
        "non_retryable",
    ]
    note: str = Field(min_length=3, max_length=2_000)


class DispatchDlqFallback(WireModel):
    expected_state_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    fallback_route_profile: Literal[
        "parse_fast_v1",
        "parse_balanced_v1",
        "parse_precision_v1",
        "parse_private_v1",
        "parse_long_v1",
    ]
    reason_code: Literal[
        "provider_unavailable",
        "route_exhausted",
        "policy_override",
        "manual_recovery",
    ]
    note: str = Field(min_length=3, max_length=2_000)


class ExportCreate(WireModel):
    document_id: uuid.UUID | None = None
    export_type: Literal["portable", "obsidian", "rag", "jsonld"] = "portable"
    options: dict[str, Any] = Field(default_factory=dict)


class JobExportCreate(WireModel):
    profiles: list[ExportProfileName] = Field(
        min_length=1,
        max_length=4,
    )
    options: dict[str, Any] = Field(default_factory=dict)


class VaultConflictResponse(WireModel):
    existing_path: str = Field(min_length=1, max_length=1_024)
    incoming_path: str = Field(min_length=1, max_length=1_024)
    reason: str = Field(min_length=1, max_length=160)
    resolution: str | None = Field(default=None, max_length=160)
    resolved_path: str | None = Field(default=None, max_length=1_024)


class VaultBrokenLinkResponse(WireModel):
    source_path: str = Field(min_length=1, max_length=1_024)
    target: str = Field(min_length=1, max_length=2_048)
    resolved_path: str | None = Field(default=None, max_length=1_024)
    reason: str = Field(min_length=1, max_length=160)


class VaultMergePreviewResponse(WireModel):
    schema_version: Literal["vault-merge-preview-1.0.0"]
    policy: Literal[
        "error",
        "keep_existing",
        "rename_incoming",
        "replace_same_source",
        "update_managed",
    ]
    existing_file_count: int = Field(ge=0)
    incoming_file_count: int = Field(ge=1)
    output_file_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    unresolved_conflict_count: int = Field(ge=0)
    broken_link_count: int = Field(ge=0)
    safe_to_apply: bool
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    conflicts: list[VaultConflictResponse]
    broken_links: list[VaultBrokenLinkResponse]


class ExportResponse(WireModel):
    id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID | None
    export_type: str
    status: str
    sha256: str | None
    size_bytes: int | None
    created_at: datetime
    completed_at: datetime | None


class CreditBalance(WireModel):
    balance: Decimal
    reserved: Decimal
    available: Decimal


class CreditPackResponse(WireModel):
    code: str
    amount_minor: int
    currency: str
    credits: Decimal


class CreditCheckoutCreate(WireModel):
    pack_code: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )


class CreditCheckoutResponse(WireModel):
    id: uuid.UUID
    provider: str
    provider_checkout_id: str | None
    pack_code: str
    amount_minor: int
    currency: str
    credits: Decimal
    status: str
    checkout_url: str | None
    expires_at: datetime
    completed_at: datetime | None
    created_at: datetime


class PaymentResponse(WireModel):
    id: uuid.UUID
    checkout_id: uuid.UUID
    provider: str
    provider_payment_id: str
    amount_minor: int
    currency: str
    credits: Decimal
    status: str
    paid_at: datetime | None
    created_at: datetime


class PaymentWebhookResponse(WireModel):
    event_id: uuid.UUID
    status: str
    duplicate: bool


class PaymentEventResponse(WireModel):
    id: uuid.UUID
    provider: str
    provider_event_id: str
    event_type: str
    status: str
    attempts: int
    last_error_code: str | None
    provider_created_at: datetime
    received_at: datetime
    processed_at: datetime | None
    dead_lettered_at: datetime | None


class PaymentReconciliationResponse(WireModel):
    id: uuid.UUID
    provider: str
    status: str
    events_scanned: int
    events_processed: int
    events_retried: int
    events_dead_lettered: int
    mismatches: int
    repaired: int
    outstanding_credits: Decimal
    last_error_code: str | None
    started_at: datetime
    completed_at: datetime | None


class PrivacyPatch(WireModel):
    external_transfer_allowed: bool | None = None
    training_opt_in: bool | None = None
    data_retention_days: int | None = Field(default=None, ge=0, le=3650)
    private_mode: bool | None = None
    preview_pii_masking: bool | None = None
    product_analytics_enabled: bool | None = None


class DocumentCreate(WireModel):
    project_id: uuid.UUID
    title: str = Field(min_length=1, max_length=500)
    source_url: str | None = Field(default=None, max_length=2048)


class PageRetryRequest(WireModel):
    reason: str | None = Field(default=None, max_length=500)


class WebhookCreate(WireModel):
    url: str = Field(min_length=8, max_length=2000)
    event_types: list[
        Literal[
            "job.completed.v1",
            "job.failed.v1",
            "export.completed.v1",
        ]
    ] = Field(min_length=1, max_length=3)


class WebhookResponse(WireModel):
    id: uuid.UUID
    url: str
    event_types: list[str]
    active: bool
    created_at: datetime


class WebhookCreated(WebhookResponse):
    signing_secret: str


class WebhookPatch(WireModel):
    active: bool | None = None
    event_types: (
        list[
            Literal[
                "job.completed.v1",
                "job.failed.v1",
                "export.completed.v1",
            ]
        ]
        | None
    ) = Field(default=None, min_length=1, max_length=3)


class ModelPromotionRequest(WireModel):
    expected_generation: int = Field(ge=1)
    approval_ref: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/#-]+$",
    )
    benchmark_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    recipe_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason: str = Field(min_length=3, max_length=500)


class ModelRollbackRequest(WireModel):
    expected_generation: int = Field(ge=1)
    approval_ref: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/#-]+$",
    )
    reason: str = Field(min_length=3, max_length=500)


class ModelRetireRequest(WireModel):
    expected_generation: int = Field(ge=1)
    approval_ref: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/#-]+$",
    )
    reason: str = Field(min_length=3, max_length=500)


class DeleteReceiptResponse(WireModel):
    id: uuid.UUID
    target_type: str
    manifest_hash: str
    deleted_count: int
    requested_at: datetime
    completed_at: datetime


class DeletionRequestResponse(WireModel):
    """Asynchronous deletion handle; a receipt exists only after ``purged``."""

    id: uuid.UUID
    target_type: Literal["document", "project"]
    state: Literal["requested", "purging", "retry", "purged", "dead_letter"]
    manifest_hash: str
    object_count: int
    deleted_count: int
    requested_at: datetime
    completed_at: datetime | None = None
    status_url: str
    receipt: DeleteReceiptResponse | None = None


class EventWire(WireModel):
    event_id: uuid.UUID
    event_type: str
    occurred_at: datetime
    project_id: uuid.UUID
    document_id: uuid.UUID | None
    job_id: uuid.UUID
    page_id: uuid.UUID | None = None
    sequence: int
    schema_version: Literal["1.0"] = "1.0"
    payload: dict[str, Any]


class ErrorDetail(WireModel):
    code: str
    message: str
    request_id: str
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(WireModel):
    error: ErrorDetail


# ── Anonymous trial ingest — ADR-006 ────────────────────────────────────────
#
# A visitor with no account may submit one document and see the preflight it
# produces. The flow stops at PREFLIGHTED: no extraction, no knowledge, no
# export, and no GPU work, which is what keeps an anonymous caller away from
# the cost surface.


class TrialSessionCreated(WireModel):
    """The only credential a trial visitor gets.

    ``session_id`` grants read access to exactly one project under the reserved
    system trial tenant and nothing else. It is not a token, carries no claims,
    and stops working at ``expires_at``.
    """

    session_id: uuid.UUID
    expires_at: datetime
    max_bytes: int = Field(ge=1)
    max_pages: int = Field(ge=1)
    accepted_content_types: list[str]


class TrialUploadRequest(WireModel):
    filename: str = Field(min_length=1, max_length=500)
    size: int = Field(ge=1)
    content_type: str = Field(min_length=1, max_length=160)
    # The client computes this before sending; the server verifies it against
    # the stored object. Same integrity contract as the authenticated path.
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class TrialUploadAccepted(WireModel):
    document_id: uuid.UUID
    upload_url: str
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


class TrialPreflight(WireModel):
    """What the compiler established, and what it did not.

    ``pages_inspected`` and ``page_count`` are separate on purpose. A document
    longer than the trial cap is inspected in part, and §25.7 forbids reporting
    a partial measurement as a whole one — ``truncated`` says so explicitly
    rather than leaving the caller to compare two numbers.
    """

    session_id: uuid.UUID
    document_id: uuid.UUID
    status: Literal[
        "UPLOADED",
        "SECURITY_SCANNING",
        "SECURITY_VERIFIED",
        "SECURITY_REJECTED",
        "PREFLIGHTING",
        "PREFLIGHTED",
        "FAILED",
    ]
    page_count: int | None = Field(default=None, ge=0)
    pages_inspected: int = Field(default=0, ge=0)
    truncated: bool = False
    detected_language_codes: list[str] = Field(default_factory=list)
    encrypted: bool | None = None
    # The recipe the compiler would run. Shown so the visitor sees a decision
    # was made, not a generic promise.
    route_profile: str | None = None
    error_code: str | None = None
    expires_at: datetime
