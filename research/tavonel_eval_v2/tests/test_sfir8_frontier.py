"""Controls for the disk-backed frontier and the byte-budget resource bound.

The thing being defended is a distinction SFIR7 got wrong at a cost of twenty
roots: an *external resource* running out is an operational stop, and a
*repository being large* is not a stop at all. A bound whose derivation reads a
repository cannot tell those apart, so these controls check the derivation and
not merely the number it produces.

The other half is order. A resumed traversal must issue exactly the sequence an
uninterrupted one would, or segmented execution changes the measurement it is
supposed to be preserving.
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

import sfir8_frontier as frontier  # noqa: E402


@pytest.fixture
def db(tmp_path):
    return tmp_path / "frontier.sqlite3"


def drain(f, *, limit=1000):
    """Every pending entry, in order, with a hard stop.

    `iter(f.dequeue, None)` reads better and hangs forever if `dequeue` ever
    stops marking what it hands out -- mutation F3 did exactly that and the
    suite timed out instead of failing. A control that hangs is indistinguishable
    from a broken runner, so the drain is bounded and the bound is an assertion.
    """
    out = []
    for _ in range(limit):
        entry = f.dequeue()
        if entry is None:
            return out
        out.append(entry)
    raise AssertionError(
        f"dequeue produced more than {limit} entries from a frontier that was never "
        "given that many, so it is handing the same entries out repeatedly"
    )


def _enqueue(f, n, root="r1", depth=1):
    return [
        f.enqueue(
            root_id=root, path=f"p{i}", tree_sha=f"sha{i}", depth=depth, parent_path=None
        )
        for i in range(n)
    ]


# ------------------------------------------------------- order is the contract


def test_entries_come_out_in_enqueue_order(db):
    with frontier.Frontier(db) as f:
        _enqueue(f, 5)
        assert [e.path for e in drain(f)] == ["p0", "p1", "p2", "p3", "p4"]


def test_order_survives_the_process_that_built_it(db):
    """The whole point of the disk. A resumed run continues the same sequence."""
    with frontier.Frontier(db) as f:
        _enqueue(f, 6)
        first = [f.dequeue().path for _ in range(2)]

    with frontier.Frontier(db) as resumed:
        rest = [e.path for e in drain(resumed)]

    assert first + rest == ["p0", "p1", "p2", "p3", "p4", "p5"]


def test_a_segmented_traversal_matches_an_uninterrupted_one(db, tmp_path):
    """Section J's first equivalence, at the frontier level.

    The same enqueues, once straight through and once across four reopenings,
    must yield one identical sequence. If they diverge, segmented execution is
    measuring something an uninterrupted run would not.
    """
    with frontier.Frontier(tmp_path / "straight.sqlite3") as f:
        for i in range(12):
            f.enqueue(
                root_id="r", path=f"p{i}", tree_sha=f"s{i}", depth=i % 3, parent_path=None
            )
        straight = [entry.path for entry in drain(f)]

    segmented = []
    for start in range(0, 12, 3):
        with frontier.Frontier(db) as f:
            for i in range(start, start + 3):
                f.enqueue(
                    root_id="r", path=f"p{i}", tree_sha=f"s{i}", depth=i % 3, parent_path=None
                )
            for _ in range(3):
                entry = f.dequeue()
                if entry is not None:
                    segmented.append(entry.path)

    assert segmented == straight


def test_a_dequeued_entry_is_not_handed_out_again(db):
    """Replaying an entry double-counts every candidate beneath it."""
    with frontier.Frontier(db) as f:
        _enqueue(f, 3)
        seen = [f.dequeue().path for _ in range(3)]
        assert f.dequeue() is None
        assert len(set(seen)) == 3


def test_an_empty_frontier_yields_none_rather_than_raising(db):
    with frontier.Frontier(db) as f:
        assert f.dequeue() is None


# ------------------------------------------------------------- the visited set


def test_the_same_tree_reached_twice_is_enqueued_once(db):
    with frontier.Frontier(db) as f:
        first = f.enqueue(
            root_id="r", path="a", tree_sha="shared", depth=1, parent_path=None
        )
        second = f.enqueue(
            root_id="r", path="b/elsewhere", tree_sha="shared", depth=2, parent_path="b"
        )
        assert first is not None
        assert second is None, "one tree object is one subtree, however it is reached"
        assert f.pending_count() == 1


def test_the_visited_set_is_scoped_to_its_root(db):
    """Two repositories can legitimately share a tree sha; neither hides the other."""
    with frontier.Frontier(db) as f:
        assert f.enqueue(
            root_id="r1", path="a", tree_sha="same", depth=1, parent_path=None
        ) is not None
        assert f.enqueue(
            root_id="r2", path="a", tree_sha="same", depth=1, parent_path=None
        ) is not None
        assert f.pending_count() == 2


def test_the_visited_set_survives_reopening(db):
    with frontier.Frontier(db) as f:
        f.enqueue(root_id="r", path="a", tree_sha="s", depth=1, parent_path=None)
        f.dequeue()

    with frontier.Frontier(db) as resumed:
        assert resumed.visited("r", "s") is True
        assert resumed.enqueue(
            root_id="r", path="a", tree_sha="s", depth=1, parent_path=None
        ) is None, "a tree expanded before resume must not be expanded again after"


def test_dequeuing_does_not_forget_that_an_entry_was_seen(db):
    with frontier.Frontier(db) as f:
        f.enqueue(root_id="r", path="a", tree_sha="s", depth=1, parent_path=None)
        f.dequeue()
        assert f.visited("r", "s") is True


# --------------------------------------------- the bound is bytes, from outside


def test_the_worst_case_is_not_beatable_by_an_adversarial_entry():
    """An entry built at every declared maximum must not exceed the worst case."""
    worst = frontier.worst_case_entry_bytes()
    adversarial = frontier.Entry(
        root_id="ü" * 10,
        path="a/" * (frontier.MAX_GIT_PATH_BYTES // 2),
        tree_sha="f" * frontier.MAX_OBJECT_NAME_BYTES,
        depth=frontier.MAX_DEPTH,
        parent_path="b/" * (frontier.MAX_GIT_PATH_BYTES // 2),
        enqueue_sequence=2**63 - 1,
    )
    assert adversarial.serialized_bytes() <= worst, (
        "an entry the format permits serialized larger than the worst case the "
        "budget was divided by, so the entry ceiling understates real storage use"
    )


def test_the_budget_is_denominated_in_bytes_not_characters():
    """A four-byte character must cost four, or the envelope is overspent.

    Mutation F9 dropped the UTF-8 encode and survived, because json.dumps
    escapes non-ASCII by default and the string was already ASCII -- the encode
    had nothing left to do. Measuring what SQLite actually stores is what lets
    a control exist here at all.
    """
    def entry(path):
        return frontier.Entry(
            root_id="r", path=path, tree_sha="f" * 40, depth=1,
            parent_path=None, enqueue_sequence=1,
        )

    narrow = entry("a" * 100)
    wide = entry(chr(0x1F600) * 100)
    assert wide.serialized_bytes() == narrow.serialized_bytes() + 300, (
        "a 4-byte character must cost 4 bytes where a 1-byte character costs 1"
    )


def test_the_entry_ceiling_is_derived_from_the_budget_not_from_a_repository():
    """Halve the storage envelope and the ceiling halves. Nothing else moves it."""
    full = frontier.max_frontier_entries(working_storage_bytes=1_000_000)
    half = frontier.max_frontier_entries(working_storage_bytes=500_000)
    assert half == full // 2 or abs(half * 2 - full) <= 1


def test_the_declared_envelope_is_not_the_sfir4_queue_bound():
    """256 was calibrated on twenty hand-picked repositories and did not transport."""
    assert frontier.max_frontier_entries() > 256 * 100


def test_exhausting_the_declared_storage_is_an_operational_stop(db):
    tiny = frontier.worst_case_entry_bytes() * 3
    with frontier.Frontier(db, working_storage_bytes=tiny) as f:
        assert f.capacity == 3
        _enqueue(f, 3)
        with pytest.raises(frontier.WorkingStorageExhausted, match="WORKING_STORAGE"):
            f.enqueue(root_id="r1", path="p9", tree_sha="sha9", depth=1, parent_path=None)


def test_dequeuing_frees_capacity_because_the_bound_is_on_what_is_held(db):
    """Pending entries occupy storage; expanded ones do not. A traversal that
    keeps up with itself is never stopped by this bound however large the tree."""
    tiny = frontier.worst_case_entry_bytes() * 2
    with frontier.Frontier(db, working_storage_bytes=tiny) as f:
        for i in range(50):
            f.enqueue(
                root_id="r", path=f"p{i}", tree_sha=f"s{i}", depth=1, parent_path=None
            )
            assert f.dequeue() is not None
        assert f.visited_count() == 50, "fifty trees expanded under a two-entry ceiling"


def test_the_bounds_receipt_denies_that_cardinality_is_a_criterion(db):
    with frontier.Frontier(db) as f:
        bounds = f.bounds()
    assert bounds["queue_cardinality_is_a_truncation_criterion"] is False
    assert bounds["max_frontier_entries"] == f.capacity
    assert bounds["worst_case_entry_bytes"] == frontier.worst_case_entry_bytes()
    assert "no repository" in bounds["derived_from"].casefold()


def test_the_bounds_receipt_reports_the_envelope_actually_in_force(db):
    """A receipt that always prints the default hides a narrowed run."""
    with frontier.Frontier(db, working_storage_bytes=4096) as f:
        assert f.bounds()["declared_working_storage_bytes"] == 4096


# ------------------------------------------------------------ entry fidelity


def test_every_field_needed_to_resume_is_stored(db):
    with frontier.Frontier(db) as f:
        f.enqueue(root_id="r", path="src/x", tree_sha="abc", depth=3, parent_path="src")

    with frontier.Frontier(db) as resumed:
        entry = resumed.dequeue()

    assert entry.root_id == "r"
    assert entry.path == "src/x"
    assert entry.tree_sha == "abc"
    assert entry.depth == 3
    assert entry.parent_path == "src"
    assert entry.enqueue_sequence == 1
    assert json.loads(json.dumps(entry.as_dict())) == entry.as_dict()


def test_enqueue_sequence_is_monotonic_and_gapless_within_a_run(db):
    with frontier.Frontier(db) as f:
        assert [e.enqueue_sequence for e in _enqueue(f, 4)] == [1, 2, 3, 4]


def test_enqueue_sequence_does_not_restart_after_reopening(db):
    """Restarting the counter would collide two entries onto one ordinal."""
    with frontier.Frontier(db) as f:
        _enqueue(f, 3)
    with frontier.Frontier(db) as resumed:
        entry = resumed.enqueue(
            root_id="r1", path="p9", tree_sha="sha9", depth=1, parent_path=None
        )
    assert entry.enqueue_sequence == 4


def test_the_sequence_is_the_stored_ordinal_not_a_count_of_what_is_pending(db):
    """Dequeuing must not rewind the ordinal the next entry receives.

    Mutation F15 returned `pending_count()` as the enqueue sequence and survived
    every other control, because until something is dequeued the two numbers are
    identical. Dequeue first and they diverge: the count falls back while the
    ordinal must not, or two entries end up sharing one position in the order a
    resumed traversal replays.
    """
    with frontier.Frontier(db) as f:
        _enqueue(f, 5)
        for _ in range(4):
            f.dequeue()
        assert f.pending_count() == 1
        later = f.enqueue(
            root_id="r1", path="p9", tree_sha="sha9", depth=1, parent_path=None
        )
        assert later.enqueue_sequence == 6, (
            "the sixth entry ever enqueued must be ordinal 6, whatever has since "
            "been expanded"
        )


def test_the_stored_sequence_and_the_returned_sequence_agree(db):
    """A returned ordinal that differs from the stored one would make the digest
    a segment records disagree with the frontier it is meant to describe."""
    with frontier.Frontier(db) as f:
        _enqueue(f, 3)
        f.dequeue()
        returned = f.enqueue(
            root_id="r1", path="p7", tree_sha="sha7", depth=1, parent_path=None
        )
        stored = next(e for e in f.pending() if e.path == "p7")
    assert returned.enqueue_sequence == stored.enqueue_sequence
    assert returned.as_dict() == stored.as_dict()
