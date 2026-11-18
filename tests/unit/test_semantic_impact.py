"""Tests for the semantic/positional impact-channel split.

The protected diff still records evidence movement. These tests prove the new
product-facing impact policy does not reinterpret that movement as a semantic
invalidation, while preserving fail-closed behavior for real meaning changes and
unresolved identity.
"""

from __future__ import annotations

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.recompilation import content_hash, plan_recompilation, verify_equivalence
from akc_cir.semantic_diff import ChangeKind, DiffLevel, DocumentShape, UnitSnapshot, diff_documents
from akc_cir.semantic_impact import plan_semantic_recompilation, semantic_impact_seeds

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64
ARTIFACTS = ("chunk_a", "workflow_a", "chunk_unrelated")


def _unit(
    logical_id: str,
    text: str,
    *,
    evidence: str,
    page: int,
    anchor: str = "4.2",
) -> UnitSnapshot:
    return UnitSnapshot(
        logical_id=logical_id,
        text=text,
        document_path=("Warranty", "Coverage"),
        anchor=anchor,
        neighbour_anchors=("4.1", "4.3"),
        evidence_id=evidence,
        page_number1=page,
    )


def _graph(*logical_ids: str) -> DependencyGraph:
    edges: list[DependencyEdge] = []
    for logical_id in logical_ids:
        edges.append(DependencyEdge("chunk_a", logical_id, EdgeType.DEPENDS_ON))
    edges.extend(
        [
            DependencyEdge("chunk_a", "workflow_a", EdgeType.CONSUMED_BY),
            DependencyEdge("chunk_unrelated", "ku_other", EdgeType.DEPENDS_ON),
        ]
    )
    return DependencyGraph(edges)


def _diff(before_units, after_units):
    return diff_documents(
        before_sha256=A,
        after_sha256=B,
        level=DiffLevel.SEMANTIC,
        before_shape=DocumentShape(),
        after_shape=DocumentShape(),
        before_units=before_units,
        after_units=after_units,
    )


def test_moved_evidence_remains_observable_but_is_not_a_semantic_seed() -> None:
    diff = _diff(
        [_unit("ku_warranty", "Warranty is two years.", evidence="ev_old", page=17)],
        [_unit("ku_warranty", "Warranty is two years.", evidence="ev_new", page=18)],
    )

    assert any(change.kind is ChangeKind.EVIDENCE_MOVED for change in diff.changes)
    assert diff.changed_logical_ids == ("ku_warranty",)  # protected legacy channel is unchanged
    assert semantic_impact_seeds(diff) == ()


def test_moved_only_claim_does_not_rebuild_knowledge_consumers() -> None:
    diff = _diff(
        [_unit("ku_warranty", "Warranty is two years.", evidence="ev_old", page=17)],
        [_unit("ku_warranty", "Warranty is two years.", evidence="ev_new", page=18)],
    )

    plan = plan_semantic_recompilation(
        diff=diff,
        graph=_graph("ku_warranty"),
        artifacts=ARTIFACTS,
    )

    assert plan.to_rebuild == ()
    assert plan.work_avoided == len(ARTIFACTS)
    assert all(target.reason == "no semantic change reached it" for target in plan.targets)


def test_meaning_change_still_rebuilds_the_same_dependency_radius() -> None:
    diff = _diff(
        [_unit("ku_warranty", "Warranty is two years.", evidence="ev_old", page=17)],
        [_unit("ku_warranty", "Warranty is three years.", evidence="ev_old", page=17)],
    )

    assert semantic_impact_seeds(diff) == ("ku_warranty",)
    plan = plan_semantic_recompilation(
        diff=diff,
        graph=_graph("ku_warranty"),
        artifacts=ARTIFACTS,
    )

    assert set(plan.to_rebuild) == {"chunk_a", "workflow_a"}
    assert "chunk_unrelated" not in plan.to_rebuild


def test_move_plus_meaning_change_is_semantic_because_meaning_changed() -> None:
    diff = _diff(
        [_unit("ku_warranty", "Warranty is two years.", evidence="ev_old", page=17)],
        [_unit("ku_warranty", "Warranty is three years.", evidence="ev_new", page=18)],
    )

    kinds = {change.kind for change in diff.changes}
    assert ChangeKind.EVIDENCE_MOVED in kinds
    assert ChangeKind.MODIFIED_CLAIM in kinds
    assert semantic_impact_seeds(diff) == ("ku_warranty",)

    plan = plan_semantic_recompilation(
        diff=diff,
        graph=_graph("ku_warranty"),
        artifacts=ARTIFACTS,
    )
    assert set(plan.to_rebuild) == {"chunk_a", "workflow_a"}


def test_unresolved_identity_remains_fail_closed_and_rebuilds_candidates_consumers() -> None:
    before = [
        _unit("ku_left", "Warranty is two years.", evidence="ev_left", page=17),
        _unit("ku_right", "Warranty is two years.", evidence="ev_right", page=17),
    ]
    after = [_unit("ku_incoming", "Warranty is three years.", evidence="ev_new", page=18)]
    diff = _diff(before, after)

    assert diff.unresolved
    assert semantic_impact_seeds(diff) == ()

    plan = plan_semantic_recompilation(
        diff=diff,
        graph=_graph("ku_left", "ku_right"),
        artifacts=ARTIFACTS,
    )

    assert set(plan.unresolved) == {"chunk_a", "workflow_a"}
    assert set(plan.to_rebuild) == {"chunk_a", "workflow_a"}
    assert "chunk_unrelated" not in plan.to_rebuild


def test_positional_split_avoids_legacy_work_without_breaking_full_rebuild_equivalence() -> None:
    """The product claim needs both halves: less work and no stale escape."""
    diff = _diff(
        [_unit("ku_warranty", "Warranty is two years.", evidence="ev_old", page=17)],
        [_unit("ku_warranty", "Warranty is two years.", evidence="ev_new", page=18)],
    )
    graph = _graph("ku_warranty")

    legacy = plan_recompilation(diff=diff, graph=graph, artifacts=ARTIFACTS)
    challenger = plan_semantic_recompilation(diff=diff, graph=graph, artifacts=ARTIFACTS)

    assert set(legacy.to_rebuild) == {"chunk_a", "workflow_a"}
    assert challenger.to_rebuild == ()
    assert challenger.work_avoided > legacy.work_avoided

    # A pure evidence move does not change the semantic content of any derived
    # artifact. Therefore the full rebuild after the move equals the carried
    # artifact content from before the move.
    full = {
        artifact: content_hash({"artifact": artifact, "semantic_value": "two years"})
        for artifact in ARTIFACTS
    }
    carried = dict(full)

    report = verify_equivalence(
        full_rebuild=full,
        selective_rebuild={},
        carried_over=carried,
        plan=challenger,
    )

    assert report.equivalent is True
    assert report.stale_left_behind == ()
    assert report.unexpectedly_rebuilt == ()
