"""Run and persist the frozen FOLYNTA system-algorithm evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (
    ROOT,
    ROOT / "packages/cir-python/src",
    ROOT / "packages/router/src",
    ROOT / "packages/quality/src",
    ROOT / "packages/parallel-runtime/src",
)
for source_root in reversed(SOURCE_ROOTS):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))


def main() -> None:
    from benchmark.evaluators.system_algorithms import write_report

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = write_report(args.output)
    summary = {
        "gate": report["gate"],
        "corpus_type": report["corpus_type"],
        "metrics": {
            key: {
                metric: value
                for metric, value in payload.items()
                if metric
                in {
                    "fixtures",
                    "accuracy",
                    "precision",
                    "recall",
                    "f1",
                    "selection_accuracy",
                    "decision_accuracy",
                    "duplicate_attempts",
                    "duplicate_charge_credits",
                    "conservation_invariant",
                }
            }
            for key, payload in report["metrics"].items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
