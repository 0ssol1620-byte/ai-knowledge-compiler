#!/usr/bin/env python3
"""H1-K Amendment 1 -- is the `candidates` attribution diagnostic, or semantic?

The extraction document proposed holding a sparse replacement to classification,
logical id and future path, treating the reported candidate attribution as
secondary because LEGACY does not define it stably under exact ties.

**That proposal must not be frozen until this audit answers whether the field is
actually consumed.** "The implementation does not define it stably" and "it is
not part of the contract" are different statements, and only the second would
license dropping it from an exactness endpoint. An implementation artifact that
is nonetheless persisted and read downstream is a contract.

Q1-Q7 are answered by call-site search plus a *dynamic* end-to-end probe: the
static answer is only a list of read sites, and what matters is whether a
different attribution produces a different externally observable artifact.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType  # noqa: E402
from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalUnitFingerprint,
    MatchingPolicy,
    assign_one_to_one,
)
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeKind,
    DiffLevel,
    SemanticChange,
    SemanticDiff,
)


def rg(pattern: str) -> list[str]:
    """Call-site search, excluding tests: tests read everything by design."""
    try:
        # Fixed argv, no shell, pattern supplied by this module only.
        out = subprocess.run(  # noqa: S603 -- fixed argv, no shell
            ["git", "grep", "-n", pattern, "--", "*.py"],  # noqa: S607
            cwd=ROOT, capture_output=True, text=True, check=False,
        ).stdout
    except OSError:
        return []
    return [
        line for line in out.splitlines()
        if line.strip() and "/tests/" not in line and "test_" not in line
    ]


def unit(lid: str, text: str) -> LogicalUnitFingerprint:
    return LogicalUnitFingerprint.of(
        logical_id=lid, text=text, document_path=("Doc", "Sec"), anchor=lid,
    )


def tie_decisions(order: list[int]):
    """The equal-score tie case from the probe, with `previous` permuted."""
    prev = [unit("u1", "same text here"), unit("u2", "same text here")]
    inc = [unit("n1", "same text here")]
    return assign_one_to_one(
        inc, [prev[i] for i in order],
        resolver=LogicalIdentityResolver(), policy=MatchingPolicy.LEGACY,
    )


def diff_from_decisions(decisions) -> SemanticDiff:
    """Reproduce the IDENTITY_UNRESOLVED branch of semantic_diff.py:563-571."""
    changes = [
        SemanticChange(
            kind=ChangeKind.IDENTITY_UNRESOLVED,
            logical_id="n1",
            detail=d.reason,
            candidates=d.candidates,
        )
        for d in decisions
        if d.logical_id is None
    ]
    return SemanticDiff(
        level=DiffLevel.SEMANTIC,
        content_changed=True,
        changes=tuple(changes),
        change_id="chg_h1k",
    )


def graph() -> DependencyGraph:
    """u1 and u2 have *different* dependents, so a different seed reaches a
    different artifact. Without that the probe could not separate."""
    return DependencyGraph([
        DependencyEdge("artifact:from_u1", "u1", EdgeType.DEPENDS_ON),
        DependencyEdge("artifact:from_u2", "u2", EdgeType.DEPENDS_ON),
    ])


def impact_of_candidates(decisions) -> dict[str, Any]:
    """Seed the traversal exactly as recompilation.py:250-253 does."""
    diff = diff_from_decisions(decisions)
    seeds: list[str] = []
    for change in diff.unresolved:
        seeds.extend(change.candidates)
    report = graph().impact_of(seeds) if seeds else None
    return {
        "candidates": [list(c.candidates) for c in diff.unresolved],
        "seeds": sorted(seeds),
        "impacted_artifacts": sorted(p.node_id for p in report.affected) if report else [],
        "serialized_records": [c.as_record() for c in diff.unresolved],
    }


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    exp = Path(__file__).resolve().parents[1]
    out = exp / "receipts" / "candidates-semanticity-audit-2026-08-19.json"

    # --- static: who reads it ---
    identity_to_diff = rg("candidates=decision.candidates")
    change_candidate_reads = rg(r"change\.candidates")
    decision_candidate_reads = rg(r"decision\.candidates")
    serialization = rg(r'record\["candidates"\]')

    # --- dynamic: does a different attribution change an artifact? ---
    runs = {}
    for order in itertools.permutations(range(2)):
        decisions = tie_decisions(list(order))
        runs[str(list(order))] = impact_of_candidates(decisions)

    keys = list(runs)
    base = runs[keys[0]]
    diverging = [k for k in keys[1:] if runs[k] != base]
    impact_differs = any(
        runs[k]["impacted_artifacts"] != base["impacted_artifacts"] for k in keys[1:]
    )
    records_differ = any(
        runs[k]["serialized_records"] != base["serialized_records"] for k in keys[1:]
    )

    verdict = "CASE_B_SEMANTIC" if (impact_differs or records_differ) else "CASE_A_DIAGNOSTIC"

    receipt: dict[str, Any] = {
        "schema": "tavonel.candidates-semanticity-audit.v1",
        "experiment": "H1-K-LEGACY-INVARIANT-EXTRACTION-01",
        "amendment": "AMENDMENT_1_2026-08-19.md",
        "generated_at": datetime.now(UTC).isoformat(),
        "question": (
            "Is the LEGACY resolver's `candidates` / tie attribution "
            "diagnostic-only, or is it consumed downstream and persisted?"
        ),
        "Q1_read_outside_identity_assignment": {
            "identity_decision_flows_into_semantic_change": identity_to_diff,
            "decision_candidates_read_sites": decision_candidate_reads,
            "answer": "yes" if decision_candidate_reads else "no",
        },
        "Q2_read_by_propagation_recompilation_promotion": {
            "change_candidates_read_sites": change_candidate_reads,
            "answer": "yes" if change_candidate_reads else "no",
            "note": (
                "promotion_gate seeds its changes-accounted impact traversal from "
                "change.candidates, and recompilation seeds its unresolved "
                "traversal from the same field"
            ),
        },
        "Q3_reused_as_next_revision_input": {
            "answer": "not directly; the next revision consumes logical ids. But an "
                      "unresolved identity carries logical_id=None, so the fork it "
                      "creates is mediated by classification rather than by this field",
        },
        "Q4_audit_ui_debug_only": {"answer": "no"},
        "Q5_claimed_as_observable_behaviour": {
            "answer": "not currently recited in any claim as candidate attribution",
        },
        "Q6_externally_observable_difference": {
            "runs": runs,
            "diverging_permutations": diverging,
            "impacted_artifacts_differ": impact_differs,
            "answer": "yes" if impact_differs else "no",
        },
        "Q7_serialization_replay_equivalence": {
            "serialized_by": serialization,
            "serialized_records_differ": records_differ,
            "answer": "yes" if records_differ else "no",
            "note": (
                "SemanticChange.as_record emits `candidates`, so the attribution "
                "reaches any persisted diff record and any hash taken over it"
            ),
        },
        "verdict": verdict,
        "endpoint_decision": (
            "CASE B: candidate attribution is downstream-consumed and persisted, "
            "so it MUST be part of the exactness endpoint for any replacement "
            "matcher. The extraction document's proposal to treat it as secondary "
            "is withdrawn."
            if verdict == "CASE_B_SEMANTIC"
            else "CASE A: diagnostic only."
        ),
        "instrument_separation": {
            "note": (
                "u1 and u2 are given different dependents, so a different seed "
                "reaches a different artifact. Without that the probe could not "
                "have separated and its null would be uncitable."
            ),
            "separates": impact_differs or records_differ,
        },
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"verdict: {verdict}")
    print(f"  impacted artifacts differ by permutation: {impact_differs}")
    print(f"  serialized records differ:                {records_differ}")
    for k, v in runs.items():
        print(f"  order {k}: candidates={v['candidates']} -> impacted={v['impacted_artifacts']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
