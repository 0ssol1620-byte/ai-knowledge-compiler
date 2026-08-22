#!/usr/bin/env python3
"""Build a publication-safe OmniDocBench evidence summary.

The inference worker never receives ground truth.  This utility runs only in the
evaluation environment and deliberately separates valid metrics from evaluator
infrastructure failures (for example, an unavailable CDM toolchain).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _metric(metrics: dict[str, Any], *path: str) -> float:
    current: Any = metrics
    for segment in path:
        current = current[segment]
    value = float(current)
    if not math.isfinite(value):
        raise ValueError(f"non-finite metric at {'.'.join(path)}")
    return value


def summarize_metric_result(path: Path, repeat_index: int) -> dict[str, Any]:
    metrics = json.loads(path.read_text(encoding="utf-8"))
    page_count = int(metrics["match_debug"]["page_count"])
    cdm_debug = metrics["display_formula"].get("metric_debug", {}).get("CDM", {})
    cdm_samples = int(cdm_debug.get("sample_count", 0))
    cdm_exceptions = int(cdm_debug.get("exception_case_count", 0))
    cdm_timeouts = int(cdm_debug.get("timeout_case_count", 0))
    cdm_valid = cdm_samples > 0 and cdm_exceptions == 0 and cdm_timeouts == 0

    return {
        "repeat_index": repeat_index,
        "page_count": page_count,
        "metrics": {
            "text_edit_distance_page_average": _metric(
                metrics, "text_block", "all", "Edit_dist", "ALL_page_avg"
            ),
            "formula_edit_distance_page_average": _metric(
                metrics, "display_formula", "all", "Edit_dist", "ALL_page_avg"
            ),
            "table_teds_sample_average": _metric(
                metrics, "table", "all", "TEDS", "all"
            ),
            "table_teds_structure_sample_average": _metric(
                metrics, "table", "all", "TEDS_structure_only", "all"
            ),
            "table_edit_distance_page_average": _metric(
                metrics, "table", "all", "Edit_dist", "ALL_page_avg"
            ),
            "reading_order_edit_distance_page_average": _metric(
                metrics, "reading_order", "all", "Edit_dist", "ALL_page_avg"
            ),
        },
        "cdm": {
            "status": "valid" if cdm_valid else "unavailable",
            "sample_count": cdm_samples,
            "exception_count": cdm_exceptions,
            "timeout_count": cdm_timeouts,
            "score": (
                _metric(metrics, "display_formula", "all", "CDM", "all")
                if cdm_valid
                else None
            ),
            "reason": (
                None
                if cdm_valid
                else (
                    "CDM was not executed or its rendering toolchain was unavailable; "
                    "no model score is reported."
                )
            ),
        },
        "source": {"path": path.name, "sha256": sha256_file(path)},
    }


def _aggregate(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values),
        "min": min(values),
        "max": max(values),
        "population_stddev": statistics.pstdev(values),
    }


def summarize_repeat_stability(
    inference_runs: list[dict[str, Any]], page_count: int, predictions_root: Path
) -> dict[str, Any]:
    digest_maps: list[dict[str, str]] = []
    prediction_dirs = [
        predictions_root / f"markdown-repeat-{index}"
        for index in range(1, len(inference_runs) + 1)
    ]
    if all(path.is_dir() for path in prediction_dirs):
        digest_maps = [
            {path.stem: sha256_file(path) for path in sorted(directory.glob("*.md"))}
            for directory in prediction_dirs
        ]
    for run in (() if digest_maps else inference_runs):
        cases = run.get("cases")
        if not isinstance(cases, list):
            return {
                "status": "unavailable",
                "reason": "inference run summary has no page-level cases",
                "exact_page_count": None,
                "page_count": page_count,
                "exact_repeat_ratio": None,
            }
        case_digests: dict[str, str] = {}
        for case in cases:
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("case_id", "")).strip()
            digest = str(case.get("markdown_sha256") or "").strip()
            if case_id and digest:
                case_digests[case_id] = digest
        digest_maps.append(case_digests)
    identities = set(digest_maps[0]) if digest_maps else set()
    if len(identities) != page_count or any(set(row) != identities for row in digest_maps):
        raise ValueError("repeat stability cases do not match the evaluated page set")
    exact = sum(
        len({row[case_id] for row in digest_maps}) == 1 for case_id in identities
    )
    return {
        "status": "available",
        "reason": None,
        "exact_page_count": exact,
        "page_count": page_count,
        "exact_repeat_ratio": exact / page_count,
    }


def build_summary(
    *,
    metric_paths: list[Path],
    run_summary_path: Path,
    model_id: str,
    corpus_id: str,
    evaluator_revision: str,
    provider_hourly_usd: float,
) -> dict[str, Any]:
    if len(metric_paths) < 1:
        raise ValueError("at least one metric result is required")
    repeats = [
        summarize_metric_result(path, index)
        for index, path in enumerate(metric_paths, start=1)
    ]
    page_counts = {repeat["page_count"] for repeat in repeats}
    if len(page_counts) != 1:
        raise ValueError("metric repeats do not cover the same page count")

    run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
    inference_runs = run_summary.get("runs", [])
    if len(inference_runs) != len(repeats):
        raise ValueError("inference and evaluation repeat counts differ")
    if any(run.get("failed") or run.get("timed_out") for run in inference_runs):
        raise ValueError("failed or timed-out inference cannot be promoted")

    latencies = [
        float(
            run["latency_seconds"]
            if "latency_seconds" in run
            else run["total_latency_seconds"]
        )
        for run in inference_runs
    ]
    page_count = next(iter(page_counts))
    seconds_per_page = [seconds / page_count for seconds in latencies]
    costs_per_page = [seconds / 3600.0 * provider_hourly_usd / page_count for seconds in latencies]
    repeat_stability = summarize_repeat_stability(
        inference_runs, page_count, run_summary_path.parent
    )

    metric_names = tuple(repeats[0]["metrics"].keys())
    aggregate_metrics = {
        name: _aggregate([float(repeat["metrics"][name]) for repeat in repeats])
        for name in metric_names
    }
    cdm_valid = all(repeat["cdm"]["status"] == "valid" for repeat in repeats)

    return {
        "schema_version": SCHEMA_VERSION,
        "claim_class": "internal_reproducibility_evidence",
        "promotion_status": "eligible_partial_metrics" if len(repeats) >= 3 else "diagnostic_only",
        "overall_score_status": "available" if cdm_valid else "unavailable",
        "overall_score": None,
        "model_id": model_id,
        "corpus": {
            "id": corpus_id,
            "page_count": page_count,
            "ground_truth_mounted_on_inference_worker": False,
        },
        "evaluator_revision": evaluator_revision,
        "repeat_count": len(repeats),
        "valid_partial_metrics": aggregate_metrics,
        "performance": {
            "latency_seconds_per_repeat": latencies,
            "seconds_per_page": _aggregate(seconds_per_page),
            "provider_hourly_usd_observed": provider_hourly_usd,
            "estimated_provider_cost_per_page_usd": _aggregate(costs_per_page),
            "cost_scope": "runtime estimate; not invoice reconciliation",
        },
        "repeat_stability": repeat_stability,
        "excluded_metrics": {
            "cdm": {
                "status": "valid" if cdm_valid else "unavailable",
                "reason": (
                    None
                    if cdm_valid
                    else "CDM was excluded from or unavailable in evaluator repeats."
                ),
            }
        },
        "repeats": repeats,
        "sources": {
            "inference_run_summary": {
                "path": run_summary_path.name,
                "sha256": sha256_file(run_summary_path),
            }
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metric-result", action="append", required=True, type=Path)
    parser.add_argument("--run-summary", required=True, type=Path)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--evaluator-revision", required=True)
    parser.add_argument("--provider-hourly-usd", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_summary(
        metric_paths=args.metric_result,
        run_summary_path=args.run_summary,
        model_id=args.model_id,
        corpus_id=args.corpus_id,
        evaluator_revision=args.evaluator_revision,
        provider_hourly_usd=args.provider_hourly_usd,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
