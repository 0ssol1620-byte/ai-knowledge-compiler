from __future__ import annotations

import json
from pathlib import Path

import pytest
from summarize_omnidoc_evidence import build_summary


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _metrics(*, page_count: int = 18, cdm_exceptions: int = 0) -> dict[str, object]:
    return {
        "text_block": {"all": {"Edit_dist": {"ALL_page_avg": 0.04}}},
        "display_formula": {
            "all": {"Edit_dist": {"ALL_page_avg": 0.15}, "CDM": {"all": 0.9}},
            "metric_debug": {
                "CDM": {
                    "sample_count": 23,
                    "exception_case_count": cdm_exceptions,
                    "timeout_case_count": 0,
                }
            },
        },
        "table": {
            "all": {
                "TEDS": {"all": 0.89},
                "TEDS_structure_only": {"all": 0.95},
                "Edit_dist": {"ALL_page_avg": 0.43},
            }
        },
        "reading_order": {"all": {"Edit_dist": {"ALL_page_avg": 0.09}}},
        "match_debug": {"page_count": page_count},
    }


def test_build_summary_excludes_broken_cdm_and_computes_cost(tmp_path: Path) -> None:
    metric_paths = [
        _write_json(tmp_path / f"metric-{index}.json", _metrics(cdm_exceptions=23))
        for index in range(3)
    ]
    run_summary = _write_json(
        tmp_path / "run-summary.json",
        {
            "runs": [
                {
                    "latency_seconds": 126.0,
                    "failed": 0,
                    "timed_out": False,
                    "cases": [
                        {"case_id": f"page-{page}", "markdown_sha256": f"sha256:{page:064x}"}
                        for page in range(18)
                    ],
                }
                for _ in range(3)
            ]
        },
    )

    summary = build_summary(
        metric_paths=metric_paths,
        run_summary_path=run_summary,
        model_id="mineru-3.4.4-pipeline",
        corpus_id="omnidocbench-demo-18",
        evaluator_revision="test-revision",
        provider_hourly_usd=0.69,
    )

    assert summary["promotion_status"] == "eligible_partial_metrics"
    assert summary["overall_score_status"] == "unavailable"
    assert summary["overall_score"] is None
    assert summary["excluded_metrics"]["cdm"]["status"] == "unavailable"
    assert summary["performance"]["seconds_per_page"]["mean"] == 7.0
    assert summary["performance"]["estimated_provider_cost_per_page_usd"]["mean"] == pytest.approx(
        0.0013416666666666668
    )
    assert summary["repeat_stability"]["exact_repeat_ratio"] == 1.0


def test_build_summary_rejects_inconsistent_repeat_page_counts(tmp_path: Path) -> None:
    metric_paths = [
        _write_json(tmp_path / "metric-1.json", _metrics(page_count=18)),
        _write_json(tmp_path / "metric-2.json", _metrics(page_count=17)),
    ]
    run_summary = _write_json(
        tmp_path / "run-summary.json",
        {
            "runs": [
                {"latency_seconds": 120.0, "failed": 0, "timed_out": False},
                {"latency_seconds": 120.0, "failed": 0, "timed_out": False},
            ]
        },
    )

    with pytest.raises(ValueError, match="same page count"):
        build_summary(
            metric_paths=metric_paths,
            run_summary_path=run_summary,
            model_id="mineru-3.4.4-pipeline",
            corpus_id="omnidocbench-demo-18",
            evaluator_revision="test-revision",
            provider_hourly_usd=0.69,
        )


def test_build_summary_accepts_case_summed_latency_shape(tmp_path: Path) -> None:
    metric_paths = [
        _write_json(tmp_path / f"metric-{index}.json", _metrics(cdm_exceptions=23))
        for index in range(3)
    ]
    run_summary = _write_json(
        tmp_path / "run-summary.json",
        {
            "runs": [
                {"total_latency_seconds": 90.0, "failed": 0},
                {"total_latency_seconds": 90.0, "failed": 0},
                {"total_latency_seconds": 90.0, "failed": 0},
            ]
        },
    )

    summary = build_summary(
        metric_paths=metric_paths,
        run_summary_path=run_summary,
        model_id="paddleocr-vl-1.6-fastdeploy",
        corpus_id="omnidocbench-demo-18",
        evaluator_revision="test-revision",
        provider_hourly_usd=0.69,
    )

    assert summary["performance"]["seconds_per_page"]["mean"] == 5.0
    assert summary["repeat_stability"]["status"] == "unavailable"
