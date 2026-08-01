from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6.orchestration import (
    CleanupFacts,
    EndpointLifecycle,
    EndpointState,
    PoolRegistry,
    SpendGuard,
    SpendPolicy,
    SpendState,
    audit_orphan_endpoints,
)


def test_pool_registry_is_model_isolated_disabled_and_secret_name_only(
    repo_root: Path,
) -> None:
    registry = PoolRegistry.load(repo_root / "infra/runpod/v6/pool-registry.yaml")
    pools = registry.pools

    assert len(pools) == 16
    assert all(not pool.enabled for pool in pools)
    assert all(pool.provider_retry_count == 0 for pool in pools)
    assert len({candidate for pool in pools for candidate in pool.candidate_ids}) == sum(
        len(pool.candidate_ids) for pool in pools
    )
    assert all("=" not in secret for pool in pools for secret in pool.secret_names)


def test_spend_guard_is_idempotent_and_cost_is_only_a_soft_alert() -> None:
    guard = SpendGuard(
        run_id="run-1",
        policy=SpendPolicy(expected_cost_usd=Decimal("10")),
    )
    first = guard.dispatch(
        idempotency_key="run-1:page-1:primary",
        logical_work_id="page-1",
        provider_job_id="job-1",
        attempt_kind="primary",
    )
    replay = guard.dispatch(
        idempotency_key="run-1:page-1:primary",
        logical_work_id="page-1",
        provider_job_id="job-1",
        attempt_kind="primary",
    )
    assert replay is first

    assert guard.record_provider_cost(amount_usd="40", cause="planned") is SpendState.SOFT_ALERT
    assert guard.state is SpendState.SOFT_ALERT
    assert guard.report()["cost_used_as_mandatory_test_blocker"] is False


def test_spend_guard_hard_stops_duplicate_jobs_charges_and_anomalous_error_cost() -> None:
    duplicate = SpendGuard(
        run_id="run-duplicate",
        policy=SpendPolicy(expected_cost_usd=Decimal("10")),
    )
    duplicate.dispatch(
        idempotency_key="key",
        logical_work_id="page-1",
        provider_job_id="job-1",
        attempt_kind="primary",
    )
    with pytest.raises(ContractError, match="different provider job"):
        duplicate.dispatch(
            idempotency_key="key",
            logical_work_id="page-1",
            provider_job_id="job-2",
            attempt_kind="primary",
        )
    assert duplicate.state is SpendState.HARD_STOP_RUNAWAY

    anomaly = SpendGuard(
        run_id="run-anomaly",
        policy=SpendPolicy(expected_cost_usd=Decimal("10")),
    )
    anomaly.record_provider_cost(amount_usd="31", cause="error")
    assert anomaly.state is SpendState.HARD_STOP_RUNAWAY


def test_user_settlement_is_once_and_unresolved_is_zero_charge() -> None:
    guard = SpendGuard(
        run_id="run-billing",
        policy=SpendPolicy(expected_cost_usd=Decimal("10")),
    )
    guard.dispatch(
        idempotency_key="page-1-primary",
        logical_work_id="page-1",
        provider_job_id="job-1",
        attempt_kind="primary",
    )
    guard.accept_verified_result(logical_work_id="page-1", provider_job_id="job-1")
    guard.settle_user_charge(
        logical_work_id="page-1",
        amount_usd="0.20",
        final_integrity_state="verified",
    )
    guard.settle_user_charge(
        logical_work_id="page-2",
        amount_usd="0",
        final_integrity_state="unresolved",
    )
    assert guard.user_charge_usd == Decimal("0.20")
    with pytest.raises(ContractError, match="at most once"):
        guard.settle_user_charge(
            logical_work_id="page-1",
            amount_usd="0.20",
            final_integrity_state="verified",
        )


def test_endpoint_cleanup_requires_empty_work_evidence_grace_and_provider_absence() -> None:
    start = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    endpoint = EndpointLifecycle(
        endpoint_id="ep-1",
        run_id="run-1",
        pool_id="parser-mineru-3-4-4",
        created_at=start,
    )
    empty = CleanupFacts()
    endpoint.transition(EndpointState.PROVISIONING, facts=empty, occurred_at=start, reason="create")
    endpoint.transition(
        EndpointState.WARMING, facts=empty, occurred_at=start, reason="container ready"
    )
    endpoint.transition(EndpointState.READY, facts=empty, occurred_at=start, reason="warmup passed")
    endpoint.transition(
        EndpointState.DRAINING, facts=empty, occurred_at=start, reason="benchmark complete"
    )
    with pytest.raises(ContractError, match="work remains"):
        endpoint.transition(
            EndpointState.EVIDENCE_PENDING,
            facts=CleanupFacts(in_flight_jobs=1),
            occurred_at=start,
            reason="too early",
        )
    endpoint.transition(
        EndpointState.EVIDENCE_PENDING, facts=empty, occurred_at=start, reason="drained"
    )
    with pytest.raises(ContractError, match="delete requires"):
        endpoint.transition(
            EndpointState.DELETE_REQUESTED,
            facts=empty,
            occurred_at=start,
            reason="too early",
        )
    ready_to_delete = CleanupFacts(
        artifacts_uploaded=True,
        evidence_persisted=True,
        grace_window_elapsed=True,
    )
    endpoint.transition(
        EndpointState.DELETE_REQUESTED,
        facts=ready_to_delete,
        occurred_at=start,
        reason="all receipts persisted",
    )
    with pytest.raises(ContractError, match="provider absence"):
        endpoint.transition(
            EndpointState.DELETED,
            facts=ready_to_delete,
            occurred_at=start,
            reason="unconfirmed",
        )
    endpoint.transition(
        EndpointState.DELETED,
        facts=CleanupFacts(provider_endpoint_absent=True),
        occurred_at=start,
        reason="provider inventory confirms absence",
    )
    assert endpoint.state is EndpointState.DELETED
    assert endpoint.receipt()["state"] == "deleted"


def test_orphan_audit_excludes_active_and_deleted_endpoints() -> None:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    old = now - timedelta(hours=2)
    orphan = EndpointLifecycle("ep-orphan", "run-old", "pool", old, state=EndpointState.READY)
    active = EndpointLifecycle("ep-active", "run-active", "pool", old, state=EndpointState.READY)
    deleted = EndpointLifecycle("ep-deleted", "run-old", "pool", old, state=EndpointState.DELETED)

    assert audit_orphan_endpoints(
        [orphan, active, deleted],
        active_run_ids={"run-active"},
        now=now,
        orphan_after=timedelta(minutes=30),
    ) == ("ep-orphan",)

    orphan.transition(
        EndpointState.ORPHANED,
        facts=CleanupFacts(),
        occurred_at=now,
        reason="inactive run tag exceeded orphan threshold",
    )
    assert orphan.state is EndpointState.ORPHANED


def test_runpod_receipt_schemas_are_valid(repo_root: Path) -> None:
    schema_root = repo_root / "infra/runpod/v6/schemas"
    for path in sorted(schema_root.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)

    guard = SpendGuard(
        run_id="run-schema",
        policy=SpendPolicy(expected_cost_usd=Decimal("1")),
    )
    spend_schema = json.loads(
        (schema_root / "spend-report.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(guard.report(), spend_schema)
