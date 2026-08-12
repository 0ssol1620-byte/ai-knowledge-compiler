"""Candidate tiers, signal availability, the assignment, and the baseline arm."""

from __future__ import annotations

import itertools

import pytest
from akc_absorption.alignment import (
    ALIGNMENT_SIGNAL_NAMES,
    AlignmentContext,
    CandidateTier,
    classify_tier,
    compatibility,
    type_compatibility,
)
from akc_absorption.assignment import max_weight_assignment
from akc_absorption.baseline_xversion import baseline_diff
from akc_absorption.element_model import (
    DocumentElement,
    ElementIndex,
    ElementType,
    numeric_tokens,
)


def _element(
    logical_id: str,
    text: str,
    *,
    order: int = 0,
    page: int = 0,
    kind: ElementType = ElementType.TEXT,
    path: tuple[str, ...] = ("section_1",),
    table_key: str = "",
    binds_to: str = "",
) -> DocumentElement:
    top = 100 + order * 100
    return DocumentElement(
        element_id=f"el_{logical_id}",
        version_id="dv_test",
        element_type=kind,
        logical_id=logical_id,
        text=text,
        structural_path=path,
        page_index=page,
        bbox1000=(100, top, 900, top + 80),
        order_index=order,
        table_key=table_key,
        binds_to=binds_to,
    )


def _pair(before: list[DocumentElement], after: list[DocumentElement]):
    before_index = ElementIndex.of("dv_before", before)
    after_index = ElementIndex.of("dv_after", after)
    return before_index, after_index, AlignmentContext.build(before_index, after_index)


# -- assignment -------------------------------------------------------------


@pytest.mark.parametrize("size", [1, 2, 3, 4])
def test_assignment_matches_brute_force(size: int) -> None:
    """A weaker matcher would understate the baseline, which §0.2 forbids."""
    weights = [
        [((row * 7 + column * 13) % 11) / 10.0 for column in range(size)]
        for row in range(size)
    ]
    assignment = max_weight_assignment(weights)
    achieved = sum(weights[row][column] for row, column in assignment.items())
    best = max(
        sum(weights[row][order[row]] for row in range(size))
        for order in itertools.permutations(range(size))
    )
    assert achieved == pytest.approx(best)


def test_assignment_handles_rectangular_and_empty_matrices() -> None:
    assert max_weight_assignment([]) == {}
    assert max_weight_assignment([[]]) == {}
    rectangular = max_weight_assignment([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]])
    assert len(rectangular) == 2
    assert sorted(rectangular.values()) == [0, 1]


def test_ragged_matrix_is_rejected() -> None:
    with pytest.raises(ValueError, match="same length"):
        max_weight_assignment([[1.0, 2.0], [1.0]])


# -- element model ----------------------------------------------------------


def test_content_hash_ignores_position_but_not_type() -> None:
    here = _element("a", "same words", order=0, page=0)
    moved = _element("a", "same words", order=5, page=3)
    retyped = _element("a", "same words", kind=ElementType.CAPTION)
    assert here.content_hash == moved.content_hash
    assert here.content_hash != retyped.content_hash


def test_duplicate_logical_ids_in_one_version_are_rejected() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        ElementIndex.of("dv", [_element("a", "one"), _element("a", "two", order=1)])


def test_numeric_tokens_keep_order_and_canonical_form() -> None:
    assert numeric_tokens("1,200 and 3.50 and +7") == ("1200", "3.5", "7")
    assert numeric_tokens("no numbers here") == ()


# -- tiers and signals ------------------------------------------------------


def test_identical_content_reaches_the_exact_tier_and_suppresses_position() -> None:
    before = _element("a", "the clause text", order=0, page=0)
    after = _element("b", "the clause text", order=6, page=4)
    before_index, after_index, context = _pair([before], [after])
    assert (
        classify_tier(before, after, before_index=before_index, after_index=after_index)
        is CandidateTier.EXACT_CONTENT
    )
    present, missing, _ = compatibility(
        before, after, before_index=before_index, after_index=after_index, context=context
    )
    assert missing["align_spatial"] == "NOT_APPLICABLE"
    assert missing["align_context"] == "NOT_APPLICABLE"
    assert present["align_content"] == 1.0


def test_duplicate_content_does_not_reach_the_exact_tier() -> None:
    """Two identical rows make an exact-content match a coin flip."""
    before_a = _element("a", "same row", order=0)
    before_b = _element("b", "same row", order=1)
    after = _element("c", "same row", order=0)
    before_index = ElementIndex.of("dv_before", [before_a, before_b])
    after_index = ElementIndex.of("dv_after", [after])
    assert (
        classify_tier(
            before_a, after, before_index=before_index, after_index=after_index
        )
        is not CandidateTier.EXACT_CONTENT
    )


def test_incompatible_types_are_never_candidates() -> None:
    before = _element("a", "row one", kind=ElementType.TABLE_ROW)
    after = _element("b", "a figure", kind=ElementType.FIGURE)
    before_index, after_index, _ = _pair([before], [after])
    assert (
        classify_tier(before, after, before_index=before_index, after_index=after_index)
        is CandidateTier.INCOMPATIBLE
    )
    assert type_compatibility(ElementType.TABLE_ROW, ElementType.FIGURE) == 0.0
    assert type_compatibility(ElementType.TEXT, ElementType.FOOTNOTE) == 0.5


def test_a_missing_box_is_absent_rather_than_zero() -> None:
    before = DocumentElement(
        element_id="el_a",
        version_id="dv",
        element_type=ElementType.TEXT,
        logical_id="a",
        text="one",
        bbox1000=None,
        order_index=0,
    )
    after = _element("b", "two", order=0)
    before_index, after_index, context = _pair([before], [after])
    present, missing, _ = compatibility(
        before, after, before_index=before_index, after_index=after_index, context=context
    )
    assert "align_spatial" not in present
    assert missing["align_spatial"] == "NOT_APPLICABLE"


def test_a_disabled_signal_is_absent_rather_than_zero() -> None:
    before = _element("a", "one", order=0)
    after = _element("b", "two", order=0)
    before_index, after_index, context = _pair([before], [after])
    present, missing, _ = compatibility(
        before,
        after,
        before_index=before_index,
        after_index=after_index,
        context=context,
        enabled=frozenset(ALIGNMENT_SIGNAL_NAMES) - {"align_content"},
    )
    assert "align_content" not in present
    assert missing["align_content"] == "NOT_APPLICABLE"


def test_table_key_disagreement_is_a_structural_zero() -> None:
    before = _element("a", "10 | 20", kind=ElementType.TABLE_ROW, table_key="latency")
    after = _element("b", "10 | 20", kind=ElementType.TABLE_ROW, table_key="uptime")
    before_index, after_index, context = _pair([before], [after])
    present, _, _ = compatibility(
        before, after, before_index=before_index, after_index=after_index, context=context
    )
    assert present["align_structural"] == 0.0


# -- baseline ---------------------------------------------------------------


def test_the_baseline_aligns_an_unchanged_version_perfectly() -> None:
    elements = [_element(f"a{index}", f"clause {index}", order=index) for index in range(4)]
    after = [_element(f"b{index}", f"clause {index}", order=index) for index in range(4)]
    before_index = ElementIndex.of("dv_before", elements)
    after_index = ElementIndex.of("dv_after", after)
    result = baseline_diff(before_index, after_index)
    assert len(result.pairs) == 4
    assert not result.added and not result.removed
    assert not result.changed_logical_ids


def test_the_baseline_never_abstains() -> None:
    """The property that makes it the baseline. It forces an assignment."""
    before_index = ElementIndex.of("dv_before", [_element("a", "wholly different text")])
    after_index = ElementIndex.of("dv_after", [_element("b", "entirely other words")])
    result = baseline_diff(before_index, after_index, accept_threshold=0.0)
    assert len(result.pairs) == 1
    assert not result.added and not result.removed


def test_the_baseline_reports_added_and_removed_on_empty_sides() -> None:
    populated = ElementIndex.of("dv", [_element("a", "one")])
    empty = ElementIndex.of("dv_empty", [])
    assert baseline_diff(populated, empty).removed == ("a",)
    assert baseline_diff(empty, populated).added == ("a",)
