from __future__ import annotations

from decimal import Decimal
from typing import Any

from akc_api.telemetry import after_commit_metric
from akc_telemetry import (
    PARALLEL_ACCEPTED_BLOCKS,
    PARALLEL_ATTEMPTS_TERMINAL,
    PARALLEL_CONTINUITY_OUTCOMES,
    PARALLEL_DUPLICATE_CREDIT_SUPPRESSIONS,
    PARALLEL_NONBILLABLE_ATTEMPTS,
    PARALLEL_PROVIDER_COST,
    PARALLEL_PROVIDER_EXECUTION_DURATION,
    PARALLEL_PROVIDER_GPU_SECONDS,
    PARALLEL_PROVIDER_JOB_COST,
    PARALLEL_PROVIDER_OBSERVATIONS,
    PARALLEL_PROVIDER_QUEUE_DELAY,
    PARALLEL_RECOVERY_TERMINAL,
    PARALLEL_SHARDS_TERMINAL,
    PARALLEL_VALIDATIONS,
    PARALLEL_WORKER_HEALTH_TRANSITIONS,
    observe_parallel_provider_job,
    record_parallel_acceptance,
    record_parallel_attempt_terminal,
    record_parallel_continuity_outcome,
    record_parallel_duplicate_credit_suppression,
    record_parallel_nonbillable_attempt,
    record_parallel_recovery_terminal,
    record_parallel_shard_terminal,
    record_parallel_validation,
    record_parallel_worker_dual_health_transition,
    render_prometheus,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _sample_value(metric: Any, sample_name: str, labels: dict[str, str]) -> float:
    for family in metric.collect():
        for sample in family.samples:
            if sample.name == sample_name and sample.labels == labels:
                return float(sample.value)
    raise AssertionError(f"missing sample {sample_name} {labels}")


def test_parallel_metric_contract_exposes_every_required_signal() -> None:
    payload = render_prometheus().decode("utf-8")
    for series in (
        "akc_parallel_shards_terminal_total",
        "akc_parallel_attempts_terminal_total",
        "akc_parallel_validations_total",
        "akc_parallel_worker_health_transitions_total",
        "akc_parallel_recovery_terminal_total",
        "akc_parallel_continuity_outcomes_total",
        "akc_parallel_accepted_blocks_total",
        "akc_parallel_nonbillable_attempts_total",
        "akc_parallel_duplicate_credit_suppressions_total",
        "akc_parallel_provider_observations_total",
        "akc_parallel_provider_queue_delay_seconds",
        "akc_parallel_provider_execution_duration_seconds",
        "akc_parallel_provider_job_cost_usd",
        "akc_parallel_provider_cost_usd_total",
        "akc_parallel_provider_gpu_seconds_total",
    ):
        assert series in payload


def test_parallel_helpers_fail_closed_to_fixed_cardinality_labels() -> None:
    customer_identifier = "tenant-owner@example.com"
    record_parallel_shard_terminal(customer_identifier)
    record_parallel_attempt_terminal(customer_identifier)
    record_parallel_validation(level=customer_identifier, outcome=customer_identifier)
    record_parallel_worker_dual_health_transition(
        previous_infrastructure=customer_identifier,
        current_infrastructure="healthy",
        previous_semantic=customer_identifier,
        current_semantic="healthy",
    )
    record_parallel_recovery_terminal(
        level=customer_identifier,
        outcome=customer_identifier,
    )
    record_parallel_continuity_outcome(customer_identifier)
    record_parallel_acceptance(final_state=customer_identifier, billable=False)
    record_parallel_nonbillable_attempt(customer_identifier)
    record_parallel_duplicate_credit_suppression(customer_identifier)
    observe_parallel_provider_job(
        provider=customer_identifier,
        queue_delay_seconds="0.25",
        execution_seconds="1.5",
        cost_usd="0.001",
        gpu_seconds="1.25",
    )

    payload = render_prometheus().decode("utf-8")
    assert customer_identifier not in payload
    for label_fragment in (
        'status="other"',
        'level="other"',
        'outcome="other"',
        'provider="other"',
        'final_state="other"',
        'disposition="other"',
        'reason="other"',
    ):
        assert label_fragment in payload


def test_parallel_lifecycle_counters_and_unchanged_health_are_exact() -> None:
    cases = (
        (
            PARALLEL_SHARDS_TERMINAL,
            "akc_parallel_shards_terminal_total",
            {"status": "accepted"},
            lambda: record_parallel_shard_terminal("ACCEPTED"),
        ),
        (
            PARALLEL_ATTEMPTS_TERMINAL,
            "akc_parallel_attempts_terminal_total",
            {"status": "terminal_failed"},
            lambda: record_parallel_attempt_terminal("TERMINAL_FAILED"),
        ),
        (
            PARALLEL_VALIDATIONS,
            "akc_parallel_validations_total",
            {"level": "L6", "outcome": "passed"},
            lambda: record_parallel_validation(level=6, outcome="passed"),
        ),
        (
            PARALLEL_RECOVERY_TERMINAL,
            "akc_parallel_recovery_terminal_total",
            {"level": "row", "outcome": "completed"},
            lambda: record_parallel_recovery_terminal(level="row", outcome="COMPLETED"),
        ),
        (
            PARALLEL_CONTINUITY_OUTCOMES,
            "akc_parallel_continuity_outcomes_total",
            {"outcome": "unresolved"},
            lambda: record_parallel_continuity_outcome("UNRESOLVED"),
        ),
        (
            PARALLEL_ACCEPTED_BLOCKS,
            "akc_parallel_accepted_blocks_total",
            {"final_state": "authority_verified", "billing": "billable"},
            lambda: record_parallel_acceptance(
                final_state="authority_verified",
                billable=True,
            ),
        ),
        (
            PARALLEL_NONBILLABLE_ATTEMPTS,
            "akc_parallel_nonbillable_attempts_total",
            {"disposition": "speculative_unbillable"},
            lambda: record_parallel_nonbillable_attempt("speculative_unbillable"),
        ),
        (
            PARALLEL_DUPLICATE_CREDIT_SUPPRESSIONS,
            "akc_parallel_duplicate_credit_suppressions_total",
            {"reason": "duplicate_compute"},
            lambda: record_parallel_duplicate_credit_suppression("duplicate_compute"),
        ),
    )
    for metric, sample_name, labels, callback in cases:
        before = _sample_value(metric, sample_name, labels)
        callback()
        assert _sample_value(metric, sample_name, labels) == before + 1

    health_labels = {
        "projection": "semantic",
        "previous": "healthy",
        "current": "failing",
    }
    health_before = _sample_value(
        PARALLEL_WORKER_HEALTH_TRANSITIONS,
        "akc_parallel_worker_health_transitions_total",
        health_labels,
    )
    record_parallel_worker_dual_health_transition(
        previous_infrastructure="healthy",
        current_infrastructure="healthy",
        previous_semantic="healthy",
        current_semantic="failing",
    )
    assert (
        _sample_value(
            PARALLEL_WORKER_HEALTH_TRANSITIONS,
            "akc_parallel_worker_health_transitions_total",
            health_labels,
        )
        == health_before + 1
    )


def test_parallel_provider_receipts_record_valid_values_and_ignore_invalid_values() -> None:
    provider = {"provider": "runpod"}
    queue_count_name = "akc_parallel_provider_queue_delay_seconds_count"
    execution_count_name = "akc_parallel_provider_execution_duration_seconds_count"
    cost_count_name = "akc_parallel_provider_job_cost_usd_count"
    queue_before = _sample_value(PARALLEL_PROVIDER_QUEUE_DELAY, queue_count_name, provider)
    execution_before = _sample_value(
        PARALLEL_PROVIDER_EXECUTION_DURATION,
        execution_count_name,
        provider,
    )
    cost_count_before = _sample_value(PARALLEL_PROVIDER_JOB_COST, cost_count_name, provider)
    cost_before = _sample_value(
        PARALLEL_PROVIDER_COST,
        "akc_parallel_provider_cost_usd_total",
        provider,
    )
    gpu_before = _sample_value(
        PARALLEL_PROVIDER_GPU_SECONDS,
        "akc_parallel_provider_gpu_seconds_total",
        provider,
    )
    observations_before = {
        measurement: _sample_value(
            PARALLEL_PROVIDER_OBSERVATIONS,
            "akc_parallel_provider_observations_total",
            {"provider": "runpod", "measurement": measurement},
        )
        for measurement in (
            "queue_delay",
            "execution_duration",
            "job_cost",
            "gpu_seconds",
        )
    }

    observe_parallel_provider_job(
        provider="runpod",
        queue_delay_seconds=Decimal("0.5"),
        execution_seconds=Decimal("3.25"),
        cost_usd=Decimal("0.0125"),
        gpu_seconds=Decimal("3.0"),
    )
    assert (
        _sample_value(PARALLEL_PROVIDER_QUEUE_DELAY, queue_count_name, provider) == queue_before + 1
    )
    assert (
        _sample_value(
            PARALLEL_PROVIDER_EXECUTION_DURATION,
            execution_count_name,
            provider,
        )
        == execution_before + 1
    )
    assert (
        _sample_value(PARALLEL_PROVIDER_JOB_COST, cost_count_name, provider)
        == cost_count_before + 1
    )
    assert (
        _sample_value(
            PARALLEL_PROVIDER_COST,
            "akc_parallel_provider_cost_usd_total",
            provider,
        )
        == cost_before + 0.0125
    )
    assert (
        _sample_value(
            PARALLEL_PROVIDER_GPU_SECONDS,
            "akc_parallel_provider_gpu_seconds_total",
            provider,
        )
        == gpu_before + 3.0
    )
    for measurement, before in observations_before.items():
        assert (
            _sample_value(
                PARALLEL_PROVIDER_OBSERVATIONS,
                "akc_parallel_provider_observations_total",
                {"provider": "runpod", "measurement": measurement},
            )
            == before + 1
        )

    observe_parallel_provider_job(
        provider="runpod",
        queue_delay_seconds=-1,
        execution_seconds="nan",
        cost_usd="not-a-number",
        gpu_seconds="Infinity",
    )
    assert (
        _sample_value(PARALLEL_PROVIDER_QUEUE_DELAY, queue_count_name, provider) == queue_before + 1
    )
    assert (
        _sample_value(
            PARALLEL_PROVIDER_EXECUTION_DURATION,
            execution_count_name,
            provider,
        )
        == execution_before + 1
    )
    assert (
        _sample_value(PARALLEL_PROVIDER_JOB_COST, cost_count_name, provider)
        == cost_count_before + 1
    )


async def test_parallel_outcomes_are_scheduled_only_after_commit() -> None:
    labels = {"status": "failed"}
    sample_name = "akc_parallel_shards_terminal_total"
    before = _sample_value(PARALLEL_SHARDS_TERMINAL, sample_name, labels)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sessions() as session:
            await session.execute(text("SELECT 1"))
            after_commit_metric(session, record_parallel_shard_terminal, "FAILED")
            assert _sample_value(PARALLEL_SHARDS_TERMINAL, sample_name, labels) == before
            await session.rollback()
            await session.commit()
        assert _sample_value(PARALLEL_SHARDS_TERMINAL, sample_name, labels) == before

        async with sessions() as session:
            await session.execute(text("SELECT 1"))
            after_commit_metric(session, record_parallel_shard_terminal, "FAILED")
            await session.commit()
        assert _sample_value(PARALLEL_SHARDS_TERMINAL, sample_name, labels) == before + 1
    finally:
        await engine.dispose()
