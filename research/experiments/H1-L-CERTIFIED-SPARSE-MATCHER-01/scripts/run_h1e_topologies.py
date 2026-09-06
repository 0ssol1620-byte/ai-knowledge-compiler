#!/usr/bin/env python3
"""H1-L extension -- CERTIFIED_SPARSE against LEGACY on H1-E's own topologies.

The H1-L protocol declared, before running, that its frozen corpus did not cover
the H1-E residual cases. This closes that gap **as a separate run with its own
receipt**, rather than by editing H1-L's frozen corpus after results were seen --
which the stop rule forbids and which would be indistinguishable from tuning.

The corpora are not re-authored. `identity_shadow_equivalence.py`'s topology
generators are imported and driven with the same seed the pinned H1-E receipt
records, so these are the same distributions that produced the 8 residual
divergences that vetoed the BLOCKED policy.

Endpoint is unchanged from H1-L: the full row-attached contract footprint,
`candidates` attribution included.

BLOCKED is not executed here. The comparison is LEGACY vs CERTIFIED_SPARSE.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import random
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
    MatchingPolicy,
    assign_one_to_one,
)
from certified_sparse import Stats, assign_certified_sparse  # noqa: E402

H1E = (
    ROOT / "research" / "experiments" / "H1-E-IDENTITY-SCALABILITY-01"
    / "scripts" / "identity_shadow_equivalence.py"
)
PINNED = (
    ROOT / "research" / "experiments" / "H1-E-IDENTITY-SCALABILITY-01"
    / "receipts" / "shadow-equivalence-rerun-pinned-2026-08-19.json"
)


def load_h1e():
    spec = importlib.util.spec_from_file_location("h1e_topologies", H1E)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def footprint(decisions) -> list[dict[str, Any]]:
    """Same contract footprint H1-L uses, row-attached and ordered."""
    return [
        {
            "row": i,
            "match": d.match.value,
            "logical_id": d.logical_id,
            "candidates": list(d.candidates),
            "relation": d.relation.value if d.relation else None,
            "score": round(d.score, 9),
        }
        for i, d in enumerate(decisions)
    ]


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    exp = HERE.parent
    out = exp / "receipts" / "h1e-topology-exactness-2026-08-19.json"
    mod = load_h1e()
    pinned = json.loads(PINNED.read_text(encoding="utf-8"))
    seed = pinned["seed"]

    topologies = {
        name: getattr(mod, f"topo_{name}")
        for name in (
            "stable", "edited", "reordered", "duplicate_text_decoy",
            "shared_identifier", "split_and_merge", "near_tie",
        )
    }

    cases_per_cell = 10
    size = 20
    cells: dict[str, Any] = {}
    total_divergences = 0
    total_comparisons = 0
    examples: list[dict[str, Any]] = []

    for name, builder in topologies.items():
        divergences = 0
        compared = 0
        for case in range(cases_per_cell):
            rng = random.Random(f"{seed}:{name}:{case}")  # noqa: S311
            previous, incoming = builder(rng, size)
            base = footprint(
                assign_one_to_one(
                    list(incoming), list(previous),
                    resolver=LogicalIdentityResolver(),
                    policy=MatchingPolicy.LEGACY,
                )
            )
            got_decisions, _st = assign_certified_sparse(
                list(incoming), list(previous), resolver=LogicalIdentityResolver(),
                stats=Stats(),
            )
            got = footprint(got_decisions)
            compared += 1
            if got != base:
                divergences += 1
                if len(examples) < 5:
                    diff_rows = [
                        {"row": b["row"], "legacy": b, "certified_sparse": g}
                        for b, g in zip(base, got, strict=False)
                        if b != g
                    ]
                    examples.append(
                        {"cell": name, "case": case, "rows": diff_rows[:3]}
                    )
        cells[name] = {"cases": compared, "divergences": divergences}
        total_divergences += divergences
        total_comparisons += compared

    exact = total_divergences == 0
    receipt: dict[str, Any] = {
        "schema": "tavonel.certified-sparse-h1e-topology-exactness.v1",
        "experiment": "H1-L-CERTIFIED-SPARSE-MATCHER-01",
        "extension_of": "receipts/exactness-2026-08-19.json",
        "closes_declared_gap": (
            "The H1-L protocol section 5 declared that its frozen corpus did not "
            "cover the H1-E cases. This is a SEPARATE run with its own receipt, "
            "not an edit to that corpus."
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "topology_source": str(H1E.relative_to(ROOT)).replace("\\", "/"),
        "topology_source_sha256": "sha256:"
        + hashlib.sha256(H1E.read_bytes()).hexdigest(),
        "seed_source_receipt": str(PINNED.relative_to(ROOT)).replace("\\", "/"),
        "seed_source_receipt_sha256": pinned.get("receipt_sha256"),
        "seed": seed,
        "cases_per_cell": cases_per_cell,
        "units_per_side": size,
        "cells": cells,
        "total_comparisons": total_comparisons,
        "total_divergences": total_divergences,
        "divergence_examples": examples,
        "exact_on_h1e_topologies": exact,
        "blocked_policy_executed": False,
        "identity_module_modified": False,
        "result": "EXACT_ON_H1E_TOPOLOGIES" if exact else "DIVERGENT_ON_H1E_TOPOLOGIES",
        "scope_note": (
            "These are the same generators and seed that produced H1-E's 8 "
            "residual BLOCKED divergences, so the distributions are the ones that "
            "vetoed BLOCKED. This run does NOT reproduce those 8 specific "
            "divergences by index; it re-draws from the same seeded generators at "
            "this cell size and compares LEGACY against CERTIFIED_SPARSE."
        ),
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"result: {receipt['result']}")
    for name, c in cells.items():
        print(f"  {name:<24} cases={c['cases']:<3} divergences={c['divergences']}")
    print(f"  total: {total_divergences}/{total_comparisons}")
    print(f"wrote {out}")
    return 0 if exact else 1


if __name__ == "__main__":
    raise SystemExit(main())
