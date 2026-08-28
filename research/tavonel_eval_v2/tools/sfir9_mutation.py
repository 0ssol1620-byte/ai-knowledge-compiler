#!/usr/bin/env python3
"""Run every component's mutation table and record what survived.

"Mutation baselines green" is a freeze precondition, and a precondition that
lives only in a session's transcript is not one. This runs the committed tables
against the committed components and writes
`receipts/sfir9-mutation-baselines.json`.

Three rules the engine enforces, each of which cost a real round to learn:

**A red baseline is refused, never run.** Against a suite that is already
failing, every mutation looks killed and the score is a perfect, meaningless
100%. The unmutated suite has to pass first or the component is recorded as
`BASELINE_RED` and the run does not pass.

**A missing anchor is a survivor, not a skip.** A table entry whose text no
longer appears in the file has stopped testing anything. Silently skipping it
would let a component drift out from under its own mutations while the score
stayed green.

**A test selection that excludes some tests must still leave a green baseline.**
The closure cannot verify itself -- mutating it breaks its own committed-versus-
working check, so every real-repository control dies trivially and the mutation
proves nothing. Those controls are excluded by name and copy-tree equivalents
carry the load, but an exclusion that emptied the suite would also look green.
So the baseline is required to have actually run tests.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir9-mutation-baselines.json"
SCHEMA = "tavonel.sfir9.mutation_baselines.v1"

#: One table module per component, in the freeze's own order.
COMPONENTS = (
    "protocol",
    "transport",
    "identity",
    "chain",
    "roster",
    "scorer",
    "acceptance",
    "closure",
    "gate",
    "selection",
    "audit",
    "taxonomy",
    "freeze_gate",
)

KILLED = "KILLED"
SURVIVED = "SURVIVED"
ANCHOR_MISSING = "ANCHOR_MISSING"
HUNG = "HUNG"
BASELINE_RED = "BASELINE_RED"
EMPTY_BASELINE = "BASELINE_SELECTED_NO_TESTS"

#: pytest's exit code for "no tests collected".
NO_TESTS_COLLECTED = 5

#: Outcomes that do not count as a killed mutation.
NOT_KILLED = (SURVIVED, ANCHOR_MISSING, HUNG)


@dataclass(frozen=True)
class Table:
    """One component's target, test selection and hand-written mutations."""

    component: str
    target: str
    tests: tuple[str, ...]
    mutations: tuple[tuple[str, str, str], ...]


def load(component: str) -> Table:
    module = importlib.import_module(f"sfir9_mutation_tables.{component}")
    return Table(
        component=component,
        target=module.TARGET,
        tests=tuple(module.TESTS),
        mutations=tuple(tuple(row) for row in module.MUTATIONS),
    )


def tables() -> tuple[Table, ...]:
    return tuple(load(name) for name in COMPONENTS)


def _pytest(table: Table, *, python: str, root: Path, timeout: int, first_fail: bool):
    args = [python, "-m", "pytest", *table.tests, "-q", "--no-header"]
    if first_fail:
        args.append("-x")
    return subprocess.run(  # noqa: S603 - a fixed argv, no shell
        args, cwd=root, capture_output=True, text=True, timeout=timeout, check=False
    )


def _selected_count(output: str) -> int:
    """How many tests the baseline actually ran, from pytest's own summary."""
    for line in reversed(output.splitlines()):
        for word in line.replace(",", " ").split():
            if word.isdigit() and ("passed" in line or "failed" in line):
                return int(word)
    return 0


def run_component(
    table: Table,
    *,
    python: str = sys.executable,
    root: Path = NS,
    timeout: int = 300,
) -> dict[str, Any]:
    """Baseline first, then one run per mutation with the file restored after."""
    baseline = _pytest(table, python=python, root=root, timeout=timeout * 3, first_fail=False)
    selected = _selected_count(baseline.stdout)
    # Checked before the red-baseline branch: pytest exits 5 on "no tests
    # collected", which is non-zero, and an emptied selection would otherwise be
    # reported as a failing suite rather than as the missing suite it is.
    if baseline.returncode == NO_TESTS_COLLECTED or selected == 0:
        return {
            "component": table.component,
            "target": table.target,
            "state": EMPTY_BASELINE,
            "why_not_run": (
                "the selection left no tests. An empty suite passes, so every "
                "mutation would have looked killed."
            ),
            "mutations_declared": len(table.mutations),
            "mutations_killed": 0,
            "survivors": [],
            "baseline_tests_selected": 0,
        }
    if baseline.returncode != 0:
        return {
            "component": table.component,
            "target": table.target,
            "state": BASELINE_RED,
            "why_not_run": (
                "against a failing suite every mutation looks killed. The score "
                "would have been a perfect and meaningless 100%."
            ),
            "mutations_declared": len(table.mutations),
            "mutations_killed": 0,
            "survivors": [],
            "baseline_tests_selected": selected,
        }

    path = root / table.target
    outcomes = []
    for label, old, new in table.mutations:
        original = path.read_bytes()
        text = original.decode("utf-8")
        if old not in text:
            outcomes.append({"mutation": label, "outcome": ANCHOR_MISSING})
            continue
        path.write_bytes(text.replace(old, new, 1).encode("utf-8"))
        try:
            try:
                result = _pytest(
                    table, python=python, root=root, timeout=timeout, first_fail=True
                )
                outcome = KILLED if result.returncode != 0 else SURVIVED
            except subprocess.TimeoutExpired:
                outcome = HUNG
        finally:
            path.write_bytes(original)
        outcomes.append({"mutation": label, "outcome": outcome})

    survivors = [row for row in outcomes if row["outcome"] in NOT_KILLED]
    return {
        "component": table.component,
        "target": table.target,
        "state": "RUN",
        "mutations_declared": len(table.mutations),
        "mutations_killed": len(outcomes) - len(survivors),
        "survivors": survivors,
        "baseline_tests_selected": selected,
        "outcomes": outcomes,
    }


def baselines(results: list[dict[str, Any]]) -> dict[str, Any]:
    declared = sum(r["mutations_declared"] for r in results)
    killed = sum(r["mutations_killed"] for r in results)
    clean = [r for r in results if r["state"] == "RUN" and not r["survivors"]]
    body = {
        "schema": SCHEMA,
        "components_run": len(results),
        "mutations_declared": declared,
        "mutations_killed": killed,
        "components_with_no_survivor": len(clean),
        "all_baselines_green": len(clean) == len(results) and declared == killed,
        "results": results,
        "why_a_red_baseline_is_refused": (
            "against a failing suite every mutation looks killed, so the score "
            "would be a perfect 100% that measured nothing."
        ),
        "why_a_missing_anchor_is_a_survivor": (
            "a table entry whose text is no longer in the file has stopped "
            "testing anything. Skipping it would let a component drift out from "
            "under its own mutations while the score stayed green."
        ),
    }
    return {
        **body,
        "baselines_digest": "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", action="append", choices=COMPONENTS)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)

    chosen = [load(name) for name in (args.component or COMPONENTS)]
    results = []
    for table in chosen:
        result = run_component(table, python=args.python)
        results.append(result)
        mark = "clean" if result["state"] == "RUN" and not result["survivors"] else "FAILED"
        print(
            f"{table.component:<12} "
            f"{result['mutations_killed']:>3}/{result['mutations_declared']:<3} {mark}"
        )
        for survivor in result["survivors"]:
            print(f"    {survivor['outcome']}  {survivor['mutation']}")

    report = baselines(results)
    if args.component is None:
        OUTPUT.write_bytes(
            json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        )
        print(f"written to {OUTPUT.relative_to(REPO).as_posix()}")
    print("-" * 60)
    print(f"{report['mutations_killed']}/{report['mutations_declared']} killed")
    print(f"all baselines green: {report['all_baselines_green']}")
    return 0 if report["all_baselines_green"] else 1


if __name__ == "__main__":
    sys.path.insert(0, str(NS / "tools"))
    raise SystemExit(main())
