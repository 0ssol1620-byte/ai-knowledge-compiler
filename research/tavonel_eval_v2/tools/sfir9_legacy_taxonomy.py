#!/usr/bin/env python3
"""Classify every legacy test failure by its root cause, before the freeze.

The freeze condition is `D == 0`: no failure in this repository is a defect in
code the SFIR9 prospective chain depends on. That claim is only worth as much as
the classification behind it, so two rules shape this module.

**Nothing is classified by its name.** A test called
`test_the_gate_refuses_a_spent_root` tells you what its author hoped it did. The
signatures below match the *exception text and traceback* that actually came
back, and a structural control asserts no signature pattern mentions a test name.

**An unrecognised failure is a D.** The default is the category that blocks the
freeze, not the one that permits it. A new failure nobody has looked at is
exactly the thing `D == 0` exists to catch, and a permissive default would have
made the check quietest precisely when it mattered most.

Run it to produce `receipts/sfir9-legacy-failure-taxonomy.json`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir9-legacy-failure-taxonomy.json"
SCHEMA = "tavonel.sfir9.legacy_failure_taxonomy.v1"

A = "A"
B = "B"
C = "C"
D = "D"

CATEGORIES = {
    A: (
        "the study has advanced past the state the test asserts. The test "
        "encodes a snapshot of the repository at an earlier rung -- SFI3 "
        "unacquired, no freeze receipt written, twelve source modules on disk. "
        "Reconciling it would mean either un-acquiring real material or editing "
        "a frozen declaration, and both are worse than the red."
    ),
    B: (
        "a preserved historical frozen drift. The founder ruled that the frozen "
        "drifts are preserved rather than reconciled, and that SFIR9 is built as "
        "an independent chain instead. Turning these green is forbidden; they "
        "are evidence, not breakage."
    ),
    C: (
        "the execution environment, not the instrument. An absent third-party "
        "dependency, or a deliberate guard refusing live network or live cohort "
        "access from a test runner."
    ),
    D: (
        "a defect in code the SFIR9 prospective chain depends on. The freeze "
        "condition is that this category is empty."
    ),
}

#: Categories whose members could still carry scientific weight for SFIR9. A is
#: about repository state, B is preserved evidence, C is the environment -- none
#: of the three is a statement about the prospective instrument.
VALUE_BEARING_FOR_SFIR9 = frozenset({D})

#: The ten components the freeze binds. A failure whose traceback touches one of
#: these is not classifiable as anything but D, whatever else it matches.
SFIR9_COMPONENT_MODULES = (
    "sfir9_protocol",
    "sfir9_transport",
    "sfir9_identity_logic",
    "sfir9_checkpoint_chain",
    "sfir9_cohort_roster",
    "sfir9_scorer",
    "sfir9_acceptance",
    "sfir9_execution_closure",
    "sfir9_isolation_gate",
    "sfir9_selection",
)

UNCLASSIFIED = "no declared signature matched this root cause"


@dataclass(frozen=True)
class Signature:
    """One recognised root cause, matched against traceback text."""

    key: str
    category: str
    pattern: str
    why: str

    def matches(self, text: str) -> bool:
        return re.search(self.pattern, text) is not None


SIGNATURES = (
    Signature(
        "sfi3_frame_materialised",
        A,
        r"sfi3_lineages\.json exists",
        "the SFI3 development frame was materialised, and the enumerator "
        "refuses to be the thing that made it exist. The refusal is the tool "
        "working; the assertion is about a repository state that has moved on.",
    ),
    Signature(
        "sfi3_frame_present_but_asserted_absent",
        A,
        r"assert not True[\s\S]{0,400}?sfi3_lineages\.json",
        "the same materialised frame, seen from the assertion side.",
    ),
    Signature(
        "sfi3_protocol_freeze_receipt_exists",
        A,
        r"a real sfi3-protocol-freeze receipt exists",
        "the orchestrator has already frozen the SFI3 protocol. The suite's "
        "documentation-as-assertion recorded that no freeze had happened yet.",
    ),
    Signature(
        "more_source_modules_than_v2r3_declared",
        A,
        r"assert 16 == 12",
        "four source frames were declared after v2r3 fixed its count. The "
        "declared number sits inside a frozen protocol and is not editable.",
    ),
    Signature(
        "frozen_scorer_module_changed",
        B,
        r"a frozen scorer module has changed since rung \d+",
        "one of the preserved frozen drifts, reported by the rung that pins it.",
    ),
    Signature(
        "attested_files_since_changed",
        B,
        r"attests files that have since changed|pinned files moved|"
        r"moved and it must not have",
        "a frozen attestation naming files that moved. Preserved, not "
        "reconciled: this is what the founder ruled must not be repaired.",
    ),
    Signature(
        "spent_source_digest_drift",
        B,
        r"mandatory spent source digest drift",
        "a spent-authority source whose digest drifted. Spent material cannot "
        "be re-pinned without laundering the record it stands for.",
    ),
    Signature(
        "reservation_no_longer_describes_sfi3",
        B,
        r"the reservation no longer describes what SFI3 declares",
        "the same drift reaching the reservation handoff, which refuses because "
        "a container set that changed cannot be the reserved set.",
    ),
    Signature(
        "frozen_contract_digest_moved",
        B,
        r"AssertionError: (cohort_floor_190|twelve_revision_bound|"
        r"history_horizon_1460_days|source_families_and_weighting|value_scorer|"
        r"value_fact_taxonomy_and_extractor)",
        "a pinned frozen-contract file whose digest moved. The pin exists so "
        "the edit is visible, and it is visible.",
    ),
    Signature(
        "absent_third_party_dependency",
        C,
        r"ModuleNotFoundError: No module named",
        "a third-party package this checkout does not have installed.",
    ),
    Signature(
        "live_cohort_guard",
        C,
        r"LiveCohortRefused",
        "the live-cohort guard refusing to let a test runner touch a live "
        "cohort. The guard firing is the guard working.",
    ),
    Signature(
        "real_network_guard",
        C,
        r"RealNetworkForbidden",
        "the suite's network bar refusing a real socket (INC-V2-100).",
    ),
)


def _text_of(record: dict[str, Any]) -> str:
    return f"{record.get('exception', '')}\n{record.get('traceback_tail', '')}"


def touches_sfir9(record: dict[str, Any]) -> list[str]:
    """Which SFIR9 components, if any, appear in this failure's traceback."""
    text = _text_of(record)
    return [module for module in SFIR9_COMPONENT_MODULES if module in text]


def classify(record: dict[str, Any]) -> dict[str, Any]:
    """Category, the signature that decided it, and why -- or D by default."""
    touched = touches_sfir9(record)
    if touched:
        return {
            "nodeid": record["nodeid"],
            "category": D,
            "signature": "sfir9_component_in_traceback",
            "why": (
                "the traceback reaches "
                + ", ".join(touched)
                + ", which the freeze binds. No other classification applies."
            ),
            "value_bearing_for_sfir9": True,
            "sfir9_components_in_traceback": touched,
        }
    text = _text_of(record)
    for signature in SIGNATURES:
        if signature.matches(text):
            return {
                "nodeid": record["nodeid"],
                "category": signature.category,
                "signature": signature.key,
                "why": signature.why,
                "value_bearing_for_sfir9": signature.category in VALUE_BEARING_FOR_SFIR9,
                "sfir9_components_in_traceback": [],
            }
    return {
        "nodeid": record["nodeid"],
        "category": D,
        "signature": None,
        "why": UNCLASSIFIED,
        "value_bearing_for_sfir9": True,
        "sfir9_components_in_traceback": [],
    }


def taxonomy(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for record in records:
        row = classify(record)
        row["failure_signature"] = (record.get("exception") or "").strip()[:400]
        row["phase"] = record.get("phase")
        rows.append(row)
    counts = {
        name: len([r for r in rows if r["category"] == name]) for name in CATEGORIES
    }
    body = {
        "schema": SCHEMA,
        "failures_examined": len(rows),
        "counts": counts,
        "category_definitions": CATEGORIES,
        "rows": sorted(rows, key=lambda r: r["nodeid"]),
        "freeze_condition": "D == 0",
        "freeze_condition_met": counts[D] == 0,
        "unclassified_defaults_to": D,
        "why_unclassified_is_a_d": (
            "a failure nobody has looked at is exactly what this check exists to "
            "catch. A permissive default would have made it quietest when it "
            "mattered most."
        ),
        "why_names_are_not_used": (
            "a test's name records what its author hoped it did. Every signature "
            "here matches the exception and traceback that actually came back."
        ),
    }
    return {
        **body,
        "taxonomy_digest": "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


class _Collector:
    """Records what actually failed, not what pytest printed."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.outcome != "failed":
            return
        text = str(report.longrepr)
        lines = [line for line in text.splitlines() if line.strip()]
        exception = ""
        for line in reversed(lines):
            stripped = line.strip()
            if stripped.startswith("E "):
                exception = stripped[2:].strip()
                break
        self.rows.append(
            {
                "nodeid": report.nodeid.replace("\\", "/"),
                "phase": report.when,
                "exception": exception,
                "traceback_tail": "\n".join(lines[-25:]),
            }
        )


def collect(paths: list[str] | None = None) -> list[dict[str, Any]]:
    """Run the suite in-process and return one record per failure."""
    import pytest

    collector = _Collector()
    pytest.main(
        ["-q", "--no-header", "-p", "no:randomly", "--tb=long", *(paths or ["tests"])],
        plugins=[collector],
    )
    return collector.rows


def main() -> int:
    report = taxonomy(collect())
    OUTPUT.write_bytes(
        json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    for name in (A, B, C, D):
        print(f"  {name}: {report['counts'][name]:>3}")
    print("-" * 60)
    print(f"{report['failures_examined']} failures examined")
    print(f"D == 0: {report['freeze_condition_met']}")
    for row in report["rows"]:
        if row["category"] == D:
            print(f"  D  {row['nodeid']}\n     {row['why']}")
    print(f"written to {OUTPUT.relative_to(REPO).as_posix()}")
    return 0 if report["freeze_condition_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
