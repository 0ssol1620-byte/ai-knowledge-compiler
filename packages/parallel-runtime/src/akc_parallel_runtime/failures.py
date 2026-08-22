"""Separate infrastructure failures from silent semantic failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import FailureClass

INFRASTRUCTURE_FAILURE_CODES = frozenset(
    {
        "container_crash",
        "oom",
        "health_503",
        "connection_timeout",
        "cuda_error",
        "model_checksum_mismatch",
        "model_identity_mismatch",
        "disk_cache_error",
        "malformed_protocol",
        "dependency_import_failure",
    }
)

SEMANTIC_FAILURE_CODES = frozenset(
    {
        "numeric_mutation",
        "row_omission",
        "repetition",
        "blank_page",
        "table_column_shift",
        "caption_omission",
        "reading_order_error",
        "source_coverage_incomplete",
        "hallucinated_row",
        "false_verified",
        "false_bbox",
        "truncated_output",
    }
)


class DiagnosisState(StrEnum):
    HEALTHY = "healthy"
    INFRASTRUCTURE_FAILED = "infrastructure_failed"
    SEMANTIC_FAILED = "semantic_failed"


@dataclass(frozen=True, slots=True)
class FailureObservation:
    http_status: int
    response_schema_valid: bool
    reason_codes: frozenset[str]

    def __post_init__(self) -> None:
        if self.http_status < 0:
            raise ValueError("HTTP status cannot be negative")


@dataclass(frozen=True, slots=True)
class FailureDiagnosis:
    state: DiagnosisState
    failure_class: FailureClass | None
    reason_codes: tuple[str, ...]
    actions: tuple[str, ...]
    candidate_accepted: bool


def diagnose_failure(observation: FailureObservation) -> FailureDiagnosis:
    reasons = set(observation.reason_codes)
    if not 200 <= observation.http_status < 300:
        reasons.add("transport_http_failure")
    if not observation.response_schema_valid:
        reasons.add("malformed_protocol")
    infrastructure = reasons & (INFRASTRUCTURE_FAILURE_CODES | {"transport_http_failure"})
    semantic = reasons & SEMANTIC_FAILURE_CODES
    unknown = reasons - infrastructure - semantic
    if infrastructure:
        return FailureDiagnosis(
            state=DiagnosisState.INFRASTRUCTURE_FAILED,
            failure_class=FailureClass.INFRASTRUCTURE,
            reason_codes=tuple(sorted(reasons)),
            actions=(
                "retry_same_recipe_different_worker",
                "alternate_gpu_or_image_if_policy_allows",
                "drain_worker_on_recurrence",
            ),
            candidate_accepted=False,
        )
    if semantic or unknown:
        if unknown:
            reasons.add("unclassified_semantic_failure_fail_closed")
        return FailureDiagnosis(
            state=DiagnosisState.SEMANTIC_FAILED,
            failure_class=FailureClass.SEMANTIC,
            reason_codes=tuple(sorted(reasons)),
            actions=(
                "reject_attempt",
                "update_semantic_health",
                "alternate_preprocessing_or_model",
                "request_smallest_scope_recovery",
            ),
            candidate_accepted=False,
        )
    return FailureDiagnosis(
        state=DiagnosisState.HEALTHY,
        failure_class=None,
        reason_codes=(),
        actions=(),
        candidate_accepted=True,
    )


__all__ = [
    "INFRASTRUCTURE_FAILURE_CODES",
    "SEMANTIC_FAILURE_CODES",
    "DiagnosisState",
    "FailureDiagnosis",
    "FailureObservation",
    "diagnose_failure",
]
