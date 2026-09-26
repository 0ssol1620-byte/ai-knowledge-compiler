"""Run the pinned olmOCR-Bench rule engine and write machine-readable results.

``benchmark.py`` prints its scores to stdout and keeps the per-test outcomes in
memory. Masterplan section 12.1 wants the individual test pass/fail, so this
driver calls the checkout's own ``evaluate_candidate`` - the official scoring
function, unmodified - and serialises everything it returns. The metric names
and the aggregation (overall score = mean of per-jsonl pass rates) are the
evaluator's, not this campaign's.

It runs as a subprocess inside the checkout so it uses the evaluator's
dependencies. Every heavy import happens inside :func:`run`; importing this
module costs nothing.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

__all__ = ["build_parser", "main", "run"]

SCHEMA = "tavonel.arena.olmocr-official-result.v1"
_MODULE_NAMES = ("benchmark", "report", "tests", "utils")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluator-dir", type=Path, required=True)
    parser.add_argument("--bench-dir", type=Path, required=True)
    parser.add_argument("--candidate", type=str, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def _load_official_modules(evaluator_dir: Path) -> dict[str, Any]:
    """Import the checkout's modules without colliding with anything installed."""

    required = ["benchmark.py", "tests.py", "utils.py"]
    missing = [name for name in required if not (evaluator_dir / name).is_file()]
    if missing:
        raise SystemExit(f"olmOCR evaluator checkout is incomplete: {missing}")
    displaced = {name: sys.modules.pop(name, None) for name in _MODULE_NAMES}
    sys.path.insert(0, str(evaluator_dir))
    try:
        loaded = {
            "tests": importlib.import_module("tests"),
            "utils": importlib.import_module("utils"),
            "benchmark": importlib.import_module("benchmark"),
        }
    finally:
        sys.path.pop(0)
        for name in _MODULE_NAMES:
            sys.modules.pop(name, None)
            previous = displaced[name]
            if previous is not None:
                sys.modules[name] = previous
    return loaded


def run(*, evaluator_dir: Path, bench_dir: Path, candidate: str, out: Path) -> dict[str, Any]:
    from pypdf import PdfReader

    modules = _load_official_modules(evaluator_dir)
    evaluate_candidate = modules["benchmark"].evaluate_candidate
    load_tests = modules["tests"].load_tests
    baseline_test = modules["tests"].BaselineTest

    pdf_root = bench_dir / "pdfs"
    if not pdf_root.is_dir():
        raise SystemExit(f"no pdfs/ under {bench_dir}")
    pdf_files = sorted(pdf_root.rglob("*.pdf"))
    pdf_basenames = [path.relative_to(pdf_root).as_posix() for path in pdf_files]
    if not pdf_basenames:
        raise SystemExit(f"no PDFs under {pdf_root}")

    all_tests: list[Any] = []
    test_to_jsonl: dict[str, str] = {}
    jsonl_paths = sorted(bench_dir.glob("*.jsonl"))
    if not jsonl_paths:
        raise SystemExit(f"no rule .jsonl files under {bench_dir}")
    for jsonl_path in jsonl_paths:
        for test in load_tests(str(jsonl_path)):
            if test.id in test_to_jsonl:
                raise SystemExit(f"duplicate olmOCR test id: {test.id}")
            test_to_jsonl[test.id] = jsonl_path.name
            all_tests.append(test)

    for pdf_name, pdf_path in zip(pdf_basenames, pdf_files, strict=True):
        page_count = len(PdfReader(str(pdf_path)).pages)
        for page in range(1, page_count + 1):
            if not any(test.pdf == pdf_name and test.page == page for test in all_tests):
                raise SystemExit(f"olmOCR page has no official rule: {pdf_name}/page-{page}")
        if not any(test.type == "baseline" for test in all_tests if test.pdf == pdf_name):
            created = baseline_test(
                id=f"{pdf_name}_baseline", pdf=pdf_name, page=1, type="baseline"
            )
            all_tests.append(created)
            test_to_jsonl[created.id] = "baseline"

    (
        _raw_overall,
        total_tests,
        candidate_errors,
        _failure_messages,
        type_breakdown,
        _all_scores,
        test_results,
    ) = evaluate_candidate(str(bench_dir / candidate), all_tests, pdf_basenames, False)

    rows: list[dict[str, Any]] = []
    buckets: dict[str, dict[str, Any]] = {}
    for test in all_tests:
        source_jsonl = test_to_jsonl[test.id]
        bucket = buckets.setdefault(source_jsonl, {"total": 0, "passed": 0})
        bucket["total"] += 1
        outcomes = test_results.get(test.pdf, {}).get(test.page, [])
        matches = [
            (passed, explanation) for item, passed, explanation in outcomes if item.id == test.id
        ]
        if len(matches) != 1:
            raise SystemExit(f"missing unique official outcome for olmOCR test {test.id}")
        passed, explanation = matches[0]
        bucket["passed"] += int(bool(passed))
        rows.append(
            {
                "test_id": test.id,
                "pdf": test.pdf,
                "page": test.page,
                "type": test.type,
                "source_jsonl": source_jsonl,
                "passed": bool(passed),
                "explanation": explanation,
            }
        )

    per_jsonl = {
        name: {
            "total": int(values["total"]),
            "passed": int(values["passed"]),
            "pass_rate": (
                float(values["passed"]) / float(values["total"]) if values["total"] else None
            ),
        }
        for name, values in sorted(buckets.items())
    }
    rates = [entry["pass_rate"] for entry in per_jsonl.values() if entry["pass_rate"] is not None]
    payload = {
        "schema": SCHEMA,
        "candidate": candidate,
        "evaluator_dir": str(evaluator_dir),
        "bench_dir": str(bench_dir),
        "pdf_count": len(pdf_basenames),
        "test_count": int(total_tests),
        "candidate_errors": [str(error) for error in candidate_errors],
        "overall_score": (sum(rates) / len(rates)) if rates else None,
        "overall_score_definition": (
            "mean of the per-jsonl pass rates, as benchmark.py computes it"
        ),
        "per_jsonl": per_jsonl,
        "type_breakdown": {
            name: {
                "test_count": len(scores),
                "pass_rate": (sum(scores) / len(scores)) if scores else None,
            }
            for name, scores in sorted(type_breakdown.items())
        },
        "tests": sorted(rows, key=lambda row: str(row["test_id"])),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run(
        evaluator_dir=args.evaluator_dir.resolve(),
        bench_dir=args.bench_dir.resolve(),
        candidate=args.candidate,
        out=args.out.resolve(),
    )
    print(f"olmOCR official result written: {args.out} ({payload['test_count']} tests)")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
