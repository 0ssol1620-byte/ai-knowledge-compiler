"""Thread-safe immutable attempt lineage and first-verified-wins acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from .contracts import EventJournal
from .identity import canonical_sha256, stable_id
from .models import (
    AttemptKind,
    AttemptOutput,
    AttemptSnapshot,
    AttemptStatus,
    AttemptTransition,
    ParseAttempt,
)


class AttemptError(RuntimeError):
    pass


class AttemptNotFoundError(AttemptError):
    pass


class AttemptConflictError(AttemptError):
    pass


class InvalidAttemptTransition(AttemptError):
    pass


class ImmutableAttemptError(AttemptError):
    pass


_ALLOWED_TRANSITIONS: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    AttemptStatus.CREATED: frozenset({AttemptStatus.QUEUED, AttemptStatus.TERMINAL_FAILED}),
    AttemptStatus.QUEUED: frozenset(
        {
            AttemptStatus.RUNNING,
            AttemptStatus.RETRYABLE_FAILED,
            AttemptStatus.TERMINAL_FAILED,
            AttemptStatus.QUARANTINED,
        }
    ),
    AttemptStatus.RUNNING: frozenset(
        {
            AttemptStatus.OUTPUT_RECEIVED,
            AttemptStatus.RETRYABLE_FAILED,
            AttemptStatus.TERMINAL_FAILED,
            AttemptStatus.QUARANTINED,
        }
    ),
    AttemptStatus.OUTPUT_RECEIVED: frozenset(
        {AttemptStatus.VALIDATING, AttemptStatus.REJECTED, AttemptStatus.QUARANTINED}
    ),
    AttemptStatus.VALIDATING: frozenset(
        {
            AttemptStatus.ACCEPTED,
            AttemptStatus.REJECTED,
            AttemptStatus.RETRYABLE_FAILED,
            AttemptStatus.TERMINAL_FAILED,
            AttemptStatus.SUPERSEDED,
            AttemptStatus.QUARANTINED,
        }
    ),
    AttemptStatus.ACCEPTED: frozenset({AttemptStatus.SUPERSEDED, AttemptStatus.QUARANTINED}),
    AttemptStatus.REJECTED: frozenset(),
    AttemptStatus.RETRYABLE_FAILED: frozenset(),
    AttemptStatus.TERMINAL_FAILED: frozenset(),
    AttemptStatus.SUPERSEDED: frozenset(),
    AttemptStatus.QUARANTINED: frozenset(),
}


@dataclass(slots=True)
class _MutableAttempt:
    attempt: ParseAttempt
    status: AttemptStatus
    output: AttemptOutput | None
    validation_digest: str | None
    transitions: list[AttemptTransition]

    def snapshot(self) -> AttemptSnapshot:
        return AttemptSnapshot(
            attempt=self.attempt,
            status=self.status,
            output=self.output,
            validation_digest=self.validation_digest,
            transitions=tuple(self.transitions),
        )


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    winner: AttemptSnapshot
    challenger: AttemptSnapshot | None
    accepted_new: bool


class AttemptStore:
    """Append-only lineage; only status projections change and every change is logged."""

    def __init__(self, *, events: EventJournal | None = None) -> None:
        self._records: dict[str, _MutableAttempt] = {}
        self._creation_keys: dict[str, str] = {}
        self._acceptance_keys: dict[str, tuple[str, AcceptanceResult]] = {}
        self._accepted_by_shard: dict[str, str] = {}
        self._events = events
        self._lock = RLock()

    @staticmethod
    def _creation_identity(attempt: ParseAttempt) -> str:
        return canonical_sha256(attempt)

    def _create(self, attempt: ParseAttempt, *, idempotency_key: str) -> AttemptSnapshot:
        identity = self._creation_identity(attempt)
        with self._lock:
            existing_id = self._creation_keys.get(idempotency_key)
            if existing_id is not None:
                existing = self._records[existing_id]
                if self._creation_identity(existing.attempt) != identity:
                    raise AttemptConflictError(
                        "attempt idempotency key reused with different immutable fields"
                    )
                return existing.snapshot()
            if attempt.attempt_id in self._records:
                raise AttemptConflictError("attempt_id already exists")
            transition = AttemptTransition(
                sequence=1,
                from_status=None,
                to_status=AttemptStatus.CREATED,
                occurred_at=attempt.created_at,
                reason_code="attempt_created",
            )
            record = _MutableAttempt(
                attempt=attempt,
                status=AttemptStatus.CREATED,
                output=None,
                validation_digest=None,
                transitions=[transition],
            )
            self._records[attempt.attempt_id] = record
            self._creation_keys[idempotency_key] = attempt.attempt_id
            return record.snapshot()

    def create_root(
        self,
        *,
        idempotency_key: str,
        document_id: str,
        document_version_id: str,
        shard_id: str,
        page_ids: tuple[str, ...],
        region_ids: tuple[str, ...],
        parser_recipe: str,
        model_revision: str,
        runtime_image_digest: str,
        worker_id: str,
        gpu_type: str,
        source_sha256: str,
        preprocessing_sha256: str,
        prompt_sha256: str,
        decoding_sha256: str,
        created_at: datetime,
    ) -> AttemptSnapshot:
        attempt_id = stable_id(
            "attempt",
            "root",
            idempotency_key,
            document_version_id,
            shard_id,
            parser_recipe,
            worker_id,
        )
        attempt = ParseAttempt(
            attempt_id=attempt_id,
            root_attempt_id=attempt_id,
            parent_attempt_id=None,
            kind=AttemptKind.PRIMARY,
            document_id=document_id,
            document_version_id=document_version_id,
            shard_id=shard_id,
            page_ids=page_ids,
            region_ids=region_ids,
            parser_recipe=parser_recipe,
            model_revision=model_revision,
            runtime_image_digest=runtime_image_digest,
            worker_id=worker_id,
            gpu_type=gpu_type,
            source_sha256=source_sha256,
            preprocessing_sha256=preprocessing_sha256,
            prompt_sha256=prompt_sha256,
            decoding_sha256=decoding_sha256,
            created_at=created_at,
        )
        return self._create(attempt, idempotency_key=idempotency_key)

    def create_child(
        self,
        parent_attempt_id: str,
        *,
        kind: AttemptKind,
        idempotency_key: str,
        parser_recipe: str,
        model_revision: str,
        runtime_image_digest: str,
        worker_id: str,
        gpu_type: str,
        preprocessing_sha256: str,
        prompt_sha256: str,
        decoding_sha256: str,
        created_at: datetime,
        region_ids: tuple[str, ...] | None = None,
    ) -> AttemptSnapshot:
        if kind is AttemptKind.PRIMARY:
            raise ValueError("child attempts cannot use the primary kind")
        with self._lock:
            parent = self._records.get(parent_attempt_id)
            if parent is None:
                raise AttemptNotFoundError(parent_attempt_id)
            inherited_regions = parent.attempt.region_ids if region_ids is None else region_ids
            if created_at < parent.attempt.created_at:
                raise ValueError("child attempt cannot predate its parent")
            attempt_id = stable_id(
                "attempt",
                parent.attempt.root_attempt_id,
                parent_attempt_id,
                kind,
                idempotency_key,
                parser_recipe,
                worker_id,
                inherited_regions,
            )
            attempt = ParseAttempt(
                attempt_id=attempt_id,
                root_attempt_id=parent.attempt.root_attempt_id,
                parent_attempt_id=parent_attempt_id,
                kind=kind,
                document_id=parent.attempt.document_id,
                document_version_id=parent.attempt.document_version_id,
                shard_id=parent.attempt.shard_id,
                page_ids=parent.attempt.page_ids,
                region_ids=inherited_regions,
                parser_recipe=parser_recipe,
                model_revision=model_revision,
                runtime_image_digest=runtime_image_digest,
                worker_id=worker_id,
                gpu_type=gpu_type,
                source_sha256=parent.attempt.source_sha256,
                preprocessing_sha256=preprocessing_sha256,
                prompt_sha256=prompt_sha256,
                decoding_sha256=decoding_sha256,
                created_at=created_at,
            )
            return self._create(attempt, idempotency_key=idempotency_key)

    def get(self, attempt_id: str) -> AttemptSnapshot:
        with self._lock:
            record = self._records.get(attempt_id)
            if record is None:
                raise AttemptNotFoundError(attempt_id)
            return record.snapshot()

    def lineage(self, root_attempt_id: str) -> tuple[AttemptSnapshot, ...]:
        with self._lock:
            return tuple(
                record.snapshot()
                for record in sorted(
                    (
                        record
                        for record in self._records.values()
                        if record.attempt.root_attempt_id == root_attempt_id
                    ),
                    key=lambda item: (item.attempt.created_at, item.attempt.attempt_id),
                )
            )

    def transition(
        self,
        attempt_id: str,
        *,
        expected_status: AttemptStatus,
        to_status: AttemptStatus,
        occurred_at: datetime,
        reason_code: str,
    ) -> AttemptSnapshot:
        with self._lock:
            record = self._records.get(attempt_id)
            if record is None:
                raise AttemptNotFoundError(attempt_id)
            if record.status is not expected_status:
                raise AttemptConflictError(
                    f"expected {expected_status.value}, observed {record.status.value}"
                )
            if to_status not in _ALLOWED_TRANSITIONS[record.status]:
                raise InvalidAttemptTransition(
                    f"cannot transition {record.status.value} to {to_status.value}"
                )
            if occurred_at < record.transitions[-1].occurred_at:
                raise InvalidAttemptTransition("attempt transitions must be chronological")
            record.transitions.append(
                AttemptTransition(
                    sequence=len(record.transitions) + 1,
                    from_status=record.status,
                    to_status=to_status,
                    occurred_at=occurred_at,
                    reason_code=reason_code,
                )
            )
            record.status = to_status
            if expected_status is AttemptStatus.ACCEPTED and to_status in {
                AttemptStatus.SUPERSEDED,
                AttemptStatus.QUARANTINED,
            }:
                accepted_id = self._accepted_by_shard.get(record.attempt.shard_id)
                if accepted_id == attempt_id:
                    del self._accepted_by_shard[record.attempt.shard_id]
            snapshot = record.snapshot()
            if self._events is not None and to_status is AttemptStatus.RUNNING:
                self._events.append(
                    event_type="attempt.started.v1",
                    aggregate_id=attempt_id,
                    payload={
                        "shard_id": record.attempt.shard_id,
                        "worker_id": record.attempt.worker_id,
                    },
                    occurred_at=occurred_at,
                    idempotency_key=f"attempt-started:{attempt_id}",
                )
            return snapshot

    def attach_output(
        self,
        attempt_id: str,
        output: AttemptOutput,
        *,
        idempotency_key: str,
    ) -> AttemptSnapshot:
        with self._lock:
            record = self._records.get(attempt_id)
            if record is None:
                raise AttemptNotFoundError(attempt_id)
            if record.output is not None:
                if record.output != output:
                    raise ImmutableAttemptError("attempt output cannot be replaced")
                return record.snapshot()
            if record.status is not AttemptStatus.RUNNING:
                raise InvalidAttemptTransition("output can only be attached to a running attempt")
            record.output = output
            snapshot = self.transition(
                attempt_id,
                expected_status=AttemptStatus.RUNNING,
                to_status=AttemptStatus.OUTPUT_RECEIVED,
                occurred_at=output.completed_at,
                reason_code="output_received",
            )
            if self._events is not None:
                self._events.append(
                    event_type="attempt.output.received.v1",
                    aggregate_id=attempt_id,
                    payload={
                        "prediction_sha256": output.prediction_sha256,
                        "prediction_uri": output.prediction_uri,
                    },
                    occurred_at=output.completed_at,
                    idempotency_key=idempotency_key,
                )
            return snapshot

    def record_validation(
        self,
        attempt_id: str,
        *,
        validation_digest: str,
        passed: bool,
        occurred_at: datetime,
        failure_reason: str = "hard_gate_failed",
    ) -> AttemptSnapshot:
        with self._lock:
            record = self._records.get(attempt_id)
            if record is None:
                raise AttemptNotFoundError(attempt_id)
            if record.validation_digest is not None:
                if record.validation_digest != validation_digest:
                    raise ImmutableAttemptError("validation digest cannot be replaced")
                if passed and record.status not in {
                    AttemptStatus.VALIDATING,
                    AttemptStatus.ACCEPTED,
                    AttemptStatus.SUPERSEDED,
                }:
                    raise AttemptConflictError(
                        "validation result cannot change from failed to passed"
                    )
                if not passed and record.status is not AttemptStatus.REJECTED:
                    raise AttemptConflictError(
                        "validation result cannot change from passed to failed"
                    )
                return record.snapshot()
            if record.status is not AttemptStatus.OUTPUT_RECEIVED:
                raise InvalidAttemptTransition("validation requires an output-received attempt")
            record.validation_digest = validation_digest
            self.transition(
                attempt_id,
                expected_status=AttemptStatus.OUTPUT_RECEIVED,
                to_status=AttemptStatus.VALIDATING,
                occurred_at=occurred_at,
                reason_code="validation_started",
            )
            if passed:
                return record.snapshot()
            snapshot = self.transition(
                attempt_id,
                expected_status=AttemptStatus.VALIDATING,
                to_status=AttemptStatus.REJECTED,
                occurred_at=occurred_at,
                reason_code=failure_reason,
            )
            if self._events is not None:
                self._events.append(
                    event_type="attempt.validation.failed.v1",
                    aggregate_id=attempt_id,
                    payload={"validation_sha256": validation_digest, "reason": failure_reason},
                    occurred_at=occurred_at,
                    idempotency_key=f"validation-failed:{attempt_id}:{validation_digest}",
                )
                self._events.append(
                    event_type="attempt.rejected.v1",
                    aggregate_id=attempt_id,
                    payload={"reason": failure_reason},
                    occurred_at=occurred_at,
                    idempotency_key=f"attempt-rejected:{attempt_id}:{validation_digest}",
                )
            return snapshot

    def accept(
        self,
        attempt_id: str,
        *,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> AcceptanceResult:
        with self._lock:
            record = self._records.get(attempt_id)
            if record is None:
                raise AttemptNotFoundError(attempt_id)
            keyed = self._acceptance_keys.get(idempotency_key)
            if keyed is not None:
                keyed_attempt, keyed_result = keyed
                if keyed_attempt != attempt_id:
                    raise AttemptConflictError("acceptance key reused for another attempt")
                return keyed_result
            if record.status is AttemptStatus.ACCEPTED:
                result = AcceptanceResult(record.snapshot(), None, False)
                self._acceptance_keys[idempotency_key] = (attempt_id, result)
                return result
            if record.status is not AttemptStatus.VALIDATING or record.validation_digest is None:
                raise InvalidAttemptTransition("only a validated hard-gate-passing attempt can win")
            existing_id = self._accepted_by_shard.get(record.attempt.shard_id)
            if existing_id is not None:
                existing = self._records[existing_id]
                challenger = self.transition(
                    attempt_id,
                    expected_status=AttemptStatus.VALIDATING,
                    to_status=AttemptStatus.SUPERSEDED,
                    occurred_at=occurred_at,
                    reason_code="first_verified_result_already_accepted",
                )
                result = AcceptanceResult(existing.snapshot(), challenger, False)
                self._acceptance_keys[idempotency_key] = (attempt_id, result)
                return result
            winner = self.transition(
                attempt_id,
                expected_status=AttemptStatus.VALIDATING,
                to_status=AttemptStatus.ACCEPTED,
                occurred_at=occurred_at,
                reason_code="hard_gates_passed_and_arbitrated",
            )
            self._accepted_by_shard[record.attempt.shard_id] = attempt_id
            result = AcceptanceResult(winner, None, True)
            self._acceptance_keys[idempotency_key] = (attempt_id, result)
            if self._events is not None:
                self._events.append(
                    event_type="attempt.accepted.v1",
                    aggregate_id=attempt_id,
                    payload={
                        "shard_id": record.attempt.shard_id,
                        "validation_sha256": record.validation_digest,
                    },
                    occurred_at=occurred_at,
                    idempotency_key=(
                        f"attempt-accepted:{record.attempt.shard_id}:{attempt_id}"
                    ),
                )
            return result

    def quarantine(
        self, attempt_id: str, *, occurred_at: datetime, reason_code: str
    ) -> AttemptSnapshot:
        with self._lock:
            record = self._records.get(attempt_id)
            if record is None:
                raise AttemptNotFoundError(attempt_id)
            if record.status is AttemptStatus.QUARANTINED:
                return record.snapshot()
            if AttemptStatus.QUARANTINED not in _ALLOWED_TRANSITIONS[record.status]:
                raise InvalidAttemptTransition(
                    f"attempt in {record.status.value} cannot be quarantined"
                )
            return self.transition(
                attempt_id,
                expected_status=record.status,
                to_status=AttemptStatus.QUARANTINED,
                occurred_at=occurred_at,
                reason_code=reason_code,
            )


__all__ = [
    "AcceptanceResult",
    "AttemptConflictError",
    "AttemptError",
    "AttemptNotFoundError",
    "AttemptStore",
    "ImmutableAttemptError",
    "InvalidAttemptTransition",
]
