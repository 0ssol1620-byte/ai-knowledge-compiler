"""Smallest-scope deterministic recovery planning and acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from threading import RLock
from typing import ClassVar

from .contracts import EventJournal
from .identity import canonical_sha256, require_sha256, stable_id
from .models import RegionLevel, VerificationState
from .validation import EvidenceReceipt, ValidationResult


class PreprocessingVariant(StrEnum):
    DPI = "dpi"
    CROP_MARGIN = "crop_margin"
    CONTRAST = "contrast"
    GRAYSCALE = "grayscale"
    DEWARP = "dewarp"
    ROTATE = "rotate"
    DENOISE = "denoise"
    SHARPEN = "sharpen"
    TILE = "tile"
    OVERLAPPING_TILE = "overlapping_tile"
    CELL_GEOMETRY = "cell_geometry_specialist"
    OCR_EXACT = "ocr_exact"
    AUTHORITY_MAPPING = "authority_mapping"


@dataclass(frozen=True, slots=True)
class RecoveryScope:
    level: RegionLevel
    scope_id: str
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.scope_id or not self.source_refs:
            raise ValueError("recovery scope needs an id and source references")


@dataclass(frozen=True, slots=True)
class RecoveryTask:
    task_id: str
    base_attempt_id: str
    base_prediction_sha256: str
    scope: RecoveryScope
    variant: PreprocessingVariant
    parser_recipe: str
    created_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        require_sha256(self.base_prediction_sha256, field_name="base_prediction_sha256")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("recovery task time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RecoveryCandidate:
    task: RecoveryTask
    repair_attempt_id: str
    prediction_sha256: str
    diff_sha256: str
    validation: ValidationResult
    source_evidence: tuple[EvidenceReceipt, ...]

    def __post_init__(self) -> None:
        require_sha256(self.prediction_sha256, field_name="prediction_sha256")
        require_sha256(self.diff_sha256, field_name="diff_sha256")


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    task_id: str
    accepted: bool
    state: VerificationState
    selected_attempt_id: str | None
    base_prediction_sha256: str
    repaired_prediction_sha256: str | None
    reason_codes: tuple[str, ...]
    decision_sha256: str


class RecoveryConflictError(RuntimeError):
    pass


class RecoveryPlanner:
    _ORDER: ClassVar[dict[RegionLevel, int]] = {
        RegionLevel.CELL: 0,
        RegionLevel.ROW: 1,
        RegionLevel.TABLE: 2,
        RegionLevel.REGION: 3,
        RegionLevel.PAGE: 4,
        RegionLevel.PAGE_GROUP: 5,
    }

    def __init__(self, *, events: EventJournal | None = None) -> None:
        self._tasks_by_key: dict[str, RecoveryTask] = {}
        self._tasks_by_id: dict[str, RecoveryTask] = {}
        self._decisions: dict[str, tuple[str, RecoveryDecision]] = {}
        self._events = events
        self._lock = RLock()

    @classmethod
    def smallest_scope(cls, scopes: tuple[RecoveryScope, ...]) -> RecoveryScope:
        if not scopes:
            raise ValueError("recovery requires at least one source-localized scope")
        if len({scope.scope_id for scope in scopes}) != len(scopes):
            raise ValueError("recovery scope ids must be unique")
        return sorted(scopes, key=lambda scope: (cls._ORDER[scope.level], scope.scope_id))[0]

    @staticmethod
    def choose_variant(failure_codes: frozenset[str], scope: RecoveryScope) -> PreprocessingVariant:
        if "authority_numeric_mismatch" in failure_codes:
            return PreprocessingVariant.AUTHORITY_MAPPING
        if "table_column_shift" in failure_codes or scope.level in {
            RegionLevel.CELL,
            RegionLevel.ROW,
            RegionLevel.TABLE,
        }:
            return PreprocessingVariant.CELL_GEOMETRY
        if "numeric_character_ambiguity" in failure_codes:
            return PreprocessingVariant.OCR_EXACT
        if "cropped_region" in failure_codes:
            return PreprocessingVariant.CROP_MARGIN
        if "rotation_detected" in failure_codes:
            return PreprocessingVariant.ROTATE
        if "photographed_low_quality" in failure_codes:
            return PreprocessingVariant.DEWARP
        return PreprocessingVariant.OVERLAPPING_TILE

    def plan(
        self,
        *,
        base_attempt_id: str,
        base_prediction_sha256: str,
        scopes: tuple[RecoveryScope, ...],
        failure_codes: frozenset[str],
        parser_recipe: str,
        created_at: datetime,
        idempotency_key: str,
    ) -> RecoveryTask:
        scope = self.smallest_scope(scopes)
        variant = self.choose_variant(failure_codes, scope)
        require_sha256(base_prediction_sha256, field_name="base_prediction_sha256")
        identity = canonical_sha256(
            {
                "base_attempt_id": base_attempt_id,
                "base_prediction_sha256": base_prediction_sha256,
                "scope": scope,
                "variant": variant,
                "parser_recipe": parser_recipe,
            }
        )
        with self._lock:
            existing = self._tasks_by_key.get(idempotency_key)
            if existing is not None:
                if canonical_sha256(
                    {
                        "base_attempt_id": existing.base_attempt_id,
                        "base_prediction_sha256": existing.base_prediction_sha256,
                        "scope": existing.scope,
                        "variant": existing.variant,
                        "parser_recipe": existing.parser_recipe,
                    }
                ) != identity:
                    raise RecoveryConflictError(
                        "recovery idempotency key reused with different recovery input"
                    )
                return existing
            task = RecoveryTask(
                task_id=stable_id("recovery", base_attempt_id, scope.scope_id, variant, identity),
                base_attempt_id=base_attempt_id,
                base_prediction_sha256=base_prediction_sha256,
                scope=scope,
                variant=variant,
                parser_recipe=parser_recipe,
                created_at=created_at,
                idempotency_key=idempotency_key,
            )
            self._tasks_by_key[idempotency_key] = task
            self._tasks_by_id[task.task_id] = task
            if self._events is not None:
                self._events.append(
                    event_type="recovery.region.requested.v1",
                    aggregate_id=task.task_id,
                    payload={
                        "base_attempt_id": base_attempt_id,
                        "scope_id": scope.scope_id,
                        "scope_level": scope.level.value,
                        "variant": variant.value,
                    },
                    occurred_at=created_at,
                    idempotency_key=f"recovery-requested:{task.task_id}",
                )
                self._events.append(
                    event_type="recovery.planned.v1",
                    aggregate_id=task.task_id,
                    payload={
                        "scope_id": scope.scope_id,
                        "scope_level": scope.level.value,
                        "variant": variant.value,
                        "parser_recipe": parser_recipe,
                    },
                    occurred_at=created_at,
                    idempotency_key=f"recovery-planned:{task.task_id}",
                )
                self._events.append(
                    event_type="recovery.started.v1",
                    aggregate_id=task.task_id,
                    payload={"base_attempt_id": base_attempt_id},
                    occurred_at=created_at,
                    idempotency_key=f"recovery-started:{task.task_id}",
                )
            return task

    @classmethod
    def next_broader_scope(
        cls, current: RecoveryScope, candidates: tuple[RecoveryScope, ...]
    ) -> RecoveryScope | None:
        broader = [
            scope
            for scope in candidates
            if cls._ORDER[scope.level] > cls._ORDER[current.level]
        ]
        return (
            sorted(broader, key=lambda scope: (cls._ORDER[scope.level], scope.scope_id))[0]
            if broader
            else None
        )

    def accept(
        self, candidate: RecoveryCandidate, *, completed_at: datetime
    ) -> RecoveryDecision:
        with self._lock:
            registered = self._tasks_by_id.get(candidate.task.task_id)
            if registered is None or registered != candidate.task:
                raise RecoveryConflictError("recovery candidate references an unknown task")
            input_digest = canonical_sha256(candidate)
            existing = self._decisions.get(candidate.task.task_id)
            if existing is not None:
                existing_digest, decision = existing
                if existing_digest != input_digest:
                    raise RecoveryConflictError(
                        "recovery task already completed with another immutable candidate"
                    )
                return decision
        reasons: list[str] = []
        if not candidate.validation.passed:
            reasons.append("recovery_validation_failed")
        if candidate.validation.hard_failure_count:
            reasons.append("recovery_has_critical_findings")
        if not candidate.source_evidence:
            reasons.append("recovery_source_evidence_missing")
        if candidate.prediction_sha256 == candidate.task.base_prediction_sha256:
            reasons.append("recovery_produced_no_change")
        if not candidate.diff_sha256:
            reasons.append("recovery_diff_missing")
        accepted = not reasons
        payload = {
            "task_id": candidate.task.task_id,
            "repair_attempt_id": candidate.repair_attempt_id,
            "accepted": accepted,
            "base_prediction_sha256": candidate.task.base_prediction_sha256,
            "prediction_sha256": candidate.prediction_sha256,
            "diff_sha256": candidate.diff_sha256,
            "validation_sha256": candidate.validation.digest,
            "reasons": tuple(sorted(reasons)),
        }
        digest = canonical_sha256(payload)
        decision = RecoveryDecision(
            task_id=candidate.task.task_id,
            accepted=accepted,
            state=(VerificationState.AUTO_REPAIRED if accepted else VerificationState.UNRESOLVED),
            selected_attempt_id=candidate.repair_attempt_id if accepted else None,
            base_prediction_sha256=candidate.task.base_prediction_sha256,
            repaired_prediction_sha256=candidate.prediction_sha256 if accepted else None,
            reason_codes=tuple(sorted(reasons)),
            decision_sha256=digest,
        )
        with self._lock:
            existing = self._decisions.get(candidate.task.task_id)
            if existing is not None:
                existing_digest, existing_decision = existing
                if existing_digest != input_digest:
                    raise RecoveryConflictError(
                        "recovery task already completed with another immutable candidate"
                    )
                return existing_decision
            if self._events is not None:
                self._events.append(
                    event_type="recovery.validated.v1",
                    aggregate_id=candidate.task.task_id,
                    payload={
                        "passed": candidate.validation.passed,
                        "hard_failure_count": candidate.validation.hard_failure_count,
                        "validation_sha256": candidate.validation.digest,
                    },
                    occurred_at=completed_at,
                    idempotency_key=f"recovery-validated:{candidate.task.task_id}",
                )
                self._events.append(
                    event_type=(
                        "region.verified.v1" if accepted else "region.unresolved.v1"
                    ),
                    aggregate_id=candidate.task.task_id,
                    payload={
                        "scope_id": candidate.task.scope.scope_id,
                        "selected_attempt_id": decision.selected_attempt_id,
                        "reason_codes": decision.reason_codes,
                    },
                    occurred_at=completed_at,
                    idempotency_key=f"recovery-region-final:{candidate.task.task_id}",
                )
                self._events.append(
                    event_type="recovery.completed.v1",
                    aggregate_id=candidate.task.task_id,
                    payload={
                        "accepted": accepted,
                        "state": decision.state.value,
                        "decision_sha256": digest,
                    },
                    occurred_at=completed_at,
                    idempotency_key=f"recovery-completed:{candidate.task.task_id}",
                )
            self._decisions[candidate.task.task_id] = (input_digest, decision)
        return decision


__all__ = [
    "PreprocessingVariant",
    "RecoveryCandidate",
    "RecoveryConflictError",
    "RecoveryDecision",
    "RecoveryPlanner",
    "RecoveryScope",
    "RecoveryTask",
]
