"""Hidden, offline scoring of an already sealed Native capture.

Calls the pinned official rule objects directly, avoiding the upstream CLI's
POSIX-only file-name matching on Windows. Nothing here is imported by capture.
Failed Native executions count as failed rules, including absence rules.
This is spent development evidence, not model or production qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import platform
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--bench-data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    capture = args.capture.resolve(strict=True)
    output = args.output.resolve()
    scratch = (root / ".chatgpt2codex").resolve()
    if not output.is_relative_to(scratch) or output == scratch:
        raise ValueError("SCORING_OUTPUT_MUST_BE_NEW_WORKTREE_SCRATCH")
    freeze = json.loads((capture / "FREEZE.json").read_text(encoding="utf-8"))
    result = json.loads((capture / "RESULT.json").read_text(encoding="utf-8"))
    observations = capture / "observations.jsonl"
    if result["observations_sha256"] != digest(observations):
        raise ValueError("CAPTURE_HASH_MISMATCH")
    if freeze["confirmatory_eligible"] is not False or freeze["selected_units"] != 1403:
        raise ValueError("COMPLETE_SPENT_CAPTURE_REQUIRED")
    rows = [json.loads(line) for line in observations.read_text(encoding="utf-8").splitlines()]
    observed = {row["sample_id"]: row for row in rows}
    if len(observed) != len(rows) or len(rows) != 1403:
        raise ValueError("OBSERVATION_DENOMINATOR_INVALID")
    page_map = {}
    for source in freeze["selected_source_rows"]:
        row = observed[source["sample_id"]]
        if row["source_sha256"] != source["original_source_sha256"]:
            raise ValueError("OBSERVATION_SOURCE_MISMATCH")
        actual = "sha256:" + hashlib.sha256(row["text"].encode()).hexdigest()
        if actual != row["output_sha256"]:
            raise ValueError("OBSERVATION_TEXT_HASH_MISMATCH")
        pdf = str(PurePosixPath(source["original_source_relative_path"]).relative_to(
            PurePosixPath("bench_data/pdfs")
        ))
        key = (pdf, source["page_index"] + 1)
        if key in page_map:
            raise ValueError("AMBIGUOUS_SOURCE_PAGE")
        page_map[key] = row
    evaluator = args.evaluator.resolve(strict=True)
    bench = args.bench_data.resolve(strict=True)
    rules = sorted(bench.glob("*.jsonl"))
    if len(rules) != 7:
        raise ValueError("OFFICIAL_RULE_INVENTORY_CHANGED")
    code = {str(path.relative_to(evaluator)): digest(path) for path in evaluator.rglob("*")
            if path.is_file() and path.suffix in {".py", ".js", ".css"}}
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "FREEZE.json", {
        "confirmatory_eligible": False,
        "capture_sha256": digest(capture / "FREEZE.json"),
        "observations_sha256": digest(observations),
        "scoring_code_sha256": digest(Path(__file__)),
        "evaluator_files": code,
        "rules": {path.name: digest(path) for path in rules},
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "method": "Official load_tests and test.run, one Native observation per source page",
        "failed_execution_policy": "All rules fail; no missing page or rule is dropped",
        "quality_scope": "Declared Native text projection; not full document fidelity or SCLR",
    })
    sys.path.insert(0, str(evaluator))
    official = importlib.import_module("tests")
    if not Path(official.__file__).resolve().is_relative_to(evaluator):
        raise ValueError("WRONG_EVALUATOR_IMPORT")
    render = importlib.import_module("katex.render")
    render.equation_cache = render.EquationCache(str(output / "equations.sqlite"))
    tests = []
    source_jsonl = {}
    for rule in rules:
        for test in official.load_tests(str(rule)):
            if test.id in source_jsonl:
                raise ValueError("DUPLICATE_OFFICIAL_TEST_ID")
            source_jsonl[test.id] = rule.name
            tests.append(test)
    rule_pages = {(test.pdf, test.page) for test in tests}
    if rule_pages != set(page_map):
        raise ValueError("OFFICIAL_RULE_AND_CAPTURE_PAGES_DIFFER")
    for pdf in sorted({key[0] for key in page_map}):
        if not any(test.type == "baseline" and test.pdf == pdf for test in tests):
            test = official.BaselineTest(id=f"{pdf}_baseline", pdf=pdf, page=1, type="baseline")
            tests.append(test)
            source_jsonl[test.id] = "baseline"
    totals: dict[str, Counter] = defaultdict(Counter)
    error_count = 0
    with (output / "rule-results.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for index, test in enumerate(tests):
            row = page_map[(test.pdf, test.page)]
            error = None
            if row["status"] not in {"native_text_observed", "native_text_unobserved"}:
                passed, explanation = False, "Native execution failed or was refused"
            else:
                try:
                    passed, explanation = test.run(row["text"])
                except Exception as exc:
                    passed, explanation = False, "Official evaluator could not execute this rule"
                    error = type(exc).__name__
                    error_count += 1
            bucket = source_jsonl[test.id]
            totals[bucket]["total"] += 1
            totals[bucket]["passed"] += int(bool(passed))
            handle.write(json.dumps({
                "test_id": test.id, "pdf": test.pdf, "page": test.page,
                "type": test.type, "source_jsonl": bucket, "passed": bool(passed),
                "explanation": explanation, "evaluator_error": error,
            }, ensure_ascii=False) + "\n")
            if index % 250 == 0:
                handle.flush()
                print(json.dumps({"evaluated": index + 1, "total": len(tests)}), flush=True)
    buckets = {key: {**value, "pass_rate": value["passed"] / value["total"]}
               for key, value in sorted(totals.items())}
    write_json(output / "RESULT.json", {
        "confirmatory_eligible": False, "production_qualified": False,
        "status": "EVALUATOR_INCOMPLETE" if error_count else "DEVELOPMENT_SCORED",
        "units": len(rows), "tests": len(tests), "evaluator_errors": error_count,
        "native_statuses": Counter(row["status"] for row in rows),
        "overall_score": sum(item["pass_rate"] for item in buckets.values()) / len(buckets),
        "overall_score_definition": "Mean per-jsonl pass rate including official baseline bucket",
        "per_jsonl": buckets,
        "rule_results_sha256": digest(output / "rule-results.jsonl"),
        "cost_usd": None, "production_latency": None, "SCLR": None,
    })
    if error_count:
        raise SystemExit("Evaluator errors retained; do not interpret as qualified quality score")
    print("Native development rule scoring completed", flush=True)


if __name__ == "__main__":
    main()
