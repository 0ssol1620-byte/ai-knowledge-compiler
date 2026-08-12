"""Immutable domain contracts for the v6 parallel runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .identity import require_sha256


def _require_identifier(value: str, field_name: str) -> str:
    if not value or len(value) > 200 or any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must be a non-empty identifier without whitespace")
    return value


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class AttemptStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    OUTPUT_RECEIVED = "OUTPUT_RECEIVED"
    VALIDATING = "VALIDATING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RETRYABLE_FAILED = "RETRYABLE_FAILED"
    TERMINAL_FAILED = "TERMINAL_FAILED"
    SUPERSEDED = "SUPERSEDED"
    QUARANTINED = "QUARANTINED"


class AttemptKind(StrEnum):
    PRIMARY = "primary"
    RETRY = "retry"
    RECOVERY = "recovery"
    HEDGE = "hedge"
    STRAGGLER = "straggler"
    SHADOW = "shadow"
    CHALLENGER = "challenger"


class FailureClass(StrEnum):
    INFRASTRUCTURE = "infrastructure"
    SEMANTIC = "semantic"


class WorkerState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DRAINING = "DRAINING"
    QUARANTINED = "QUARANTINED"
    TERMINATED = "TERMINATED"


class VerificationState(StrEnum):
    VERIFIED = "verified"
    AUTHORITY_VERIFIED = "authority_verified"
    CROSS_MODEL_VERIFIED = "cross_model_verified"
    AUTO_REPAIRED = "auto_repaired"
    UNRESOLVED = "unresolved"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class RegionLevel(StrEnum):
    CELL = "cell"
    ROW = "row"
    TABLE = "table"
    REGION = "region"
    PAGE = "page"
    PAGE_PAIR = "page_pair"
    PAGE_GROUP = "page_group"
    DOCUMENT = "document"


class PageClass(StrEnum):
    NATIVE_CLEAN = "native_clean"
    NORMAL_SCAN = "normal_scan"
    COMPLEX_LAYOUT = "complex_layout"
    INDEPENDENT = "independent"
    LONG_TABLE = "long_table"
    FORMULA_HEAVY = "formula_heavy"
    PHOTOGRAPHED = "photographed"
    OFFICE_STRUCTURED = "office_structured"


@dataclass(frozen=True, slots=True)
class CostRecord:
    gpu_seconds: Decimal = Decimal("0")
    provider_cost: Decimal = Decimal("0")
    user_credits: Decimal = Decimal("0")
    duplicate_compute: bool = False

    def __post_init__(self) -> None:
        if any(value < 0 for value in (self.gpu_seconds, self.provider_cost, self.user_credits)):
            raise ValueError("cost values cannot be negative")
        if self.duplicate_compute and self.user_credits != 0:
            raise ValueError("duplicate compute cannot carry user credits")


@dataclass(frozen=True, slots=True)
class ParseAttempt:
    attempt_id: str
    root_attempt_id: str
    parent_attempt_id: str | None
    kind: AttemptKind
    document_id: str
    document_version_id: str
    shard_id: str
    page_ids: tuple[str, ...]
    region_ids: tuple[str, ...]
    parser_recipe: str
    model_revision: str
    runtime_image_digest: str
    worker_id: str
    gpu_type: str
    source_sha256: str
    preprocessing_sha256: str
    prompt_sha256: str
    decoding_sha256: str
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "attempt_id",
            "root_attempt_id",
            "document_id",
            "document_version_id",
            "shard_id",
            "parser_recipe",
            "model_revision",
            "runtime_image_digest",
            "worker_id",
            "gpu_type",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if self.parent_attempt_id is not None:
            _require_identifier(self.parent_attempt_id, "parent_attempt_id")
        if not self.page_ids and not self.region_ids:
            raise ValueError("an attempt must target at least one page or region")
        if len(set(self.page_ids)) != len(self.page_ids):
            raise ValueError("attempt page_ids must be unique")
        if len(set(self.region_ids)) != len(self.region_ids):
            raise ValueError("attempt region_ids must be unique")
        for field_name in (
            "source_sha256",
            "preprocessing_sha256",
            "prompt_sha256",
            "decoding_sha256",
        ):
            require_sha256(getattr(self, field_name), field_name=field_name)
        _require_aware(self.created_at, "created_at")
        if self.parent_attempt_id is None and self.attempt_id != self.root_attempt_id:
            raise ValueError("a root attempt must identify itself as root_attempt_id")
        if self.parent_attempt_id is not None and self.attempt_id == self.root_attempt_id:
            raise ValueError("a child attempt cannot reuse the root attempt id")


@dataclass(frozen=True, slots=True)
class AttemptOutput:
    prediction_uri: str
    prediction_sha256: str
    completed_at: datetime
    cost: CostRecord = field(default_factory=CostRecord)

    def __post_init__(self) -> None:
        if not self.prediction_uri or any(character.isspace() for character in self.prediction_uri):
            raise ValueError("prediction_uri must be non-empty and contain no whitespace")
        require_sha256(self.prediction_sha256, field_name="prediction_sha256")
        _require_aware(self.completed_at, "completed_at")


@dataclass(frozen=True, slots=True)
class AttemptTransition:
    sequence: int
    from_status: AttemptStatus | None
    to_status: AttemptStatus
    occurred_at: datetime
    reason_code: str

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("transition sequence must be positive")
        _require_aware(self.occurred_at, "occurred_at")
        _require_identifier(self.reason_code, "reason_code")


@dataclass(frozen=True, slots=True)
class AttemptSnapshot:
    attempt: ParseAttempt
    status: AttemptStatus
    output: AttemptOutput | None
    validation_digest: str | None
    transitions: tuple[AttemptTransition, ...]

    def __post_init__(self) -> None:
        if self.validation_digest is not None:
            require_sha256(self.validation_digest, field_name="validation_digest")
        if not self.transitions or self.transitions[-1].to_status is not self.status:
            raise ValueError("attempt snapshot status must match the latest transition")


@dataclass(frozen=True, slots=True)
class WorkerSnapshot:
    worker_id: str
    model_revision: str
    runtime_image_digest: str
    state: WorkerState
    capabilities: frozenset[str]
    warm: bool
    cached_models: frozenset[str]
    estimated_available_at: float
    semantic_score: float

    def __post_init__(self) -> None:
        _require_identifier(self.worker_id, "worker_id")
        _require_identifier(self.model_revision, "model_revision")
        _require_identifier(self.runtime_image_digest, "runtime_image_digest")
        if self.estimated_available_at < 0:
            raise ValueError("estimated_available_at cannot be negative")
        if not 0 <= self.semantic_score <= 100:
            raise ValueError("semantic_score must be between 0 and 100")


ACCEPTED_VERIFICATION_STATES = frozenset(
    {
        VerificationState.VERIFIED,
        VerificationState.AUTHORITY_VERIFIED,
        VerificationState.CROSS_MODEL_VERIFIED,
        VerificationState.AUTO_REPAIRED,
    }
)


__all__ = [
    "ACCEPTED_VERIFICATION_STATES",
    "AttemptKind",
    "AttemptOutput",
    "AttemptSnapshot",
    "AttemptStatus",
    "AttemptTransition",
    "CostRecord",
    "FailureClass",
    "PageClass",
    "ParseAttempt",
    "RegionLevel",
    "VerificationState",
    "WorkerSnapshot",
    "WorkerState",
]
