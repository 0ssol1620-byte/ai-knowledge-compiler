"""Low-cardinality scheduler gauges sourced from durable database state."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from akc_api.models import OutboxEvent, ProcessingJob, WebhookDelivery
from akc_telemetry import (
    set_dead_letter_count,
    set_deletion_oldest_pending,
    set_queue_gauges,
)
from akc_telemetry.metrics import REGISTRY
from prometheus_client import Counter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

DISPATCH_TENANT_BUSY_DEFERRALS = Counter(
    "akc_dispatch_tenant_busy_deferrals_total",
    "Compile dispatch candidates deferred by the cluster-wide tenant semaphore.",
    registry=REGISTRY,
)


def record_dispatch_tenant_busy_deferral() -> None:
    """Record a fairness deferral without any tenant or job label."""

    DISPATCH_TENANT_BUSY_DEFERRALS.inc()


def _age_seconds(value: datetime | None, *, now: datetime) -> float:
    if value is None:
        return 0.0
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return max(0.0, (now - normalized).total_seconds())


async def refresh_scheduler_metrics(
    sessions: async_sessionmaker[AsyncSession],
    *,
    mode: str,
    now: datetime | None = None,
) -> None:
    """Refresh only gauges readable by the mode's restricted database role."""

    if mode not in {"all", "dispatch", "webhook"}:
        raise ValueError("unknown scheduler telemetry mode")
    observed_at = now or datetime.now(UTC)
    async with sessions() as session:
        if mode in {"all", "dispatch"}:
            rows = (
                await session.execute(
                    select(ProcessingJob.status, func.count(ProcessingJob.id))
                    .where(
                        ProcessingJob.status.in_(
                            ("queued", "running", "paused", "waiting_review")
                        )
                    )
                    .group_by(ProcessingJob.status)
                )
            ).all()
            oldest = await session.scalar(
                select(func.min(ProcessingJob.created_at)).where(ProcessingJob.status == "queued")
            )
            set_queue_gauges(
                queue_counts={str(status): int(count) for status, count in rows},
                oldest_queue_age_seconds=_age_seconds(oldest, now=observed_at),
            )
        if mode == "dispatch":
            return

        outbox_dead = await session.scalar(
            select(func.count(OutboxEvent.id)).where(OutboxEvent.dead_lettered_at.is_not(None))
        )
        delivery_dead = await session.scalar(
            select(func.count(WebhookDelivery.id)).where(WebhookDelivery.status == "dead_letter")
        )
        oldest_deletion = await session.scalar(
            select(func.min(OutboxEvent.created_at)).where(
                OutboxEvent.event_type.in_(
                    (
                        "deletion.purge.requested.v1",
                        "deletion.retry.requested.v1",
                    )
                ),
                OutboxEvent.published_at.is_(None),
            )
        )
        set_dead_letter_count(int(outbox_dead or 0) + int(delivery_dead or 0))
        set_deletion_oldest_pending(_age_seconds(oldest_deletion, now=observed_at))


async def run_scheduler_metrics_loop(
    sessions: async_sessionmaker[AsyncSession],
    *,
    mode: str,
    stopping: Callable[[], bool],
    refresh_seconds: float = 5.0,
) -> None:
    """Refresh database-backed gauges until the scheduler begins shutdown."""

    while not stopping():
        try:
            await refresh_scheduler_metrics(sessions, mode=mode)
        except Exception:
            logger.exception("scheduler metrics refresh failed")
        if not stopping():
            await asyncio.sleep(max(1.0, min(30.0, refresh_seconds)))
