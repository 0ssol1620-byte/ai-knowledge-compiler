#!/usr/bin/env python3
"""Run the frozen official ParseBench evaluator and export rule failures.

This script must be executed with the frozen ParseBench checkout on
``PYTHONPATH``. It never modifies prediction files and binds every report to
the evaluator Git revision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from parse_bench.evaluation.cli import EvaluationCLI
from parse_bench.test_cases.loader import load_test_cases

GROUPS: tuple[tuple[str, str], ...] = (
    ("chart", "parse"),
    ("layout", "layout_detection"),
    ("table", "parse"),
    ("text_content", "parse"),
    ("text_formatting", "parse"),
)


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _revision(evaluator_dir: Path) -> str:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git executable is required to pin the evaluator revision")
    result = subprocess.run(
        [git, "rev-parse", "HEAD"],
        cwd=evaluator_dir,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    revision = result.stdout.strip()
    if not revision or len(revision) != 40:
        raise ValueError("ParseBench evaluator revision is not immutable")
    return revision


def _worktree_provenance(evaluator_dir: Path) -> dict[str, Any]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git executable is required to capture evaluator provenance")
    status = subprocess.run(
        [git, "status", "--porcelain", "--untracked-files=no"],
        cwd=evaluator_dir,
        check=True,
        capture_output=True,
    ).stdout
    diff = subprocess.run(
        [git, "diff", "--binary", "HEAD", "--"],
        cwd=evaluator_dir,
        check=True,
        capture_output=True,
    ).stdout
    return {
        "evaluator_worktree_clean": not bool(status.strip()),
        "evaluator_tracked_patch_sha256": (
            None if not diff else f"sha256:{hashlib.sha256(diff).hexdigest()}"
        ),
        "evaluator_watchdog_policy": (
            "punctuation-only formatting queries are recorded as conservative "
            "evaluator failures"
        ),
    }


def _manifest_case_lookup(manifest_path: Path) -> dict[str, str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") == "folynta.public-core-source-manifest.v1":
        cases = manifest.get("sources", [])
        expected_count = int(manifest.get("source_count", -1))
    else:
        cases = manifest.get("inputs", [])
        expected_count = int(manifest.get("input_count", -1))
    result: dict[str, str] = {}
    for case in cases:
        source = Path(str(case["source_relative_path"]))
        category = source.parent.name
        inference_group = "text" if category == "text" else category
        test_id = f"{inference_group}/{source.stem}"
        if test_id in result:
            raise ValueError(f"duplicate ParseBench test id in source manifest: {test_id}")
        result[test_id] = str(case["case_id"])
    if len(result) != expected_count:
        raise ValueError("ParseBench source manifest coverage is invalid")
    return result


def _failure_location(rule: dict[str, Any], index: int) -> str:
    for key in ("id", "layout_id"):
        value = rule.get(key)
        if isinstance(value, str) and value:
            return value
    element_index = rule.get("element_index")
    if isinstance(element_index, int):
        return f"element-{element_index}"
    return f"rule-{index}"


def _rule_failures(
    *,
    report: dict[str, Any],
    group: str,
    case_lookup: dict[str, str],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    metric_names = (
        ("layout_element_rule_pass_rate", "rule_pass_rate")
        if group == "layout"
        else ("rule_pass_rate",)
    )
    for result in report.get("per_example_results", []):
        test_id = str(result.get("test_id", ""))
        case_id = case_lookup.get(test_id)
        if case_id is None:
            raise ValueError(f"official ParseBench result has unknown test id: {test_id}")
        if result.get("success") is not True:
            failures.append(
                {
                    "case_id": case_id,
                    "test_id": test_id,
                    "evaluator_type": "evaluator_error",
                    "location_id": "evaluation",
                    "score": 0.0,
                    "explanation": str(result.get("error") or "evaluation failed"),
                    "group": group,
                }
            )
            continue
        metric = None
        for metric_name in metric_names:
            matches = [
                item
                for item in result.get("metrics", [])
                if item.get("metric_name") == metric_name
            ]
            if len(matches) == 1:
                metric = matches[0]
                break
        if metric is None:
            failures.append(
                {
                    "case_id": case_id,
                    "test_id": test_id,
                    "evaluator_type": "evaluator_error",
                    "location_id": "evaluation",
                    "score": 0.0,
                    "explanation": "official rule metric is missing",
                    "group": group,
                }
            )
            continue
        rules = metric.get("metadata", {}).get("rule_results", [])
        if not isinstance(rules, list):
            raise ValueError(f"invalid official rule results for {test_id}")
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict) or rule.get("passed") is True:
                continue
            failures.append(
                {
                    "case_id": case_id,
                    "test_id": test_id,
                    "evaluator_type": "layout" if group == "layout" else str(rule.get("type")),
                    "location_id": _failure_location(rule, index),
                    "score": float(rule.get("score", 0.0)),
                    "explanation": str(
                        rule.get("explanation")
                        or rule.get("localization_reason")
                        or "official rule failed"
                    ),
                    "group": group,
                    "official_rule": rule,
                }
            )
    return failures


def evaluate_parsebench(
    *,
    evaluator_dir: Path,
    predictions_root: Path,
    dataset_root: Path,
    source_manifest: Path,
    output_root: Path,
    max_workers: int,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    revision = _revision(evaluator_dir)
    worktree_provenance = _worktree_provenance(evaluator_dir)
    case_lookup = _manifest_case_lookup(source_manifest)
    all_cases = load_test_cases(root_dir=dataset_root, require_test_json=False)
    expected_by_group: dict[str, int] = {}
    for test_case in all_cases:
        expected_by_group[test_case.group] = expected_by_group.get(test_case.group, 0) + 1

    records: list[dict[str, Any]] = []
    all_failures: list[dict[str, Any]] = []
    for group, product_type in GROUPS:
        report_dir = output_root / group
        report_path = report_dir / "_evaluation_report.json"
        if not report_path.is_file():
            exit_code = EvaluationCLI().run(
                output_dir=predictions_root,
                test_cases_dir=dataset_root,
                product_type=product_type,
                group=group,
                report_dir=report_dir,
                export_csv=True,
                export_rule_csv=False,
                export_markdown=True,
                export_html=True,
                verbose=False,
                force=True,
                multi_task=True,
                max_workers=max_workers,
                enable_teds=True,
                skip_rules=False,
                ontology="canonical",
                verified_only=False,
            )
            if exit_code != 0:
                raise RuntimeError(
                    f"official ParseBench evaluation failed for {group}: {exit_code}"
                )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        expected = expected_by_group.get(group, 0)
        if int(report.get("total_examples", -1)) != expected:
            raise ValueError(
                f"ParseBench group coverage mismatch for {group}: "
                f"expected {expected}, received {report.get('total_examples')}"
            )
        failures = _rule_failures(
            report=report,
            group=group,
            case_lookup=case_lookup,
        )
        all_failures.extend(failures)
        records.append(
            {
                "group": group,
                "product_type": product_type,
                "example_count": expected,
                "successful": int(report.get("successful", 0)),
                "failed": int(report.get("failed", 0)),
                "rule_failure_count": len(failures),
                "aggregate_metrics": report.get("aggregate_metrics", {}),
                "report_sha256": _sha256_file(report_path),
            }
        )

    failures_path = output_root / "official-rule-failures.json"
    failures_payload = {
        "schema": "folynta.parsebench-official-rule-failures.v1",
        "evaluator_revision": revision,
        **worktree_provenance,
        "failure_count": len(all_failures),
        "failures": sorted(
            all_failures,
            key=lambda item: (
                str(item["case_id"]),
                str(item["evaluator_type"]),
                str(item["location_id"]),
            ),
        ),
    }
    failures_path.write_bytes(_canonical_json(failures_payload))
    summary = {
        "schema": "folynta.parsebench-official-evaluation.v1",
        "evaluator_revision": revision,
        **worktree_provenance,
        "source_manifest_sha256": _sha256_file(source_manifest),
        "unique_input_count": len(case_lookup),
        "evaluated_example_count": sum(record["example_count"] for record in records),
        "rule_failure_count": len(all_failures),
        "failure_evidence_sha256": _sha256_file(failures_path),
        "groups": records,
    }
    summary_path = output_root / "evaluation-summary.json"
    summary_path.write_bytes(_canonical_json(summary))
    return {**summary, "summary_sha256": _sha256_file(summary_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluator-dir", type=Path, required=True)
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = evaluate_parsebench(
        evaluator_dir=args.evaluator_dir.resolve(),
        predictions_root=args.predictions_root.resolve(),
        dataset_root=args.dataset_root.resolve(),
        source_manifest=args.source_manifest.resolve(),
        output_root=args.output_root.resolve(),
        max_workers=args.max_workers,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["evaluate_parsebench"]
