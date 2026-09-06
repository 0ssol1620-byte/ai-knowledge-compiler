#!/usr/bin/env python3
"""Correct the attribution in the 2026-08-18 stale diagnosis, without rewriting it.

`receipts/structure-only-stale-diagnosis-2026-08-18.json` states
`reproduces_confirmatory_defect: true` and names the structural channel as the
root cause of the confirmatory corpus's `stale_left_behind = 2`. Opening the
failing pair shows that is wrong: its block count did not move, no artifact in
that graph depends on heading structure, and the two carried-over artifacts
belong to a unit that exists only in the *after* revision.

The structural defect it demonstrates is real, and its synthetic reproduction
stands. What is wrong is the causal claim about the real corpus.

The earlier receipt is **not** edited. It is a record of what was believed on the
day it was written, and rewriting it would erase the fact that the belief was
held and acted on. This writes a superseding record beside it, which is the same
treatment a retracted result gets anywhere else in this repository.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
R = ROOT / "research" / "experiments" / "H1-B-REAL-REVISION-01" / "receipts"
SUPERSEDED = R / "structure-only-stale-diagnosis-2026-08-18.json"
BENCHMARK = R / "recompilation-fix-benchmark-2026-08-19.json"
OUTPUT = R / "stale-attribution-correction-2026-08-19.json"


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    for path in (SUPERSEDED, BENCHMARK):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    bench = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    arms = bench["corpora"]["confirmatory-v1"]["arms"]

    receipt = {
        "schema": "tavonel.family-b-stale-attribution-correction.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "supersedes": {
            "receipt": SUPERSEDED.name,
            "sha256": sha256_of(SUPERSEDED),
            "claim_being_corrected": (
                "reproduces_confirmatory_defect: true -- that the structural "
                "channel is the root cause of stale_left_behind = 2 on the "
                "confirmatory corpus"
            ),
        },
        "what_still_stands": (
            "the structural defect itself. A structure-only change carries no "
            "logical_id, cannot seed the traversal, and lets an artifact "
            "aggregated over document position be carried over stale. The "
            "synthetic reproduction demonstrates it and remains valid."
        ),
        "what_was_wrong": (
            "the causal attribution to the real corpus. On the failing pair the "
            "block count did not move, the only structural change was the "
            "heading tree, and no artifact in that adapter's graph depends on "
            "heading structure."
        ),
        "evidence_from_the_failing_pair": {
            "title": "Self-driving car",
            "block_count_before_after": [69, 69],
            "structural_change_present": "heading tree only",
            "shared_units_whose_text_changed": 0,
            "units_only_in_before": 1,
            "units_only_in_after": 1,
            "artifacts_whose_bytes_differ": 5,
            "artifacts_total": 75,
        },
        "actual_root_cause": (
            "diff_documents records an AMBIGUOUS identity decision with "
            "logical_id=None and the prior candidates, then returns -- so the "
            "incoming unit appears in no change at all, not even as UNIT_ADDED. "
            "plan_recompilation seeds its unresolved traversal from the "
            "candidates alone, so anything derived from the incoming unit is "
            "reached by nothing, is labelled CURRENT, and is carried over stale."
        ),
        "why_the_wrong_fix_looked_right": (
            "seeding every unit of the document on a structural change rebuilds "
            "enough to cover the missed artifact. The corpus went equivalent, "
            "the stale count went to zero, and the acceptance criteria passed -- "
            "while the defect that caused the failure was untouched. Measured "
            "apart, the structural channel rebuilds 87 of 334 artifacts against "
            "the identity fix's 20, for the same correctness."
        ),
        "measured_attribution": {
            arm: {
                "all_equivalent": summary["all_equivalent"],
                "stale_left_behind_total": summary["stale_left_behind_total"],
                "total_rebuilt": summary["total_rebuilt"],
                "total_artifacts": summary["total_artifacts"],
            }
            for arm, summary in arms.items()
        },
        "benchmark_receipt": {
            "receipt": BENCHMARK.name,
            "sha256": sha256_of(BENCHMARK),
        },
        "lesson_recorded_rather_than_absorbed": (
            "an acceptance suite that only asks 'did the failure go away' cannot "
            "tell a fix from a mask. The four-arm design exists because the "
            "single-arm result was green and wrong."
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    OUTPUT.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"superseded : {SUPERSEDED.name}")
    print(f"correction : {OUTPUT}")
    for arm, summary in receipt["measured_attribution"].items():
        print(
            f"  {arm:26} equivalent={summary['all_equivalent']!s:5} "
            f"stale={summary['stale_left_behind_total']} "
            f"rebuilt={summary['total_rebuilt']}/{summary['total_artifacts']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
