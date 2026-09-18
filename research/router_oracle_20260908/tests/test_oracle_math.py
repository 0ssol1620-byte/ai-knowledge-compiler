"""Oracle math on tiny synthetic matrices.

The invariants that must hold whatever the arena data says:

  * the permitted-plan Oracle is never worse than any fixed plan it chose from
  * missing-as-failure is never better than the intersection cohort
  * the frozen reconciler is deterministic and never reads a score
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oracle import (
    Surface,
    build_plans,
    document_family,
    elementwise_forbidden,
    summarize,
)
from reconciler import UNRESOLVED, normalize, select, similarity


def make_surface(loss: dict[str, dict[str, float]], classes: dict[str, str] | None = None):
    surface = Surface(
        key="synthetic",
        benchmark="omnidoc",
        unit_label="page",
        models=sorted(loss),
        loss=loss,
    )
    for unit in surface.all_units():
        surface.cluster[unit] = document_family(unit)
        surface.page_class[unit] = (classes or {}).get(unit, "c0")
    return surface


def mean_loss(plan: dict[str, float]) -> float:
    return sum(plan.values()) / len(plan)


# --------------------------------------------------------------------------
# Oracle dominance
# --------------------------------------------------------------------------


def test_oracle_is_never_worse_than_any_fixed_plan():
    surface = make_surface(
        {
            "a": {"p1": 0.10, "p2": 0.90, "p3": 0.50},
            "b": {"p1": 0.80, "p2": 0.05, "p3": 0.50},
            "c": {"p1": 0.40, "p2": 0.40, "p3": 0.01},
        }
    )
    units = surface.intersection_units()
    plans = build_plans(surface, units, {u: "a" for u in units}, missing_as_failure=False)
    plans.pop("__champion_choice__")
    plans.pop("__unscoreable__")
    oracle = plans["ORACLE_PERMITTED"]
    for name, plan in plans.items():
        if name == "ORACLE_PERMITTED":
            continue
        for unit in units:
            assert oracle[unit] <= plan[unit] + 1e-12, (name, unit)
        assert mean_loss(oracle) <= mean_loss(plan) + 1e-12, name


def test_oracle_equals_best_single_when_one_model_dominates_everywhere():
    surface = make_surface(
        {
            "a": {"p1": 0.10, "p2": 0.10, "p3": 0.10},
            "b": {"p1": 0.20, "p2": 0.30, "p3": 0.40},
        }
    )
    units = surface.intersection_units()
    plans = build_plans(surface, units, {u: "a" for u in units}, missing_as_failure=False)
    plans.pop("__champion_choice__")
    plans.pop("__unscoreable__")
    assert mean_loss(plans["ORACLE_PERMITTED"]) == pytest.approx(mean_loss(plans["SINGLE:a"]))


def test_page_class_champion_beats_or_matches_global_best_single_in_sample():
    surface = make_surface(
        {
            "a": {"p1": 0.00, "p2": 0.00, "p3": 0.90, "p4": 0.90},
            "b": {"p1": 0.90, "p2": 0.90, "p3": 0.00, "p4": 0.00},
        },
        classes={"p1": "x", "p2": "x", "p3": "y", "p4": "y"},
    )
    units = surface.intersection_units()
    plans = build_plans(surface, units, {u: "a" for u in units}, missing_as_failure=False)
    plans.pop("__champion_choice__")
    plans.pop("__unscoreable__")
    best_single = min(mean_loss(plans["SINGLE:a"]), mean_loss(plans["SINGLE:b"]))
    assert mean_loss(plans["PAGE_CLASS_CHAMPION"]) <= best_single + 1e-12
    # and the champion is still bounded below by the oracle
    assert mean_loss(plans["ORACLE_PERMITTED"]) <= mean_loss(plans["PAGE_CLASS_CHAMPION"]) + 1e-12


# --------------------------------------------------------------------------
# Section 37 — missing as failure
# --------------------------------------------------------------------------


def test_missing_as_failure_is_never_better_than_intersection():
    surface = make_surface(
        {
            "a": {"p1": 0.10, "p2": 0.20, "p3": 0.30},
            "b": {"p1": 0.15, "p2": 0.25},  # p3 missing
        }
    )
    selection = {"p1": "a", "p2": "a", "p3": "a"}
    inter_units = surface.intersection_units()
    union_units = surface.all_units()
    assert inter_units == ["p1", "p2"]
    assert union_units == ["p1", "p2", "p3"]

    inter = build_plans(surface, inter_units, selection, missing_as_failure=False)
    union = build_plans(surface, union_units, selection, missing_as_failure=True)
    inter.pop("__champion_choice__")
    inter.pop("__unscoreable__")
    union.pop("__champion_choice__")
    union.pop("__unscoreable__")

    # the model with a hole is punished, never silently dropped
    assert union["SINGLE:b"]["p3"] == 1.0
    assert mean_loss(union["SINGLE:b"]) >= mean_loss(inter["SINGLE:b"])
    assert mean_loss(union["ORACLE_PERMITTED"]) >= mean_loss(inter["ORACLE_PERMITTED"])


def test_unresolved_reconciler_unit_is_a_full_loss_not_a_fallback():
    surface = make_surface({"a": {"p1": 0.10}, "b": {"p1": 0.20}})
    plans = build_plans(surface, ["p1"], {"p1": UNRESOLVED}, missing_as_failure=False)
    assert plans["ALWAYS_ALL_RECONCILED"]["p1"] == 1.0


def test_summarize_counts_hard_fails_over_tau():
    assert summarize({"a": 0.04, "b": 0.06, "c": 1.0})["hard_fail"] == 2
    assert summarize({})["n"] == 0


# --------------------------------------------------------------------------
# Frozen reconciler
# --------------------------------------------------------------------------


def test_reconciler_is_deterministic_under_input_reordering():
    candidates = {
        "alpha": normalize("the quick brown fox"),
        "bravo": normalize("the quick brown fox jumps"),
        "charlie": normalize("completely different words here"),
    }
    first = select(candidates)
    reordered = dict(reversed(list(candidates.items())))
    assert select(reordered) == first
    assert first in {"alpha", "bravo"}  # the two that agree with each other


def test_reconciler_tie_break_is_lexicographic_not_quality_ordered():
    same = normalize("identical text")
    assert select({"zulu": same, "alpha": same, "mike": same}) == "alpha"


def test_reconciler_handles_empty_and_single_candidates():
    assert select({}) == UNRESOLVED
    assert select({"only": normalize("")}) == "only"
    assert similarity(frozenset(), frozenset()) == 1.0
    assert similarity(frozenset({"a"}), frozenset()) == 0.0


def test_reconciler_normalization_strips_markdown_syntax():
    assert normalize("# Heading **bold**") == normalize("Heading bold")


def test_reconciler_picks_the_majority_shape_without_seeing_truth():
    # three models agree, one is a wild outlier; the outlier must lose even
    # though nothing here knows which is correct.
    agree = "alpha beta gamma delta epsilon"
    candidates = {
        "m1": normalize(agree),
        "m2": normalize(agree + " zeta"),
        "m3": normalize(agree + " eta"),
        "m4": normalize("totally unrelated tokens only"),
    }
    assert select(candidates) == "m1"


# --------------------------------------------------------------------------
# Section 35 — no cross-model splicing in a permitted plan
# --------------------------------------------------------------------------


def test_elementwise_ceiling_is_below_the_permitted_oracle_and_is_flagged():
    surface = Surface(
        key="synthetic",
        benchmark="omnidoc",
        unit_label="page",
        models=["a", "b"],
        loss={"a": {"p1": 0.5}, "b": {"p1": 0.5}},
        elements={
            "a": {"text": {"p1": 0.0}, "table": {"p1": 1.0}},
            "b": {"text": {"p1": 1.0}, "table": {"p1": 0.0}},
        },
    )
    surface.cluster["p1"] = "p"
    surface.page_class["p1"] = "c0"
    plans = build_plans(surface, ["p1"], {"p1": "a"}, missing_as_failure=False)
    plans.pop("__champion_choice__")
    plans.pop("__unscoreable__")
    forbidden = elementwise_forbidden(surface, ["p1"], missing_as_failure=False)
    # splicing text from a and table from b reaches 0; no permitted plan can.
    assert forbidden["p1"] == pytest.approx(0.0)
    assert plans["ORACLE_PERMITTED"]["p1"] == pytest.approx(0.5)
    assert forbidden["p1"] < plans["ORACLE_PERMITTED"]["p1"]


def test_document_family_groups_pages_of_one_document():
    assert document_family("PPT_1001115_eng_page_003.png") == "PPT_1001115_eng"
    assert document_family("arxiv_math/2502.15977_pg21.pdf") == "2502.15977"
    assert document_family("page-f9583127-1277.png") == "page-f9583127-1277"
