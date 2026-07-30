from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import orjson
import pytest
import pytest_asyncio
from akc_api.database import Base
from akc_api.models import (
    Document,
    IdempotencyRecord,
    JobEvent,
    OutboxEvent,
    ProcessingJob,
    Project,
    Tenant,
    User,
    WebhookDelivery,
    WebhookEndpoint,
)
from akc_scheduler.scheduler import (
    DurableScheduler,
    _PostgresDispatchLease,
    delivery_claim_statement,
    dispatch_advisory_lock_key,
    dispatch_claim_statement,
    exponential_backoff_seconds,
    outbox_claim_statement,
)
from akc_scheduler.settings import SchedulerSettings
from akc_scheduler.telemetry import (
    DISPATCH_TENANT_BUSY_DEFERRALS,
    refresh_scheduler_metrics,
)
from akc_scheduler.webhooks import WebhookResponse, encrypt_secret
from akc_telemetry.metrics import (
    DELETION_OLDEST_PENDING,
    DLQ_MESSAGES,
    QUEUE_DEPTH,
    QUEUE_OLDEST_AGE,
)
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class RecordingHttpClient:
    def __init__(
        self,
        *statuses: int,
        on_post: Callable[[], None] | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        self._statuses = deque(statuses)
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []
        self._on_post = on_post
        self._retry_after_seconds = retry_after_seconds

    async def post(
        self,
        url: str,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> WebhookResponse:
        self.calls.append((url, body, headers))
        if self._on_post is not None:
            self._on_post()
        return WebhookResponse(
            status_code=self._statuses.popleft(),
            final_url=url,
            redirect_count=0,
            retry_after_seconds=self._retry_after_seconds,
        )


class HangingHttpClient:
    async def post(
        self,
        _url: str,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> WebhookResponse:
        del body, headers
        await asyncio.get_running_loop().create_future()
        raise AssertionError("unreachable")


class RecordingCompileJob:
    def __init__(
        self,
        *,
        failures: int = 0,
        commit_before_failure: bool = False,
        gate: asyncio.Event | None = None,
        wait_stage: str | None = None,
    ) -> None:
        self.failures = failures
        self.commit_before_failure = commit_before_failure
        self.gate = gate
        self.wait_stage = wait_stage
        self.calls: list[uuid.UUID] = []

    async def __call__(
        self,
        *,
        session: AsyncSession,
        job_id: uuid.UUID,
        settings: object,
        object_store: object | None = None,
    ) -> None:
        del settings, object_store
        self.calls.append(job_id)
        if self.gate is not None:
            await self.gate.wait()
        job = await session.get(ProcessingJob, job_id)
        assert job is not None
        if self.failures:
            self.failures -= 1
            if self.commit_before_failure:
                job.status = "completed"
                await session.commit()
            raise RuntimeError("synthetic_compile_failure")
        if self.wait_stage is not None:
            job.status = "running"
            job.progress = {"stage": self.wait_stage}
            await session.commit()
            return
        job.status = "completed"
        await session.commit()


class SequenceAdvisoryLease:
    def __init__(self, *outcomes: bool) -> None:
        self._outcomes = deque(outcomes)
        self.keys: list[int] = []

    async def try_acquire(self, lock_key: int) -> bool:
        self.keys.append(lock_key)
        return self._outcomes.popleft()

    async def release(self) -> None:
        return None


class InMemoryAdvisoryBackend:
    def __init__(self) -> None:
        self.owners: dict[int, object] = {}


class InMemoryAdvisorySession:
    def __init__(self, backend: InMemoryAdvisoryBackend, owner: object) -> None:
        self.backend = backend
        self.owner = owner

    async def scalar(
        self,
        statement: object,
        parameters: dict[str, int],
    ) -> bool:
        del statement
        lock_key = parameters["lock_key"]
        if lock_key in self.backend.owners:
            return False
        self.backend.owners[lock_key] = self.owner
        return True


class InMemoryAdvisoryConnection:
    def __init__(
        self,
        backend: InMemoryAdvisoryBackend,
        owner: object,
        *,
        block_unlock: bool = False,
    ) -> None:
        self.backend = backend
        self.owner = owner
        self.block_unlock = block_unlock
        self.unlock_started = asyncio.Event()
        self.unlock_gate = asyncio.Event()
        self.invalidated = False
        self.commits = 0

    async def scalar(
        self,
        statement: object,
        parameters: dict[str, int],
    ) -> bool:
        del statement
        if self.block_unlock:
            self.unlock_started.set()
            await self.unlock_gate.wait()
        lock_key = parameters["lock_key"]
        if self.backend.owners.get(lock_key) is not self.owner:
            return False
        del self.backend.owners[lock_key]
        return True

    async def commit(self) -> None:
        self.commits += 1

    async def invalidate(self) -> None:
        self.invalidated = True
        self.backend.owners = {
            key: owner for key, owner in self.backend.owners.items() if owner is not self.owner
        }


@pytest_asyncio.fixture
async def sessions(
    tmp_path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scheduler.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    yield factory
    await engine.dispose()


def settings(encryption_key: str, **overrides: object) -> SchedulerSettings:
    values: dict[str, object] = {
        "env": "test",
        "webhook_delivery_enabled": True,
        "webhook_encryption_key": encryption_key,
        "webhook_allowed_hosts": "hooks.example.com",
        "webhook_retry_schedule_seconds": "",
        "webhook_backoff_jitter_ratio": 0,
    }
    values.update(overrides)
    return SchedulerSettings(**values)


async def seed_endpoint_and_event(
    sessions: async_sessionmaker[AsyncSession],
    *,
    encryption_key: str,
    event_types: list[str] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    async with sessions.begin() as session:
        tenant = Tenant(slug=f"tenant-{uuid.uuid4()}", name="Tenant")
        user = User(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=uuid.uuid4().hex,
            display_name="Owner",
        )
        session.add_all([tenant, user])
        await session.flush()
        endpoint = WebhookEndpoint(
            tenant_id=tenant.id,
            url="https://hooks.example.com/events",
            secret_hash=hashlib.sha256(b"signing-secret").hexdigest(),
            encrypted_secret=encrypt_secret("signing-secret", encryption_key),
            event_types=event_types or ["job.completed.v1"],
            active=True,
            created_by=user.id,
        )
        event = OutboxEvent(
            tenant_id=tenant.id,
            aggregate_type="job",
            aggregate_id=uuid.uuid4(),
            event_type="job.completed.v1",
            payload={"job_id": "job-1"},
            available_at=NOW,
        )
        session.add_all([endpoint, event])
        await session.flush()
        return endpoint.id, event.id


async def seed_dispatch(
    sessions: async_sessionmaker[AsyncSession],
    *,
    payload: dict[str, object] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    async with sessions.begin() as session:
        tenant = Tenant(slug=f"tenant-{uuid.uuid4()}", name="Tenant")
        user = User(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=uuid.uuid4().hex,
            display_name="Owner",
        )
        session.add_all([tenant, user])
        await session.flush()
        project = Project(
            tenant_id=tenant.id,
            name="Project",
            created_by=user.id,
        )
        session.add(project)
        await session.flush()
        document = Document(
            tenant_id=tenant.id,
            project_id=project.id,
            title="Document",
            document_type="markdown",
        )
        session.add(document)
        await session.flush()
        job = ProcessingJob(
            tenant_id=tenant.id,
            project_id=project.id,
            document_id=document.id,
            job_type="compile",
            status="queued",
        )
        session.add(job)
        await session.flush()
        event = OutboxEvent(
            tenant_id=tenant.id,
            aggregate_type="job",
            aggregate_id=job.id,
            event_type="job.dispatch.requested.v1",
            payload=payload or {"job_id": str(job.id)},
            available_at=NOW,
        )
        session.add(event)
        await session.flush()
        return job.id, event.id


def metric_value(
    metric: Any,
    sample_name: str,
    labels: dict[str, str] | None = None,
) -> float:
    for family in metric.collect():
        for sample in family.samples:
            if sample.name == sample_name and sample.labels == (labels or {}):
                return float(sample.value)
    raise AssertionError(f"missing metric sample {sample_name}")


async def test_scheduler_metrics_reflect_durable_global_state(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    job_id, dispatch_event_id = await seed_dispatch(sessions)
    endpoint_id, _ = await seed_endpoint_and_event(
        sessions,
        encryption_key=encryption_key,
    )
    async with sessions.begin() as session:
        job = await session.get(ProcessingJob, job_id)
        dispatch_event = await session.get(OutboxEvent, dispatch_event_id)
        endpoint = await session.get(WebhookEndpoint, endpoint_id)
        assert job is not None and dispatch_event is not None and endpoint is not None
        job.created_at = NOW - timedelta(minutes=10)
        dispatch_event.dead_lettered_at = NOW
        dispatch_event.published_at = NOW
        session.add(
            OutboxEvent(
                tenant_id=job.tenant_id,
                aggregate_type="document",
                aggregate_id=job.document_id or job.id,
                event_type="deletion.retry.requested.v1",
                payload={"manifest_hash": "0" * 64},
                available_at=NOW,
                created_at=NOW - timedelta(minutes=2),
            )
        )
        session.add(
            WebhookDelivery(
                tenant_id=endpoint.tenant_id,
                endpoint_id=endpoint.id,
                event_type="job.completed.v1",
                payload={},
                status="dead_letter",
                attempts=1,
                next_attempt_at=NOW,
                dead_lettered_at=NOW,
            )
        )

    await refresh_scheduler_metrics(sessions, mode="dispatch", now=NOW)
    assert (
        metric_value(
            QUEUE_DEPTH,
            "akc_queue_depth",
            {"status": "queued"},
        )
        == 1
    )
    assert (
        metric_value(
            QUEUE_OLDEST_AGE,
            "akc_queue_oldest_job_age_seconds",
        )
        == 600
    )

    await refresh_scheduler_metrics(sessions, mode="webhook", now=NOW)
    assert metric_value(DLQ_MESSAGES, "akc_dlq_messages") == 2
    assert (
        metric_value(
            DELETION_OLDEST_PENDING,
            "akc_deletion_oldest_pending_seconds",
        )
        == 120
    )


def test_claim_statements_use_skip_locked_only_for_postgresql() -> None:
    outbox_postgres = str(
        outbox_claim_statement(
            now=NOW,
            batch_size=10,
            dialect_name="postgresql",
        ).compile(dialect=postgresql.dialect())
    )
    delivery_postgres = str(
        delivery_claim_statement(
            now=NOW,
            dialect_name="postgresql",
        ).compile(dialect=postgresql.dialect())
    )
    dispatch_postgres = str(
        dispatch_claim_statement(
            now=NOW,
            dialect_name="postgresql",
            candidate_tenants=64,
        ).compile(dialect=postgresql.dialect())
    )
    outbox_sqlite = str(
        outbox_claim_statement(
            now=NOW,
            batch_size=10,
            dialect_name="sqlite",
        ).compile(dialect=sqlite.dialect())
    )

    assert "FOR UPDATE SKIP LOCKED" in outbox_postgres
    assert "row_number() OVER (PARTITION BY outbox_events.tenant_id" in dispatch_postgres
    assert "FOR UPDATE OF outbox_events SKIP LOCKED" in dispatch_postgres
    assert "FOR UPDATE OF webhook_deliveries SKIP LOCKED" in delivery_postgres
    assert "FOR UPDATE" not in outbox_sqlite


def test_dispatch_advisory_keys_are_stable_and_domain_separated() -> None:
    identifier = uuid.UUID("00000000-0000-4000-8000-000000000001")
    other = uuid.UUID("00000000-0000-4000-8000-000000000002")

    tenant_key = dispatch_advisory_lock_key("tenant", identifier)
    assert tenant_key == dispatch_advisory_lock_key("tenant", identifier)
    assert tenant_key != dispatch_advisory_lock_key("job", identifier)
    assert tenant_key != dispatch_advisory_lock_key("tenant", other)
    assert -(2**63) <= tenant_key < 2**63
    with pytest.raises(ValueError, match="unknown dispatch advisory lock namespace"):
        dispatch_advisory_lock_key("unknown", identifier)  # type: ignore[arg-type]


async def test_fair_candidate_scan_returns_at_most_one_event_per_tenant(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    first_job_id, _ = await seed_dispatch(sessions)
    async with sessions.begin() as session:
        first_job = await session.get(ProcessingJob, first_job_id)
        assert first_job is not None
        second_job = ProcessingJob(
            tenant_id=first_job.tenant_id,
            project_id=first_job.project_id,
            document_id=first_job.document_id,
            job_type="compile",
            status="queued",
        )
        session.add(second_job)
        await session.flush()
        session.add(
            OutboxEvent(
                tenant_id=first_job.tenant_id,
                aggregate_type="job",
                aggregate_id=second_job.id,
                event_type="job.dispatch.requested.v1",
                payload={"job_id": str(second_job.id)},
                available_at=NOW,
            )
        )
    await seed_dispatch(sessions)

    async with sessions.begin() as session:
        candidates = list(
            await session.scalars(
                dispatch_claim_statement(
                    now=NOW,
                    dialect_name="sqlite",
                    candidate_tenants=64,
                )
            )
        )

    assert len(candidates) == 2
    assert len({candidate.tenant_id for candidate in candidates}) == 2


async def test_busy_tenant_defers_without_attempt_and_next_tenant_is_admitted(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(),  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            dispatch_tenant_busy_delay_seconds=3,
        ),
        clock=MutableClock(),
    )
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    job_a = uuid.uuid4()
    job_b = uuid.uuid4()
    event_a = OutboxEvent(
        tenant_id=tenant_a,
        aggregate_type="job",
        aggregate_id=job_a,
        event_type="job.dispatch.requested.v1",
        payload={"job_id": str(job_a)},
        available_at=NOW,
        attempts=0,
    )
    event_b = OutboxEvent(
        tenant_id=tenant_b,
        aggregate_type="job",
        aggregate_id=job_b,
        event_type="job.dispatch.requested.v1",
        payload={"job_id": str(job_b)},
        available_at=NOW,
        attempts=0,
    )
    lease = SequenceAdvisoryLease(False, True, True)
    before = metric_value(
        DISPATCH_TENANT_BUSY_DEFERRALS,
        "akc_dispatch_tenant_busy_deferrals_total",
    )

    admission = await scheduler._admit_dispatch_candidate(
        [event_a, event_b],
        dialect="postgresql",
        lease=lease,
        now=NOW,
    )

    assert admission is not None
    assert admission.event is event_b
    assert admission.job_id == job_b
    assert event_a.attempts == 0
    assert event_a.available_at == NOW + timedelta(seconds=3)
    assert lease.keys == [
        dispatch_advisory_lock_key("tenant", tenant_a),
        dispatch_advisory_lock_key("tenant", tenant_b),
        dispatch_advisory_lock_key("job", job_b),
    ]
    assert (
        metric_value(
            DISPATCH_TENANT_BUSY_DEFERRALS,
            "akc_dispatch_tenant_busy_deferrals_total",
        )
        == before + 1
    )
    for family in DISPATCH_TENANT_BUSY_DEFERRALS.collect():
        assert all(not sample.labels for sample in family.samples)


async def test_advisory_lease_cancel_cleanup_releases_capacity_for_waiter() -> None:
    backend = InMemoryAdvisoryBackend()
    first_owner = object()
    second_owner = object()
    first_connection = InMemoryAdvisoryConnection(
        backend,
        first_owner,
        block_unlock=True,
    )
    second_connection = InMemoryAdvisoryConnection(backend, second_owner)
    first_lease = _PostgresDispatchLease(
        session=InMemoryAdvisorySession(backend, first_owner),  # type: ignore[arg-type]
        connection=first_connection,  # type: ignore[arg-type]
    )
    second_lease = _PostgresDispatchLease(
        session=InMemoryAdvisorySession(backend, second_owner),  # type: ignore[arg-type]
        connection=second_connection,  # type: ignore[arg-type]
    )
    lock_key = dispatch_advisory_lock_key("tenant", uuid.uuid4())
    attempt_started = asyncio.Event()
    hold_attempt = asyncio.Event()

    async def run_attempt() -> None:
        try:
            assert await first_lease.try_acquire(lock_key)
            attempt_started.set()
            await hold_attempt.wait()
        finally:
            await first_lease.release()

    task = asyncio.create_task(run_attempt())
    await attempt_started.wait()
    assert not await second_lease.try_acquire(lock_key)

    task.cancel()
    await first_connection.unlock_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert first_connection.invalidated
    assert await second_lease.try_acquire(lock_key)
    await second_lease.release()
    assert backend.owners == {}
    assert second_connection.commits == 1


async def test_dispatch_executes_job_and_acknowledges_outbox(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    job_id, event_id = await seed_dispatch(sessions)
    compile_job = RecordingCompileJob()
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(),  # type: ignore[arg-type]
        settings=settings(encryption_key),
        compile_job=compile_job,  # type: ignore[arg-type]
        clock=MutableClock(),
    )

    assert await scheduler.dispatch_one()
    assert not await scheduler.dispatch_one()
    async with sessions() as session:
        job = await session.get(ProcessingJob, job_id)
        event = await session.get(OutboxEvent, event_id)
    assert compile_job.calls == [job_id]
    assert job is not None and job.status == "completed"
    assert event is not None and as_utc(event.published_at) == NOW
    assert event.dead_lettered_at is None
    assert event.attempts == 1


async def test_dispatch_acknowledges_durable_provider_wait_without_retrying(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    job_id, event_id = await seed_dispatch(sessions)
    compile_job = RecordingCompileJob(wait_stage="knowledge_waiting")
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(),  # type: ignore[arg-type]
        settings=settings(encryption_key),
        compile_job=compile_job,  # type: ignore[arg-type]
        clock=MutableClock(),
    )

    assert await scheduler.dispatch_one()
    assert not await scheduler.dispatch_one()
    async with sessions() as session:
        job = await session.get(ProcessingJob, job_id)
        event = await session.get(OutboxEvent, event_id)
    assert compile_job.calls == [job_id]
    assert job is not None and job.status == "running"
    assert job.progress["stage"] == "knowledge_waiting"
    assert event is not None and as_utc(event.published_at) == NOW


async def test_concurrent_dispatch_does_not_duplicate_execution(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    job_id, _ = await seed_dispatch(sessions)
    gate = asyncio.Event()
    compile_job = RecordingCompileJob(gate=gate)
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(),  # type: ignore[arg-type]
        settings=settings(encryption_key),
        compile_job=compile_job,  # type: ignore[arg-type]
        clock=MutableClock(),
    )

    first = asyncio.create_task(scheduler.dispatch_one())
    await asyncio.sleep(0)
    second = asyncio.create_task(scheduler.dispatch_one())
    gate.set()
    assert sorted(await asyncio.gather(first, second)) == [False, True]
    assert compile_job.calls == [job_id]


async def test_dispatch_retries_adapter_failure_then_succeeds(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    job_id, event_id = await seed_dispatch(sessions)
    clock = MutableClock()
    compile_job = RecordingCompileJob(failures=1)
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(),  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            dispatch_backoff_base_seconds=2,
            dispatch_backoff_jitter_ratio=0,
        ),
        compile_job=compile_job,  # type: ignore[arg-type]
        clock=clock,
    )

    assert await scheduler.dispatch_one()
    async with sessions() as session:
        event = await session.get(OutboxEvent, event_id)
    assert event is not None and event.published_at is None
    assert event.attempts == 1
    assert as_utc(event.available_at) == NOW + timedelta(seconds=2)
    clock.value = as_utc(event.available_at) or NOW
    assert await scheduler.dispatch_one()
    assert compile_job.calls == [job_id, job_id]


async def test_dispatch_crash_after_job_commit_is_not_reexecuted(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    job_id, event_id = await seed_dispatch(sessions)
    clock = MutableClock()
    compile_job = RecordingCompileJob(
        failures=1,
        commit_before_failure=True,
    )
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(),  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            dispatch_backoff_base_seconds=2,
            dispatch_backoff_jitter_ratio=0,
        ),
        compile_job=compile_job,  # type: ignore[arg-type]
        clock=clock,
    )

    assert await scheduler.dispatch_one()
    clock.value += timedelta(seconds=2)
    assert await scheduler.dispatch_one()
    async with sessions() as session:
        event = await session.get(OutboxEvent, event_id)
    assert compile_job.calls == [job_id]
    assert event is not None and as_utc(event.published_at) == clock.value
    assert event.attempts == 2


async def test_dispatch_attempt_limit_dead_letters_terminally(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    _, event_id = await seed_dispatch(sessions)
    compile_job = RecordingCompileJob(failures=1)
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(),  # type: ignore[arg-type]
        settings=settings(encryption_key, dispatch_max_attempts=1),
        compile_job=compile_job,  # type: ignore[arg-type]
        clock=MutableClock(),
    )

    assert await scheduler.dispatch_one()
    assert not await scheduler.dispatch_one()
    async with sessions() as session:
        event = await session.get(OutboxEvent, event_id)
    assert event is not None and as_utc(event.published_at) == NOW
    assert as_utc(event.dead_lettered_at) == NOW
    assert event.attempts == 1
    async with sessions() as session:
        job = await session.scalar(select(ProcessingJob))
    assert job is not None and job.status == "failed"
    assert job.error is not None
    assert job.error["code"] == "DISPATCH_ATTEMPTS_EXHAUSTED"


@pytest.mark.parametrize(
    ("attempt", "random_value", "expected"),
    (
        (1, 0.0, 8.0),
        (1, 0.5, 10.0),
        (2, 1.0, 24.0),
        (8, 1.0, 25.0),
    ),
)
def test_exponential_backoff_is_jittered_and_capped(
    attempt: int,
    random_value: float,
    expected: float,
) -> None:
    assert exponential_backoff_seconds(
        attempt,
        base_seconds=10,
        maximum_seconds=25,
        jitter_ratio=0.2,
        random_value=random_value,
    ) == pytest.approx(expected)


async def test_outbox_fanout_is_atomic_filtered_and_idempotent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    endpoint_id, event_id = await seed_endpoint_and_event(
        sessions,
        encryption_key=encryption_key,
    )
    async with sessions.begin() as session:
        public_event = await session.get(OutboxEvent, event_id)
        assert public_event is not None
        internal_event = OutboxEvent(
            tenant_id=public_event.tenant_id,
            aggregate_type="job",
            aggregate_id=uuid.uuid4(),
            event_type="job.dispatch.requested.v1",
            payload={"job_id": "internal-job"},
            available_at=NOW,
        )
        session.add(internal_event)
        await session.flush()
        internal_event_id = internal_event.id
    http_client = RecordingHttpClient()
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=http_client,  # type: ignore[arg-type]
        settings=settings(encryption_key),
        clock=MutableClock(),
    )

    concurrent_results = await asyncio.gather(
        scheduler.publish_outbox_batch(),
        scheduler.publish_outbox_batch(),
    )
    assert sorted(concurrent_results) == [0, 1]
    assert await scheduler.publish_outbox_batch() == 0

    async with sessions() as session:
        event = await session.get(OutboxEvent, event_id)
        untouched_internal_event = await session.get(OutboxEvent, internal_event_id)
        deliveries = list(await session.scalars(select(WebhookDelivery)))
    assert event is not None
    assert event.published_at is not None
    assert event.attempts == 1
    assert untouched_internal_event is not None
    assert untouched_internal_event.published_at is None
    assert untouched_internal_event.attempts == 0
    assert len(deliveries) == 1
    assert deliveries[0].endpoint_id == endpoint_id
    assert deliveries[0].payload == {"job_id": "job-1"}


async def test_outbox_fanout_fails_closed_when_endpoint_quota_drifted(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    endpoint_id, event_id = await seed_endpoint_and_event(
        sessions,
        encryption_key=encryption_key,
    )
    async with sessions.begin() as session:
        endpoint = await session.get(WebhookEndpoint, endpoint_id)
        assert endpoint is not None
        session.add(
            WebhookEndpoint(
                tenant_id=endpoint.tenant_id,
                url="https://hooks.example.com/second",
                secret_hash=endpoint.secret_hash,
                encrypted_secret=endpoint.encrypted_secret,
                event_types=["job.completed.v1"],
                active=True,
                created_by=endpoint.created_by,
            )
        )

    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(),  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            webhook_max_endpoints_per_tenant=1,
        ),
        clock=MutableClock(),
    )

    with pytest.raises(RuntimeError, match="webhook_endpoint_quota_drift"):
        await scheduler.publish_outbox_batch()

    async with sessions() as session:
        event = await session.get(OutboxEvent, event_id)
        deliveries = list(await session.scalars(select(WebhookDelivery)))
    assert event is not None
    assert event.published_at is None
    assert event.attempts == 0
    assert deliveries == []


async def test_delivery_kill_switch_leaves_outbox_and_delivery_pending(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    _endpoint_id, event_id = await seed_endpoint_and_event(
        sessions,
        encryption_key=encryption_key,
    )
    http_client = RecordingHttpClient(204)
    disabled = DurableScheduler(
        sessions=sessions,
        http_client=http_client,  # type: ignore[arg-type]
        settings=settings(encryption_key, webhook_delivery_enabled=False),
        clock=MutableClock(),
    )
    assert await disabled.publish_outbox_batch() == 0
    async with sessions() as session:
        event = await session.get(OutboxEvent, event_id)
        deliveries = list(await session.scalars(select(WebhookDelivery)))
    assert event is not None and event.published_at is None
    assert deliveries == []

    enabled = DurableScheduler(
        sessions=sessions,
        http_client=http_client,  # type: ignore[arg-type]
        settings=settings(encryption_key),
        clock=MutableClock(),
    )
    assert await enabled.publish_outbox_batch() == 1
    assert not await disabled.deliver_one()
    async with sessions() as session:
        delivery = await session.scalar(select(WebhookDelivery))
    assert delivery is not None
    assert delivery.status == "pending"
    assert delivery.attempts == 0
    assert http_client.calls == []


async def test_masterplan_webhook_retry_schedule_is_exact(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(),  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            webhook_max_attempts=6,
            webhook_retry_schedule_seconds="60,300,1800,7200,43200",
        ),
        clock=MutableClock(),
    )
    assert [scheduler._retry_delay(attempt) for attempt in range(1, 6)] == [
        60,
        300,
        1_800,
        7_200,
        43_200,
    ]


async def test_retry_preserves_idempotency_identity_then_delivers(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    await seed_endpoint_and_event(sessions, encryption_key=encryption_key)
    clock = MutableClock()
    http_client = RecordingHttpClient(503, 204)
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=http_client,  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            webhook_backoff_base_seconds=2,
            webhook_backoff_max_seconds=60,
        ),
        clock=clock,
        random_source=lambda: 0.5,
    )
    await scheduler.publish_outbox_batch()

    assert await scheduler.deliver_one()
    async with sessions() as session:
        delivery = await session.scalar(select(WebhookDelivery))
        assert delivery is not None
        delivery_id = delivery.id
        assert delivery.status == "retry"
        assert delivery.attempts == 1
        assert delivery.next_attempt_at.replace(tzinfo=UTC) == NOW + timedelta(seconds=2)

    clock.value += timedelta(seconds=2)
    assert await scheduler.deliver_one()
    async with sessions() as session:
        delivery = await session.get(WebhookDelivery, delivery_id)
        assert delivery is not None
        assert delivery.status == "delivered"
        assert delivery.attempts == 2
        assert delivery.last_status_code == 204
        assert delivery.delivered_at is not None

    first_call, second_call = http_client.calls
    assert first_call[1] == second_call[1]
    assert first_call[2]["Idempotency-Key"] == second_call[2]["Idempotency-Key"] == str(delivery_id)
    assert first_call[2]["X-AKC-Delivery-Attempt"] == "1"
    assert second_call[2]["X-AKC-Delivery-Attempt"] == "2"
    assert orjson.loads(first_call[1])["id"] == str(delivery_id)


async def test_retry_delay_starts_when_slow_attempt_finishes(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    await seed_endpoint_and_event(sessions, encryption_key=encryption_key)
    clock = MutableClock()

    def finish_slow_attempt() -> None:
        clock.value += timedelta(seconds=20)

    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(503, on_post=finish_slow_attempt),  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            webhook_backoff_base_seconds=2,
            webhook_backoff_max_seconds=60,
        ),
        clock=clock,
        random_source=lambda: 0.5,
    )
    await scheduler.publish_outbox_batch()
    assert await scheduler.deliver_one()

    async with sessions() as session:
        delivery = await session.scalar(select(WebhookDelivery))
    assert delivery is not None
    assert delivery.next_attempt_at.replace(tzinfo=UTC) == NOW + timedelta(seconds=22)


async def test_retry_after_extends_exponential_backoff(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    await seed_endpoint_and_event(sessions, encryption_key=encryption_key)
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(429, retry_after_seconds=600),  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            webhook_backoff_base_seconds=2,
            webhook_backoff_max_seconds=60,
        ),
        clock=MutableClock(),
        random_source=lambda: 0.5,
    )
    await scheduler.publish_outbox_batch()
    assert await scheduler.deliver_one()

    async with sessions() as session:
        delivery = await session.scalar(select(WebhookDelivery))
    assert delivery is not None
    assert delivery.next_attempt_at.replace(tzinfo=UTC) == NOW + timedelta(seconds=600)


async def test_exhausted_retry_enters_terminal_dead_letter_state(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    await seed_endpoint_and_event(sessions, encryption_key=encryption_key)
    clock = MutableClock()
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(503, 503),  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            webhook_max_attempts=2,
            webhook_backoff_base_seconds=1,
            webhook_backoff_max_seconds=10,
        ),
        clock=clock,
        random_source=lambda: 0.5,
    )
    await scheduler.publish_outbox_batch()

    assert await scheduler.deliver_one()
    clock.value += timedelta(seconds=1)
    assert await scheduler.deliver_one()
    clock.value += timedelta(days=1)
    assert not await scheduler.deliver_one()

    async with sessions() as session:
        delivery = await session.scalar(select(WebhookDelivery))
    assert delivery is not None
    assert delivery.status == "dead_letter"
    assert delivery.attempts == 2
    assert delivery.last_status_code == 503


async def test_key_mismatch_pauses_without_consuming_attempts(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    wrong_key = Fernet.generate_key().decode("ascii")
    await seed_endpoint_and_event(sessions, encryption_key=encryption_key)
    http_client = RecordingHttpClient()
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=http_client,  # type: ignore[arg-type]
        settings=settings(
            wrong_key,
            webhook_configuration_retry_seconds=60,
        ),
        clock=MutableClock(),
    )
    await scheduler.publish_outbox_batch()
    assert await scheduler.deliver_one()

    async with sessions() as session:
        delivery = await session.scalar(select(WebhookDelivery))
    assert delivery is not None
    assert delivery.status == "retry"
    assert delivery.attempts == 0
    assert delivery.last_error == "webhook_secret_decryption_failed"
    assert delivery.next_attempt_at.replace(tzinfo=UTC) == NOW + timedelta(seconds=60)
    assert http_client.calls == []


async def test_secret_hash_corruption_dead_letters_terminally(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    endpoint_id, _event_id = await seed_endpoint_and_event(
        sessions,
        encryption_key=encryption_key,
    )
    async with sessions.begin() as session:
        endpoint = await session.get(WebhookEndpoint, endpoint_id)
        assert endpoint is not None
        endpoint.secret_hash = "0" * 64
    http_client = RecordingHttpClient()
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=http_client,  # type: ignore[arg-type]
        settings=settings(encryption_key),
        clock=MutableClock(),
    )
    await scheduler.publish_outbox_batch()
    assert await scheduler.deliver_one()

    async with sessions() as session:
        delivery = await session.scalar(select(WebhookDelivery))
    assert delivery is not None
    assert delivery.status == "dead_letter"
    assert delivery.dead_lettered_at is not None
    assert delivery.last_error == "webhook_secret_integrity_failed"
    assert http_client.calls == []


async def test_inactive_endpoint_pauses_queue_until_reactivated(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    endpoint_id, _event_id = await seed_endpoint_and_event(
        sessions,
        encryption_key=encryption_key,
    )
    http_client = RecordingHttpClient(204)
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=http_client,  # type: ignore[arg-type]
        settings=settings(encryption_key),
        clock=MutableClock(),
    )
    await scheduler.publish_outbox_batch()
    async with sessions.begin() as session:
        endpoint = await session.get(WebhookEndpoint, endpoint_id)
        assert endpoint is not None
        endpoint.active = False

    assert not await scheduler.deliver_one()
    async with sessions() as session:
        delivery = await session.scalar(select(WebhookDelivery))
        assert delivery is not None
        delivery_id = delivery.id
        assert delivery.status == "pending"
        assert delivery.attempts == 0

    async with sessions.begin() as session:
        endpoint = await session.get(WebhookEndpoint, endpoint_id)
        assert endpoint is not None
        endpoint.active = True
    assert await scheduler.deliver_one()
    async with sessions() as session:
        delivery = await session.get(WebhookDelivery, delivery_id)
    assert delivery is not None
    assert delivery.status == "delivered"


async def test_poison_payload_dead_letters_without_blocking_later_delivery(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    endpoint_id, _event_id = await seed_endpoint_and_event(
        sessions,
        encryption_key=encryption_key,
    )
    http_client = RecordingHttpClient(204)
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=http_client,  # type: ignore[arg-type]
        settings=settings(encryption_key),
        clock=MutableClock(),
    )
    await scheduler.publish_outbox_batch()
    poison_id = uuid.UUID(int=1)
    healthy_id = uuid.UUID(int=2)
    async with sessions.begin() as session:
        poison = await session.scalar(select(WebhookDelivery))
        assert poison is not None
        poison.id = poison_id
        poison.payload = {"too_large": 10**100}
        session.add(
            WebhookDelivery(
                id=healthy_id,
                tenant_id=poison.tenant_id,
                endpoint_id=endpoint_id,
                event_type="job.completed.v1",
                payload={"job_id": "healthy"},
                status="pending",
                attempts=0,
                next_attempt_at=NOW,
            )
        )

    assert await scheduler.deliver_batch() == 2
    async with sessions() as session:
        poison = await session.get(WebhookDelivery, poison_id)
        healthy = await session.get(WebhookDelivery, healthy_id)
    assert poison is not None
    assert poison.status == "dead_letter"
    assert poison.last_error == "webhook_payload_not_serializable"
    assert healthy is not None
    assert healthy.status == "delivered"
    assert len(http_client.calls) == 1


async def test_total_attempt_timeout_is_retryable_and_bounded(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    await seed_endpoint_and_event(sessions, encryption_key=encryption_key)
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=HangingHttpClient(),  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            webhook_attempt_timeout_seconds=0.01,
        ),
        clock=MutableClock(),
        random_source=lambda: 0.5,
    )
    await scheduler.publish_outbox_batch()

    assert await asyncio.wait_for(scheduler.deliver_one(), timeout=0.5)
    async with sessions() as session:
        delivery = await session.scalar(select(WebhookDelivery))
    assert delivery is not None
    assert delivery.status == "retry"
    assert delivery.last_error == "webhook_attempt_timeout"


async def test_retention_cleanup_deletes_only_expired_terminal_rows(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    endpoint_id, event_id = await seed_endpoint_and_event(
        sessions,
        encryption_key=encryption_key,
    )
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(),  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            webhook_delivery_retention_days=30,
            outbox_retention_days=7,
        ),
        clock=MutableClock(),
    )
    await scheduler.publish_outbox_batch()
    recent_id = uuid.uuid4()
    old_job_event_id = uuid.uuid4()
    recent_job_event_id = uuid.uuid4()
    expired_idempotency_id = uuid.uuid4()
    recent_idempotency_id = uuid.uuid4()
    retained_dispatch_dead_letter_id = uuid.uuid4()
    expired_dispatch_dead_letter_id = uuid.uuid4()
    job_id, _dispatch_event_id = await seed_dispatch(sessions)
    async with sessions.begin() as session:
        old_delivery = await session.scalar(select(WebhookDelivery))
        event = await session.get(OutboxEvent, event_id)
        job = await session.get(ProcessingJob, job_id)
        assert old_delivery is not None and event is not None and job is not None
        old_delivery.status = "delivered"
        old_delivery.delivered_at = NOW - timedelta(days=31)
        event.published_at = NOW - timedelta(days=8)
        session.add(
            WebhookDelivery(
                id=recent_id,
                tenant_id=old_delivery.tenant_id,
                endpoint_id=endpoint_id,
                event_type="job.completed.v1",
                payload={"job_id": "recent"},
                status="delivered",
                attempts=1,
                next_attempt_at=NOW,
                delivered_at=NOW - timedelta(days=1),
            )
        )
        session.add_all(
            [
                JobEvent(
                    id=old_job_event_id,
                    tenant_id=job.tenant_id,
                    job_id=job_id,
                    sequence=1,
                    event_type="job.stage.started.v1",
                    payload={"stage": "old"},
                    occurred_at=NOW - timedelta(days=8),
                ),
                JobEvent(
                    id=recent_job_event_id,
                    tenant_id=job.tenant_id,
                    job_id=job_id,
                    sequence=2,
                    event_type="job.stage.started.v1",
                    payload={"stage": "recent"},
                    occurred_at=NOW - timedelta(days=1),
                ),
                OutboxEvent(
                    id=retained_dispatch_dead_letter_id,
                    tenant_id=event.tenant_id,
                    aggregate_type="job",
                    aggregate_id=uuid.uuid4(),
                    event_type="job.dispatch.requested.v1",
                    payload={"job_id": "retained"},
                    available_at=NOW - timedelta(days=8),
                    dead_lettered_at=NOW - timedelta(days=8),
                ),
                OutboxEvent(
                    id=expired_dispatch_dead_letter_id,
                    tenant_id=event.tenant_id,
                    aggregate_type="job",
                    aggregate_id=uuid.uuid4(),
                    event_type="job.dispatch.requested.v1",
                    payload={"job_id": "expired"},
                    available_at=NOW - timedelta(days=31),
                    dead_lettered_at=NOW - timedelta(days=31),
                ),
                IdempotencyRecord(
                    id=expired_idempotency_id,
                    tenant_id=event.tenant_id,
                    endpoint="POST:/v1/projects",
                    idempotency_key="expired",
                    request_hash="a" * 64,
                    response_status=201,
                    response_body={"id": "expired"},
                    state="completed",
                    expires_at=NOW - timedelta(seconds=1),
                ),
                IdempotencyRecord(
                    id=recent_idempotency_id,
                    tenant_id=event.tenant_id,
                    endpoint="POST:/v1/projects",
                    idempotency_key="recent",
                    request_hash="b" * 64,
                    response_status=201,
                    response_body={"id": "recent"},
                    state="completed",
                    expires_at=NOW + timedelta(days=1),
                ),
            ]
        )

    assert await scheduler.cleanup_retained_rows() == 5
    async with sessions() as session:
        remaining = await session.get(WebhookDelivery, recent_id)
        expired_event = await session.get(OutboxEvent, event_id)
        retained_dispatch_dead_letter = await session.get(
            OutboxEvent,
            retained_dispatch_dead_letter_id,
        )
        expired_dispatch_dead_letter = await session.get(
            OutboxEvent,
            expired_dispatch_dead_letter_id,
        )
        old_job_event = await session.get(JobEvent, old_job_event_id)
        recent_job_event = await session.get(JobEvent, recent_job_event_id)
        expired_idempotency = await session.get(
            IdempotencyRecord,
            expired_idempotency_id,
        )
        recent_idempotency = await session.get(
            IdempotencyRecord,
            recent_idempotency_id,
        )
    assert remaining is not None
    assert expired_event is None
    assert retained_dispatch_dead_letter is not None
    assert expired_dispatch_dead_letter is None
    assert old_job_event is None
    assert recent_job_event is not None
    assert expired_idempotency is None
    assert recent_idempotency is not None


async def test_graceful_stop_wakes_idle_pollers(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    scheduler = DurableScheduler(
        sessions=sessions,
        http_client=RecordingHttpClient(),  # type: ignore[arg-type]
        settings=settings(
            encryption_key,
            scheduler_poll_interval_seconds=30,
        ),
    )
    task = asyncio.create_task(scheduler.run())
    await asyncio.sleep(0)
    scheduler.request_stop()

    await asyncio.wait_for(task, timeout=1)
    assert scheduler.stopping
