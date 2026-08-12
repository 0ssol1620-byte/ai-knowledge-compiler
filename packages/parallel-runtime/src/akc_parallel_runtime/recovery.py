"""Smallest-scope deterministic recovery planning and acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from threading import RLock
from typing import ClassVar

from .contracts import EventJournal
from .identity import canonical_sha256, require_sha256, stable_id
from .impact_scope import LineageEdge, impacted_descendants
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
    PAGE_RERENDER_ALT_PARSER = "page_rerender_alternate_parser"
    REGION_CROP = "region_crop"
    ROW_BAND_TILE = "row_band_tile"
    CANDIDATE_REJECT = "candidate_reject"
    TARGET_SELECTION = "target_selection"
    NATIVE_AUTHORITY_RECONSTRUCTION = "native_authority_reconstruction"
    CANONICAL_NUMERIC = "canonical_numeric_recovery"
    LAYOUT_SPECIALIST = "layout_specialist"
    PAGE_PAIR_STITCH = "page_pair_stitch"
    FORMULA_SPECIALIST = "formula_specialist"
    SOURCE_REMAP = "source_remap"
    NOTE_RECOMPILE = "note_recompile"
    ENTITY_SPLIT = "entity_split"
    RELATION_REMOVE = "relation_remove"


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
    base_independent_family: str
    repair_independent_family: str
    lineage_edges: tuple[LineageEdge, ...] = ()

    def __post_init__(self) -> None:
        require_sha256(self.prediction_sha256, field_name="prediction_sha256")
        require_sha256(self.diff_sha256, field_name="diff_sha256")
        if not self.base_independent_family or not self.repair_independent_family:
            raise ValueError("recovery candidate requires both independent family identities")


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
    impacted_object_ids: tuple[str, ...] = ()


class RecoveryConflictError(RuntimeError):
    pass


class RecoveryPlanner:
    _ORDER: ClassVar[dict[RegionLevel, int]] = {
        RegionLevel.CELL: 0,
        RegionLevel.ROW: 1,
        RegionLevel.TABLE: 2,
        RegionLevel.REGION: 3,
        RegionLevel.PAGE: 4,
        RegionLevel.PAGE_PAIR: 5,
        RegionLevel.PAGE_GROUP: 5,
        RegionLevel.DOCUMENT: 6,
    }

    _MINIMUM_SCOPE: ClassVar[dict[str, RegionLevel]] = {
        "P01": RegionLevel.PAGE,
        "page_coverage_mismatch": RegionLevel.PAGE,
        "B01": RegionLevel.REGION,
        "visible_region_missing": RegionLevel.REGION,
        "T01": RegionLevel.ROW,
        "bottom_row_omission": RegionLevel.ROW,
        "row_omission": RegionLevel.ROW,
        "table_cut_detected": RegionLevel.ROW,
        "T02": RegionLevel.ROW,
        "middle_row_omission": RegionLevel.ROW,
        "T03": RegionLevel.TABLE,
        "extra_rows": RegionLevel.TABLE,
        "T04": RegionLevel.TABLE,
        "wrong_table": RegionLevel.TABLE,
        "native_heading_mismatch": RegionLevel.TABLE,
        "T05": RegionLevel.CELL,
        "table_column_shift": RegionLevel.CELL,
        "native_object_count_mismatch": RegionLevel.TABLE,
        "N01": RegionLevel.CELL,
        "digit_mutation": RegionLevel.CELL,
        "native_numeric_mismatch": RegionLevel.CELL,
        "authority_numeric_mismatch": RegionLevel.CELL,
        "N02": RegionLevel.CELL,
        "sign_scale_error": RegionLevel.CELL,
        "authority_dimension_mismatch": RegionLevel.CELL,
        "R01": RegionLevel.REGION,
        "reading_order_invalid": RegionLevel.REGION,
        "visual_hierarchy_invalid": RegionLevel.REGION,
        "C01": RegionLevel.PAGE_PAIR,
        "cross_page_split": RegionLevel.PAGE_PAIR,
        "F01": RegionLevel.REGION,
        "formula_corruption": RegionLevel.REGION,
        "G01": RegionLevel.REGION,
        "grounding_mismatch": RegionLevel.REGION,
        "bbox_invalid": RegionLevel.REGION,
        "source_coverage_incomplete": RegionLevel.REGION,
        "source_link_invalid": RegionLevel.REGION,
        "caption_missing": RegionLevel.REGION,
        "H01": RegionLevel.REGION,
        "hallucination": RegionLevel.REGION,
        "unsupported_content": RegionLevel.REGION,
        "differential_disagreement": RegionLevel.REGION,
        "H02": RegionLevel.REGION,
        "repetition_detected": RegionLevel.REGION,
        "K01": RegionLevel.REGION,
        "note_split_error": RegionLevel.REGION,
        "K02": RegionLevel.REGION,
        "wrong_entity_merge": RegionLevel.REGION,
        "K03": RegionLevel.REGION,
        "unsupported_relation": RegionLevel.REGION,
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

    @classmethod
    def minimum_valid_scope(
        cls,
        failure_codes: frozenset[str],
        scopes: tuple[RecoveryScope, ...],
    ) -> RecoveryScope:
        """Return the smallest supplied scope that is safe for every finding."""

        if not scopes:
            raise ValueError("recovery requires at least one source-localized scope")
        minimum_rank = max(
            (
                cls._ORDER[cls._MINIMUM_SCOPE[code]]
                for code in failure_codes
                if code in cls._MINIMUM_SCOPE
            ),
            default=0,
        )
        eligible = tuple(
            scope for scope in scopes if cls._ORDER[scope.level] >= minimum_rank
        )
        if not eligible:
            raise ValueError("recovery scopes do not satisfy the failure minimum scope")
        return cls.smallest_scope(eligible)

    @staticmethod
    def choose_variant(failure_codes: frozenset[str], scope: RecoveryScope) -> PreprocessingVariant:
        if failure_codes & {"P01", "page_coverage_mismatch"}:
            return PreprocessingVariant.PAGE_RERENDER_ALT_PARSER
        if failure_codes & {"B01", "visible_region_missing"}:
            return PreprocessingVariant.REGION_CROP
        if failure_codes & {"T01", "bottom_row_omission", "row_omission", "table_cut_detected"}:
            return PreprocessingVariant.OVERLAPPING_TILE
        if failure_codes & {"T02", "middle_row_omission"}:
            return PreprocessingVariant.ROW_BAND_TILE
        if failure_codes & {
            "T03",
            "H01",
            "H02",
            "extra_rows",
            "hallucination",
            "unsupported_content",
            "differential_disagreement",
            "repetition_detected",
        }:
            return PreprocessingVariant.CANDIDATE_REJECT
        if failure_codes & {"T04", "wrong_table", "native_heading_mismatch"}:
            return PreprocessingVariant.TARGET_SELECTION
        if failure_codes & {
            "T05",
            "table_column_shift",
            "native_object_count_mismatch",
        }:
            return PreprocessingVariant.CELL_GEOMETRY
        if failure_codes & {
            "N01",
            "digit_mutation",
            "native_numeric_mismatch",
            "authority_numeric_mismatch",
        }:
            return PreprocessingVariant.NATIVE_AUTHORITY_RECONSTRUCTION
        if failure_codes & {"N02", "sign_scale_error", "authority_dimension_mismatch"}:
            return PreprocessingVariant.CANONICAL_NUMERIC
        if failure_codes & {"R01", "reading_order_invalid", "visual_hierarchy_invalid"}:
            return PreprocessingVariant.LAYOUT_SPECIALIST
        if failure_codes & {"C01", "cross_page_split"}:
            return PreprocessingVariant.PAGE_PAIR_STITCH
        if failure_codes & {"F01", "formula_corruption"}:
            return PreprocessingVariant.FORMULA_SPECIALIST
        if failure_codes & {
            "G01",
            "grounding_mismatch",
            "bbox_invalid",
            "source_coverage_incomplete",
            "source_link_invalid",
            "caption_missing",
        }:
            return PreprocessingVariant.SOURCE_REMAP
        if failure_codes & {"K01", "note_split_error"}:
            return PreprocessingVariant.NOTE_RECOMPILE
        if failure_codes & {"K02", "wrong_entity_merge"}:
            return PreprocessingVariant.ENTITY_SPLIT
        if failure_codes & {"K03", "unsupported_relation"}:
            return PreprocessingVariant.RELATION_REMOVE
        if failure_codes & {
            "authority_numeric_mismatch",
            "authority_dimension_mismatch",
        }:
            return PreprocessingVariant.AUTHORITY_MAPPING
        if failure_codes & {
            "table_column_shift",
            "table_cut_detected",
            "native_object_count_mismatch",
        } or scope.level in {
            RegionLevel.CELL,
            RegionLevel.ROW,
            RegionLevel.TABLE,
        }:
            return PreprocessingVariant.CELL_GEOMETRY
        if failure_codes & {
            "numeric_character_ambiguity",
            "native_numeric_mismatch",
        }:
            return PreprocessingVariant.OCR_EXACT
        if failure_codes & {
            "cropped_region",
            "caption_missing",
            "bbox_invalid",
            "source_coverage_incomplete",
        }:
            return PreprocessingVariant.CROP_MARGIN
        if "rotation_detected" in failure_codes:
            return PreprocessingVariant.ROTATE
        if "photographed_low_quality" in failure_codes:
            return PreprocessingVariant.DEWARP
        if failure_codes & {
            "reading_order_invalid",
            "visual_hierarchy_invalid",
        }:
            return PreprocessingVariant.TILE
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
        scope = self.minimum_valid_scope(failure_codes, scopes)
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
        if candidate.base_independent_family == candidate.repair_independent_family:
            reasons.append("recovery_independent_family_missing")
        if candidate.prediction_sha256 == candidate.task.base_prediction_sha256:
            reasons.append("recovery_produced_no_change")
        if not candidate.diff_sha256:
            reasons.append("recovery_diff_missing")
        accepted = not reasons
        impacted_object_ids = (
            impacted_descendants(
                (candidate.task.scope.scope_id,),
                candidate.lineage_edges,
            )
            if accepted
            else ()
        )
        payload = {
            "task_id": candidate.task.task_id,
            "repair_attempt_id": candidate.repair_attempt_id,
            "accepted": accepted,
            "base_prediction_sha256": candidate.task.base_prediction_sha256,
            "prediction_sha256": candidate.prediction_sha256,
            "diff_sha256": candidate.diff_sha256,
            "validation_sha256": candidate.validation.digest,
            "base_independent_family": candidate.base_independent_family,
            "repair_independent_family": candidate.repair_independent_family,
            "reasons": tuple(sorted(reasons)),
            "impacted_object_ids": impacted_object_ids,
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
            impacted_object_ids=impacted_object_ids,
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
