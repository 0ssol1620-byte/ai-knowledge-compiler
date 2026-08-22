"""Statistics, denominators, flags, and one end-to-end pass over the arms."""

from __future__ import annotations

import pytest
from akc_absorption.evolution_suite import MutationClass, build_suite
from akc_absorption.flags import (
    ABSORB_ALIGNMENT_DIFF,
    AbsorptionFlagError,
    flag_enabled,
    require_flag,
)
from akc_absorption.harness import ARMS, Arm, run_case
from akc_absorption.metrics import (
    bootstrap_ci,
    holm_bonferroni,
    mcnemar_exact,
    rate,
    score_case,
    summarise,
)

ON = {ABSORB_ALIGNMENT_DIFF: "1"}


# -- flags ------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True"])
def test_recognised_true_values(value: str) -> None:
    assert flag_enabled(ABSORB_ALIGNMENT_DIFF, {ABSORB_ALIGNMENT_DIFF: value})


@pytest.mark.parametrize("value", ["", "0", "yes", "on", "TrUe", "false"])
def test_everything_else_is_off(value: str) -> None:
    """An unexpected value fails towards off, because this gates a shadow path."""
    assert not flag_enabled(ABSORB_ALIGNMENT_DIFF, {ABSORB_ALIGNMENT_DIFF: value})


def test_require_flag_raises_rather_than_returning_quietly() -> None:
    with pytest.raises(AbsorptionFlagError):
        require_flag(ABSORB_ALIGNMENT_DIFF, {})


# -- rates ------------------------------------------------------------------


def test_an_empty_population_has_no_rate_rather_than_a_zero_one() -> None:
    assert rate(0, 0, "nothing").value is None
    assert rate(0, 5, "five things").value == 0.0


def test_a_rate_carries_its_denominator_into_the_record() -> None:
    record = rate(3, 12, "gold pairs").as_record()
    assert record == {
        "value": 0.25,
        "numerator": 3,
        "denominator": 12,
        "population": "gold pairs",
    }


# -- statistics -------------------------------------------------------------


def test_mcnemar_is_one_when_nothing_is_discordant() -> None:
    assert mcnemar_exact(0, 0) == 1.0


def test_mcnemar_is_symmetric_and_shrinks_with_imbalance() -> None:
    assert mcnemar_exact(8, 2) == mcnemar_exact(2, 8)
    assert mcnemar_exact(20, 0) < mcnemar_exact(12, 8)


def test_mcnemar_matches_the_closed_form_on_a_known_case() -> None:
    # b=1, c=4: two-sided exact p = 2 * (C(5,0)+C(5,1)) / 2^5 = 12/32.
    assert mcnemar_exact(1, 4) == pytest.approx(0.375)


def test_holm_is_monotone_and_bounded() -> None:
    adjusted = holm_bonferroni({"a": 0.001, "b": 0.02, "c": 0.5})
    assert adjusted["a"] <= adjusted["b"] <= adjusted["c"] <= 1.0
    assert adjusted["a"] == pytest.approx(0.003)


def test_the_bootstrap_is_reproducible_and_brackets_the_point_estimate() -> None:
    values = [1.0] * 30 + [0.0] * 70
    first = bootstrap_ci(values, resamples=500)
    second = bootstrap_ci(values, resamples=500)
    assert first == second
    assert first is not None
    assert first[0] <= 0.30 <= first[1]


def test_the_bootstrap_declines_an_empty_population() -> None:
    assert bootstrap_ci([]) is None


# -- end to end -------------------------------------------------------------


def test_every_arm_runs_over_every_mutation_class() -> None:
    cases = build_suite(documents=1)
    assert len(cases) == 11
    for case in cases:
        outcomes = run_case(case, env=ON)
        assert set(outcomes) == {spec.arm for spec in ARMS}
        for outcome in outcomes.values():
            assert outcome.case_id == case.case_id
            assert outcome.rebuild is not None


def test_the_baseline_is_the_only_arm_that_never_abstains() -> None:
    abstained = {arm: False for arm in (spec.arm for spec in ARMS)}
    for case in build_suite(documents=2):
        for arm, outcome in run_case(case, env=ON).items():
            if outcome.unresolved_candidates:
                abstained[arm] = True
    assert abstained[Arm.BASELINE] is False
    assert abstained[Arm.CURRENT] is True
    assert abstained[Arm.CHALLENGER] is True


def test_scores_and_summary_agree_on_the_denominators() -> None:
    cases = build_suite(documents=2)
    scores = [
        score_case(case, run_case(case, env=ON)[Arm.CURRENT]) for case in cases
    ]
    summary = summarise(scores, with_ci=False)
    assert summary["cases"] == len(cases)
    layout = summary["layout_only_false_positive_rate"]
    assert isinstance(layout, dict)
    assert layout["denominator"] == sum(1 for item in scores if item.mutation_is_layout)
    critical = summary["critical_change_recall"]
    assert isinstance(critical, dict)
    assert critical["denominator"] == sum(
        1 for item in scores if item.mutation_is_critical
    )


def test_an_abstention_is_not_scored_as_a_false_split() -> None:
    """The distinction the whole comparison rests on."""
    for case in build_suite(documents=2):
        if case.mutation is not MutationClass.SECTION_REORDERING:
            continue
        outcome = run_case(case, env=ON)[Arm.CURRENT]
        score = score_case(case, outcome)
        if outcome.unresolved_candidates:
            assert score.false_splits == 0
