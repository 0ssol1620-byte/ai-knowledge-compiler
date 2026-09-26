"""Shard scheduling — masterplan section 35, and section 14's hard rule.

Two behaviours are load bearing:

- **Slowest first.** Shards are dispatched in descending predicted seconds so
  the straggler tail lands early rather than at the end of the campaign.
- **MinerU VLM never runs at concurrency > 1.** The 2026-08 incident (48 of 54
  tensor-shape failures at concurrency 3) is the reason; throughput for that
  model scales by replicas only.

Assignment is earliest-predicted-finish over healthy workers. Everything here
is pure: given shards, workers and a clock it returns assignments, so the
policy is testable without a provider.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from arena.controller.queue import ShardRecord, WorkerRecord

__all__ = [
    "HARD_CONCURRENCY_ONE",
    "Assignment",
    "ReplicaPlan",
    "SchedulerError",
    "assign_shards",
    "effective_concurrency",
    "plan_replicas",
]

# Masterplan section 14: not a default, a rule.
HARD_CONCURRENCY_ONE: Final = frozenset({"mineru_vlm"})

HEALTHY_WORKER_STATES: Final = frozenset({"READY", "BUSY"})
ASSIGNABLE_SHARD_STATES: Final = frozenset({"PENDING"})


class SchedulerError(RuntimeError):
    """The scheduler refused to place work."""


@dataclass(frozen=True, slots=True)
class Assignment:
    shard_id: str
    worker_id: str
    predicted_start_seconds: float
    predicted_finish_seconds: float
    reason: str


@dataclass(frozen=True, slots=True)
class ReplicaPlan:
    model_key: str
    current_replicas: int
    desired_replicas: int
    capped_by: str
    detail: Mapping[str, object] = field(default_factory=dict)

    @property
    def scale_up(self) -> int:
        return max(0, self.desired_replicas - self.current_replicas)


def effective_concurrency(model_key: str, policy: Mapping[str, object] | None) -> int:
    """Per-worker concurrency from ``concurrency_policy``, with the VLM floor.

    A registry that asks for more than 1 on ``mineru_vlm`` is not silently
    honoured and not silently clamped either -- it is refused, because the
    registry disagreeing with masterplan section 14 is a fact someone needs to
    see rather than a number to round down.
    """

    requested = 1
    if policy is not None:
        raw = policy.get("per_worker")
        if isinstance(raw, int) and not isinstance(raw, bool):
            requested = raw
        elif raw is not None:
            raise SchedulerError(
                f"concurrency_policy.per_worker for {model_key} is not an integer"
            )
    if requested < 1:
        raise SchedulerError(f"concurrency_policy.per_worker for {model_key} must be at least 1")
    if model_key in HARD_CONCURRENCY_ONE and requested != 1:
        raise SchedulerError(
            f"{model_key} is fixed at concurrency 1 by masterplan section 14; "
            f"the registry asks for {requested}"
        )
    return requested


def assign_shards(
    shards: Sequence[ShardRecord],
    workers: Sequence[WorkerRecord],
    *,
    concurrency: Mapping[str, int],
    worker_available_at: Mapping[str, float] | None = None,
    now_seconds: float = 0.0,
) -> tuple[Assignment, ...]:
    """Place PENDING shards on healthy workers, slowest shard first."""

    available = dict(worker_available_at or {})
    healthy: dict[str, list[WorkerRecord]] = {}
    for worker in workers:
        if worker.state not in HEALTHY_WORKER_STATES:
            continue
        healthy.setdefault(worker.model_key, []).append(worker)
        available.setdefault(worker.worker_id, now_seconds)

    ordered = sorted(
        (shard for shard in shards if shard.state in ASSIGNABLE_SHARD_STATES),
        key=lambda shard: (-shard.predicted_seconds, shard.shard_id),
    )

    assignments: list[Assignment] = []
    for shard in ordered:
        candidates = healthy.get(shard.model_key, [])
        if not candidates:
            continue
        per_worker = max(1, concurrency.get(shard.model_key, 1))
        duration = shard.predicted_seconds / per_worker
        best = min(
            candidates,
            key=lambda worker: (available[worker.worker_id], worker.worker_id),
        )
        start = available[best.worker_id]
        finish = start + duration
        available[best.worker_id] = finish
        assignments.append(
            Assignment(
                shard_id=shard.shard_id,
                worker_id=best.worker_id,
                predicted_start_seconds=start,
                predicted_finish_seconds=finish,
                reason=(
                    f"earliest predicted finish {finish:.1f}s at concurrency {per_worker}"
                ),
            )
        )
    return tuple(assignments)


def plan_replicas(
    model_key: str,
    *,
    pending_seconds: float,
    current_replicas: int,
    registry_max_replicas: int,
    target_wall_seconds: float,
    budget_allows_new_replicas: bool,
    per_worker_concurrency: int = 1,
) -> ReplicaPlan:
    """How many workers this model should have right now.

    Capped by three separate things, and the plan says which one bound it:
    the registry maximum, the soft budget cap (masterplan section 15.13, where
    the rule is *no new replicas* rather than a shutdown), and the amount of
    work actually left.
    """

    if registry_max_replicas < 1:
        raise SchedulerError(f"registry max replicas for {model_key} must be at least 1")
    if target_wall_seconds <= 0:
        raise SchedulerError("target wall time must be positive")
    if pending_seconds <= 0:
        return ReplicaPlan(
            model_key=model_key,
            current_replicas=current_replicas,
            desired_replicas=0,
            capped_by="no_pending_work",
            detail={"pending_seconds": pending_seconds},
        )
    throughput = max(1, per_worker_concurrency)
    needed = pending_seconds / (target_wall_seconds * throughput)
    wanted = max(1, int(needed) + (1 if needed % 1 else 0))
    capped_by = "demand"
    desired = wanted
    if desired > registry_max_replicas:
        desired = registry_max_replicas
        capped_by = "registry_max"
    if not budget_allows_new_replicas and desired > current_replicas:
        desired = current_replicas
        capped_by = "budget_soft_cap"
    return ReplicaPlan(
        model_key=model_key,
        current_replicas=current_replicas,
        desired_replicas=desired,
        capped_by=capped_by,
        detail={
            "pending_seconds": pending_seconds,
            "target_wall_seconds": target_wall_seconds,
            "unclamped_desired": wanted,
            "registry_max_replicas": registry_max_replicas,
            "per_worker_concurrency": throughput,
        },
    )
