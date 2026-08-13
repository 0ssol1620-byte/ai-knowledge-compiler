"""Selective recompilation is only worth anything if it matches a full rebuild.

A plan that skips work it should have done produces a corpus that looks compiled
and is quietly wrong, and nothing downstream can tell. §44's PHASE 5 exit says
prove the equivalence; these tests are that proof plus the ways it fails.
"""

from __future__ import annotations

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.recompilation import (
    ArtifactState,
    content_hash,
    plan_recompilation,
    rebuild_order,
    verify_equivalence,
)
from akc_cir.semantic_diff import (
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64

TWO_YEARS = "The warranty covers parts and labour for two years from delivery."
THREE_YEARS = "The warranty covers parts and labour for three years from delivery."


def _unit(logical_id: str, text: str, **kw) -> UnitSnapshot:
    return UnitSnapshot(
        logical_id=logical_id,
        text=text,
        document_path=kw.pop("path", ("Warranty", "Coverage")),
        anchor=kw.pop("anchor", "4.2 Exceptions"),
        neighbour_anchors=kw.pop("neighbours", ("4.1 Scope", "4.3 Claims")),
        **kw,
    )


def _diff(before, after, before_sha=A, after_sha=B):
    return diff_documents(
        before_sha256=before_sha,
        after_sha256=after_sha,
        level=DiffLevel.SEMANTIC,
        before_shape=DocumentShape(),
        after_shape=DocumentShape(),
        before_units=before,
        after_units=after,
    )


def _graph() -> DependencyGraph:
    return DependencyGraph(
        [
            DependencyEdge("chunk_88", "ku_warranty", EdgeType.DEPENDS_ON),
            DependencyEdge("chunk_89", "ku_warranty", EdgeType.DEPENDS_ON),
            DependencyEdge("vault_md", "ku_warranty", EdgeType.DEPENDS_ON),
            DependencyEdge("chunk_90", "ku_shipping", EdgeType.DEPENDS_ON),
        ]
    )


INVENTORY = ["chunk_88", "chunk_89", "chunk_90", "vault_md"]


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


def test_only_what_the_change_reached_is_rebuilt() -> None:
    plan = plan_recompilation(
        diff=_diff([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)]),
        graph=_graph(),
        artifacts=INVENTORY,
    )

    assert set(plan.to_rebuild) == {"chunk_88", "chunk_89", "vault_md"}
    assert "chunk_90" not in plan.to_rebuild


def test_the_untouched_artifact_is_current_and_says_why() -> None:
    plan = plan_recompilation(
        diff=_diff([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)]),
        graph=_graph(),
        artifacts=INVENTORY,
    )

    assert plan.explain("chunk_90") == "no change reached it"


def test_every_rebuilt_artifact_explains_its_own_presence() -> None:
    """An artifact nobody can explain is a traversal bug, not a rounding error."""
    plan = plan_recompilation(
        diff=_diff([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)]),
        graph=_graph(),
        artifacts=INVENTORY,
    )

    for artifact in plan.to_rebuild:
        reason = plan.explain(artifact)
        assert reason and "ku_warranty" in reason


def test_the_work_avoided_is_reported() -> None:
    plan = plan_recompilation(
        diff=_diff([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)]),
        graph=_graph(),
        artifacts=INVENTORY,
    )

    assert plan.total_artifacts == 4
    assert plan.work_avoided == 1
    assert plan.work_avoided_fraction == 0.25


def test_unchanged_content_rebuilds_nothing() -> None:
    plan = plan_recompilation(
        diff=_diff(
            [_unit("ku_warranty", TWO_YEARS)],
            [_unit("ku_warranty", TWO_YEARS)],
            after_sha=A,
        ),
        graph=_graph(),
        artifacts=INVENTORY,
    )

    assert plan.to_rebuild == ()
    assert plan.work_avoided == 4
    assert all(t.state is ArtifactState.CURRENT for t in plan.targets)


# --------------------------------------------------------------------------
# The state that matters most
# --------------------------------------------------------------------------


def _unresolved_plan():
    diff = _diff(
        [_unit("ku_left", TWO_YEARS), _unit("ku_right", TWO_YEARS)],
        [_unit("ku_incoming", THREE_YEARS)],
    )
    graph = DependencyGraph(
        [
            DependencyEdge("chunk_left", "ku_left", EdgeType.DEPENDS_ON),
            DependencyEdge("chunk_right", "ku_right", EdgeType.DEPENDS_ON),
            DependencyEdge("chunk_other", "ku_other", EdgeType.DEPENDS_ON),
        ]
    )
    return diff, plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=["chunk_left", "chunk_right", "chunk_other"],
    )


def test_an_unsettled_identity_does_not_quietly_become_current() -> None:
    """Skipping it turns an honest refusal into a claim that it is still valid."""
    _, plan = _unresolved_plan()

    assert set(plan.unresolved) == {"chunk_left", "chunk_right"}
    assert "chunk_other" not in plan.unresolved


def test_an_unsettled_artifact_is_rebuilt() -> None:
    """It may not need it. Not rebuilding one that did ships a stale answer."""
    _, plan = _unresolved_plan()

    assert set(plan.to_rebuild) == {"chunk_left", "chunk_right"}


def test_an_unsettled_artifact_is_labelled_as_unsettled_not_as_stale() -> None:
    _, plan = _unresolved_plan()

    assert plan.stale == ()
    reason = plan.explain("chunk_left")
    assert reason and "could not settle" in reason


def test_an_artifact_no_change_reached_stays_current_even_beside_unsettled_ones() -> None:
    _, plan = _unresolved_plan()

    assert plan.explain("chunk_other") == "no change reached it"


# --------------------------------------------------------------------------
# Equivalence — the PHASE 5 exit criterion
# --------------------------------------------------------------------------


def test_a_correct_selective_run_equals_a_full_rebuild() -> None:
    full = {"a": content_hash({"v": 2}), "b": content_hash({"v": 1})}
    report = verify_equivalence(
        full_rebuild=full,
        selective_rebuild={"a": content_hash({"v": 2})},
        carried_over={"b": content_hash({"v": 1})},
    )

    assert report.equivalent is True
    assert report.diverged == ()
    assert report.compared == 2


def test_an_artifact_wrongly_carried_over_is_caught() -> None:
    """The quiet failure: reused, and a full rebuild disagrees."""
    full = {"a": content_hash({"v": 2}), "b": content_hash({"v": 2})}
    report = verify_equivalence(
        full_rebuild=full,
        selective_rebuild={"a": content_hash({"v": 2})},
        carried_over={"b": content_hash({"v": 1})},
    )

    assert report.equivalent is False
    assert report.diverged == ("b",)
    assert report.stale_left_behind == ("b",)


def test_an_artifact_the_selective_run_never_produced_is_caught() -> None:
    report = verify_equivalence(
        full_rebuild={"a": content_hash({"v": 1}), "b": content_hash({"v": 1})},
        selective_rebuild={"a": content_hash({"v": 1})},
        carried_over={},
    )

    assert report.equivalent is False
    assert report.missing_from_selective == ("b",)


def test_a_rebuild_outside_the_plan_is_reported() -> None:
    """Not a correctness failure, but the plan and the run disagreed."""
    plan = plan_recompilation(
        diff=_diff([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)]),
        graph=_graph(),
        artifacts=INVENTORY,
    )
    full = {a: content_hash({"a": a}) for a in INVENTORY}
    report = verify_equivalence(
        full_rebuild=full,
        selective_rebuild={a: full[a] for a in [*plan.to_rebuild, "chunk_90"]},
        carried_over={},
        plan=plan,
    )

    assert report.equivalent is True
    assert report.unexpectedly_rebuilt == ("chunk_90",)


def test_equivalence_over_a_whole_worked_change() -> None:
    """End to end: change a clause, plan, rebuild the plan, prove equivalence."""
    diff = _diff([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)])
    plan = plan_recompilation(diff=diff, graph=_graph(), artifacts=INVENTORY)

    before = {a: content_hash({"artifact": a, "warranty": "two years"}) for a in INVENTORY}
    after_full = {
        a: content_hash(
            {
                "artifact": a,
                "warranty": "three years" if a in plan.to_rebuild else "two years",
            }
        )
        for a in INVENTORY
    }
    selective = {
        a: content_hash({"artifact": a, "warranty": "three years"})
        for a in plan.to_rebuild
    }
    carried = {a: before[a] for a in INVENTORY if a not in plan.to_rebuild}

    report = verify_equivalence(
        full_rebuild=after_full,
        selective_rebuild=selective,
        carried_over=carried,
        plan=plan,
    )

    assert report.equivalent is True
    assert report.stale_left_behind == ()
    assert plan.work_avoided == 1


def test_a_missed_dependency_shows_up_as_a_divergence() -> None:
    """If the graph lacks an edge, the plan under-rebuilds and equivalence fails."""
    incomplete = DependencyGraph(
        [DependencyEdge("chunk_88", "ku_warranty", EdgeType.DEPENDS_ON)]
    )
    diff = _diff([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)])
    plan = plan_recompilation(diff=diff, graph=incomplete, artifacts=INVENTORY)

    after_full = {
        a: content_hash({"artifact": a, "warranty": "three years"})
        if a in {"chunk_88", "chunk_89", "vault_md"}
        else content_hash({"artifact": a, "warranty": "two years"})
        for a in INVENTORY
    }
    selective = {
        a: content_hash({"artifact": a, "warranty": "three years"}) for a in plan.to_rebuild
    }
    carried = {
        a: content_hash({"artifact": a, "warranty": "two years"})
        for a in INVENTORY
        if a not in plan.to_rebuild
    }

    report = verify_equivalence(
        full_rebuild=after_full, selective_rebuild=selective, carried_over=carried, plan=plan
    )

    assert report.equivalent is False
    assert set(report.stale_left_behind) == {"chunk_89", "vault_md"}


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def test_a_dependency_is_rebuilt_before_what_depends_on_it() -> None:
    graph = DependencyGraph(
        [
            DependencyEdge("mid", "ku_warranty", EdgeType.DEPENDS_ON),
            DependencyEdge("leaf", "mid", EdgeType.DEPENDS_ON),
        ]
    )
    diff = _diff([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)])
    plan = plan_recompilation(diff=diff, graph=graph, artifacts=["mid", "leaf"])

    order = rebuild_order(plan, graph)

    assert order.index("mid") < order.index("leaf")


def test_cycle_members_are_ordered_last_rather_than_arbitrarily() -> None:
    graph = DependencyGraph(
        [
            DependencyEdge("a", "ku_warranty", EdgeType.DEPENDS_ON),
            DependencyEdge("b", "a", EdgeType.DEPENDS_ON),
            DependencyEdge("a", "b", EdgeType.DEPENDS_ON),
        ]
    )
    diff = _diff([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)])
    plan = plan_recompilation(diff=diff, graph=graph, artifacts=["a", "b"])

    assert plan.cycles_detected
    assert set(rebuild_order(plan, graph)) == {"a", "b"}


def test_the_plan_record_carries_the_change_it_came_from() -> None:
    diff = _diff([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)])
    record = plan_recompilation(diff=diff, graph=_graph(), artifacts=INVENTORY).as_record()

    assert record["change_id"] == diff.change_id
    assert record["rebuild_count"] == 3
    assert record["work_avoided"] == 1
