"""Retry table, scheduler, circuit breaker, idle killer, budget caps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from arena.constants import BUDGET_HARD_CAP_USD, BUDGET_SOFT_CAP_USD, ERROR_CLASSES
from arena.controller import retry as retry_policy
from arena.controller.queue import ShardRecord, WorkerRecord
from arena.controller.scheduler import (
    SchedulerError,
    assign_shards,
    effective_concurrency,
    plan_replicas,
)
from arena.controller.watchdogs import (
    MAX_POD_LIFETIME_SECONDS,
    BudgetWatchdog,
    CircuitBreaker,
    WorkerObservation,
    heartbeat_findings,
    idle_grace_seconds,
    idle_killer,
    lifetime_expiry,
    stall_threshold_seconds,
    straggler_check,
)

NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)


def _stamp(offset_seconds: float) -> str:
    return (NOW - timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ retry


def test_deterministic_runtime_errors_are_never_retried() -> None:
    for error_class in ("DEPENDENCY", "MODEL_LOAD", "TENSOR_SHAPE", "EVALUATOR"):
        decision = retry_policy.decide(error_class, retry_count=0)
        assert decision.retry is False
        assert decision.rule.max_retries == 0
        assert decision.rule.mp_row  # every rule names its masterplan row


def test_worker_lost_requeues_the_same_job_id() -> None:
    decision = retry_policy.decide(retry_policy.WORKER_LOST, retry_count=0)
    assert decision.retry is True
    assert decision.rule.action == retry_policy.RetryAction.REQUEUE_SAME_ID


def test_oom_retries_once_after_reducing_concurrency() -> None:
    first = retry_policy.decide("CUDA_OOM", retry_count=0)
    assert first.retry is True
    assert first.rule.max_retries == 1
    assert "concurrency" in first.rule.action.casefold()
    second = retry_policy.decide("CUDA_OOM", retry_count=1)
    assert second.retry is False


def test_rate_limit_respects_retry_after() -> None:
    decision = retry_policy.decide("RATE_LIMIT", retry_count=0, retry_after_seconds=120.0)
    assert decision.delay_seconds == pytest.approx(120.0)


def test_network_backoff_grows() -> None:
    delays = [
        retry_policy.decide("INFRA_NETWORK", retry_count=n).delay_seconds for n in range(3)
    ]
    assert delays == sorted(delays)
    assert delays[0] < delays[-1]


def test_every_taxonomy_class_has_a_rule_and_unlisted_ones_fail_closed() -> None:
    for error_class in ERROR_CLASSES:
        rule = retry_policy.rule_for(error_class)
        assert rule.error_class == error_class
        if rule.mp_row == "no masterplan 15.9 row; fail closed":
            assert rule.max_retries == 0


def test_an_invented_error_class_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside the taxonomy"):
        retry_policy.rule_for("MADE_UP_CLASS")


# -------------------------------------------------------------- scheduler


def test_mineru_vlm_is_pinned_to_concurrency_one() -> None:
    assert effective_concurrency("mineru_vlm", {"per_worker": 1}) == 1
    assert effective_concurrency("mineru_vlm", None) == 1
    with pytest.raises(SchedulerError, match="section 14"):
        effective_concurrency("mineru_vlm", {"per_worker": 8})


def test_other_models_take_the_registry_concurrency() -> None:
    assert effective_concurrency("paddleocr_vl_1_6", {"per_worker": 4}) == 4


def test_slowest_shard_is_dispatched_first() -> None:
    shards = [
        ShardRecord("m-omnidoc-0000", "m", "omnidoc", 0, 10, 100.0),
        ShardRecord("m-omnidoc-0001", "m", "omnidoc", 1, 10, 900.0),
        ShardRecord("m-omnidoc-0002", "m", "omnidoc", 2, 10, 400.0),
    ]
    workers = [WorkerRecord("m-w0-p0", "m", "p0", 0, 1, state="READY")]
    assignments = assign_shards(shards, workers, concurrency={"m": 1})
    assert [item.shard_id for item in assignments] == [
        "m-omnidoc-0001",
        "m-omnidoc-0002",
        "m-omnidoc-0000",
    ]


def test_assignment_picks_the_earliest_predicted_finish() -> None:
    shards = [
        ShardRecord("m-omnidoc-0000", "m", "omnidoc", 0, 10, 100.0),
        ShardRecord("m-omnidoc-0001", "m", "omnidoc", 1, 10, 100.0),
    ]
    workers = [
        WorkerRecord("m-w0-p0", "m", "p0", 0, 1, state="READY"),
        WorkerRecord("m-w1-p1", "m", "p1", 1, 1, state="READY"),
    ]
    assignments = assign_shards(
        shards, workers, concurrency={"m": 1}, worker_available_at={"m-w0-p0": 500.0}
    )
    # The free worker takes the first shard; the busy one waits its turn.
    assert assignments[0].worker_id == "m-w1-p1"
    assert assignments[1].worker_id == "m-w1-p1"


def test_stalled_workers_never_receive_a_shard() -> None:
    shards = [ShardRecord("m-omnidoc-0000", "m", "omnidoc", 0, 10, 100.0)]
    workers = [WorkerRecord("m-w0-p0", "m", "p0", 0, 1, state="STALLED")]
    assert assign_shards(shards, workers, concurrency={"m": 1}) == ()


def test_replica_plan_is_capped_by_registry_and_budget() -> None:
    demand = plan_replicas(
        "m",
        pending_seconds=36_000.0,
        current_replicas=1,
        registry_max_replicas=8,
        target_wall_seconds=3600.0,
        budget_allows_new_replicas=True,
    )
    assert demand.desired_replicas == 8
    assert demand.capped_by == "registry_max"

    frozen = plan_replicas(
        "m",
        pending_seconds=36_000.0,
        current_replicas=2,
        registry_max_replicas=8,
        target_wall_seconds=3600.0,
        budget_allows_new_replicas=False,
    )
    assert frozen.desired_replicas == 2
    assert frozen.capped_by == "budget_soft_cap"
    assert frozen.scale_up == 0


# ---------------------------------------------------------- stall / straggler


def test_stall_threshold_is_three_times_p95_or_the_model_minimum() -> None:
    assert stall_threshold_seconds(40.0, 60.0) == pytest.approx(120.0)
    assert stall_threshold_seconds(10.0, 300.0) == pytest.approx(300.0)
    assert stall_threshold_seconds(None, 300.0) == pytest.approx(300.0)
    with pytest.raises(ValueError):
        stall_threshold_seconds(10.0, 0.0)


def test_heartbeat_silence_beyond_three_intervals_is_a_stall() -> None:
    workers = [
        WorkerObservation("w-fresh", "m", "READY", _stamp(10)),
        WorkerObservation("w-silent", "m", "BUSY", _stamp(200)),
        WorkerObservation("w-never", "m", "READY", None),
    ]
    findings = heartbeat_findings(workers, now=NOW)
    kinds = {finding.entity_id: finding.kind for finding in findings}
    assert kinds == {"w-silent": "heartbeat_stall", "w-never": "heartbeat_missing"}


def test_a_job_past_the_dynamic_threshold_is_a_stall() -> None:
    workers = [
        WorkerObservation(
            "w0", "mineru_vlm", "BUSY", _stamp(5), current_job_id="job1", job_elapsed_seconds=400.0
        )
    ]
    findings = heartbeat_findings(workers, now=NOW, stall_thresholds={"mineru_vlm": 300.0})
    assert [finding.kind for finding in findings] == ["job_stall"]
    assert findings[0].action == "fail_job_inference_stall"


def test_straggler_is_diagnosed_at_one_and_a_half_times_p95_with_hedging_off() -> None:
    assert (
        straggler_check(
            shard_id="s",
            elapsed_seconds=100.0,
            p95_expected_seconds=100.0,
            progressing=True,
            source_corrupt=False,
            healthy_spare_worker=True,
        )
        is None
    )
    finding = straggler_check(
        shard_id="s",
        elapsed_seconds=200.0,
        p95_expected_seconds=100.0,
        progressing=False,
        source_corrupt=False,
        healthy_spare_worker=True,
    )
    assert finding is not None
    assert finding.threshold_seconds == pytest.approx(150.0)
    assert finding.hedge_allowed is False
    assert "hedging is off by default" in finding.reason


def test_hedging_needs_every_precondition() -> None:
    allowed = straggler_check(
        shard_id="s",
        elapsed_seconds=200.0,
        p95_expected_seconds=100.0,
        progressing=False,
        source_corrupt=False,
        healthy_spare_worker=True,
        hedging_enabled=True,
    )
    assert allowed is not None and allowed.hedge_allowed is True
    blocked = straggler_check(
        shard_id="s",
        elapsed_seconds=200.0,
        p95_expected_seconds=100.0,
        progressing=False,
        source_corrupt=True,
        healthy_spare_worker=True,
        hedging_enabled=True,
    )
    assert blocked is not None and blocked.hedge_allowed is False


# ---------------------------------------------------------- circuit breaker


def test_three_identical_signatures_in_a_row_trip_the_breaker() -> None:
    breaker = CircuitBreaker("mineru_vlm")
    assert breaker.record(failed=True, error_signature="TENSOR_SHAPE:mismatch 3x1") is None
    assert breaker.record(failed=True, error_signature="TENSOR_SHAPE:mismatch 3x1") is None
    trip = breaker.record(failed=True, error_signature="TENSOR_SHAPE:mismatch 3x1")
    assert trip is not None
    assert trip.rule == "identical_signature_streak"
    assert breaker.tripped is trip


def test_a_success_breaks_the_identical_signature_streak() -> None:
    breaker = CircuitBreaker("m")
    breaker.record(failed=True, error_signature="X")
    breaker.record(failed=True, error_signature="X")
    breaker.record(failed=False)
    assert breaker.record(failed=True, error_signature="X") is None
    assert breaker.tripped is None


def test_different_signatures_do_not_trip_the_streak_rule() -> None:
    breaker = CircuitBreaker("m")
    for index in range(3):
        breaker.record(failed=True, error_signature=f"X{index}")
    assert breaker.tripped is None


def test_more_than_ten_percent_of_the_first_twenty_trips_the_breaker() -> None:
    breaker = CircuitBreaker("m")
    for index in range(20):
        breaker.record(failed=index < 3, error_signature=f"sig{index}")
    trip = breaker.tripped
    assert trip is not None
    assert trip.rule == "first_window_failure_rate"


def test_gpu_idle_while_busy_trips_the_breaker() -> None:
    breaker = CircuitBreaker("m")
    trip = breaker.observe_idle_gpu_while_busy("w0", 0.2, 600.0)
    assert trip is not None
    assert trip.rule == "gpu_idle_while_busy"


def test_version_mismatch_trips_the_breaker() -> None:
    breaker = CircuitBreaker("m")
    trip = breaker.observe_version_mismatch("rev-a", "rev-b")
    assert trip is not None and trip.rule == "version_mismatch"


# --------------------------------------------------------------- idle killer


def test_idle_killer_needs_all_three_conditions() -> None:
    idle = WorkerObservation("w0", "m", "READY", _stamp(5), idle_seconds=900.0)
    grace = idle_grace_seconds("m", None)
    assert idle_killer(idle, queue_empty=True, reserved_shards=0, grace_seconds=grace).shutdown
    assert not idle_killer(
        idle, queue_empty=False, reserved_shards=0, grace_seconds=grace
    ).shutdown
    assert not idle_killer(
        idle, queue_empty=True, reserved_shards=1, grace_seconds=grace
    ).shutdown
    fresh = WorkerObservation("w0", "m", "READY", _stamp(5), idle_seconds=10.0)
    assert not idle_killer(fresh, queue_empty=True, reserved_shards=0, grace_seconds=grace).shutdown


def test_idle_killer_never_touches_a_busy_worker() -> None:
    busy = WorkerObservation("w0", "m", "BUSY", _stamp(5), idle_seconds=10_000.0)
    decision = idle_killer(busy, queue_empty=True, reserved_shards=0, grace_seconds=60.0)
    assert decision.shutdown is False
    assert "running a page" in decision.reason


def test_idle_grace_uses_the_registry_value_when_given() -> None:
    assert idle_grace_seconds("infinity_parser2_pro", 1800.0) == pytest.approx(1800.0)
    assert idle_grace_seconds("m", None, large_model=True) == pytest.approx(600.0)


def test_pod_lifetime_expiry() -> None:
    old = WorkerObservation(
        "w0", "m", "READY", _stamp(5), pod_provisioned_at=_stamp(MAX_POD_LIFETIME_SECONDS + 60)
    )
    finding = lifetime_expiry(old, now=NOW)
    assert finding is not None
    assert finding.action == "drain_then_terminate"
    young = WorkerObservation("w1", "m", "READY", _stamp(5), pod_provisioned_at=_stamp(60))
    assert lifetime_expiry(young, now=NOW) is None


# ------------------------------------------------------------------ budget


def test_budget_normal_below_the_soft_cap() -> None:
    watchdog = BudgetWatchdog()
    assessment = watchdog.evaluate(
        spent_usd=10.0, running_worker_rates_usd_per_hour=[0.34], seconds_to_next_checkpoint=60.0
    )
    assert assessment.state == "NORMAL"
    assert assessment.allow_new_replicas is True


def test_soft_cap_stops_new_replicas_but_not_the_work() -> None:
    watchdog = BudgetWatchdog()
    assessment = watchdog.evaluate(
        spent_usd=BUDGET_SOFT_CAP_USD - 0.5,
        running_worker_rates_usd_per_hour=[2.0, 2.0],
        seconds_to_next_checkpoint=3600.0,
    )
    assert assessment.state == "SOFT_CAP"
    assert assessment.allow_new_replicas is False
    assert assessment.pause_queue is False
    assert assessment.drain_workers is False


def test_hard_cap_pauses_and_drains() -> None:
    watchdog = BudgetWatchdog()
    assessment = watchdog.evaluate(
        spent_usd=BUDGET_HARD_CAP_USD - 1.0,
        running_worker_rates_usd_per_hour=[2.0],
        seconds_to_next_checkpoint=3600.0,
    )
    assert assessment.state == "HARD_CAP"
    assert assessment.pause_queue is True
    assert assessment.drain_workers is True
    assert "without killing a page" in assessment.reason


def test_budget_projection_includes_committed_worker_time() -> None:
    watchdog = BudgetWatchdog()
    assessment = watchdog.evaluate(
        spent_usd=100.0,
        running_worker_rates_usd_per_hour=[1.0, 2.0],
        seconds_to_next_checkpoint=1800.0,
    )
    assert assessment.committed_usd == pytest.approx(1.5)
    assert assessment.projected_usd == pytest.approx(101.5)


def test_budget_caps_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="soft cap cannot exceed"):
        BudgetWatchdog(soft_cap_usd=500.0, hard_cap_usd=100.0)


def test_quarantining_rules_are_recognised_whichever_table_is_adopted() -> None:
    """The controller must not depend on owning the action string.

    Lane A1's table states the action in prose. A controller that compared it
    against its own constants would silently stop quarantining, so the test
    asserts the structural property instead.
    """

    for error_class in ("TENSOR_SHAPE", "CHECKSUM"):
        assert retry_policy.rule_for(error_class).quarantines is True
    assert retry_policy.rule_for("INFRA_NETWORK").quarantines is False
