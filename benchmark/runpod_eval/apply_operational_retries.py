#!/usr/bin/env python3
"""Create provenance-bound composite worker views after different-worker retry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from public_core_merge import EXPECTED_ARTIFACT_SHA256, EXPECTED_CANDIDATE_ID, SUITES


@dataclass(frozen=True, slots=True)
class ResultSource:
    worker_index: int
    result_root: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> str:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return _sha256(path)


def _model_path(root: Path, case_id: str) -> Path:
    exact = root / "repeat-1" / case_id / "vlm" / f"{case_id}_model.json"
    if exact.is_file():
        return exact
    matches = sorted((root / "repeat-1" / case_id).rglob(f"{case_id}_model.json"))
    if len(matches) != 1:
        raise ValueError(f"retry model payload is not unique for {case_id}")
    return matches[0]


def _replace_bound(source: Path, target: Path, expected_sha256: str) -> None:
    if not source.is_file() or _sha256(source) != expected_sha256:
        raise ValueError(f"retry artifact hash mismatch: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)
    if _sha256(target) != expected_sha256:
        raise ValueError(f"composite artifact hash mismatch: {target}")


def apply_operational_retries(
    *,
    primary_sources: tuple[ResultSource, ...],
    retry_sources: tuple[ResultSource, ...],
    retry_plan: Path,
    output_root: Path,
) -> dict[str, Any]:
    primaries = {item.worker_index: item.result_root for item in primary_sources}
    retries = {item.worker_index: item.result_root for item in retry_sources}
    if set(primaries) != {0, 1, 2, 3} or len(primaries) != len(primary_sources):
        raise ValueError("exactly four unique primary worker sources are required")
    if len(retries) != len(retry_sources) or any(
        not 0 <= index <= 99 for index in retries
    ):
        raise ValueError("retry worker sources must have unique indices between 0 and 99")
    if output_root.exists():
        raise FileExistsError(f"composite output already exists: {output_root}")
    plan = _load(retry_plan)
    failures = plan.get("failures", [])
    if int(plan.get("failed_input_count", -1)) != len(failures):
        raise ValueError("operational retry plan failure coverage is invalid")
    if plan.get("different_worker_only") is not True:
        raise ValueError("operational retry plan is not different-worker-only")
    planned_retry_workers = {int(item["retry_worker_index"]) for item in failures}
    if set(retries) != planned_retry_workers:
        raise ValueError("retry worker sources do not exactly match the retry plan")

    output_root.mkdir(parents=True)
    original_summary_hashes: dict[tuple[int, str], str] = {}
    for worker_index in range(4):
        target = output_root / f"worker-{worker_index:02d}"
        shutil.copytree(primaries[worker_index], target, copy_function=os.link)
        for suite in SUITES:
            summary_path = primaries[worker_index] / suite / "run-summary.json"
            original_summary_hashes[(worker_index, suite)] = _sha256(summary_path)

    retry_case_lookup: dict[tuple[int, str, str], tuple[dict[str, Any], str]] = {}
    retry_summary_hashes: dict[tuple[int, str], str] = {}
    for retry_worker, root in sorted(retries.items()):
        for suite in SUITES:
            summary_path = root / suite / "run-summary.json"
            if not summary_path.is_file():
                continue
            summary = _load(summary_path)
            if summary.get("candidate_id") != EXPECTED_CANDIDATE_ID:
                raise ValueError(f"retry candidate identity mismatch: {summary_path}")
            if summary.get("artifact_manifest_sha256") != EXPECTED_ARTIFACT_SHA256:
                raise ValueError(f"retry model identity mismatch: {summary_path}")
            runs = summary.get("runs", [])
            if len(runs) != 1 or int(runs[0].get("repeat_index", -1)) != 1:
                raise ValueError(f"retry summary must contain exactly repeat 1: {summary_path}")
            summary_hash = _sha256(summary_path)
            retry_summary_hashes[(retry_worker, suite)] = summary_hash
            for case in runs[0].get("cases", []):
                key = (retry_worker, suite, str(case["case_id"]))
                if key in retry_case_lookup:
                    raise ValueError(f"duplicate retry result case: {key}")
                retry_case_lookup[key] = (case, summary_hash)

    accepted = 0
    unresolved = 0
    case_outcomes: list[dict[str, Any]] = []
    overlays_by_summary: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for failure in failures:
        suite = str(failure["benchmark_id"])
        case_id = str(failure["case_id"])
        primary = int(failure["primary_worker_index"])
        retry_worker = int(failure["retry_worker_index"])
        if primary == retry_worker:
            raise ValueError(f"same-worker retry is forbidden: {suite}/{case_id}")
        observed = retry_case_lookup.get((retry_worker, suite, case_id))
        if observed is None:
            raise ValueError(f"planned retry result is missing: {suite}/{case_id}")
        retry_case, retry_summary_sha256 = observed
        composite_suite = output_root / f"worker-{primary:02d}" / suite
        primary_summary_path = composite_suite / "run-summary.json"
        primary_summary = _load(primary_summary_path)
        primary_cases = {str(item["case_id"]): item for item in primary_summary["runs"][0]["cases"]}
        primary_case = primary_cases.get(case_id)
        if primary_case is None or primary_case.get("status") != "failed":
            raise ValueError(
                f"retry overlay target is not a failed primary case: {suite}/{case_id}"
            )
        retry_status = str(retry_case.get("status"))
        overlay = {
            "benchmark_id": suite,
            "case_id": case_id,
            "primary_worker_index": primary,
            "retry_worker_index": retry_worker,
            "retry_status": retry_status,
            "primary_run_summary_sha256": original_summary_hashes[(primary, suite)],
            "retry_run_summary_sha256": retry_summary_sha256,
        }
        if retry_status == "completed":
            markdown_sha256 = str(retry_case["markdown_sha256"])
            retry_suite = retries[retry_worker] / suite
            _replace_bound(
                retry_suite / "markdown-repeat-1" / f"{case_id}.md",
                composite_suite / "markdown-repeat-1" / f"{case_id}.md",
                markdown_sha256,
            )
            model_source = _model_path(retry_suite, case_id)
            model_sha256 = _sha256(model_source)
            _replace_bound(
                model_source,
                composite_suite / "repeat-1" / case_id / "vlm" / f"{case_id}_model.json",
                model_sha256,
            )
            primary_case.update(
                {
                    "status": "completed",
                    "markdown_sha256": markdown_sha256,
                    "markdown_characters": int(retry_case["markdown_characters"]),
                }
            )
            overlay["accepted"] = True
            overlay["model_sha256"] = model_sha256
            accepted += 1
        elif retry_status == "failed":
            overlay["accepted"] = False
            unresolved += 1
        else:
            raise ValueError(f"unsupported retry status: {suite}/{case_id}/{retry_status}")
        case_outcomes.append(dict(overlay))
        overlays_by_summary.setdefault((primary, suite), []).append(overlay)
        primary_summary["runs"][0]["completed"] = sum(
            item["status"] == "completed" for item in primary_summary["runs"][0]["cases"]
        )
        primary_summary["runs"][0]["failed"] = sum(
            item["status"] == "failed" for item in primary_summary["runs"][0]["cases"]
        )
        primary_summary["operational_retry_overlay"] = sorted(
            overlays_by_summary[(primary, suite)], key=lambda item: str(item["case_id"])
        )
        _write(primary_summary_path, primary_summary)

    receipt: dict[str, Any] = {
        "schema": "folynta.public-core-operational-retry-overlay.v1",
        "retry_plan_sha256": _sha256(retry_plan),
        "planned": len(failures),
        "accepted": accepted,
        "unresolved": unresolved,
        "different_worker_only": True,
        "case_outcomes": sorted(
            case_outcomes,
            key=lambda item: (str(item["benchmark_id"]), str(item["case_id"])),
        ),
        "composite_summaries": [
            {
                "primary_worker_index": worker,
                "benchmark_id": suite,
                "original_sha256": original_summary_hashes[(worker, suite)],
                "composite_sha256": _sha256(
                    output_root / f"worker-{worker:02d}" / suite / "run-summary.json"
                ),
            }
            for worker in range(4)
            for suite in SUITES
        ],
    }
    receipt_path = output_root / "operational-retry-overlay-receipt.json"
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
    parser.add_argument("--primary", action="append", type=_source, required=True)
    parser.add_argument("--retry", action="append", type=_source, required=True)
    parser.add_argument("--retry-plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = apply_operational_retries(
        primary_sources=tuple(args.primary),
        retry_sources=tuple(args.retry),
        retry_plan=args.retry_plan.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ResultSource", "apply_operational_retries"]
