#!/usr/bin/env python3
"""Bind unresolved inference cases to pre-official alternate-model routes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from public_core_merge import SUITES


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def build_operational_failure_routes(
    *, composite_root: Path, retry_plan: Path, output_path: Path
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"operational failure route output exists: {output_path}")
    plan = _load(retry_plan)
    failures = plan.get("failures", [])
    if (
        plan.get("schema") != "folynta.public-core-operational-retry-plan.v1"
        or int(plan.get("failed_input_count", -1)) != len(failures)
    ):
        raise ValueError("operational retry plan identity or coverage is invalid")

    summaries: dict[tuple[int, str], tuple[dict[str, Any], str]] = {}
    for worker in range(4):
        for suite in SUITES:
            path = composite_root / f"worker-{worker:02d}" / suite / "run-summary.json"
            payload = _load(path)
            runs = payload.get("runs", [])
            if len(runs) != 1 or int(runs[0].get("repeat_index", -1)) != 1:
                raise ValueError(f"operational summary is not repeat 1: {path}")
            summaries[(worker, suite)] = (payload, _sha256(path))

    routes: list[dict[str, Any]] = []
    observed: set[tuple[str, str]] = set()
    for failure in failures:
        suite = str(failure["benchmark_id"])
        case_id = str(failure["case_id"])
        worker = int(failure["primary_worker_index"])
        identity = (suite, case_id)
        if identity in observed:
            raise ValueError(f"duplicate operational failure route: {identity}")
        observed.add(identity)
        summary, summary_sha256 = summaries[(worker, suite)]
        cases = {
            str(item["case_id"]): item for item in summary["runs"][0].get("cases", [])
        }
        case = cases.get(case_id)
        if case is None:
            raise ValueError(f"operational failure case is missing: {identity}")
        if case.get("status") == "completed":
            continue
        if case.get("status") != "failed":
            raise ValueError(f"unsupported operational case status: {identity}")
        candidate_models = ["paddleocr-vl-1.6"]
        if suite != "parsebench":
            candidate_models.append("deepseek-ocr-2")
        routes.append(
            {
                "benchmark_id": suite,
                "case_id": case_id,
                "primary_worker_index": worker,
                "request_recovery": True,
                "escalate": False,
                "failure_codes": ["operational_inference_failure"],
                "candidate_models": candidate_models,
                "source_run_summary_sha256": summary_sha256,
                "source_error": str(case.get("error") or "unknown")[:512],
            }
        )

    payload = {
        "schema": "folynta.preofficial-operational-failure-routes.v1",
        "retry_plan_sha256": _sha256(retry_plan),
        "planned_case_count": len(failures),
        "unresolved_case_count": len(routes),
        "recovered_before_alternate_count": len(failures) - len(routes),
        "routes": sorted(routes, key=lambda item: (item["benchmark_id"], item["case_id"])),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return {**payload, "output_sha256": _sha256(output_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--composite-root", type=Path, required=True)
    parser.add_argument("--retry-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_operational_failure_routes(
        composite_root=args.composite_root.resolve(),
        retry_plan=args.retry_plan.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_operational_failure_routes"]
