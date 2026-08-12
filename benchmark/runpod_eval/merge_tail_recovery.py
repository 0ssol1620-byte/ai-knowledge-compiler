#!/usr/bin/env python3
"""Fold a rerouted tail run back into the worker collection it belongs to.

A worker whose suite hits its wall clock stops with documents it never
attempted. Those are not documents the pipeline cannot process; the same model
on another worker finished all three of them in minutes. But the collected
run-summary records them as failed, and the candidate overlay reads that summary
rather than the directory, so the recovered output would be invisible.

This merges the two, and it is deliberately hard to misuse. It refuses to accept
a case the original run did not record as failed, refuses a tail case that did
not itself complete, refuses to write over an existing collection, and writes a
receipt naming both sources and their hashes. Editing the summary by hand would
have taken two minutes and left no way to tell afterwards what had been changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _cases(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return summary["runs"][0]["cases"]


def plan_merge(
    collected_summary: dict[str, Any], tail_summary: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Decide which tail cases may replace which collected cases.

    Returns the accepted replacements and the ordered case ids, or raises. The
    check that matters is the first one: a tail run may only supply documents
    the collected run actually lost.
    """
    collected = {str(case["case_id"]): case for case in _cases(collected_summary)}
    failed = {case_id for case_id, case in collected.items() if case.get("status") != "completed"}

    replacements: dict[str, dict[str, Any]] = {}
    for case in _cases(tail_summary):
        case_id = str(case["case_id"])
        if case_id not in collected:
            raise ValueError(f"{case_id} is not part of the collected run at all")
        if case_id not in failed:
            raise ValueError(
                f"{case_id} already completed in the collected run; a tail run may only "
                "supply documents that were lost"
            )
        if case.get("status") != "completed":
            raise ValueError(f"{case_id} did not complete in the tail run either")
        replacements[case_id] = case

    if not replacements:
        raise ValueError("the tail run supplies nothing the collected run lost")
    still_missing = sorted(failed - set(replacements))
    return replacements, still_missing


def merge(
    collected_suite: Path,
    tail_root: Path,
    output_suite: Path,
    *,
    reason: str,
) -> dict[str, Any]:
    if output_suite.exists():
        raise FileExistsError(f"merge target already exists: {output_suite}")

    collected_summary_path = collected_suite / "run-summary.json"
    tail_summary_path = tail_root / "run-summary.json"
    collected_summary = _load(collected_summary_path)
    tail_summary = _load(tail_summary_path)

    replacements, still_missing = plan_merge(collected_summary, tail_summary)

    shutil.copytree(collected_suite, output_suite)

    copied: list[str] = []
    for case_id in sorted(replacements):
        source_markdown = tail_root / "markdown-repeat-1" / f"{case_id}.md"
        if not source_markdown.is_file():
            raise FileNotFoundError(f"tail run has no markdown for {case_id}")
        target_markdown = output_suite / "markdown-repeat-1" / f"{case_id}.md"
        target_markdown.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_markdown, target_markdown)
        copied.append(case_id)

        source_case = tail_root / "repeat-1" / case_id
        if source_case.is_dir():
            target_case = output_suite / "repeat-1" / case_id
            if target_case.exists():
                shutil.rmtree(target_case)
            shutil.copytree(source_case, target_case)

    merged_summary = json.loads(json.dumps(collected_summary))
    run = merged_summary["runs"][0]
    run["cases"] = [
        replacements.get(str(case["case_id"]), case) for case in run["cases"]
    ]
    run["completed"] = sum(1 for case in run["cases"] if case.get("status") == "completed")
    run["failed"] = len(run["cases"]) - run["completed"]
    # The original numbers stay readable rather than being overwritten silently.
    run["merged_from_tail_recovery"] = {
        "case_ids": copied,
        "completed_before": collected_summary["runs"][0]["completed"],
        "failed_before": collected_summary["runs"][0]["failed"],
        "reason": reason,
    }
    (output_suite / "run-summary.json").write_text(
        json.dumps(merged_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    receipt = {
        "schema": "folynta.tail-recovery-merge.v1",
        "reason": reason,
        "collected_suite": collected_suite.as_posix(),
        "collected_run_summary_sha256": _sha256(collected_summary_path),
        "tail_root": tail_root.as_posix(),
        "tail_run_summary_sha256": _sha256(tail_summary_path),
        "cases_merged": copied,
        "cases_still_missing": still_missing,
        "completed_before": collected_summary["runs"][0]["completed"],
        "completed_after": run["completed"],
        "failed_before": collected_summary["runs"][0]["failed"],
        "failed_after": run["failed"],
        "merged_run_summary_sha256": _sha256(output_suite / "run-summary.json"),
    }
    (output_suite / "tail-recovery-merge-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collected-suite", required=True, type=Path)
    parser.add_argument("--tail-root", required=True, type=Path)
    parser.add_argument("--output-suite", required=True, type=Path)
    parser.add_argument("--reason", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = merge(
        args.collected_suite, args.tail_root, args.output_suite, reason=args.reason
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
