from __future__ import annotations

import json
from pathlib import Path

from compare_official_evaluation_metrics import compare_evaluations


def _write_evaluation(
    root: Path,
    *,
    parse_failures: int,
    omni_failures: int,
    olm_failures: int,
    olm_score: float,
) -> None:
    values = {
        "parsebench": {"rule_failure_count": parse_failures},
        "omnidocbench": {
            "records": [
                {
                    "repeat_index": 1,
                    "official_failure_count": omni_failures,
                }
            ]
        },
        "olmocr-bench": {
            "rule_failure_count": olm_failures,
            "overall_score": olm_score,
        },
    }
    for suite, payload in values.items():
        path = root / suite / "evaluation-summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


def _write_failures(path: Path, count: int) -> None:
    path.write_text(
        json.dumps({"record_count": count, "records": [{} for _ in range(count)]}),
        encoding="utf-8",
    )


def test_aggregate_gate_accepts_non_regressing_official_metrics(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_evaluation(
        baseline,
        parse_failures=10,
        omni_failures=20,
        olm_failures=30,
        olm_score=0.8,
    )
    _write_evaluation(
        candidate,
        parse_failures=8,
        omni_failures=20,
        olm_failures=29,
        olm_score=0.81,
    )
    baseline_failures = tmp_path / "baseline-failures.json"
    candidate_failures = tmp_path / "candidate-failures.json"
    _write_failures(baseline_failures, 60)
    _write_failures(candidate_failures, 57)

    result = compare_evaluations(
        baseline_root=baseline,
        candidate_root=candidate,
        baseline_failure_records=baseline_failures,
        candidate_failure_records=candidate_failures,
        output_path=tmp_path / "comparison.json",
    )
    assert result["no_regression"] is True
    assert result["strict_improvement"] is True
    assert result["delta"]["official_failure_records_removed"] == 3


def test_aggregate_gate_rejects_score_regression_despite_fewer_failures(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_evaluation(
        baseline,
        parse_failures=10,
        omni_failures=20,
        olm_failures=30,
        olm_score=0.8,
    )
    _write_evaluation(
        candidate,
        parse_failures=9,
        omni_failures=19,
        olm_failures=29,
        olm_score=0.79,
    )
    baseline_failures = tmp_path / "baseline-failures.json"
    candidate_failures = tmp_path / "candidate-failures.json"
    _write_failures(baseline_failures, 60)
    _write_failures(candidate_failures, 57)

    result = compare_evaluations(
        baseline_root=baseline,
        candidate_root=candidate,
        baseline_failure_records=baseline_failures,
        candidate_failure_records=candidate_failures,
        output_path=tmp_path / "comparison.json",
    )
    assert result["no_regression"] is False
    assert result["strict_improvement"] is False
    assert result["delta"]["olmocr_overall_score_gain"] < 0
