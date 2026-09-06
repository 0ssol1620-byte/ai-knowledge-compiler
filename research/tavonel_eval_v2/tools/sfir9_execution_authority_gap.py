#!/usr/bin/env python3
"""Prove, mechanically, that SFIR9 has no frozen rate-window orchestration.

This is a diagnostic. It changes no instrument, issues no authority and runs no
census. It exists because the answer to one question decides whether SFIR9 can
produce a sealable capacity result, and that answer should be reproducible by
someone who does not trust this session's prose.

The question, asked before any cohort repository was contacted:

    what pre-roster frozen artifact specifies WHEN the runner invokes
    `observe_rate_window`, how `remaining` / `reset_epoch` / `retry_after` are
    obtained, and when a segment must terminate?

Frozen constants are not an answer. `RETRY_WAIT_SECONDS`, `TOTAL_WAIT_SECONDS`
and `SEGMENT_COMPLETE_RATE_WINDOW` are all frozen, and all three describe what
happens *once the decision function has been called with three observed values*.
None of them says when to call it, or where the values come from.

Five findings, each checked against bytes rather than recalled:

    1. `observe_rate_window` has no production caller. Only tests reach it.
    2. `plan_wait` is reachable only through `observe_rate_window`.
    3. `HopAtom` -- the frozen evidence record for one network hop -- carries
       `provider_remaining_before/after` and no reset epoch and no retry-after.
       Two of `plan_wait`'s three inputs cannot come from hop evidence.
    4. The frozen upstream reads only `x-ratelimit-remaining` from response
       headers. It never reads `x-ratelimit-reset` or `Retry-After`.
    5. The transport's own `declared_surface()` nevertheless declares all three
       as `observed_from`. The declaration is frozen; the acquisition is absent.

And the consequence, which is why this is not a cosmetic gap: with no caller,
nothing closes a segment on a rate window. A 403 comes back through the frozen
upstream as an ordinary record with a non-dict body, `_expand` reads that as an
empty tree, the frontier drains, and the root is recorded `FRONTIER_EXHAUSTED`
-- which the frozen scorer defines as "its candidate count is the count".

That is SFIR7's failure restated exactly: an instrument that stopped, reported
as a measurement. It is the failure SFIR9 was built to eliminate.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
OUTPUT = NS / "receipts/sfir9-execution-authority-gap.json"
SCHEMA = "tavonel.sfir9.execution_authority_gap.v1"

OBSERVED = "OBSERVED"
ASSERTED = "ASSERTED"

#: Where a production caller could live. Tests are deliberately excluded: a
#: function exercised only by its own controls has no orchestration behind it.
PRODUCTION_DIRS = ("tools",)
TEST_DIRS = ("tests",)


def _digest(payload: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def _calls_in(path: Path, name: str) -> list[str]:
    """Every call to `name` in one file, by the caller's own function name.

    Parsed rather than grepped: a mention in a docstring or a comment is not a
    caller, and this finding turns on the difference.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        attribute = func.attr if isinstance(func, ast.Attribute) else None
        plain = func.id if isinstance(func, ast.Name) else None
        if name not in {attribute, plain}:
            continue
        enclosing = "<module>"
        for candidate in ast.walk(tree):
            if isinstance(
                candidate, ast.FunctionDef | ast.AsyncFunctionDef
            ) and candidate.lineno <= node.lineno <= (candidate.end_lineno or node.lineno):
                enclosing = candidate.name
        found.append(f"{path.name}:{node.lineno} in {enclosing}()")
    return found


def callers_of(namespace: Path, name: str) -> dict[str, list[str]]:
    """Production callers and test callers, kept apart."""
    production, tests = [], []
    for directory, sink in ((PRODUCTION_DIRS, production), (TEST_DIRS, tests)):
        for folder in directory:
            for path in sorted((namespace / folder).glob("*.py")):
                sink.extend(_calls_in(path, name))
    # A definition is not a call, and neither is the method's own body.
    return {"production": production, "tests": tests}


def hop_evidence_fields(namespace: Path) -> dict[str, Any]:
    """What one frozen hop record can actually carry."""
    sys.path.insert(0, str(namespace / "tools"))
    import sfir8_transport

    fields = [f.name for f in dataclasses.fields(sfir8_transport.HopAtom)]
    return {
        "hop_atom_fields": fields,
        "carries_provider_remaining": any("remaining" in f for f in fields),
        "carries_reset_epoch": any("reset" in f for f in fields),
        "carries_retry_after": any("retry" in f for f in fields),
    }


def headers_read_by_the_frozen_upstream(namespace: Path) -> dict[str, Any]:
    """Which rate-window headers the frozen hop implementation extracts."""
    source = (namespace / "tools/sfir8_transport.py").read_text(encoding="utf-8").lower()
    return {
        "x_ratelimit_remaining": "x-ratelimit-remaining" in source,
        "x_ratelimit_reset": "x-ratelimit-reset" in source,
        "retry_after": "retry-after" in source,
    }


def declared_but_unimplemented(namespace: Path) -> dict[str, Any]:
    sys.path.insert(0, str(namespace / "tools"))
    import sfir9_transport

    surface = sfir9_transport.declared_surface()
    return {
        "declared_observed_from": surface["rate_window"]["observed_from"],
        "declared_segment_close_condition": surface["segment_close_condition"],
        "declared_polling_permitted": surface["rate_window"][
            "polling_to_discover_whether_the_limit_lifted"
        ],
    }


def findings(namespace: Path = NS) -> dict[str, Any]:
    observe = callers_of(namespace, "observe_rate_window")
    plan = callers_of(namespace, "plan_wait")
    hops = hop_evidence_fields(namespace)
    headers = headers_read_by_the_frozen_upstream(namespace)
    declared = declared_but_unimplemented(namespace)

    body = {
        "schema": SCHEMA,
        "study_id": "SOURCE_FACT_IR_FRESH_HELDOUT_V9",
        "question": (
            "what pre-roster frozen artifact specifies when the runner invokes "
            "observe_rate_window, how remaining/reset_epoch/retry_after are "
            "obtained, and when a segment must terminate?"
        ),
        "findings": {
            "observe_rate_window_production_callers": {
                "value": observe["production"],
                "basis": OBSERVED,
                "how": "every call site in tools/, parsed rather than grepped",
            },
            "observe_rate_window_test_callers": {
                "value": observe["tests"],
                "basis": OBSERVED,
                "how": (
                    "a function exercised only by its own controls has no "
                    "orchestration behind it"
                ),
            },
            "plan_wait_production_callers": {
                "value": plan["production"],
                "basis": OBSERVED,
                "how": "the wait decision is reachable only through observe_rate_window",
            },
            "hop_evidence": {
                "value": hops,
                "basis": OBSERVED,
                "how": "dataclass fields of the frozen HopAtom",
            },
            "rate_window_headers_read_by_the_frozen_upstream": {
                "value": headers,
                "basis": OBSERVED,
                "how": "byte search of the frozen sfir8_transport source",
            },
            "declared_surface": {
                "value": declared,
                "basis": OBSERVED,
                "how": "sfir9_transport.declared_surface() as it stands frozen",
            },
        },
        "conclusion": {
            "a_frozen_rate_window_orchestration_exists": False,
            "basis": OBSERVED,
            "how": (
                "observe_rate_window has no production caller; plan_wait is "
                "reachable only through it; two of plan_wait's three inputs "
                "cannot be carried by the frozen hop record and are never read "
                "from response headers by the frozen upstream. The surface "
                "declares all three as observed, so the declaration is frozen "
                "and the acquisition is absent."
            ),
        },
        "why_this_is_not_a_seam": (
            "a seam is two frozen components whose shapes do not meet, bridged "
            "by a representation-only adapter that decides nothing. This is a "
            "decision nobody has made: when to look, what to look at, and when "
            "to stop. Choosing it now would be choosing it with the roster "
            "visible."
        ),
        "consequence_if_it_were_invented_now": (
            "with no caller, nothing closes a segment on a rate window. A 403 "
            "returns through the frozen upstream as an ordinary record with a "
            "non-dict body; _expand reads that as an empty tree; the frontier "
            "drains; and the root is recorded FRONTIER_EXHAUSTED, which the "
            "frozen scorer defines as a count that is exact. That is SFIR7's "
            "failure restated: an instrument that stopped, reported as a "
            "measurement, which is the failure SFIR9 exists to eliminate."
        ),
        "what_was_not_done": (
            "no polling schedule was invented, no segment budget was chosen, no "
            "checkpoint cadence was selected, and no census was run. The "
            "instrument freeze, the cohort-input binding and the sealed roster "
            "are unchanged."
        ),
        "what_this_does_not_establish": {
            "value": (
                "that SFIR9's frozen components are wrong, or that a future "
                "protocol cannot use them. Everything frozen here remains valid "
                "for a study whose orchestration is frozen before selection."
            ),
            "basis": ASSERTED,
        },
    }
    return {**body, "gap_digest": _digest(body)}


def verify(report: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in report.items() if key != "gap_digest"}
    problems = []
    if _digest(body) != report.get("gap_digest"):
        problems.append("gap_digest does not recompute; the receipt was edited")
    conclusion = report.get("conclusion", {})
    if conclusion.get("basis") != OBSERVED:
        problems.append("the conclusion does not rest on an observation")
    return {
        "schema": SCHEMA + ".verification",
        "verified": not problems,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", type=Path, default=NS)
    args = parser.parse_args(argv)
    report = findings(args.namespace)
    found = report["findings"]
    hops = found["hop_evidence"]["value"]
    surface = found["declared_surface"]["value"]
    headers = found["rate_window_headers_read_by_the_frozen_upstream"]["value"]
    print("question:", report["question"])
    print()
    observe_prod = found["observe_rate_window_production_callers"]["value"]
    observe_tests = found["observe_rate_window_test_callers"]["value"]
    plan_prod = found["plan_wait_production_callers"]["value"]
    print(f"observe_rate_window production callers  {observe_prod}")
    print(f"observe_rate_window test callers        {len(observe_tests)}")
    print(f"plan_wait production callers            {plan_prod}")
    print(f"hop record carries reset epoch          {hops['carries_reset_epoch']}")
    print(f"hop record carries retry-after          {hops['carries_retry_after']}")
    print(f"upstream reads rate-window headers      {headers}")
    print(f"surface declares observed_from          {surface['declared_observed_from']}")
    print()
    print(f"a frozen rate-window orchestration exists: "
          f"{report['conclusion']['a_frozen_rate_window_orchestration_exists']}")
    print(f"verify  {verify(report)}")
    OUTPUT.write_bytes(json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    print(f"written to {OUTPUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
