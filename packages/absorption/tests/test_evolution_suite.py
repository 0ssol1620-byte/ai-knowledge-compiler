"""The fixture EXP-0101 and EXP-0104 both stand on.

A silently broken generator produces a whole experiment's worth of numbers that
mean nothing, so the properties asserted here are the ones a metric would not
notice were false: determinism, non-empty mutations, and gold labels that match
what was actually done to the document.
"""

from __future__ import annotations

import pytest
from akc_absorption.evolution_suite import (
    CRITICAL_MUTATIONS,
    LAYOUT_ONLY_MUTATIONS,
    SEMANTIC_MUTATIONS,
    MutationClass,
    build_suite,
    suite_manifest_sha256,
)


def test_eleven_mutation_classes_exactly() -> None:
    """Blueprint §9.7 lists eleven. A twelfth silently changes every denominator."""
    assert len(list(MutationClass)) == 11


def test_every_document_is_crossed_with_every_class() -> None:
    cases = build_suite(documents=3)
    assert len(cases) == 3 * 11
    per_class = {mutation: 0 for mutation in MutationClass}
    for case in cases:
        per_class[case.mutation] += 1
    assert set(per_class.values()) == {3}


def test_the_suite_is_deterministic() -> None:
    first = build_suite(documents=4)
    second = build_suite(documents=4)
    assert suite_manifest_sha256(first) == suite_manifest_sha256(second)
    assert [case.after.content_sha256 for case in first] == [
        case.after.content_sha256 for case in second
    ]


def test_every_mutation_actually_changes_the_document() -> None:
    """A no-op mutation would be scored as a permanent miss by every arm."""
    for case in build_suite(documents=5):
        assert case.before.content_sha256 != case.after.content_sha256, case.case_id


def test_gold_labels_partition_the_classes_consistently() -> None:
    assert not SEMANTIC_MUTATIONS & LAYOUT_ONLY_MUTATIONS
    assert CRITICAL_MUTATIONS <= SEMANTIC_MUTATIONS
    for case in build_suite(documents=2):
        assert case.gold.semantic_change == (case.mutation in SEMANTIC_MUTATIONS)
        assert case.gold.critical == (case.mutation in CRITICAL_MUTATIONS)
        assert case.gold.layout_only == (case.mutation in LAYOUT_ONLY_MUTATIONS)


def test_semantic_classes_name_the_units_they_changed() -> None:
    for case in build_suite(documents=4):
        if case.mutation in SEMANTIC_MUTATIONS:
            assert case.gold.changed_logical_ids, case.case_id
        else:
            assert not case.gold.changed_logical_ids, case.case_id


def test_layout_classes_leave_every_unit_text_alone() -> None:
    """The definition of the class, checked rather than asserted in a docstring."""
    for case in build_suite(documents=4):
        if case.mutation is not MutationClass.OCR_DEGRADATION_ONLY and (
            case.mutation in LAYOUT_ONLY_MUTATIONS
        ):
            before = {unit.anchor: unit.text for unit in case.before.units}
            after = {unit.anchor: unit.text for unit in case.after.units}
            assert before == after, case.case_id


def test_optical_degradation_never_touches_a_digit() -> None:
    for case in build_suite(documents=6):
        if case.mutation is not MutationClass.OCR_DEGRADATION_ONLY:
            continue
        before = {unit.anchor: unit.text for unit in case.before.units}
        for unit in case.after.units:
            original = before[unit.anchor]
            digits_before = [ch for ch in original if ch.isdigit()]
            digits_after = [ch for ch in unit.text if ch.isdigit()]
            assert digits_before == digits_after, case.case_id


def test_clause_split_adds_exactly_one_unit() -> None:
    for case in build_suite(documents=3):
        if case.mutation is not MutationClass.CLAUSE_SPLIT_MERGE:
            continue
        assert len(case.after.units) == len(case.before.units) + 1
        assert len(case.gold.added) == 1


def test_aligned_pairs_cover_every_surviving_anchor() -> None:
    for case in build_suite(documents=3):
        before_anchors = {unit.anchor for unit in case.before.units}
        after_anchors = {unit.anchor for unit in case.after.units}
        assert len(case.gold.aligned_pairs) == len(before_anchors & after_anchors)


def test_a_suite_needs_at_least_one_document() -> None:
    with pytest.raises(ValueError, match="at least one seed document"):
        build_suite(documents=0)
