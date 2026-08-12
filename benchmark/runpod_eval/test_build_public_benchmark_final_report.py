from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.runpod_eval.build_public_benchmark_final_report import (
    _aggregate_stage,
    _final_evaluation_root,
    _longest_observed_no_progress,
    _milestone,
    _recovery_runtime_policy,
    _timestamp,
    _validate_expansion_evidence,
    _write_korean_final_markdown,
)


def _evidence() -> dict[str, object]:
    manifest = "sha256:model"
    return {
        "status": "ready_identity_bound_and_smoke_passed",
        "expansion_worker_count": 3,
        "model_artifact_manifest_sha256": manifest,
        "workers": [
            {
                "worker_index": index,
                "model_artifact_manifest_sha256": manifest,
                "nonempty_smoke_markdown_count": 1,
            }
            for index in (4, 5, 6)
        ],
    }


def test_validate_expansion_evidence_binds_three_identical_workers() -> None:
    assert _validate_expansion_evidence(_evidence()) == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "bootstrapping"),
        ("expansion_worker_count", 2),
    ],
)
def test_validate_expansion_evidence_rejects_incomplete_receipts(
    field: str, value: object
) -> None:
    evidence = _evidence()
    evidence[field] = value
    with pytest.raises(ValueError):
        _validate_expansion_evidence(evidence)


def test_validate_expansion_evidence_rejects_model_mismatch() -> None:
    evidence = _evidence()
    workers = evidence["workers"]
    assert isinstance(workers, list)
    workers[1]["model_artifact_manifest_sha256"] = "sha256:different"
    with pytest.raises(ValueError):
        _validate_expansion_evidence(evidence)


def test_timestamp_rejects_naive_values() -> None:
    with pytest.raises(ValueError):
        _timestamp("2026-08-04T12:00:00")


def test_milestone_binds_timestamp_and_hash(tmp_path: Path) -> None:
    receipt = tmp_path / "terminal.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "complete",
                "completed_at_utc": "2026-08-04T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    milestone = _milestone(receipt, tmp_path)
    assert milestone is not None
    assert milestone["path"] == "terminal.json"
    assert milestone["status"] == "complete"
    assert milestone["sha256"].startswith("sha256:")


def test_longest_observed_no_progress_measures_between_output_changes(
    tmp_path: Path,
) -> None:
    progress = tmp_path / "progress.jsonl"
    records = [
        {
            "observed_at_utc": "2026-08-04T12:00:00Z",
            "workers": [
                {
                    "worker_index": 0,
                    "parsebench_directories": 10,
                    "omnidocbench_directories": 0,
                    "olmocr_bench_directories": 0,
                }
            ],
        },
        {
            "observed_at_utc": "2026-08-04T12:16:00Z",
            "workers": [
                {
                    "worker_index": 0,
                    "parsebench_directories": 10,
                    "omnidocbench_directories": 1,
                    "olmocr_bench_directories": 0,
                }
            ],
        },
    ]
    progress.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )

    result = _longest_observed_no_progress(progress)
    assert result["worker_index"] == 0
    assert result["seconds"] == 960
    assert result["minutes"] == 16


def test_aggregate_stage_requires_accept_or_rollback_consistency(
    tmp_path: Path,
) -> None:
    comparison = tmp_path / "aggregate.json"
    comparison.write_text(
        json.dumps(
            {
                "schema": "folynta.aggregate-official-metric-comparison.v1",
                "no_regression": False,
                "delta": {"olmocr_overall_score_gain": -0.01},
            }
        ),
        encoding="utf-8",
    )

    stage = _aggregate_stage(
        repository=tmp_path, comparison=str(comparison), rollback=True
    )
    assert stage["status"] == "rolled_back_aggregate_regression"
    assert stage["rollback"] is True

    with pytest.raises(ValueError):
        _aggregate_stage(
            repository=tmp_path, comparison=str(comparison), rollback=False
        )


def test_final_evaluation_root_supports_full_aggregate_rollback(tmp_path: Path) -> None:
    failures = (
        tmp_path
        / "folynta-mineru344-public-core-official-failures-r1-2026-08-04.json"
    )
    expected = (
        tmp_path
        / "benchmark/reports/generated"
        / "folynta-mineru344-public-core-official-evaluations-r1-2026-08-04"
    )
    assert _final_evaluation_root(tmp_path, failures) == expected


def test_final_evaluation_root_supports_current_baseline_failure_name(
    tmp_path: Path,
) -> None:
    failures = (
        tmp_path / "folynta-mineru344-public-failure-records-r1-2026-08-04.json"
    )
    expected = (
        tmp_path
        / "benchmark/reports/generated"
        / "folynta-mineru344-public-core-official-evaluations-r1-2026-08-04"
    )
    assert _final_evaluation_root(tmp_path, failures) == expected


def test_korean_final_markdown_is_utf8_and_human_readable(tmp_path: Path) -> None:
    report = {
        "scope": {"full_corpus_input_count": 5132},
        "selection": {
            "policy": "official-metric-improvement-only",
            "paddle_routed_case_count": 2,
            "paddle_accepted_case_count": 1,
            "paddle_reverted_regression_case_count": 1,
            "deepseek_routed_case_count": 3,
            "deepseek_accepted_case_count": 2,
            "deepseek_reverted_regression_case_count": 1,
        },
        "cost": {
            "total_runtime_rate_estimate_usd": 123.456,
            "approved_cap_usd": 400,
            "within_approved_cap": True,
        },
        "timing": {"elapsed_hours_to_report": 24.5},
        "case_zero_official_failure_accuracy": {
            suite: {
                "input_count": 10,
                "baseline_cases_with_zero_official_failures": 7,
                "final_cases_with_zero_official_failures": 9,
                "absolute_rate_gain": 0.2,
                "additional_cases_cleared": 2,
            }
            for suite in ("parsebench", "omnidocbench", "olmocr-bench")
        },
        "official_metrics": {
            "delta": {
                "parsebench_rule_failures_removed": 2,
                "omnidocbench_element_failures_removed": 3,
                "olmocr_overall_score_gain": 0.01,
                "official_failure_records_removed": 5,
            }
        },
        "operational_fault_detection": {"f1": 1.0},
        "recovery_runtime_policy": {
            "batch_size_cases": 1,
            "per_case_timeout_seconds": 1800,
            "live_primary_stall_recovery": {
                "stall_threshold_seconds": 900,
                "batch_size_cases_after_recovery": 1,
                "per_case_timeout_seconds_after_recovery": 900,
                "resume_completed_outputs": True,
            },
        },
        "three_repeat_variance_audit": {"inference_count": 1152},
        "evidence": {
            "detection_report": "detection.json",
            "detection_report_sha256": "sha256:detection",
        },
        "receipt_sha256": "sha256:report",
    }
    output = tmp_path / "final-report-ko.md"

    _write_korean_final_markdown(report=report, output_markdown=output)

    text = output.read_text(encoding="utf-8")
    assert "FOLYNTA 전체 공개 벤치마크 장애 복구 최종 보고서" in text
    assert "공개 벤치마크 5,132건" in text
    assert "3회 층화 표본 반복 검증" in text
    assert "장애 복구 실행 정책" in text
    assert '"stall_threshold_seconds": 900' in text
    assert '"resume_completed_outputs": true' in text
    assert "RunPod 공급자 청구 합계: USD 123.456000" in text
    assert "\ufffd" not in text


def test_recovery_runtime_policy_binds_live_primary_stall_guard(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[2]
    progress = tmp_path / "progress.jsonl"
    progress.write_text(
        "\n".join(
            json.dumps(record)
            for record in (
                {
                    "observed_at_utc": "2026-08-05T00:00:00Z",
                    "workers": [
                        {
                            "worker_index": 0,
                            "parsebench_directories": 10,
                            "omnidocbench_directories": 0,
                            "olmocr_bench_directories": 0,
                        }
                    ],
                },
                {
                    "observed_at_utc": "2026-08-05T00:16:00Z",
                    "workers": [
                        {
                            "worker_index": 0,
                            "parsebench_directories": 11,
                            "omnidocbench_directories": 0,
                            "olmocr_bench_directories": 0,
                        }
                    ],
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )

    policy = _recovery_runtime_policy(
        repository=repository,
        primary_progress=progress,
    )

    live = policy["live_primary_stall_recovery"]
    assert live["stall_threshold_seconds"] == 900
    assert live["batch_size_cases_after_recovery"] == 1
    assert live["per_case_timeout_seconds_after_recovery"] == 900
    assert live["resume_completed_outputs"] is True
    # Each retry lane reports the timeout it actually pins, so a lane that was
    # tightened after live measurement cannot be described by a stale constant.
    lanes = policy["per_case_timeout_seconds_by_lane"]
    assert set(lanes) == {"operational_retry", "mineru_quality_retry"}
    assert all(isinstance(value, int) and value > 0 for value in lanes.values())
    assert policy["per_case_timeout_seconds"] == lanes["operational_retry"]
    assert policy["longest_observed_primary_no_new_directory"]["seconds"] == 960
    assert {
        "full_worker",
        "full_stall_guard",
        "full_stall_recovery",
    } <= set(policy["source_sha256"])
