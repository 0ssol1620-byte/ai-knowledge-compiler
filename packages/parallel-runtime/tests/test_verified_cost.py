import pytest
from akc_parallel_runtime.verified_cost import (
    AttemptRecord,
    CostLine,
    QualityStat,
    VerifiedCostError,
    aggregate_level,
    compare_levels,
    percentile,
)

Q = QualityStat(critical_errors=0)


def _fixture(level: int, n: int = 8, per_attempt: float = 10.0):
    # n equal attempts of per_attempt seconds spread over `level` workers.
    attempts = [
        AttemptRecord(
            f"a{i}", (i // level) * per_attempt, (i // level + 1) * per_attempt, per_attempt, "ok"
        )
        for i in range(n)
    ]
    inv = [CostLine("invoice", 1.0, n * per_attempt)]
    return aggregate_level(level, attempts, inv, 8, Q)


def test_invoice_cost_per_accepted_page() -> None:
    agg = _fixture(1)
    assert agg.status == "ok" and agg.receipt_grade
    assert agg.verified_usd_per_accepted_page == pytest.approx(1.0 / 8)
    assert agg.utilization == pytest.approx(1.0)


def test_estimate_cost_has_no_per_page_figure() -> None:
    agg = aggregate_level(
        1, [AttemptRecord("a", 0, 5, 5, "ok")], [CostLine("estimate", 1.0, 5)], 4, Q
    )
    assert not agg.receipt_grade
    assert agg.verified_usd_per_accepted_page is None
    assert agg.status == "not_receipt_grade"
    mixed = aggregate_level(1, [], [CostLine("invoice", 1, 1), CostLine("estimate", 1, 1)], 4, Q)
    assert mixed.verified_usd_per_accepted_page is None


def test_no_invoice_is_not_receipt_grade() -> None:
    assert aggregate_level(1, [], [], 4, Q).verified_usd_per_accepted_page is None


def test_zero_accepted_pages_no_division() -> None:
    agg = aggregate_level(1, [], [CostLine("invoice", 2.0, 10)], 0, Q)
    assert agg.status == "none_accepted"
    assert agg.verified_usd_per_accepted_page is None


def test_percentiles_known_arrays() -> None:
    data = [float(i) for i in range(1, 101)]
    assert percentile(data, 50) == 50
    assert percentile(data, 95) == 95
    assert percentile(data, 99) == 99
    assert percentile([], 50) is None


def test_counts_and_latency() -> None:
    attempts = [
        AttemptRecord("a", 0, 1, 1, "oom"),
        AttemptRecord("b", 0, 2, 2, "cancelled"),
        AttemptRecord("c", 0, 3, 3, "retry"),
        AttemptRecord("d", 0, 4, 4, "ok"),
    ]
    agg = aggregate_level(2, attempts, [CostLine("invoice", 1, 20)], 1, Q)
    assert (agg.oom_count, agg.cancel_count, agg.retry_count) == (1, 1, 1)
    assert agg.latency_p50_s == 2 and agg.utilization == pytest.approx(0.5)


def test_levels_gpu_hours_flat_wall_time_shrinks() -> None:
    levels = [_fixture(k) for k in (1, 2, 4, 8)]
    assert len({lv.billed_gpu_s for lv in levels}) == 1
    assert [lv.wall_s for lv in levels] == [80, 40, 20, 10]
    cmp = compare_levels(levels)
    assert cmp.status == "matched" and cmp.speedup[8] == pytest.approx(8.0)


def test_mismatched_coverage_or_critical_errors_gives_no_speedup() -> None:
    a = _fixture(1)
    b = aggregate_level(2, [AttemptRecord("x", 0, 1, 1, "ok")], [CostLine("invoice", 1, 1)], 7, Q)
    r = compare_levels([a, b])
    assert r.status == "quality_not_matched" and r.speedup == {}
    c = aggregate_level(
        2, [AttemptRecord("x", 0, 1, 1, "ok")], [CostLine("invoice", 1, 1)], 8, QualityStat(1)
    )
    assert compare_levels([a, c]).status == "quality_not_matched"


def test_none_accepted_comparison() -> None:
    z = [aggregate_level(k, [], [], 0, Q) for k in (1, 2)]
    assert compare_levels(z).status == "none_accepted"


def test_invalid_inputs_refused() -> None:
    with pytest.raises(VerifiedCostError):
        AttemptRecord("a", 5, 1, 1, "ok")
    with pytest.raises(VerifiedCostError):
        AttemptRecord("a", 0, 1, 1, "weird")
    with pytest.raises(VerifiedCostError):
        CostLine("timing", 1, 1)
    with pytest.raises(VerifiedCostError):
        compare_levels([_fixture(1)])


def test_non_finite_values_refused() -> None:
    nan, inf = float("nan"), float("inf")
    for bad in (nan, inf):
        with pytest.raises(VerifiedCostError):
            CostLine("invoice", bad, 1)
        with pytest.raises(VerifiedCostError):
            CostLine("invoice", 1, bad)
        with pytest.raises(VerifiedCostError):
            AttemptRecord("a", bad, 1, 1, "ok")
        with pytest.raises(VerifiedCostError):
            AttemptRecord("a", 0, bad, 1, "ok")
        with pytest.raises(VerifiedCostError):
            AttemptRecord("a", 0, 1, bad, "ok")


def test_duplicate_level_refused() -> None:
    a, b = _fixture(1), _fixture(1, per_attempt=5.0)
    with pytest.raises(VerifiedCostError, match="duplicate level"):
        compare_levels([a, b])
