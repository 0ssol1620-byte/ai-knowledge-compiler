"""Durable outbox fan-out and webhook retry scheduler."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import logging
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol

from akc_api.models import (
    IdempotencyRecord,
    JobEvent,
    OutboxEvent,
    ProcessingJob,
    WebhookDelivery,
    WebhookEndpoint,
)
from akc_api.providers import KnowledgeProviderSettings
from akc_api.services import credit_entry, emit_event, run_compile_job
from akc_api.storage import ObjectStore
from sqlalchemy import Select, and_, func, or_, select, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from akc_scheduler.settings import SchedulerSettings
from akc_scheduler.telemetry import record_dispatch_tenant_busy_deferral
from akc_scheduler.webhooks import (
    SecretDecryptionError,
    WebhookDeliveryError,
    WebhookHostNotAllowedError,
    WebhookHttpClient,
    WebhookSecretIntegrityError,
    canonical_webhook_body,
    decrypt_webhook_secret,
    verify_secret_hash,
    webhook_headers,
)

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]
RandomSource = Callable[[], float]

_RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429})
_DELIVERY_READY_STATES = ("pending", "retry")
_DISPATCH_EVENT_TYPE = "job.dispatch.requested.v1"
_TERMINAL_JOB_STATES = frozenset({"cancelled", "completed", "failed", "waiting_review"})
_ERROR_LIMIT = 500
_SYSTEM_RANDOM = random.SystemRandom()
_ADVISORY_LOCK_PERSON = b"akc-dsp-lock-v1"
WEBHOOK_EVENT_TYPES = frozenset(
    {
        "export.completed.v1",
        "job.completed.v1",
        "job.failed.v1",
    }
)


class CompileJob(Protocol):
    async def __call__(
        self,
        *,
        session: AsyncSession,
        job_id: uuid.UUID,
        settings: KnowledgeProviderSettings,
        object_store: ObjectStore | None = None,
    ) -> None: ...


class _AdvisoryLease(Protocol):
    async def try_acquire(self, lock_key: int) -> bool: ...

    async def release(self) -> None: ...


@dataclass(frozen=True, slots=True)
class _DispatchAdmission:
    event: OutboxEvent
    job_id: uuid.UUID | None


class _PostgresDispatchLease:
    """Own session advisory locks until the complete dispatch attempt exits."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        connection: AsyncConnection,
    ) -> None:
        self._session = session
        self._connection = connection
        self._held_keys: list[int] = []

    async def try_acquire(self, lock_key: int) -> bool:
        acquired = bool(
            await self._session.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
        )
        if acquired:
            self._held_keys.append(lock_key)
        return acquired

    async def release(self) -> None:
        """Release in reverse order, invalidating the session on any ambiguity."""

        if not self._held_keys:
            return
        try:
            for lock_key in reversed(self._held_keys):
                released = bool(
                    await self._connection.scalar(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": lock_key},
                    )
                )
                if not released:
                    raise RuntimeError("dispatch_advisory_unlock_failed")
            await self._connection.commit()
        except BaseException:
            # Closing the physical PostgreSQL session is the fail-safe release
            # for session advisory locks, including cancellation during cleanup.
            with contextlib.suppress(BaseException):
                await asyncio.shield(self._connection.invalidate())
            raise
        finally:
            self._held_keys.clear()


def utcnow() -> datetime:
    return datetime.now(UTC)


def dispatch_advisory_lock_key(
    kind: Literal["job", "tenant"],
    identifier: uuid.UUID,
) -> int:
    """Derive a deterministic, domain-separated signed PostgreSQL bigint key."""

    if kind not in {"job", "tenant"}:
        raise ValueError("unknown dispatch advisory lock namespace")
    digest = hashlib.blake2b(
        kind.encode("ascii") + b"\x00" + identifier.bytes,
        digest_size=8,
        person=_ADVISORY_LOCK_PERSON,
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def exponential_backoff_seconds(
    attempt: int,
    *,
    base_seconds: float,
    maximum_seconds: float,
    jitter_ratio: float,
    random_value: float | None = None,
) -> float:
    """Calculate capped exponential delay with symmetric proportional jitter."""

    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    if base_seconds <= 0 or maximum_seconds <= 0:
        raise ValueError("backoff durations must be positive")
    if not 0 <= jitter_ratio <= 1:
        raise ValueError("jitter_ratio must be between 0 and 1")
    unit = _SYSTEM_RANDOM.random() if random_value is None else random_value
    if not 0 <= unit <= 1:
        raise ValueError("random_value must be between 0 and 1")
    exponent = min(attempt - 1, 62)
    uncapped = float(base_seconds) * float(2**exponent)
    capped = float(min(maximum_seconds, uncapped))
    jittered = float(capped * (1.0 - jitter_ratio + (2.0 * jitter_ratio * unit)))
    return float(min(maximum_seconds, max(0.0, jittered)))


def outbox_claim_statement(
    *,
    now: datetime,
    batch_size: int,
    dialect_name: str,
) -> Select[tuple[OutboxEvent]]:
    """Build a PostgreSQL SKIP LOCKED claim, omitting it for SQLite."""

    statement = (
        select(OutboxEvent)
        .where(
            OutboxEvent.published_at.is_(None),
            OutboxEvent.available_at <= now,
            OutboxEvent.event_type.in_(WEBHOOK_EVENT_TYPES),
        )
        .order_by(OutboxEvent.available_at, OutboxEvent.created_at, OutboxEvent.id)
        .limit(batch_size)
    )
    if dialect_name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    return statement


def dispatch_claim_statement(
    *,
    now: datetime,
    dialect_name: str,
    candidate_tenants: int = 1,
) -> Select[tuple[OutboxEvent]]:
    """Claim the oldest due dispatch from each tenant in a bounded fair scan."""

    if candidate_tenants < 1:
        raise ValueError("candidate_tenants must be at least 1")
    tenant_rank = func.row_number().over(
        partition_by=OutboxEvent.tenant_id,
        order_by=(
            OutboxEvent.available_at,
            OutboxEvent.created_at,
            OutboxEvent.id,
        ),
    )
    ranked = (
        select(
            OutboxEvent.id.label("event_id"),
            tenant_rank.label("tenant_rank"),
        )
        .where(
            OutboxEvent.published_at.is_(None),
            OutboxEvent.dead_lettered_at.is_(None),
            OutboxEvent.available_at <= now,
            OutboxEvent.event_type == _DISPATCH_EVENT_TYPE,
        )
        .subquery("tenant_dispatch_rank")
    )
    statement = (
        select(OutboxEvent)
        .join(ranked, ranked.c.event_id == OutboxEvent.id)
        .where(ranked.c.tenant_rank == 1)
        .order_by(OutboxEvent.available_at, OutboxEvent.created_at, OutboxEvent.id)
        .limit(candidate_tenants)
    )
    if dialect_name == "postgresql":
        statement = statement.with_for_update(
            of=OutboxEvent,
            skip_locked=True,
        )
    return statement


def delivery_claim_statement(
    *,
    now: datetime,
    dialect_name: str,
) -> Select[tuple[WebhookDelivery]]:
    """Build a single-delivery row claim for one bounded HTTP attempt."""

    statement = (
        select(WebhookDelivery)
        .join(
            WebhookEndpoint,
            and_(
                WebhookEndpoint.id == WebhookDelivery.endpoint_id,
                WebhookEndpoint.tenant_id == WebhookDelivery.tenant_id,
            ),
        )
        .where(
            WebhookDelivery.status.in_(_DELIVERY_READY_STATES),
            WebhookDelivery.next_attempt_at <= now,
            WebhookEndpoint.active.is_(True),
        )
        .order_by(
            WebhookDelivery.next_attempt_at,
            WebhookDelivery.attempts,
            WebhookDelivery.id,
        )
        .limit(1)
    )
    if dialect_name == "postgresql":
        statement = statement.with_for_update(
            of=WebhookDelivery,
            skip_locked=True,
        )
    return statement


def endpoint_accepts_event(endpoint: WebhookEndpoint, event_type: str) -> bool:
    subscriptions = endpoint.event_types or []
    return "*" in subscriptions or event_type in subscriptions


class DurableScheduler:
    """Coordinates short outbox transactions and row-locked HTTP attempts."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        http_client: WebhookHttpClient,
        settings: SchedulerSettings,
        dispatch_engine: AsyncEngine | None = None,
        compile_job: CompileJob = run_compile_job,
        object_store: ObjectStore | None = None,
        clock: Clock = utcnow,
        random_source: RandomSource = _SYSTEM_RANDOM.random,
    ) -> None:
        self._sessions = sessions
        self._http_client = http_client
        self._settings = settings
        session_bind = sessions.kw.get("bind")
        if dispatch_engine is None:
            if not isinstance(session_bind, AsyncEngine):
                raise TypeError("sessions must be bound to an AsyncEngine")
            dispatch_engine = session_bind
        self._dispatch_engine = dispatch_engine
        self._compile_job = compile_job
        self._object_store = object_store
        self._clock = clock
        self._random = random_source
        self._stop_event = asyncio.Event()
        self._sqlite_delivery_lock = asyncio.Lock()
        self._sqlite_outbox_lock = asyncio.Lock()
        self._sqlite_cleanup_lock = asyncio.Lock()
        self._sqlite_dispatch_lock = asyncio.Lock()

    @property
    def stopping(self) -> bool:
        return self._stop_event.is_set()

    def request_stop(self) -> None:
        """Ask polling loops to finish their current bounded transaction."""

        self._stop_event.set()

    @staticmethod
    def _dialect_name(session: AsyncSession) -> str:
        return session.get_bind().dialect.name

    def _dispatch_retry_delay(self, attempt: int) -> float:
        return exponential_backoff_seconds(
            attempt,
            base_seconds=self._settings.dispatch_backoff_base_seconds,
            maximum_seconds=self._settings.dispatch_backoff_max_seconds,
            jitter_ratio=self._settings.dispatch_backoff_jitter_ratio,
            random_value=self._random(),
        )

    @staticmethod
    def _dispatch_job_id(event: OutboxEvent) -> uuid.UUID:
        try:
            job_id = uuid.UUID(str(event.payload["job_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("dispatch_payload_invalid_job_id") from exc
        if event.aggregate_type != "job" or event.aggregate_id != job_id:
            raise ValueError("dispatch_payload_aggregate_mismatch")
        return job_id

    def _defer_busy_dispatch_candidate(
        self,
        event: OutboxEvent,
        *,
        now: datetime,
    ) -> None:
        """Park a busy tenant candidate without charging its retry budget."""

        event.available_at = now + timedelta(
            seconds=self._settings.dispatch_tenant_busy_delay_seconds
        )
        record_dispatch_tenant_busy_deferral()

    async def _admit_dispatch_candidate(
        self,
        candidates: list[OutboxEvent],
        *,
        dialect: str,
        lease: _AdvisoryLease | None,
        now: datetime,
    ) -> _DispatchAdmission | None:
        """Select the first candidate whose tenant-wide semaphore is available."""

        for event in candidates:
            try:
                job_id = self._dispatch_job_id(event)
            except ValueError as exc:
                event.attempts += 1
                self._dead_letter_dispatch(event, now=now, error=str(exc))
                return _DispatchAdmission(event=event, job_id=None)

            if dialect == "postgresql":
                if lease is None:
                    raise RuntimeError("postgresql_dispatch_lease_missing")
                tenant_key = dispatch_advisory_lock_key("tenant", event.tenant_id)
                if not await lease.try_acquire(tenant_key):
                    self._defer_busy_dispatch_candidate(event, now=now)
                    continue
                job_key = dispatch_advisory_lock_key("job", job_id)
                if not await lease.try_acquire(job_key):
                    # The tenant key remains owned until the outer attempt's
                    # finally block. This bounded deferral consumes no attempt.
                    self._defer_busy_dispatch_candidate(event, now=now)
                    return None
            return _DispatchAdmission(event=event, job_id=job_id)
        return None

    @staticmethod
    def _dead_letter_dispatch(
        event: OutboxEvent,
        *,
        now: datetime,
        error: str,
    ) -> None:
        event.last_error = error[:_ERROR_LIMIT]
        event.dead_lettered_at = now
        # A dead-lettered internal event is terminal and therefore no longer
        # eligible for the unpublished outbox claim.
        event.published_at = now

    async def _record_dispatch_adapter_failure(
        self,
        *,
        session: AsyncSession,
        event_id: uuid.UUID,
        error: Exception,
    ) -> None:
        now = self._clock()
        async with session.begin():
            statement = select(OutboxEvent).where(OutboxEvent.id == event_id)
            if self._dialect_name(session) == "postgresql":
                statement = statement.with_for_update()
            event = await session.scalar(statement)
            if event is None or event.published_at is not None:
                return
            error_text = f"dispatch_adapter_error:{type(error).__name__}"
            if event.attempts >= self._settings.dispatch_max_attempts:
                try:
                    job_id = self._dispatch_job_id(event)
                except ValueError:
                    job_id = None
                job = (
                    await session.scalar(
                        select(ProcessingJob).where(
                            ProcessingJob.id == job_id,
                            ProcessingJob.tenant_id == event.tenant_id,
                        )
                    )
                    if job_id is not None
                    else None
                )
                if job is not None and job.status in _TERMINAL_JOB_STATES:
                    event.published_at = now
                    event.last_error = None
                    return
                if job is not None:
                    await self._fail_dispatch_job(
                        session=session,
                        event=event,
                        job=job,
                        now=now,
                        error=error_text,
                    )
                self._dead_letter_dispatch(
                    event,
                    now=now,
                    error=error_text,
                )
                return
            event.last_error = error_text[:_ERROR_LIMIT]
            event.available_at = now + timedelta(
                seconds=self._dispatch_retry_delay(max(1, event.attempts))
            )

    async def _fail_dispatch_job(
        self,
        *,
        session: AsyncSession,
        event: OutboxEvent,
        job: ProcessingJob,
        now: datetime,
        error: str,
    ) -> None:
        reserved = Decimal(str(job.cost_estimate.get("reserved", "0")))
        if reserved > 0:
            await credit_entry(
                session,
                tenant_id=job.tenant_id,
                operation_key=f"job:{job.id}:dispatch-terminal-release",
                entry_type="release",
                credits=reserved,
                job_id=job.id,
                metadata={"reason": "dispatch_attempts_exhausted"},
            )
        job.status = "failed"
        job.completed_at = now
        job.error = {
            "code": "DISPATCH_ATTEMPTS_EXHAUSTED",
            "retryable": True,
            "detail": error[:_ERROR_LIMIT],
        }
        await emit_event(
            session,
            job=job,
            event_type="job.failed.v1",
            payload={
                "status": "failed",
                "code": "DISPATCH_ATTEMPTS_EXHAUSTED",
                "retryable": True,
            },
        )
        session.add(
            OutboxEvent(
                tenant_id=job.tenant_id,
                aggregate_type="job",
                aggregate_id=job.id,
                event_type="job.failed.v1",
                payload={
                    "job_id": str(job.id),
                    "code": "DISPATCH_ATTEMPTS_EXHAUSTED",
                },
                available_at=now,
            )
        )

    async def _dispatch_on_connection(self) -> bool:
        async with self._dispatch_engine.connect() as connection:
            dialect = connection.dialect.name
            session = AsyncSession(
                bind=connection,
                expire_on_commit=False,
                autoflush=False,
            )
            event_id: uuid.UUID | None = None
            execute_job = False
            job_id: uuid.UUID | None = None
            tenant_id: uuid.UUID | None = None
            lease: _PostgresDispatchLease | None = None
            if dialect == "postgresql":
                lease = _PostgresDispatchLease(
                    session=session,
                    connection=connection,
                )
            try:
                async with session.begin():
                    now = self._clock()
                    candidates = list(
                        await session.scalars(
                            dispatch_claim_statement(
                                now=now,
                                dialect_name=dialect,
                                candidate_tenants=(self._settings.dispatch_fairness_scan_tenants),
                            )
                        )
                    )
                    if not candidates:
                        return False
                    admission = await self._admit_dispatch_candidate(
                        candidates,
                        dialect=dialect,
                        lease=lease,
                        now=now,
                    )
                    if admission is None:
                        return True
                    event = admission.event
                    job_id = admission.job_id
                    event_id = event.id
                    tenant_id = event.tenant_id
                    if job_id is None:
                        return True

                    job_statement = select(ProcessingJob).where(
                        ProcessingJob.id == job_id,
                        ProcessingJob.tenant_id == tenant_id,
                    )
                    if dialect == "postgresql":
                        job_statement = job_statement.with_for_update()
                    job = await session.scalar(job_statement)
                    if job is None:
                        event.attempts += 1
                        self._dead_letter_dispatch(
                            event,
                            now=now,
                            error="dispatch_job_missing_or_tenant_mismatch",
                        )
                        return True

                    if event.attempts >= self._settings.dispatch_max_attempts:
                        if job.status in _TERMINAL_JOB_STATES:
                            event.published_at = now
                            event.last_error = None
                        else:
                            await self._fail_dispatch_job(
                                session=session,
                                event=event,
                                job=job,
                                now=now,
                                error="dispatch_attempts_exhausted_after_lease",
                            )
                            self._dead_letter_dispatch(
                                event,
                                now=now,
                                error="dispatch_attempts_exhausted_after_lease",
                            )
                        return True

                    event.attempts += 1
                    event.last_error = None
                    event.available_at = now + timedelta(
                        seconds=self._settings.dispatch_lease_seconds
                    )
                    execute_job = job.status not in _TERMINAL_JOB_STATES

                if execute_job:
                    assert job_id is not None
                    try:
                        async with asyncio.timeout(self._settings.dispatch_attempt_timeout_seconds):
                            await self._compile_job(
                                session=session,
                                job_id=job_id,
                                settings=self._settings,
                                object_store=self._object_store,
                            )
                        status_row = (
                            await session.execute(
                                select(
                                    ProcessingJob.status,
                                    ProcessingJob.progress,
                                ).where(
                                    ProcessingJob.id == job_id,
                                    ProcessingJob.tenant_id == tenant_id,
                                )
                            )
                        ).one_or_none()
                        if status_row is None:
                            raise RuntimeError("dispatch_job_missing_after_run")
                        status, progress = status_row
                        waiting_stage = (
                            str(progress.get("stage", "")) if isinstance(progress, dict) else ""
                        )
                        if status == "queued" or (
                            status == "running" and not waiting_stage.endswith("_waiting")
                        ):
                            raise RuntimeError("dispatch_job_not_terminal_or_waiting")
                        await session.rollback()
                    except Exception as exc:
                        if session.in_transaction():
                            await session.rollback()
                        assert event_id is not None
                        await self._record_dispatch_adapter_failure(
                            session=session,
                            event_id=event_id,
                            error=exc,
                        )
                        logger.exception(
                            "compile dispatch adapter failed for event %s",
                            event_id,
                        )
                        return True

                assert event_id is not None
                async with session.begin():
                    statement = select(OutboxEvent).where(OutboxEvent.id == event_id)
                    if dialect == "postgresql":
                        statement = statement.with_for_update()
                    stored_event = await session.scalar(statement)
                    if stored_event is not None and stored_event.published_at is None:
                        stored_event.published_at = self._clock()
                        stored_event.dead_lettered_at = None
                        stored_event.last_error = None
                return True
            finally:
                if session.in_transaction():
                    await session.rollback()
                try:
                    if lease is not None:
                        await lease.release()
                finally:
                    await session.close()

    async def dispatch_one(self) -> bool:
        """Consume one durable internal compile request."""

        if self._dispatch_engine.dialect.name == "sqlite":
            async with self._sqlite_dispatch_lock:
                return await self._dispatch_on_connection()
        return await self._dispatch_on_connection()

    async def dispatch_batch(self) -> int:
        processed = 0
        while processed < self._settings.scheduler_batch_size and not self.stopping:
            if not await self.dispatch_one():
                break
            processed += 1
        return processed

    async def publish_outbox_batch(self) -> int:
        """Atomically fan pending events out to matching webhook endpoints."""

        if not self._settings.webhook_delivery_enabled:
            return 0
        async with self._sessions() as session:
            dialect = self._dialect_name(session)
            lock = self._sqlite_outbox_lock if dialect == "sqlite" else _NullAsyncLock()
            async with lock:
                async with session.begin():
                    events = list(
                        await session.scalars(
                            outbox_claim_statement(
                                now=self._clock(),
                                batch_size=self._settings.scheduler_batch_size,
                                dialect_name=dialect,
                            )
                        )
                    )
                    if not events:
                        return 0

                    tenant_ids = {event.tenant_id for event in events}
                    endpoint_limit = (
                        len(tenant_ids) * self._settings.webhook_max_endpoints_per_tenant
                    )
                    endpoints = list(
                        await session.scalars(
                            select(WebhookEndpoint)
                            .where(
                                WebhookEndpoint.active.is_(True),
                                WebhookEndpoint.tenant_id.in_(tenant_ids),
                            )
                            .order_by(WebhookEndpoint.tenant_id, WebhookEndpoint.id)
                            .limit(endpoint_limit + 1)
                        )
                    )
                    if len(endpoints) > endpoint_limit:
                        raise RuntimeError("webhook_endpoint_quota_drift")
                    endpoints_by_tenant: dict[object, list[WebhookEndpoint]] = {}
                    for endpoint in endpoints:
                        endpoints_by_tenant.setdefault(endpoint.tenant_id, []).append(endpoint)

                    published_at = self._clock()
                    for event in events:
                        for endpoint in endpoints_by_tenant.get(event.tenant_id, []):
                            if endpoint_accepts_event(endpoint, event.event_type):
                                session.add(
                                    WebhookDelivery(
                                        tenant_id=event.tenant_id,
                                        endpoint_id=endpoint.id,
                                        event_type=event.event_type,
                                        payload=copy.deepcopy(event.payload),
                                        status="pending",
                                        attempts=0,
                                        next_attempt_at=published_at,
                                    )
                                )
                        event.attempts += 1
                        event.last_error = None
                        event.published_at = published_at
                return len(events)

    def _retry_delay(self, attempt: int) -> float:
        schedule = self._settings.webhook_retry_schedule
        if schedule:
            index = min(max(0, attempt - 1), len(schedule) - 1)
            return float(schedule[index])
        return exponential_backoff_seconds(
            attempt,
            base_seconds=self._settings.webhook_backoff_base_seconds,
            maximum_seconds=self._settings.webhook_backoff_max_seconds,
            jitter_ratio=self._settings.webhook_backoff_jitter_ratio,
            random_value=self._random(),
        )

    def _record_failure(
        self,
        delivery: WebhookDelivery,
        *,
        error: str,
        retryable: bool,
        status_code: int | None,
        now: datetime,
        retry_after_seconds: float | None = None,
    ) -> None:
        delivery.last_error = error[:_ERROR_LIMIT]
        delivery.last_status_code = status_code
        if not retryable or delivery.attempts >= self._settings.webhook_max_attempts:
            delivery.status = "dead_letter"
            delivery.next_attempt_at = now
            delivery.dead_lettered_at = now
            return
        delivery.status = "retry"
        delivery.dead_lettered_at = None
        delay = self._retry_delay(delivery.attempts)
        if retry_after_seconds is not None:
            delay = max(delay, retry_after_seconds)
        delivery.next_attempt_at = now + timedelta(seconds=delay)

    def _record_configuration_pause(
        self,
        delivery: WebhookDelivery,
        *,
        error: str,
    ) -> None:
        delivery.attempts -= 1
        delivery.last_error = error[:_ERROR_LIMIT]
        delivery.last_status_code = None
        delivery.status = "retry"
        delivery.dead_lettered_at = None
        delivery.next_attempt_at = self._clock() + timedelta(
            seconds=self._settings.webhook_configuration_retry_seconds
        )

    async def _deliver_locked(self, session: AsyncSession) -> bool:
        dialect = self._dialect_name(session)
        now = self._clock()
        delivery = await session.scalar(delivery_claim_statement(now=now, dialect_name=dialect))
        if delivery is None:
            return False

        endpoint = await session.get(WebhookEndpoint, delivery.endpoint_id)
        if endpoint is None or endpoint.tenant_id != delivery.tenant_id:
            delivery.attempts += 1
            self._record_failure(
                delivery,
                error="webhook_endpoint_inactive_or_missing",
                retryable=False,
                status_code=None,
                now=now,
            )
            return True
        if not endpoint.active:
            delivery.status = "pending"
            delivery.dead_lettered_at = None
            delivery.next_attempt_at = now + timedelta(
                seconds=self._settings.webhook_configuration_retry_seconds
            )
            return True
        delivery.attempts += 1

        try:
            body = canonical_webhook_body(
                delivery_id=str(delivery.id),
                event_type=delivery.event_type,
                payload=delivery.payload,
            )
            secret = decrypt_webhook_secret(
                endpoint.encrypted_secret,
                self._settings.webhook_encryption_key,
            )
            if not verify_secret_hash(secret, endpoint.secret_hash):
                raise WebhookSecretIntegrityError
            timestamp = int(now.timestamp())
            async with asyncio.timeout(self._settings.webhook_attempt_timeout_seconds):
                response = await self._http_client.post(
                    endpoint.url,
                    body=body,
                    headers=webhook_headers(
                        body=body,
                        delivery_id=str(delivery.id),
                        event_type=delivery.event_type,
                        attempt=delivery.attempts,
                        secret=secret,
                        timestamp=timestamp,
                    ),
                )
        except (SecretDecryptionError, WebhookHostNotAllowedError) as exc:
            self._record_configuration_pause(delivery, error=str(exc))
            return True
        except TimeoutError:
            self._record_failure(
                delivery,
                error="webhook_attempt_timeout",
                retryable=True,
                status_code=None,
                now=self._clock(),
            )
            return True
        except WebhookDeliveryError as exc:
            self._record_failure(
                delivery,
                error=str(exc),
                retryable=exc.retryable,
                status_code=None,
                now=self._clock(),
            )
            return True
        except Exception as exc:  # defensive adapter boundary
            logger.exception("unexpected webhook delivery adapter failure")
            self._record_failure(
                delivery,
                error=f"unexpected_delivery_error:{type(exc).__name__}",
                retryable=True,
                status_code=None,
                now=self._clock(),
            )
            return True

        status_code = response.status_code
        if 200 <= status_code < 300:
            completed_at = self._clock()
            delivery.status = "delivered"
            delivery.last_status_code = status_code
            delivery.last_error = None
            delivery.delivered_at = completed_at
            delivery.dead_lettered_at = None
        else:
            retryable = status_code in _RETRYABLE_HTTP_STATUSES or status_code >= 500
            self._record_failure(
                delivery,
                error=f"webhook_http_status:{status_code}",
                retryable=retryable,
                status_code=status_code,
                now=self._clock(),
                retry_after_seconds=response.retry_after_seconds,
            )
        return True

    async def deliver_one(self) -> bool:
        """Attempt one due delivery, holding its PostgreSQL row lock."""

        if not self._settings.webhook_delivery_enabled:
            return False
        async with self._sessions() as session:
            dialect = self._dialect_name(session)
            lock = self._sqlite_delivery_lock if dialect == "sqlite" else _NullAsyncLock()
            async with lock, session.begin():
                return await self._deliver_locked(session)

    async def deliver_batch(self) -> int:
        processed = 0
        while processed < self._settings.scheduler_batch_size and not self.stopping:
            if not await self.deliver_one():
                break
            processed += 1
        return processed

    async def cleanup_retained_rows(self) -> int:
        """Delete bounded expired replay records and retained event rows."""

        now = self._clock()
        job_event_cutoff = now - timedelta(days=self._settings.event_retention_days)
        delivery_cutoff = now - timedelta(days=self._settings.webhook_delivery_retention_days)
        outbox_cutoff = now - timedelta(days=self._settings.outbox_retention_days)
        dispatch_dead_cutoff = now - timedelta(
            days=self._settings.dispatch_dead_letter_retention_days
        )
        async with self._sessions() as session:
            dialect = self._dialect_name(session)
            lock = self._sqlite_cleanup_lock if dialect == "sqlite" else _NullAsyncLock()
            async with lock, session.begin():
                delivery_statement = (
                    select(WebhookDelivery)
                    .where(
                        or_(
                            and_(
                                WebhookDelivery.status == "delivered",
                                WebhookDelivery.delivered_at.is_not(None),
                                WebhookDelivery.delivered_at < delivery_cutoff,
                            ),
                            and_(
                                WebhookDelivery.status == "dead_letter",
                                WebhookDelivery.dead_lettered_at.is_not(None),
                                WebhookDelivery.dead_lettered_at < delivery_cutoff,
                            ),
                        )
                    )
                    .order_by(WebhookDelivery.id)
                    .limit(self._settings.scheduler_cleanup_batch_size)
                )
                outbox_statement = (
                    select(OutboxEvent)
                    .where(
                        or_(
                            and_(
                                OutboxEvent.published_at.is_not(None),
                                OutboxEvent.dead_lettered_at.is_(None),
                                OutboxEvent.published_at < outbox_cutoff,
                            ),
                            and_(
                                OutboxEvent.dead_lettered_at.is_not(None),
                                OutboxEvent.dead_lettered_at < dispatch_dead_cutoff,
                            ),
                        )
                    )
                    .order_by(OutboxEvent.id)
                    .limit(self._settings.scheduler_cleanup_batch_size)
                )
                job_event_statement = (
                    select(JobEvent)
                    .where(JobEvent.occurred_at < job_event_cutoff)
                    .order_by(JobEvent.occurred_at, JobEvent.id)
                    .limit(self._settings.scheduler_cleanup_batch_size)
                )
                idempotency_statement = (
                    select(IdempotencyRecord)
                    .where(IdempotencyRecord.expires_at < now)
                    .order_by(IdempotencyRecord.expires_at, IdempotencyRecord.id)
                    .limit(self._settings.scheduler_cleanup_batch_size)
                )
                if dialect == "postgresql":
                    delivery_statement = delivery_statement.with_for_update(
                        of=WebhookDelivery,
                        skip_locked=True,
                    )
                    outbox_statement = outbox_statement.with_for_update(
                        of=OutboxEvent,
                        skip_locked=True,
                    )
                    job_event_statement = job_event_statement.with_for_update(
                        of=JobEvent,
                        skip_locked=True,
                    )
                    idempotency_statement = idempotency_statement.with_for_update(
                        of=IdempotencyRecord,
                        skip_locked=True,
                    )
                deliveries = list(await session.scalars(delivery_statement))
                events = list(await session.scalars(outbox_statement))
                job_events = list(await session.scalars(job_event_statement))
                idempotency_records = list(await session.scalars(idempotency_statement))
                for row in (
                    *deliveries,
                    *events,
                    *job_events,
                    *idempotency_records,
                ):
                    await session.delete(row)
            return len(deliveries) + len(events) + len(job_events) + len(idempotency_records)

    async def run_once(
        self,
        *,
        dispatch_enabled: bool = True,
        webhook_enabled: bool = True,
    ) -> tuple[int, int, int]:
        """Run one bounded dispatch, webhook fan-out, and delivery pass."""

        dispatched = await self.dispatch_batch() if dispatch_enabled else 0
        published = await self.publish_outbox_batch() if webhook_enabled else 0
        delivered = await self.deliver_batch() if webhook_enabled else 0
        return dispatched, published, delivered

    async def _wait_or_stop(self, delay_seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=delay_seconds,
            )

    async def _outbox_loop(self) -> None:
        while not self.stopping:
            try:
                processed = await self.publish_outbox_batch()
            except Exception:
                logger.exception("outbox poll failed")
                processed = 0
            if processed == 0:
                await self._wait_or_stop(self._settings.scheduler_poll_interval_seconds)

    async def _dispatch_loop(self) -> None:
        while not self.stopping:
            try:
                processed = await self.dispatch_batch()
            except Exception:
                logger.exception("internal dispatch poll failed")
                processed = 0
            if processed == 0:
                await self._wait_or_stop(self._settings.scheduler_poll_interval_seconds)

    async def _delivery_loop(self) -> None:
        while not self.stopping:
            try:
                processed = await self.deliver_batch()
            except Exception:
                logger.exception("webhook delivery poll failed")
                processed = 0
            if processed == 0:
                await self._wait_or_stop(self._settings.scheduler_poll_interval_seconds)

    async def _retention_loop(self) -> None:
        while not self.stopping:
            try:
                deleted = await self.cleanup_retained_rows()
                if deleted:
                    logger.info("scheduler retention cleanup deleted %d rows", deleted)
            except Exception:
                logger.exception("scheduler retention cleanup failed")
            await self._wait_or_stop(self._settings.scheduler_retention_interval_seconds)

    async def run(
        self,
        *,
        dispatch_enabled: bool = True,
        webhook_enabled: bool = True,
    ) -> None:
        """Run durable dispatch, webhook, and retention loops until shutdown."""

        if not dispatch_enabled and not webhook_enabled:
            raise ValueError("at least one scheduler loop must be enabled")
        logger.info("durable scheduler started")
        try:
            async with asyncio.TaskGroup() as tasks:
                if dispatch_enabled:
                    tasks.create_task(
                        self._dispatch_loop(),
                        name="compile-dispatch-poller",
                    )
                if webhook_enabled:
                    tasks.create_task(self._outbox_loop(), name="outbox-poller")
                    tasks.create_task(self._delivery_loop(), name="webhook-poller")
                    tasks.create_task(
                        self._retention_loop(),
                        name="retention-cleaner",
                    )
        finally:
            logger.info("durable scheduler stopped")


class _NullAsyncLock:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None
