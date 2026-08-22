#!/usr/bin/env python3
"""Write the deterministic semantic/infrastructure worker-fault evidence receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "packages" / "parallel-runtime" / "src"))


def main() -> int:
    from benchmark.v6.worker_fault_campaign import evaluate_worker_fault_campaign

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = evaluate_worker_fault_campaign()
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": f"sha256:{digest}",
                "gate_passed": report["aggregate"]["gate_passed"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
