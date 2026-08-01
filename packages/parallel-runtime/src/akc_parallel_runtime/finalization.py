"""Fail-closed document finalization and export inclusion policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from .contracts import EventJournal
from .identity import canonical_sha256, require_sha256, stable_id
from .models import ACCEPTED_VERIFICATION_STATES, VerificationState


@dataclass(frozen=True, slots=True)
class FinalizationUnit:
    unit_id: str
    state: VerificationState
    prediction_sha256: str | None
    source_refs: tuple[str, ...]
    provenance_attempt_ids: tuple[str, ...]
    required: bool = True
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.unit_id:
            raise ValueError("finalization unit id is required")
        if self.prediction_sha256 is not None:
            require_sha256(self.prediction_sha256, field_name="prediction_sha256")
        if self.state in ACCEPTED_VERIFICATION_STATES and (
            self.prediction_sha256 is None
            or not self.source_refs
            or not self.provenance_attempt_ids
        ):
            raise ValueError("accepted units require prediction, source, and attempt provenance")
        if self.state is VerificationState.AUTO_REPAIRED and len(self.provenance_attempt_ids) < 2:
            raise ValueError("auto-repaired units must preserve base and repair attempt lineage")


@dataclass(frozen=True, slots=True)
class UnresolvedManifestEntry:
    unit_id: str
    state: VerificationState
    reason_codes: tuple[str, ...]
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FinalizationResult:
    finalization_id: str
    document_version_id: str
    merge_sha256: str
    publishable: bool
    accepted_units: tuple[FinalizationUnit, ...]
    unresolved_manifest: tuple[UnresolvedManifestEntry, ...]
    excluded_unit_ids: tuple[str, ...]
    billable_unit_ids: tuple[str, ...]
    manifest_sha256: str
    reason_codes: tuple[str, ...]


class FinalizationConflictError(RuntimeError):
    pass


class Finalizer:
    def __init__(self, *, events: EventJournal | None = None) -> None:
        self._events = events
        self._results: dict[str, tuple[str, FinalizationResult]] = {}
        self._lock = RLock()

    def finalize(
        self,
        *,
        document_version_id: str,
        units: tuple[FinalizationUnit, ...],
        merge_sha256: str,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> FinalizationResult:
        if not units or len({unit.unit_id for unit in units}) != len(units):
            raise ValueError("finalization requires unique non-empty units")
        require_sha256(merge_sha256, field_name="merge_sha256")
        input_digest = canonical_sha256(
            {
                "document_version_id": document_version_id,
                "units": units,
                "merge_sha256": merge_sha256,
            }
        )
        with self._lock:
            existing = self._results.get(idempotency_key)
            if existing is not None:
                existing_digest, result = existing
                if existing_digest != input_digest:
                    raise FinalizationConflictError(
                        "export idempotency key reused with different finalization input"
                    )
                return result
            accepted = tuple(unit for unit in units if unit.state in ACCEPTED_VERIFICATION_STATES)
            unresolved = tuple(
                UnresolvedManifestEntry(
                    unit_id=unit.unit_id,
                    state=unit.state,
                    reason_codes=unit.reason_codes or (f"{unit.state.value}_excluded",),
                    source_refs=unit.source_refs,
                )
                for unit in units
                if unit.state is VerificationState.UNRESOLVED
            )
            excluded = tuple(
                unit.unit_id
                for unit in units
                if unit.state in {VerificationState.QUARANTINED, VerificationState.FAILED}
            )
            required_failures = tuple(
                unit
                for unit in units
                if unit.required and unit.state not in ACCEPTED_VERIFICATION_STATES
            )
            publishable = not required_failures
            reasons = tuple(sorted({f"required_{unit.state.value}" for unit in required_failures}))
            payload = {
                "document_version_id": document_version_id,
                "merge_sha256": merge_sha256,
                "accepted_unit_ids": tuple(unit.unit_id for unit in accepted),
                "unresolved": unresolved,
                "excluded": excluded,
                "publishable": publishable,
                "reason_codes": reasons,
            }
            digest = canonical_sha256(payload)
            result = FinalizationResult(
                finalization_id=stable_id("finalization", document_version_id, digest),
                document_version_id=document_version_id,
                merge_sha256=merge_sha256,
                publishable=publishable,
                accepted_units=accepted,
                unresolved_manifest=unresolved,
                excluded_unit_ids=excluded,
                billable_unit_ids=tuple(unit.unit_id for unit in accepted),
                manifest_sha256=digest,
                reason_codes=reasons,
            )
            self._results[idempotency_key] = (input_digest, result)
            if self._events is not None and publishable:
                self._events.append(
                    event_type="document.finalized.v1",
                    aggregate_id=document_version_id,
                    payload={
                        "finalization_id": result.finalization_id,
                        "manifest_sha256": digest,
                        "accepted_units": len(accepted),
                    },
                    occurred_at=occurred_at,
                    idempotency_key=f"document-finalized:{idempotency_key}",
                )
            return result


__all__ = [
    "FinalizationConflictError",
    "FinalizationResult",
    "FinalizationUnit",
    "Finalizer",
    "UnresolvedManifestEntry",
]
