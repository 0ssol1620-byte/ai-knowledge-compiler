"""Dedicated durable consumer for deletion manifests."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from weakref import WeakKeyDictionary

from akc_api.deletions import (
    DeletionProcessResult,
    DeletionTargetType,
    create_deletion_request,
    process_deletion_request,
)
from akc_api.models import DeletionRequest, Document, OutboxEvent, Project, Tenant, utcnow
from akc_api.storage import ObjectStore
from akc_security.tenant_context import enter_tenant_context
from akc_telemetry import set_deletion_oldest_pending
from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from akc_scheduler.scheduler import exponential_backoff_seconds
from akc_scheduler.settings import SchedulerSettings

logger = logging.getLogger(__name__)
_EVENT_TYPES = (
    "deletion.purge.requested.v1",
    "deletion.retry.requested.v1",
)
_SQLITE_LOCKS: WeakKeyDictionary[AsyncEngine, asyncio.Lock] = WeakKeyDictionary()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def deletion_advisory_lock_key(request_id: uuid.UUID) -> int:
    digest = hashlib.sha256(b"akc-deletion-request-v1\0" + request_id.bytes).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def deletion_claim_statement(
    *,
    now: datetime,
    dialect_name: str,
) -> Select[tuple[OutboxEvent]]:
    statement = (
        select(OutboxEvent)
        .where(
            OutboxEvent.published_at.is_(None),
            OutboxEvent.dead_lettered_at.is_(None),
            OutboxEvent.available_at <= now,
            OutboxEvent.event_type.in_(_EVENT_TYPES),
        )
        .order_by(
            OutboxEvent.available_at,
            OutboxEvent.created_at,
            OutboxEvent.id,
        )
        .limit(1)
    )
    if dialect_name == "postgresql":
        statement = statement.with_for_update(
            of=OutboxEvent,
            skip_locked=True,
        )
    return statement


def retention_claim_statement(
    *,
    now: datetime,
    dialect_name: str,
    limit: int,
) -> Select[tuple[Document, int]]:
    """Claim a bounded oldest-first retention candidate set."""

    statement = (
        select(Document, Tenant.data_retention_days)
        .join(Tenant, Tenant.id == Document.tenant_id)
        .join(
            Project,
            (Project.tenant_id == Document.tenant_id) & (Project.id == Document.project_id),
        )
        .where(
            Document.deletion_requested_at.is_(None),
            Project.deletion_requested_at.is_(None),
        )
        .order_by(Document.created_at, Document.id)
        .limit(limit)
    )
    if dialect_name == "postgresql":
        statement = statement.where(
            text(
                "documents.created_at <= CAST(:retention_now AS timestamptz) "
                "- (tenants.data_retention_days * INTERVAL '1 day')"
            ).bindparams(retention_now=now)
        ).with_for_update(
            of=Document,
            skip_locked=True,
        )
    else:
        statement = statement.where(
            func.julianday(Document.created_at) <= func.julianday(now) - Tenant.data_retention_days
        )
    return statement


class DeletionWorker:
    """Lease and advisory-lock protected cross-tenant deletion consumer."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        object_store: ObjectStore,
        settings: SchedulerSettings,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        if settings.env == "production" and engine.dialect.name != "postgresql":
            raise RuntimeError("production_deletion_requires_postgresql")
        self._engine = engine
        self._sessions = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self._object_store = object_store
        self._settings = settings
        self._clock = clock
        self._stopping = False
        self._sqlite_lock = _SQLITE_LOCKS.setdefault(engine, asyncio.Lock())
        self._next_retention_sweep_at = datetime.min.replace(tzinfo=UTC)

    @property
    def stopping(self) -> bool:
        return self._stopping

    def request_stop(self) -> None:
        self._stopping = True

    def _retry_delay(self, attempt: int) -> float:
        return exponential_backoff_seconds(
            attempt=max(1, attempt),
            base_seconds=self._settings.deletion_backoff_base_seconds,
            maximum_seconds=self._settings.deletion_backoff_max_seconds,
            jitter_ratio=self._settings.deletion_backoff_jitter_ratio,
        )

    async def _resolve_request(
        self,
        session: AsyncSession,
        event: OutboxEvent,
    ) -> DeletionRequest | None:
        raw_request_id = event.payload.get("deletion_request_id")
        if raw_request_id:
            try:
                request_id = uuid.UUID(str(raw_request_id))
            except ValueError:
                return None
            request = await session.scalar(
                select(DeletionRequest).where(
                    DeletionRequest.id == request_id,
                    DeletionRequest.tenant_id == event.tenant_id,
                )
            )
            if request is None or (
                event.aggregate_type == "deletion_request" and event.aggregate_id != request.id
            ):
                return None
            return request

        # Compatibility bridge for the v1 event that carried only the target.
        try:
            target_type = str(event.payload["target_type"])
            target_id = uuid.UUID(str(event.payload["target_id"]))
        except (KeyError, TypeError, ValueError):
            return None
        if target_type not in {"document", "project"}:
            return None
        request, _created = await create_deletion_request(
            session,
            tenant_id=event.tenant_id,
            actor_id=None,
            target_type=cast(DeletionTargetType, target_type),
            target_id=target_id,
            emit_outbox=False,
        )
        expected_manifest_hash = event.payload.get("manifest_hash")
        if expected_manifest_hash and str(expected_manifest_hash) != request.manifest_hash:
            event.last_error = "legacy_deletion_manifest_rebuilt"
        return request

    async def _release_advisory_lock(
        self,
        connection: AsyncConnection,
        lock_key: int,
    ) -> None:
        try:
            released = bool(
                await connection.scalar(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            )
            if not released:
                raise RuntimeError("deletion_advisory_unlock_failed")
        except BaseException:
            await connection.invalidate()
            raise

    async def _record_result(
        self,
        *,
        event_id: uuid.UUID,
        tenant_id: uuid.UUID,
        result: DeletionProcessResult | None,
        error_code: str | None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            await enter_tenant_context(session, tenant_id=tenant_id)
            statement = select(OutboxEvent).where(OutboxEvent.id == event_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                statement = statement.with_for_update()
            event = await session.scalar(statement)
            if event is None or event.published_at is not None:
                return
            now = self._clock()
            if result is not None and result.state == "purged":
                event.published_at = now
                event.dead_lettered_at = None
                event.last_error = None
                return
            if result is not None and result.state == "dead_letter":
                event.dead_lettered_at = now
                event.last_error = "deletion_attempts_exhausted"
                return
            event.last_error = error_code or "deletion_retry_pending"
            event.available_at = now + timedelta(seconds=self._retry_delay(max(1, event.attempts)))

    async def _run_once_on_connection(self) -> bool:
        async with self._engine.connect() as connection:
            event_id: uuid.UUID | None = None
            request_id: uuid.UUID | None = None
            tenant_id: uuid.UUID | None = None
            lock_key: int | None = None
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    autoflush=False,
                ) as session:
                    event = await session.scalar(
                        deletion_claim_statement(
                            now=self._clock(),
                            dialect_name=connection.dialect.name,
                        )
                    )
                    if event is None:
                        await session.commit()
                        return False
                    event_id = event.id
                    # The outbox poll spans tenants; this event does not.
                    await enter_tenant_context(session, tenant_id=event.tenant_id)
                    tenant_id = event.tenant_id
                    request = await self._resolve_request(session, event)
                    if request is None:
                        event.attempts += 1
                        event.last_error = "deletion_event_payload_invalid"
                        event.dead_lettered_at = self._clock()
                        await session.commit()
                        return True
                    request_id = request.id
                    # A request that resolves to a different tenant than the
                    # event that carried it is a spoofed or corrupted payload.
                    await enter_tenant_context(
                        session,
                        tenant_id=tenant_id,
                        expected_tenant_id=request.tenant_id,
                    )
                    if connection.dialect.name == "postgresql":
                        lock_key = deletion_advisory_lock_key(request.id)
                        acquired = bool(
                            await session.scalar(
                                text("SELECT pg_try_advisory_lock(:lock_key)"),
                                {"lock_key": lock_key},
                            )
                        )
                        if not acquired:
                            event.available_at = self._clock() + timedelta(seconds=1)
                            await session.commit()
                            lock_key = None
                            return True
                    event.attempts += 1
                    event.last_error = None
                    event.available_at = self._clock() + timedelta(
                        seconds=self._settings.deletion_lease_seconds
                    )
                    await session.commit()

                assert event_id is not None
                assert request_id is not None
                assert tenant_id is not None
                result: DeletionProcessResult | None = None
                error_code: str | None = None
                try:
                    async with asyncio.timeout(self._settings.deletion_attempt_timeout_seconds):
                        result = await process_deletion_request(
                            self._sessions,
                            object_store=self._object_store,
                            request_id=request_id,
                            lease_seconds=self._settings.deletion_lease_seconds,
                            max_attempts=self._settings.deletion_max_attempts,
                            clock=self._clock,
                        )
                except TimeoutError:
                    error_code = "deletion_attempt_timeout"
                except Exception as exc:
                    error_code = f"deletion_worker_{type(exc).__name__}"[:120]
                    logger.exception("deletion attempt failed")
                await self._record_result(
                    event_id=event_id,
                    tenant_id=tenant_id,
                    result=result,
                    error_code=error_code,
                )
                return True
            finally:
                if lock_key is not None:
                    await self._release_advisory_lock(connection, lock_key)

    async def run_once(self) -> bool:
        if self._engine.dialect.name == "sqlite":
            async with self._sqlite_lock:
                return await self._run_once_on_connection()
        return await self._run_once_on_connection()

    async def _run_retention_sweep_unlocked(self) -> int:
        now = self._clock()
        created = 0
        async with self._sessions() as session, session.begin():
            statement = retention_claim_statement(
                now=now,
                dialect_name=session.bind.dialect.name if session.bind is not None else "",
                limit=self._settings.scheduler_batch_size,
            )
            candidates = list((await session.execute(statement)).all())
            for document, _retention_days in candidates:
                _request, was_created = await create_deletion_request(
                    session,
                    tenant_id=document.tenant_id,
                    actor_id=None,
                    target_type="document",
                    target_id=document.id,
                )
                created += int(was_created)
        return created

    async def run_retention_sweep(self) -> int:
        """Create durable deletion requests for expired active documents."""

        if self._engine.dialect.name == "sqlite":
            async with self._sqlite_lock:
                return await self._run_retention_sweep_unlocked()
        return await self._run_retention_sweep_unlocked()

    async def maybe_run_retention_sweep(self) -> int:
        now = self._clock()
        if now < self._next_retention_sweep_at:
            return 0
        created = await self.run_retention_sweep()
        self._next_retention_sweep_at = now + timedelta(
            seconds=self._settings.deletion_retention_sweep_interval_seconds
        )
        return created

    async def run_batch(self) -> int:
        await self.maybe_run_retention_sweep()
        processed = 0
        while (
            processed < self._settings.scheduler_batch_size
            and not self._stopping
            and await self.run_once()
        ):
            processed += 1
        return processed

    async def refresh_metrics(self) -> None:
        async with self._sessions() as session:
            oldest = await session.scalar(
                select(func.min(DeletionRequest.requested_at)).where(
                    DeletionRequest.state.in_(("requested", "purging", "retry"))
                )
            )
        age = (
            max(0.0, (self._clock() - _aware(oldest)).total_seconds())
            if oldest is not None
            else 0.0
        )
        set_deletion_oldest_pending(age)

    async def run(self) -> None:
        logger.info("durable deletion worker started")
        try:
            while not self._stopping:
                processed = 0
                try:
                    processed = await self.run_batch()
                    await self.refresh_metrics()
                except Exception:
                    logger.exception("deletion poll failed")
                if processed == 0:
                    await asyncio.sleep(self._settings.scheduler_poll_interval_seconds)
        finally:
            logger.info("durable deletion worker stopped")
