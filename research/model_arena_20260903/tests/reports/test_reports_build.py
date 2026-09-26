"""End-to-end: every masterplan section 29 file, generated from the synthetic fixture."""

from __future__ import annotations

import csv
from pathlib import Path

from arena.reports.build import build_reports
from arena.reports.paths import SourcePaths

MODELS = ("paddleocr_vl_1_6", "mineru_pipeline", "opus5_subscription")
BENCHMARKS = ("parsebench", "omnidoc", "olmocr")

REPORT_FILES = (
    "LEADERBOARD.md",
    "leaderboard.csv",
    "benchmark_breakdown.csv",
    "document_type_breakdown.csv",
    "latency_report.csv",
    "gpu_resource_report.csv",
    "cost_report.csv",
    "reliability_report.csv",
    "failure_taxonomy.csv",
    "runtime_failures.csv",
    "tavonel_ablation.csv",
    "tavonel_routes.csv",
    "recovery_report.csv",
    "opus_subscription_report.csv",
    "model_disagreement.csv",
    "pareto_frontier.csv",
    "executive_summary_ko.md",
    "methodology.md",
)

EVIDENCE_FILES = (
    "campaign_manifest.json",
    "model_registry.json",
    "evaluator_registry.json",
    "source_hashes.jsonl",
    "prompt_hashes.json",
    "output_hashes.jsonl",
    "route_decision_hashes.jsonl",
    "cleanup_receipt.json",
    "FINAL_EVIDENCE_MANIFEST.json",
)


def _csv_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle))


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_build_reports_writes_every_masterplan_29_file(campaign_root: Path) -> None:
    result = build_reports(
        source_root=SourcePaths(root=campaign_root),
        models=MODELS,
        benchmarks=BENCHMARKS,
        with_evidence=True,
    )
    reports_dir = campaign_root / "reports"
    for filename in REPORT_FILES:
        path = reports_dir / filename
        assert path.is_file(), f"{filename} was not written"
        assert path.stat().st_size > 0
    assert set(result.reports_written) == set(REPORT_FILES)

    evidence_dir = campaign_root / "evidence"
    for filename in EVIDENCE_FILES:
        assert (evidence_dir / filename).is_file(), f"evidence/{filename} was not written"


def test_build_reports_every_csv_has_its_declared_header(campaign_root: Path) -> None:
    build_reports(source_root=SourcePaths(root=campaign_root), models=MODELS, benchmarks=BENCHMARKS)
    reports_dir = campaign_root / "reports"
    expected_headers = {
        "leaderboard.csv": (
            "System",
            "ParseBench",
            "OmniDoc",
            "olmOCR",
            "completion",
            "sec_per_page",
            "gpu_or_api_equivalent_cost_usd_per_1000_pages",
            "retry_pct",
            "stall_pct",
            "unresolved_pct",
            "data_gaps",
        ),
        "benchmark_breakdown.csv": ("model_key", "benchmark", "metric", "value", "reason"),
        "pareto_frontier.csv": (
            "benchmark",
            "system",
            "x_axis",
            "x_value",
            "y_quality",
            "pareto_non_dominated",
            "reason",
        ),
    }
    for filename, header in expected_headers.items():
        assert tuple(_csv_header(reports_dir / filename)) == header


def test_build_reports_leaderboard_has_a_row_per_model(campaign_root: Path) -> None:
    build_reports(source_root=SourcePaths(root=campaign_root), models=MODELS, benchmarks=BENCHMARKS)
    rows = _csv_rows(campaign_root / "reports" / "leaderboard.csv")
    assert {row["System"] for row in rows} <= {
        "Paddleocr Vl 1 6",
        "Mineru Pipeline",
        "Opus5 Subscription",
    }
    assert len(rows) == len(MODELS)


def test_build_reports_never_writes_a_zero_for_a_missing_metric(campaign_root: Path) -> None:
    # opus5_subscription/olmocr has no scores/summary.json in the fixture on purpose.
    build_reports(source_root=SourcePaths(root=campaign_root), models=MODELS, benchmarks=BENCHMARKS)
    rows = {row["System"]: row for row in _csv_rows(campaign_root / "reports" / "leaderboard.csv")}
    opus_row = rows["Opus5 Subscription"]
    assert opus_row["olmOCR"] == "n/a"
    assert opus_row["olmOCR"] != "0"


def test_build_reports_missing_cost_ledger_gives_na_not_crash(campaign_root: Path) -> None:
    (campaign_root / "cost" / "pod_ledger.jsonl").unlink()
    result = build_reports(
        source_root=SourcePaths(root=campaign_root), models=MODELS, benchmarks=BENCHMARKS
    )
    assert "leaderboard.csv" in result.reports_written


def test_build_reports_pareto_frontier_has_all_three_benchmarks(campaign_root: Path) -> None:
    build_reports(source_root=SourcePaths(root=campaign_root), models=MODELS, benchmarks=BENCHMARKS)
    rows = _csv_rows(campaign_root / "reports" / "pareto_frontier.csv")
    assert {row["benchmark"] for row in rows} == {"ParseBench", "OmniDoc", "olmOCR"}


def test_build_reports_dod_checklist_available_with_evidence_flag(campaign_root: Path) -> None:
    result = build_reports(
        source_root=SourcePaths(root=campaign_root),
        models=MODELS,
        benchmarks=BENCHMARKS,
        with_evidence=True,
    )
    assert result.dod_checklist
    assert any(item.satisfied for item in result.dod_checklist)


def test_build_reports_without_evidence_flag_skips_evidence_dir(campaign_root: Path) -> None:
    build_reports(source_root=SourcePaths(root=campaign_root), models=MODELS, benchmarks=BENCHMARKS)
    assert not (campaign_root / "evidence" / "FINAL_EVIDENCE_MANIFEST.json").is_file()
