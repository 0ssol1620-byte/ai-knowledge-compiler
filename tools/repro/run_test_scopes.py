#!/usr/bin/env python3
"""Run named test scopes and emit a machine-readable status receipt.

P18: the program status recorded "repository green | 696 passed" while the full
repository suite had 25 failures. The number was true of `tests/unit` and the
label was true of nothing. Nobody lied; a narrow command's result was given a
wide command's name.

The structural fix is to stop letting a human write the word. A scope is green
only if a run of *that scope* reported zero failures, and the word is emitted by
this tool from a parsed pytest summary, never typed into a document.

Two rules the guard enforces:

1. `green` requires `failed == 0` AND `errors == 0` AND a nonzero collected
   count. A run that collected nothing is not green; it is broken.
2. "repository green" means the `full` scope and nothing else. `unit` green does
   not license it, which is the exact substitution P18 recorded.

`--self-test` runs the positive control: a scope pointed at a deliberately
failing test, asserting the guard refuses to call it green. A guard whose alarm
has never been heard is not evidence, and this programme has already voided one
experiment on an instrument that could not separate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

#: The interpreter the project's environment is installed into.
#:
#: This is not pedantry. Running the suite with the global interpreter produced 24
#: failures that looked like product defects and were not: the parser sandbox
#: launches its child with `-I`, which excludes user site-packages, and the
#: dependencies were installed there. Under the project venv the same child
#: imports cleanly. A test result is only meaningful together with the interpreter
#: that produced it, so the interpreter is recorded and checked.
_VENV_BIN = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
PROJECT_PYTHON = ROOT / ".venv" / _VENV_BIN

SCOPES: dict[str, list[str]] = {
    "unit": ["tests/unit"],
    "full": [],  # whole repository, pytest's own default collection
}

#: Only this scope may be described as "the repository".
REPOSITORY_SCOPE = "full"

_COUNT = re.compile(r"(\d+) (passed|failed|skipped|error|errors|xfailed|xpassed|deselected)")
_COLLECTED = re.compile(r"collected (\d+) items?")


def parse_summary(text: str) -> dict[str, int]:
    """Pull counts out of pytest's terminal summary.

    Reads the LAST line that carries counts, because pytest prints per-file
    progress lines that can also match.
    """
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0,
              "xfailed": 0, "xpassed": 0, "deselected": 0, "collected": 0}
    tail = [ln for ln in text.splitlines() if _COUNT.search(ln)]
    if tail:
        for n, kind in _COUNT.findall(tail[-1]):
            key = "errors" if kind in ("error", "errors") else kind
            counts[key] = int(n)

    # `-q` suppresses pytest's "collected N items" line, so it is usually absent.
    # Fall back to the number of outcomes actually reported. Recorded either way,
    # because "collected 0" is the guard's broken-scope trip wire and it must not
    # fire merely because the count was printed in a different verbosity.
    for match in _COLLECTED.finditer(text):
        counts["collected"] = int(match.group(1))
    counts["collected_source"] = "reported" if counts["collected"] else "summed_outcomes"
    if not counts["collected"]:
        counts["collected"] = sum(
            counts[k] for k in ("passed", "failed", "skipped", "errors", "xfailed", "xpassed")
        )
    return counts


def is_green(counts: dict[str, Any], exit_code: int) -> tuple[bool, str]:
    """The single place the word is decided.

    Returns (green, reason). The reason is recorded whether or not it is green,
    so a red result explains itself in the receipt instead of in a commit message.
    """
    if counts["collected"] == 0:
        return False, "collected 0 items -- a scope that ran nothing is broken, not green"
    if counts["failed"]:
        return False, f"{counts['failed']} failed"
    if counts["errors"]:
        return False, f"{counts['errors']} errors"
    if exit_code != 0:
        return False, f"pytest exit code {exit_code} with no parsed failures"
    return True, "zero failures and zero errors in this scope"


def interpreter_state() -> dict[str, Any]:
    running = Path(sys.executable).resolve()
    expected = PROJECT_PYTHON.resolve() if PROJECT_PYTHON.exists() else None
    return {
        "running_interpreter": str(running),
        "project_interpreter": str(expected) if expected else None,
        "project_venv_present": PROJECT_PYTHON.exists(),
        "is_project_interpreter": bool(expected and running == expected),
        "why_it_matters": (
            "The parser sandbox launches its child with -I, which excludes user "
            "site-packages. Dependencies installed there are invisible to it, and the "
            "child dies with PARSER_PROCESS_CRASH -- 24 failures that look like product "
            "defects. A result from the wrong interpreter is not a result about this "
            "repository."
        ),
    }


def run_scope(name: str, targets: list[str], extra: list[str] | None = None) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:randomly",
           *targets, *(extra or [])]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)  # noqa: S603
    text = proc.stdout + proc.stderr
    counts = parse_summary(text)
    green, reason = is_green(counts, proc.returncode)
    return {
        "test_scope": name,
        "command": " ".join(cmd[1:]),
        "collected": counts["collected"],
        "collected_source": counts["collected_source"],
        "passed": counts["passed"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "errors": counts["errors"],
        "exit_code": proc.returncode,
        "green": green,
        "green_reason": reason,
        "summary_line": (
            [ln for ln in text.splitlines() if _COUNT.search(ln)] or ["<no summary line>"]
        )[-1].strip(),
    }


def self_test() -> dict[str, Any]:
    """Positive control: does the guard refuse to call a failing scope green?

    A synthetic scope with one passing and one failing test. If the guard reports
    green here, every other green in this receipt is worthless.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "test_control.py").write_text(
            "def test_that_passes():\n    assert True\n\n\n"
            "def test_that_fails():\n    assert 1 == 2, 'deliberate control failure'\n",
            encoding="utf-8",
        )
        injected = run_scope("__positive_control__", [str(d)], extra=["-p", "no:cacheprovider"])

    clean = run_scope("__negative_control__", ["tests/unit/test_migration_graph.py"])

    # The repository-green verdict has its own logic on top of per-scope green:
    # it requires the FULL scope specifically, and the project interpreter. Both
    # are exercised here against synthetic scope results, because the failure P18
    # actually recorded was not "a scope was wrongly called green" -- it was "a
    # green narrow scope was called the repository".
    interp_ok = interpreter_state()["is_project_interpreter"]
    full_failing = {"test_scope": "full", "green": False}
    unit_green_only = {"test_scope": "unit", "green": True}

    def repo_green(results: list[dict[str, Any]]) -> bool:
        by = {r["test_scope"]: r for r in results}
        repo = by.get(REPOSITORY_SCOPE)
        return bool(repo and repo["green"] and interp_ok)

    return {
        "purpose": (
            "Prove the guard can say NO. A scope-reporting guard that has never refused "
            "anything is an assertion, not a check."
        ),
        "injected_failure_scope": injected,
        "clean_scope": clean,
        "guard_refused_injected": injected["green"] is False,
        "guard_accepted_clean": clean["green"] is True,
        "repository_verdict_controls": {
            "full_scope_with_failure_refused": repo_green([full_failing]) is False,
            "unit_green_alone_refused": repo_green([unit_green_only]) is False,
            "why": (
                "P18 was not a scope wrongly called green. It was a green NARROW scope "
                "called the repository. The verdict must refuse both a failing full scope "
                "and a green unit scope offered in its place."
            ),
        },
        "separates": (
            injected["green"] is False
            and clean["green"] is True
            and repo_green([full_failing]) is False
            and repo_green([unit_green_only]) is False
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scopes", nargs="*", default=["unit"],
                    help="scope names to run; 'full' runs the whole repository")
    ap.add_argument("--self-test", action="store_true",
                    help="run the positive control only")
    args = ap.parse_args()

    control = self_test()
    results = [] if args.self_test else [
        run_scope(name, SCOPES[name]) for name in args.scopes if name in SCOPES
    ]

    by_scope = {r["test_scope"]: r for r in results}
    repo = by_scope.get(REPOSITORY_SCOPE)
    receipt: dict[str, Any] = {
        "schema": "tavonel.test-scope-status.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "closes": (
            "P18 -- 'repository green' was written from a tests/unit run. The word is now "
            "emitted by this tool from a parsed summary of the scope actually executed."
        ),
        "interpreter": interpreter_state(),
        "scopes": results,
        "positive_control": control,
        "repository_scope": REPOSITORY_SCOPE,
        "repository_green": bool(
            repo and repo["green"] and interpreter_state()["is_project_interpreter"]
        ),
        "repository_green_evaluated": repo is not None,
        "repository_green_note": (
            "Only the 'full' scope may be called the repository. A green 'unit' scope does "
            "not license the phrase; that substitution is exactly what P18 recorded. When "
            "the full scope was not run, repository_green is False and "
            "repository_green_evaluated is False -- absence of a run is not a pass."
        ),
        "guard_is_live": control["separates"],
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()

    # `--self-test` runs the positive control and NO scope, so its receipt has an
    # empty `scopes` list and `repository_green: false`. Writing that to the
    # canonical path destroys the last real full-run result and replaces it with a
    # receipt that reads as a red repository. That happened on 2026-08-19 and again
    # on 2026-08-20; the 2026-08-19T23:44Z and 2026-08-20T09:56Z snapshots are gone
    # and survive only as numbers quoted in an incident record.
    #
    # The control-only run now writes beside the canonical receipt instead of over
    # it. A run that measured no scope cannot speak for the repository.
    canonical = ROOT / "docs" / "repro" / "TEST_SCOPE_STATUS.json"
    out = (canonical.with_name("TEST_SCOPE_SELF_TEST.json") if args.self_test
           else canonical)
    out.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" because this artifact is cited by sha256. Path.write_text
    # emits CRLF on Windows, git stores LF, and the digest of the file on disk
    # then never matches the digest of the file anyone checks out.
    out.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.self_test:
        print(f"  self-test only: {canonical.name} left untouched")

    interp = interpreter_state()
    print(f"interpreter: {interp['running_interpreter']}")
    if not interp["is_project_interpreter"]:
        print("  ! NOT the project interpreter -- repository_green is withheld")
    print(f"guard live (refuses injected failure, accepts clean): {control['separates']}")
    for r in results:
        state = "GREEN" if r["green"] else "NOT GREEN"
        print(
            f"  {r['test_scope']:<6} {state:<9} "
            f"collected={r['collected']} passed={r['passed']} failed={r['failed']} "
            f"skipped={r['skipped']} exit={r['exit_code']}  -- {r['green_reason']}"
        )
    print(f"repository_green: {receipt['repository_green']} "
          f"(evaluated: {receipt['repository_green_evaluated']})")
    print(f"wrote {out}")
    return 0 if control["separates"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
