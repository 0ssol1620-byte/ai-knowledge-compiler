"""Vintage observations of public series, mapped onto strict known-at facts.

A source revision never overwrites the earlier release: each vintage becomes a
`TemporalFact` recorded when it was certainly public and superseded when its
successor was. Availability the source does not state is never estimated, so
such an observation is held (or, on request, left unrecorded, which the strict
`known_at` of `akc_cir.temporal` excludes).

Observation records are source-only: no score, signal, forecast or derived
field exists, by construction.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Literal

from akc_cir.temporal import TemporalFact, TemporalSource

HoldReason = Literal[
    "availability_unknown",
    "vintage_chain_inconsistent",
    "ambiguous_vintage",
    "missing_value",
]

_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
_DAY = timedelta(days=1)


def available_upper_bound(d: date) -> datetime:
    """An instant by which calendar date `d` has ended in every civil time zone.

    Noon UTC on `d + 1`: the latest zone (UTC-12) ends `d` at 12:00 UTC on
    `d + 1`. No timezone database and no assumption about the publisher's zone
    (unverified for every source).
    """
    # ponytail: loses up to ~36 h of precision; replace with the exact release
    # instant once a source's release timestamp and zone are verified from
    # primary docs.
    return datetime.combine(d + _DAY, time(12), tzinfo=UTC)


@dataclass(frozen=True)
class VintageObservation:
    source_id: str
    series_id: str
    period_start: date
    period_end: date | None
    value: str
    unit: str
    frequency: str | None
    seasonal_adjustment: str | None
    measure: str
    geography_id: str | None
    geography_level: str | None
    geography_vintage: str | None
    vintage_id: str
    available_on: date | None
    available_precision: Literal["day"] | None
    superseded_on: date | None
    source_uri: str
    raw_sha256: str
    rights_id: str

    def __post_init__(self) -> None:
        if (self.available_precision is None) != (self.available_on is None):
            raise ValueError(f"{self.logical_id}: available_precision is set iff available_on is")
        if self.available_precision not in (None, "day"):
            raise ValueError(f"{self.logical_id}: unsupported available_precision")
        if not self.source_uri.startswith("https://"):
            raise ValueError(f"{self.logical_id}: source_uri must be https")
        if not _SHA.match(self.raw_sha256):
            raise ValueError(f"{self.logical_id}: raw_sha256 must be 'sha256:' + 64 hex")
        if self.period_end is not None and self.period_end < self.period_start:
            raise ValueError(f"{self.logical_id}: period_end precedes period_start")
        if self.superseded_on is not None:
            if self.available_on is None or self.superseded_on < self.available_on:
                raise ValueError(f"{self.logical_id}: superseded_on needs an earlier available_on")
            if self.superseded_on >= date.max:
                raise ValueError(f"{self.logical_id}: superseded_on is an open-end sentinel")

    @property
    def logical_id(self) -> str:
        return f"{self.source_id}:{self.series_id}:{self.period_start.isoformat()}"


@dataclass(frozen=True)
class HeldObservation:
    observation: VintageObservation
    reason: HoldReason


def _midnight(d: date) -> datetime:
    return datetime.combine(d, time(0), tzinfo=UTC)


def _fact(
    o: VintageObservation, recorded_at: datetime | None, superseded_at: datetime | None
) -> TemporalFact:
    return TemporalFact(
        logical_id=o.logical_id,
        value=o.value,
        valid_from=_midnight(o.period_start),
        # period_end is an inclusive calendar date; valid_to is exclusive.
        valid_to=_midnight(o.period_end + _DAY) if o.period_end is not None else None,
        recorded_at=recorded_at,
        superseded_at=superseded_at,
        temporal_source=TemporalSource.EXPLICIT,
        evidence_id=f"{o.source_uri}#{o.raw_sha256}:{o.vintage_id}",
    )


def to_temporal_facts(
    observations: Iterable[VintageObservation],
    *,
    missing_markers: tuple[str, ...] = (".", ""),
    include_unrecorded: bool = False,
) -> tuple[tuple[TemporalFact, ...], tuple[HeldObservation, ...]]:
    """Map observations to (facts, held). Nothing is dated beyond what the source states.

    A logical id whose vintages disagree on the same day, or whose stated
    `superseded_on` does not meet the next vintage, is held whole: its chain
    cannot be trusted, and a partial chain would claim a value was current
    when it was not.
    """
    by_id: dict[str, list[VintageObservation]] = {}
    for o in observations:
        by_id.setdefault(o.logical_id, []).append(o)

    facts: list[TemporalFact] = []
    held: list[HeldObservation] = []
    for lid in sorted(by_id):
        usable: list[VintageObservation] = []
        ordered = sorted(by_id[lid], key=lambda o: (o.available_on or date.min, o.vintage_id))
        for o in ordered:
            if o.value.strip() in missing_markers:
                held.append(HeldObservation(o, "missing_value"))
            elif o.available_on is None:
                if include_unrecorded:
                    facts.append(_fact(o, None, None))
                else:
                    held.append(HeldObservation(o, "availability_unknown"))
            else:
                usable.append(o)

        by_day: dict[date, list[VintageObservation]] = {}
        for o in usable:
            assert o.available_on is not None
            by_day.setdefault(o.available_on, []).append(o)

        if any(len({o.value for o in day}) > 1 for day in by_day.values()):
            held.extend(HeldObservation(o, "ambiguous_vintage") for o in usable)
            continue
        # Same day, same value: one vintage; the first by vintage_id represents it.
        # Every duplicate's stated superseded_on is still checked: none may be dropped.
        days = sorted(by_day)
        chain = [by_day[d][0] for d in days]
        if any(
            o.superseded_on is not None and o.superseded_on + _DAY != nxt
            for d, nxt in pairwise(days)
            for o in by_day[d]
        ):
            held.extend(HeldObservation(o, "vintage_chain_inconsistent") for o in usable)
            continue
        for i, o in enumerate(chain):
            assert o.available_on is not None
            successor_day: date | None = None
            if i + 1 < len(chain):
                successor_day = chain[i + 1].available_on
            elif o.superseded_on is not None:
                successor_day = o.superseded_on + _DAY
            facts.append(
                _fact(
                    o,
                    available_upper_bound(o.available_on),
                    available_upper_bound(successor_day) if successor_day else None,
                )
            )

    facts.sort(
        key=lambda f: (
            f.logical_id,
            f.recorded_at is None,
            f.recorded_at or datetime.min.replace(tzinfo=UTC),
        )
    )
    return tuple(facts), tuple(held)


def comparability_blockers(a: VintageObservation, b: VintageObservation) -> tuple[str, ...]:
    """Why two observations must not be compared. Empty means comparable.

    A `None` on frequency, seasonal adjustment or geography level is unknown,
    and unknown never counts as equal. Different areas (`geography_id`) are
    what a comparison is for and never block by themselves.
    """
    out: list[str] = []
    if a.measure != b.measure:
        out.append("measure_differs")
    if a.unit != b.unit:
        out.append("unit_differs")
    if a.frequency is None or a.frequency != b.frequency:
        out.append("frequency_differs")
    if a.seasonal_adjustment is None or a.seasonal_adjustment != b.seasonal_adjustment:
        out.append("seasonal_adjustment_differs")
    if a.geography_level is None or a.geography_level != b.geography_level:
        out.append("geography_level_differs")
    if a.geography_vintage is None or b.geography_vintage is None:
        out.append("geography_vintage_unknown")
    elif a.geography_vintage != b.geography_vintage:
        out.append("geography_vintage_differs")
    return tuple(out)
