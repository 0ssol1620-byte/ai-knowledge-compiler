#!/usr/bin/env python3
"""Materialize only officially improved alternate-model recovery cases."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

from apply_alternate_candidates import ALTERNATE_MODELS, _case_lookup
from apply_operational_retries import (
    ResultSource,
    _load,
    _replace_bound,
    _sha256,
    _write,
)
from compare_official_failure_records import validate_accepted_decision
from public_core_merge import EXPECTED_ARTIFACT_SHA256, EXPECTED_CANDIDATE_ID, SUITES


def apply_accepted_alternate_candidates(
    *,
    baseline_sources: tuple[ResultSource, ...],
    candidate_sources: tuple[ResultSource, ...],
    selective_plan: Path,
    comparison: Path,
    recovery_model: str,
    output_root: Path,
) -> dict[str, Any]:
    baselines = {item.worker_index: item.result_root for item in baseline_sources}
    candidates = {item.worker_index: item.result_root for item in candidate_sources}
    if set(baselines) != {0, 1, 2, 3} or set(candidates) != {0, 1, 2, 3}:
        raise ValueError("exactly four baseline and four candidate workers are required")
    if recovery_model not in ALTERNATE_MODELS:
        raise ValueError("unsupported alternate recovery model")
    if output_root.exists():
        raise FileExistsError(f"accepted alternate output exists: {output_root}")
    plan = _load(selective_plan)
    if (
        plan.get("schema") != "folynta.public-core-selective-recovery-staging.v1"
        or plan.get("recovery_model") != recovery_model
    ):
        raise ValueError("alternate recovery plan identity is invalid")
    route_lookup = {
        (str(route["benchmark_id"]), str(route["case_id"])): route
        for route in plan.get("routes", [])
    }
    if len(route_lookup) != int(plan.get("input_count", -1)):
        raise ValueError("alternate recovery plan coverage is invalid")

    compared = _load(comparison)
    if compared.get("schema") != "folynta.public-core-official-failure-comparison.v1":
        raise ValueError("official alternate comparison identity is invalid")
    policy = compared.get("policy", {})
    if not all(
        policy.get(key) is True
        for key in (
            "require_strict_failure_record_reduction",
            "forbid_new_failure_codes",
            "forbid_candidate_escalation",
            "unchanged_candidates_are_not_accepted",
        )
    ):
        raise ValueError("official alternate acceptance policy is incomplete")
    accepted = {
        (str(item["benchmark_id"]), str(item["case_id"])): item
        for item in compared.get("accepted_quality_cases", [])
    }
    if len(accepted) != int(compared.get("accepted_quality_case_count", -1)):
        raise ValueError("accepted alternate case coverage is invalid")
    if not set(accepted).issubset(route_lookup):
        raise ValueError("accepted alternate case is absent from its selective plan")
    for decision in accepted.values():
        validate_accepted_decision(decision)

    output_root.mkdir(parents=True)
    for worker in range(4):
        shutil.copytree(
            baselines[worker], output_root / f"worker-{worker:02d}", copy_function=os.link
        )

    overlays: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for key, decision in sorted(accepted.items()):
        suite, case_id = key
        primary = int(route_lookup[key]["primary_worker_index"])
        baseline_suite = output_root / f"worker-{primary:02d}" / suite
        candidate_suite = candidates[primary] / suite
        baseline_summary_path = baseline_suite / "run-summary.json"
        candidate_summary_path = candidate_suite / "run-summary.json"
        baseline_summary = _load(baseline_summary_path)
        candidate_summary = _load(candidate_summary_path)
        for summary in (baseline_summary, candidate_summary):
            if (
                summary.get("candidate_id") != EXPECTED_CANDIDATE_ID
                or summary.get("artifact_manifest_sha256") != EXPECTED_ARTIFACT_SHA256
            ):
                raise ValueError(f"accepted alternate MinerU identity mismatch: {key}")
        baseline_case = _case_lookup(baseline_summary).get(case_id)
        candidate_case = _case_lookup(candidate_summary).get(case_id)
        if (
            baseline_case is None
            or candidate_case is None
            or baseline_case.get("status") != "completed"
            or candidate_case.get("status") != "completed"
        ):
            raise ValueError(f"accepted alternate case is not completed: {key}")
        markdown_sha256 = str(candidate_case["markdown_sha256"])
        _replace_bound(
            candidate_suite / "markdown-repeat-1" / f"{case_id}.md",
            baseline_suite / "markdown-repeat-1" / f"{case_id}.md",
            markdown_sha256,
        )
        model_sha256: str | None = None
        if suite == "parsebench":
            model_source = (
                candidate_suite
                / "repeat-1"
                / case_id
                / "vlm"
                / f"{case_id}_model.json"
            )
            model_sha256 = _sha256(model_source)
            _replace_bound(
                model_source,
                baseline_suite
                / "repeat-1"
                / case_id
                / "vlm"
                / f"{case_id}_model.json",
                model_sha256,
            )
        baseline_case.update(
            {
                "markdown_sha256": markdown_sha256,
                "markdown_characters": int(candidate_case["markdown_characters"]),
            }
        )
        overlay = {
            "benchmark_id": suite,
            "case_id": case_id,
            "recovery_model": recovery_model,
            "primary_worker_index": primary,
            "baseline_failure_record_count": int(decision["baseline_failure_record_count"]),
            "candidate_failure_record_count": int(decision["candidate_failure_record_count"]),
            "accepted": True,
            "markdown_sha256": markdown_sha256,
            "model_sha256": model_sha256,
        }
        overlays.setdefault((primary, suite), []).append(overlay)
        baseline_summary[f"accepted_{recovery_model}_overlay"] = sorted(
            overlays[(primary, suite)], key=lambda item: str(item["case_id"])
        )
        _write(baseline_summary_path, baseline_summary)

    receipt: dict[str, Any] = {
        "schema": "folynta.accepted-alternate-recovery-overlay.v1",
        "recovery_model": recovery_model,
        "selective_plan_sha256": _sha256(selective_plan),
        "comparison_sha256": _sha256(comparison),
        "accepted_case_count": len(accepted),
        "rejected_or_unchanged_case_count": int(compared["compared_recoverable_case_count"])
        - len(accepted),
        "strict_no_regression_policy_enforced": True,
        "accepted_cases": [item for values in overlays.values() for item in values],
        "composite_summaries": [
            {
                "worker_index": worker,
                "benchmark_id": suite,
                "sha256": _sha256(
                    output_root / f"worker-{worker:02d}" / suite / "run-summary.json"
                ),
            }
            for worker in range(4)
            for suite in SUITES
        ],
    }
    receipt_path = output_root / f"accepted-{recovery_model}-overlay-receipt.json"
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
    parser.add_argument("--candidate", action="append", type=_source, required=True)
    parser.add_argument("--selective-plan", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--recovery-model", choices=ALTERNATE_MODELS, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = apply_accepted_alternate_candidates(
        baseline_sources=tuple(args.baseline),
        candidate_sources=tuple(args.candidate),
        selective_plan=args.selective_plan.resolve(),
        comparison=args.comparison.resolve(),
        recovery_model=args.recovery_model,
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["apply_accepted_alternate_candidates"]
