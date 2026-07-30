"""Deterministic free-tier usage policy shared by API transaction boundaries."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from enum import StrEnum

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MONEY_QUANTUM = Decimal("0.000001")


class FreeUsageDimension(StrEnum):
    FILES = "files"
    PAGES = "pages"
    GPU_COST_USD = "gpu_cost_usd"


class FreeTierPolicyError(ValueError):
    """Raised for invalid policy configuration or a malformed usage delta."""


class FreeTierCapExceeded(RuntimeError):
    """Raised before a transaction would cross a daily free-tier cap."""

    def __init__(
        self,
        *,
        dimension: FreeUsageDimension,
        limit: int | Decimal,
        current: int | Decimal,
        requested: int | Decimal,
        retry_after_seconds: int,
    ) -> None:
        super().__init__(f"daily free-tier {dimension.value} cap exceeded")
        self.dimension = dimension
        self.limit = limit
        self.current = current
        self.requested = requested
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class FreeTierCaps:
    files: int
    pages: int
    gpu_cost_usd: Decimal

    def __post_init__(self) -> None:
        if self.files < 1 or self.pages < 1:
            raise FreeTierPolicyError("free file and page caps must be positive")
        _validate_decimal(self.gpu_cost_usd, name="free GPU cost cap", positive=True)


@dataclass(frozen=True, slots=True)
class FreeUsageSnapshot:
    usage_date: date
    files: int = 0
    pages: int = 0
    gpu_cost_usd: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.files < 0 or self.pages < 0:
            raise FreeTierPolicyError("usage counters cannot be negative")
        _validate_decimal(self.gpu_cost_usd, name="GPU usage", positive=False)


@dataclass(frozen=True, slots=True)
class FreeUsageDelta:
    files: int = 0
    pages: int = 0
    gpu_cost_usd: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.files < 0 or self.pages < 0:
            raise FreeTierPolicyError("usage deltas cannot be negative")
        _validate_decimal(self.gpu_cost_usd, name="GPU usage delta", positive=False)
        if self.files == 0 and self.pages == 0 and self.gpu_cost_usd == 0:
            raise FreeTierPolicyError("at least one usage delta must be positive")


def _validate_decimal(value: Decimal, *, name: str, positive: bool) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise FreeTierPolicyError(f"{name} must be a finite decimal")
    if value < 0 or (positive and value <= 0):
        raise FreeTierPolicyError(f"{name} is outside the allowed range")


def utc_usage_date(now: datetime | None = None) -> date:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).date()


def seconds_until_utc_reset(now: datetime | None = None) -> int:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    next_day = datetime.combine(
        current.date() + timedelta(days=1),
        time.min,
        tzinfo=UTC,
    )
    return max(1, math.ceil((next_day - current).total_seconds()))


def apply_free_usage(
    *,
    current: FreeUsageSnapshot,
    delta: FreeUsageDelta,
    caps: FreeTierCaps,
    now: datetime | None = None,
) -> FreeUsageSnapshot:
    """Return reserved usage or raise before any cap is crossed."""

    usage_day = utc_usage_date(now)
    if current.usage_date != usage_day:
        raise FreeTierPolicyError("usage snapshot does not match the current UTC day")
    retry_after = seconds_until_utc_reset(now)

    next_files = current.files + delta.files
    if next_files > caps.files:
        raise FreeTierCapExceeded(
            dimension=FreeUsageDimension.FILES,
            limit=caps.files,
            current=current.files,
            requested=delta.files,
            retry_after_seconds=retry_after,
        )

    next_pages = current.pages + delta.pages
    if next_pages > caps.pages:
        raise FreeTierCapExceeded(
            dimension=FreeUsageDimension.PAGES,
            limit=caps.pages,
            current=current.pages,
            requested=delta.pages,
            retry_after_seconds=retry_after,
        )

    next_gpu_cost = (current.gpu_cost_usd + delta.gpu_cost_usd).quantize(
        _MONEY_QUANTUM,
        rounding=ROUND_CEILING,
    )
    if next_gpu_cost > caps.gpu_cost_usd:
        raise FreeTierCapExceeded(
            dimension=FreeUsageDimension.GPU_COST_USD,
            limit=caps.gpu_cost_usd,
            current=current.gpu_cost_usd,
            requested=delta.gpu_cost_usd,
            retry_after_seconds=retry_after,
        )

    return FreeUsageSnapshot(
        usage_date=current.usage_date,
        files=next_files,
        pages=next_pages,
        gpu_cost_usd=next_gpu_cost,
    )


def estimate_gpu_cost(
    *,
    visual_pages: int,
    per_visual_page_usd: Decimal | str,
) -> Decimal:
    if visual_pages < 0:
        raise FreeTierPolicyError("visual page count cannot be negative")
    try:
        unit_cost = (
            per_visual_page_usd
            if isinstance(per_visual_page_usd, Decimal)
            else Decimal(per_visual_page_usd)
        )
    except InvalidOperation as exc:
        raise FreeTierPolicyError("GPU unit cost must be a decimal") from exc
    _validate_decimal(unit_cost, name="GPU unit cost", positive=False)
    return (unit_cost * visual_pages).quantize(
        _MONEY_QUANTUM,
        rounding=ROUND_CEILING,
    )


def canonical_source_sha256(value: str) -> str:
    canonical = value.strip().casefold()
    if _SHA256_PATTERN.fullmatch(canonical) is None:
        raise FreeTierPolicyError("source digest must be a full SHA-256 hex digest")
    return canonical


def is_free_plan(plan_code: str) -> bool:
    return plan_code.strip().casefold() == "free"


def queue_priority_for_plan(plan_code: str) -> int:
    """Keep free work below every paid/default job without starving the queue."""

    return 1 if is_free_plan(plan_code) else 5
