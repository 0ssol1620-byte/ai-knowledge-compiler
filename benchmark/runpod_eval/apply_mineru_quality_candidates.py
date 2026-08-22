#!/usr/bin/env python3
"""Build a full candidate view from successful MinerU quality retries."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

from apply_operational_retries import (
    ResultSource,
    _load,
    _model_path,
    _replace_bound,
    _sha256,
    _write,
)
from public_core_merge import EXPECTED_ARTIFACT_SHA256, EXPECTED_CANDIDATE_ID, SUITES


def apply_quality_candidates(
    *,
    baseline_sources: tuple[ResultSource, ...],
    quality_sources: tuple[ResultSource, ...],
    selective_plan: Path,
    output_root: Path,
) -> dict[str, Any]:
    baselines = {item.worker_index: item.result_root for item in baseline_sources}
    quality = {item.worker_index: item.result_root for item in quality_sources}
    if set(baselines) != {0, 1, 2, 3} or len(baselines) != len(baseline_sources):
        raise ValueError("exactly four unique baseline workers are required")
    if len(quality) != len(quality_sources) or any(
        not 0 <= index <= 99 for index in quality
    ):
        raise ValueError("quality sources must have unique worker indices")
    if output_root.exists():
        raise FileExistsError(f"quality candidate output already exists: {output_root}")
    plan = _load(selective_plan)
    if (
        plan.get("schema") != "folynta.public-core-selective-recovery-staging.v1"
        or plan.get("recovery_model") != "mineru-3.4.4-vlm-quality-retry"
    ):
        raise ValueError("MinerU quality retry plan identity is invalid")
    routes = plan.get("routes", [])
    if int(plan.get("input_count", -1)) != len(routes):
        raise ValueError("MinerU quality retry plan coverage is invalid")
    if plan.get("different_worker_only") is not True:
        raise ValueError("MinerU quality retry plan is not different-worker-only")
    planned_quality_workers = {int(route["recovery_worker_index"]) for route in routes}
    if set(quality) != planned_quality_workers:
        raise ValueError("quality sources do not exactly match the selective plan")

    output_root.mkdir(parents=True)
    original_summary_hashes: dict[tuple[int, str], str] = {}
    for worker_index in range(4):
        target = output_root / f"worker-{worker_index:02d}"
        shutil.copytree(baselines[worker_index], target, copy_function=os.link)
        for suite in SUITES:
            summary = baselines[worker_index] / suite / "run-summary.json"
            original_summary_hashes[(worker_index, suite)] = _sha256(summary)

    quality_lookup: dict[tuple[int, str, str], tuple[dict[str, Any], str]] = {}
    for worker_index, root in sorted(quality.items()):
        for suite in SUITES:
            summary_path = root / suite / "run-summary.json"
            if not summary_path.is_file():
                continue
            summary = _load(summary_path)
            if summary.get("candidate_id") != EXPECTED_CANDIDATE_ID:
                raise ValueError(f"quality candidate identity mismatch: {summary_path}")
            if summary.get("artifact_manifest_sha256") != EXPECTED_ARTIFACT_SHA256:
                raise ValueError(f"quality model identity mismatch: {summary_path}")
            runs = summary.get("runs", [])
            if len(runs) != 1 or int(runs[0].get("repeat_index", -1)) != 1:
                raise ValueError(f"quality summary must contain repeat 1: {summary_path}")
            summary_hash = _sha256(summary_path)
            for case in runs[0].get("cases", []):
                key = (worker_index, suite, str(case["case_id"]))
                if key in quality_lookup:
                    raise ValueError(f"duplicate quality retry case: {key}")
                quality_lookup[key] = (case, summary_hash)

    applied = 0
    inference_failed = 0
    overlays: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for route in routes:
        suite = str(route["benchmark_id"])
        case_id = str(route["case_id"])
        primary = int(route["primary_worker_index"])
        recovery_worker = int(route["recovery_worker_index"])
        if primary == recovery_worker:
            raise ValueError(f"same-worker quality retry is forbidden: {suite}/{case_id}")
        observed = quality_lookup.get((recovery_worker, suite, case_id))
        if observed is None:
            raise ValueError(f"planned quality retry result is missing: {suite}/{case_id}")
        quality_case, quality_summary_hash = observed
        candidate_suite = output_root / f"worker-{primary:02d}" / suite
        summary_path = candidate_suite / "run-summary.json"
        summary = _load(summary_path)
        by_case = {str(item["case_id"]): item for item in summary["runs"][0]["cases"]}
        baseline_case = by_case.get(case_id)
        if baseline_case is None or baseline_case.get("status") != "completed":
            raise ValueError(
                f"official quality retry target is not completed: {suite}/{case_id}"
            )
        status = str(quality_case.get("status"))
        overlay: dict[str, Any] = {
            "case_id": case_id,
            "primary_worker_index": primary,
            "recovery_worker_index": recovery_worker,
            "quality_retry_status": status,
            "baseline_run_summary_sha256": original_summary_hashes[(primary, suite)],
            "quality_run_summary_sha256": quality_summary_hash,
            "candidate_applied": False,
        }
        if status == "completed":
            markdown_sha256 = str(quality_case["markdown_sha256"])
            quality_suite = quality[recovery_worker] / suite
            _replace_bound(
                quality_suite / "markdown-repeat-1" / f"{case_id}.md",
                candidate_suite / "markdown-repeat-1" / f"{case_id}.md",
                markdown_sha256,
            )
            model_source = _model_path(quality_suite, case_id)
            model_sha256 = _sha256(model_source)
            _replace_bound(
                model_source,
                candidate_suite
                / "repeat-1"
                / case_id
                / "vlm"
                / f"{case_id}_model.json",
                model_sha256,
            )
            baseline_case.update(
                {
                    "markdown_sha256": markdown_sha256,
                    "markdown_characters": int(quality_case["markdown_characters"]),
                }
            )
            overlay.update(
                {
                    "candidate_applied": True,
                    "markdown_sha256": markdown_sha256,
                    "model_sha256": model_sha256,
                }
            )
            applied += 1
        elif status == "failed":
            inference_failed += 1
        else:
            raise ValueError(f"unsupported quality retry status: {suite}/{case_id}/{status}")
        overlays.setdefault((primary, suite), []).append(overlay)
        summary["mineru_quality_retry_candidate_overlay"] = sorted(
            overlays[(primary, suite)], key=lambda item: str(item["case_id"])
        )
        _write(summary_path, summary)

    receipt: dict[str, Any] = {
        "schema": "folynta.mineru-quality-retry-candidate-overlay.v1",
        "selective_plan_sha256": _sha256(selective_plan),
        "attempted": len(routes),
        "candidate_outputs_applied": applied,
        "inference_failed": inference_failed,
        "final_acceptance_pending_official_evaluation": True,
        "different_worker_only": True,
        "composite_summaries": [
            {
                "primary_worker_index": worker,
                "benchmark_id": suite,
                "original_sha256": original_summary_hashes[(worker, suite)],
                "candidate_sha256": _sha256(
                    output_root / f"worker-{worker:02d}" / suite / "run-summary.json"
                ),
            }
            for worker in range(4)
            for suite in SUITES
        ],
    }
    receipt_path = output_root / "mineru-quality-retry-candidate-receipt.json"
    receipt["receipt_sha256"] = _write(receipt_path, receipt)
    return receipt


def _source(value: str) -> ResultSource:
    try:
        index, path = value.split("=", 1)
        return ResultSource(int(index), Path(path))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("result source must be INDEX=PATH") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="append", type=_source, required=True)
    parser.add_argument("--quality", action="append", type=_source, required=True)
    parser.add_argument("--selective-plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = apply_quality_candidates(
        baseline_sources=tuple(args.baseline),
        quality_sources=tuple(args.quality),
        selective_plan=args.selective_plan.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["apply_quality_candidates"]
