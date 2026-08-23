"""Freshness tiers F0-F3 and the SLO each tier promises.

Every source is classified into one of four freshness tiers, and every tier
carries a service-level objective: the maximum acceptable lag between a change
happening in the source and the compiler having observed it. The tier is the
contract; the SLO makes it measurable — ``evaluate_freshness`` turns a
timestamp pair into a pass/breach verdict, and ``classify_lag`` names the
tightest tier a given lag still satisfies.

The defaults are starting points for local polling adapters (git checkouts,
Obsidian vaults); operators override per source. What is *not* optional is that
a breach is computed, not assumed: lag is measured against the recorded
``observed_at`` of the last event, so "fresh enough" is always a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Final


class Freshness(Enum):
    """Freshness tier F0-F3; ``slo_seconds`` is the tier's promise."""

    F0 = "F0"
    F1 = "F1"
    F2 = "F2"
    F3 = "F3"

    @property
    def slo_seconds(self) -> int:
        return FRESHNESS_SLO_SECONDS[self]

    @property
    def description(self) -> str:
        return FRESHNESS_DESCRIPTIONS[self]


# The tier tables live below the enum they name: these are real module-level
# values, not annotations, so forward references would not save them.
FRESHNESS_SLO_SECONDS: Final[dict[Freshness, int]] = {
    Freshness.F0: 60,
    Freshness.F1: 3_600,
    Freshness.F2: 86_400,
    Freshness.F3: 604_800,
}

FRESHNESS_DESCRIPTIONS: Final[dict[Freshness, str]] = {
    Freshness.F0: "realtime — observed within a minute",
    Freshness.F1: "hourly — observed within an hour",
    Freshness.F2: "daily — observed within a day",
    Freshness.F3: "archive — eventually, within a week",
}

PROVIDER_DEFAULT_FRESHNESS: Final[dict[str, Freshness]] = {
    "git": Freshness.F2,
    "obsidian": Freshness.F1,
}


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    """Measured lag for one source against one tier's SLO."""

    freshness: Freshness
    lag_seconds: float
    slo_seconds: int
    within_slo: bool
    breach_seconds: float


def _as_utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC) if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def evaluate_freshness(
    freshness: Freshness,
    changed_at: datetime,
    *,
    observed_at: datetime | None = None,
    now: datetime | None = None,
) -> FreshnessReport:
    """Measure lag from ``changed_at`` to observation against the tier's SLO.

    Naive datetimes are read as UTC. A negative lag (observation claimed before
    the change, or clock skew) clamps to zero rather than flattering the score.
    ``observed_at`` defaults to ``changed_at`` itself; ``now`` defaults to the
    current time.
    """
    measured_at = _as_utc(observed_at) if observed_at is not None else _as_utc(changed_at)
    horizon = _as_utc(now) if now is not None else datetime.now(UTC)
    lag = max(0.0, (horizon - measured_at).total_seconds())
    slo = freshness.slo_seconds
    return FreshnessReport(
        freshness=freshness,
        lag_seconds=lag,
        slo_seconds=slo,
        within_slo=lag <= slo,
        breach_seconds=max(0.0, lag - slo),
    )


def classify_lag(lag_seconds: float) -> Freshness:
    """Tightest tier whose SLO still covers ``lag_seconds`` (never worse than F3)."""
    for tier in (Freshness.F0, Freshness.F1, Freshness.F2, Freshness.F3):
        if lag_seconds <= tier.slo_seconds:
            return tier
    return Freshness.F3
