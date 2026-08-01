"""Deterministic capability, fairness, backpressure, and autoscale scheduling."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import IntEnum

from benchmark.v6.contracts import ContractError, canonical_sha256

from .orchestration import SpendState


class QueuePriority(IntEnum):
    TINY_QUICK = 1
    INTERACTIVE = 2
    BENCHMARK_SHARD = 3
    RECOVERY = 4
    BULK_BACKGROUND = 5


@dataclass(frozen=True, slots=True)
class WorkUnit:
    work_id: str
    tenant_id: str
    priority: QueuePriority
    predicted_seconds: float
    required_capabilities: frozenset[str]
    enqueued_at: datetime
    input_url_expires_at: datetime

    def __post_init__(self) -> None:
        if not self.work_id.strip() or not self.tenant_id.strip():
            raise ContractError("work_id and tenant_id are required")
        if self.predicted_seconds <= 0 or not math.isfinite(self.predicted_seconds):
            raise ContractError("predicted_seconds must be finite and positive")
        if not self.required_capabilities:
            raise ContractError("at least one required capability is required")
        if self.enqueued_at.tzinfo is None or self.input_url_expires_at.tzinfo is None:
            raise ContractError("queue timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class WorkerObservation:
    worker_id: str
    pool_id: str
    capabilities: frozenset[str]
    infrastructure_healthy: bool
    semantic_health_score: float
    warm: bool
    cache_hit: bool
    estimated_remaining_seconds: float
    draining: bool = False
    quarantined: bool = False

    def __post_init__(self) -> None:
        if not self.worker_id.strip() or not self.pool_id.strip():
            raise ContractError("worker_id and pool_id are required")
        if not 0 <= self.semantic_health_score <= 1:
            raise ContractError("semantic_health_score must be between zero and one")
        if self.estimated_remaining_seconds < 0 or not math.isfinite(
            self.estimated_remaining_seconds
        ):
            raise ContractError("estimated_remaining_seconds must be finite and non-negative")

    def eligible_for(self, work: WorkUnit, *, semantic_threshold: float) -> bool:
        return (
            self.infrastructure_healthy
            and self.semantic_health_score >= semantic_threshold
            and not self.draining
            and not self.quarantined
            and work.required_capabilities.issubset(self.capabilities)
        )


@dataclass(frozen=True, slots=True)
class Assignment:
    work_id: str
    worker_id: str
    predicted_start_seconds: float
    predicted_finish_seconds: float


def fair_priority_order(work_units: Iterable[WorkUnit]) -> tuple[WorkUnit, ...]:
    """Priority order with round-robin tenant fairness inside each lane."""

    units = tuple(work_units)
    if len({unit.work_id for unit in units}) != len(units):
        raise ContractError("queue contains duplicate work IDs")
    result: list[WorkUnit] = []
    for priority in QueuePriority:
        lane = [unit for unit in units if unit.priority is priority]
        by_tenant: dict[str, deque[WorkUnit]] = defaultdict(deque)
        for unit in sorted(lane, key=lambda item: (item.enqueued_at, item.work_id)):
            by_tenant[unit.tenant_id].append(unit)
        tenant_order = sorted(
            by_tenant,
            key=lambda tenant: (by_tenant[tenant][0].enqueued_at, tenant),
        )
        while tenant_order:
            next_round: list[str] = []
            for tenant in tenant_order:
                result.append(by_tenant[tenant].popleft())
                if by_tenant[tenant]:
                    next_round.append(tenant)
            tenant_order = next_round
    return tuple(result)


def select_worker(
    work: WorkUnit,
    workers: Sequence[WorkerObservation],
    *,
    now: datetime,
    semantic_threshold: float = 0.9,
    minimum_url_margin_seconds: int = 60,
) -> WorkerObservation:
    if now.tzinfo is None:
        raise ContractError("scheduler time must be timezone-aware")
    if (work.input_url_expires_at - now).total_seconds() <= minimum_url_margin_seconds:
        raise ContractError("input URL lifetime is insufficient for dispatch")
    eligible = [
        worker
        for worker in workers
        if worker.eligible_for(work, semantic_threshold=semantic_threshold)
    ]
    if not eligible:
        raise ContractError("no compatible healthy semantic-safe worker is available")
    return min(
        eligible,
        key=lambda worker: (
            not worker.warm,
            not worker.cache_hit,
            worker.estimated_remaining_seconds + work.predicted_seconds,
            worker.worker_id,
        ),
    )


def size_aware_assignments(
    work_units: Iterable[WorkUnit],
    workers: Sequence[WorkerObservation],
    *,
    now: datetime,
    semantic_threshold: float = 0.9,
) -> tuple[Assignment, ...]:
    """Deterministic list scheduling that avoids concentrating large shards."""

    if not workers:
        raise ContractError("at least one worker observation is required")
    scheduling_order = fair_priority_order(work_units)
    observations = {worker.worker_id: worker for worker in workers}
    assignments: list[Assignment] = []
    for unit in scheduling_order:
        selected = select_worker(
            unit,
            tuple(observations.values()),
            now=now,
            semantic_threshold=semantic_threshold,
        )
        start = selected.estimated_remaining_seconds
        finish = start + unit.predicted_seconds
        assignments.append(
            Assignment(
                work_id=unit.work_id,
                worker_id=selected.worker_id,
                predicted_start_seconds=start,
                predicted_finish_seconds=finish,
            )
        )
        observations[selected.worker_id] = replace(
            selected,
            estimated_remaining_seconds=finish,
        )
    return tuple(assignments)


@dataclass(frozen=True, slots=True)
class BackpressureSnapshot:
    queue_depth: int
    queue_high_watermark: int
    minimum_url_remaining_seconds: float
    required_url_margin_seconds: float
    object_cache_utilization: float
    evaluator_utilization: float
    database_utilization: float
    spend_state: SpendState

    def __post_init__(self) -> None:
        if self.queue_depth < 0 or self.queue_high_watermark < 1:
            raise ContractError("queue depths are invalid")
        for name, value in (
            ("object_cache_utilization", self.object_cache_utilization),
            ("evaluator_utilization", self.evaluator_utilization),
            ("database_utilization", self.database_utilization),
        ):
            if not 0 <= value <= 1:
                raise ContractError(f"{name} must be between zero and one")

    def admission(self) -> dict[str, object]:
        reasons: list[str] = []
        if self.queue_depth >= self.queue_high_watermark:
            reasons.append("QUEUE_HIGH_WATERMARK")
        if self.minimum_url_remaining_seconds <= self.required_url_margin_seconds:
            reasons.append("PRESIGNED_URL_EXPIRY_RISK")
        if self.object_cache_utilization >= 0.95:
            reasons.append("OBJECT_CACHE_SATURATED")
        if self.evaluator_utilization >= 0.95:
            reasons.append("EVALUATOR_CAPACITY_SATURATED")
        if self.database_utilization >= 0.90:
            reasons.append("DATABASE_CAPACITY_SATURATED")
        if self.spend_state is SpendState.HARD_STOP_RUNAWAY:
            reasons.append("RUNAWAY_HARD_STOP")
        result: dict[str, object] = {
            "admitted": not reasons,
            "reasons": reasons,
            "cost_soft_alert_blocks_admission": False,
        }
        result["snapshot_sha256"] = canonical_sha256(
            {
                "queue_depth": self.queue_depth,
                "queue_high_watermark": self.queue_high_watermark,
                "minimum_url_remaining_seconds": self.minimum_url_remaining_seconds,
                "required_url_margin_seconds": self.required_url_margin_seconds,
                "object_cache_utilization": self.object_cache_utilization,
                "evaluator_utilization": self.evaluator_utilization,
                "database_utilization": self.database_utilization,
                "spend_state": self.spend_state.value,
                "reasons": reasons,
            }
        )
        return result


def dynamic_worker_target(
    *,
    total_remaining_predicted_seconds: float,
    desired_completion_window_seconds: float,
    min_workers: int,
    provider_quota: int,
    account_capacity: int,
    queue_capacity: int,
    evaluator_capacity: int,
    database_capacity: int,
    spend_state: SpendState,
) -> int:
    if total_remaining_predicted_seconds < 0:
        raise ContractError("remaining predicted seconds cannot be negative")
    if desired_completion_window_seconds <= 0:
        raise ContractError("desired completion window must be positive")
    caps = (
        provider_quota,
        account_capacity,
        queue_capacity,
        evaluator_capacity,
        database_capacity,
    )
    if min_workers < 0 or any(capacity < 0 for capacity in caps):
        raise ContractError("worker capacities cannot be negative")
    maximum = min(caps)
    if min_workers > maximum:
        raise ContractError("min_workers exceeds an operational capacity")
    if spend_state is SpendState.HARD_STOP_RUNAWAY:
        return 0
    if total_remaining_predicted_seconds == 0:
        return min_workers
    unconstrained = math.ceil(total_remaining_predicted_seconds / desired_completion_window_seconds)
    return min(max(unconstrained, min_workers), maximum)


def should_scale_down(
    *,
    queue_depth: int,
    in_flight_jobs: int,
    artifacts_uploaded: bool,
    grace_window_elapsed: bool,
) -> bool:
    if queue_depth < 0 or in_flight_jobs < 0:
        raise ContractError("queue and in-flight counts cannot be negative")
    return queue_depth == 0 and in_flight_jobs == 0 and artifacts_uploaded and grace_window_elapsed
