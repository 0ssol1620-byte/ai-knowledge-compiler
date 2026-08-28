#!/usr/bin/env python3
"""Every precondition the freeze depends on, checked in one place.

The ruling's sequence is: commit the instrument, check it out in isolation at
that exact commit, re-run the whole prospective gate there, and only then
freeze. This is that gate.

**Fail closed.** A condition that could not be evaluated is `UNPROVEN`, and
`UNPROVEN` does not pass. The states are deliberately three, not two: a
condition that failed and a condition nobody could measure are different
problems, and collapsing them would let a broken checker read as a clean bill.

**Receipts are verified, not trusted.** Each recorded receipt has its digest
recomputed from its own body, so a receipt edited after it was written is
caught. Two of them -- the legacy taxonomy and the mutation baselines -- take
minutes to re-derive; `--rerun-slow` does that instead of reading them, and the
report always says which of the two happened.

**The roster stays shut.** The last condition is that no real cohort has been
observed. Everything above it is about being ready to look; this one is about
not having looked yet, and it is checked last because it is the one that stops
being true the moment the freeze succeeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir9-freeze-gate.json"
SCHEMA = "tavonel.sfir9.freeze_gate.v1"

PASS = "PASS"  # noqa: S105 - a gate state, not a credential
FAIL = "FAIL"
UNPROVEN = "UNPROVEN"

#: Receipts written by other tools, with the field that carries their verdict
#: and the key their own digest lives under.
TAXONOMY = ("sfir9-legacy-failure-taxonomy.json", "freeze_condition_met", "taxonomy_digest")
AUDIT = ("sfir9-hostile-audit.json", "audit_passes", "audit_digest")
BASELINES = ("sfir9-mutation-baselines.json", "all_baselines_green", "baselines_digest")

#: Any of these on disk means a real cohort has been opened.
ROSTER_ARTIFACTS = ("sfir9-cohort-roster*.json", "sfir9-census*.json", "sfir9-roster*.json")


@dataclass(frozen=True)
class Outcome:
    state: str
    detail: str


@dataclass(frozen=True)
class Condition:
    name: str
    what_it_establishes: str
    check: Callable[[Path], Outcome]


def _run_suite(root: Path, selection: list[str], *, timeout: int = 1800) -> Outcome:
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "pytest", *selection, "-q", "--no-header"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        return Outcome(UNPROVEN, f"the suite could not be run: {error}")
    tail = result.stdout.strip().splitlines()[-1:] or [""]
    if result.returncode == 5:
        return Outcome(UNPROVEN, "the selection collected no tests")
    return Outcome(PASS if result.returncode == 0 else FAIL, tail[0])


def read_receipt(root: Path, name: str, verdict_key: str, digest_key: str) -> Outcome:
    """Present, internally consistent, and green -- in that order."""
    path = root / "receipts" / name
    if not path.is_file():
        return Outcome(UNPROVEN, f"{name} has not been written")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return Outcome(UNPROVEN, f"{name} could not be read: {error}")
    recorded = report.get(digest_key)
    body = {key: value for key, value in report.items() if key != digest_key}
    recomputed = "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if recorded != recomputed:
        return Outcome(FAIL, f"{name} was edited after it was written")
    if verdict_key not in report:
        return Outcome(UNPROVEN, f"{name} carries no {verdict_key}")
    if report[verdict_key] is not True:
        return Outcome(FAIL, f"{name} reports {verdict_key} = {report[verdict_key]!r}")
    return Outcome(PASS, f"{name} verified, {digest_key} recomputes")


def check_closure(root: Path) -> Outcome:
    """Component closure, source recoverability and import isolation at once.

    They are one condition because they are one call: the closure verifies every
    component's committed blob, its bytes on disk, and where its module actually
    resolved from, and refuses if any of the three disagree.
    """
    sys.path.insert(0, str(root / "tools"))
    try:
        import sfir9_execution_closure as closure
    except ImportError as error:
        return Outcome(UNPROVEN, f"the closure could not be imported: {error}")
    try:
        closure.require_component_lists_agree()
        result = closure.closure(repository_root=root)
    except closure.ClosureRefused as error:
        return Outcome(FAIL, str(error))
    except Exception as error:
        return Outcome(UNPROVEN, f"the closure could not be evaluated: {error}")
    # No per-record re-check here. `closure()` raises on the first component
    # that fails any of the five bindings, so a returned record can only say
    # they held -- a second check over those fields could never fire.
    return Outcome(
        PASS, f"{result['component_count']} components bound five ways"
    )


def check_roster_unopened(root: Path) -> Outcome:
    found = sorted(
        path.name
        for pattern in ROSTER_ARTIFACTS
        for path in (root / "receipts").glob(pattern)
    )
    if found:
        return Outcome(FAIL, f"a real cohort has already been opened: {found}")
    return Outcome(PASS, "no real cohort artifact exists")


CONDITIONS = (
    Condition(
        "sfir8_equivalence_j1_j2",
        "segmented traversal equals uninterrupted traversal, and a canonical "
        "address equals the redirect-followed one",
        lambda root: _run_suite(root, ["tests/test_sfir8_equivalence.py"]),
    ),
    Condition(
        "component_suites",
        "every component the freeze binds passes its own controls",
        lambda root: _run_suite(root, ["tests", "-k", "sfir9"]),
    ),
    Condition(
        "seam_verification",
        "catalogue parser to live transport, bound at every stage, with the "
        "selected set fixed by an external oracle",
        lambda root: _run_suite(root, ["tests/test_sfir9_seam.py"]),
    ),
    Condition(
        "execution_closure",
        "ten components, each verified by path, hash, committed blob, working "
        "bytes and import origin",
        check_closure,
    ),
    Condition(
        "historical_isolation",
        "the prospective chain depends on no historical authority",
        lambda root: _run_suite(root, ["tests/test_sfir9_isolation_gate.py"]),
    ),
    Condition(
        "hostile_audit",
        "thirteen attacks mounted for real, each refused with the code it "
        "should refuse with",
        lambda root: read_receipt(root, *AUDIT),
    ),
    Condition(
        "legacy_failure_taxonomy",
        "no failure anywhere in this repository is a defect in code the "
        "prospective chain depends on",
        lambda root: read_receipt(root, *TAXONOMY),
    ),
    Condition(
        "mutation_baselines",
        "every component's tests still notice when the component is weakened",
        lambda root: read_receipt(root, *BASELINES),
    ),
    Condition(
        "roster_not_yet_opened",
        "no real cohort has been observed, so nothing downstream of the roster "
        "could have been fitted to it",
        check_roster_unopened,
    ),
)

SLOW = {"legacy_failure_taxonomy": "tools/sfir9_legacy_taxonomy.py",
        "mutation_baselines": "tools/sfir9_mutation.py"}


def _rerun(root: Path, script: str) -> Outcome:
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, script],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=7200,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        return Outcome(UNPROVEN, f"{script} could not be re-run: {error}")
    tail = (result.stdout.strip().splitlines() or [""])[-1]
    return Outcome(PASS if result.returncode == 0 else FAIL, f"re-derived: {tail}")


def gate(root: Path = NS, *, rerun_slow: bool = False) -> dict[str, Any]:
    rows = []
    for condition in CONDITIONS:
        if rerun_slow and condition.name in SLOW:
            outcome = _rerun(root, SLOW[condition.name])
            derived = "re-derived in this run"
        else:
            outcome = condition.check(root)
            derived = (
                "read from its receipt, digest recomputed"
                if condition.name in SLOW
                else "evaluated in this run"
            )
        rows.append(
            {
                "condition": condition.name,
                "establishes": condition.what_it_establishes,
                "state": outcome.state,
                "detail": outcome.detail,
                "how": derived,
            }
        )
    passed = [row for row in rows if row["state"] == PASS]
    body = {
        "schema": SCHEMA,
        "conditions_checked": len(rows),
        "conditions_passed": len(passed),
        "conditions": rows,
        "gate_opens": len(passed) == len(rows),
        "unproven_does_not_pass": (
            "a condition nobody could measure and a condition that failed are "
            "different problems. Neither opens the gate."
        ),
        "why_the_seam_has_its_own_condition": (
            "`component_suites` already collects the seam tests -- `-k sfir9` "
            "matches their path. The narrow condition is not redundant with the "
            "broad one: if the seam file were deleted, the broad condition would "
            "still pass with fewer tests, while the narrow one reports UNPROVEN "
            "because its selection collected nothing. A suite that vanished and "
            "a suite that passed look identical to a count of failures."
        ),
        "what_this_gate_does_not_establish": (
            "that any threshold here is calibrated, or that the instrument "
            "measures what the protocol says it measures. It establishes that "
            "the instrument is the one that was committed, and that nothing "
            "downstream of the cohort has seen the cohort."
        ),
    }
    return {
        **body,
        "gate_digest": "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the SFIR9 prospective freeze gate")
    parser.add_argument(
        "--rerun-slow",
        action="store_true",
        help="re-derive the taxonomy and mutation baselines instead of reading them",
    )
    parser.add_argument("--root", type=Path, default=NS)
    args = parser.parse_args(argv)

    report = gate(args.root, rerun_slow=args.rerun_slow)
    for row in report["conditions"]:
        print(f"{row['state']:<9} {row['condition']:<28} {row['detail'][:70]}")
    OUTPUT.write_bytes(json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    print("-" * 70)
    print(f"{report['conditions_passed']}/{report['conditions_checked']} conditions pass")
    print(f"FREEZE GATE {'OPEN' if report['gate_opens'] else 'CLOSED'}")
    print(f"written to {OUTPUT.relative_to(REPO).as_posix()}")
    return 0 if report["gate_opens"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
