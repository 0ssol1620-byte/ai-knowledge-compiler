"""Contracts for `MatchingPolicy` and the candidate index behind `BLOCKED`.

These are contracts, not the evidence. The equivalence claim itself is measured
in `research/experiments/H1-E-IDENTITY-SCALABILITY-01/`; what is enforced here
is that the default has not moved, that the pruning lemma the index rests on is
arithmetically true, and that the index reproduces the candidate set §N15.1
already describes.
"""

from __future__ import annotations

import inspect
import random

import pytest
from akc_cir.identity import (
    _TIE_BAND,
    IDENTITY_SIGNAL_WEIGHTS,
    MERGE_THRESHOLD,
    PRUNED_CANDIDATE_SCORE_CEILING,
    LogicalIdentityResolver,
    LogicalMatch,
    LogicalUnitFingerprint,
    MatchingPolicy,
    _blocked_candidate_columns,
    assign_one_to_one,
    candidate_index_for,
    generate_candidates,
)


def unit(
    logical_id: str,
    section: str,
    ordinal: int,
    text: str,
    *,
    identifier: str = "",
    lineage: str = "src",
) -> LogicalUnitFingerprint:
    return LogicalUnitFingerprint.of(
        logical_id=logical_id,
        document_path=(section, f"para-{ordinal}"),
        anchor=f"anchor-{logical_id}",
        text=text,
        source_lineage=lineage,
        explicit_identifier=identifier,
        previous_anchor=f"anchor-{logical_id}-prev",
        next_anchor=f"anchor-{logical_id}-next",
        geometry_style="body",
    )


def test_the_default_matching_policy_is_still_legacy():
    """Every existing receipt was measured under LEGACY. It does not move here.

    `BLOCKED` is a shadow policy; promoting it is a separate act with its own
    evidence, and a default that drifted would silently invalidate the numbers
    already published against this module.
    """
    signature = inspect.signature(assign_one_to_one)
    assert signature.parameters["policy"].default is MatchingPolicy.LEGACY


def test_the_pruning_ceiling_is_what_the_weights_actually_imply():
    """§4's lemma, recomputed from the weights rather than trusted as a constant.

    A pruned candidate scores a hard zero on `structural_path`, which is always
    present. The best it can do is have every other signal present at 1.0.
    """
    total = sum(IDENTITY_SIGNAL_WEIGHTS.values())
    ceiling = (total - IDENTITY_SIGNAL_WEIGHTS["structural_path"]) / total
    assert ceiling == pytest.approx(PRUNED_CANDIDATE_SCORE_CEILING)


def test_a_pruned_candidate_can_neither_merge_nor_fire_the_tie_guard():
    """Why pruning is fail-closed for a fixed row.

    If the ceiling ever rose above the merge bar, or above the bar less the tie
    band, pruning could turn an abstention into a merge -- the one error
    invariant 10 calls the expensive one.
    """
    assert PRUNED_CANDIDATE_SCORE_CEILING < MERGE_THRESHOLD
    assert PRUNED_CANDIDATE_SCORE_CEILING < MERGE_THRESHOLD - _TIE_BAND


def test_the_index_reproduces_the_documented_candidate_set():
    """The inverted index is a faster route to `generate_candidates`, not a new rule.

    `generate_candidates` truncates to a window; the index deliberately does
    not, so the comparison is against its untruncated keep-set.
    """
    rng = random.Random(11)
    previous = [
        unit(f"u{i}", f"section-{i % 4}", i, " ".join(str(rng.random()) for _ in range(6)))
        for i in range(60)
    ]
    index = candidate_index_for(previous)
    for incoming in [
        unit("n0", "section-1", 3, "wholly unrelated text"),
        unit("n1", "section-9", 3, "text in a section nobody else uses"),
        unit("n2", "section-2", 7, "text", identifier="4.2"),
    ]:
        columns = _blocked_candidate_columns(incoming, previous, index)
        by_index = {previous[c].logical_id for c in columns}
        by_scan = {
            c.logical_id
            for c in generate_candidates(incoming, previous, window=len(previous))
        }
        assert by_index == by_scan


def test_a_unit_with_no_candidate_at_all_is_new_not_matched():
    """An empty candidate set must abstain into NEW, never fall through."""
    previous = [unit("u0", "section-0", 0, "alpha beta gamma delta")]
    incoming = [unit("n0", "elsewhere", 0, "completely different words entirely")]
    decisions = assign_one_to_one(
        incoming, previous, policy=MatchingPolicy.BLOCKED, resolver=LogicalIdentityResolver()
    )
    assert decisions[0].match is LogicalMatch.NEW


def test_blocked_still_refuses_to_hand_one_old_unit_to_two_new_ones():
    """§N15.3's whole point survives the per-component decomposition.

    Two identical incoming units in one section can only continue one prior
    unit between them; the second must not also claim it.
    """
    text = "identical clause text repeated verbatim across both units"
    previous = [unit("u0", "section-0", 0, text)]
    incoming = [unit("n0", "section-0", 0, text), unit("n1", "section-0", 1, text)]
    decisions = assign_one_to_one(
        incoming, previous, policy=MatchingPolicy.BLOCKED, resolver=LogicalIdentityResolver()
    )
    merged_onto = [d.logical_id for d in decisions if d.match is LogicalMatch.MATCHED]
    assert merged_onto.count("u0") <= 1


def test_blocked_and_legacy_agree_on_a_plain_edited_version_pair():
    """A smoke equivalence check. The measured claim lives in H1-E, not here."""
    rng = random.Random(7)
    previous = [
        unit(f"u{i}", f"section-{i % 5}", i, " ".join(str(rng.random()) for _ in range(8)))
        for i in range(50)
    ]
    incoming = [
        unit(f"n{i}", p.document_path[0], i, p.normalized_text if i % 3 else "rewritten body text")
        for i, p in enumerate(previous)
    ]
    engine = LogicalIdentityResolver()
    legacy = assign_one_to_one(incoming, previous, resolver=engine, policy=MatchingPolicy.LEGACY)
    blocked = assign_one_to_one(incoming, previous, resolver=engine, policy=MatchingPolicy.BLOCKED)
    assert [(d.match, d.logical_id) for d in legacy] == [
        (d.match, d.logical_id) for d in blocked
    ]
