#!/usr/bin/env python3
"""Register H1-I (gate-ordering ablation) in the claim-evidence registry.

Appends one claim rather than rewriting the file, for the same reason
sync_20260819_new_evidence.py does: unrelated rows and their receipt paths must
survive untouched.

The claim registered here is a **narrowing** result. It records that the
ordering limitation was measured and withdrawn, not that a mechanism was
validated. A registry that only grows with successes is not a registry.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs" / "ip" / "claim-evidence-matrix.yaml"
EXP = "research/experiments/H1-I-GATE-ORDERING-01"

CLAIM: dict[str, Any] = {
    "id": "B-GATE-ORDERING-NOT-LOAD-BEARING",
    "title": (
        "The promotion gate's four checks are mutually independent, so their "
        "order does not change whether a candidate state is admitted"
    ),
    "scope": (
        "controlled: 6 constructed candidate states x all 24 orders of the four "
        "checks = 144 evaluations, CPU-local, deterministic, $0"
    ),
    "paper_section": "B. Atomic Promotion / Gate composition",
    "patent": "Family B, claim B1 element 7 - narrowed by this result",
    "permitted_wording": (
        "Permuting the four promotion-gate checks over six constructed candidate "
        "states produced no change in the admit/refuse verdict in any of 144 "
        "evaluations, on a harness whose positive control diverged on 12 of 24 "
        "orders. The checks are mutually independent, and the claim's ordering "
        "limitation was narrowed accordingly."
    ),
    "forbidden_wording": [
        "the ordering of the gate checks is essential",
        "the ordered sequence of checks is what prevents promotion of a stale state",
        "ordering was validated",
        "any citation of the attempt-2 null without the positive control that "
        "made it citable",
    ],
    "claim": (
        "The promotion gate's four checks are mutually independent: each is "
        "evaluated against the candidate state rather than another check's "
        "output, so the order in which they run does not change whether a "
        "candidate state is admitted. The order controls which refusal is "
        "reported, not whether one occurs."
    ),
    "status": "EMPIRICALLY_VALIDATED_CONTROLLED",
    "evidence": [
        {
            "path": f"{EXP}/receipts/gate-ordering-permutation-2026-08-19.json",
            "asserts": [
                {"pointer": "/result", "equals": "ORDERING_NOT_LOAD_BEARING_FOR_VERDICT"},
                {"pointer": "/fidelity_gate/all_agree", "equals": True},
                {"pointer": "/total_evaluations", "equals": 144},
                {"pointer": "/E1_verdict_divergence_count", "equals": 0},
                {"pointer": "/instrument_separates", "equals": True},
                {"pointer": "/null_is_citable", "equals": True},
                {"pointer": "/positive_control/divergence_count", "equals": 12},
                {"pointer": "/external_gpu_cost_usd", "equals": 0.0},
            ],
        },
        {"path": f"{EXP}/PROTOCOL_2026-08-19.md"},
        {"path": f"{EXP}/AMENDMENT_1_2026-08-19.md"},
        {"path": f"{EXP}/receipts/gate-ordering-attempt1-void-2026-08-19.json"},
        {"path": f"{EXP}/receipts/gate-ordering-attempt2-nonseparating-2026-08-19.json"},
    ],
    "limitations": [
        (
            "This NARROWS a claim rather than supporting one. Claim B1 element 7 "
            "recited an 'ordered sequence of checks'; the protocol froze, before "
            "execution, the rule that a null result requires narrowing. It "
            "returned null, and element 7 now recites 'mutually independent' "
            "checks. Defending the ordering limitation on this null is prohibited "
            "by the protocol that produced it."
        ),
        (
            "The result supports 'order cannot affect the verdict BECAUSE the "
            "checks are independent'. It says nothing about a gate whose checks "
            "consumed one another's output; that would be a different system."
        ),
        (
            "Attempt 1 was voided by the harness fidelity gate - the harness "
            "paraphrased an internal against the wrong channel API and admitted a "
            "state the real gate refuses. Retained unedited."
        ),
        (
            "Attempt 2 passed fidelity but its permutation arm could not separate "
            "by construction, the same defect recorded for the H1-E null arm. Its "
            "null was not citable until Amendment 1's positive control showed the "
            "harness detects ordering effects when they exist (12 of 24 orders)."
        ),
        (
            "Six constructed states, each failing exactly one check. Multi-failure "
            "states were excluded by the frozen protocol as non-discriminating. "
            "The cause-divergence endpoint is therefore also non-separating and is "
            "reported, not interpreted."
        ),
    ],
}


def main() -> int:
    text = REGISTRY.read_text(encoding="utf-8")
    if f"- id: {CLAIM['id']}" in text:
        print(f"already registered: {CLAIM['id']}")
        return 0
    dumped = yaml.safe_dump(
        [CLAIM], sort_keys=False, allow_unicode=True, width=100,
        default_flow_style=False,
    ).rstrip()
    block = "\n".join("  " + line for line in dumped.splitlines()) + "\n"
    if not text.endswith("\n"):
        text += "\n"
    REGISTRY.write_text(text + block, encoding="utf-8")
    print(f"registered {CLAIM['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
