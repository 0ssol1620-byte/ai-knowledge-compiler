#!/usr/bin/env python3
"""Run the frozen official olmOCR-Bench rule engine with structured evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
from pypdf import PdfReader


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
    if len(revision) != 40:
        raise ValueError("olmOCR-Bench evaluator revision is not immutable")
    return revision


def _worktree_provenance(evaluator_dir: Path) -> dict[str, Any]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to capture evaluator provenance")
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
        "evaluator_portability_patch": (
            "candidate relative paths normalized to POSIX separators on Windows"
        ),
    }


def _load_official_modules(
    evaluator_dir: Path,
) -> tuple[ModuleType, ModuleType, ModuleType, ModuleType]:
    """Load the frozen checkout without colliding with this repo's benchmark package."""

    required = ["benchmark.py", "report.py", "tests.py", "utils.py"]
    missing = [name for name in required if not (evaluator_dir / name).is_file()]
    if missing:
        raise ValueError(f"olmOCR evaluator checkout is incomplete: {missing}")

    names = ("benchmark", "report", "tests", "utils")
    displaced = {name: sys.modules.pop(name, None) for name in names}
    sys.path.insert(0, str(evaluator_dir))
    try:
        tests_module = importlib.import_module("tests")
        report_module = importlib.import_module("report")
        utils_module = importlib.import_module("utils")
        benchmark_module = importlib.import_module("benchmark")
    finally:
        sys.path.pop(0)
        for name in names:
            sys.modules.pop(name, None)
            if displaced[name] is not None:
                sys.modules[name] = displaced[name]
    return benchmark_module, report_module, tests_module, utils_module


def _case_lookup(source_manifest: Path) -> dict[str, str]:
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    if manifest.get("schema") == "folynta.public-core-source-manifest.v1":
        cases = manifest.get("sources", [])
        expected_count = int(manifest.get("source_count", -1))
    else:
        cases = manifest.get("inputs", [])
        expected_count = int(manifest.get("input_count", -1))
    result: dict[str, str] = {}
    for case in cases:
        source = Path(str(case["source_relative_path"]))
        relative = source.relative_to("bench_data/pdfs").as_posix()
        if relative in result:
            raise ValueError(f"duplicate olmOCR PDF in source manifest: {relative}")
        result[relative] = str(case["case_id"])
    if len(result) != expected_count:
        raise ValueError("olmOCR source manifest coverage is invalid")
    return result


def evaluate_olmocr(
    *,
    evaluator_dir: Path,
    dataset_root: Path,
    candidate_dir: Path,
    source_manifest: Path,
    output_root: Path,
    bootstrap_samples: int,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=False)
    revision = _revision(evaluator_dir)
    worktree_provenance = _worktree_provenance(evaluator_dir)
    benchmark_module, report_module, tests_module, utils_module = (
        _load_official_modules(evaluator_dir)
    )
    evaluate_candidate = benchmark_module.evaluate_candidate
    generate_html_report = report_module.generate_html_report
    BaselineTest = tests_module.BaselineTest
    load_tests = tests_module.load_tests
    calculate_bootstrap_ci = utils_module.calculate_bootstrap_ci
    lookup = _case_lookup(source_manifest)
    bench_data_root = (
        dataset_root / "bench_data"
        if (dataset_root / "bench_data").is_dir()
        else dataset_root
    )
    pdf_root = bench_data_root / "pdfs"
    pdf_files = sorted(pdf_root.rglob("*.pdf"))
    pdf_basenames = [path.relative_to(pdf_root).as_posix() for path in pdf_files]
    if set(pdf_basenames) != set(lookup):
        raise ValueError("olmOCR evaluator PDFs differ from the frozen source manifest")

    all_tests = []
    test_to_jsonl: dict[str, str] = {}
    jsonl_paths = sorted(bench_data_root.glob("*.jsonl"))
    if not jsonl_paths:
        raise ValueError("olmOCR evaluator JSONL rules are missing")
    for jsonl_path in jsonl_paths:
        for test in load_tests(str(jsonl_path)):
            if test.id in test_to_jsonl:
                raise ValueError(f"duplicate olmOCR test id: {test.id}")
            test_to_jsonl[test.id] = jsonl_path.name
            all_tests.append(test)

    for pdf_name, pdf_path in zip(pdf_basenames, pdf_files, strict=True):
        page_count = len(PdfReader(str(pdf_path)).pages)
        for page in range(1, page_count + 1):
            matching = [test for test in all_tests if test.pdf == pdf_name and test.page == page]
            if not matching:
                raise ValueError(f"olmOCR page has no official rule: {pdf_name}/page-{page}")
        if not any(test.type == "baseline" for test in all_tests if test.pdf == pdf_name):
            baseline = BaselineTest(
                id=f"{pdf_name}_baseline",
                pdf=pdf_name,
                page=1,
                type="baseline",
            )
            all_tests.append(baseline)
            test_to_jsonl[baseline.id] = "baseline"

    (
        _raw_overall_score,
        total_tests,
        candidate_errors,
        _test_failure_messages,
        type_breakdown,
        _all_test_scores,
        test_results,
    ) = evaluate_candidate(
        str(candidate_dir),
        all_tests,
        pdf_basenames,
        force=False,
    )
    if candidate_errors:
        raise ValueError(f"olmOCR candidate validation failed: {candidate_errors[:5]}")

    jsonl_results: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    observed_test_ids: set[str] = set()
    for test in all_tests:
        jsonl_name = test_to_jsonl[test.id]
        bucket = jsonl_results.setdefault(
            jsonl_name,
            {"total": 0, "passed": 0, "scores": []},
        )
        bucket["total"] += 1
        outcomes = test_results.get(test.pdf, {}).get(test.page, [])
        matches = [
            (passed, explanation)
            for item, passed, explanation in outcomes
            if item.id == test.id
        ]
        if len(matches) != 1:
            raise ValueError(f"missing unique official outcome for olmOCR test {test.id}")
        passed, explanation = matches[0]
        observed_test_ids.add(test.id)
        score = 1.0 if passed else 0.0
        bucket["scores"].append(score)
        bucket["passed"] += int(passed)
        if not passed:
            failures.append(
                {
                    "case_id": lookup[test.pdf],
                    "test_id": test.id,
                    "evaluator_type": test.type,
                    "location_id": test.id,
                    "pdf": test.pdf,
                    "page": test.page,
                    "score": 0.0,
                    "explanation": explanation,
                    "official_rule": asdict(test),
                    "source_jsonl": jsonl_name,
                }
            )
    if len(observed_test_ids) != len(all_tests) or total_tests != len(all_tests):
        raise ValueError("olmOCR official test coverage is incomplete")

    per_jsonl: dict[str, dict[str, float | int]] = {}
    flat_scores: list[float] = []
    split_sizes: list[int] = []
    for name, bucket in sorted(jsonl_results.items()):
        total = int(bucket["total"])
        passed = int(bucket["passed"])
        scores = [float(value) for value in bucket["scores"]]
        if len(scores) != total:
            raise ValueError(f"olmOCR score coverage is incomplete for {name}")
        per_jsonl[name] = {
            "total": total,
            "passed": passed,
            "pass_rate": passed / total if total else 0.0,
        }
        flat_scores.extend(scores)
        split_sizes.append(len(scores))
    overall_score = sum(
        float(bucket["pass_rate"]) for bucket in per_jsonl.values()
    ) / len(per_jsonl)
    np.random.seed(20260804)
    confidence_interval = calculate_bootstrap_ci(
        flat_scores,
        n_bootstrap=bootstrap_samples,
        ci_level=0.95,
        splits=split_sizes,
    )

    failures_payload = {
        "schema": "folynta.olmocr-official-rule-failures.v1",
        "evaluator_revision": revision,
        **worktree_provenance,
        "failure_count": len(failures),
        "failures": sorted(failures, key=lambda item: str(item["test_id"])),
    }
    failures_path = output_root / "official-rule-failures.json"
    failures_path.write_bytes(_canonical_json(failures_payload))
    html_path = output_root / "detailed-report.html"
    generate_html_report(
        {candidate_dir.name: test_results},
        str(pdf_root),
        str(html_path),
    )
    summary = {
        "schema": "folynta.olmocr-official-evaluation.v1",
        "evaluator_revision": revision,
        **worktree_provenance,
        "source_manifest_sha256": _sha256_file(source_manifest),
        "input_count": len(lookup),
        "test_count": len(all_tests),
        "overall_score": overall_score,
        "confidence_interval_95": [
            float(confidence_interval[0]),
            float(confidence_interval[1]),
        ],
        "bootstrap_samples": bootstrap_samples,
        "per_jsonl": per_jsonl,
        "type_breakdown": {
            name: {
                "test_count": len(scores),
                "pass_rate": sum(scores) / len(scores) if scores else 0.0,
            }
            for name, scores in sorted(type_breakdown.items())
        },
        "rule_failure_count": len(failures),
        "failure_evidence_sha256": _sha256_file(failures_path),
        "html_report_sha256": _sha256_file(html_path),
    }
    summary_path = output_root / "evaluation-summary.json"
    summary_path.write_bytes(_canonical_json(summary))
    return {**summary, "summary_sha256": _sha256_file(summary_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluator-dir", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = evaluate_olmocr(
        evaluator_dir=args.evaluator_dir.resolve(),
        dataset_root=args.dataset_root.resolve(),
        candidate_dir=args.candidate_dir.resolve(),
        source_manifest=args.source_manifest.resolve(),
        output_root=args.output_root.resolve(),
        bootstrap_samples=args.bootstrap_samples,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["evaluate_olmocr"]
