from __future__ import annotations

import importlib.util
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from akc_api.database import Base
from akc_api.gpu_provider import GpuProviderError
from akc_api.models import (
    Collection,
    Document,
    GpuInvocationEvent,
    GpuProviderInvocation,
    ProcessingJob,
    Project,
    Tenant,
    User,
)
from akc_api.parallel_models import ParallelParseAttempt, ParallelParseShard
from akc_scheduler.first_verified_settlement import (
    SUPERSEDE_REASON,
    FirstVerifiedSettlementError,
    LoserSettlement,
    supersede_losers,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

NOW = datetime(2099, 8, 1, 12, 0, tzinfo=UTC)
REV = "a" * 40
DIGEST = "sha256:" + ("b" * 64)

Sessions = async_sessionmaker[AsyncSession]

# Reuse the callback harness (fixture, result builder, worker) from the sibling test module.
_spec = importlib.util.spec_from_file_location(
    "gpu_admission_harness", Path(__file__).with_name("test_parallel_v6_gpu_admission.py")
)
assert _spec is not None and _spec.loader is not None
gpu_admission = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gpu_admission
_spec.loader.exec_module(gpu_admission)
_callback_harness = gpu_admission.parallel_harness


@dataclass(frozen=True, slots=True)
class Seed:
    tenant_id: uuid.UUID
    shard_id: uuid.UUID
    winner_id: uuid.UUID
    loser_id: uuid.UUID
    loser_invocation_id: uuid.UUID


def _attempt(
    tenant_id: uuid.UUID,
    shard_id: uuid.UUID,
    number: int,
    state: str,
    kind: str,
    invocation_id: uuid.UUID | None = None,
) -> ParallelParseAttempt:
    attempt_id = uuid.uuid4()
    return ParallelParseAttempt(
        id=attempt_id,
        tenant_id=tenant_id,
        shard_id=shard_id,
        provider_invocation_id=invocation_id,
        attempt_number=number,
        attempt_kind=kind,
        state=state,
        pool_key="paddleocr-vl",
        model_id="paddleocr-vl-1.6",
        model_revision=REV,
        runtime_identity=DIGEST,
        route_policy_version="parallel-router-v6",
        idempotency_key=f"attempt-{attempt_id}",
        request_sha256="e" * 64,
        billing_disposition="pending",
    )


def _invocation(
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    job_id: uuid.UUID,
    invocation_id: uuid.UUID,
) -> GpuProviderInvocation:
    return GpuProviderInvocation(
        id=invocation_id,
        tenant_id=tenant_id,
        job_id=job_id,
        project_id=project_id,
        document_id=document_id,
        document_version_id=f"{document_id}:v1",
        provider_key="paddleocr_vl_1_6",
        endpoint_id="parser-accurate",
        idempotency_key=f"inv-{invocation_id}",
        request_manifest_sha256="f" * 64,
        status="submitted",
        input_bucket="source",
        input_object_key=f"tenants/{tenant_id}/source/input.pdf",
        input_sha256="c" * 64,
        output_object_key=f"tenants/{tenant_id}/derived/{invocation_id}.json",
        model_revision=REV,
        runtime_image_digest=DIGEST,
        adapter_version="parallel-parser-adapter-6.0.0",
        provider_job_id=f"job-{invocation_id}",
    )


@pytest_asyncio.fixture
async def harness(tmp_path: Path) -> AsyncIterator[tuple[Sessions, Seed]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'fv.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    tenant_id, user_id, project_id, document_id, job_id, collection_id, shard_id = (
        uuid.uuid4() for _ in range(7)
    )
    loser_invocation_id = uuid.uuid4()
    async with sessions() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, slug=f"t-{tenant_id.hex[:8]}", name="Tenant"),
                User(
                    id=user_id,
                    email=f"{user_id.hex}@example.com",
                    password_hash="not-used",  # noqa: S106
                    display_name="u",
                ),
                Project(id=project_id, tenant_id=tenant_id, name="p", created_by=user_id),
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    title="d",
                    document_type="pdf",
                    status="READY",
                ),
                ProcessingJob(
                    id=job_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_id=document_id,
                    job_type="compile",
                    status="running",
                ),
                Collection(
                    id=collection_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    name="c",
                    status="PROCESSING",
                    created_by=user_id,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                ParallelParseShard(
                    id=shard_id,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    document_id=document_id,
                    processing_job_id=job_id,
                    document_version_id=f"{document_id}:v1",
                    shard_key=f"s-{shard_id}",
                    shard_kind="page",
                    ordinal=0,
                    page_start=1,
                    page_end=1,
                    region={},
                    context={},
                    overlap={},
                    ownership={},
                    route_class="normal_scan",
                    priority=50,
                    size_units=1,
                    plan_version="parallel-v6",
                    input_sha256="d" * 64,
                    status="RUNNING",
                    dispatch_idempotency_key=f"dispatch-{shard_id}",
                ),
                _invocation(tenant_id, project_id, document_id, job_id, loser_invocation_id),
            ]
        )
        await session.flush()
        winner = _attempt(tenant_id, shard_id, 1, "ACCEPTED", "primary")
        loser = _attempt(tenant_id, shard_id, 2, "RUNNING", "hedge", loser_invocation_id)
        session.add_all([winner, loser])
        await session.commit()
        seed = Seed(tenant_id, shard_id, winner.id, loser.id, loser_invocation_id)
    yield sessions, seed
    await engine.dispose()


async def _settle(sessions: Sessions, seed: Seed, key: str = "op-1") -> LoserSettlement:
    async with sessions() as session:
        result = await supersede_losers(
            session, seed.tenant_id, seed.shard_id, seed.winner_id, key, now=NOW
        )
        await session.commit()
        return result


@pytest.mark.asyncio
async def test_running_loser_superseded_and_invocation_cancel_requested(
    harness: tuple[Sessions, Seed],
) -> None:
    sessions, seed = harness
    result = await _settle(sessions, seed)
    assert result.superseded_attempt_ids == (seed.loser_id,)
    assert result.cancel_requested_invocation_ids == (seed.loser_invocation_id,)
    async with sessions() as session:
        loser = await session.get(ParallelParseAttempt, seed.loser_id)
        invocation = await session.get(GpuProviderInvocation, seed.loser_invocation_id)
        winner = await session.get(ParallelParseAttempt, seed.winner_id)
        assert loser is not None and invocation is not None and winner is not None
        assert loser.state == "SUPERSEDED"
        assert loser.billing_disposition == "speculative_unbillable"
        assert loser.failure_code == SUPERSEDE_REASON
        assert invocation.status == "cancel_requested"
        assert invocation.cancellation_reason == SUPERSEDE_REASON
        assert winner.state == "ACCEPTED" and winner.billing_disposition == "pending"


@pytest.mark.asyncio
async def test_replay_is_a_noop(harness: tuple[Sessions, Seed]) -> None:
    sessions, seed = harness
    await _settle(sessions, seed)
    replay = await _settle(sessions, seed)
    assert replay.superseded_attempt_ids == ()
    assert replay.cancel_requested_invocation_ids == ()
    async with sessions() as session:
        events = await session.scalar(select(func.count()).select_from(GpuInvocationEvent))
        assert events == 1


@pytest.mark.asyncio
async def test_other_tenant_shard_raises_and_changes_nothing(
    harness: tuple[Sessions, Seed],
) -> None:
    sessions, seed = harness
    async with sessions() as session:
        with pytest.raises(FirstVerifiedSettlementError):
            await supersede_losers(
                session, uuid.uuid4(), seed.shard_id, seed.winner_id, "op", now=NOW
            )
    async with sessions() as session:
        loser = await session.get(ParallelParseAttempt, seed.loser_id)
        assert loser is not None and loser.state == "RUNNING"


@pytest.mark.asyncio
async def test_unaccepted_foreign_winner_or_empty_key_raises(
    harness: tuple[Sessions, Seed],
) -> None:
    sessions, seed = harness
    for winner, key in ((seed.loser_id, "op"), (uuid.uuid4(), "op"), (seed.winner_id, "")):
        async with sessions() as session:
            with pytest.raises(FirstVerifiedSettlementError):
                await supersede_losers(session, seed.tenant_id, seed.shard_id, winner, key, now=NOW)
    async with sessions() as session:
        loser = await session.get(ParallelParseAttempt, seed.loser_id)
        assert loser is not None and loser.state == "RUNNING"


@pytest.mark.asyncio
async def test_terminal_siblings_are_untouched(harness: tuple[Sessions, Seed]) -> None:
    sessions, seed = harness
    async with sessions() as session:
        loser = await session.get(ParallelParseAttempt, seed.loser_id)
        invocation = await session.get(GpuProviderInvocation, seed.loser_invocation_id)
        assert loser is not None and invocation is not None
        loser.state = "TERMINAL_FAILED"
        invocation.status = "completed"
        await session.commit()
    result = await _settle(sessions, seed)
    assert result.superseded_attempt_ids == ()
    assert result.cancel_requested_invocation_ids == ()
    async with sessions() as session:
        loser = await session.get(ParallelParseAttempt, seed.loser_id)
        invocation = await session.get(GpuProviderInvocation, seed.loser_invocation_id)
        assert loser is not None and invocation is not None
        assert loser.state == "TERMINAL_FAILED" and invocation.status == "completed"


@pytest.mark.asyncio
async def test_queued_sibling_is_reported_and_its_invocation_still_cancelled(
    harness: tuple[Sessions, Seed],
) -> None:
    sessions, seed = harness
    async with sessions() as session:
        loser = await session.get(ParallelParseAttempt, seed.loser_id)
        assert loser is not None
        loser.state = "QUEUED"
        await session.commit()
    result = await _settle(sessions, seed)
    # The api attempt state machine has no QUEUED->SUPERSEDED edge: reported, not hidden.
    assert result.unsupersedable_attempt_ids == (seed.loser_id,)
    assert result.cancel_requested_invocation_ids == (seed.loser_invocation_id,)
    async with sessions() as session:
        loser = await session.get(ParallelParseAttempt, seed.loser_id)
        assert loser is not None and loser.state == "QUEUED"


@pytest.mark.asyncio
async def test_late_provider_completion_for_cancelled_invocation_is_fenced(
    _callback_harness: tuple[Any, Sessions, Any, Any],
) -> None:
    engine, sessions, store, seed = _callback_harness
    winner = _attempt(seed.tenant_id, seed.shard_id, 2, "ACCEPTED", "hedge")
    async with sessions() as session:
        session.add(winner)
        await session.commit()
    async with sessions() as session:
        await supersede_losers(
            session, seed.tenant_id, seed.shard_id, winner.id, "op-late", now=NOW
        )
        await session.commit()
    worker = gpu_admission._worker(engine, store)
    # gpu_jobs does not consult cancel_requested before completing; the fence is the
    # SUPERSEDED attempt, whose output the parallel v6 admission refuses.
    with pytest.raises(GpuProviderError) as refused:
        await worker.admit_callback(
            invocation_id=seed.invocation_id,
            provider_event_id="late-event-1",
            provider_event_sha256="3" * 64,
            result=gpu_admission._result(seed, store),
        )
    assert refused.value.code == "GPU_PARALLEL_V6_RESULT_STATE_INVALID_OUTPUT"
    async with sessions() as session:
        invocation = await session.get(GpuProviderInvocation, seed.invocation_id)
        attempt = await session.get(ParallelParseAttempt, seed.attempt_id)
        assert invocation is not None and attempt is not None
        assert invocation.status != "completed"
        assert invocation.result_manifest is None
        assert attempt.state == "SUPERSEDED"
        assert attempt.output_sha256 is None
