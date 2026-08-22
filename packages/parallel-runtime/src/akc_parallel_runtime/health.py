"""Independent infrastructure and semantic worker health projections."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import RLock
from typing import ClassVar

from .contracts import EventJournal
from .models import AttemptStatus, WorkerSnapshot, WorkerState


class WorkerRegistrationConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class InfrastructureObservation:
    observed_at: datetime
    ping: bool
    process: bool
    gpu: bool
    ram: bool
    disk: bool
    model_loaded: bool
    cuda_ready: bool
    request_response: bool
    heartbeat: bool
    model_identity_matches: bool
    checksum_matches: bool
    memory_slope_exceeded: bool = False
    latency_p99_spike: bool = False

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("infrastructure observation time must be timezone-aware")

    @property
    def base_healthy(self) -> bool:
        return all(
            (
                self.ping,
                self.process,
                self.gpu,
                self.ram,
                self.disk,
                self.model_loaded,
                self.cuda_ready,
                self.request_response,
                self.heartbeat,
            )
        )


@dataclass(frozen=True, slots=True)
class SemanticObservation:
    attempt_id: str
    shard_id: str
    observed_at: datetime
    validator_passed: bool
    source_coverage: float
    critical_numeric_failure: bool = False
    page_omission: bool = False
    repetition: bool = False
    schema_failure: bool = False
    row_omission: bool = False
    empty_output: bool = False
    latency_outlier: bool = False
    output_length_drift: bool = False
    canary_reproduced: bool = False
    canary_fixture_failed: bool = False

    def __post_init__(self) -> None:
        if not self.attempt_id or not self.shard_id:
            raise ValueError("semantic observations require attempt and shard ids")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("semantic observation time must be timezone-aware")
        if not 0 <= self.source_coverage <= 1:
            raise ValueError("source coverage must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class HealthTransition:
    worker_id: str
    from_state: WorkerState
    to_state: WorkerState
    occurred_at: datetime
    reason_codes: tuple[str, ...]
    semantic_score: float


@dataclass(frozen=True, slots=True)
class QuarantineImpact:
    worker_id: str
    pending_attempt_ids: tuple[str, ...]
    accepted_attempt_ids_for_analysis: tuple[str, ...]
    shard_ids_to_replay: tuple[str, ...]


@dataclass(slots=True)
class _WorkerRecord:
    worker_id: str
    model_revision: str
    runtime_image_digest: str
    capabilities: frozenset[str]
    warm: bool
    cached_models: frozenset[str]
    estimated_available_at: float
    state: WorkerState = WorkerState.HEALTHY
    semantic_score: float = 100.0
    infrastructure: list[InfrastructureObservation] = field(default_factory=list)
    semantics: list[SemanticObservation] = field(default_factory=list)
    attempts: list[tuple[str, str, AttemptStatus]] = field(default_factory=list)
    transitions: list[HealthTransition] = field(default_factory=list)
    # When the infrastructure channel last produced a signal for this worker.
    # Seeded at registration so a worker that is never observed at all is still
    # measurable; see WorkerHealthRegistry.evaluate_liveness.
    last_signal_at: datetime | None = None

    def snapshot(self) -> WorkerSnapshot:
        return WorkerSnapshot(
            worker_id=self.worker_id,
            model_revision=self.model_revision,
            runtime_image_digest=self.runtime_image_digest,
            state=self.state,
            capabilities=self.capabilities,
            warm=self.warm,
            cached_models=self.cached_models,
            estimated_available_at=self.estimated_available_at,
            semantic_score=self.semantic_score,
        )


class WorkerHealthRegistry:
    _STATE_RANK: ClassVar[dict[WorkerState, int]] = {
        WorkerState.HEALTHY: 0,
        WorkerState.DEGRADED: 1,
        WorkerState.DRAINING: 2,
        WorkerState.QUARANTINED: 3,
        WorkerState.TERMINATED: 4,
    }

    def __init__(
        self,
        *,
        events: EventJournal | None = None,
        semantic_window: int = 20,
        signal_stale_after: timedelta = timedelta(minutes=5),
        signal_silent_after: timedelta = timedelta(minutes=20),
    ) -> None:
        if semantic_window < 3:
            raise ValueError("semantic health window must contain at least three attempts")
        if signal_stale_after <= timedelta(0):
            raise ValueError("stale signal threshold must be positive")
        if signal_silent_after <= signal_stale_after:
            raise ValueError("silent signal threshold must exceed the stale threshold")
        self._records: dict[str, _WorkerRecord] = {}
        self._events = events
        self._window = semantic_window
        self._stale_after = signal_stale_after
        self._silent_after = signal_silent_after
        self._lock = RLock()

    def register(
        self,
        *,
        worker_id: str,
        model_revision: str,
        runtime_image_digest: str,
        capabilities: frozenset[str],
        warm: bool,
        cached_models: frozenset[str] = frozenset(),
        estimated_available_at: float = 0.0,
        registered_at: datetime | None = None,
    ) -> WorkerSnapshot:
        if registered_at is not None and (
            registered_at.tzinfo is None or registered_at.utcoffset() is None
        ):
            raise ValueError("worker registration time must be timezone-aware")
        proposed = (
            model_revision,
            runtime_image_digest,
            capabilities,
            warm,
            cached_models,
            estimated_available_at,
        )
        with self._lock:
            existing = self._records.get(worker_id)
            if existing is not None:
                observed = (
                    existing.model_revision,
                    existing.runtime_image_digest,
                    existing.capabilities,
                    existing.warm,
                    existing.cached_models,
                    existing.estimated_available_at,
                )
                if observed != proposed:
                    raise WorkerRegistrationConflict(
                        "worker identity cannot be mutated after registration"
                    )
                return existing.snapshot()
            record = _WorkerRecord(
                worker_id=worker_id,
                model_revision=model_revision,
                runtime_image_digest=runtime_image_digest,
                capabilities=capabilities,
                warm=warm,
                cached_models=cached_models,
                estimated_available_at=estimated_available_at,
                last_signal_at=registered_at,
            )
            self._records[worker_id] = record
            return record.snapshot()

    def snapshot(self, worker_id: str) -> WorkerSnapshot:
        with self._lock:
            return self._records[worker_id].snapshot()

    @staticmethod
    def _semantic_score(observations: list[SemanticObservation]) -> float:
        score = 100.0
        for observation in observations:
            score -= 30 * int(observation.critical_numeric_failure)
            score -= 20 * int(observation.page_omission or observation.empty_output)
            score -= 15 * int(observation.repetition)
            score -= 10 * int(observation.schema_failure)
            score -= 10 * int(observation.row_omission)
            score -= 5 * int(observation.latency_outlier)
            score -= 5 * int(observation.output_length_drift)
            if observation.source_coverage < 1:
                score -= min(10.0, (1 - observation.source_coverage) * 20)
        return round(max(0.0, min(100.0, score)), 6)

    def _transition(
        self,
        record: _WorkerRecord,
        *,
        state: WorkerState,
        occurred_at: datetime,
        reasons: tuple[str, ...],
    ) -> HealthTransition | None:
        if state is record.state:
            return None
        if self._STATE_RANK[state] < self._STATE_RANK[record.state]:
            raise RuntimeError("worker health promotion requires explicit canary restoration")
        transition = HealthTransition(
            worker_id=record.worker_id,
            from_state=record.state,
            to_state=state,
            occurred_at=occurred_at,
            reason_codes=tuple(sorted(reasons)),
            semantic_score=record.semantic_score,
        )
        record.state = state
        record.transitions.append(transition)
        if self._events is not None:
            event_type = {
                WorkerState.DEGRADED: "worker.semantic.degraded.v1",
                WorkerState.DRAINING: "worker.draining.v1",
                WorkerState.QUARANTINED: "worker.quarantined.v1",
            }.get(state)
            if event_type is not None:
                self._events.append(
                    event_type=event_type,
                    aggregate_id=record.worker_id,
                    payload={
                        "reason_codes": transition.reason_codes,
                        "semantic_score": record.semantic_score,
                    },
                    occurred_at=occurred_at,
                    idempotency_key=(
                        f"worker-health:{record.worker_id}:{state.value}:{len(record.transitions)}"
                    ),
                )
        return transition

    def record_infrastructure(
        self, worker_id: str, observation: InfrastructureObservation
    ) -> WorkerSnapshot:
        with self._lock:
            record = self._records[worker_id]
            record.infrastructure.append(observation)
            if (
                record.last_signal_at is None
                or observation.observed_at > record.last_signal_at
            ):
                record.last_signal_at = observation.observed_at
            if record.state in {WorkerState.QUARANTINED, WorkerState.TERMINATED}:
                return record.snapshot()
            if not observation.model_identity_matches or not observation.checksum_matches:
                infra_reasons = tuple(
                    code
                    for code, failed in (
                        ("model_identity_mismatch", not observation.model_identity_matches),
                        ("model_checksum_mismatch", not observation.checksum_matches),
                    )
                    if failed
                )
                self._transition(
                    record,
                    state=WorkerState.QUARANTINED,
                    occurred_at=observation.observed_at,
                    reasons=infra_reasons,
                )
            elif (
                not observation.base_healthy
                or observation.memory_slope_exceeded
                or observation.latency_p99_spike
            ):
                drain_reasons: list[str] = []
                if not observation.base_healthy:
                    drain_reasons.append("infrastructure_probe_failed")
                if observation.memory_slope_exceeded:
                    drain_reasons.append("memory_slope_exceeded")
                if observation.latency_p99_spike:
                    drain_reasons.append("latency_p99_spike")
                self._transition(
                    record,
                    state=WorkerState.DRAINING,
                    occurred_at=observation.observed_at,
                    reasons=tuple(drain_reasons),
                )
            return record.snapshot()

    def evaluate_liveness(self, now: datetime) -> tuple[HealthTransition, ...]:
        """Demote workers whose infrastructure channel has gone quiet.

        Every other transition in this registry is driven by an observation that
        *arrived*. That leaves the one failure mode where nothing arrives at all:
        if the probe transport hangs, the provider poll never produces an
        observation, and a purely reactive registry cannot tell a silent worker
        apart from one that simply has not been polled yet. A live campaign lost
        five and a half hours to exactly that shape — the pods were healthy and
        their work had finished, but the control channel was wedged and no
        signal was ever emitted.

        The caller supplies ``now`` and decides the sweep cadence, so the rule
        stays deterministic and testable with no background timer. Silence is
        measured from the last infrastructure observation, or from the
        registration time for a worker that was never observed at all.
        """
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("liveness evaluation time must be timezone-aware")
        transitions: list[HealthTransition] = []
        with self._lock:
            for record in self._records.values():
                if record.state in {WorkerState.QUARANTINED, WorkerState.TERMINATED}:
                    continue
                baseline = record.last_signal_at
                if baseline is None:
                    # Nothing to measure against: the caller never told the
                    # registry when this worker started being observable.
                    continue
                silence = now - baseline
                if silence >= self._silent_after:
                    state = WorkerState.QUARANTINED
                    reason = "infrastructure_signal_silent"
                elif silence >= self._stale_after:
                    state = WorkerState.DRAINING
                    reason = "infrastructure_signal_stale"
                else:
                    continue
                transition = self._transition(
                    record,
                    state=state,
                    occurred_at=now,
                    reasons=(reason,),
                )
                if transition is not None:
                    transitions.append(transition)
        return tuple(transitions)

    def terminate(
        self, worker_id: str, *, occurred_at: datetime, reason: str
    ) -> HealthTransition | None:
        """Record that a worker's underlying resource is permanently gone.

        Quarantine says "stop trusting this worker"; it still assumes the worker
        exists and can be inspected. Nothing expressed "the resource was
        destroyed and is never coming back", so a Pod deleted out from under the
        campaign — by a cost backstop, a provider reclaim, or an operator — left
        a quarantined record that a reader could mistake for recoverable. The
        distinction matters to the caller that has to decide between waiting and
        acquiring a replacement.
        """
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("termination time must be timezone-aware")
        if not reason:
            raise ValueError("termination requires a reason code")
        with self._lock:
            record = self._records[worker_id]
            if record.state is WorkerState.TERMINATED:
                return None
            return self._transition(
                record,
                state=WorkerState.TERMINATED,
                occurred_at=occurred_at,
                reasons=(reason,),
            )

    def serving_workers(self) -> tuple[str, ...]:
        """Workers that can still accept new work.

        DRAINING is deliberately excluded: a draining worker finishes what it
        holds and takes nothing new, so counting it as capacity would hide a
        deficit until the last attempt completed.
        """
        with self._lock:
            return tuple(
                sorted(
                    record.worker_id
                    for record in self._records.values()
                    if record.state in {WorkerState.HEALTHY, WorkerState.DEGRADED}
                )
            )

    def unmonitored_workers(self) -> tuple[str, ...]:
        """Workers whose silence cannot be measured because no baseline exists."""
        with self._lock:
            return tuple(
                sorted(
                    record.worker_id
                    for record in self._records.values()
                    if record.last_signal_at is None
                    and record.state
                    not in {WorkerState.QUARANTINED, WorkerState.TERMINATED}
                )
            )

    def record_semantic(
        self, worker_id: str, observation: SemanticObservation
    ) -> WorkerSnapshot:
        with self._lock:
            record = self._records[worker_id]
            record.semantics.append(observation)
            window = record.semantics[-self._window :]
            record.semantic_score = self._semantic_score(window)
            if record.state in {WorkerState.QUARANTINED, WorkerState.TERMINATED}:
                return record.snapshot()
            recent_schema_failures = 0
            recent_repetitions = 0
            for item in reversed(window):
                if item.schema_failure:
                    recent_schema_failures += 1
                else:
                    break
            for item in reversed(window):
                if item.repetition:
                    recent_repetitions += 1
                else:
                    break
            if observation.canary_fixture_failed or (
                observation.critical_numeric_failure and observation.canary_reproduced
            ):
                self._transition(
                    record,
                    state=WorkerState.QUARANTINED,
                    occurred_at=observation.observed_at,
                    reasons=(
                        (
                            "canary_fixture_failure"
                            if observation.canary_fixture_failed
                            else "critical_numeric_failure_reproduced"
                        ),
                    ),
                )
            elif (
                recent_schema_failures >= 3
                or recent_repetitions >= 2
                or record.semantic_score < 50
            ):
                reasons: list[str] = []
                if recent_schema_failures >= 3:
                    reasons.append("consecutive_schema_failures")
                if recent_repetitions >= 2:
                    reasons.append("consecutive_repetition")
                if record.semantic_score < 50:
                    reasons.append("semantic_score_critical")
                self._transition(
                    record,
                    state=WorkerState.DRAINING,
                    occurred_at=observation.observed_at,
                    reasons=tuple(reasons),
                )
            elif (
                not observation.validator_passed
                or observation.empty_output
                or observation.row_omission
                or record.semantic_score < 85
            ):
                self._transition(
                    record,
                    state=WorkerState.DEGRADED,
                    occurred_at=observation.observed_at,
                    reasons=("semantic_quality_degraded",),
                )
            return record.snapshot()

    def record_attempt(
        self,
        worker_id: str,
        *,
        attempt_id: str,
        shard_id: str,
        status: AttemptStatus,
    ) -> None:
        with self._lock:
            record = self._records[worker_id]
            item = (attempt_id, shard_id, status)
            if item not in record.attempts:
                record.attempts.append(item)

    def quarantine_impact(self, worker_id: str, *, recent_n: int = 100) -> QuarantineImpact:
        if recent_n < 1:
            raise ValueError("recent_n must be positive")
        with self._lock:
            record = self._records[worker_id]
            if record.state is not WorkerState.QUARANTINED:
                raise RuntimeError("influence analysis requires a quarantined worker")
            recent = record.attempts[-recent_n:]
            latest: dict[str, tuple[str, str, AttemptStatus]] = {}
            for attempt_id, shard_id, status in recent:
                latest[attempt_id] = (attempt_id, shard_id, status)
            current = tuple(latest.values())
            accepted = tuple(
                attempt_id
                for attempt_id, _, status in current
                if status is AttemptStatus.ACCEPTED
            )
            terminal = {
                AttemptStatus.REJECTED,
                AttemptStatus.RETRYABLE_FAILED,
                AttemptStatus.TERMINAL_FAILED,
                AttemptStatus.SUPERSEDED,
                AttemptStatus.QUARANTINED,
            }
            pending = tuple(
                attempt_id
                for attempt_id, _, status in current
                if status not in terminal and status is not AttemptStatus.ACCEPTED
            )
            replay_shards = tuple(
                sorted(
                    {
                        shard_id
                        for _, shard_id, status in current
                        if status not in terminal or status is AttemptStatus.ACCEPTED
                    }
                )
            )
            return QuarantineImpact(
                worker_id=worker_id,
                pending_attempt_ids=pending,
                accepted_attempt_ids_for_analysis=accepted,
                shard_ids_to_replay=replay_shards,
            )

    def transitions(self, worker_id: str) -> tuple[HealthTransition, ...]:
        with self._lock:
            return tuple(self._records[worker_id].transitions)


__all__ = [
    "HealthTransition",
    "InfrastructureObservation",
    "QuarantineImpact",
    "SemanticObservation",
    "WorkerHealthRegistry",
    "WorkerRegistrationConflict",
]
