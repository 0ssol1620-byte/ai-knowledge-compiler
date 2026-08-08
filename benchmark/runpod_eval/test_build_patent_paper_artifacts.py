from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from benchmark.runpod_eval.build_patent_paper_artifacts import build_artifacts


def _metric(tp: int, fp: int, fn: int, tn: int) -> dict[str, int | float]:
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
    }


def _report() -> dict[str, object]:
    accuracy = {
        suite: {
            "input_count": count,
            "baseline_cases_with_zero_official_failures": baseline,
            "final_cases_with_zero_official_failures": final,
            "absolute_rate_gain": (final - baseline) / count,
            "additional_cases_cleared": final - baseline,
        }
        for suite, count, baseline, final in (
            ("parsebench", 2078, 1500, 1800),
            ("omnidocbench", 1651, 1200, 1500),
            ("olmocr-bench", 1403, 900, 1200),
        )
    }
    stability = [
        {
            "benchmark_id": suite,
            "identical_markdown_all_three_count": identical,
            "identical_markdown_all_three_rate": identical / 128,
            "stable_terminal_status_count": 128,
            "stable_terminal_status_rate": 1.0,
        }
        for suite, identical in zip(
            ("parsebench", "omnidocbench", "olmocr-bench"),
            (120, 124, 126),
            strict=True,
        )
    ]
    return {
        "schema": "folynta.public-benchmark-recovery-final-report.v1",
        "status": "complete_and_officially_verified",
        "created_at_utc": "2026-08-05T12:00:00+00:00",
        "scope": {
            "full_corpus_input_count": 5132,
            "full_corpus_repeat_count": 1,
            "stratified_audit_input_count_per_suite": 128,
            "stratified_audit_repeat_count": 3,
            "stratified_audit_inference_count": 1152,
        },
        "selection": {
            "paddle_routed_case_count": 100,
            "paddle_accepted_case_count": 70,
            "paddle_reverted_regression_case_count": 30,
            "deepseek_routed_case_count": 40,
            "deepseek_accepted_case_count": 25,
            "deepseek_reverted_regression_case_count": 15,
        },
        "case_zero_official_failure_accuracy": accuracy,
        "official_metrics": {
            "delta": {
                "parsebench_rule_failures_removed": 300,
                "omnidocbench_element_failures_removed": 250,
                "olmocr_overall_score_gain": 0.02,
                "official_failure_records_removed": 850,
            }
        },
        "operational_fault_detection": {
            "case_failure_detection": _metric(1788, 0, 0, 3344),
            "worker_anomaly_detection": _metric(2, 0, 0, 2),
            "worker_repeated_stall_quarantine": _metric(1, 0, 0, 3),
        },
        "three_repeat_variance_audit": {
            "repeat_count": 3,
            "inference_stability": stability,
        },
        "timing": {"elapsed_hours_to_report": 28.5},
        "cost": {
            "total_runtime_rate_estimate_usd": 186.25,
            "approved_cap_usd": 400,
            "within_approved_cap": True,
        },
    }


def _write_inputs(root: Path) -> tuple[Path, Path, Path]:
    generated = root / "benchmark/reports/generated"
    generated.mkdir(parents=True)
    report = generated / "final.json"
    patent = generated / "patent.json"
    service = generated / "service.json"
    report.write_text(json.dumps(_report()), encoding="utf-8")
    patent.write_text(
        json.dumps({"schema": "folynta.patent-technical-evidence-index.v1"}),
        encoding="utf-8",
    )
    service.write_text(
        json.dumps(
            {
                "schema": "folynta.service-recovery-equivalence-evaluation.v1",
                "status": "complete_service_recovery_equivalence_verified",
                "gate_passed": True,
            }
        ),
        encoding="utf-8",
    )
    return report, patent, service


def test_builds_patent_paper_figures_data_and_reproducibility_bundle(
    tmp_path: Path,
) -> None:
    report, patent, service = _write_inputs(tmp_path)
    output = tmp_path / "benchmark/reports/generated/patent-paper"

    manifest = build_artifacts(
        repository=tmp_path,
        final_report_path=report,
        patent_index_path=patent,
        service_evidence_path=service,
        output_root=output,
    )

    assert manifest["status"] == "complete_real_evidence_only"
    assert manifest["truth_policy"]["image_generation_used"] is False
    assert len(manifest["assets"]) == 8
    assert {asset["truth_class"] for asset in manifest["assets"]} == {"T0", "T1"}
    assert all(asset["generated_with_ai"] is False for asset in manifest["assets"])
    assert all(len(asset["derivatives"]) == 2 for asset in manifest["assets"])
    assert (output / "artifact-provenance-manifest.json").is_file()
    assert (output / "patent/CLAIM_EVIDENCE_TECHNICAL_MAP.csv").is_file()
    assert (
        output
        / "paper/FOLYNTA_PUBLIC_BENCHMARK_TECHNICAL_REPORT.artifact.json"
    ).is_file()
    assert (output / "reproducibility/chart-contracts.json").is_file()
    png = output / "paper/figures/FIG-01-zero-official-failure-rate.png"
    svg = output / "paper/figures/FIG-01-zero-official-failure-rate.svg"
    with Image.open(png) as image:
        assert image.size == (2800, 1800)
        assert image.info["dpi"][0] == pytest.approx(300, abs=1)
    assert svg.read_text(encoding="utf-8").startswith("<?xml")
    artifact = json.loads(
        (
            output
            / "paper/FOLYNTA_PUBLIC_BENCHMARK_TECHNICAL_REPORT.artifact.json"
        ).read_text(encoding="utf-8")
    )
    assert artifact["surface"] == "report"
    assert artifact["snapshot"]["status"] == "ready"
    assert artifact["manifest"]["blocks"][0]["body"].startswith("# FOLYNTA")


def test_rejects_incomplete_or_nonfinal_evidence(tmp_path: Path) -> None:
    report, patent, service = _write_inputs(tmp_path)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["status"] = "partial"
    report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="not complete"):
        build_artifacts(
            repository=tmp_path,
            final_report_path=report,
            patent_index_path=patent,
            service_evidence_path=service,
            output_root=tmp_path / "output",
        )

