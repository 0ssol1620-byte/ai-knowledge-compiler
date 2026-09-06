#!/usr/bin/env python3
"""H1-L extension -- the future-path facet the main harness never measured.

The frozen semantic contract lists "next-revision lineage" as a facet of the
observable footprint. `run_exactness.py` does not compute it: its footprint stops
at the current revision's rows, seeds and impact set. A summary table then
described CERTIFIED_SPARSE as preserving future-path exactness, which **nothing
had measured**. This closes that gap.

Why the facet matters, and why it is not implied by the current-revision result.
An AMBIGUOUS decision carries `logical_id=None`, so the following revision seeds
a fresh identity rather than continuing an existing one. That is the mechanism by
which H1-E's 8 residual divergences became H1-E2's 8/8 divergences one revision
later. A policy can therefore agree on revision N and disagree on revision N+1,
and only measuring N+1 distinguishes the two.

Method: run revision 1 under both policies, build each policy's own revision-2
`previous` set from *its own* revision-1 outcome, run revision 2, and compare.
Building revision 2 from each policy's own output is the whole point -- feeding
both the same revision-2 inputs would erase the divergence being tested.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalUnitFingerprint,
    MatchingPolicy,
    assign_one_to_one,
)
from certified_sparse import Stats, assign_certified_sparse  # noqa: E402
from run_exactness import corpus, footprint  # noqa: E402


def legacy(inc, prev):
    return assign_one_to_one(
        list(inc), list(prev), resolver=LogicalIdentityResolver(),
        policy=MatchingPolicy.LEGACY,
    )


def sparse(inc, prev):
    decisions, _ = assign_certified_sparse(
        list(inc), list(prev), resolver=LogicalIdentityResolver(), stats=Stats()
    )
    return decisions


def carry_forward(incoming, decisions) -> list[LogicalUnitFingerprint]:
    """Revision N+1's `previous` set, built from revision N's outcome.

    A MATCHED unit carries the continued logical id. A NEW unit carries its seed.
    An AMBIGUOUS unit has no id, so it seeds a fresh one -- which is exactly the
    lineage fork this experiment exists to detect.
    """
    out = []
    for unit, d in zip(incoming, decisions, strict=False):
        lid = d.logical_id if d.logical_id is not None else f"fresh::{unit.logical_id}"
        out.append(
            LogicalUnitFingerprint.of(
                logical_id=lid,
                text=unit.raw_text if hasattr(unit, "raw_text") else unit.normalized_text,
                document_path=unit.document_path,
                anchor=unit.anchor,
                source_lineage=getattr(unit, "source_lineage", "") or "",
                previous_anchor=getattr(unit, "previous_anchor", "") or "",
                next_anchor=getattr(unit, "next_anchor", "") or "",
                geometry_style=getattr(unit, "geometry_style", "") or "",
            )
        )
    return out


def perturb(units) -> list[LogicalUnitFingerprint]:
    """A small revision-2 edit, identical for both policies."""
    out = []
    for i, u in enumerate(units):
        text = (u.normalized_text or "") + (" amended" if i % 2 == 0 else "")
        out.append(
            LogicalUnitFingerprint.of(
                logical_id=f"r2_{i}",
                text=text,
                document_path=u.document_path,
                anchor=u.anchor,
                source_lineage=getattr(u, "source_lineage", "") or "",
                previous_anchor=getattr(u, "previous_anchor", "") or "",
                next_anchor=getattr(u, "next_anchor", "") or "",
                geometry_style=getattr(u, "geometry_style", "") or "",
            )
        )
    return out


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    exp = HERE.parent
    out = exp / "receipts" / "future-path-exactness-2026-08-19.json"

    cases = corpus()
    rev1_divergences = 0
    rev2_divergences = 0
    compared = 0
    examples: list[dict[str, Any]] = []
    fork_cases: list[str] = []

    for case in cases:
        inc, prev = case["incoming"], case["previous"]
        d_leg, d_spa = legacy(inc, prev), sparse(inc, prev)
        if footprint(d_leg, prev) != footprint(d_spa, prev):
            rev1_divergences += 1

        # each policy's own revision-2 previous set
        prev2_leg = carry_forward(inc, d_leg)
        prev2_spa = carry_forward(inc, d_spa)
        if [u.logical_id for u in prev2_leg] != [u.logical_id for u in prev2_spa]:
            fork_cases.append(case["name"])

        inc2 = perturb(inc)
        f_leg = footprint(legacy(inc2, prev2_leg), prev2_leg)
        f_spa = footprint(sparse(inc2, prev2_spa), prev2_spa)
        compared += 1
        if f_leg != f_spa:
            rev2_divergences += 1
            if len(examples) < 5:
                examples.append(
                    {
                        "case": case["name"],
                        "legacy_rev2": f_leg["rows"][:3],
                        "sparse_rev2": f_spa["rows"][:3],
                    }
                )

    exact = rev1_divergences == 0 and rev2_divergences == 0
    receipt: dict[str, Any] = {
        "schema": "tavonel.certified-sparse-future-path.v1",
        "experiment": "H1-L-CERTIFIED-SPARSE-MATCHER-01",
        "extension_of": "receipts/exactness-2026-08-19.json",
        "generated_at": datetime.now(UTC).isoformat(),
        "closes_gap": (
            "The frozen semantic contract lists next-revision lineage as a facet. "
            "run_exactness.py never computed it, yet a summary table described "
            "future-path exactness as preserved. Nothing had measured it."
        ),
        "method": (
            "Run revision 1 under both policies; build each policy's OWN revision-2 "
            "previous set from its own revision-1 logical ids, seeding a fresh id "
            "wherever a decision was unresolved; apply the same revision-2 edit to "
            "both; compare the revision-2 footprints."
        ),
        "why_each_policy_carries_its_own_state": (
            "Feeding both policies the same revision-2 inputs would erase the "
            "divergence under test. The fork is created by the identifiers "
            "revision 1 assigned."
        ),
        "cases": len(cases),
        "comparisons": compared,
        "revision_1_divergences": rev1_divergences,
        "revision_2_divergences": rev2_divergences,
        "cases_with_differing_carry_forward_ids": fork_cases,
        "divergence_examples": examples,
        "future_path_exact": exact,
        "result": "FUTURE_PATH_EXACT" if exact else "FUTURE_PATH_DIVERGENT",
        "instrument_note": (
            "This harness inherits its separating power from the main H1-L run, "
            "whose three mutants separated on 10, 15 and 17 cases using the same "
            "footprint function. It adds no mutants of its own, and a reader who "
            "rejects that inheritance should treat the null as unvalidated."
        ),
        "identity_module_modified": False,
        "blocked_policy_executed": False,
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"result: {receipt['result']}")
    print(f"  cases:                 {len(cases)}")
    print(f"  revision-1 divergences: {rev1_divergences}")
    print(f"  revision-2 divergences: {rev2_divergences}")
    print(f"  differing carry-forward: {len(fork_cases)}")
    print(f"wrote {out}")
    return 0 if exact else 1


if __name__ == "__main__":
    raise SystemExit(main())
