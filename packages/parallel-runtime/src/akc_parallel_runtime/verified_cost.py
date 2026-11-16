"""Verified $ per accepted page and 1/2/4/8 level comparison.

Cost comes only from provider invoices. A timing- or estimate-derived cost is
never turned into a $/page figure: the level is marked ``receipt_grade=False``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


class VerifiedCostError(ValueError):
    pass


OUTCOMES = frozenset({"ok", "oom", "cancelled", "retry", "failed"})
COST_SOURCES = frozenset({"invoice", "estimate"})


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt_id: str
    started_s: float
    finished_s: float
    busy_gpu_s: float
    outcome: str

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise VerifiedCostError(f"unknown attempt outcome: {self.outcome!r}")
        if self.finished_s < self.started_s or self.busy_gpu_s < 0:
            raise VerifiedCostError("attempt times must be non-negative and ordered")


@dataclass(frozen=True, slots=True)
class CostLine:
    source: str
    usd: float
    billed_gpu_s: float

    def __post_init__(self) -> None:
        if self.source not in COST_SOURCES:
            raise VerifiedCostError(f"unknown cost source: {self.source!r}")
        if self.usd < 0 or self.billed_gpu_s < 0:
            raise VerifiedCostError("cost line values must be non-negative")


@dataclass(frozen=True, slots=True)
class QualityStat:
    critical_errors: int


@dataclass(frozen=True, slots=True)
class LevelAggregate:
    level: int
    accepted_pages: int
    critical_errors: int
    wall_s: float
    billed_gpu_s: float
    busy_gpu_s: float
    utilization: float | None
    pages_per_hour: float | None
    latency_p50_s: float | None
    latency_p95_s: float | None
    latency_p99_s: float | None
    oom_count: int
    cancel_count: int
    retry_count: int
    receipt_grade: bool
    # None when not receipt-grade or nothing was accepted.
    verified_usd_per_accepted_page: float | None
    status: str  # "ok" | "none_accepted" | "not_receipt_grade"


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile; None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q / 100 * len(ordered))) - 1]


def aggregate_level(
    level: int,
    attempts: Sequence[AttemptRecord],
    invoices: Sequence[CostLine],
    accepted_pages: int,
    quality: QualityStat,
) -> LevelAggregate:
    if level < 1 or accepted_pages < 0 or quality.critical_errors < 0:
        raise VerifiedCostError("level must be >= 1 and counts non-negative")
    wall = (
        max(a.finished_s for a in attempts) - min(a.started_s for a in attempts)
        if attempts
        else 0.0
    )
    busy = sum(a.busy_gpu_s for a in attempts)
    billed = sum(c.billed_gpu_s for c in invoices)
    latencies = [a.finished_s - a.started_s for a in attempts]
    grade = bool(invoices) and all(c.source == "invoice" for c in invoices)
    usd = sum(c.usd for c in invoices)
    if accepted_pages == 0:
        status, per_page = "none_accepted", None
    elif not grade:
        status, per_page = "not_receipt_grade", None
    else:
        status, per_page = "ok", usd / accepted_pages
    return LevelAggregate(
        level=level,
        accepted_pages=accepted_pages,
        critical_errors=quality.critical_errors,
        wall_s=wall,
        billed_gpu_s=billed,
        busy_gpu_s=busy,
        utilization=busy / billed if billed > 0 else None,
        pages_per_hour=accepted_pages / (wall / 3600) if wall > 0 else None,
        latency_p50_s=percentile(latencies, 50),
        latency_p95_s=percentile(latencies, 95),
        latency_p99_s=percentile(latencies, 99),
        oom_count=sum(a.outcome == "oom" for a in attempts),
        cancel_count=sum(a.outcome == "cancelled" for a in attempts),
        retry_count=sum(a.outcome == "retry" for a in attempts),
        receipt_grade=grade,
        verified_usd_per_accepted_page=per_page,
        status=status,
    )


@dataclass(frozen=True, slots=True)
class LevelComparison:
    status: str  # "matched" | "quality_not_matched" | "none_accepted"
    # level -> wall-time speed-up vs the lowest level; empty unless matched.
    speedup: dict[int, float]


def compare_levels(levels: Sequence[LevelAggregate]) -> LevelComparison:
    if len(levels) < 2:
        raise VerifiedCostError("need at least two levels to compare")
    first = levels[0]
    if any(
        lv.accepted_pages != first.accepted_pages or lv.critical_errors != first.critical_errors
        for lv in levels
    ):
        return LevelComparison("quality_not_matched", {})
    if first.accepted_pages == 0:
        return LevelComparison("none_accepted", {})
    base = min(levels, key=lambda lv: lv.level)
    if any(lv.wall_s <= 0 for lv in levels):
        raise VerifiedCostError("every level needs a positive wall time")
    return LevelComparison("matched", {lv.level: base.wall_s / lv.wall_s for lv in levels})
