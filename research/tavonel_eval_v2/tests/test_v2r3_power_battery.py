"""The V2R3 power battery, founder ruling section 8. Eighteen controls.

Synthetic fixtures and spent evidence only. No fresh V2R3 outcome is read here
and none exists.

EVERY CONTROL HAS A RED MUTATION DIRECTION. A control that only ever asserts
green proves the clause is willing to agree, not that it is able to disagree,
and this study has now burned two corpora on instruments that could only return
one answer. So each PASS control below is paired with the mutation that must
turn it red, in the same test, and each FAIL control shows the unmutated shape
passing first.

Both predecessors would fail rows here:

    V2R1  fails control 2  -- MATCHED with differing raw ids read as a silent
                             appearance plus a silent disappearance
    V2R2  fails control 6  -- NEW + quarantined required `unit_added`, which the
                             compatibility contract forbids
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "tools"),
    str(NS / "compiler"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import v2r3_invariant6 as inv6  # noqa: E402
from akc_cir.semantic_diff import ChangeKind, SemanticChange  # noqa: E402
from v2r3_effective_identity import (  # noqa: E402
    Effective,
    EffectiveSurface,
    EffectiveUnit,
    StateNotTotal,
    classify_after,
    classify_before,
    verify_total,
)
from v2r3_quarantine_oracle import (  # noqa: E402
    DECLARED_CANDIDATE,
    OracleMember,
    QuarantineOracle,
    build_oracle_quarantine,
)

DECLARED = "identity_unresolved"


class FakeDiff:
    def __init__(self, changes: list[SemanticChange]) -> None:
        self.changes = changes


def rec(kind: ChangeKind, logical_id: str, **kw: object) -> SemanticChange:
    return SemanticChange(kind=kind, logical_id=logical_id, **kw)  # type: ignore[arg-type]


def oracle(*ids: str) -> QuarantineOracle:
    return QuarantineOracle(
        members={
            i: OracleMember(logical_id=i, reason=DECLARED_CANDIDATE, implicated_by="fixture")
            for i in ids
        }
    )


def surface(
    after: list[EffectiveUnit],
    before: list[EffectiveUnit],
    matched: tuple[tuple[str, str], ...] = (),
    quarantine: QuarantineOracle | None = None,
) -> EffectiveSurface:
    return EffectiveSurface(
        after=tuple(after),
        before=tuple(before),
        matched_pairs=matched,
        quarantine=quarantine or oracle(),
    )


def score(diff: FakeDiff, surf: EffectiveSurface) -> list[dict[str, object]]:
    violations, observations = inv6.check_effective_accounting(diff, surf)
    assert observations > 0, (
        "the clause examined an empty population. A criterion nothing could have "
        "violated has not been met, it has been avoided"
    )
    return violations


# ---------------------------------------------------------------------------
# 1. MATCHED, same raw ids, no quarantine -> MATCHED, silence allowed
# ---------------------------------------------------------------------------
def test_01_matched_same_ids_silence_allowed() -> None:
    unit = classify_after("u:same", "MATCHED", "u:same", "u:same", oracle())
    assert unit.effective is Effective.MATCHED and unit.rule == "E"
    surf = surface([unit], [], matched=(("u:same", "u:same"),))
    assert score(FakeDiff([]), surf) == []

    #: RED DIRECTION: a matched unit reported added is a contradiction.
    assert score(FakeDiff([rec(ChangeKind.UNIT_ADDED, "u:same")]), surf)


# ---------------------------------------------------------------------------
# 2. MATCHED, differing raw ids, no quarantine -> MATCHED, silence allowed
# ---------------------------------------------------------------------------
def test_02_matched_differing_ids_silence_allowed() -> None:
    """The shape that invalidated V2R1. A rename moves the incoming id; the
    correspondence holds; nothing is emitted; nothing is wrong."""
    unit = classify_after("u:new", "MATCHED", "u:old", "u:old", oracle())
    assert unit.effective is Effective.MATCHED
    surf = surface([unit], [], matched=(("u:old", "u:new"),))
    assert score(FakeDiff([]), surf) == []

    #: RED DIRECTION, and specifically on the BEFORE-side id, because production
    #: keys matched facets there -- a spurious removal could arrive under either.
    assert score(FakeDiff([rec(ChangeKind.UNIT_REMOVED, "u:old")]), surf)


# ---------------------------------------------------------------------------
# 3. MATCHED + EVIDENCE_MOVED -> identity accounting remains MATCHED
# ---------------------------------------------------------------------------
def test_03_matched_plus_evidence_moved_passes() -> None:
    """A facet event on an established correspondence is not a disposition.

    Founder ruling forbids the opposite repair -- promoting `evidence_moved` to
    a definite identity outcome -- so this control fails if it ever creeps back.
    """
    unit = classify_after("u:a", "MATCHED", "u:b", "u:b", oracle())
    surf = surface([unit], [], matched=(("u:b", "u:a"),))
    moved = FakeDiff([rec(ChangeKind.EVIDENCE_MOVED, "u:b", before="e1", after="e2")])
    assert score(moved, surf) == []

    #: RED DIRECTION: the same unit reported ADDED still fails, so the pass
    #: above is tolerance of facet events, not indifference to the record list.
    assert score(FakeDiff([*moved.changes, rec(ChangeKind.UNIT_ADDED, "u:a")]), surf)


# ---------------------------------------------------------------------------
# 4. MATCHED + MODIFIED_CLAIM -> identity accounting remains MATCHED
# ---------------------------------------------------------------------------
def test_04_matched_plus_modified_claim_passes_identity() -> None:
    """Content changed; identity did not. Graded by different invariants."""
    unit = classify_after("u:a", "MATCHED", "u:b", "u:b", oracle())
    surf = surface([unit], [], matched=(("u:b", "u:a"),))
    modified = FakeDiff([rec(ChangeKind.MODIFIED_CLAIM, "u:b", before="x", after="y")])
    assert score(modified, surf) == []
    assert score(FakeDiff([*modified.changes, rec(ChangeKind.UNIT_REMOVED, "u:b")]), surf)


# ---------------------------------------------------------------------------
# 5. NEW, not quarantined -> UNIT_ADDED required
# ---------------------------------------------------------------------------
def test_05_new_clean_requires_unit_added() -> None:
    unit = classify_after("u:n", "NEW", "u:n", None, oracle())
    assert unit.effective is Effective.NEW and unit.rule == "C"
    surf = surface([unit], [])
    assert score(FakeDiff([rec(ChangeKind.UNIT_ADDED, "u:n")]), surf) == []

    violations = score(FakeDiff([]), surf)
    assert [v["missing_record"] for v in violations] == ["unit_added"]


# ---------------------------------------------------------------------------
# 6. NEW, quarantined -> IDENTITY_UNRESOLVED required, UNIT_ADDED forbidden
# ---------------------------------------------------------------------------
def test_06_new_quarantined_is_unresolved_not_added() -> None:
    """The state that invalidated V2R2, as a first-class control.

    V2R2 required `unit_added` here while the compatibility contract forbade it
    and V2R2's own clause (e) required `identity_unresolved` -- a state no
    implementation could occupy.
    """
    unit = classify_after("u:n", "NEW", "u:n", None, oracle("u:n"))
    assert unit.effective is Effective.UNRESOLVED and unit.rule == "B"
    surf = surface([unit], [], quarantine=oracle("u:n"))

    stated = FakeDiff([rec(ChangeKind.IDENTITY_UNRESOLVED, "u:n", candidates=("u:c",))])
    assert score(stated, surf) == []

    #: The obligation is exactly inverted from row C, and both directions are
    #: asserted so neither can be quietly dropped.
    from v2r3_state_table import obligations_for

    rules = obligations_for(Effective.UNRESOLVED, "after")
    assert ChangeKind.UNIT_ADDED in rules["forbidden"]
    assert ChangeKind.UNIT_ADDED not in rules["required"]


# ---------------------------------------------------------------------------
# 7. AMBIGUOUS -> IDENTITY_UNRESOLVED required, definite outcomes forbidden
# ---------------------------------------------------------------------------
def test_07_ambiguous_requires_unresolved_and_forbids_definite() -> None:
    unit = classify_after("u:x", "AMBIGUOUS", "u:c", None, oracle())
    assert unit.effective is Effective.UNRESOLVED and unit.rule == "A"
    surf = surface([unit], [])
    assert score(FakeDiff([rec(ChangeKind.IDENTITY_UNRESOLVED, "u:x")]), surf) == []

    violations = score(
        FakeDiff(
            [
                rec(ChangeKind.IDENTITY_UNRESOLVED, "u:x"),
                rec(ChangeKind.UNIT_ADDED, "u:x"),
            ]
        ),
        surf,
    )
    assert [v["forbidden_record"] for v in violations] == ["unit_added"]


# ---------------------------------------------------------------------------
# 8. unmatched-before, not quarantined -> UNIT_REMOVED required
# ---------------------------------------------------------------------------
def test_08_unmatched_before_clean_requires_unit_removed() -> None:
    unit = classify_before("u:gone", oracle())
    assert unit.effective is Effective.REMOVED and unit.rule == "G"
    surf = surface([], [unit])
    assert score(FakeDiff([rec(ChangeKind.UNIT_REMOVED, "u:gone")]), surf) == []
    assert [v["missing_record"] for v in score(FakeDiff([]), surf)] == ["unit_removed"]


# ---------------------------------------------------------------------------
# 9. unmatched-before, quarantined -> visibly unresolved, UNIT_REMOVED forbidden
# ---------------------------------------------------------------------------
def test_09_unmatched_before_quarantined_forbids_removal() -> None:
    """INC-V2-047's original defect, as a standing control: before the repair
    this unit escaped as `unit_removed`."""
    unit = classify_before("u:q", oracle("u:q"))
    assert unit.effective is Effective.UNRESOLVED and unit.rule == "F"
    surf = surface([], [unit], quarantine=oracle("u:q"))

    assert score(FakeDiff([rec(ChangeKind.IDENTITY_UNRESOLVED, "u:q")]), surf) == []

    violations = score(
        FakeDiff(
            [
                rec(ChangeKind.IDENTITY_UNRESOLVED, "u:q"),
                rec(ChangeKind.UNIT_REMOVED, "u:q"),
            ]
        ),
        surf,
    )
    assert [v["forbidden_record"] for v in violations] == ["unit_removed"]


# ---------------------------------------------------------------------------
# 10. transitive quarantine over a definite MATCHED -> effective unresolved
# ---------------------------------------------------------------------------
def test_10_transitive_quarantine_overrides_a_definite_match() -> None:
    """Contract clause 1d, exercised through the real oracle rather than a
    hand-built member set: a definite match whose counterpart is already
    quarantined implicates the incoming identity too."""
    built = build_oracle_quarantine(
        unsettled_decisions=[("u:amb", ("u:c1",), "u:c1")],
        definite_matches=[("u:m", "u:c1")],
        before_ids=frozenset({"u:c1", "u:m"}),
    )
    assert "u:c1" in built, "the declared candidate must be a member"
    assert "u:m" in built, "clause 1d must implicate the transitively matched identity"
    assert built.reason_for("u:m") == "definitely_matched_to_an_already_quarantined_member"

    unit = classify_after("u:m", "MATCHED", "u:c1", "u:c1", built)
    assert unit.effective is Effective.UNRESOLVED and unit.rule == "D"

    #: RED DIRECTION: without the transitive clause the same unit would be
    #: MATCHED, and a matched assertion is exactly what the quarantine forbids.
    without_transitive = classify_after("u:m", "MATCHED", "u:c1", "u:c1", oracle())
    assert without_transitive.effective is Effective.MATCHED


# ---------------------------------------------------------------------------
# 11. duplicate match consumption -> fail
# ---------------------------------------------------------------------------
def test_11_duplicate_match_consumption_fails() -> None:
    surf = surface(
        [
            classify_after("u:a1", "MATCHED", "u:b", "u:b", oracle()),
            classify_after("u:a2", "MATCHED", "u:b", "u:b", oracle()),
        ],
        [],
        matched=(("u:b", "u:a1"), ("u:b", "u:a2")),
    )
    with pytest.raises(StateNotTotal, match="more than one effective match"):
        verify_total(surf, frozenset({"u:b"}), frozenset({"u:a1", "u:a2"}))


# ---------------------------------------------------------------------------
# 12. a unit with no effective disposition -> fail
# ---------------------------------------------------------------------------
def test_12_unit_with_no_disposition_fails() -> None:
    surf = surface([classify_after("u:a", "NEW", "u:a", None, oracle())], [])
    with pytest.raises(StateNotTotal, match="coverage is not exact"):
        verify_total(surf, frozenset({"u:orphan"}), frozenset({"u:a"}))


# ---------------------------------------------------------------------------
# 13. a unit with two effective dispositions -> fail
# ---------------------------------------------------------------------------
def test_13_unit_with_two_dispositions_fails() -> None:
    surf = surface(
        [
            classify_after("u:a", "NEW", "u:a", None, oracle()),
            classify_after("u:a", "AMBIGUOUS", "u:c", None, oracle()),
        ],
        [],
    )
    with pytest.raises(StateNotTotal, match="more than one effective disposition"):
        verify_total(surf, frozenset(), frozenset({"u:a"}))


# ---------------------------------------------------------------------------
# 14. an empty unresolved candidate does not count as visible NAMED identity
# ---------------------------------------------------------------------------
def test_14_empty_candidate_does_not_name() -> None:
    """A record implicating a unit it declines to identify names nothing, and a
    clause that accepted one could be satisfied by silence wearing the shape of
    a statement."""
    unit = classify_before("u:q", oracle("u:q"))
    surf = surface([], [unit], quarantine=oracle("u:q"))
    hollow = FakeDiff([rec(ChangeKind.IDENTITY_UNRESOLVED, "u:other", candidates=("",))])

    view = inv6.DiffView(hollow)
    assert view.visibly_unresolved("u:q") is False

    violations = score(hollow, surf)
    assert [v["missing_record"] for v in violations] == ["identity_unresolved"]

    #: Named as a NON-EMPTY candidate, the same unit is visible -- contract
    #: clause 4: a declared candidate needs no second record of its own.
    named = FakeDiff([rec(ChangeKind.IDENTITY_UNRESOLVED, "u:other", candidates=("u:q",))])
    assert score(named, surf) == []


# ---------------------------------------------------------------------------
# 15. deletion of a required IDENTITY_UNRESOLVED -> fail
# ---------------------------------------------------------------------------
def test_15_deleting_the_required_unresolved_record_fails() -> None:
    """Suppressing a false definite outcome and saying nothing replaces a false
    statement with no statement, which a fail-closed endpoint cannot score."""
    unit = classify_after("u:x", "AMBIGUOUS", "u:c", None, oracle())
    surf = surface([unit], [])
    assert score(FakeDiff([rec(ChangeKind.IDENTITY_UNRESOLVED, "u:x")]), surf) == []
    assert [v["missing_record"] for v in score(FakeDiff([]), surf)] == ["identity_unresolved"]


# ---------------------------------------------------------------------------
# 16. inserting UNIT_ADDED into NEW+QUARANTINED -> fail
# ---------------------------------------------------------------------------
def test_16_unit_added_on_a_quarantined_new_fails() -> None:
    """Contract clause 2. This is the mutation production's own source records
    as having been caught by a development replay when the quarantine guard sat
    below the NEW branch: 12 violations, all `unit_added` on a quarantined id."""
    unit = classify_after("u:n", "NEW", "u:n", None, oracle("u:n"))
    surf = surface([unit], [], quarantine=oracle("u:n"))
    violations = score(
        FakeDiff(
            [
                rec(ChangeKind.IDENTITY_UNRESOLVED, "u:n"),
                rec(ChangeKind.UNIT_ADDED, "u:n"),
            ]
        ),
        surf,
    )
    assert [v["forbidden_record"] for v in violations] == ["unit_added"]


# ---------------------------------------------------------------------------
# 17. inserting UNIT_REMOVED into a quarantined before-side unit -> fail
# ---------------------------------------------------------------------------
def test_17_unit_removed_on_a_quarantined_before_unit_fails() -> None:
    unit = classify_before("u:q", oracle("u:q"))
    surf = surface([], [unit], quarantine=oracle("u:q"))
    violations = score(
        FakeDiff(
            [
                rec(ChangeKind.IDENTITY_UNRESOLVED, "u:q"),
                rec(ChangeKind.UNIT_REMOVED, "u:q"),
            ]
        ),
        surf,
    )
    assert [v["forbidden_record"] for v in violations] == ["unit_removed"]


# ---------------------------------------------------------------------------
# 18. removing UNIT_ADDED from a genuine non-quarantined NEW -> fail
# ---------------------------------------------------------------------------
def test_18_removing_unit_added_from_a_genuine_new_fails() -> None:
    """The guard against a blanket surrender. Row B must not be won by making
    every NEW tolerant of silence: over-quarantine is its own defect and would
    destroy the diff's usefulness."""
    clean = classify_after("u:n", "NEW", "u:n", None, oracle())
    surf = surface([clean], [])
    assert score(FakeDiff([rec(ChangeKind.UNIT_ADDED, "u:n")]), surf) == []
    assert score(FakeDiff([]), surf), "silence on a genuine addition must fail"


# ---------------------------------------------------------------------------
# The composition rule, which no single row above exercises
# ---------------------------------------------------------------------------
def test_composed_obligations_for_an_id_carried_on_both_sides() -> None:
    """One logical id, two real units: an unmatched before-side unit that ended
    and an unmatched after-side unit that began at the same path.

    Found on the spent V2R2 corpus. Both records are correct and an accounting
    indexed by id alone reads each as a violation of the other. `compose` makes
    both required and neither forbidden.
    """
    after = classify_after("u:shared", "NEW", "u:shared", None, oracle())
    before = classify_before("u:shared", oracle())
    surf = surface([after], [before])

    both = FakeDiff(
        [
            rec(ChangeKind.UNIT_ADDED, "u:shared"),
            rec(ChangeKind.UNIT_REMOVED, "u:shared"),
        ]
    )
    assert score(both, surf) == []

    #: RED DIRECTION in each direction separately -- the composition must not
    #: have made the id unfalsifiable.
    assert [v["missing_record"] for v in score(
        FakeDiff([rec(ChangeKind.UNIT_ADDED, "u:shared")]), surf
    )] == ["unit_removed"]
    assert [v["missing_record"] for v in score(
        FakeDiff([rec(ChangeKind.UNIT_REMOVED, "u:shared")]), surf
    )] == ["unit_added"]
    assert score(FakeDiff([*both.changes, rec(ChangeKind.IDENTITY_UNRESOLVED, "u:shared")]), surf)
