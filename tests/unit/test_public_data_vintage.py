"""Vintage observations -> strict known-at facts. Synthetic; IMPLEMENTED_NOT_PROVEN."""

from __future__ import annotations

import dataclasses
import random
from collections import Counter
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from akc_cir.temporal import TemporalFact, TemporalTimeline
from akc_source_adapters.public_data.vintage import (
    HeldObservation,
    VintageObservation,
    available_upper_bound,
    comparability_blockers,
    to_temporal_facts,
)

SHA = "sha256:" + "b" * 64


def obs(
    vintage: str = "v1",
    available_on: date | None = date(2020, 3, 1),
    value: str = "1.10",
    *,
    period_start: date = date(2019, 12, 1),
    period_end: date | None = None,
    superseded_on: date | None = None,
    **over: object,
) -> VintageObservation:
    fields: dict[str, object] = {
        "source_id": "alfred",
        "series_id": "S1",
        "period_start": period_start,
        "period_end": period_end,
        "value": value,
        "unit": "index",
        "frequency": "monthly",
        "seasonal_adjustment": "SA",
        "measure": "level",
        "geography_id": None,
        "geography_level": None,
        "geography_vintage": None,
        "vintage_id": vintage,
        "available_on": available_on,
        "available_precision": "day" if available_on else None,
        "superseded_on": superseded_on,
        "source_uri": "https://example.test/series/S1",
        "raw_sha256": SHA,
        "rights_id": "rights:synthetic",
    }
    fields.update(over)
    return VintageObservation(**fields)  # type: ignore[arg-type]


def test_upper_bound_is_after_the_date_has_ended_everywhere() -> None:
    d = date(2020, 3, 1)
    last_moment_in_utc_minus_12 = datetime(
        2020, 3, 1, 23, 59, 59, tzinfo=timezone(timedelta(hours=-12))
    )
    assert last_moment_in_utc_minus_12 < available_upper_bound(d)


def test_revision_supersedes_without_gap_or_overlap() -> None:
    first, second = date(2020, 3, 1), date(2020, 6, 10)
    facts, held = to_temporal_facts(
        [
            obs("v1", first, "1.0", superseded_on=second - timedelta(days=1)),
            obs("v2", second, "2.0"),
        ]
    )
    assert not held
    timeline = TemporalTimeline(facts)
    start = available_upper_bound(first) - timedelta(hours=2)
    for hour in range(0, 24 * 120):
        moment = start + timedelta(hours=hour)
        values = timeline.as_of(known_at=moment).values
        before = moment < available_upper_bound(first)
        assert len(values) == (0 if before else 1), (moment, values)
    boundary = available_upper_bound(second)
    assert timeline.as_of(known_at=boundary - timedelta(seconds=1)).values == ("1.0",)
    assert timeline.as_of(known_at=boundary).values == ("2.0",)


def test_backdated_revision_is_not_known_before_it_was_published() -> None:  # S21
    facts, _ = to_temporal_facts(
        [obs("v1", date(2020, 1, 20), "1.0"), obs("v2", date(2021, 5, 4), "1.5")]
    )
    lid = facts[0].logical_id
    timeline = TemporalTimeline(facts)
    answer = timeline.as_of(known_at=datetime(2020, 6, 1, tzinfo=UTC), logical_id=lid)
    assert answer.values == ("1.0",)


def test_cutoff_on_the_release_day_does_not_see_the_release() -> None:
    day = date(2020, 3, 1)
    facts, _ = to_temporal_facts([obs("v1", day)])
    timeline = TemporalTimeline(facts)
    assert timeline.as_of(known_at=datetime(2020, 3, 1, 23, 0, tzinfo=UTC)).values == ()
    assert timeline.as_of(known_at=available_upper_bound(day)).values == ("1.10",)


def test_unknown_availability_is_held_not_dated() -> None:
    facts, held = to_temporal_facts([obs("v1", None)])
    assert facts == ()
    assert [h.reason for h in held] == ["availability_unknown"]


def test_unrecorded_current_mode_fact_is_excluded_from_every_known_at_answer() -> None:
    facts, held = to_temporal_facts([obs("v1", None)], include_unrecorded=True)
    assert not held
    assert facts[0].recorded_at is None
    timeline = TemporalTimeline(facts)
    assert timeline.as_of().values == ("1.10",)
    answer = timeline.as_of(known_at=datetime(2099, 1, 1, tzinfo=UTC))
    assert answer.values == ()
    assert answer.excluded_unrecorded == (facts[0].logical_id,)


def test_inconsistent_vintage_chain_is_held() -> None:
    first, second = date(2020, 3, 1), date(2020, 6, 10)
    facts, held = to_temporal_facts(
        [obs("v1", first, "1.0", superseded_on=date(2020, 4, 1)), obs("v2", second, "2.0")]
    )
    assert facts == ()
    assert {h.reason for h in held} == {"vintage_chain_inconsistent"}
    assert len(held) == 2


def test_duplicate_vintage_contradicting_supersession_holds_chain_in_any_id_order() -> None:
    day, nxt = date(2020, 1, 1), date(2020, 6, 1)
    for a, b in (("v1", "v2"), ("v2", "v1")):
        facts, held = to_temporal_facts(
            [
                obs(a, day, "1.0", superseded_on=date(2020, 5, 31)),
                obs(b, day, "1.0", superseded_on=date(2020, 3, 1)),
                obs("v3", nxt, "2.0"),
            ]
        )
        assert facts == ()
        assert {h.reason for h in held} == {"vintage_chain_inconsistent"}
        assert len(held) == 3


def test_same_day_conflicting_vintages_are_held() -> None:
    day = date(2020, 3, 1)
    facts, held = to_temporal_facts([obs("v1", day, "1.0"), obs("v2", day, "2.0")])
    assert facts == ()
    assert {h.reason for h in held} == {"ambiguous_vintage"}


def test_same_day_identical_vintages_are_one_fact() -> None:
    day = date(2020, 3, 1)
    facts, held = to_temporal_facts([obs("v1", day, "1.0"), obs("v2", day, "1.0")])
    assert len(facts) == 1 and not held


def test_stated_supersession_without_a_successor_ends_the_fact() -> None:
    facts, _ = to_temporal_facts([obs("v1", date(2020, 3, 1), superseded_on=date(2020, 4, 30))])
    assert facts[0].superseded_at == available_upper_bound(date(2020, 5, 1))


def test_missing_value_marker_is_held_not_zero() -> None:
    facts, held = to_temporal_facts([obs("v1", value="."), obs("v2", value="")])
    assert facts == ()
    assert {h.reason for h in held} == {"missing_value"}


def test_value_is_kept_as_exact_source_text() -> None:
    facts, _ = to_temporal_facts([obs("v1", value="1.10")])
    assert facts[0].value == "1.10"


def test_period_end_is_inclusive_and_period_is_explicit() -> None:
    facts, _ = to_temporal_facts([obs(period_start=date(2020, 1, 1), period_end=date(2020, 3, 31))])
    f = facts[0]
    assert f.valid_at(datetime(2020, 3, 31, 12, tzinfo=UTC))
    assert not f.valid_at(datetime(2020, 4, 1, tzinfo=UTC))
    assert f.evidence_id == f"https://example.test/series/S1#{SHA}:v1"


def test_observation_has_no_derived_or_signal_fields() -> None:
    assert {f.name for f in dataclasses.fields(VintageObservation)} == {
        "source_id", "series_id", "period_start", "period_end", "value", "unit",
        "frequency", "seasonal_adjustment", "measure", "geography_id",
        "geography_level", "geography_vintage", "vintage_id", "available_on",
        "available_precision", "superseded_on", "source_uri", "raw_sha256", "rights_id",
    }  # fmt: skip


@pytest.mark.parametrize(
    "bad",
    [
        {"available_precision": None},
        {"available_precision": "day", "available_on": None},
        {"source_uri": "http://example.test/x"},
        {"raw_sha256": "b" * 64},
        {"period_end": date(2019, 1, 1)},
        {"superseded_on": date(2020, 1, 1)},
    ],
)
def test_invalid_observation_is_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        obs(**bad)


def _geo(**over: object) -> VintageObservation:
    base: dict[str, Any] = {
        "geography_id": "CBSA-1",
        "geography_level": "cbsa",
        "geography_vintage": "2023",
        "measure": "hpi",
    }
    base.update(over)
    return obs(**base)


def test_area_comparability_same_everything_is_comparable() -> None:
    assert comparability_blockers(_geo(), _geo(geography_id="CBSA-2")) == ()


def test_area_comparability_differing_delineation_vintage() -> None:
    assert comparability_blockers(_geo(), _geo(geography_vintage="2020")) == (
        "geography_vintage_differs",
    )


def test_area_comparability_unknown_vintage() -> None:
    assert comparability_blockers(_geo(geography_vintage=None), _geo()) == (
        "geography_vintage_unknown",
    )
    assert comparability_blockers(_geo(geography_vintage=None), _geo(geography_vintage=None)) == (
        "geography_vintage_unknown",
    )


def test_area_comparability_seasonal_adjustment() -> None:
    assert comparability_blockers(_geo(), _geo(seasonal_adjustment="NSA")) == (
        "seasonal_adjustment_differs",
    )
    assert comparability_blockers(
        _geo(seasonal_adjustment=None), _geo(seasonal_adjustment=None)
    ) == ("seasonal_adjustment_differs",)


def test_area_comparability_measure_unit_frequency_level() -> None:
    assert comparability_blockers(_geo(), _geo(measure="count")) == ("measure_differs",)
    assert comparability_blockers(_geo(), _geo(unit="count")) == ("unit_differs",)
    assert comparability_blockers(_geo(), _geo(frequency="quarterly")) == ("frequency_differs",)
    assert comparability_blockers(_geo(), _geo(geography_level="state")) == (
        "geography_level_differs",
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [(date(2020, 5, 31), date(2020, 3, 1)), (None, date(2020, 5, 31))],
)
def test_last_day_duplicates_contradicting_supersession_are_held_in_any_id_order(
    first: date | None, second: date | None
) -> None:
    day = date(2020, 1, 1)
    for a, b in (("v1", "v2"), ("v2", "v1")):
        facts, held = to_temporal_facts(
            [obs(a, day, "1.0", superseded_on=first), obs(b, day, "1.0", superseded_on=second)]
        )
        assert facts == ()
        assert [h.reason for h in held] == ["vintage_chain_inconsistent"] * 2


def test_same_day_duplicates_disagreeing_on_period_end_are_held() -> None:
    day = date(2020, 3, 1)
    facts, held = to_temporal_facts(
        [obs("v1", day, "1.0"), obs("v2", day, "1.0", period_end=date(2019, 12, 31))]
    )
    assert facts == ()
    assert [h.reason for h in held] == ["ambiguous_vintage"] * 2


def test_unrecorded_vintage_of_a_held_logical_id_is_held_too() -> None:
    day = date(2020, 3, 1)
    facts, held = to_temporal_facts(
        [obs("v0", None, "0.5"), obs("v1", day, "1.0"), obs("v2", day, "2.0")],
        include_unrecorded=True,
    )
    assert facts == ()
    assert sorted(h.reason for h in held) == [
        "ambiguous_vintage",
        "ambiguous_vintage",
        "availability_unknown",
    ]


_END = date.max


@pytest.mark.parametrize(
    "bad",
    [
        {"available_on": _END, "available_precision": "day"},
        {"available_on": _END - timedelta(days=2), "superseded_on": _END - timedelta(days=1)},
        {"period_start": _END - timedelta(days=1), "period_end": _END},
    ],
)
def test_dates_at_the_calendar_end_are_rejected_not_overflowed(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        obs(**bad)
    with pytest.raises(ValueError):
        available_upper_bound(_END)


Answer = tuple[Counter[tuple[object, ...]], Counter[tuple[object, ...]]]


def _canonical(facts: tuple[TemporalFact, ...], held: tuple[HeldObservation, ...]) -> Answer:
    """Everything a known-at answer depends on; provenance labels left out."""
    return (
        Counter(
            (f.logical_id, f.value, f.valid_from, f.valid_to, f.recorded_at, f.superseded_at)
            for f in facts
        ),
        Counter(
            (
                h.reason,
                h.observation.value,
                h.observation.available_on,
                h.observation.superseded_on,
                h.observation.period_end,
            )
            for h in held
        ),
    )


def _random_observations(rng: random.Random) -> list[VintageObservation]:
    near_end = [_END - timedelta(days=n) for n in range(4)]
    days = [date(2020, 1, 1), date(2020, 3, 1), date(2020, 6, 1), *near_end]
    out: list[VintageObservation] = []
    for n in range(rng.randint(1, 6)):
        avail = rng.choice([*days, None])
        later = [d - timedelta(days=1) for d in days if avail and d > avail] + [avail]
        try:
            out.append(
                obs(
                    f"v{n}",
                    avail,
                    rng.choice(["1.0", "2.0", "."]),
                    period_start=date(2019, 12, 1),
                    period_end=rng.choice([None, date(2019, 12, 31), _END]),
                    superseded_on=rng.choice([None, *later]) if avail else None,
                )
            )
        except ValueError:
            continue  # the observation itself is refused; nothing to map
    return out


def test_answers_do_not_depend_on_vintage_id_or_input_order() -> None:
    """Property: relabelling vintages and shuffling the input never changes an answer.

    Same-day duplicates are collapsed onto one representative, so any field the
    representative contributes must agree across them or the id is held; and no
    accepted observation may make the mapping raise.
    """
    for seed in range(3000):
        rng = random.Random(seed)
        observations = _random_observations(rng)
        unrecorded = rng.random() < 0.5
        base = _canonical(*to_temporal_facts(observations, include_unrecorded=unrecorded))
        labels = [o.vintage_id for o in observations]
        rng.shuffle(labels)
        relabelled = [
            dataclasses.replace(o, vintage_id=v) for o, v in zip(observations, labels, strict=True)
        ]
        rng.shuffle(relabelled)
        again = _canonical(*to_temporal_facts(relabelled, include_unrecorded=unrecorded))
        assert again == base, (seed, observations)
