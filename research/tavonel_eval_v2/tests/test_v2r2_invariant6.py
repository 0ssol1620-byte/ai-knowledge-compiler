"""Anti-tautology battery for the V2R2 INVARIANT_6, founder ruling section 9.

Thirteen controls, each proving clause (d) moves for ONE specific reason, plus
the three spent V2R1 shapes as DEVELOPMENT regressions. Their results certify
nothing about V2R2 -- that corpus is spent -- but they are the only material in
existence that reproduces the exact defect the redesign is answering, and a
redesign that cannot be shown green on the shapes it was built for has not been
demonstrated at all.

The battery matters more than usual here. V2R1's clause (d) passed its own test
suite: every test agreed with the classifier because both were written from the
same wrong idea of what identity is. So these controls do not ask "does the
clause agree with itself". Each one names a mutation, states the required
direction, and fails if the clause is indifferent to it -- because a check that
can only return one answer is not a measurement (INC-V2-044).

Two of the thirteen are PASS controls guarding the opposite error. A clause that
went red on `MATCHED + EVIDENCE_MOVED` would be reintroducing the ruling's
central mistake from the other side: treating a facet event on an established
correspondence as though it were an identity disposition.
"""

from __future__ import annotations

import json
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

import selective_build as engine  # noqa: E402
import v2r2_invariant6 as inv6  # noqa: E402
import v2r2_resolver_surface as surface_mod  # noqa: E402
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeKind,
    DiffLevel,
    SemanticChange,
    diff_documents,
)
from v2r2_resolver_surface import (  # noqa: E402
    Correspondence,
    ResolverSurface,
    SurfaceNotExhaustive,
    verify_exhaustive,
)

DECLARED = "identity_unresolved"


class FakeDiff:
    """A change list and nothing else -- all the clauses read of a diff."""

    def __init__(self, changes: list[SemanticChange]) -> None:
        self.changes = changes


def change(kind: ChangeKind, logical_id: str, **kw: object) -> SemanticChange:
    return SemanticChange(kind=kind, logical_id=logical_id, **kw)  # type: ignore[arg-type]


def surface(
    *,
    matched: tuple[tuple[str, str], ...] = (),
    new_after: tuple[str, ...] = (),
    ambiguous_after: tuple[str, ...] = (),
    ambiguous_candidates: tuple[str, ...] = (),
    extra_before: tuple[str, ...] = (),
    quarantine: tuple[str, ...] = (),
    check: bool = True,
) -> ResolverSurface:
    """Build a surface by hand.

    `check=False` bypasses `verify_exhaustive`, which some controls need: a
    mutation that breaks totality must be scoreable by clause (d) rather than
    only rejected at construction, or the clause would be relying on the
    constructor to do its work.
    """
    corrs = tuple(Correspondence(b, a) for b, a in matched)
    before = frozenset([b for b, _ in matched] + list(extra_before) + list(ambiguous_candidates))
    after = frozenset(
        [a for _, a in matched] + list(new_after) + list(ambiguous_after)
    )
    consumed = frozenset(b for b, _ in matched)
    built = ResolverSurface(
        matched=corrs,
        new_after_ids=frozenset(new_after),
        ambiguous_after_ids=frozenset(ambiguous_after),
        ambiguous_candidate_before_ids=frozenset(ambiguous_candidates),
        unmatched_before_ids=before - consumed,
        before_ids=before,
        after_ids=after,
        quarantine_members=frozenset(quarantine or ambiguous_candidates),
    )
    if check:
        verify_exhaustive(built)
    return built


def score(diff: FakeDiff, surf: ResolverSurface) -> list[dict[str, object]]:
    violations, observations = inv6.check_total_accounting(diff, surf)
    assert observations > 0, (
        "the clause examined an empty population. A criterion nothing could have "
        "violated has not been met, it has been avoided"
    )
    return violations


# ---------------------------------------------------------------------------
# 1. resolver MATCHED with different before/after raw ids -> MUST PASS
# ---------------------------------------------------------------------------
def test_control_01_matched_with_differing_raw_ids_passes() -> None:
    """The exact shape that produced all 30 V2R1 false violations.

    A path rename moves the incoming unit's revision-local id while the resolver
    holds the correspondence. V2R1's `before_ids & after_ids` saw a silent
    appearance and a silent disappearance where there was one continuing unit.
    """
    surf = surface(matched=(("src:old/path#1", "src:new/path#1"),))
    assert score(FakeDiff([]), surf) == []


# ---------------------------------------------------------------------------
# 2. delete the MATCHED correspondence from scorer input -> MUST FAIL
# ---------------------------------------------------------------------------
def test_control_02_deleted_correspondence_fails() -> None:
    """Remove the match and both sides must become unaccounted, not quietly fine."""
    intact = surface(matched=(("b1", "a1"),))
    assert score(FakeDiff([]), intact) == []

    broken = ResolverSurface(
        matched=(),
        new_after_ids=frozenset(),
        ambiguous_after_ids=frozenset(),
        ambiguous_candidate_before_ids=frozenset(),
        unmatched_before_ids=frozenset({"b1"}),
        before_ids=frozenset({"b1"}),
        after_ids=frozenset({"a1"}),
    )
    with pytest.raises(SurfaceNotExhaustive):
        verify_exhaustive(broken)

    violations, _ = inv6.check_total_accounting(FakeDiff([]), broken)
    assert violations, "clause (d) is indifferent to a deleted correspondence"
    assert any("conservation failed" in v["why"] for v in violations)
    assert any(v.get("disposition") == "D_UNCONSUMED_BEFORE" for v in violations)


# ---------------------------------------------------------------------------
# 3. resolver NEW but production UNIT_ADDED removed -> MUST FAIL
# ---------------------------------------------------------------------------
def test_control_03_new_without_unit_added_fails() -> None:
    surf = surface(new_after=("a_new",))
    assert score(FakeDiff([change(ChangeKind.UNIT_ADDED, "a_new")]), surf) == []

    violations = score(FakeDiff([]), surf)
    assert [v["disposition"] for v in violations] == ["B_NEW"]


# ---------------------------------------------------------------------------
# 4. genuine before-side removal but UNIT_REMOVED removed -> MUST FAIL
# ---------------------------------------------------------------------------
def test_control_04_removal_without_unit_removed_fails() -> None:
    surf = surface(extra_before=("b_gone",))
    assert score(FakeDiff([change(ChangeKind.UNIT_REMOVED, "b_gone")]), surf) == []

    violations = score(FakeDiff([]), surf)
    assert [v["disposition"] for v in violations] == ["D_UNCONSUMED_BEFORE"]


# ---------------------------------------------------------------------------
# 5. AMBIGUOUS but IDENTITY_UNRESOLVED removed -> MUST FAIL
# ---------------------------------------------------------------------------
def test_control_05_ambiguous_without_unresolved_record_fails() -> None:
    surf = surface(ambiguous_after=("a_amb",), ambiguous_candidates=("b_cand",))
    stated = FakeDiff(
        [change(ChangeKind.IDENTITY_UNRESOLVED, "a_amb", candidates=("b_cand",))]
    )
    assert score(stated, surf) == []

    violations = score(FakeDiff([]), surf)
    dispositions = {v.get("disposition") for v in violations}
    assert "C_AMBIGUOUS" in dispositions
    #: The candidate is also left unaccounted, which is the INC-V2-047 escape.
    assert "D_UNCONSUMED_BEFORE" in dispositions

    #: Clause (e) must move for the same mutation, independently.
    e_violations, e_observed = inv6.check_quarantine_channel(
        FakeDiff([]), surf, declared_record=DECLARED
    )
    assert e_observed > 0 and e_violations


# ---------------------------------------------------------------------------
# 6. AMBIGUOUS candidate also UNIT_REMOVED -> MUST FAIL
# ---------------------------------------------------------------------------
def test_control_06_ambiguous_candidate_also_removed_fails() -> None:
    """The original INC-V2-047 defect: withheld identity, definite removal anyway."""
    surf = surface(ambiguous_after=("a_amb",), ambiguous_candidates=("b_cand",))
    violations = score(
        FakeDiff(
            [
                change(ChangeKind.IDENTITY_UNRESOLVED, "a_amb", candidates=("b_cand",)),
                change(ChangeKind.UNIT_REMOVED, "b_cand"),
            ]
        ),
        surf,
    )
    assert any(v.get("disposition") == "PARTITION" for v in violations), (
        "a candidate of an unsettled identity was reported definitely removed and "
        "the accounting called it a partition"
    )


# ---------------------------------------------------------------------------
# 7. MATCHED unit spuriously UNIT_ADDED -> MUST FAIL
# ---------------------------------------------------------------------------
def test_control_07_matched_reported_added_fails() -> None:
    surf = surface(matched=(("b1", "a1"),))
    violations = score(FakeDiff([change(ChangeKind.UNIT_ADDED, "a1")]), surf)
    assert [v["disposition"] for v in violations] == ["A_MATCHED"]

    #: Keyed on the before-side id it must move too -- production keys matched
    #: facets on the before id, so a spurious add could arrive under either.
    violations = score(FakeDiff([change(ChangeKind.UNIT_ADDED, "b1")]), surf)
    assert [v["disposition"] for v in violations] == ["A_MATCHED"]


# ---------------------------------------------------------------------------
# 8. MATCHED before unit spuriously UNIT_REMOVED -> MUST FAIL
# ---------------------------------------------------------------------------
def test_control_08_matched_before_reported_removed_fails() -> None:
    surf = surface(matched=(("b1", "a1"),))
    violations = score(FakeDiff([change(ChangeKind.UNIT_REMOVED, "b1")]), surf)
    assert [v["disposition"] for v in violations] == ["A_MATCHED"]


# ---------------------------------------------------------------------------
# 9. duplicate MATCHED consumption -> MUST FAIL
# ---------------------------------------------------------------------------
def test_control_09_duplicate_matched_consumption_fails() -> None:
    """One before-side unit may continue into at most one successor."""
    doubled = ResolverSurface(
        matched=(Correspondence("b1", "a1"), Correspondence("b1", "a2")),
        new_after_ids=frozenset(),
        ambiguous_after_ids=frozenset(),
        ambiguous_candidate_before_ids=frozenset(),
        unmatched_before_ids=frozenset(),
        before_ids=frozenset({"b1"}),
        after_ids=frozenset({"a1", "a2"}),
    )
    with pytest.raises(SurfaceNotExhaustive):
        verify_exhaustive(doubled)

    violations, _ = inv6.check_total_accounting(FakeDiff([]), doubled)
    assert any("more than one correspondence" in v["why"] for v in violations)


# ---------------------------------------------------------------------------
# 10. empty unresolved candidate -> MUST NOT count as NAMED
# ---------------------------------------------------------------------------
def test_control_10_empty_candidate_does_not_name() -> None:
    """A record implicating a unit it declines to identify names nothing.

    A clause that accepted one could be satisfied by silence wearing the shape
    of a statement.
    """
    surf = surface(ambiguous_after=("a_amb",), ambiguous_candidates=("b_cand",))
    hollow = FakeDiff([change(ChangeKind.IDENTITY_UNRESOLVED, "a_amb", candidates=("",))])

    assert inv6.named_ids(hollow) == {"a_amb"}
    assert "b_cand" not in inv6.named_ids(hollow)

    e_violations, e_observed = inv6.check_quarantine_channel(
        hollow, surf, declared_record=DECLARED
    )
    assert e_observed > 0
    assert [v["logical_id"] for v in e_violations] == ["b_cand"]

    #: And an entirely hollow record names nobody at all.
    fully_hollow = FakeDiff([change(ChangeKind.IDENTITY_UNRESOLVED, "", candidates=("",))])
    assert inv6.named_ids(fully_hollow) == set()


# ---------------------------------------------------------------------------
# 11. ordinary unchanged same-raw-id MATCH -> MUST PASS
# ---------------------------------------------------------------------------
def test_control_11_unchanged_same_id_match_passes() -> None:
    """Silence under disposition A is legitimate, and this is why (d) cannot
    be computed from the change list alone: production publishes no matched
    surface, so an unchanged unit emits nothing (INC-V2-053)."""
    surf = surface(matched=(("same:id#1", "same:id#1"),))
    assert score(FakeDiff([]), surf) == []


# ---------------------------------------------------------------------------
# 12. MATCHED + EVIDENCE_MOVED -> MUST PASS
# ---------------------------------------------------------------------------
def test_control_12_matched_plus_evidence_moved_passes() -> None:
    """A facet event on an established correspondence is not a disposition.

    Founder ruling section 4 forbids the opposite repair -- adding EVIDENCE_MOVED
    to DEFINITE_KINDS -- because a change event must never substitute for
    identity accounting. This control fails if that ever creeps back in.
    """
    assert ChangeKind.EVIDENCE_MOVED not in inv6.DEFINITE_KINDS
    surf = surface(matched=(("b1", "a1"),))
    moved = FakeDiff(
        [change(ChangeKind.EVIDENCE_MOVED, "b1", before="ev1", after="ev2")]
    )
    assert score(moved, surf) == []


# ---------------------------------------------------------------------------
# 13. MATCHED + MODIFIED_CLAIM -> identity accounting MUST PASS
# ---------------------------------------------------------------------------
def test_control_13_matched_plus_modified_claim_passes_identity() -> None:
    """Content changed; identity did not. The two are scored separately."""
    surf = surface(matched=(("b1", "a1"),))
    modified = FakeDiff(
        [change(ChangeKind.MODIFIED_CLAIM, "b1", before="old", after="new")]
    )
    assert score(modified, surf) == []


# ---------------------------------------------------------------------------
# Development regressions: the three spent V2R1 shapes.
# ---------------------------------------------------------------------------
SPENT_SHAPES = (
    "ecfr:40:273:273.3",
    "git:qdrant/landing_page:qdrant-landing/content/documentation/capacity-planning.md",
    "ecfr:47:54:54.101",
)


#: V2R1's frozen universe receipt, named DIRECTLY rather than resolved through
#: the V2R1 freezer.
#:
#: The freezer route was tried first and it broke silently. The V2R2 adapter
#: overrides `freeze_migration_closure_v2r1`'s module state at import -- that is
#: how it avoids forking 1,900 lines -- and the override is process-wide. So in
#: any pytest session that also imported the adapter, `fz.Workspace()` here
#: returned the V2R2 protocol, `stem_for(..., "universe")` returned the V2R2
#: stem, and these three lineages were simply absent from the receipt that came
#: back. The tests SKIPPED. Not failed: skipped, reporting green, with the only
#: regressions over real material that reproduce V2R1's defect quietly switched
#: off by an import in a neighbouring file.
#:
#: A test whose coverage depends on which modules another file imported is not
#: coverage. Naming the receipt makes this immune to the adapter entirely.
V2R1_UNIVERSE_GLOB = "identity-change-migration-closure-v2r1-universe--*.json"


def _spent_pairs() -> dict[str, dict[str, object]]:
    receipts = sorted((NS / "receipts").glob(V2R1_UNIVERSE_GLOB))
    if not receipts:
        return {}
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    return {row["lineage_id"]: row for row in body.get("pairs", ())}


@pytest.mark.parametrize("lineage_id", SPENT_SHAPES)
def test_spent_v2r1_shapes_are_clean_under_the_redesign(lineage_id: str) -> None:
    """DEVELOPMENT ONLY. These lineages are SPENT and certify nothing.

    They are the material that produced V2R1's 30 clause-(d) violations, all of
    which the founder adjudicated instrument false violations. Under the
    resolver-based clause every one of them must be clean, over a population
    that is not empty.
    """
    rows = _spent_pairs()
    row = rows.get(lineage_id)
    if row is None:
        pytest.skip("the spent V2R1 universe is not present in this checkout")

    before = json.loads((ROOT / row["before"]["canonical_path"]).read_text(encoding="utf-8"))
    after = json.loads((ROOT / row["after"]["canonical_path"]).read_text(encoding="utf-8"))
    before_units, before_shape = engine.snapshots(before)
    after_units, after_shape = engine.snapshots(after)
    source = after["source_id"]

    surf = surface_mod.build_surface(before_units, after_units, source)
    diff = diff_documents(
        before_sha256=before["source_digest"],
        after_sha256=after["source_digest"],
        level=DiffLevel.GRAPH,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=source,
    )

    d_violations, d_observed = inv6.check_total_accounting(diff, surf)
    assert d_observed > 0, "an empty population proves nothing"
    assert d_violations == []

    e_violations, _ = inv6.check_quarantine_channel(diff, surf, declared_record=DECLARED)
    assert e_violations == []

    c_violations, _ = inv6.check_ambiguous_not_reproduced(surf, surf.matched_before_ids)
    assert c_violations == []


def test_spent_shapes_carry_the_renamed_correspondences() -> None:
    """The regression above would be hollow if the shapes no longer contained
    the defect. This asserts the material still exhibits it: 17 resolver-MATCHED
    correspondences whose before and after raw ids differ, exactly as the
    adjudication recorded."""
    rows = _spent_pairs()
    if not all(lineage in rows for lineage in SPENT_SHAPES):
        pytest.skip("the spent V2R1 universe is not present in this checkout")

    differing = 0
    for lineage_id in SPENT_SHAPES:
        row = rows[lineage_id]
        before = json.loads((ROOT / row["before"]["canonical_path"]).read_text(encoding="utf-8"))
        after = json.loads((ROOT / row["after"]["canonical_path"]).read_text(encoding="utf-8"))
        before_units, _ = engine.snapshots(before)
        after_units, _ = engine.snapshots(after)
        surf = surface_mod.build_surface(before_units, after_units, after["source_id"])
        differing += sum(
            1 for c in surf.matched if c.before_logical_id != c.after_snapshot_logical_id
        )
    assert differing == 17
