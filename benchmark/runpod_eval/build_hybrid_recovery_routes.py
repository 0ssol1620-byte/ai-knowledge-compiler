#!/usr/bin/env python3
"""Route only failed Paddle candidates to DeepSeek with layout fallback evidence."""

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
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def build_hybrid_recovery_routes(
    *, base_routes: Path, paddle_evidence_root: Path, output_path: Path
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"hybrid recovery route output exists: {output_path}")
    base = _load(base_routes)
    routes = base.get("routes", [])
    if base.get("schema") != "folynta.preofficial-operational-failure-routes.v1":
        raise ValueError("base operational route identity is invalid")
    by_identity = {
        (str(route["benchmark_id"]), str(route["case_id"])): route
        for route in routes
    }
    if len(by_identity) != len(routes):
        raise ValueError("base operational routes contain duplicates")

    failed: list[dict[str, Any]] = []
    for worker in range(4):
        for suite in SUITES:
            summary_path = (
                paddle_evidence_root
                / f"worker-{worker:02d}"
                / suite
                / "run-summary.json"
            )
            if not summary_path.is_file():
                continue
            summary = _load(summary_path)
            if (
                summary.get("candidate_id") != "paddleocr-vl-1.6"
                or summary.get("ground_truth_mounted") is not False
            ):
                raise ValueError(f"Paddle recovery identity mismatch: {summary_path}")
            runs = summary.get("runs", [])
            if len(runs) != 1 or int(runs[0].get("repeat_index", -1)) != 1:
                raise ValueError(f"Paddle recovery repeat identity mismatch: {summary_path}")
            for case in runs[0].get("cases", []):
                if case.get("status") != "failed":
                    continue
                case_id = str(case["case_id"])
                identity = (suite, case_id)
                original = by_identity.get(identity)
                if original is None:
                    raise ValueError(f"failed Paddle case is absent from base routes: {identity}")
                if case.get("error") != "empty_markdown":
                    raise ValueError(f"unsupported Paddle failure for hybrid route: {identity}")
                failed.append(
                    {
                        **original,
                        "candidate_models": ["deepseek-ocr-2"],
                        "source_error": "paddle_empty_markdown",
                        "paddle_recovery_worker_index": worker,
                        "paddle_run_summary_sha256": _sha256(summary_path),
                        "layout_fallback_model": (
                            "paddleocr-vl-1.6" if suite == "parsebench" else None
                        ),
                    }
                )

    failed.sort(key=lambda item: (str(item["benchmark_id"]), str(item["case_id"])))
    if not failed:
        raise ValueError("Paddle evidence contains no hybrid recovery targets")
    identities = [(item["benchmark_id"], item["case_id"]) for item in failed]
    if len(identities) != len(set(identities)):
        raise ValueError("hybrid recovery targets contain duplicates")
    payload = {
        "schema": "folynta.preofficial-hybrid-recovery-routes.v1",
        "base_routes_sha256": _sha256(base_routes),
        "recovery_model": "deepseek-ocr-2",
        "layout_fallback_model": "paddleocr-vl-1.6",
        "unresolved_case_count": len(failed),
        "routes": failed,
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
    parser.add_argument("--base-routes", type=Path, required=True)
    parser.add_argument("--paddle-evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_hybrid_recovery_routes(
        base_routes=args.base_routes.resolve(),
        paddle_evidence_root=args.paddle_evidence_root.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_hybrid_recovery_routes"]
