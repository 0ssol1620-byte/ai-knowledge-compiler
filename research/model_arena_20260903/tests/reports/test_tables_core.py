"""``arena.reports.tables_core``: header shape, missing-input -> n/a, values."""

from __future__ import annotations

from arena.reports.common import Cell
from arena.reports.loaders import CampaignSources, ModelRunSource, ScoreSource
from arena.reports.tables_core import (
    LEADERBOARD_HEADER,
    build_benchmark_breakdown,
    build_cost_report,
    build_document_type_breakdown,
    build_failure_taxonomy,
    build_gpu_resource_report,
    build_latency_report,
    build_leaderboard,
    build_reliability_report,
    build_runtime_failures,
)

MODELS = ("model_a", "model_b")
BENCHMARKS = ("parsebench", "omnidoc", "olmocr")


def _empty_sources(**overrides: object) -> CampaignSources:
    base: dict[str, object] = {"root_exists": True}
    base.update(overrides)
    return CampaignSources(**base)  # type: ignore[arg-type]


def test_build_leaderboard_header_matches_masterplan_30() -> None:
    spec = build_leaderboard(_empty_sources(), MODELS)
    assert spec.header == LEADERBOARD_HEADER


def test_build_leaderboard_missing_everything_is_na_not_zero() -> None:
    spec = build_leaderboard(_empty_sources(), MODELS)
    assert len(spec.rows) == len(MODELS)
    for row in spec.rows:
        completion = row["completion"]
        assert isinstance(completion, Cell)
        assert completion.value is None
        assert completion.rendered() == "n/a"
        assert completion.rendered() != "0"


def test_build_leaderboard_reads_headline_quality_and_completion() -> None:
    sources = _empty_sources(
        scores={
            ("model_a", "parsebench"): ScoreSource(
                summary={"overall": 0.8}, summary_reason=None, per_case=None, per_case_reason=None
            )
        },
        runs={
            "model_a": ModelRunSource(
                receipts=[
                    {"status": "SUCCESS", "attempt": 1, "retry_count": 0, "total_ms": 1000},
                    {"status": "FAILED", "attempt": 1, "retry_count": 0, "error_class": "CUDA_OOM"},
                ],
                run_summary=None,
                run_summary_reason=None,
                canary_receipt=None,
            )
        },
    )
    spec = build_leaderboard(sources, ("model_a",))
    row = spec.rows[0]
    assert row["ParseBench"].value == 0.8
    assert row["completion"].value == 0.5
    assert row["sec_per_page"].value == 1.0


def test_build_benchmark_breakdown_long_format_and_missing_reason() -> None:
    sources = _empty_sources(
        scores={
            ("model_a", "parsebench"): ScoreSource(
                summary={"overall": 0.5, "table_teds": 0.6},
                summary_reason=None,
                per_case=None,
                per_case_reason=None,
            )
        }
    )
    spec = build_benchmark_breakdown(sources, ("model_a",), ("parsebench",))
    metrics = {row["metric"].value for row in spec.rows if row["model_key"].value == "model_a"}
    assert metrics == {"overall", "table_teds"}
    for row in spec.rows:
        assert row["value"].value is not None


def test_build_benchmark_breakdown_missing_summary_has_reason_not_crash() -> None:
    spec = build_benchmark_breakdown(_empty_sources(), ("model_a",), ("parsebench",))
    assert len(spec.rows) == 1
    assert spec.rows[0]["value"].value is None
    assert spec.rows[0]["reason"].value != "ok"


def test_build_document_type_breakdown_aggregates_by_family() -> None:
    sources = _empty_sources(
        scores={
            ("model_a", "parsebench"): ScoreSource(
                summary={"overall": 0.5},
                summary_reason=None,
                per_case=[
                    {"document_type": "tables", "score": 0.8},
                    {"document_type": "table", "score": 0.6},
                    {"document_type": "old_scans", "score": 0.4},
                ],
                per_case_reason=None,
            )
        }
    )
    spec = build_document_type_breakdown(sources, ("model_a",), ("parsebench",))
    by_family = {row["document_type"].value: row for row in spec.rows}
    assert by_family["tables"]["mean_metric"].value == round((0.8 + 0.6) / 2, 6)
    assert by_family["old_scan"]["mean_metric"].value == 0.4


def test_build_document_type_breakdown_no_per_case_is_na() -> None:
    spec = build_document_type_breakdown(_empty_sources(), ("model_a",), ("parsebench",))
    assert spec.rows[0]["document_type"].value is None


def test_build_latency_report_quantiles_and_canary_stages() -> None:
    sources = _empty_sources(
        runs={
            "model_a": ModelRunSource(
                receipts=[
                    {"status": "SUCCESS", "total_ms": 1000},
                    {"status": "SUCCESS", "total_ms": 2000},
                ],
                run_summary=None,
                run_summary_reason=None,
                canary_receipt={"stage_latency_ms": {"cold_start": {"p50_ms": 4000}}},
            )
        }
    )
    spec = build_latency_report(sources, ("model_a",))
    row = spec.rows[0]
    assert row["p50_sec_per_page"].value is not None
    assert row["cold_start_p50_sec"].value == 4.0
    assert row["model_load_p50_sec"].value is None  # not present in this canary receipt


def test_build_latency_report_no_receipts_is_na() -> None:
    spec = build_latency_report(_empty_sources(), ("model_a",))
    assert spec.rows[0]["p50_sec_per_page"].value is None


def test_build_gpu_resource_report_util_always_na_documented_reason() -> None:
    spec = build_gpu_resource_report(_empty_sources(), ("model_a",))
    row = spec.rows[0]
    assert row["gpu_util_mean"].value is None
    assert "not captured" in (row["gpu_util_mean"].reason or "")


def test_build_cost_report_subscription_never_zero_per_page() -> None:
    sources = _empty_sources(
        runs={
            "opus5_subscription": ModelRunSource(
                receipts=[
                    {"status": "SUCCESS", "api_equivalent_list_price_usd": 0.05},
                    {"status": "SUCCESS", "api_equivalent_list_price_usd": 0.03},
                ],
                run_summary=None,
                run_summary_reason=None,
                canary_receipt=None,
            )
        }
    )
    spec = build_cost_report(sources, ("opus5_subscription",))
    row = spec.rows[0]
    assert row["usd_per_successful_page"].value == 0.04
    assert row["usd_per_successful_page"].value != 0


def test_build_cost_report_no_data_is_na_row() -> None:
    spec = build_cost_report(_empty_sources(), ("model_a",))
    assert spec.rows[0]["reason"].value != "ok"


def test_build_reliability_report_denominator_is_attempted_count() -> None:
    sources = _empty_sources(
        runs={
            "model_a": ModelRunSource(
                receipts=[
                    {"status": "SUCCESS", "attempt": 1, "retry_count": 0},
                    {"status": "SUCCESS", "attempt": 1, "retry_count": 0},
                    {
                        "status": "FAILED",
                        "attempt": 1,
                        "retry_count": 0,
                        "error_class": "INFERENCE_TIMEOUT",
                    },
                    {
                        "status": "FAILED",
                        "attempt": 1,
                        "retry_count": 0,
                        "error_class": "RATE_LIMIT",
                    },
                ],
                run_summary=None,
                run_summary_reason=None,
                canary_receipt=None,
            )
        }
    )
    spec = build_reliability_report(sources, ("model_a",))
    row = spec.rows[0]
    assert row["attempted"].value == 4
    assert row["success"].value == 2
    assert row["completion_rate"].value == 0.5
    assert row["timeout_pages"].value == 1
    assert row["rate_limit_pages"].value == 1
    assert row["worker_replacement_count"].value is None


def test_build_reliability_report_no_receipts_directory_is_na() -> None:
    spec = build_reliability_report(_empty_sources(), ("model_a",))
    assert spec.rows[0]["attempted"].value == 0
    assert spec.rows[0]["reason"].value != "ok"


def test_build_failure_taxonomy_empty_is_na_row_with_header() -> None:
    spec = build_failure_taxonomy(_empty_sources())
    assert "reason" in spec.header
    assert spec.rows[0]["reason"].value is None  # na_reason cell


def test_build_failure_taxonomy_passthrough() -> None:
    sources = _empty_sources(
        errors=[
            {
                "error_class": "CUDA_OOM",
                "first_seen": "t0",
                "last_seen": "t1",
                "count": 3,
                "affected_model": "model_a",
                "retryability": True,
                "root_cause": None,
                "resolution": None,
                "wasted_gpu_seconds": 1.2,
            }
        ]
    )
    spec = build_failure_taxonomy(sources)
    row = spec.rows[0]
    assert row["error_class"].value == "CUDA_OOM"
    assert row["count"].value == 3
    assert row["root_cause"].value is None  # not yet determined


def test_build_runtime_failures_filters_non_success() -> None:
    sources = _empty_sources(
        runs={
            "model_a": ModelRunSource(
                receipts=[
                    {"status": "SUCCESS", "case_key": "a"},
                    {"status": "FAILED", "case_key": "b", "error_class": "CUDA_OOM"},
                ],
                run_summary=None,
                run_summary_reason=None,
                canary_receipt=None,
            )
        }
    )
    spec = build_runtime_failures(sources, ("model_a",))
    assert len(spec.rows) == 1
    assert spec.rows[0]["case_key"].value == "b"


def test_build_runtime_failures_none_found_is_na_row() -> None:
    spec = build_runtime_failures(_empty_sources(), ("model_a",))
    assert spec.rows[0]["reason"].value is None
