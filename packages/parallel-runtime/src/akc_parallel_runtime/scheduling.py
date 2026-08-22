"""Fair size-aware scheduling, backpressure, hedging, and scale decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from math import ceil
from threading import RLock

from .contracts import EventJournal
from .identity import canonical_sha256, stable_id
from .models import WorkerSnapshot, WorkerState


class JobPriority(IntEnum):
    TINY_QUICK = 0
    INTERACTIVE = 1
    BENCHMARK = 2
    RECOVERY = 3
    BULK_BACKGROUND = 4


@dataclass(frozen=True, slots=True)
class WorkItem:
    work_id: str
    shard_id: str
    priority: JobPriority
    estimated_seconds: float
    required_capabilities: frozenset[str]
    model_cache_key: str
    enqueued_at: datetime
    sequence: int

    def __post_init__(self) -> None:
        if not self.work_id or not self.shard_id or not self.model_cache_key:
            raise ValueError("work identity fields are required")
        if self.estimated_seconds < 0 or self.sequence < 0:
            raise ValueError("work duration and sequence cannot be negative")
        if self.enqueued_at.tzinfo is None or self.enqueued_at.utcoffset() is None:
            raise ValueError("work enqueue time must be timezone-aware")


class FairPriorityQueue:
    """Deterministic priority queue with aging so background work cannot starve."""

    def __init__(self, *, aging_seconds: float = 30.0) -> None:
        if aging_seconds <= 0:
            raise ValueError("aging_seconds must be positive")
        self._aging_seconds = aging_seconds
        self._items: dict[str, WorkItem] = {}
        self._lock = RLock()

    def put(self, item: WorkItem) -> WorkItem:
        with self._lock:
            existing = self._items.get(item.work_id)
            if existing is not None and existing != item:
                raise RuntimeError("work id cannot be reused with different scheduling input")
            self._items[item.work_id] = item
            return item

    def _sort_key(self, item: WorkItem, now: datetime) -> tuple[float, float, int, str]:
        waited = max(0.0, (now - item.enqueued_at).total_seconds())
        effective = max(0.0, float(item.priority) - waited / self._aging_seconds)
        return effective, item.estimated_seconds, item.sequence, item.work_id

    def pop(self, *, now: datetime) -> WorkItem:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("queue time must be timezone-aware")
        with self._lock:
            if not self._items:
                raise IndexError("queue is empty")
            item = min(self._items.values(), key=lambda candidate: self._sort_key(candidate, now))
            del self._items[item.work_id]
            return item

    def snapshot(self, *, now: datetime) -> tuple[WorkItem, ...]:
        with self._lock:
            return tuple(sorted(self._items.values(), key=lambda item: self._sort_key(item, now)))

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


class WorkerSelector:
    @staticmethod
    def select(item: WorkItem, workers: tuple[WorkerSnapshot, ...]) -> WorkerSnapshot:
        compatible = tuple(
            worker
            for worker in workers
            if worker.state in {WorkerState.HEALTHY, WorkerState.DEGRADED}
            and item.required_capabilities.issubset(worker.capabilities)
        )
        if not compatible:
            raise RuntimeError("no healthy compatible worker is available")
        return sorted(
            compatible,
            key=lambda worker: (
                0 if worker.state is WorkerState.HEALTHY else 1,
                0 if worker.warm else 1,
                0 if item.model_cache_key in worker.cached_models else 1,
                worker.estimated_available_at + item.estimated_seconds,
                -worker.semantic_score,
                worker.worker_id,
            ),
        )[0]


def size_aware_bin_pack(
    work: tuple[WorkItem, ...], worker_ids: tuple[str, ...]
) -> dict[str, tuple[WorkItem, ...]]:
    if not worker_ids or len(worker_ids) != len(set(worker_ids)):
        raise ValueError("unique worker ids are required")
    loads = {worker_id: 0.0 for worker_id in worker_ids}
    assignments: dict[str, list[WorkItem]] = {worker_id: [] for worker_id in worker_ids}
    for item in sorted(work, key=lambda value: (-value.estimated_seconds, value.work_id)):
        worker_id = min(worker_ids, key=lambda value: (loads[value], value))
        assignments[worker_id].append(item)
        loads[worker_id] += item.estimated_seconds
    return {worker_id: tuple(items) for worker_id, items in assignments.items()}


@dataclass(frozen=True, slots=True)
class BackpressureSnapshot:
    queue_depth: int
    queue_high_watermark: int
    presigned_url_seconds_remaining: float
    estimated_work_seconds: float
    object_cache_available: bool
    evaluator_capacity: int
    database_capacity: int
    cost_anomaly: bool = False

    def __post_init__(self) -> None:
        if any(
            value < 0
            for value in (
                self.queue_depth,
                self.queue_high_watermark,
                self.presigned_url_seconds_remaining,
                self.estimated_work_seconds,
                self.evaluator_capacity,
                self.database_capacity,
            )
        ):
            raise ValueError("backpressure values cannot be negative")


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    admitted: bool
    reason_codes: tuple[str, ...]


def evaluate_backpressure(
    snapshot: BackpressureSnapshot, *, url_safety_margin_seconds: float = 60.0
) -> AdmissionDecision:
    reasons: list[str] = []
    if snapshot.queue_depth >= snapshot.queue_high_watermark:
        reasons.append("queue_high_watermark")
    if snapshot.presigned_url_seconds_remaining < (
        snapshot.estimated_work_seconds + url_safety_margin_seconds
    ):
        reasons.append("presigned_url_expiry_risk")
    if not snapshot.object_cache_available:
        reasons.append("object_cache_unavailable")
    if snapshot.evaluator_capacity < 1:
        reasons.append("evaluator_capacity_exhausted")
    if snapshot.database_capacity < 1:
        reasons.append("database_capacity_exhausted")
    if snapshot.cost_anomaly:
        reasons.append("cost_anomaly")
    return AdmissionDecision(admitted=not reasons, reason_codes=tuple(sorted(reasons)))


@dataclass(frozen=True, slots=True)
class HedgeDecision:
    hedge_id: str | None
    launch: bool
    reason_code: str
    original_attempt_id: str
    alternate_worker_id: str | None


class HedgeConflictError(RuntimeError):
    pass


class HedgeController:
    def __init__(
        self,
        *,
        events: EventJournal | None = None,
        threshold_multiplier: float = 1.2,
    ) -> None:
        if threshold_multiplier <= 1:
            raise ValueError("hedge threshold multiplier must exceed one")
        self._events = events
        self._threshold = threshold_multiplier
        self._requests: dict[str, tuple[str, HedgeDecision]] = {}
        self._launched_by_attempt: dict[tuple[str, str], HedgeDecision] = {}
        self._lock = RLock()

    def decide(
        self,
        *,
        original_attempt_id: str,
        shard_id: str,
        elapsed_seconds: float,
        predicted_p95_seconds: float,
        alternate_worker_id: str | None,
        original_verified: bool,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> HedgeDecision:
        if elapsed_seconds < 0 or predicted_p95_seconds <= 0:
            raise ValueError("hedge timing must be positive")
        identity = canonical_sha256(
            {
                "original_attempt_id": original_attempt_id,
                "shard_id": shard_id,
                "elapsed_seconds": elapsed_seconds,
                "predicted_p95_seconds": predicted_p95_seconds,
                "alternate_worker_id": alternate_worker_id,
                "original_verified": original_verified,
            }
        )
        with self._lock:
            existing = self._requests.get(idempotency_key)
            if existing is not None:
                existing_identity, decision = existing
                if existing_identity != identity:
                    raise HedgeConflictError("hedge key reused with different hedge input")
                return decision
            launched = self._launched_by_attempt.get((original_attempt_id, shard_id))
            if launched is not None:
                if launched.alternate_worker_id != alternate_worker_id:
                    raise HedgeConflictError(
                        "a shard attempt cannot launch multiple hedge workers"
                    )
                self._requests[idempotency_key] = (identity, launched)
                return launched
            if original_verified:
                decision = HedgeDecision(
                    hedge_id=None,
                    launch=False,
                    reason_code="original_already_verified",
                    original_attempt_id=original_attempt_id,
                    alternate_worker_id=None,
                )
            elif alternate_worker_id is None:
                decision = HedgeDecision(
                    hedge_id=None,
                    launch=False,
                    reason_code="no_alternate_worker",
                    original_attempt_id=original_attempt_id,
                    alternate_worker_id=None,
                )
            elif elapsed_seconds <= predicted_p95_seconds * self._threshold:
                decision = HedgeDecision(
                    hedge_id=None,
                    launch=False,
                    reason_code="below_hedge_threshold",
                    original_attempt_id=original_attempt_id,
                    alternate_worker_id=None,
                )
            else:
                hedge_id = stable_id(
                    "hedge", original_attempt_id, shard_id, alternate_worker_id, idempotency_key
                )
                decision = HedgeDecision(
                    hedge_id=hedge_id,
                    launch=True,
                    reason_code="predicted_p95_exceeded",
                    original_attempt_id=original_attempt_id,
                    alternate_worker_id=alternate_worker_id,
                )
                if self._events is not None:
                    self._events.append(
                        event_type="attempt.hedged.v1",
                        aggregate_id=original_attempt_id,
                        payload={
                            "hedge_id": hedge_id,
                            "shard_id": shard_id,
                            "alternate_worker_id": alternate_worker_id,
                            "duplicate_billable": False,
                        },
                        occurred_at=occurred_at,
                        idempotency_key=f"attempt-hedged:{idempotency_key}",
                    )
                self._launched_by_attempt[(original_attempt_id, shard_id)] = decision
            self._requests[idempotency_key] = (identity, decision)
            return decision


def straggler_candidates(
    *,
    total_shards: int,
    incomplete_elapsed_seconds: dict[str, float],
    completed_latencies_seconds: tuple[float, ...],
    multiplier: float = 10.0,
) -> tuple[str, ...]:
    if total_shards < 1 or multiplier <= 1:
        raise ValueError("total shards and straggler multiplier must be valid")
    if not completed_latencies_seconds or any(value < 0 for value in completed_latencies_seconds):
        return ()
    if len(incomplete_elapsed_seconds) > max(1, ceil(total_shards * 0.10)):
        return ()
    ordered = sorted(completed_latencies_seconds)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )
    threshold = median * multiplier
    return tuple(
        work_id
        for work_id, elapsed in sorted(incomplete_elapsed_seconds.items())
        if elapsed > threshold
    )


def can_scale_down(
    *,
    queue_empty: bool,
    in_flight: int,
    artifacts_uploaded: bool,
    grace_window_elapsed: bool,
    current_workers: int,
    minimum_workers: int,
) -> bool:
    if in_flight < 0 or current_workers < 0 or minimum_workers < 0:
        raise ValueError("worker counts cannot be negative")
    return (
        queue_empty
        and in_flight == 0
        and artifacts_uploaded
        and grace_window_elapsed
        and current_workers > minimum_workers
    )


__all__ = [
    "AdmissionDecision",
    "BackpressureSnapshot",
    "FairPriorityQueue",
    "HedgeConflictError",
    "HedgeController",
    "HedgeDecision",
    "JobPriority",
    "WorkItem",
    "WorkerSelector",
    "can_scale_down",
    "evaluate_backpressure",
    "size_aware_bin_pack",
    "straggler_candidates",
]
