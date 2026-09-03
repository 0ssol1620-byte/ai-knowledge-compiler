#!/usr/bin/env python3
"""H1-L extension -- the three contract facets the exactness harness did not compute.

H1-L Amendment 2 recorded that three facets of the frozen semantic contract were
never measured: the serialized semantic record, `changed_logical_ids`, and the
selective rebuild set. Two were argued to be "strongly implied" by facets that
were measured.

"Strongly implied" is the reasoning that produced the future-path overclaim (P15),
so it is not relied on. This measures all three.

Adding facets to a comparison can only reveal divergence, never hide it, so this
extension is safe to run after the fact: if the earlier zero was an artifact of a
narrow footprint, this is what exposes it.
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

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType  # noqa: E402
from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    MatchingPolicy,
    assign_one_to_one,
)
from akc_cir.recompilation import plan_recompilation  # noqa: E402
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeKind,
    DiffLevel,
    SemanticChange,
    SemanticDiff,
)
from certified_sparse import Stats, assign_certified_sparse  # noqa: E402
from run_exactness import corpus  # noqa: E402


def diff_from(decisions, incoming) -> SemanticDiff:
    """Rebuild the diff the way semantic_diff.py does for each decision kind."""
    changes = []
    for unit, d in zip(incoming, decisions, strict=False):
        if d.logical_id is None:
            changes.append(
                SemanticChange(
                    kind=ChangeKind.IDENTITY_UNRESOLVED,
                    logical_id=unit.logical_id,
                    detail=d.reason,
                    candidates=d.candidates,
                )
            )
        elif d.match.value == "new":
            changes.append(
                SemanticChange(kind=ChangeKind.UNIT_ADDED, logical_id=d.logical_id)
            )
        else:
            changes.append(
                SemanticChange(kind=ChangeKind.MODIFIED_CLAIM, logical_id=d.logical_id)
            )
    return SemanticDiff(
        level=DiffLevel.SEMANTIC, content_changed=True,
        changes=tuple(changes), change_id="chg_full_contract",
    )


def graph_for(previous):
    return DependencyGraph(
        [
            DependencyEdge(f"artifact:from_{p.logical_id}", p.logical_id,
                           EdgeType.DEPENDS_ON)
            for p in previous
        ]
    )


def full_facets(decisions, incoming, previous) -> dict[str, Any]:
    """The three facets Amendment 2 listed as not computed."""
    diff = diff_from(decisions, incoming)
    graph = graph_for(previous)
    artifacts = [f"artifact:from_{p.logical_id}" for p in previous]
    plan = plan_recompilation(diff=diff, graph=graph, artifacts=artifacts)
    return {
        "serialized_semantic_record": [c.as_record() for c in diff.changes],
        "changed_logical_ids": sorted(diff.changed_logical_ids),
        "selective_rebuild_set": sorted(
            {"artifact": t.artifact_id, "state": t.state.value}.__repr__()
            for t in plan.targets
        ),
    }


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    exp = HERE.parent
    out = exp / "receipts" / "full-contract-exactness-2026-08-19.json"

    per_facet = {"serialized_semantic_record": 0, "changed_logical_ids": 0,
                 "selective_rebuild_set": 0}
    examples: list[dict[str, Any]] = []
    compared = 0

    for case in corpus():
        inc, prev = case["incoming"], case["previous"]
        d_leg = assign_one_to_one(
            list(inc), list(prev), resolver=LogicalIdentityResolver(),
            policy=MatchingPolicy.LEGACY,
        )
        d_spa, _ = assign_certified_sparse(
            list(inc), list(prev), resolver=LogicalIdentityResolver(), stats=Stats()
        )
        f_leg = full_facets(d_leg, inc, prev)
        f_spa = full_facets(d_spa, inc, prev)
        compared += 1
        for facet in per_facet:
            if f_leg[facet] != f_spa[facet]:
                per_facet[facet] += 1
                if len(examples) < 5:
                    examples.append(
                        {"case": case["name"], "facet": facet,
                         "legacy": f_leg[facet], "certified_sparse": f_spa[facet]}
                    )

    total = sum(per_facet.values())
    exact = total == 0
    receipt: dict[str, Any] = {
        "schema": "tavonel.certified-sparse-full-contract.v1",
        "experiment": "H1-L-CERTIFIED-SPARSE-MATCHER-01",
        "extension_of": "receipts/exactness-2026-08-19.json",
        "closes": (
            "H1-L Amendment 2 listed three contract facets as not computed: the "
            "serialized semantic record, changed_logical_ids, and the selective "
            "rebuild set. Two were argued 'strongly implied'. That reasoning "
            "produced the P15 overclaim, so it is not relied on here."
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "cases": compared,
        "divergences_per_facet": per_facet,
        "total_divergences": total,
        "divergence_examples": examples,
        "all_three_facets_exact": exact,
        "result": "FULL_CONTRACT_EXACT" if exact else "FULL_CONTRACT_DIVERGENT",
        "note_on_direction": (
            "Adding facets to a comparison can only reveal divergence, never hide "
            "it. A zero here therefore strengthens the earlier zero rather than "
            "restating it."
        ),
        "instrument_note": (
            "No mutants of its own; inherits separating power from the main H1-L "
            "run. A reader who rejects that inheritance should treat this null as "
            "unvalidated."
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
    print(f"  cases: {compared}")
    for facet, n in per_facet.items():
        print(f"  {facet:<28} divergences={n}")
    print(f"wrote {out}")
    return 0 if exact else 1


if __name__ == "__main__":
    raise SystemExit(main())
