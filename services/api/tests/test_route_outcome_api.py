"""Authorized read evidence for persisted production route outcomes."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from akc_api.arena_repository import (
    ProductionRouteOutcomeSpec,
    record_production_route_outcome,
)
from akc_api.database import Database
from akc_api.models import Collection, ProcessingJob, Project, Tenant, User
from akc_api.route_outcome_api import latest_production_route_outcome, router
from akc_api.security import Principal
from akc_api.settings import Settings
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

TENANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000137")
USER_ID = uuid.UUID("20000000-0000-0000-0000-000000000137")
WORKSPACE_ID = uuid.UUID("30000000-0000-0000-0000-000000000137")
COLLECTION_ID = uuid.UUID("40000000-0000-0000-0000-000000000137")
JOB_ID = uuid.UUID("50000000-0000-0000-0000-000000000137")
OTHER_WORKSPACE_ID = uuid.UUID("60000000-0000-0000-0000-000000000137")
OTHER_JOB_ID = uuid.UUID("70000000-0000-0000-0000-000000000137")
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


@pytest.fixture
async def route_database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(
        Settings(database_url=f"sqlite+aiosqlite:///{(tmp_path / 'routes.db').as_posix()}")
    )
    await database.create_schema()
    async with database.sessions() as session:
        session.add(Tenant(id=TENANT_ID, slug="route-tenant", name="Route Tenant"))
        session.add(
            User(
                id=USER_ID,
                email="route-outcome@example.test",
                password_hash="test-only-hash",  # noqa: S106
                display_name="Route Reader",
            )
        )
        await session.flush()
        session.add(
            Project(
                id=WORKSPACE_ID,
                tenant_id=TENANT_ID,
                name="Route workspace",
                created_by=USER_ID,
            )
        )
        await session.flush()
        session.add(
            Collection(
                id=COLLECTION_ID,
                tenant_id=TENANT_ID,
                project_id=WORKSPACE_ID,
                name="Route collection",
                status="PROCESSING",
                created_by=USER_ID,
            )
        )
        session.add(
            ProcessingJob(
                id=JOB_ID,
                tenant_id=TENANT_ID,
                project_id=WORKSPACE_ID,
                job_type="collection_processing",
                status="running",
                requested_options={"collection_id": str(COLLECTION_ID)},
            )
        )
        await session.commit()
    yield database
    await database.dispose()


def _principal(*, tenant_id: uuid.UUID = TENANT_ID) -> Principal:
    return Principal(
        user_id=USER_ID,
        tenant_id=tenant_id,
        roles=frozenset({"owner"}),
        scopes=frozenset({"api:read"}),
        auth_type="api_key",
    )


def _spec(
    *,
    outcome_id: uuid.UUID,
    idempotency_key: str,
    shard_id: str,
    status: str = "EXECUTED",
) -> ProductionRouteOutcomeSpec:
    shadow = status == "SHADOW_ONLY"
    return ProductionRouteOutcomeSpec(
        id=outcome_id,
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        collection_id=COLLECTION_ID,
        processing_job_id=JOB_ID,
        shard_id=shard_id,
        idempotency_key=idempotency_key,
        requested_mode="shadow" if shadow else "deterministic",
        effective_mode="shadow" if shadow else "deterministic",
        decision_kind="DETERMINISTIC",
        executable=not shadow,
        outcome_status=status,  # type: ignore[arg-type]
        selected_path="native:worker-1",
        selected_model_registry_id=None,
        policy_version="deterministic-v1",
        policy_sha256=SHA_A,
        authority_envelope_sha256=SHA_B,
        permission_snapshot_sha256=SHA_C,
        route_receipt_sha256=SHA_D,
        fail_closed_reason_codes=(),
        shadow_counterfactual={"executable": False} if shadow else None,
        trusted=None if shadow else True,
        latency_ms=None if shadow else 120,
        actual_cost_usd=None if shadow else Decimal("0.0012000000"),
    )


@pytest.mark.asyncio
async def test_latest_route_outcome_returns_newest_real_row_and_preserves_nulls(
    route_database: Database,
) -> None:
    async with route_database.sessions() as session:
        older = await record_production_route_outcome(
            session,
            _spec(
                outcome_id=uuid.UUID(int=1),
                idempotency_key="route-old",
                shard_id="shard-old",
            ),
        )
        older.created_at = datetime(2026, 9, 12, 10, tzinfo=UTC)
        newest = await record_production_route_outcome(
            session,
            _spec(
                outcome_id=uuid.UUID(int=2),
                idempotency_key="route-new",
                shard_id="shard-new",
                status="SHADOW_ONLY",
            ),
        )
        newest.created_at = datetime(2026, 9, 12, 11, tzinfo=UTC)
        await session.commit()

    async with route_database.sessions() as session:
        response = await latest_production_route_outcome(
            COLLECTION_ID,
            JOB_ID,
            _principal(),
            session,
        )

    assert response.outcome_id == uuid.UUID(int=2)
    assert response.shard_id == "shard-new"
    assert response.outcome_status == "SHADOW_ONLY"
    assert response.trusted is None
    assert response.latency_ms is None
    assert response.actual_cost_usd is None
    assert not hasattr(response, "shadow_counterfactual")


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["tenant", "project", "job", "binding"])
async def test_latest_route_outcome_hides_cross_scope_and_binding_mismatches(
    route_database: Database,
    mismatch: str,
) -> None:
    async with route_database.sessions() as session:
        await record_production_route_outcome(
            session,
            _spec(outcome_id=uuid.uuid4(), idempotency_key="route", shard_id="shard"),
        )
        await session.commit()
        principal = _principal(tenant_id=uuid.uuid4()) if mismatch == "tenant" else _principal()
        job_id = uuid.uuid4() if mismatch == "job" else JOB_ID
        if mismatch == "project":
            session.add(
                Project(
                    id=OTHER_WORKSPACE_ID,
                    tenant_id=TENANT_ID,
                    name="Other route workspace",
                    created_by=USER_ID,
                )
            )
            await session.flush()
            session.add(
                ProcessingJob(
                    id=OTHER_JOB_ID,
                    tenant_id=TENANT_ID,
                    project_id=OTHER_WORKSPACE_ID,
                    job_type="collection_processing",
                    status="running",
                    requested_options={"collection_id": str(COLLECTION_ID)},
                )
            )
            await session.commit()
            job_id = OTHER_JOB_ID
        if mismatch == "binding":
            job = await session.get(ProcessingJob, JOB_ID)
            assert job is not None
            job.requested_options = {"collection_id": str(uuid.uuid4())}
            await session.commit()
        with pytest.raises(HTTPException) as raised:
            await latest_production_route_outcome(
                COLLECTION_ID,
                job_id,
                principal,
                session,
            )
    assert raised.value.status_code == 404
    assert raised.value.detail == {"code": "ROUTE_OUTCOME_NOT_FOUND"}


@pytest.mark.asyncio
async def test_latest_route_outcome_fails_closed_on_integrity_drift(
    route_database: Database,
) -> None:
    async with route_database.sessions() as session:
        row = await record_production_route_outcome(
            session,
            _spec(outcome_id=uuid.uuid4(), idempotency_key="route", shard_id="shard"),
        )
        await session.execute(text("PRAGMA ignore_check_constraints = ON"))
        row.research_use_allowed = True
        await session.commit()
        with pytest.raises(HTTPException) as raised:
            await latest_production_route_outcome(
                COLLECTION_ID,
                JOB_ID,
                _principal(),
                session,
            )
    assert raised.value.status_code == 503
    assert raised.value.detail == {"code": "ROUTE_OUTCOME_INTEGRITY_UNAVAILABLE"}


class _UnavailableSession:
    async def scalar(self, _statement: Any) -> None:
        raise SQLAlchemyError("store unavailable")


@pytest.mark.asyncio
async def test_latest_route_outcome_reports_store_unavailable() -> None:
    with pytest.raises(HTTPException) as raised:
        await latest_production_route_outcome(
            COLLECTION_ID,
            JOB_ID,
            _principal(),
            cast(AsyncSession, _UnavailableSession()),
        )
    assert raised.value.status_code == 503
    assert raised.value.detail == {"code": "ROUTE_OUTCOME_STORE_UNAVAILABLE"}


def test_route_is_registered_with_the_bounded_path() -> None:
    paths = {getattr(route, "path", None) for route in router.routes}
    assert "/v1/collections/{collection_id}/route-outcomes/latest" in paths
