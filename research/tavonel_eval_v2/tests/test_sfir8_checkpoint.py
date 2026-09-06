"""Controls for segmented, resumable traversal.

Every refusal here exists because its absence would let a traversal be steered
between windows -- by an edit, an omission, a reordering, or a swapped roster.
A resumed run that cannot prove what it inherited is not a resumed run, it is a
new run wearing the old one's totals.

The equivalence controls are the other half: if segmenting changes the order or
the outcome, then the segmentation is part of the measurement, and the frozen
protocol no longer describes what was measured.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir8_checkpoint as cp  # noqa: E402
import sfir8_frontier as frontier  # noqa: E402

ROSTER = "sha256:" + "a" * 64


def make(index, previous, **overrides):
    body = dict(
        study_id="SFIR8-DEV",
        segment_index=index,
        roster_digest=ROSTER,
        root_index=index,
        current_root_id="react/react",
        current_canonical_address="react/react",
        current_repository_numeric_id="10270250",
        frontier_digest="sha256:" + "b" * 64,
        visited_digest="sha256:" + "c" * 64,
        candidate_digest="sha256:" + "d" * 64,
        completed_roots_digest="sha256:" + "e" * 64,
        logical_request_count=100 * (index + 1),
        network_hop_count=110 * (index + 1),
        provider_charged_count=110 * (index + 1),
        provider_remaining=4000,
        provider_reset_epoch=1787884322,
        previous_segment_digest=previous,
        next_action="CONTINUE_ROOT",
        disposition=cp.RATE_WINDOW_CLOSE,
    )
    body.update(overrides)
    return cp.Checkpoint(**body)


def chain_of(n):
    chain = cp.SegmentChain(study_id="SFIR8-DEV", roster_digest=ROSTER)
    for i in range(n):
        chain.append(make(i, chain.head))
    return chain


# ------------------------------------------------------------ the chain links


def test_the_first_segment_inherits_genesis():
    chain = cp.SegmentChain(study_id="SFIR8-DEV", roster_digest=ROSTER)
    assert chain.head == cp.GENESIS
    chain.append(make(0, cp.GENESIS))
    assert chain.head != cp.GENESIS


def test_a_chain_of_segments_links_head_to_predecessor():
    chain = chain_of(4)
    assert len(chain.segments) == 4
    for previous, current in zip(chain.segments, chain.segments[1:], strict=False):
        assert current.previous_segment_digest == previous.digest()


def test_an_omitted_segment_refuses():
    chain = chain_of(2)
    skipped = make(3, chain.head)
    with pytest.raises(cp.CheckpointRefused, match="index 3"):
        chain.append(skipped)


def test_a_reordered_segment_refuses():
    chain = cp.SegmentChain(study_id="SFIR8-DEV", roster_digest=ROSTER)
    first = make(0, cp.GENESIS)
    chain.append(first)
    second = make(1, first.digest())
    third = make(2, second.digest())
    with pytest.raises(cp.CheckpointRefused, match="index 2"):
        chain.append(third)


def test_a_segment_naming_the_wrong_predecessor_refuses():
    chain = chain_of(2)
    with pytest.raises(cp.CheckpointRefused, match="chain head"):
        chain.append(make(2, "sha256:" + "9" * 64))


def test_a_segment_from_another_study_refuses():
    chain = chain_of(1)
    with pytest.raises(cp.CheckpointRefused, match="do not compose"):
        chain.append(make(1, chain.head, study_id="SFIR9"))


def test_a_segment_against_another_roster_refuses():
    """Resuming across a roster change traverses a population nobody selected."""
    chain = chain_of(1)
    with pytest.raises(cp.CheckpointRefused, match="different roster"):
        chain.append(make(1, chain.head, roster_digest="sha256:" + "f" * 64))


@pytest.mark.parametrize(
    "counter",
    ["root_index", "logical_request_count", "network_hop_count", "provider_charged_count"],
)
def test_a_counter_that_fell_across_a_boundary_refuses(counter):
    """Work does not un-happen. A fall means the segment did not inherit state."""
    chain = chain_of(2)
    regressed = make(2, chain.head, **{counter: 0})
    with pytest.raises(cp.CheckpointRefused, match="does not un-happen"):
        chain.append(regressed)


# ------------------------------------------------- the checkpoint is not editable


def test_a_checkpoint_round_trips(tmp_path):
    original = make(0, cp.GENESIS)
    path = original.write(tmp_path / "seg0.json")
    loaded, claimed = cp.read(path)
    assert loaded == original
    assert claimed == original.digest()


@pytest.mark.parametrize(
    "field,value",
    [
        ("root_index", 99),
        ("frontier_digest", "sha256:" + "0" * 64),
        ("candidate_digest", "sha256:" + "1" * 64),
        ("current_repository_numeric_id", "1"),
        ("logical_request_count", 1),
        ("previous_segment_digest", "sha256:" + "2" * 64),
    ],
)
def test_an_edited_checkpoint_refuses(tmp_path, field, value):
    path = make(0, cp.GENESIS).write(tmp_path / "seg0.json")
    body = json.loads(path.read_text(encoding="utf-8"))
    body[field] = value
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(cp.CheckpointRefused, match="edited since it was written"):
        cp.read(path)


def test_a_checkpoint_without_its_digest_refuses(tmp_path):
    path = make(0, cp.GENESIS).write(tmp_path / "seg0.json")
    body = json.loads(path.read_text(encoding="utf-8"))
    del body["segment_digest"]
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(cp.CheckpointRefused, match="nothing attests"):
        cp.read(path)


def test_re_stamping_the_digest_after_an_edit_still_changes_identity(tmp_path):
    """An editor who recomputes the digest produces a segment the chain rejects."""
    chain = chain_of(1)
    honest = make(1, chain.head)
    tampered = make(1, chain.head, root_index=50)
    assert honest.digest() != tampered.digest()
    path = tampered.write(tmp_path / "seg1.json")
    loaded, _ = cp.read(path)
    with pytest.raises(cp.CheckpointRefused, match=r"does not un-happen|index"):
        cp.SegmentChain(study_id="SFIR8-DEV", roster_digest=ROSTER).append(loaded)


# ---------------------------------------------------------------- the digests


def test_the_frontier_digest_depends_on_order():
    """Same entries, different order, different digest.

    Mutation C10 sorted the entries before digesting and survived, because the
    two frontiers the old control built also differed in their ordinals -- so
    sorting could not make them collide and the control proved nothing. Holding
    the entries fixed and permuting only their order is what tests the claim.
    """
    def entry(path, seq):
        return frontier.Entry(
            root_id="r", path=path, tree_sha=f"s-{path}", depth=1,
            parent_path=None, enqueue_sequence=seq,
        )

    a, b = entry("x", 1), entry("y", 2)
    assert cp.frontier_digest([a, b]) != cp.frontier_digest([b, a]), (
        "two frontiers holding the same entries in different orders traverse "
        "differently and must not digest alike"
    )


def test_the_frontier_digest_of_a_live_frontier_is_its_enqueue_order(tmp_path):
    """The contract above, reached through the object that actually produces it."""
    with frontier.Frontier(tmp_path / "f.sqlite3") as f:
        for p in ("x", "y"):
            f.enqueue(root_id="r", path=p, tree_sha=f"s{p}", depth=1, parent_path=None)
        entries = list(f.pending())
    assert [e.path for e in entries] == ["x", "y"]
    assert cp.frontier_digest(entries) == cp.digest([e.as_dict() for e in entries])


def test_the_visited_digest_does_not_depend_on_order():
    """Membership is the fact; the order rows come back in is not."""
    assert cp.visited_digest([("r", "a"), ("r", "b")]) == cp.visited_digest(
        [("r", "b"), ("r", "a")]
    )


def test_the_visited_digest_distinguishes_different_membership():
    assert cp.visited_digest([("r", "a")]) != cp.visited_digest([("r", "b")])


def test_the_frontier_digest_survives_a_reopening(tmp_path):
    """The digest a segment records must be the one the next window recomputes."""
    db = tmp_path / "f.sqlite3"
    with frontier.Frontier(db) as f:
        for i in range(5):
            f.enqueue(root_id="r", path=f"p{i}", tree_sha=f"s{i}", depth=1, parent_path=None)
        before = cp.frontier_digest(list(f.pending()))
    with frontier.Frontier(db) as resumed:
        assert cp.frontier_digest(list(resumed.pending())) == before


# ------------------------------------------------------------- the run receipt


def test_the_receipt_carries_the_chain_head():
    chain = chain_of(3)
    receipt = chain.receipt()
    assert receipt["segment_chain_head"] == chain.head
    assert receipt["segment_count"] == 3
    assert len(receipt["segment_digests"]) == 3


def test_the_chain_head_changes_if_any_segment_changes():
    """The head is the only value that depends on every segment, in order."""
    a = chain_of(3).head
    chain = cp.SegmentChain(study_id="SFIR8-DEV", roster_digest=ROSTER)
    for i in range(3):
        chain.append(make(i, chain.head, root_index=i + 10))
    assert chain.head != a


def test_the_receipt_says_the_fail_safe_was_not_widened():
    """The alternative to waiting is stopping, not a longer permitted wait."""
    receipt = chain_of(1).receipt()
    assert cp.RATE_WINDOW_CLOSE in receipt["waiting_was_not_the_alternative"]
    assert "unchanged" in receipt["waiting_was_not_the_alternative"]


def test_a_rate_window_close_is_not_a_completion_state():
    assert cp.RATE_WINDOW_CLOSE not in {"COMPLETE", "ZERO_CANDIDATE_ROOT_DISPOSITION"}
    assert "SEGMENT" in cp.RATE_WINDOW_CLOSE


def test_the_digest_is_canonical_and_not_a_repr():
    """Two dicts with the same content must digest alike whatever order they
    were built in.

    Mutation C14 swapped the canonical JSON encoding for `repr`, which preserves
    insertion order, and survived -- every checkpoint in the suite happened to be
    built key-by-key in the same sequence, so the difference never showed. A
    digest that depends on how a dict was assembled would make two identical
    checkpoints look like different segments.
    """
    forwards = {"a": 1, "b": {"c": 2, "d": 3}}
    backwards = {"b": {"d": 3, "c": 2}, "a": 1}
    assert forwards == backwards
    assert cp.digest(forwards) == cp.digest(backwards)
    assert cp.digest(forwards) != cp.digest({"a": 1, "b": {"c": 2, "d": 4}})


def test_the_receipt_says_the_segment_closed_rather_than_the_bound_widening():
    """The claim is about what was done, not merely that a word appears.

    Mutation C16 changed "closes the segment" to "widens the" and the old
    control still passed, because it only looked for the word "unchanged"
    elsewhere in the sentence.
    """
    sentence = chain_of(1).receipt()["waiting_was_not_the_alternative"]
    assert "closes the segment" in sentence, (
        "the receipt must say the segment was closed. Changing an execution bound "
        "because a result was inconvenient is the one thing the frozen protocol "
        "forbids, so what was done instead has to be stated."
    )
    assert "widens the segment" not in sentence
    assert "unchanged" in sentence
