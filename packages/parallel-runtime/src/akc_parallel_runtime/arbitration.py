"""Authority-first arbitration that never treats a model majority as truth."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .identity import canonical_sha256, require_sha256, stable_id
from .models import VerificationState


class ArbitrationBasis(StrEnum):
    AUTHORITY_EXACT = "authority_exact"
    NATIVE_EXACT = "native_exact"
    PIXEL_SPECIALIST = "pixel_specialist"
    INDEPENDENT_AGREEMENT = "independent_agreement"
    SOURCE_GEOMETRY = "source_geometry"
    TABLE_CELL_MAP = "table_cell_map"
    DOWNSTREAM_CONSISTENCY = "downstream_consistency"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class ArbitrationCandidate:
    attempt_id: str
    prediction_sha256: str
    hard_gate_pass: bool
    numeric_value: Decimal | None
    structure_fingerprint: str | None
    independent_family: str
    authority_exact: bool | None = None
    native_exact: bool | None = None
    pixel_specialist_exact: bool = False
    source_geometry_exact: bool = False
    table_cell_map_exact: bool = False
    downstream_consistent: bool = False
    source_coverage: float = 0.0
    structure_score: float = 0.0
    cross_model_agreement: float = 0.0
    runtime_reliability: float = 0.0

    def __post_init__(self) -> None:
        if not self.attempt_id or not self.independent_family:
            raise ValueError("candidate identity and independent family are required")
        require_sha256(self.prediction_sha256, field_name="prediction_sha256")
        if any(
            not 0 <= value <= 1
            for value in (
                self.source_coverage,
                self.structure_score,
                self.cross_model_agreement,
                self.runtime_reliability,
            )
        ):
            raise ValueError("candidate score components must be between 0 and 1")

    @property
    def score(self) -> float | None:
        if not self.hard_gate_pass:
            return None
        return round(
            0.30 * self.source_coverage
            + 0.25 * self.structure_score
            + 0.20 * self.cross_model_agreement
            + 0.25 * self.runtime_reliability,
            12,
        )


@dataclass(frozen=True, slots=True)
class ArbitrationDecision:
    decision_id: str
    scope_id: str
    selected_attempt_id: str | None
    selected_prediction_sha256: str | None
    basis: ArbitrationBasis
    verification_state: VerificationState
    accepted: bool
    billable: bool
    reason_codes: tuple[str, ...]
    considered_attempt_ids: tuple[str, ...]
    excluded_hard_gate_attempt_ids: tuple[str, ...]
    decision_sha256: str


class Arbitrator:
    @staticmethod
    def _best(candidates: tuple[ArbitrationCandidate, ...]) -> ArbitrationCandidate:
        return sorted(
            candidates,
            key=lambda candidate: (-(candidate.score or 0.0), candidate.attempt_id),
        )[0]

    @staticmethod
    def _unresolved(
        *,
        scope_id: str,
        considered: tuple[ArbitrationCandidate, ...],
        excluded: tuple[ArbitrationCandidate, ...],
        reasons: tuple[str, ...],
    ) -> ArbitrationDecision:
        payload = {
            "scope_id": scope_id,
            "basis": ArbitrationBasis.UNRESOLVED,
            "considered": tuple(candidate.attempt_id for candidate in considered),
            "excluded": tuple(candidate.attempt_id for candidate in excluded),
            "reasons": reasons,
        }
        digest = canonical_sha256(payload)
        return ArbitrationDecision(
            decision_id=stable_id("arbitration", scope_id, digest),
            scope_id=scope_id,
            selected_attempt_id=None,
            selected_prediction_sha256=None,
            basis=ArbitrationBasis.UNRESOLVED,
            verification_state=VerificationState.UNRESOLVED,
            accepted=False,
            billable=False,
            reason_codes=reasons,
            considered_attempt_ids=tuple(candidate.attempt_id for candidate in considered),
            excluded_hard_gate_attempt_ids=tuple(candidate.attempt_id for candidate in excluded),
            decision_sha256=digest,
        )

    @staticmethod
    def _selected(
        *,
        scope_id: str,
        candidate: ArbitrationCandidate,
        basis: ArbitrationBasis,
        state: VerificationState,
        considered: tuple[ArbitrationCandidate, ...],
        excluded: tuple[ArbitrationCandidate, ...],
    ) -> ArbitrationDecision:
        payload = {
            "scope_id": scope_id,
            "attempt_id": candidate.attempt_id,
            "prediction_sha256": candidate.prediction_sha256,
            "basis": basis,
            "state": state,
        }
        digest = canonical_sha256(payload)
        return ArbitrationDecision(
            decision_id=stable_id("arbitration", scope_id, digest),
            scope_id=scope_id,
            selected_attempt_id=candidate.attempt_id,
            selected_prediction_sha256=candidate.prediction_sha256,
            basis=basis,
            verification_state=state,
            accepted=True,
            billable=True,
            reason_codes=(basis.value,),
            considered_attempt_ids=tuple(candidate.attempt_id for candidate in considered),
            excluded_hard_gate_attempt_ids=tuple(candidate.attempt_id for candidate in excluded),
            decision_sha256=digest,
        )

    def arbitrate_numeric(
        self,
        scope_id: str,
        candidates: tuple[ArbitrationCandidate, ...],
        *,
        authority_required: bool = False,
    ) -> ArbitrationDecision:
        excluded = tuple(candidate for candidate in candidates if not candidate.hard_gate_pass)
        eligible = tuple(
            candidate
            for candidate in candidates
            if candidate.hard_gate_pass and candidate.numeric_value is not None
        )
        if not eligible:
            return self._unresolved(
                scope_id=scope_id,
                considered=eligible,
                excluded=excluded,
                reasons=("no_hard_gate_passing_numeric_candidate",),
            )
        authority = tuple(candidate for candidate in eligible if candidate.authority_exact is True)
        if authority:
            if len({candidate.numeric_value for candidate in authority}) != 1:
                return self._unresolved(
                    scope_id=scope_id,
                    considered=eligible,
                    excluded=excluded,
                    reasons=("authority_conflict",),
                )
            return self._selected(
                scope_id=scope_id,
                candidate=self._best(authority),
                basis=ArbitrationBasis.AUTHORITY_EXACT,
                state=VerificationState.AUTHORITY_VERIFIED,
                considered=eligible,
                excluded=excluded,
            )
        if any(candidate.authority_exact is False for candidate in eligible):
            return self._unresolved(
                scope_id=scope_id,
                considered=eligible,
                excluded=excluded,
                reasons=("authority_mismatch",),
            )
        if authority_required:
            return self._unresolved(
                scope_id=scope_id,
                considered=eligible,
                excluded=excluded,
                reasons=("authority_required_but_unavailable",),
            )
        native = tuple(candidate for candidate in eligible if candidate.native_exact is True)
        if native:
            if len({candidate.numeric_value for candidate in native}) != 1:
                return self._unresolved(
                    scope_id=scope_id,
                    considered=eligible,
                    excluded=excluded,
                    reasons=("native_source_conflict",),
                )
            return self._selected(
                scope_id=scope_id,
                candidate=self._best(native),
                basis=ArbitrationBasis.NATIVE_EXACT,
                state=VerificationState.VERIFIED,
                considered=eligible,
                excluded=excluded,
            )
        if any(candidate.native_exact is False for candidate in eligible):
            return self._unresolved(
                scope_id=scope_id,
                considered=eligible,
                excluded=excluded,
                reasons=("native_source_mismatch",),
            )
        specialist = tuple(candidate for candidate in eligible if candidate.pixel_specialist_exact)
        if specialist:
            if len({candidate.numeric_value for candidate in specialist}) != 1:
                return self._unresolved(
                    scope_id=scope_id,
                    considered=eligible,
                    excluded=excluded,
                    reasons=("pixel_specialist_conflict",),
                )
            return self._selected(
                scope_id=scope_id,
                candidate=self._best(specialist),
                basis=ArbitrationBasis.PIXEL_SPECIALIST,
                state=VerificationState.VERIFIED,
                considered=eligible,
                excluded=excluded,
            )
        by_value: dict[Decimal, dict[str, list[ArbitrationCandidate]]] = {}
        for candidate in eligible:
            numeric_value = candidate.numeric_value
            if numeric_value is None:
                raise RuntimeError("eligible numeric candidate lost its numeric value")
            by_value.setdefault(numeric_value, {}).setdefault(
                candidate.independent_family, []
            ).append(candidate)
        independently_supported = [
            (value, families) for value, families in by_value.items() if len(families) >= 2
        ]
        if len(independently_supported) != 1:
            reason = (
                "independent_values_conflict"
                if len(independently_supported) > 1
                else "independent_agreement_insufficient"
            )
            return self._unresolved(
                scope_id=scope_id,
                considered=eligible,
                excluded=excluded,
                reasons=(reason,),
            )
        value, families = independently_supported[0]
        agreeing = tuple(
            candidate
            for candidate in eligible
            if candidate.numeric_value == value and candidate.independent_family in families
        )
        return self._selected(
            scope_id=scope_id,
            candidate=self._best(agreeing),
            basis=ArbitrationBasis.INDEPENDENT_AGREEMENT,
            state=VerificationState.CROSS_MODEL_VERIFIED,
            considered=eligible,
            excluded=excluded,
        )

    def arbitrate_structure(
        self, scope_id: str, candidates: tuple[ArbitrationCandidate, ...]
    ) -> ArbitrationDecision:
        excluded = tuple(candidate for candidate in candidates if not candidate.hard_gate_pass)
        eligible = tuple(
            candidate
            for candidate in candidates
            if candidate.hard_gate_pass and candidate.structure_fingerprint is not None
        )
        if not eligible:
            return self._unresolved(
                scope_id=scope_id,
                considered=eligible,
                excluded=excluded,
                reasons=("no_hard_gate_passing_structure_candidate",),
            )
        tiers: tuple[tuple[ArbitrationBasis, Callable[[ArbitrationCandidate], bool]], ...] = (
            (ArbitrationBasis.SOURCE_GEOMETRY, lambda candidate: candidate.source_geometry_exact),
            (ArbitrationBasis.TABLE_CELL_MAP, lambda candidate: candidate.table_cell_map_exact),
            (
                ArbitrationBasis.DOWNSTREAM_CONSISTENCY,
                lambda candidate: candidate.downstream_consistent,
            ),
        )
        for basis, predicate in tiers:
            supported = tuple(candidate for candidate in eligible if predicate(candidate))
            if not supported:
                continue
            if len({candidate.structure_fingerprint for candidate in supported}) != 1:
                return self._unresolved(
                    scope_id=scope_id,
                    considered=eligible,
                    excluded=excluded,
                    reasons=(f"{basis.value}_conflict",),
                )
            return self._selected(
                scope_id=scope_id,
                candidate=self._best(supported),
                basis=basis,
                state=VerificationState.VERIFIED,
                considered=eligible,
                excluded=excluded,
            )
        return self._unresolved(
            scope_id=scope_id,
            considered=eligible,
            excluded=excluded,
            reasons=("objective_structure_evidence_insufficient",),
        )


__all__ = [
    "ArbitrationBasis",
    "ArbitrationCandidate",
    "ArbitrationDecision",
    "Arbitrator",
]
