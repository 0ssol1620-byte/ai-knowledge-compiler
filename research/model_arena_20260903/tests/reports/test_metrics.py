"""``arena.reports.metrics``: per-model aggregation, happy and failure paths."""

from __future__ import annotations

from arena.reports.loaders import ModelRunSource
from arena.reports.metrics import (
    aggregate_pod_costs,
    compute_model_metrics,
    cost_usd_per_1000_pages,
    quantile,
)


def _receipt(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "status": "SUCCESS",
        "attempt": 1,
        "retry_count": 0,
        "total_ms": 2000,
        "peak_vram_mb": 8000,
        "gpu_type": "RTX4090",
        "error_class": None,
        "wasted_gpu_seconds": 0.0,
    }
    base.update(overrides)
    return base


def _run(receipts: list[dict[str, object]], *, reason: str | None = None) -> ModelRunSource:
    return ModelRunSource(
        receipts=receipts, run_summary=None, run_summary_reason=reason, canary_receipt=None
    )


def test_compute_model_metrics_empty_receipts_is_all_na() -> None:
    metrics = compute_model_metrics("model_x", _run([], reason="missing"))
    assert metrics.attempted == 0
    assert metrics.completion_rate.value is None
    assert metrics.completion_rate.reason is not None
    assert metrics.sec_per_page_mean.value is None


def test_compute_model_metrics_counts_success_and_failure() -> None:
    receipts = [
        _receipt(case_key="a", status="SUCCESS", total_ms=1000),
        _receipt(case_key="b", status="SUCCESS", total_ms=3000, attempt=2),
        _receipt(case_key="c", status="FAILED", error_class="CUDA_OOM", retry_count=1),
    ]
    metrics = compute_model_metrics("model_x", _run(receipts))

    assert metrics.attempted == 3
    assert metrics.success == 2
    assert metrics.failed == 1
    assert metrics.first_attempt_success == 1  # only the attempt==1 SUCCESS counts
    assert metrics.oom_pages == 1
    assert metrics.retryable_pages == 1
    assert metrics.completion_rate.value == round(2 / 3, 6)
    assert metrics.unresolved_rate.value == round(1 / 3, 6)
    assert metrics.sec_per_page_mean.value == 2.0  # mean(1000, 3000) ms -> 2.0s


def test_compute_model_metrics_ignores_load_error_placeholder_rows() -> None:
    metrics = compute_model_metrics("model_x", _run([{"_load_error": "not an object"}]))
    assert metrics.attempted == 0


def test_quantile_empty_is_none() -> None:
    assert quantile([], 0.5) is None


def test_quantile_single_value() -> None:
    assert quantile([42.0], 0.95) == 42.0


def test_quantile_p50_of_evenly_spaced_values() -> None:
    values = [float(i) for i in range(1, 101)]  # 1..100
    p50 = quantile(values, 0.5)
    assert p50 is not None
    assert 49 <= p50 <= 51


def test_aggregate_pod_costs_none_when_no_rows_for_model() -> None:
    assert aggregate_pod_costs("model_x", []) is None
    assert aggregate_pod_costs("model_x", [{"model_key": "other_model"}]) is None


def test_aggregate_pod_costs_sums_rows_for_one_model() -> None:
    rows = [
        {
            "model_key": "model_x",
            "gpu_type": "RTX4090",
            "billed_seconds": 100.0,
            "model_loading_seconds": 10.0,
            "useful_inference_seconds": 80.0,
            "retry_seconds": 5.0,
            "idle_seconds": 5.0,
            "estimated_provider_cost_usd": 1.0,
            "useful_cost_usd": 0.8,
            "wasted_cost_usd": 0.2,
        },
        {
            "model_key": "model_x",
            "gpu_type": "A100",
            "billed_seconds": 50.0,
            "model_loading_seconds": 5.0,
            "useful_inference_seconds": 40.0,
            "retry_seconds": 0.0,
            "idle_seconds": 5.0,
            "estimated_provider_cost_usd": 2.0,
            "useful_cost_usd": 1.6,
            "wasted_cost_usd": 0.4,
        },
        {"model_key": "other_model", "billed_seconds": 999.0},
    ]
    agg = aggregate_pod_costs("model_x", rows)
    assert agg is not None
    assert agg.pod_count == 2
    assert agg.billed_seconds == 150.0
    assert agg.useful_inference_seconds == 120.0
    assert agg.gpu_types == ("A100", "RTX4090")
    assert agg.operational_efficiency.value == round(120.0 / 150.0, 6)


def test_aggregate_pod_costs_zero_billed_seconds_gives_na_ratios() -> None:
    rows = [{"model_key": "model_x", "billed_seconds": 0.0, "useful_inference_seconds": 0.0}]
    agg = aggregate_pod_costs("model_x", rows)
    assert agg is not None
    assert agg.operational_efficiency.value is None
    assert agg.idle_overhead_ratio.value is None


def test_cost_usd_per_1000_pages_prefers_api_equivalent() -> None:
    receipts = [
        _receipt(case_key="a", api_equivalent_list_price_usd=0.05),
        _receipt(case_key="b", api_equivalent_list_price_usd=0.03),
    ]
    metrics = compute_model_metrics("opus5_subscription", _run(receipts))
    cell = cost_usd_per_1000_pages(metrics, None)
    assert cell.value == round(0.04 * 1000.0, 4)


def test_cost_usd_per_1000_pages_na_with_neither_source() -> None:
    metrics = compute_model_metrics("model_x", _run([]))
    cell = cost_usd_per_1000_pages(metrics, None)
    assert cell.value is None
    assert cell.reason is not None
