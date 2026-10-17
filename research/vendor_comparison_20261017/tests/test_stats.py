"""Paired statistics (AT-7). Every dataset here is SYNTHETIC and measures nothing."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from research.vendor_comparison_20261017 import stats
from research.vendor_comparison_20261017.stats import (
    AnswerTask,
    PairedUnit,
    answer_axis_difference,
    answer_axis_verdict,
    document_axis_verdict,
    exact_mcnemar_p,
    mean_refused_as_zero,
    paired_cluster_bootstrap,
)

# Deterministic, and no .hypothesis/ directory left in the worktree.
PROPERTY = settings(database=None, derandomize=True, deadline=None, max_examples=60)

SEED = "SYNTHETIC-at7-test-seed"
scores = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


def _units(pairs: Sequence[tuple[float | None, float | None]]) -> list[PairedUnit[float]]:
    return [PairedUnit(f"doc-{i:03d}", f"doc-{i:03d}", t, v) for i, (t, v) in enumerate(pairs)]


def _boot(
    units: Sequence[PairedUnit[float]], direction: stats.Direction = "higher", resamples: int = 200
) -> stats.PairedDifference:
    return paired_cluster_bootstrap(
        units,
        aggregate=mean_refused_as_zero,
        direction=direction,
        denominator=len(units),
        seed=SEED,
        resamples=resamples,
        level=0.95,
    )


# --------------------------------------------------------------------------- exact McNemar


def test_mcnemar_reproduces_the_script_it_was_copied_from() -> None:
    # gdp-plan-scripts/GDP-LEDGER-REVERIFY.json (sha256 a947138b…80a0), "paired": native_only 11,
    # compiled_only 7, mcnemar_exact_two_sided_p 0.4807 (the script rounds to 4 places).
    assert round(exact_mcnemar_p(11, 7), 4) == 0.4807
    assert exact_mcnemar_p(0, 0) == 1.0
    assert exact_mcnemar_p(0, 6) == 2 / 64
    assert exact_mcnemar_p(2, 8) == 2 * (1 + 10 + 45) / 1024


@PROPERTY
@given(st.integers(min_value=0, max_value=300), st.integers(min_value=0, max_value=300))
def test_mcnemar_is_the_exact_two_sided_binomial(b: int, c: int) -> None:
    m, k = b + c, min(b, c)
    exact = min(Fraction(1), 2 * Fraction(sum(math.comb(m, i) for i in range(k + 1)), 2**m))
    p = exact_mcnemar_p(b, c)
    assert p == exact_mcnemar_p(c, b)
    assert 0.0 < p <= 1.0
    assert math.isclose(p, float(exact), rel_tol=1e-12)
    if b == c:
        assert p == 1.0


@pytest.mark.parametrize("bad", [-1, 1.0, True, None])
def test_mcnemar_refuses_a_count_that_is_not_a_count(bad: object) -> None:
    with pytest.raises(ValueError, match="non-negative int"):
        exact_mcnemar_p(bad, 3)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative int"):
        exact_mcnemar_p(3, bad)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- verdicts

# Copied verbatim from VENDOR-COMPARISON-PREREG.json (sha256 d68e0027…16c9),
# statistics.d_axis_verdict.test_vectors and a_axis_verdict.test_vectors.
D_AXIS_PREREG: list[tuple[tuple[float, float], float, str]] = [
    ((2.01, 5), 2, "AHEAD"),
    ((2, 5), 2, "INCONCLUSIVE"),
    ((-2, 2), 2, "WITHIN"),
    ((-0.5, 0), 2, "WITHIN"),
    ((-1.5, -0.2), 2, "BEHIND"),
    ((-5, -3), 2, "BEHIND"),
    ((-2.5, 1), 2, "INCONCLUSIVE"),
    ((0.5, 2.5), 2, "INCONCLUSIVE"),
    ((0.011, 0.03), 0.01, "AHEAD"),
]
A_AXIS_PREREG: list[tuple[float, tuple[float, float], float, str]] = [
    (6, (1, 11), 0.03, "AHEAD"),
    (6, (1, 11), 0.06, "INCONCLUSIVE"),
    (4, (0.5, 8), 0.01, "INCONCLUSIVE"),
    (-2, (-4, -0.5), 0.04, "BEHIND"),
    (1, (-3, 4.5), 0.5, "WITHIN"),
    (5, (0.2, 5), 0.04, "AHEAD"),
]
# The boundary rows of the Foundation test the verdicts must match
# (fnd-UX-tab nextjs/lib/benchmark-registry.test.ts, commit 358dc3a3), all with delta 2 / margin 5.
D_AXIS_FOUNDATION: list[tuple[tuple[float, float], str]] = [
    ((-2.0001, 2), "INCONCLUSIVE"),
    ((-2, 2.0001), "INCONCLUSIVE"),
    ((-3, 0), "INCONCLUSIVE"),
    ((-3, -0.0001), "BEHIND"),
    ((2.0001, 2.0001), "AHEAD"),
]
A_AXIS_FOUNDATION: list[tuple[float, tuple[float, float], float, str]] = [
    (6, (1, 11), 0.05, "INCONCLUSIVE"),
    (6, (0, 5), 0.01, "WITHIN"),
    (4.9999, (1, 5), 0.01, "WITHIN"),
    (3, (-1, 5.0001), 0.01, "INCONCLUSIVE"),
]


@pytest.mark.parametrize(("ci", "delta", "expected"), D_AXIS_PREREG)
def test_document_axis_preregistered_vectors(
    ci: tuple[float, float], delta: float, expected: str
) -> None:
    assert document_axis_verdict(ci, delta) == expected


@pytest.mark.parametrize(("ci", "expected"), D_AXIS_FOUNDATION)
def test_document_axis_matches_the_foundation_boundaries(
    ci: tuple[float, float], expected: str
) -> None:
    assert document_axis_verdict(ci, 2) == expected


@pytest.mark.parametrize(("point", "ci", "p", "expected"), A_AXIS_PREREG + A_AXIS_FOUNDATION)
def test_answer_axis_vectors(
    point: float, ci: tuple[float, float], p: float, expected: str
) -> None:
    assert answer_axis_verdict(point, ci, p, margin_pp=5, alpha=0.05) == expected


def test_a_metric_with_no_interval_is_inconclusive() -> None:
    assert document_axis_verdict(None, 2) == "INCONCLUSIVE"


def test_verdicts_refuse_input_that_is_not_a_measurement() -> None:
    nan, inf = math.nan, math.inf
    for ci, message in (((nan, 1.0), "finite"), ((0.0, inf), "finite"), ((3.0, 1.0), "lower")):
        with pytest.raises(ValueError, match=message):
            document_axis_verdict(ci, 2)
    for delta in (0.0, -2.0, nan):
        with pytest.raises(ValueError, match="delta must be a positive finite number"):
            document_axis_verdict((3.0, 5.0), delta)
        with pytest.raises(ValueError, match="delta must be a positive finite number"):
            document_axis_verdict(None, delta)
    fine: tuple[float, tuple[float, float], float] = (6.0, (1.0, 11.0), 0.03)
    for point, ci, p, message in (
        (nan, fine[1], fine[2], "point difference"),
        (fine[0], fine[1], 1.2, "not a probability"),
        (fine[0], fine[1], nan, "not a probability"),
        (fine[0], (11.0, 1.0), fine[2], "lower bound"),
    ):
        with pytest.raises(ValueError, match=message):
            answer_axis_verdict(point, ci, p, margin_pp=5, alpha=0.05)
    for margin, alpha, message in (
        (0.0, 0.05, "margin_pp"),
        (5.0, 0.0, "alpha"),
        (5.0, 1.0, "alpha"),
    ):
        with pytest.raises(ValueError, match=message):
            answer_axis_verdict(*fine, margin_pp=margin, alpha=alpha)


bounds = st.floats(min_value=-10, max_value=10, allow_nan=False)


@PROPERTY
@given(bounds, bounds, st.floats(min_value=0.01, max_value=5))
def test_document_verdict_properties(a: float, b: float, delta: float) -> None:
    lower, upper = min(a, b), max(a, b)
    verdict = document_axis_verdict((lower, upper), delta)
    assert verdict in stats.VERDICTS
    assert (verdict == "BEHIND") == (upper < 0)  # behind is easy: no margin, and it wins overlaps
    assert (verdict == "AHEAD") == (lower > delta)  # ahead needs the margin
    if verdict == "WITHIN":
        assert -delta <= lower <= upper <= delta


# --------------------------------------------------------------------------- bootstrap


def test_bootstrap_is_pinned_to_its_seed() -> None:
    units = _units([(0.9, 0.5), (0.4, 0.6), (1.0, 0.2), (0.3, 0.3), (0.7, 0.1)])
    first, again = _boot(units, resamples=10_000), _boot(units, resamples=10_000)
    assert first == again
    # Pinned from this module's first run (SYNTHETIC data, CPython random.Random + choices).
    # Exact equality on purpose: a changed generator or draw order must fail here.
    assert (first.point, first.lower, first.upper) == (0.31999999999999995, 0.0, 0.6399999999999999)
    assert (first.units, first.clusters, first.resamples, first.seed) == (5, 5, 10_000, SEED)


def test_the_seed_drives_the_draws() -> None:
    units = [
        PairedUnit(f"doc-{i:03d}", f"doc-{i:03d}", (i % 7) / 7, (i % 5) / 5) for i in range(25)
    ]

    def run(seed: str) -> stats.PairedDifference:
        return paired_cluster_bootstrap(
            units,
            aggregate=mean_refused_as_zero,
            direction="higher",
            denominator=25,
            seed=seed,
            resamples=50,
            level=0.95,
        )

    a, b = run(SEED), run("SYNTHETIC-another-seed")
    assert a.point == b.point
    assert a.ci != b.ci
    assert run(SEED) == a


@PROPERTY
@given(st.lists(st.tuples(scores, scores), min_size=1, max_size=25), st.randoms())
def test_bootstrap_ignores_input_order(
    pairs: list[tuple[float, float]], rnd: random.Random
) -> None:
    units = _units(pairs)
    shuffled = list(units)
    rnd.shuffle(shuffled)
    assert _boot(units) == _boot(shuffled)


def test_input_order_does_not_reach_an_order_sensitive_aggregate() -> None:
    # Naive float addition depends on order: (0.1 + 0.2) + 0.3 != (0.3 + 0.2) + 0.1 (the builtin
    # sum compensates since 3.12, so it is spelled out). Units are sorted inside each cluster
    # before aggregating, so the order they were handed in cannot matter.
    def plain_mean(values: Sequence[float | None]) -> float:
        total = 0.0
        for v in values:
            total += 0.0 if v is None else v
        return total / len(values)

    units = [PairedUnit(f"task-{i}", "pdf-0", x, 0.0) for i, x in enumerate((0.1, 0.2, 0.3))]

    def run(given_units: Sequence[PairedUnit[float]]) -> stats.PairedDifference:
        return paired_cluster_bootstrap(
            given_units,
            aggregate=plain_mean,
            direction="higher",
            denominator=3,
            seed=SEED,
            resamples=20,
            level=0.95,
        )

    assert plain_mean([0.1, 0.2, 0.3]) != plain_mean([0.3, 0.2, 0.1])
    assert run(units) == run(units[::-1])
    assert run(units).point == plain_mean([0.1, 0.2, 0.3])


@PROPERTY
@given(st.lists(st.tuples(scores, scores), min_size=1, max_size=25))
def test_lower_is_better_flips_the_sign(pairs: list[tuple[float, float]]) -> None:
    higher = _boot(_units(pairs), "higher")
    lower = _boot(_units(pairs), "lower")
    swapped = _boot(_units([(v, t) for t, v in pairs]), "higher")
    # vendor - TAVONEL on the same draws is TAVONEL-vs-vendor with the arms swapped, exactly.
    assert (lower.point, lower.lower, lower.upper) == (swapped.point, swapped.lower, swapped.upper)
    assert lower.point == -higher.point
    assert lower.lower == pytest.approx(-higher.upper, abs=1e-9)
    assert lower.upper == pytest.approx(-higher.lower, abs=1e-9)


@PROPERTY
@given(st.lists(st.tuples(scores, scores), min_size=1, max_size=25))
def test_interval_is_ordered_and_bounded(pairs: list[tuple[float, float]]) -> None:
    result = _boot(_units(pairs))
    assert -1.0 <= result.lower <= result.upper <= 1.0
    assert result.ci == (result.lower, result.upper)


@PROPERTY
@given(st.lists(scores, min_size=1, max_size=25), st.floats(min_value=0.01, max_value=5))
def test_identical_arms_are_within_any_margin(values: list[float], delta: float) -> None:
    result = _boot(_units([(x, x) for x in values]))
    assert (result.point, result.lower, result.upper) == (0.0, 0.0, 0.0)
    assert document_axis_verdict(result.ci, delta) == "WITHIN"


@PROPERTY
@given(st.lists(st.one_of(st.none(), scores), min_size=1, max_size=25))
def test_refusals_score_zero_and_keep_the_denominator(values: list[float | None]) -> None:
    answered = [x for x in values if x is not None]
    assert mean_refused_as_zero(values) == pytest.approx(math.fsum(answered) / len(values))
    # TAVONEL refuses where `values` is None; the vendor answers 1.0 everywhere.
    result = _boot(_units([(x, 1.0) for x in values]))
    assert result.units == len(values)
    assert result.point == pytest.approx(math.fsum(answered) / len(values) - 1.0)


def test_a_refusal_counts_against_the_arm_that_refused() -> None:
    result = _boot(_units([(1.0, 1.0), (None, 1.0), (1.0, 1.0), (1.0, 1.0)]))
    assert result.point == -0.25  # 3/4 - 4/4, not 3/3 - 4/4
    assert document_axis_verdict(result.ci, 0.02) == "INCONCLUSIVE"
    assert result.upper == 0.0


def test_a_dropped_refusal_is_refused() -> None:
    units = _units([(1.0, 1.0), (1.0, 0.0), (0.0, 1.0)])
    with pytest.raises(ValueError, match="never dropped"):
        paired_cluster_bootstrap(
            units,
            aggregate=mean_refused_as_zero,
            direction="higher",
            denominator=4,  # the corpus N; one document went missing instead of scoring 0
            seed=SEED,
            resamples=10,
            level=0.95,
        )


def test_a_refusal_on_a_lower_is_better_metric_is_not_scored_zero() -> None:
    # Zero edit distance is the best score there is; the evaluator must score the empty prediction.
    with pytest.raises(ValueError, match="lower-is-better"):
        _boot(_units([(0.1, 0.2), (None, 0.3)]), "lower")
    with pytest.raises(ValueError, match="lower-is-better"):
        _boot(_units([(0.1, None)]), "lower")


def test_clusters_move_together() -> None:
    # Each pdf holds two tasks whose differences cancel: every cluster draw has Δ = 0 exactly,
    # whereas resampling tasks one by one would give a wide interval.
    units = [
        PairedUnit(f"task-{p}-{i}", f"pdf-{p}", float(i), float(1 - i))
        for p in range(6)
        for i in (0, 1)
    ]
    result = _boot(units)
    assert (result.point, result.lower, result.upper, result.clusters) == (0.0, 0.0, 0.0, 6)
    per_task = _boot([PairedUnit(u.unit_id, u.unit_id, u.tavonel, u.vendor) for u in units])
    assert per_task.lower < -0.1 and per_task.upper > 0.1


def test_the_evaluator_aggregate_is_recomputed_on_every_draw() -> None:
    # SYNTHETIC olmOCR-shaped records: (document type, checks passed, checks run). The aggregate is
    # the mean over types of each type's pass rate, which is not a mean over documents.
    type Record = tuple[str, int, int]

    def macro_type_mean(records: Sequence[Record | None]) -> Fraction:
        passed: dict[str, int] = {}
        run: dict[str, int] = {}
        for record in records:
            assert record is not None
            kind, ok, total = record
            passed[kind] = passed.get(kind, 0) + ok
            run[kind] = run.get(kind, 0) + total
        return Fraction(100) * sum(Fraction(passed[k], run[k]) for k in run) / len(run)

    units = [
        PairedUnit("d1", "d1", ("tables", 1, 4), ("tables", 3, 4)),
        PairedUnit("d2", "d2", ("tables", 2, 2), ("tables", 2, 2)),
        PairedUnit("d3", "d3", ("scans", 9, 10), ("scans", 5, 10)),
    ]
    result = paired_cluster_bootstrap(
        units,
        aggregate=macro_type_mean,
        direction="higher",
        denominator=3,
        seed=SEED,
        resamples=500,
        level=0.95,
    )
    # TAVONEL: tables 3/6, scans 9/10 -> 70; vendor: tables 5/6, scans 5/10 -> 200/3. Exact.
    assert result.point == float(Fraction(10, 3))
    assert result.lower <= result.point <= result.upper


def test_bootstrap_refuses_bad_arguments() -> None:
    units = _units([(1.0, 0.0), (0.0, 1.0)])
    good = {
        "aggregate": mean_refused_as_zero,
        "direction": "higher",
        "denominator": 2,
        "seed": SEED,
        "resamples": 10,
        "level": 0.95,
    }
    for change, message in (
        ({"direction": "up"}, "direction"),
        ({"seed": ""}, "seed"),
        ({"seed": 7}, "seed"),
        ({"resamples": 0}, "resamples"),
        ({"resamples": True}, "resamples"),
        ({"level": 0.0}, "level"),
        ({"level": 1.0}, "level"),
        ({"aggregate": lambda _: math.nan}, "finite"),
    ):
        with pytest.raises(ValueError, match=message):
            paired_cluster_bootstrap(units, **{**good, **change})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="no units"):
        paired_cluster_bootstrap([], **{**good, "denominator": 0})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="duplicate unit_id"):
        paired_cluster_bootstrap([units[0], units[0]], **good)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="no units to aggregate"):
        mean_refused_as_zero([])


# --------------------------------------------------------------------------- A axis


def _task(i: int, pdf: str, tavonel: str, vendor: str) -> AnswerTask:
    def epochs(marks: str) -> tuple[bool | None, ...]:
        return tuple({"P": True, "F": False, "X": None}[m] for m in marks)

    return AnswerTask(f"task-{i:02d}", pdf, epochs(tavonel), epochs(vendor))


def _answer(tasks: Sequence[AnswerTask], resamples: int = 500) -> stats.AnswerAxisDifference:
    return answer_axis_difference(
        tasks, denominator=len(tasks), seed=SEED, resamples=resamples, level=0.95
    )


def test_answer_axis_point_is_exact_at_the_margin() -> None:
    # 20 single-epoch tasks, TAVONEL passes one more: exactly +5 pp, which is AHEAD-eligible.
    tasks = [_task(0, "pdf-0", "P", "F")] + [_task(i, f"pdf-{i}", "P", "P") for i in range(1, 20)]
    result = _answer(tasks)
    assert result.difference.point == 5.0
    assert (result.tavonel_only, result.vendor_only, result.mcnemar_p) == (1, 0, 1.0)
    d = result.difference
    # The interval still reaches 0 and one discordant task cannot clear McNemar.
    assert d.lower == 0.0
    assert answer_axis_verdict(d.point, d.ci, result.mcnemar_p, margin_pp=5, alpha=0.05) == (
        "INCONCLUSIVE"
    )


def test_answer_axis_scores_failed_epochs_zero_and_uses_the_majority() -> None:
    tasks = [
        _task(0, "pdf-a", "PPPXX", "PPFFF"),  # 3/5 vs 2/5: majority T only
        _task(1, "pdf-a", "PPXXX", "PPPFF"),  # 2/5 vs 3/5: majority V only
        _task(2, "pdf-b", "PPPPP", "FFFFF"),  # T only
        _task(3, "pdf-c", "XXXXX", "FFFFF"),  # neither
    ]
    result = _answer(tasks)
    # macro: T (3+2+5+0)/20 = 50 %, V (2+3+0+0)/20 = 25 % -> +25 pp
    assert result.difference.point == 25.0
    assert (result.tavonel_only, result.vendor_only) == (2, 1)
    assert result.mcnemar_p == exact_mcnemar_p(2, 1)
    assert (result.difference.units, result.difference.clusters) == (4, 3)


def test_a_tied_epoch_count_is_not_a_majority() -> None:
    # Two epochs, one pass: half is not more than half, so neither task is discordant.
    result = _answer([_task(0, "pdf-a", "PF", "FF"), _task(1, "pdf-b", "FF", "PF")])
    assert (result.tavonel_only, result.vendor_only, result.mcnemar_p) == (0, 0, 1.0)
    assert result.difference.point == 0.0


def test_answer_axis_refuses_a_dropped_epoch_or_task() -> None:
    with pytest.raises(ValueError, match="never dropped"):
        _answer([_task(0, "pdf-a", "PPPPP", "PPPPP"), _task(1, "pdf-a", "PPPP", "PPPPP")])
    with pytest.raises(ValueError, match="never dropped"):
        answer_axis_difference(
            [_task(0, "pdf-a", "PPPPP", "PPPPP")],
            denominator=70,
            seed=SEED,
            resamples=10,
            level=0.95,
        )
    with pytest.raises(ValueError, match="no tasks"):
        _answer([])
    with pytest.raises(ValueError, match="no epochs"):
        _answer([_task(0, "pdf-a", "", "")])


@PROPERTY
@given(
    st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=4),
            st.text(alphabet="PFX", min_size=5, max_size=5),
            st.text(alphabet="PFX", min_size=5, max_size=5),
        ),
        min_size=1,
        max_size=30,
    )
)
def test_answer_axis_point_matches_a_direct_count(rows: list[tuple[int, str, str]]) -> None:
    tasks = [_task(i, f"pdf-{pdf}", t, v) for i, (pdf, t, v) in enumerate(rows)]
    result = _answer(tasks, resamples=50)
    passes_t = sum(t.count("P") for _, t, _ in rows)
    passes_v = sum(v.count("P") for _, _, v in rows)
    assert result.difference.point == float(Fraction(100 * (passes_t - passes_v), 5 * len(rows)))
    assert result.difference.lower <= result.difference.upper
    assert result.tavonel_only + result.vendor_only <= len(rows)
