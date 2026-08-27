"""A run must not return success while a stale artifact is CURRENT.

The defect this gate exists for was green: a selective rebuild carried two
artifacts forward as CURRENT, the equivalence check was not run because no full
rebuild existed to run it against, and the corpus was published wrong.

The tests below are ordered the way the gate is, and each one is written to fail
if the corresponding precondition is quietly dropped. The two that matter most
are the ones asserting a **refusal**: any gate can pass things.
"""

from __future__ import annotations

import pytest
from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.promotion_gate import (
    GateOutcome,
    GateStep,
    artifact_input_fingerprint,
    evaluate_promotion_gate,
)
from akc_cir.recompilation import (
    ArtifactState,
    EquivalenceReport,
    RecompilationPlan,
    RecompilationTarget,
)
from akc_cir.semantic_diff import (
    ChangeKind,
    DiffLevel,
    DocumentShape,
    SemanticChange,
    SemanticDiff,
    UnitSnapshot,
    diff_documents,
)

ART = "artifact:section:ku_a"


def _shape(blocks: int = 2) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset({("Intro",)}),
        block_count=blocks,
        table_shapes=(),
        figure_refs=frozenset(),
    )


def _diff(before_text: str, after_text: str) -> SemanticDiff:
    return diff_documents(
        before_sha256="sha256:" + "1" * 64,
        after_sha256="sha256:" + "2" * 64,
        level=DiffLevel.SEMANTIC,
        before_shape=_shape(),
        after_shape=_shape(),
        before_units=[UnitSnapshot(logical_id="ku_a", text=before_text)],
        after_units=[UnitSnapshot(logical_id="ku_a", text=after_text)],
        source="gate-test",
    )


def _graph() -> DependencyGraph:
    return DependencyGraph([DependencyEdge(ART, "ku_a", EdgeType.DEPENDS_ON)])


def _plan(state: ArtifactState) -> RecompilationPlan:
    return RecompilationPlan(
        change_id="chg_test",
        targets=(RecompilationTarget(artifact_id=ART, state=state, reason="test"),),
        total_artifacts=1,
    )


def _step(report, step: GateStep):
    return next(s for s in report.steps if s.step is step)


# --- the invariant this module is named for ---------------------------------


def test_a_current_artifact_whose_inputs_moved_blocks_promotion() -> None:
    """The exact defect: the plan says current, the inputs say otherwise."""
    diff = _diff("two years", "three years")
    report = evaluate_promotion_gate(
        diff=diff,
        graph=_graph(),
        plan=_plan(ArtifactState.CURRENT),
        rebuilt=[],
        current_input_fingerprints={
            ART: artifact_input_fingerprint(["ku_a"], {"ku_a": "hash-after"})
        },
        expected_input_fingerprints={
            ART: artifact_input_fingerprint(["ku_a"], {"ku_a": "hash-before"})
        },
        # The edge defaults to every channel, so the gate requires the caller to
        # say the shape facts are covered before it will trust the digest.
        structural_coverage=[ART],
    )
    assert report.promotable is False
    failed = _step(report, GateStep.NO_STALE_CURRENT)
    assert failed.outcome is GateOutcome.FAIL
    assert failed.offending == (ART,), "a refusal that does not name the artifact is unactionable"


def test_a_current_artifact_whose_inputs_held_is_promotable() -> None:
    diff = _diff("two years", "three years")
    same = artifact_input_fingerprint(["ku_a"], {"ku_a": "hash-unchanged"})
    report = evaluate_promotion_gate(
        diff=diff,
        graph=_graph(),
        plan=_plan(ArtifactState.CURRENT),
        rebuilt=[],
        current_input_fingerprints={ART: same},
        expected_input_fingerprints={ART: same},
        structural_coverage=[ART],
    )
    assert report.promotable is True
    assert report.checked_current_artifacts == 1


def test_an_unchecked_current_artifact_fails_closed() -> None:
    """Silence about an artifact is not evidence about it."""
    report = evaluate_promotion_gate(
        diff=_diff("two years", "three years"),
        graph=_graph(),
        plan=_plan(ArtifactState.CURRENT),
        rebuilt=[],
        current_input_fingerprints={},
        expected_input_fingerprints={},
    )
    assert report.promotable is False
    assert _step(report, GateStep.NO_STALE_CURRENT).outcome is GateOutcome.FAIL
    assert report.unverifiable_current_artifacts == (ART,)


# --- the preconditions, in order --------------------------------------------


def test_a_seed_outside_the_graph_stops_everything() -> None:
    """If the graph does not contain the changed unit, nothing can be said."""
    report = evaluate_promotion_gate(
        diff=_diff("two years", "three years"),
        graph=DependencyGraph([DependencyEdge("artifact:other", "ku_z", EdgeType.DEPENDS_ON)]),
        plan=_plan(ArtifactState.CURRENT),
        rebuilt=[],
    )
    assert report.promotable is False
    assert _step(report, GateStep.CHANGES_ACCOUNTED).outcome is GateOutcome.FAIL


def test_a_planned_artifact_that_was_never_built_blocks_promotion() -> None:
    report = evaluate_promotion_gate(
        diff=_diff("two years", "three years"),
        graph=_graph(),
        plan=_plan(ArtifactState.STALE),
        rebuilt=[],
    )
    assert report.promotable is False
    step = _step(report, GateStep.RECOMPILE_COMPLETE)
    assert step.outcome is GateOutcome.FAIL
    assert step.offending == (ART,)


def test_a_selective_build_with_no_check_of_any_kind_is_refused() -> None:
    """Neither an oracle nor fingerprints is not 'nothing went wrong'."""
    report = evaluate_promotion_gate(
        diff=_diff("two years", "three years"),
        graph=_graph(),
        plan=_plan(ArtifactState.STALE),
        rebuilt=[ART],
    )
    assert report.promotable is False
    assert _step(report, GateStep.INTEGRITY).outcome is GateOutcome.FAIL


def test_a_failed_equivalence_check_blocks_promotion() -> None:
    report = evaluate_promotion_gate(
        diff=_diff("two years", "three years"),
        graph=_graph(),
        plan=_plan(ArtifactState.STALE),
        rebuilt=[ART],
        equivalence=EquivalenceReport(equivalent=False, compared=1, diverged=(ART,)),
    )
    assert report.promotable is False
    assert _step(report, GateStep.INTEGRITY).outcome is GateOutcome.FAIL


def test_steps_after_a_failure_are_not_reached_rather_than_passed() -> None:
    """A receipt must not read as if checks ran after the run was already lost."""
    report = evaluate_promotion_gate(
        diff=_diff("two years", "three years"),
        graph=_graph(),
        plan=_plan(ArtifactState.STALE),
        rebuilt=[],
    )
    later = [
        _step(report, GateStep.INTEGRITY),
        _step(report, GateStep.NO_STALE_CURRENT),
        _step(report, GateStep.PROMOTABLE),
    ]
    assert all(s.outcome is GateOutcome.NOT_REACHED for s in later)
    assert all(s.outcome is not GateOutcome.PASS for s in later)


# --- the fingerprint itself --------------------------------------------------


def test_reordering_inputs_changes_the_fingerprint() -> None:
    """Sorting here would hide exactly the structural movement channels track."""
    hashes = {"ku_a": "h1", "ku_b": "h2"}
    assert artifact_input_fingerprint(["ku_a", "ku_b"], hashes) != (
        artifact_input_fingerprint(["ku_b", "ku_a"], hashes)
    )


def test_a_removed_input_changes_the_fingerprint() -> None:
    """Absence is recorded, not skipped, or a shorter list would hash as itself."""
    with_both = artifact_input_fingerprint(["ku_a", "ku_b"], {"ku_a": "h1", "ku_b": "h2"})
    with_missing = artifact_input_fingerprint(["ku_a", "ku_b"], {"ku_a": "h1"})
    assert with_both != with_missing


# --- the unresolved path feeds the gate too ----------------------------------


def test_an_unresolved_identity_seeds_the_accounting_step() -> None:
    """Both sides of an unsettled correspondence must resolve in the graph."""
    diff = SemanticDiff(
        level=DiffLevel.SEMANTIC,
        content_changed=True,
        changes=(
            SemanticChange(
                kind=ChangeKind.IDENTITY_UNRESOLVED,
                logical_id="ku_incoming",
                candidates=("ku_a",),
            ),
        ),
        change_id="chg_unresolved",
    )
    report = evaluate_promotion_gate(
        diff=diff,
        graph=_graph(),  # contains ku_a but not ku_incoming
        plan=_plan(ArtifactState.CURRENT),
        rebuilt=[],
    )
    step = _step(report, GateStep.CHANGES_ACCOUNTED)
    assert step.outcome is GateOutcome.FAIL
    assert "ku_incoming" in step.offending


@pytest.mark.parametrize("state", [ArtifactState.STALE, ArtifactState.UNRESOLVED])
def test_unresolved_is_treated_as_needing_a_rebuild_not_as_current(state) -> None:
    report = evaluate_promotion_gate(
        diff=_diff("two years", "three years"),
        graph=_graph(),
        plan=_plan(state),
        rebuilt=[ART],
        equivalence=EquivalenceReport(equivalent=True, compared=1),
    )
    assert report.promotable is True
    assert _step(report, GateStep.RECOMPILE_COMPLETE).outcome is GateOutcome.PASS


# --- the structural blind spot, found by the change-space sweep ---------------
#
# The first version of this gate passed 400 of 400 structural-only stale
# artifacts. Its fingerprint covered unit content, and a structural change is
# precisely the change that leaves unit content alone -- so the check matched,
# every time, on the one thing that had not moved. Both tests below fail against
# that version.


def _structural_graph() -> DependencyGraph:
    from akc_cir.dependency import DependencyChannel

    return DependencyGraph(
        [
            DependencyEdge(
                "artifact:reading-order:doc",
                "ku_a",
                EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.STRUCTURAL}),
            )
        ]
    )


def _structural_plan() -> RecompilationPlan:
    return RecompilationPlan(
        change_id="chg_structural",
        targets=(
            RecompilationTarget(
                artifact_id="artifact:reading-order:doc",
                state=ArtifactState.CURRENT,
                reason="test",
            ),
        ),
        total_artifacts=1,
    )


def test_shape_movement_alone_changes_the_fingerprint() -> None:
    """Unit content identical, document shape different: the digest must differ."""
    same_units = {"ku_a": "h1"}
    before = artifact_input_fingerprint(
        ["ku_a"], same_units, structural={"blocks": 4, "order": ["ku_a"]}
    )
    after = artifact_input_fingerprint(
        ["ku_a"], same_units, structural={"blocks": 7, "order": ["ku_a"]}
    )
    assert before != after


def test_a_structural_artifact_without_declared_coverage_is_unverifiable() -> None:
    """A caller that forgets the shape facts is refused, not believed.

    The fingerprints here match, and under a content-only check that is a pass.
    It is not one: nothing in a content fingerprint can speak to shape.
    """
    same = artifact_input_fingerprint(["ku_a"], {"ku_a": "h1"})
    report = evaluate_promotion_gate(
        diff=_diff("unchanged text", "unchanged text"),
        graph=_structural_graph(),
        plan=_structural_plan(),
        rebuilt=[],
        current_input_fingerprints={"artifact:reading-order:doc": same},
        expected_input_fingerprints={"artifact:reading-order:doc": same},
        structural_coverage=[],
    )
    assert report.promotable is False
    assert report.unverifiable_current_artifacts == ("artifact:reading-order:doc",)


def test_a_structural_artifact_with_declared_coverage_is_checked() -> None:
    same = artifact_input_fingerprint(
        ["ku_a"], {"ku_a": "h1"}, structural={"blocks": 4, "order": ["ku_a"]}
    )
    report = evaluate_promotion_gate(
        diff=_diff("unchanged text", "unchanged text"),
        graph=_structural_graph(),
        plan=_structural_plan(),
        rebuilt=[],
        current_input_fingerprints={"artifact:reading-order:doc": same},
        expected_input_fingerprints={"artifact:reading-order:doc": same},
        structural_coverage=["artifact:reading-order:doc"],
    )
    assert report.promotable is True
    assert report.checked_current_artifacts == 1
