"""Source freshness dashboard: every connector cursor, scored against its SLO.

The adapters in ``packages/source-adapters`` park each source's resume token in
the ``source_cursors`` table (migration 0039), and the ``updated_at`` of that
row is the last moment a poll *succeeded*. This module turns those rows into
the operator-facing freshness surface: for every cursor, how old it is, which
freshness tier (F0-F3) the source is held to, whether the age already breaches
that tier's service-level objective, and — when polls are failing — when the
next attempt is due.

**Tenancy.** A cursor row is a tenant's operational data like any other, so
migration 0040 gives ``source_cursors`` a ``tenant_id`` plus row-level security
and this module's queries always filter on the authenticated principal's
tenant. The dashboard can never leak another tenant's connectors.

**Tier and breach are computed, not assumed.** ``compute_from_cursor`` derives
the tier from the adapter configuration when one is pinned (git defaults to
F2, Obsidian to F1, mirroring ``PROVIDER_DEFAULT_FRESHNESS``) and otherwise
classifies from the measured age. ``breached`` compares that age against the
tier's SLO with the boundary *inclusive*: an age of exactly the SLO is still
within contract; one second more is a breach. SLO defaults are F0=300s,
F1=3600s (hourly), F2=86400s (daily), F3=604800s (weekly).

**Retry projection is honest about what the row knows.** The cursor row
records the failure streak but not when the streak began, so ``next_retry_at``
is projected as "soonest a healthy poller acting now would retry" — now plus
the current exponential backoff window. It is a planning number for the
dashboard, not a scheduler guarantee.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, DateTime, Integer, String, Uuid, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from akc_api.database import Base, get_session
from akc_api.security import Principal, require_roles

__all__ = [
    "DEFAULT_ADAPTER_TIERS",
    "RETRY_BASE_SECONDS",
    "RETRY_MAX_SECONDS",
    "TIER_SLO_SECONDS",
    "FreshnessTier",
    "SourceCursor",
    "SourceFreshnessStatus",
    "classify_cursor_age",
    "compute_from_cursor",
    "router",
]


class FreshnessTier(StrEnum):
    """Freshness tier F0-F3; ``slo_seconds`` is the tier's promise."""

    F0 = "F0"
    F1 = "F1"
    F2 = "F2"
    F3 = "F3"

    @property
    def slo_seconds(self) -> int:
        return TIER_SLO_SECONDS[self]


#: Service-level objective per tier, in seconds of acceptable cursor age.
#: The boundary is inclusive: an age of exactly the SLO still meets contract.
TIER_SLO_SECONDS: Final[dict[FreshnessTier, int]] = {
    FreshnessTier.F0: 300,
    FreshnessTier.F1: 3_600,
    FreshnessTier.F2: 86_400,
    FreshnessTier.F3: 604_800,
}

#: Default promise per adapter, mirroring PROVIDER_DEFAULT_FRESHNESS in
#: akc_source_adapters. Adapters without an entry are classified by age.
DEFAULT_ADAPTER_TIERS: Final[dict[str, FreshnessTier]] = {
    "git": FreshnessTier.F2,
    "obsidian": FreshnessTier.F1,
}

#: Exponential backoff for failing polls: base * 2^(streak-1), capped.
RETRY_BASE_SECONDS: Final[int] = 60
RETRY_MAX_SECONDS: Final[int] = 3_600

#: Cursor payload keys a revision identity is read from, tightest first. The
#: git adapter parks {"head": <sha>}; polled adapters may not have one.
_REVISION_KEYS: Final[tuple[str, ...]] = ("head", "revision")

#: Backoff exponent cap so a corrupt streak cannot shift into absurdity.
_MAX_STREAK_EXPONENT: Final[int] = 32


def classify_cursor_age(age_seconds: float) -> FreshnessTier:
    """Tightest tier whose SLO still covers ``age_seconds`` (never worse than F3)."""
    for tier in (
        FreshnessTier.F0,
        FreshnessTier.F1,
        FreshnessTier.F2,
        FreshnessTier.F3,
    ):
        if age_seconds <= tier.slo_seconds:
            return tier
    return FreshnessTier.F3


def _as_utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC) if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _row_value(row: Any, name: str) -> Any:
    """Read a field from an ORM object or a plain mapping, whichever arrives."""
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _retry_delay_seconds(failure_streak: int, config: Mapping[str, Any]) -> int:
    base = max(1, int(config.get("retry_base_seconds", RETRY_BASE_SECONDS)))
    cap = int(config.get("retry_max_seconds", RETRY_MAX_SECONDS))
    exponent = min(max(failure_streak - 1, 0), _MAX_STREAK_EXPONENT)
    return int(min(base * 2**exponent, max(cap, base)))


def _revision_from_cursor(cursor_payload: Any) -> str | None:
    if not isinstance(cursor_payload, Mapping):
        return None
    for key in _REVISION_KEYS:
        value = cursor_payload.get(key)
        if isinstance(value, str | int) and str(value):
            return str(value)
    return None


@dataclass(frozen=True, slots=True)
class SourceFreshnessStatus:
    """One source's cursor age scored against its freshness-tier SLO."""

    source_id: str
    adapter: str
    last_revision: str | None
    last_success_at: datetime
    cursor_age_seconds: float
    freshness_tier: FreshnessTier
    slo_target_seconds: int
    breached: bool
    next_retry_at: datetime | None
    failure_streak: int


def compute_from_cursor(
    cursor_row: Any,
    adapter_config: Mapping[str, Any] | None,
    now: datetime,
) -> SourceFreshnessStatus:
    """Project one ``source_cursors`` row onto its freshness status.

    ``cursor_row`` is the ORM model or any mapping/attribute object carrying
    ``source_id``, ``adapter``, ``cursor`` (canonical JSON), ``updated_at`` and
    optionally ``failure_streak``. ``adapter_config`` may pin
    ``freshness_tier`` / ``slo_target_seconds`` per source and tune the retry
    backoff (``retry_base_seconds`` / ``retry_max_seconds``); unpinned sources
    are classified from their measured age. Naive datetimes read as UTC and a
    negative age (clock skew) clamps to zero rather than flattering the score.
    """

    config: Mapping[str, Any] = adapter_config or {}
    updated_at = _row_value(cursor_row, "updated_at")
    if not isinstance(updated_at, datetime):
        msg = "cursor row has no usable updated_at timestamp"
        raise ValueError(msg)
    last_success_at = _as_utc(updated_at)
    horizon = _as_utc(now)

    source_id = str(_row_value(cursor_row, "source_id") or "")
    adapter = str(_row_value(cursor_row, "adapter") or "")
    cursor_age_seconds = max(0.0, (horizon - last_success_at).total_seconds())

    pinned_tier = config.get("freshness_tier")
    if isinstance(pinned_tier, FreshnessTier):
        tier = pinned_tier
    elif isinstance(pinned_tier, str) and pinned_tier in FreshnessTier.__members__:
        tier = FreshnessTier[pinned_tier]
    else:
        tier = classify_cursor_age(cursor_age_seconds)

    slo_override = config.get("slo_target_seconds")
    slo_target_seconds = (
        int(slo_override) if slo_override is not None else TIER_SLO_SECONDS[tier]
    )

    failure_streak = max(0, int(_row_value(cursor_row, "failure_streak") or 0))
    next_retry_at: datetime | None = None
    if failure_streak > 0:
        next_retry_at = horizon + timedelta(
            seconds=_retry_delay_seconds(failure_streak, config)
        )

    return SourceFreshnessStatus(
        source_id=source_id,
        adapter=adapter,
        last_revision=_revision_from_cursor(_row_value(cursor_row, "cursor")),
        last_success_at=last_success_at,
        cursor_age_seconds=cursor_age_seconds,
        freshness_tier=tier,
        slo_target_seconds=slo_target_seconds,
        breached=cursor_age_seconds > slo_target_seconds,
        next_retry_at=next_retry_at,
        failure_streak=failure_streak,
    )


class SourceCursor(Base):
    """One durable resume position per source (migration 0039 + tenancy 0040)."""

    __tablename__ = "source_cursors"

    source_id: Mapped[str] = mapped_column(String(length=255), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    adapter: Mapped[str] = mapped_column(String(length=64), nullable=False)
    cursor: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False
    )
    failure_streak: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


router = APIRouter(prefix="/v1", tags=["sources"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReaderDep = Annotated[
    Principal,
    Depends(require_roles("owner", "admin", "editor", "reviewer", "viewer")),
]


class SourceFreshnessItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    source_id: str
    adapter: str
    last_revision: str | None
    last_success_at: datetime
    cursor_age_seconds: float
    freshness_tier: str
    slo_target_seconds: int
    breached: bool
    next_retry_at: datetime | None
    failure_streak: int


class SourcesFreshnessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    generated_at: datetime
    items: list[SourceFreshnessItem]


def _adapter_config_for(adapter: str) -> dict[str, Any]:
    pinned = DEFAULT_ADAPTER_TIERS.get(adapter)
    return {"freshness_tier": pinned} if pinned is not None else {}


@router.get("/sources/freshness")
async def list_source_freshness(
    principal: ReaderDep,
    session: SessionDep,
) -> SourcesFreshnessResponse:
    """Freshness dashboard for the caller tenant's connector cursors."""

    rows = (
        (
            await session.scalars(
                select(SourceCursor)
                .where(SourceCursor.tenant_id == principal.tenant_id)
                .order_by(SourceCursor.source_id)
            )
        )
        .all()
    )
    generated_at = datetime.now(UTC)
    items = [
        SourceFreshnessItem(
            schema_version="1.0",
            source_id=status.source_id,
            adapter=status.adapter,
            last_revision=status.last_revision,
            last_success_at=status.last_success_at,
            cursor_age_seconds=status.cursor_age_seconds,
            freshness_tier=status.freshness_tier.value,
            slo_target_seconds=status.slo_target_seconds,
            breached=status.breached,
            next_retry_at=status.next_retry_at,
            failure_streak=status.failure_streak,
        )
        for row in rows
        for status in (
            compute_from_cursor(row, _adapter_config_for(row.adapter), generated_at),
        )
    ]
    return SourcesFreshnessResponse(generated_at=generated_at, items=items)
