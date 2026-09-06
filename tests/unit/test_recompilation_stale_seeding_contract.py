"""Selective recompilation must not carry a stale artifact and call it CURRENT.

Two distinct fail-open paths were found on the Family B real-revision corpora,
and they are easy to confuse because they produce the same symptom: the run
reports success and an artifact is wrong.

  D1  an unsettled identity named only the *prior* candidates, so the incoming
      unit appeared in no change at all and nothing derived from it could be
      reached. This is the one that fired on real data -- two artifacts carried
      over on `Self-driving car`.

  D2  a structural change carries no `logical_id`, so it cannot seed a
      traversal, and an artifact aggregated over document position is carried
      over. Real, but demonstrated only synthetically: on every real pair
      measured, no artifact depended on the structure that changed.

They are pinned separately on purpose. Enabling the structural channel *also*
made the real corpus pass -- by rebuilding 87 artifacts of 334 instead of 20 --
which is a mask rather than a fix, and a suite that only asked "did the failure
go away" would have accepted it. Testing each seeding path against a case only
it can solve is what keeps that distinction enforced rather than remembered.
"""

from __future__ import annotations

import pytest
from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.recompilation import ArtifactState, plan_recompilation
from akc_cir.semantic_diff import (
    ChangeKind,
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)

TWO_YEARS = "The warranty period is two years from the date of delivery."
THREE_YEARS = "The warranty period is three years from the date of delivery."
OTHER = "Regulatory approval followed in several jurisdictions after 2020."


def _unit(logical_id: str, text: str) -> UnitSnapshot:
    return UnitSnapshot(logical_id=logical_id, text=text)


def _shape(block_count: int) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset({("Intro",)}),
        block_count=block_count,
        table_shapes=(),
        figure_refs=frozenset(),
    )


def _state(plan, artifact: str) -> ArtifactState:
    return next(t.state for t in plan.targets if t.artifact_id == artifact)


# --- D1: the unsettled identity names both sides ----------------------------


def _ambiguous_diff():
    """Two equally plausible priors and one incoming unit the resolver won't settle."""
    return diff_documents(
        before_sha256="sha256:" + "1" * 64,
        after_sha256="sha256:" + "2" * 64,
        level=DiffLevel.SEMANTIC,
        before_shape=_shape(2),
        after_shape=_shape(2),
        before_units=[_unit("ku_left", TWO_YEARS), _unit("ku_right", TWO_YEARS)],
        after_units=[_unit("ku_incoming", THREE_YEARS)],
        source="contract:ambiguous",
    )


def test_an_unsettled_identity_names_the_incoming_unit_not_only_the_priors() -> None:
    diff = _ambiguous_diff()
    unresolved = diff.unresolved
    assert len(unresolved) == 1
    assert unresolved[0].candidates == ("ku_left", "ku_right")
    assert unresolved[0].logical_id == "ku_incoming"


def test_naming_the_incoming_unit_is_still_not_a_modification() -> None:
    """The whole point of UNRESOLVED is that it asserts nothing about continuity."""
    diff = _ambiguous_diff()
    assert diff.changed_logical_ids == ()
    kinds = {c.kind for c in diff.changes}
    assert ChangeKind.MODIFIED_CLAIM not in kinds
    assert ChangeKind.UNIT_ADDED not in kinds
    assert ChangeKind.UNIT_REMOVED not in kinds


def test_an_artifact_derived_from_the_incoming_unit_is_not_carried_over() -> None:
    """The defect that fired on real data, in its smallest form."""
    diff = _ambiguous_diff()
    graph = DependencyGraph(
        [DependencyEdge("artifact:section:incoming", "ku_incoming", EdgeType.DEPENDS_ON)]
    )
    plan = plan_recompilation(
        diff=diff, graph=graph, artifacts=["artifact:section:incoming"]
    )
    assert _state(plan, "artifact:section:incoming") is not ArtifactState.CURRENT


def test_the_incoming_seed_can_be_switched_off_and_the_defect_returns() -> None:
    """A flag that changes nothing when toggled is not measuring what it claims."""
    diff = _ambiguous_diff()
    graph = DependencyGraph(
        [DependencyEdge("artifact:section:incoming", "ku_incoming", EdgeType.DEPENDS_ON)]
    )
    plan = plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=["artifact:section:incoming"],
        seed_unresolved_incoming=False,
    )
    assert _state(plan, "artifact:section:incoming") is ArtifactState.CURRENT


# --- D2: a structural change can seed a traversal ---------------------------


def _structure_only_diff():
    """Identical unit text on both sides; only the document's block count moves."""
    units = [_unit("ku_a", TWO_YEARS), _unit("ku_b", OTHER)]
    return diff_documents(
        before_sha256="sha256:" + "3" * 64,
        after_sha256="sha256:" + "4" * 64,
        level=DiffLevel.SEMANTIC,
        before_shape=_shape(2),
        after_shape=_shape(3),
        before_units=units,
        after_units=units,
        source="contract:structure-only",
    )


def test_a_structure_only_change_yields_no_semantic_seed() -> None:
    """Which is correct -- a block count is not a property of any one unit."""
    diff = _structure_only_diff()
    assert diff.changed_logical_ids == ()
    assert diff.structural_change_present is True
    assert diff.structural_scope == ("ku_a", "ku_b")


def test_the_structural_channel_is_what_lets_that_change_reach_an_artifact() -> None:
    diff = _structure_only_diff()
    graph = DependencyGraph(
        [
            DependencyEdge("artifact:ordered", "ku_a", EdgeType.DEPENDS_ON),
            DependencyEdge("artifact:ordered", "ku_b", EdgeType.DEPENDS_ON),
        ]
    )
    assert (
        _state(
            plan_recompilation(diff=diff, graph=graph, artifacts=["artifact:ordered"]),
            "artifact:ordered",
        )
        is ArtifactState.CURRENT
    ), "default is off, and the defect is still reachable -- that is the measured trade"
    assert (
        _state(
            plan_recompilation(
                diff=diff,
                graph=graph,
                artifacts=["artifact:ordered"],
                structural_channel=True,
            ),
            "artifact:ordered",
        )
        is ArtifactState.STALE
    )


def test_an_edge_that_disclaims_structure_stays_current_under_the_channel() -> None:
    """Precision is bought back by declaration, not assumed.

    Without this, enabling the channel would mean a full rebuild of any document
    whose structure moved, which is the blunt behaviour measured at 87 of 334
    artifacts on the confirmatory corpus.
    """
    from akc_cir.dependency import DependencyChannel

    diff = _structure_only_diff()
    graph = DependencyGraph(
        [
            DependencyEdge(
                "artifact:text-only",
                "ku_a",
                EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.SEMANTIC}),
            )
        ]
    )
    plan = plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=["artifact:text-only"],
        structural_channel=True,
    )
    assert _state(plan, "artifact:text-only") is ArtifactState.CURRENT


# --- the invariants neither fix may break -----------------------------------


def test_unchanged_content_is_still_all_current_under_both_fixes() -> None:
    diff = diff_documents(
        before_sha256="sha256:" + "5" * 64,
        after_sha256="sha256:" + "5" * 64,
        level=DiffLevel.SEMANTIC,
        before_shape=_shape(2),
        after_shape=_shape(2),
        before_units=[_unit("ku_a", TWO_YEARS)],
        after_units=[_unit("ku_a", TWO_YEARS)],
    )
    graph = DependencyGraph(
        [DependencyEdge("artifact:a", "ku_a", EdgeType.DEPENDS_ON)]
    )
    plan = plan_recompilation(
        diff=diff, graph=graph, artifacts=["artifact:a"], structural_channel=True
    )
    assert _state(plan, "artifact:a") is ArtifactState.CURRENT


@pytest.mark.parametrize("structural_channel", [False, True])
def test_the_same_pair_plans_identically_twice(structural_channel: bool) -> None:
    """Impact analysis that is not reproducible cannot be audited."""
    graph = DependencyGraph(
        [
            DependencyEdge("artifact:ordered", "ku_a", EdgeType.DEPENDS_ON),
            DependencyEdge("artifact:ordered", "ku_b", EdgeType.DEPENDS_ON),
        ]
    )

    def plan_once():
        return plan_recompilation(
            diff=_structure_only_diff(),
            graph=graph,
            artifacts=["artifact:ordered"],
            structural_channel=structural_channel,
        )

    first, second = plan_once(), plan_once()
    assert first.change_id == second.change_id
    assert [(t.artifact_id, t.state, t.reason) for t in first.targets] == [
        (t.artifact_id, t.state, t.reason) for t in second.targets
    ]
