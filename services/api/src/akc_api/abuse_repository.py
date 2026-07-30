"""Transactional repositories for free-tier cost and duplicate controls."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.free_tier import (
    FreeTierCaps,
    FreeUsageDelta,
    FreeUsageSnapshot,
    apply_free_usage,
    canonical_source_sha256,
    is_free_plan,
    utc_usage_date,
)
from akc_api.models import (
    FreeDailyUsage,
    FreeProcessedSource,
    FreeUsageReservation,
)


class DuplicateFreeSource(RuntimeError):
    """A free tenant already consumed processing for this source digest."""

    def __init__(self, *, existing_document_id: uuid.UUID) -> None:
        super().__init__("source digest was already processed by this free tenant")
        self.existing_document_id = existing_document_id


class FreeUsageIdempotencyConflict(RuntimeError):
    """An operation key was reused for a different usage delta."""


@dataclass(frozen=True, slots=True)
class FreeUsageReservationResult:
    snapshot: FreeUsageSnapshot
    created: bool


def _insert_for_dialect(session: AsyncSession, model: type[object]) -> Any:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql_insert(model)
    if dialect == "sqlite":
        return sqlite_insert(model)
    raise RuntimeError("unsupported free-tier accounting database")


def _same_delta(row: FreeUsageReservation, delta: FreeUsageDelta) -> bool:
    return (
        row.file_count == delta.files
        and row.page_count == delta.pages
        and Decimal(row.gpu_cost_usd) == delta.gpu_cost_usd
    )


async def reserve_free_usage(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    plan_code: str,
    operation_key: str,
    delta: FreeUsageDelta,
    caps: FreeTierCaps,
    now: datetime | None = None,
) -> FreeUsageReservationResult | None:
    """Atomically reserve a free-plan allowance exactly once per operation."""

    if not is_free_plan(plan_code):
        return None
    if not operation_key or len(operation_key) > 200:
        raise ValueError("invalid free-tier operation key")
    usage_day = utc_usage_date(now)
    existing = await session.scalar(
        select(FreeUsageReservation).where(
            FreeUsageReservation.tenant_id == tenant_id,
            FreeUsageReservation.operation_key == operation_key,
        )
    )
    if existing is not None:
        if not _same_delta(existing, delta):
            raise FreeUsageIdempotencyConflict
        usage = await session.get(FreeDailyUsage, (tenant_id, existing.usage_date))
        if usage is None:
            raise RuntimeError("free-tier usage reservation is orphaned")
        return FreeUsageReservationResult(
            snapshot=FreeUsageSnapshot(
                usage_date=usage.usage_date,
                files=usage.file_count,
                pages=usage.page_count,
                gpu_cost_usd=Decimal(usage.gpu_cost_usd),
            ),
            created=False,
        )

    insert_statement = _insert_for_dialect(session, FreeDailyUsage).values(
        tenant_id=tenant_id,
        usage_date=usage_day,
        file_count=0,
        page_count=0,
        gpu_cost_usd=Decimal("0"),
    )
    await session.execute(
        insert_statement.on_conflict_do_nothing(
            index_elements=["tenant_id", "usage_date"]
        )
    )
    usage = await session.scalar(
        select(FreeDailyUsage)
        .where(
            FreeDailyUsage.tenant_id == tenant_id,
            FreeDailyUsage.usage_date == usage_day,
        )
        .with_for_update()
    )
    if usage is None:
        raise RuntimeError("failed to initialize free-tier usage row")

    # The daily row serializes concurrent first-use requests. Re-check the
    # idempotency key only after acquiring that lock.
    existing = await session.scalar(
        select(FreeUsageReservation).where(
            FreeUsageReservation.tenant_id == tenant_id,
            FreeUsageReservation.operation_key == operation_key,
        )
    )
    if existing is not None:
        if not _same_delta(existing, delta):
            raise FreeUsageIdempotencyConflict
        return FreeUsageReservationResult(
            snapshot=FreeUsageSnapshot(
                usage_date=usage.usage_date,
                files=usage.file_count,
                pages=usage.page_count,
                gpu_cost_usd=Decimal(usage.gpu_cost_usd),
            ),
            created=False,
        )

    updated = apply_free_usage(
        current=FreeUsageSnapshot(
            usage_date=usage.usage_date,
            files=usage.file_count,
            pages=usage.page_count,
            gpu_cost_usd=Decimal(usage.gpu_cost_usd),
        ),
        delta=delta,
        caps=caps,
        now=now,
    )
    usage.file_count = updated.files
    usage.page_count = updated.pages
    usage.gpu_cost_usd = updated.gpu_cost_usd
    session.add(
        FreeUsageReservation(
            tenant_id=tenant_id,
            usage_date=usage_day,
            operation_key=operation_key,
            file_count=delta.files,
            page_count=delta.pages,
            gpu_cost_usd=delta.gpu_cost_usd,
        )
    )
    await session.flush()
    return FreeUsageReservationResult(snapshot=updated, created=True)


async def free_source_claim(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    plan_code: str,
    sha256: str,
    document_id: uuid.UUID,
    source_file_id: uuid.UUID,
) -> bool:
    """Claim a digest atomically; return False for an idempotent same document."""

    if not is_free_plan(plan_code):
        return True
    digest = canonical_source_sha256(sha256)
    insert_statement = _insert_for_dialect(session, FreeProcessedSource).values(
        tenant_id=tenant_id,
        sha256=digest,
        document_id=document_id,
        source_file_id=source_file_id,
    )
    await session.execute(
        insert_statement.on_conflict_do_nothing(
            index_elements=["tenant_id", "sha256"]
        )
    )
    existing = await session.get(FreeProcessedSource, (tenant_id, digest))
    if existing is None:
        raise RuntimeError("failed to persist free source claim")
    if existing.document_id != document_id:
        raise DuplicateFreeSource(existing_document_id=existing.document_id)
    return existing.source_file_id == source_file_id


async def existing_free_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    plan_code: str,
    sha256: str,
) -> FreeProcessedSource | None:
    if not is_free_plan(plan_code):
        return None
    return await session.get(
        FreeProcessedSource,
        (tenant_id, canonical_source_sha256(sha256)),
    )


async def lock_current_free_usage_day(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    plan_code: str,
    now: datetime | None = None,
) -> None:
    """Serialize digest finalization for one free tenant and UTC day."""

    if not is_free_plan(plan_code):
        return
    usage_day = utc_usage_date(now)
    row = await session.scalar(
        select(FreeDailyUsage)
        .where(
            FreeDailyUsage.tenant_id == tenant_id,
            FreeDailyUsage.usage_date == usage_day,
        )
        .with_for_update()
    )
    if row is None:
        raise RuntimeError("free-tier upload has no reserved daily usage")
