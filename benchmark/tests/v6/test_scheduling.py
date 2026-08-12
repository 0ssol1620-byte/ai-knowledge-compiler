from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6.orchestration import SpendState
from infra.runpod.v6.scheduling import (
    BackpressureSnapshot,
    QueuePriority,
    WorkerObservation,
    WorkUnit,
    dynamic_worker_target,
    fair_priority_order,
    select_worker,
    should_scale_down,
    size_aware_assignments,
)


def _work(
    work_id: str,
    *,
    tenant: str = "tenant-a",
    priority: QueuePriority = QueuePriority.BENCHMARK_SHARD,
    seconds: float = 10,
    enqueued_offset: int = 0,
) -> WorkUnit:
    now = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    return WorkUnit(
        work_id=work_id,
        tenant_id=tenant,
        priority=priority,
        predicted_seconds=seconds,
        required_capabilities=frozenset({"parser:mineru", "gpu:A100"}),
        enqueued_at=now + timedelta(seconds=enqueued_offset),
        input_url_expires_at=now + timedelta(hours=1),
    )


def _worker(
    worker_id: str,
    *,
    remaining: float = 0,
    warm: bool = True,
    cache_hit: bool = True,
    semantic: float = 1,
    healthy: bool = True,
    quarantined: bool = False,
) -> WorkerObservation:
    return WorkerObservation(
        worker_id=worker_id,
        pool_id="parser-mineru-3-4-4",
        capabilities=frozenset({"parser:mineru", "gpu:A100"}),
        infrastructure_healthy=healthy,
        semantic_health_score=semantic,
        warm=warm,
        cache_hit=cache_hit,
        estimated_remaining_seconds=remaining,
        quarantined=quarantined,
    )


def test_queue_priority_and_round_robin_tenant_fairness() -> None:
    ordered = fair_priority_order(
        [
            _work("bulk", priority=QueuePriority.BULK_BACKGROUND),
            _work("a-1", tenant="a", priority=QueuePriority.TINY_QUICK),
            _work("a-2", tenant="a", priority=QueuePriority.TINY_QUICK, enqueued_offset=1),
            _work("b-1", tenant="b", priority=QueuePriority.TINY_QUICK),
            _work("interactive", priority=QueuePriority.INTERACTIVE),
        ]
    )
    assert [unit.work_id for unit in ordered] == [
        "a-1",
        "b-1",
        "a-2",
        "interactive",
        "bulk",
    ]


def test_worker_selection_filters_infrastructure_and_semantic_health() -> None:
    now = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    selected = select_worker(
        _work("page-1"),
        [
            _worker("bad-infra", remaining=0, healthy=False),
            _worker("bad-semantic", remaining=0, semantic=0.5),
            _worker("quarantined", remaining=0, quarantined=True),
            _worker("cold", remaining=0, warm=False, cache_hit=False),
            _worker("warm-cache", remaining=20),
        ],
        now=now,
    )
    assert selected.worker_id == "warm-cache"

    expiring = replace(
        _work("expiring"),
        input_url_expires_at=now + timedelta(seconds=30),
    )
    with pytest.raises(ContractError, match="URL lifetime"):
        select_worker(expiring, [_worker("worker")], now=now)


def test_size_aware_assignment_balances_large_shards_deterministically() -> None:
    now = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    units = [
        _work("large-a", seconds=100),
        _work("large-b", seconds=90),
        _work("small", seconds=10),
    ]
    workers = [_worker("worker-a"), _worker("worker-b")]
    first = size_aware_assignments(units, workers, now=now)
    second = size_aware_assignments(reversed(units), tuple(reversed(workers)), now=now)

    assert first == second
    assignment = {item.work_id: item.worker_id for item in first}
    assert assignment["large-a"] != assignment["large-b"]


def test_backpressure_and_dynamic_target_ignore_soft_cost_alert_but_honor_runaway() -> None:
    soft = BackpressureSnapshot(
        queue_depth=10,
        queue_high_watermark=100,
        minimum_url_remaining_seconds=600,
        required_url_margin_seconds=60,
        object_cache_utilization=0.5,
        evaluator_utilization=0.5,
        database_utilization=0.5,
        spend_state=SpendState.SOFT_ALERT,
    ).admission()
    assert soft["admitted"] is True
    assert soft["cost_soft_alert_blocks_admission"] is False

    hard_target = dynamic_worker_target(
        total_remaining_predicted_seconds=1000,
        desired_completion_window_seconds=100,
        min_workers=0,
        provider_quota=20,
        account_capacity=20,
        queue_capacity=20,
        evaluator_capacity=10,
        database_capacity=8,
        spend_state=SpendState.HARD_STOP_RUNAWAY,
    )
    assert hard_target == 0
    assert (
        dynamic_worker_target(
            total_remaining_predicted_seconds=1000,
            desired_completion_window_seconds=100,
            min_workers=1,
            provider_quota=20,
            account_capacity=20,
            queue_capacity=20,
            evaluator_capacity=10,
            database_capacity=8,
            spend_state=SpendState.SOFT_ALERT,
        )
        == 8
    )


def test_scale_down_requires_every_cleanup_precondition() -> None:
    assert should_scale_down(
        queue_depth=0,
        in_flight_jobs=0,
        artifacts_uploaded=True,
        grace_window_elapsed=True,
    )
    assert not should_scale_down(
        queue_depth=0,
        in_flight_jobs=1,
        artifacts_uploaded=True,
        grace_window_elapsed=True,
    )
