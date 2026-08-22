"""Type-specific reasoning, and above all the guard on its two demotions.

`RENDERING_ONLY` and `VALUE_ORDER_CHANGE` are the only refinements that say "no
meaning changed". Everything else in this module is arithmetic; those two are
where a bug ships a stale answer.
"""

from __future__ import annotations

from akc_absorption.element_model import ElementType
from akc_absorption.type_reasoning import (
    CRITICAL_REFINEMENTS,
    ChangeRefinement,
    RefinedChange,
    refine,
    refine_pair,
)
from akc_cir.semantic_diff import ChangeKind, DiffLevel, SemanticChange, SemanticDiff


def test_optical_degradation_is_demoted_when_the_numbers_agree() -> None:
    before = "The supplier must deliver the widget within 45 days."
    after = "The supplier rnust cleliver the vviclget vvithin 45 clays."
    primary, fired = refine_pair(before, after)
    assert primary is ChangeRefinement.RENDERING_ONLY
    assert fired == (ChangeRefinement.RENDERING_ONLY,)


def test_a_digit_that_changed_is_never_demoted() -> None:
    """The guard. Folding must not be reachable when a number moved."""
    before = "The supplier must deliver the widget within 45 days."
    after = "The supplier rnust cleliver the vviclget vvithin 15 clays."
    primary, fired = refine_pair(before, after)
    assert primary is not ChangeRefinement.RENDERING_ONLY
    assert ChangeRefinement.NUMERIC_VALUE_CHANGE in fired
    assert primary in CRITICAL_REFINEMENTS


def test_may_to_must_is_a_modality_change_and_not_a_date_change() -> None:
    """`may` is also a month name. Reading it as one would misfile the change."""
    primary, fired = refine_pair(
        "The buyer may inspect the goods.", "The buyer must inspect the goods."
    )
    assert primary is ChangeRefinement.MODALITY_CHANGE
    assert ChangeRefinement.DATE_PERIOD_CHANGE not in fired


def test_a_real_may_date_is_still_a_date_change() -> None:
    primary, fired = refine_pair(
        "Effective 1 may 2026 the policy applies.",
        "Effective 1 june 2026 the policy applies.",
    )
    assert ChangeRefinement.DATE_PERIOD_CHANGE in fired
    assert primary is ChangeRefinement.DATE_PERIOD_CHANGE


def test_exception_clause_addition_is_critical() -> None:
    primary, _ = refine_pair(
        "The supplier shall deliver within 30 days.",
        "Except where Article 2 applies, the supplier shall deliver within 30 days.",
    )
    assert primary is ChangeRefinement.EXCEPTION_SCOPE_CHANGE
    assert primary in CRITICAL_REFINEMENTS


def test_effective_year_change_is_critical() -> None:
    primary, _ = refine_pair(
        "The term runs from the effective date 2026-03-01.",
        "The term runs from the effective date 2027-03-01.",
    )
    assert primary in CRITICAL_REFINEMENTS


def test_reordered_values_alone_are_a_move_not_an_edit() -> None:
    primary, fired = refine_pair("alpha 10 beta 20", "beta 20 alpha 10")
    assert primary is ChangeRefinement.VALUE_ORDER_CHANGE
    assert not RefinedChange(
        kind=ChangeKind.MODIFIED_CLAIM,
        logical_id="x",
        refinement=primary,
        fired=fired,
    ).semantic


def test_reordered_values_with_changed_words_are_an_edit() -> None:
    primary, fired = refine_pair("alpha 10 beta 20", "gamma 20 alpha 10")
    assert ChangeRefinement.VALUE_ORDER_CHANGE in fired
    assert primary is ChangeRefinement.TEXT_EDIT
    assert RefinedChange(
        kind=ChangeKind.MODIFIED_CLAIM,
        logical_id="x",
        refinement=primary,
        fired=fired,
    ).semantic


def test_formula_rendering_markup_is_not_a_change() -> None:
    primary, _ = refine_pair(
        "credit = penalty * (target - achieved) / 100",
        "credit  =  penalty*(target-achieved)/100",
        element_type=ElementType.FORMULA,
    )
    assert primary is ChangeRefinement.RENDERING_ONLY


def test_a_plain_wording_change_stays_a_change() -> None:
    """Nothing here can prove a wording edit is meaningless, so it is not demoted."""
    primary, _ = refine_pair(
        "The buyer shall inspect the goods.",
        "The buyer shall inspect the recieved goods.",
    )
    assert primary is ChangeRefinement.TEXT_EDIT
    assert primary not in CRITICAL_REFINEMENTS


def test_refine_leaves_non_modified_kinds_alone() -> None:
    diff = SemanticDiff(
        level=DiffLevel.GRAPH,
        content_changed=True,
        changes=(
            SemanticChange(kind=ChangeKind.EVIDENCE_MOVED, logical_id="a"),
            SemanticChange(kind=ChangeKind.UNIT_ADDED, logical_id="b"),
            SemanticChange(
                kind=ChangeKind.MODIFIED_CLAIM,
                logical_id="c",
                before="value 10",
                after="value 11",
            ),
        ),
    )
    refined = {item.logical_id: item for item in refine(diff)}
    assert refined["a"].refinement is None
    assert refined["a"].semantic is False
    assert refined["b"].refinement is None
    assert refined["b"].semantic is True
    assert refined["c"].refinement is ChangeRefinement.NUMERIC_VALUE_CHANGE
    assert refined["c"].critical is True
