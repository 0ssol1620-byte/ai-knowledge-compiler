"""Two clocks, and the questions that look identical until you separate them.

"What was the policy on 3 January" and "what did the AI believe the policy was
on 3 January" have different answers whenever a fact was backdated, and an agent
that answered from what was recorded then was not wrong. Collapsing the axes
makes a stale answer indistinguishable from a dishonest one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from akc_cir.temporal import (
    AsOfAnswer,
    TemporalFact,
    TemporalPolicy,
    TemporalSource,
    TemporalTimeline,
    replay_context,
)

JAN1 = datetime(2026, 1, 1, tzinfo=UTC)
JAN3 = datetime(2026, 1, 3, tzinfo=UTC)
FEB1 = datetime(2026, 2, 1, tzinfo=UTC)
MAR1 = datetime(2026, 3, 1, tzinfo=UTC)
JUN1 = datetime(2026, 6, 1, tzinfo=UTC)


def _fact(value: str, **kw) -> TemporalFact:
    kw.setdefault("logical_id", "ku_warranty")
    kw.setdefault("temporal_source", TemporalSource.EXPLICIT)
    return TemporalFact(value=value, **kw)


# --------------------------------------------------------------------------
# The two axes, separated
# --------------------------------------------------------------------------


def _backdated_timeline() -> TemporalTimeline:
    """A policy effective 1 January, but not recorded until 1 March."""
    return TemporalTimeline(
        [
            _fact("two years", valid_from=JAN1, valid_to=JUN1, recorded_at=JAN1),
            _fact("three years", valid_from=JAN1, recorded_at=MAR1),
        ]
    )


def test_valid_time_answers_what_reality_was() -> None:
    answer = _backdated_timeline().as_of(valid_at=JAN3)

    assert "three years" in answer.values


def test_system_time_answers_what_the_ai_could_have_known() -> None:
    """On 3 January the March record did not exist yet."""
    answer = _backdated_timeline().as_of(valid_at=JAN3, known_at=JAN3)

    assert answer.values == ("two years",)


def test_the_same_question_later_sees_the_backdated_fact() -> None:
    answer = _backdated_timeline().as_of(valid_at=JAN3, known_at=JUN1)

    assert "three years" in answer.values


def test_a_retracted_fact_disappears_from_later_knowledge() -> None:
    timeline = TemporalTimeline(
        [_fact("two years", valid_from=JAN1, recorded_at=JAN1, superseded_at=MAR1)]
    )

    assert timeline.as_of(known_at=FEB1).values == ("two years",)
    assert timeline.as_of(known_at=JUN1).values == ()


def test_a_fact_that_has_expired_is_not_valid_now() -> None:
    timeline = TemporalTimeline([_fact("two years", valid_from=JAN1, valid_to=FEB1)])

    assert timeline.as_of(valid_at=JAN3).values == ("two years",)
    assert timeline.as_of(valid_at=JUN1).values == ()


def test_a_fact_not_yet_in_force_is_not_valid_yet() -> None:
    timeline = TemporalTimeline([_fact("three years", valid_from=JUN1)])

    assert timeline.as_of(valid_at=JAN3).values == ()


# --------------------------------------------------------------------------
# §8.1 — a date the document never gave is never invented
# --------------------------------------------------------------------------


def test_a_fact_marked_explicit_must_carry_the_date_it_claims() -> None:
    with pytest.raises(ValueError, match="temporal_source is explicit"):
        TemporalFact(
            logical_id="ku_warranty",
            value="two years",
            temporal_source=TemporalSource.EXPLICIT,
        )


def test_an_undated_fact_is_unknown_not_always_true() -> None:
    timeline = TemporalTimeline(
        [TemporalFact(logical_id="ku_warranty", value="two years", recorded_at=JAN1)]
    )

    answer = timeline.as_of(valid_at=JAN3)

    assert answer.values == ()
    assert answer.excluded_unknown == ("ku_warranty",)


def test_including_unknowns_is_a_choice_the_answer_records() -> None:
    """An answer that mixed dated and undated facts silently is not auditable."""
    timeline = TemporalTimeline(
        [TemporalFact(logical_id="ku_warranty", value="two years", recorded_at=JAN1)]
    )

    answer = timeline.as_of(valid_at=JAN3, policy=TemporalPolicy.INCLUDE_UNKNOWN)

    assert answer.values == ("two years",)
    assert answer.included_unknown == ("ku_warranty",)
    assert "include_unknown" in answer.describe()


def test_an_inferred_date_is_usable_but_distinguishable() -> None:
    timeline = TemporalTimeline(
        [
            TemporalFact(
                logical_id="ku_warranty",
                value="two years",
                valid_from=JAN1,
                temporal_source=TemporalSource.INFERRED,
            )
        ]
    )

    answer = timeline.as_of(valid_at=JAN3)

    assert answer.values == ("two years",)
    assert answer.facts[0].temporal_source is TemporalSource.INFERRED


def test_an_inverted_validity_window_is_refused() -> None:
    with pytest.raises(ValueError, match="valid_to precedes valid_from"):
        _fact("two years", valid_from=JUN1, valid_to=JAN1)


def test_a_retraction_before_its_record_is_refused() -> None:
    with pytest.raises(ValueError, match="superseded_at precedes recorded_at"):
        _fact("two years", valid_from=JAN1, recorded_at=JUN1, superseded_at=JAN1)


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------


def test_history_is_ordered_by_when_it_was_recorded() -> None:
    timeline = _backdated_timeline()

    history = timeline.history("ku_warranty")

    assert [fact.value for fact in history] == ["two years", "three years"]


def test_an_undated_record_sorts_last_not_first() -> None:
    """An undated record is not evidence that it came before everything."""
    timeline = TemporalTimeline(
        [
            TemporalFact(logical_id="ku_warranty", value="undated"),
            _fact("two years", valid_from=JAN1, recorded_at=JAN1),
        ]
    )

    assert [fact.value for fact in timeline.history("ku_warranty")] == [
        "two years",
        "undated",
    ]


def test_history_is_scoped_to_one_logical_id() -> None:
    timeline = TemporalTimeline(
        [
            _fact("two years", valid_from=JAN1, recorded_at=JAN1),
            _fact("blue", logical_id="ku_colour", valid_from=JAN1, recorded_at=JAN1),
        ]
    )

    assert len(timeline.history("ku_warranty")) == 1


# --------------------------------------------------------------------------
# §17.1 — temporal contradiction is an integrity category
# --------------------------------------------------------------------------


def test_two_different_values_valid_at_once_is_a_contradiction() -> None:
    timeline = TemporalTimeline(
        [
            _fact("two years", valid_from=JAN1, valid_to=JUN1),
            _fact("three years", valid_from=FEB1, valid_to=JUN1),
        ]
    )

    assert timeline.contradictions("ku_warranty")


def test_windows_that_do_not_overlap_are_not_a_contradiction() -> None:
    timeline = TemporalTimeline(
        [
            _fact("two years", valid_from=JAN1, valid_to=FEB1),
            _fact("three years", valid_from=FEB1, valid_to=JUN1),
        ]
    )

    assert timeline.contradictions("ku_warranty") == ()


def test_a_retracted_fact_does_not_contradict_its_replacement() -> None:
    timeline = TemporalTimeline(
        [
            _fact("two years", valid_from=JAN1, recorded_at=JAN1, superseded_at=MAR1),
            _fact("three years", valid_from=JAN1, recorded_at=MAR1),
        ]
    )

    assert timeline.contradictions("ku_warranty") == ()


def test_two_undated_facts_are_missing_dates_not_a_contradiction() -> None:
    timeline = TemporalTimeline(
        [
            TemporalFact(logical_id="ku_warranty", value="two years"),
            TemporalFact(logical_id="ku_warranty", value="three years"),
        ]
    )

    assert timeline.contradictions("ku_warranty") == ()


def test_the_same_value_twice_is_not_a_contradiction() -> None:
    timeline = TemporalTimeline(
        [
            _fact("two years", valid_from=JAN1, valid_to=JUN1),
            _fact("two years", valid_from=FEB1, valid_to=JUN1),
        ]
    )

    assert timeline.contradictions("ku_warranty") == ()


# --------------------------------------------------------------------------
# §19 — replay reconstructs the input context, never the reasoning
# --------------------------------------------------------------------------


def test_replay_pins_both_axes_to_the_same_moment() -> None:
    answer = replay_context(_backdated_timeline(), at=JAN3)

    assert answer.values == ("two years",)
    assert answer.valid_at == JAN3
    assert answer.known_at == JAN3


def test_replay_can_be_scoped_to_the_units_that_were_retrieved() -> None:
    timeline = TemporalTimeline(
        [
            _fact("two years", valid_from=JAN1, recorded_at=JAN1),
            _fact("blue", logical_id="ku_colour", valid_from=JAN1, recorded_at=JAN1),
        ]
    )

    answer = replay_context(timeline, at=JAN3, logical_ids=["ku_warranty"])

    assert answer.values == ("two years",)


def test_replay_excludes_undated_facts_by_default() -> None:
    """A replay that included them would assert they were served when they may not."""
    timeline = TemporalTimeline(
        [TemporalFact(logical_id="ku_warranty", value="two years", recorded_at=JAN1)]
    )

    answer = replay_context(timeline, at=JAN3)

    assert answer.values == ()
    assert answer.policy is TemporalPolicy.EXCLUDE_UNKNOWN


def test_an_answer_describes_the_bounds_it_was_taken_under() -> None:
    answer = _backdated_timeline().as_of(valid_at=JAN3, known_at=JAN3)

    described = answer.describe()

    assert "valid at" in described
    assert "as known at" in described


def test_an_answer_is_immutable() -> None:
    answer = AsOfAnswer(
        facts=(), valid_at=None, known_at=None, policy=TemporalPolicy.EXCLUDE_UNKNOWN
    )
    with pytest.raises((AttributeError, TypeError)):
        answer.valid_at = JAN1  # type: ignore[misc]
