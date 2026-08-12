"""Small orchestration facade that composes the v6 safety-critical domain core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from .arbitration import ArbitrationDecision
from .attempts import AcceptanceResult, AttemptStore
from .contracts import EventJournal
from .models import (
    ACCEPTED_VERIFICATION_STATES,
    AttemptOutput,
    AttemptSnapshot,
    AttemptStatus,
)
from .sharding import ParseShard, ShardPlan
from .validation import CandidateObservation, ValidationPolicy, ValidationResult, ValidatorPipeline


@dataclass(frozen=True, slots=True)
class DispatchSpec:
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


class ParallelCoordinator:
    """Coordinates state changes without weakening the underlying fail-closed contracts."""

    def __init__(
        self,
        *,
        events: EventJournal | None = None,
        attempts: AttemptStore | None = None,
        validator: ValidatorPipeline | None = None,
    ) -> None:
        self.events = events or EventJournal()
        self.attempts = attempts or AttemptStore(events=self.events)
        self.validator = validator or ValidatorPipeline()
        self._planned_shards: dict[str, tuple[str, str, ParseShard]] = {}
        self._lock = RLock()

    def record_plan(
        self, plan: ShardPlan, *, occurred_at: datetime, idempotency_prefix: str
    ) -> None:
        with self._lock:
            for shard in plan.shards:
                identity = (plan.document_id, plan.document_version_id, shard)
                existing = self._planned_shards.get(shard.shard_id)
                if existing is not None and existing != identity:
                    raise RuntimeError("planned shard identity cannot be mutated")
                self.events.append(
                    event_type="shard.planned.v1",
                    aggregate_id=shard.shard_id,
                    payload={
                        "document_version_id": plan.document_version_id,
                        "primary_page_ids": shard.primary_page_ids,
                        "context_page_ids": shard.context_page_ids,
                        "policy_version": plan.policy_version,
                    },
                    occurred_at=occurred_at,
                    idempotency_key=f"{idempotency_prefix}:{shard.shard_id}",
                )
                self._planned_shards[shard.shard_id] = identity

    def dispatch(
        self,
        spec: DispatchSpec,
        *,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> AttemptSnapshot:
        with self._lock:
            planned = self._planned_shards.get(spec.shard_id)
            if planned is None:
                raise RuntimeError("cannot dispatch an unplanned shard")
            planned_document_id, planned_version_id, shard = planned
            if (
                spec.document_id != planned_document_id
                or spec.document_version_id != planned_version_id
                or spec.page_ids != shard.primary_page_ids
            ):
                raise RuntimeError("dispatch spec does not match the immutable shard plan")
        snapshot = self.attempts.create_root(
            idempotency_key=idempotency_key,
            document_id=spec.document_id,
            document_version_id=spec.document_version_id,
            shard_id=spec.shard_id,
            page_ids=spec.page_ids,
            region_ids=spec.region_ids,
            parser_recipe=spec.parser_recipe,
            model_revision=spec.model_revision,
            runtime_image_digest=spec.runtime_image_digest,
            worker_id=spec.worker_id,
            gpu_type=spec.gpu_type,
            source_sha256=spec.source_sha256,
            preprocessing_sha256=spec.preprocessing_sha256,
            prompt_sha256=spec.prompt_sha256,
            decoding_sha256=spec.decoding_sha256,
            created_at=occurred_at,
        )
        if snapshot.status is AttemptStatus.CREATED:
            snapshot = self.attempts.transition(
                snapshot.attempt.attempt_id,
                expected_status=AttemptStatus.CREATED,
                to_status=AttemptStatus.QUEUED,
                occurred_at=occurred_at,
                reason_code="shard_dispatched",
            )
        self.events.append(
            event_type="shard.dispatched.v1",
            aggregate_id=spec.shard_id,
            payload={
                "attempt_id": snapshot.attempt.attempt_id,
                "worker_id": spec.worker_id,
                "parser_recipe": spec.parser_recipe,
            },
            occurred_at=occurred_at,
            idempotency_key=f"shard-dispatched:{idempotency_key}",
        )
        return snapshot

    def start(self, attempt_id: str, *, occurred_at: datetime) -> AttemptSnapshot:
        snapshot = self.attempts.get(attempt_id)
        if snapshot.status is AttemptStatus.RUNNING:
            return snapshot
        return self.attempts.transition(
            attempt_id,
            expected_status=AttemptStatus.QUEUED,
            to_status=AttemptStatus.RUNNING,
            occurred_at=occurred_at,
            reason_code="worker_execution_started",
        )

    def receive_and_validate(
        self,
        attempt_id: str,
        *,
        output: AttemptOutput,
        observation: CandidateObservation,
        policy: ValidationPolicy,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> tuple[AttemptSnapshot, ValidationResult]:
        before_output = self.attempts.get(attempt_id)
        if policy.expected_page_ids != before_output.attempt.page_ids:
            raise RuntimeError("validation policy must cover the exact attempted page scope")
        snapshot = self.attempts.attach_output(
            attempt_id,
            output,
            idempotency_key=f"output:{idempotency_key}",
        )
        validation = self.validator.validate(observation, policy)
        snapshot = self.attempts.record_validation(
            attempt_id,
            validation_digest=validation.digest,
            passed=validation.passed,
            occurred_at=occurred_at,
            failure_reason=(
                validation.findings[0].code if validation.findings else "hard_gate_failed"
            ),
        )
        return snapshot, validation

    def accept_arbitrated(
        self,
        decision: ArbitrationDecision,
        *,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> AcceptanceResult:
        if not decision.accepted or decision.selected_attempt_id is None:
            raise RuntimeError("unresolved arbitration cannot be accepted")
        if decision.selected_attempt_id not in decision.considered_attempt_ids:
            raise RuntimeError("arbitration winner is absent from the considered candidate set")
        if decision.verification_state not in ACCEPTED_VERIFICATION_STATES:
            raise RuntimeError("arbitration verification state is not accepted")
        snapshot = self.attempts.get(decision.selected_attempt_id)
        if snapshot.validation_digest is None:
            raise RuntimeError("arbitration cannot bypass deterministic validation")
        if (
            snapshot.output is None
            or snapshot.output.prediction_sha256 != decision.selected_prediction_sha256
        ):
            raise RuntimeError("arbitration prediction identity does not match immutable output")
        return self.attempts.accept(
            decision.selected_attempt_id,
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
        )


__all__ = ["DispatchSpec", "ParallelCoordinator"]
