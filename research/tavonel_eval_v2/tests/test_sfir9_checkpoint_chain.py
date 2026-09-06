"""Controls for the SFIR9 segment chain.

The failure this component exists to prevent is a gap that reads as a
measurement. Every refusal below therefore has a matching control proving the
chain is left untouched by it -- a chain that refused and then appended anyway,
or refused and lost its previous state, would produce exactly the receipt the
refusal was meant to avoid.

The verifier is checked against a receipt it did not build, because a receipt
this process produced is linked by construction and re-deriving it from the
builder's own object would prove nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_checkpoint_chain as chain_module  # noqa: E402
import sfir9_protocol as protocol  # noqa: E402
import sfir9_transport as transport  # noqa: E402

PROTOCOL = protocol.Protocol().digest()
ROSTER = "sha256:roster"
SELECTION = "sha256:selection"
STUDY = "SOURCE_FACT_IR_FRESH_HELDOUT_V9"


def _chain(**overrides):
    body = dict(
        study_id=STUDY,
        protocol_digest=PROTOCOL,
        roster_digest=ROSTER,
        selection_digest=SELECTION,
    )
    body.update(overrides)
    return chain_module.SegmentChain(**body)


def _handoff(**overrides):
    body = dict(
        protocol_digest=PROTOCOL,
        roster_digest=ROSTER,
        selection_digest=SELECTION,
        current_root_host_uuid="12345",
        canonical_address="new-org/new-name",
        frontier_digest="sha256:frontier",
        visited_digest="sha256:visited",
        candidate_accumulator_digest="sha256:candidates",
        logical_request_count=10,
        network_hop_count=12,
        provider_charged_count=12,
        provider_remaining=4000,
        provider_reset_epoch=1000,
        previous_segment_digest=chain_module.GENESIS,
        disposition=chain_module.RATE_WINDOW,
    )
    body.update(overrides)
    return transport.TransportHandoff(**body)


def _grow(chain, count, **handoff_overrides):
    """Append `count` well-formed segments, each distinguishable from the others.

    The traversal state varies per segment as well as the counters. Segments that
    differed only in a counter would make "the previous segment" and "the first
    segment" indistinguishable to any control that reads traversal state back.
    """
    for step in range(count):
        body = dict(
            logical_request_count=10 * (step + 1),
            network_hop_count=12 * (step + 1),
            provider_charged_count=12 * (step + 1),
            frontier_digest=f"sha256:frontier-{step}",
            visited_digest=f"sha256:visited-{step}",
            candidate_accumulator_digest=f"sha256:candidates-{step}",
            current_root_host_uuid=str(1000 + step),
            provider_remaining=4000 - step,
            provider_reset_epoch=1000 + step,
        )
        body.update(handoff_overrides)
        chain.append(chain.open_next(_handoff(**body)))
    return chain


# --------------------------------------------------------------- linking


def test_genesis_is_a_fixed_digest_shaped_value():
    """An empty predecessor is indistinguishable from a missing field.

    Every other control compares `head()` against `GENESIS`, which holds whatever
    `GENESIS` is -- including the empty string. The value has to be pinned
    somewhere, and this is that somewhere.
    """
    assert chain_module.GENESIS == "sha256:" + "0" * 64
    assert chain_module.GENESIS


def test_the_first_segment_follows_genesis():
    chain = _chain()
    assert chain.head() == chain_module.GENESIS
    segment = chain.append(chain.open_next(_handoff()))
    assert segment.previous_segment_digest == chain_module.GENESIS
    assert segment.segment_index == 0


def test_each_segment_names_the_one_before_it_by_digest():
    chain = _grow(_chain(), 3)
    for earlier, later in zip(chain.segments, chain.segments[1:], strict=False):
        assert later.previous_segment_digest == earlier.digest()


def test_the_head_moves_with_every_append():
    chain = _chain()
    heads = [chain.head()]
    _grow(chain, 3)
    heads.extend(segment.digest() for segment in chain.segments)
    assert len(set(heads)) == 4


def test_a_skipped_index_refuses():
    chain = _grow(_chain(), 1)
    stray = chain_module.Segment(
        study_id=STUDY,
        segment_index=5,
        handoff=_handoff(logical_request_count=20, network_hop_count=24,
                         provider_charged_count=24),
        previous_segment_digest=chain.head(),
    )
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(stray)
    assert caught.value.code == chain_module.BROKEN_LINK
    assert len(chain.segments) == 1


def test_a_repeated_index_refuses():
    chain = _grow(_chain(), 2)
    replay = chain_module.Segment(
        study_id=STUDY,
        segment_index=1,
        handoff=_handoff(logical_request_count=20, network_hop_count=24,
                         provider_charged_count=24),
        previous_segment_digest=chain.head(),
    )
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(replay)
    assert caught.value.code == chain_module.BROKEN_LINK


def test_a_predecessor_the_chain_does_not_end_with_refuses():
    """Two segments claiming one predecessor are a fork, and a fork has no answer."""
    chain = _grow(_chain(), 2)
    forked = chain_module.Segment(
        study_id=STUDY,
        segment_index=2,
        handoff=_handoff(logical_request_count=30, network_hop_count=36,
                         provider_charged_count=36),
        previous_segment_digest=chain.segments[0].digest(),
    )
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(forked)
    assert caught.value.code == chain_module.BROKEN_LINK
    assert "fork" in str(caught.value)
    assert len(chain.segments) == 2


def test_open_next_does_not_let_the_caller_choose_the_link():
    """The two fields most easily got wrong are not the caller's to supply."""
    chain = _grow(_chain(), 2)
    prepared = chain.open_next(_handoff())
    assert prepared.segment_index == 2
    assert prepared.previous_segment_digest == chain.head()


# ------------------------------------------------------- the three bindings


def test_a_segment_from_another_roster_refuses():
    """The checkpoint-for-the-wrong-roster attack, mechanically."""
    chain = _grow(_chain(), 1)
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(chain.open_next(_handoff(roster_digest="sha256:another-roster")))
    assert caught.value.code == chain_module.WRONG_ROSTER
    assert len(chain.segments) == 1


def test_a_segment_from_another_selection_refuses_even_with_a_matching_roster():
    """One roster can be reached by more than one selection rule."""
    chain = _grow(_chain(), 1)
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(chain.open_next(_handoff(selection_digest="sha256:other")))
    assert caught.value.code == chain_module.WRONG_SELECTION


def test_a_segment_from_another_protocol_refuses():
    chain = _grow(_chain(), 1)
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(chain.open_next(_handoff(protocol_digest="sha256:other")))
    assert caught.value.code == chain_module.WRONG_PROTOCOL


def test_a_segment_from_another_study_refuses():
    chain = _grow(_chain(), 1)
    stray = chain_module.Segment(
        study_id="SOURCE_FACT_IR_FRESH_HELDOUT_V7",
        segment_index=1,
        handoff=_handoff(),
        previous_segment_digest=chain.head(),
    )
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(stray)
    assert caught.value.code == chain_module.WRONG_STUDY


def test_the_three_bindings_are_reported_as_three_refusals():
    """Collapsing them into one code would make a mismatch unattributable."""
    assert len(
        {
            chain_module.WRONG_PROTOCOL,
            chain_module.WRONG_ROSTER,
            chain_module.WRONG_SELECTION,
        }
    ) == 3


def test_the_first_segment_is_bound_too():
    """An empty chain must not be a way past the bindings."""
    chain = _chain()
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(chain.open_next(_handoff(roster_digest="sha256:another")))
    assert caught.value.code == chain_module.WRONG_ROSTER
    assert chain.segments == []


# --------------------------------------------------------------- counters


@pytest.mark.parametrize("counter", chain_module.MONOTONIC_COUNTERS)
def test_a_counter_that_went_backwards_refuses(counter):
    chain = _grow(_chain(), 2)
    regressed = {
        "logical_request_count": 20,
        "network_hop_count": 24,
        "provider_charged_count": 24,
        counter: 1,
    }
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(chain.open_next(_handoff(**regressed)))
    assert caught.value.code == chain_module.COUNTER_REGRESSED
    assert counter in str(caught.value)
    assert len(chain.segments) == 2


def test_the_monotonic_counters_are_the_three_the_contract_names():
    assert set(chain_module.MONOTONIC_COUNTERS) == {
        "logical_request_count",
        "network_hop_count",
        "provider_charged_count",
    }


def test_a_counter_is_compared_against_the_previous_segment_not_the_first():
    """A value above the first segment and below the last is still a regression.

    Comparing against `segments[0]` accepts every one of these, and the earlier
    controls could not tell the difference: their regressed value was below both.
    """
    chain = _grow(_chain(), 3)
    assert chain.segments[0].counter("logical_request_count") == 10
    assert chain.segments[-1].counter("logical_request_count") == 30

    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(
            chain.open_next(
                _handoff(
                    logical_request_count=15,
                    network_hop_count=40,
                    provider_charged_count=40,
                )
            )
        )
    assert caught.value.code == chain_module.COUNTER_REGRESSED
    assert len(chain.segments) == 3


def test_a_counter_that_stayed_still_is_allowed():
    """A segment that closed on a rate limit before spending anything is real."""
    chain = _grow(_chain(), 1)
    same = _handoff(logical_request_count=10, network_hop_count=12,
                    provider_charged_count=12)
    assert chain.append(chain.open_next(same)).segment_index == 1


# ------------------------------------------------------------ dispositions


@pytest.mark.parametrize("disposition", sorted(chain_module.DISPOSITIONS))
def test_every_declared_disposition_is_accepted(disposition):
    chain = _chain()
    assert chain.append(chain.open_next(_handoff(disposition=disposition)))


@pytest.mark.parametrize("disposition", ["DONE", "", "ok", "SEGMENT_CLOSED", None])
def test_an_undeclared_disposition_refuses(disposition):
    """A state nobody declared is a state nothing can interpret afterwards."""
    chain = _chain()
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(chain.open_next(_handoff(disposition=disposition)))
    assert caught.value.code == chain_module.UNKNOWN_DISPOSITION
    assert chain.segments == []


def test_the_declared_dispositions_are_the_four_the_protocol_defines():
    assert {
        "SEGMENT_OPEN",
        "SEGMENT_COMPLETE_RATE_WINDOW",
        "CENSUS_COMPLETE",
        "WORKING_STORAGE_BUDGET_EXHAUSTED",
    } == chain_module.DISPOSITIONS


def test_the_rate_window_disposition_is_the_transport_one():
    """Two spellings of one state would let a segment close under neither."""
    assert chain_module.RATE_WINDOW == transport.SEGMENT_CLOSE_RATE_WINDOW


# ---------------------------------------------------------------- closing


def test_a_completed_census_closes_the_chain():
    chain = _grow(_chain(), 1)
    chain.append(chain.open_next(_handoff(disposition=chain_module.COMPLETE)))
    assert chain.is_closed() is True


def test_appending_after_the_census_finished_refuses():
    chain = _chain()
    chain.append(chain.open_next(_handoff(disposition=chain_module.COMPLETE)))
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(chain.open_next(_handoff()))
    assert caught.value.code == chain_module.CHAIN_CLOSED
    assert len(chain.segments) == 1


def test_a_rate_window_close_does_not_close_the_chain():
    """The distinction the whole design rests on: a boundary is not an end."""
    chain = _grow(_chain(), 2)
    assert chain.is_closed() is False
    assert chain.segments[-1].handoff.disposition == chain_module.RATE_WINDOW


# ---------------------------------------------------------------- resuming


def test_the_resume_input_carries_the_state_the_next_segment_needs():
    chain = _grow(_chain(), 2)
    resume = chain.resume_input()
    for key in (
        "segment_index",
        "previous_segment_digest",
        "protocol_digest",
        "roster_digest",
        "selection_digest",
        "current_root_host_uuid",
        "canonical_address",
        "frontier_digest",
        "visited_digest",
        "candidate_accumulator_digest",
        "logical_request_count",
        "network_hop_count",
        "provider_charged_count",
        "provider_remaining",
        "provider_reset_epoch",
    ):
        assert key in resume


def test_the_resume_input_points_at_the_current_head():
    chain = _grow(_chain(), 2)
    resume = chain.resume_input()
    assert resume["previous_segment_digest"] == chain.head()
    assert resume["segment_index"] == 2


def test_the_resume_input_carries_the_last_segments_state_not_an_earlier_one():
    """Resuming from an earlier segment would re-walk work already paid for."""
    chain = _grow(_chain(), 3)
    resume = chain.resume_input()
    assert resume["frontier_digest"] == "sha256:frontier-2"
    assert resume["visited_digest"] == "sha256:visited-2"
    assert resume["candidate_accumulator_digest"] == "sha256:candidates-2"
    assert resume["current_root_host_uuid"] == "1002"
    assert resume["logical_request_count"] == 30
    assert resume["provider_remaining"] == 3998
    assert resume["provider_reset_epoch"] == 1002


def test_the_resume_input_carries_no_scientific_quantity():
    """The chain knows what was spent and where it stood, not what was found."""
    resume = _grow(_chain(), 1).resume_input()
    transport.require_no_scientific_input(resume, "resume_input")
    assert "candidate_count" not in resume


def test_an_empty_chain_has_nothing_to_resume_from():
    with pytest.raises(chain_module.ChainRefused) as caught:
        _chain().resume_input()
    assert caught.value.code == chain_module.BROKEN_LINK


# --------------------------------------------------------------- verifying


def test_a_well_formed_receipt_verifies():
    receipt = _grow(_chain(), 3).receipt()
    result = chain_module.verify_chain(receipt)
    assert result["links_intact"] is True
    assert result["head_matches"] is True
    assert result["problems"] == []


def test_the_verifier_recomputes_rather_than_trusting_the_recorded_head():
    """A receipt read back from disk was not written by the object checking it."""
    receipt = _grow(_chain(), 2).receipt()
    receipt["chain_head"] = "sha256:" + "f" * 64
    result = chain_module.verify_chain(receipt)
    assert result["head_matches"] is False
    assert result["links_intact"] is False


def test_the_verifier_notices_a_segment_removed_from_the_middle():
    receipt = _grow(_chain(), 3).receipt()
    del receipt["segments"][1]
    result = chain_module.verify_chain(receipt)
    assert result["links_intact"] is False


def test_the_verifier_notices_a_segment_edited_in_place():
    """Editing a segment breaks every link after it, which is the point."""
    receipt = _grow(_chain(), 3).receipt()
    receipt["segments"][0]["handoff"]["provider_charged_count"] = 999
    result = chain_module.verify_chain(receipt)
    assert result["links_intact"] is False


def test_the_verifier_notices_two_segments_swapped():
    receipt = _grow(_chain(), 3).receipt()
    receipt["segments"][1], receipt["segments"][2] = (
        receipt["segments"][2],
        receipt["segments"][1],
    )
    result = chain_module.verify_chain(receipt)
    assert result["links_intact"] is False


def test_the_verifier_notices_an_index_the_links_cannot_catch():
    """A relabelled single segment, with the head recomputed to match.

    Every other tampering control breaks a link or the head, so the index check
    is never the thing that fires. Here it is the only thing left.
    """
    receipt = _grow(_chain(), 1).receipt()
    receipt["segments"][0]["segment_index"] = 5
    receipt["chain_head"] = chain_module._digest(receipt["segments"][0])

    result = chain_module.verify_chain(receipt)
    assert result["head_matches"] is True
    assert result["links_intact"] is False
    assert any("declares index 5" in problem for problem in result["problems"])


def test_an_empty_receipt_verifies_as_an_empty_chain():
    """Nothing is a valid state; it is a different one from a broken chain."""
    result = chain_module.verify_chain({"segments": [], "chain_head": chain_module.GENESIS})
    assert result["links_intact"] is True
    assert result["segment_count"] == 0


# ---------------------------------------------------------------- receipt


def test_the_receipt_carries_each_segment_handoff_in_full():
    """Present is not the same as populated.

    A segment whose serialization dropped the handoff would still link, still
    verify, and still produce a stable head -- because the omission would be
    consistent everywhere. Only reading a value back catches it.
    """
    receipt = _grow(_chain(), 2).receipt()
    first, second = (stored["handoff"] for stored in receipt["segments"])
    assert first["frontier_digest"] == "sha256:frontier-0"
    assert second["frontier_digest"] == "sha256:frontier-1"
    assert first["logical_request_count"] == 10
    assert second["provider_charged_count"] == 24
    assert first["roster_digest"] == ROSTER


def test_the_receipt_names_the_three_bindings():
    receipt = _grow(_chain(), 1).receipt()
    assert receipt["protocol_digest"] == PROTOCOL
    assert receipt["roster_digest"] == ROSTER
    assert receipt["selection_digest"] == SELECTION


def test_the_receipt_reports_every_segments_disposition():
    chain = _grow(_chain(), 2)
    chain.append(
        chain.open_next(
            _handoff(
                disposition=chain_module.COMPLETE,
                logical_request_count=30,
                network_hop_count=36,
                provider_charged_count=36,
            )
        )
    )
    assert chain.receipt()["dispositions"] == [
        chain_module.RATE_WINDOW,
        chain_module.RATE_WINDOW,
        chain_module.COMPLETE,
    ]


def test_the_receipt_says_why_the_predecessor_is_a_digest():
    receipt = _chain().receipt()
    assert "merely stopped" in receipt["why_the_predecessor_is_named_by_digest"]


def test_the_chain_does_not_read_checkpoint_storage():
    """A typed handoff, not a view into another component's database."""
    source = (NS / "tools/sfir9_checkpoint_chain.py").read_text(encoding="utf-8")
    assert "sqlite3" not in source
    assert "import sfir8_checkpoint" not in source
