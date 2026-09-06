from __future__ import annotations

import argparse
from pathlib import Path

from .evaluator import evaluate_suite, load_json, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a mixed-document quality candidate")
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    report = evaluate_suite(
        load_json(args.suite), load_json(args.candidate), repo_root=args.repo_root
    )
    write_report(args.output, report)
    print(f"{report['verdict']}: {report['passed_dimensions']}/{report['total_dimensions']}")
    return 0 if report["verdict"] == "qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
