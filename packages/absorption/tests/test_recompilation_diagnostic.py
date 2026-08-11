"""DIAG-B-01's counterfactuals, and the properties its verdict depends on.

The verdict says C3 is dominant and sufficient, C2 contributing but unnecessary,
C4 refuted. Each of those readings rests on a property of how the counterfactual
was constructed, and a construction bug would move the verdict without moving
anything visibly wrong. These are those properties.
"""

from __future__ import annotations

from akc_absorption.evolution_suite import MutationClass, build_suite
from akc_absorption.recompilation_diagnostic import (
    COUNTERFACTUALS,
    Cause,
    attribute_changed_set,
    diff_for,
    evidence_id_is_version_scoped,
    run_counterfactuals,
)
from akc_cir.identity import (
    CRITICAL_IDENTITY_SIGNALS,
    IDENTITY_SCHEME_VERSION,
    IDENTITY_SIGNAL_WEIGHTS,
    MERGE_THRESHOLD,
)
from akc_cir.semantic_diff import ChangeKind


def _case(mutation: MutationClass):
    return next(item for item in build_suite(documents=1) if item.mutation is mutation)


def test_every_counterfactual_is_declared_with_its_causes() -> None:
    outcomes = run_counterfactuals(_case(MutationClass.MAY_TO_MUST))
    assert set(outcomes) == set(COUNTERFACTUALS)


def test_running_the_diagnostic_mutates_no_core_constant() -> None:
    """Read-only is the contract's binding constraint, so it is asserted."""
    weights = dict(IDENTITY_SIGNAL_WEIGHTS)
    critical = frozenset(CRITICAL_IDENTITY_SIGNALS)
    threshold = MERGE_THRESHOLD
    scheme = IDENTITY_SCHEME_VERSION
    for mutation in (MutationClass.TABLE_CELL_NUMERIC_CHANGE, MutationClass.PURE_LAYOUT_MOVE):
        run_counterfactuals(_case(mutation))
    assert weights == IDENTITY_SIGNAL_WEIGHTS
    assert critical == CRITICAL_IDENTITY_SIGNALS
    assert threshold == MERGE_THRESHOLD
    assert scheme == IDENTITY_SCHEME_VERSION


def test_the_actual_arm_rebuilds_everything() -> None:
    """The number the whole diagnostic exists to explain."""
    outcomes = run_counterfactuals(_case(MutationClass.MAY_TO_MUST))
    assert outcomes["actual"].rebuild_fraction == 1.0
    assert outcomes["actual"].equivalent


def test_attribution_counts_ids_not_changes() -> None:
    """A unit reported by two kinds is `multiple`, not double-counted."""
    tally = attribute_changed_set(diff_for(_case(MutationClass.TABLE_CELL_NUMERIC_CHANGE)))
    counted = sum(value for key, value in tally.items() if key != "total")
    assert counted == tally["total"]
    assert tally["total"] > 0


def test_layout_only_mutations_are_attributed_entirely_to_evidence_moved() -> None:
    tally = attribute_changed_set(diff_for(_case(MutationClass.PURE_LAYOUT_MOVE)))
    assert tally.get("evidence_moved_only", 0) == tally["total"]


def test_c3_keeps_the_fail_closed_path() -> None:
    """A counterfactual that improved the number by deleting abstention would be void."""
    case = _case(MutationClass.SECTION_REORDERING)
    diff = diff_for(case)
    unresolved = sum(
        1 for change in diff.changes if change.kind is ChangeKind.IDENTITY_UNRESOLVED
    )
    outcomes = run_counterfactuals(case)
    if unresolved:
        # The unresolved changes carry no logical_id, so they cannot lower the
        # changed-id count; what matters is that the plan still sees them.
        assert outcomes["c3_semantic_channel_only"].equivalent


def test_c3_never_leaves_an_artifact_stale() -> None:
    """The verdict calls C3 safe. If that were false the verdict would invert."""
    for mutation in MutationClass:
        outcomes = run_counterfactuals(_case(mutation))
        assert outcomes["c3_semantic_channel_only"].stale_left_behind == 0, mutation
        assert outcomes["c3_semantic_channel_only"].equivalent, mutation


def test_c2_is_never_worse_than_actual_and_never_better_than_c3() -> None:
    for mutation in MutationClass:
        outcomes = run_counterfactuals(_case(mutation))
        assert (
            outcomes["c3_semantic_channel_only"].rebuild_fraction
            <= outcomes["c2_stable_evidence_ids"].rebuild_fraction
            <= outcomes["actual"].rebuild_fraction
        ), mutation


def test_c2_and_c3_together_equal_c3_alone() -> None:
    """The measurement behind 'C2 is not necessary'."""
    for mutation in MutationClass:
        outcomes = run_counterfactuals(_case(mutation))
        assert (
            outcomes["c2_and_c3"].rebuild_fraction
            == outcomes["c3_semantic_channel_only"].rebuild_fraction
        ), mutation


def test_c4_is_cheaper_and_unsafe_somewhere() -> None:
    """The refutation. If narrowing the rule were safe, C4 would not be refuted."""
    unsafe = 0
    for mutation in MutationClass:
        outcomes = run_counterfactuals(_case(mutation))
        assert (
            outcomes["c4_no_document_rollup"].rebuild_fraction
            <= outcomes["c3_semantic_channel_only"].rebuild_fraction
        ), mutation
        if not outcomes["c4_no_document_rollup"].equivalent:
            unsafe += 1
    assert unsafe > 0


def test_c1_is_answered_as_a_design_question_not_a_rate() -> None:
    answer = evidence_id_is_version_scoped()
    assert answer["cause"] == Cause.C1_EVIDENCE_IDENTITY_DESIGN.value
    assert answer["answer"].startswith("No")
    assert "not_concluded" in answer
