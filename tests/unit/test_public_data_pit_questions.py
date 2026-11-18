"""Generated point-in-time questions over synthetic vintages.

Synthetic harness, IMPLEMENTED_NOT_PROVEN. It is not the U08 question set: that
needs a temporal retrieval path and a frozen real question set.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from akc_cir.temporal import TemporalTimeline
from akc_source_adapters.public_data.vintage import (
    VintageObservation,
    available_upper_bound,
    to_temporal_facts,
)

SHA = "sha256:" + "c" * 64


def _o(
    source: str,
    series: str,
    period: date,
    vintage: str,
    avail: date | None,
    value: str,
    superseded_on: date | None = None,
) -> VintageObservation:
    return VintageObservation(
        source_id=source,
        series_id=series,
        period_start=period,
        period_end=None,
        value=value,
        unit="u",
        frequency="monthly",
        seasonal_adjustment="SA",
        measure="m",
        geography_id=None,
        geography_level=None,
        geography_vintage=None,
        vintage_id=vintage,
        available_on=avail,
        available_precision="day" if avail else None,
        superseded_on=superseded_on,
        source_uri=f"https://example.test/{source}/{series}",
        raw_sha256=SHA,
        rights_id="rights:synthetic",
    )


def _chain(
    source: str, series: str, period: date, releases: list[date]
) -> list[VintageObservation]:
    out = []
    for i, day in enumerate(releases):
        end = releases[i + 1] - timedelta(days=1) if i + 1 < len(releases) else None
        out.append(_o(source, series, period, f"v{i}", day, f"{series}-{period:%Y%m}-r{i}", end))
    return out


def _fixture() -> tuple[list[VintageObservation], set[str]]:
    observations: list[VintageObservation] = []
    for s in range(3):
        for m in range(8):
            period = date(2019, 1 + m, 1)
            first = date(2019, 2 + m, 15) if m != 3 else date(2020, 2, 10)  # one late first release
            releases = [first, first + timedelta(days=45 + 11 * s), first + timedelta(days=400)]
            observations += _chain("alfred", f"S{s}", period, releases[: 1 + (m + s) % 3])
    for concept in ("Revenues", "Assets"):
        period = date(2020, 1, 1)
        observations += _chain("sec_edgar", concept, period, [date(2020, 5, 1), date(2020, 11, 20)])
    unknown = {_o("eia", f"E{i}", date(2020, 1, 1), "v0", None, "1").logical_id for i in range(5)}
    observations += [_o("eia", f"E{i}", date(2020, 1, 1), "v0", None, "1") for i in range(5)]
    return observations, unknown


def _oracle(observations: list[VintageObservation], lid: str, cutoff: datetime) -> str | None:
    """Latest vintage whose release day has ended everywhere by the cutoff."""
    admissible = [
        o
        for o in observations
        if o.logical_id == lid
        and o.available_on is not None
        and datetime.combine(o.available_on + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        + timedelta(hours=12)
        <= cutoff
    ]
    if not admissible:
        return None
    return max(admissible, key=lambda o: o.available_on or date.min).value


def test_point_in_time_questions_never_leak_and_abstain_when_unknown() -> None:
    observations, unknown = _fixture()
    facts, held = to_temporal_facts(observations)
    facts_all, held_none = to_temporal_facts(observations, include_unrecorded=True)
    assert {h.observation.logical_id for h in held} == unknown and not held_none
    timelines = (TemporalTimeline(facts), TemporalTimeline(facts_all))

    fixed = [
        datetime(2019, 1, 1, tzinfo=UTC),
        datetime(2020, 6, 1, tzinfo=UTC),
        datetime(2022, 1, 1, tzinfo=UTC),
    ]
    ids = sorted({o.logical_id for o in observations})
    questions: set[tuple[str, datetime]] = set()
    for lid in ids:
        cutoffs = list(fixed)
        for o in observations:
            if o.logical_id == lid and o.available_on is not None:
                bound = available_upper_bound(o.available_on)
                cutoffs += [bound - timedelta(seconds=1), bound, bound + timedelta(days=1)]
        questions |= {(lid, c) for c in cutoffs}
    assert len(questions) >= 200, len(questions)

    leaks = wrong = abstained = 0
    for lid, cutoff in sorted(questions):
        expected = _oracle(observations, lid, cutoff)
        for timeline in timelines:
            answer = timeline.as_of(known_at=cutoff, logical_id=lid)
            leaks += sum(1 for f in answer.facts if f.recorded_at is None or f.recorded_at > cutoff)
            if lid in unknown:
                assert answer.facts == (), lid
            got = answer.values[0] if answer.values else None
            if len(answer.values) > 1 or got != expected:
                wrong += 1
            abstained += expected is None
    msg = f"questions={len(questions)} leaks={leaks} wrong={wrong} abstained={abstained}"
    assert leaks == 0 and wrong == 0, msg
    assert abstained > 0, msg
