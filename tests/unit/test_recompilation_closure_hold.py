"""A truncated closure proves nothing about what it did not reach."""

from __future__ import annotations

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.recompilation import ArtifactState, plan_recompilation
from akc_cir.semantic_diff import DiffLevel, DocumentShape, UnitSnapshot, diff_documents

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64


def _unit(text: str) -> UnitSnapshot:
    return UnitSnapshot(
        logical_id="ku_a",
        text=text,
        document_path=("Warranty", "Coverage"),
        anchor="4.2 Exceptions",
        neighbour_anchors=("4.1 Scope", "4.3 Claims"),
    )


def _plan(max_depth: int | None):
    diff = diff_documents(
        before_sha256=A,
        after_sha256=B,
        level=DiffLevel.SEMANTIC,
        before_shape=DocumentShape(),
        after_shape=DocumentShape(),
        before_units=[_unit("The warranty covers parts for two years from delivery.")],
        after_units=[_unit("The warranty covers parts for three years from delivery.")],
    )
    graph = DependencyGraph(
        [
            DependencyEdge("mid", "ku_a", EdgeType.DEPENDS_ON),
            DependencyEdge("far", "mid", EdgeType.DEPENDS_ON),
            DependencyEdge("other", "ku_unrelated", EdgeType.DEPENDS_ON),
        ]
    )
    return plan_recompilation(
        diff=diff, graph=graph, artifacts=["mid", "far", "other"], max_depth=max_depth
    )


def test_a_truncated_walk_rebuilds_everything_it_did_not_reach() -> None:
    plan = _plan(1)

    assert plan.closure_uncertain
    assert set(plan.to_rebuild) == {"mid", "far", "other"}
    assert plan.explain("far") == (
        "closure truncated at max_depth; rebuilt rather than assumed current"
    )


def test_an_untruncated_walk_is_unchanged() -> None:
    plan = _plan(None)

    assert set(plan.to_rebuild) == {"mid", "far"}
    assert plan.explain("other") == "no change reached it"
    assert dict((t.artifact_id, t.state) for t in plan.targets)["other"] is ArtifactState.CURRENT


def test_closure_uncertain_is_false_without_truncation() -> None:
    assert not _plan(None).closure_uncertain
    assert not _plan(5).closure_uncertain
