#!/usr/bin/env python3
"""Gate a candidate evaluation on aggregate official-metric non-regression."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _metrics(root: Path, failure_records: Path) -> dict[str, int | float]:
    parse = _load(root / "parsebench/evaluation-summary.json")
    omni = _load(root / "omnidocbench/evaluation-summary.json")
    olm = _load(root / "olmocr-bench/evaluation-summary.json")
    omni_records = omni.get("records", [])
    if len(omni_records) != 1 or int(omni_records[0].get("repeat_index", -1)) != 1:
        raise ValueError("aggregate gate requires OmniDocBench repeat 1 only")
    failures = _load(failure_records)
    if int(failures.get("record_count", -1)) != len(failures.get("records", [])):
        raise ValueError("aggregate gate failure-record coverage is invalid")
    return {
        "official_failure_record_count": int(failures["record_count"]),
        "parsebench_rule_failure_count": int(parse["rule_failure_count"]),
        "omnidocbench_element_failure_count": int(
            omni_records[0]["official_failure_count"]
        ),
        "olmocr_rule_failure_count": int(olm["rule_failure_count"]),
        "olmocr_overall_score": float(olm["overall_score"]),
    }


def compare_evaluations(
    *,
    baseline_root: Path,
    candidate_root: Path,
    baseline_failure_records: Path,
    candidate_failure_records: Path,
    output_path: Path,
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"aggregate official comparison exists: {output_path}")
    baseline = _metrics(baseline_root, baseline_failure_records)
    candidate = _metrics(candidate_root, candidate_failure_records)
    deltas = {
        "official_failure_records_removed": (
            int(baseline["official_failure_record_count"])
            - int(candidate["official_failure_record_count"])
        ),
        "parsebench_rule_failures_removed": (
            int(baseline["parsebench_rule_failure_count"])
            - int(candidate["parsebench_rule_failure_count"])
        ),
        "omnidocbench_element_failures_removed": (
            int(baseline["omnidocbench_element_failure_count"])
            - int(candidate["omnidocbench_element_failure_count"])
        ),
        "olmocr_rule_failures_removed": (
            int(baseline["olmocr_rule_failure_count"])
            - int(candidate["olmocr_rule_failure_count"])
        ),
        "olmocr_overall_score_gain": (
            float(candidate["olmocr_overall_score"])
            - float(baseline["olmocr_overall_score"])
        ),
    }
    no_regression = (
        all(
            int(deltas[key]) >= 0
            for key in (
                "official_failure_records_removed",
                "parsebench_rule_failures_removed",
                "omnidocbench_element_failures_removed",
                "olmocr_rule_failures_removed",
            )
        )
        and float(deltas["olmocr_overall_score_gain"]) >= -1e-12
    )
    receipt: dict[str, Any] = {
        "schema": "folynta.aggregate-official-metric-comparison.v1",
        "policy": {
            "official_failure_counts_must_not_increase": True,
            "olmocr_overall_score_must_not_decrease": True,
            "floating_tolerance": 1e-12,
            "rollback_entire_candidate_stage_on_regression": True,
        },
        "baseline": baseline,
        "candidate": candidate,
        "delta": deltas,
        "no_regression": no_regression,
        "strict_improvement": no_regression
        and any(float(value) > 1e-12 for value in deltas.values()),
        "evidence": {
            "baseline_failure_records_sha256": _sha256(baseline_failure_records),
            "candidate_failure_records_sha256": _sha256(candidate_failure_records),
            "baseline_evaluation_summaries": {
                suite: _sha256(baseline_root / suite / "evaluation-summary.json")
                for suite in ("parsebench", "omnidocbench", "olmocr-bench")
            },
            "candidate_evaluation_summaries": {
                suite: _sha256(candidate_root / suite / "evaluation-summary.json")
                for suite in ("parsebench", "omnidocbench", "olmocr-bench")
            },
        },
    }
    encoded = json.dumps(
        receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    receipt["receipt_sha256"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--baseline-failure-records", type=Path, required=True)
    parser.add_argument("--candidate-failure-records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = compare_evaluations(
        baseline_root=args.baseline_root.resolve(),
        candidate_root=args.candidate_root.resolve(),
        baseline_failure_records=args.baseline_failure_records.resolve(),
        candidate_failure_records=args.candidate_failure_records.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["compare_evaluations"]
