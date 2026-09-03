#!/usr/bin/env python3
"""CI gate: the promotion contract must hold, and must still be able to fail.

Two jobs, and the second is the one that matters. Checking that the gate passes
good runs is cheap and nearly uninformative -- a gate hardwired to `True` passes
that. So this also replays known-bad states and requires a refusal for each.

The ordering asserted here is the contract:

    changes accounted -> recompile complete -> integrity -> no stale CURRENT
    -> promotable

Exit 1 on any violation. A green run means the invariant is enforced, not that
nothing was checked.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SWEEP = ROOT / "research/experiments/H1-B-REAL-REVISION-01/scripts/change_space_sweep.py"
CASES_PER_CLASS = 60


def main() -> int:
    failures: list[str] = []

    # 1. The unit contract, including the refusal cases.
    unit = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "tests/unit/test_promotion_gate.py", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if unit.returncode != 0:
        failures.append("promotion gate unit contract failed:\n" + unit.stdout[-2000:])

    # 2. The behavioural contract over the change space. A smaller sweep than the
    #    recorded one -- this is a gate, not the experiment -- but the property
    #    it asserts is the same and does not weaken with fewer cases.
    out = ROOT / "tools/ci/.promotion-gate-sweep.json"
    sweep = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(SWEEP),
            "--cases-per-class",
            str(CASES_PER_CLASS),
            "--output",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if sweep.returncode != 0:
        failures.append("change-space sweep did not run:\n" + sweep.stderr[-2000:])
    else:
        report = json.loads(out.read_text(encoding="utf-8"))
        for arm, block in report["arms"].items():
            permitted = block["total_gate_missed_an_escape"]
            if permitted:
                failures.append(
                    f"arm {arm}: the gate permitted {permitted} promotion(s) that left a "
                    "stale artifact CURRENT. This is the fail-open defect the gate exists "
                    "to prevent"
                )
        # The default arm must still *produce* escapes, or the sweep has stopped
        # exercising the defect and a pass here would mean nothing.
        if report["arms"]["default"]["total_stale_escaped"] == 0:
            failures.append(
                "the default arm produced no stale artifacts at all. The gate cannot be "
                "credited with blocking them; the sweep is no longer testing anything"
            )
        out.unlink(missing_ok=True)

    if failures:
        print("PROMOTION GATE CONTRACT: FAIL")
        for item in failures:
            print(" -", item)
        return 1
    print("PROMOTION GATE CONTRACT: PASS")
    print("  every gate refusal case refused; no arm permitted a stale promotion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
