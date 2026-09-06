#!/usr/bin/env python3
"""Fail if the A9 contract suite reached green by skipping.

Three of these contracts guard themselves with `skipif` on artifacts that are
not always present: the evaluator-equivalence test needs the private
OmniDocBench checkout, and the provenance contracts need the committed holdout
receipts. That is the right behaviour for a developer running locally without
the private corpus, and the wrong behaviour for a gate -- a suite where every
test skips reports success and checks nothing.

This is not hypothetical for this suite specifically. The evaluator-alignment
test was silently skipping for a whole working session because its repository
root was computed with `parents[3]` instead of `parents[4]`, so it looked for
the evaluator one directory too high and never found it. It passed, green, and
verified nothing. The defect it exists to catch -- an instrument counting 88
tables where the official evaluator counts 60 -- was live at the time.

So the count of skips is itself part of the contract: at most the number the
runner cannot avoid, and no more.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-skips", type=int, required=True)
    args = parser.parse_args()

    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            str(TESTS),
            "-p",
            "no:cacheprovider",
            "-q",
            "-rs",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    print(completed.stdout)
    print(completed.stderr, file=sys.stderr)

    if completed.returncode != 0:
        print("contract suite failed; that failure is the result", file=sys.stderr)
        return completed.returncode

    # pytest's terminal summary line: "45 passed, 2 skipped in 0.73s"
    summary = [
        line
        for line in completed.stdout.splitlines()
        if " passed" in line or " skipped" in line or " no tests ran" in line
    ]
    if not summary:
        print("could not find a pytest summary line to read", file=sys.stderr)
        return 1
    last = summary[-1]

    skipped = 0
    passed = 0
    for index, token in enumerate(last.replace(",", " ").split()):
        if token.startswith("skipped") and index:
            skipped = int(last.replace(",", " ").split()[index - 1])
        if token.startswith("passed") and index:
            passed = int(last.replace(",", " ").split()[index - 1])

    print(f"executed {passed}, skipped {skipped}, ceiling {args.max_skips}")
    if passed == 0:
        print("no contract executed at all", file=sys.stderr)
        return 1
    if skipped > args.max_skips:
        print(
            f"{skipped} contracts skipped, ceiling is {args.max_skips}. A gate "
            "that skips is not a gate. Either the artifacts a contract binds to "
            "stopped being committed, or a guard is computing the wrong path -- "
            "which has happened here before.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
