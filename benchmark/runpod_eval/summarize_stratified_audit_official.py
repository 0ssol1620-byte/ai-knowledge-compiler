#!/usr/bin/env python3
"""Summarize three-repeat inference stability and official audit score variance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")


def _load(path: Path) -> dict[str, Any]:
    # PowerShell-written receipts carry a UTF-8 BOM; utf-8-sig reads both shapes.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _series(values: list[float | int]) -> dict[str, Any]:
    numbers = [float(value) for value in values]
    return {
        "values": numbers,
        "mean": fmean(numbers),
        "population_standard_deviation": pstdev(numbers),
        "minimum": min(numbers),
        "maximum": max(numbers),
        "range": max(numbers) - min(numbers),
    }


def summarize_audit(
    *, results_root: Path, evaluation_root: Path, output_path: Path
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"stratified audit summary exists: {output_path}")
    inference: list[dict[str, Any]] = []
    for suite in SUITES:
        summary_path = results_root / suite / "run-summary.json"
        summary = _load(summary_path)
        runs = summary.get("runs", [])
        if [int(run["repeat_index"]) for run in runs] != [1, 2, 3]:
            raise ValueError(f"stratified audit repeat identity mismatch: {suite}")
        case_hashes: dict[str, list[str]] = {}
        status_by_case: dict[str, list[str]] = {}
        completed_values: list[int] = []
        failed_values: list[int] = []
        latency_values: list[float] = []
        for run in runs:
            completed_values.append(int(run["completed"]))
            failed_values.append(int(run["failed"]))
            latency_values.append(float(run["latency_seconds"]))
            for case in run["cases"]:
                case_id = str(case["case_id"])
                case_hashes.setdefault(case_id, []).append(str(case["markdown_sha256"]))
                status_by_case.setdefault(case_id, []).append(str(case["status"]))
        if len(case_hashes) != 128 or any(len(values) != 3 for values in case_hashes.values()):
            raise ValueError(f"stratified audit case coverage mismatch: {suite}")
        inference.append(
            {
                "benchmark_id": suite,
                "completed": completed_values,
                "failed": failed_values,
                "latency_seconds": _series(latency_values),
                "identical_markdown_all_three_count": sum(
                    len(set(values)) == 1 for values in case_hashes.values()
                ),
                "identical_markdown_all_three_rate": sum(
                    len(set(values)) == 1 for values in case_hashes.values()
                )
                / 128,
                "stable_terminal_status_count": sum(
                    len(set(values)) == 1 for values in status_by_case.values()
                ),
                "stable_terminal_status_rate": sum(
                    len(set(values)) == 1 for values in status_by_case.values()
                )
                / 128,
                "run_summary_sha256": _sha256(summary_path),
            }
        )

    parse_summaries = [
        _load(evaluation_root / "parsebench" / f"repeat-{repeat}" / "evaluation-summary.json")
        for repeat in range(1, 4)
    ]
    omni_summary = _load(
        evaluation_root / "omnidocbench" / "evaluation-summary.json"
    )
    olm_summaries = [
        _load(evaluation_root / "olmocr-bench" / f"repeat-{repeat}" / "evaluation-summary.json")
        for repeat in range(1, 4)
    ]
    parse_failures = [int(item["rule_failure_count"]) for item in parse_summaries]
    omni_records = omni_summary.get("records", [])
    if [int(item["repeat_index"]) for item in omni_records] != [1, 2, 3]:
        raise ValueError("OmniDocBench official audit repeat coverage is invalid")
    omni_failures = [int(item["official_failure_count"]) for item in omni_records]
    olm_scores = [float(item["overall_score"]) for item in olm_summaries]
    olm_failures = [int(item["rule_failure_count"]) for item in olm_summaries]
    receipt: dict[str, Any] = {
        "schema": "folynta.stratified-audit-official-summary.v1",
        "suite_count": 3,
        "input_count_per_suite": 128,
        "repeat_count": 3,
        "total_inference_count": 1152,
        "inference_stability": inference,
        "official_variance": {
            "parsebench_rule_failure_count": _series(parse_failures),
            "omnidocbench_element_failure_count": _series(omni_failures),
            "olmocr_overall_score": _series(olm_scores),
            "olmocr_rule_failure_count": _series(olm_failures),
        },
        "interpretation": {
            "full_corpus_repeat_count": 1,
            "stratified_audit_repeat_count": 3,
            "repetition_scope": "128 cases per suite",
            "three_repeats_are_variance_evidence_not_duplicate_full_corpus_runs": True,
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
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--evaluation-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = summarize_audit(
        results_root=args.results_root.resolve(),
        evaluation_root=args.evaluation_root.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["summarize_audit"]
