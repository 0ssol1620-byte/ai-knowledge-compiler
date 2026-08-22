#!/usr/bin/env python3
"""Capture official OmniDocBench artifacts left behind by a completed evaluator run.

The 2026-08-07T03:22+09:00 OmniDocBench run finished the official evaluator and
its ``metric-result.json`` was already copied into the repeat directory, but the
capture step never ran: the downstream page-count gate used ``Path.is_file``,
which reports ``False`` for the 17 CJK prediction pages whose absolute paths
exceed the Windows MAX_PATH limit of 260 characters. The evaluator output itself
is intact, so this script copies those frozen artifacts into the repeat
directory exactly as the evaluator lane would have, and records where each one
came from. It refuses to run unless the already-copied metric result is
byte-identical to the evaluator's own copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

REQUIRED_ARTIFACTS = (
    "metric_result.json",
    "text_block_per_page_edit.json",
    "display_formula_per_page_edit.json",
    "table_per_page_edit.json",
    "reading_order_per_page_edit.json",
    "table_per_table_TEDS.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def capture(
    *,
    evaluator_dir: Path,
    repeat_dir: Path,
    repeat_name: str,
    receipt_path: Path,
) -> dict[str, object]:
    prefix = f"{repeat_name}_quick_match"
    result_dir = evaluator_dir / "result"
    source_metric = result_dir / f"{prefix}_metric_result.json"
    if not source_metric.is_file():
        raise FileNotFoundError(f"evaluator metric result is missing: {source_metric}")

    frozen_metric = repeat_dir / "metric-result.json"
    if not frozen_metric.is_file():
        raise FileNotFoundError(f"repeat metric result is missing: {frozen_metric}")
    metric_sha = sha256_file(source_metric)
    if sha256_file(frozen_metric) != metric_sha:
        raise ValueError(
            "frozen metric-result.json does not match the evaluator result; "
            "the evaluator must be re-run instead of captured"
        )

    artifact_dir = repeat_dir / "official-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    captured: list[dict[str, object]] = []
    for source in sorted(result_dir.glob(f"{prefix}_*")):
        if not source.is_file():
            continue
        name = source.name.removeprefix(f"{prefix}_")
        destination = artifact_dir / name
        shutil.copy2(source, destination)
        captured.append(
            {
                "artifact": name,
                "source_path": str(source),
                "sha256": sha256_file(destination),
                "bytes": destination.stat().st_size,
            }
        )

    captured_names = {str(item["artifact"]) for item in captured}
    missing = [name for name in REQUIRED_ARTIFACTS if name not in captured_names]
    if missing:
        raise FileNotFoundError(
            "evaluator result directory is missing required artifacts: "
            + ", ".join(missing)
        )

    receipt = {
        "schema": "folynta.omnidocbench-frozen-artifact-capture.v1",
        "status": "captured_from_completed_official_evaluator_run",
        "repeat_name": repeat_name,
        "evaluator_result_dir": str(result_dir),
        "repeat_dir": str(repeat_dir),
        "metric_result_sha256": metric_sha,
        "artifact_count": len(captured),
        "artifacts": captured,
        "reason": (
            "The official evaluator completed and wrote every artifact, but the "
            "lane aborted in require_exact_page_count, which counted frozen "
            "prediction pages with Path.is_file. Windows reports WinError 3 for "
            "the 17 prediction paths longer than MAX_PATH (260 characters), so "
            "the gate saw 1634 of 1651 real pages. No metric was recomputed, "
            "re-scored, or synthesised here."
        ),
        "score_inflation_allowed": False,
        "metrics_recomputed": False,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluator-dir", required=True, type=Path)
    parser.add_argument("--repeat-dir", required=True, type=Path)
    parser.add_argument("--repeat-name", default="markdown-repeat-1")
    parser.add_argument("--receipt", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = capture(
        evaluator_dir=args.evaluator_dir.resolve(),
        repeat_dir=args.repeat_dir.resolve(),
        repeat_name=args.repeat_name,
        receipt_path=args.receipt.resolve(),
    )
    print(json.dumps({k: v for k, v in receipt.items() if k != "artifacts"}, indent=2))
    print(f"captured {receipt['artifact_count']} artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
