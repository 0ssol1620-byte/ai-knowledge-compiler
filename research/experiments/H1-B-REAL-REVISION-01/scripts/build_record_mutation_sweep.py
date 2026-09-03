#!/usr/bin/env python3
"""What if the build record itself is wrong?

The declaration-mutation sweep moved promotion safety off the dependency
declaration and onto what the builder recorded consuming. That removed one
assumption and created another, and this attacks the new one.

The structure of the check matters for predicting what it can catch. The gate
compares an artifact's input fingerprint **now** against the fingerprint **when
it was built**. Both are produced by the same recording code, so a corruption
present in both cancels: a builder that consistently never records the block
count produces two fingerprints that agree, and agreement is what the gate reads
as evidence of currency. A corruption present in only one -- a stale record, a
receipt from a different build -- does not cancel and shows up as a mismatch.

That predicts a split, and the point of running it is to find out whether the
split is where the reasoning says it is, and how wide it is. A trust boundary
that is named and measured is a different thing from one that is assumed.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adversarial_graph_sweep import SHAPE_CLASSES, build_case  # noqa: E402
from akc_cir.dependency import (  # noqa: E402
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.promotion_gate import (  # noqa: E402
    artifact_input_fingerprint,
    evaluate_promotion_gate,
)
from akc_cir.recompilation import (  # noqa: E402
    ArtifactState,
    StructuralPolicy,
    plan_recompilation,
)
from akc_cir.semantic_diff import DiffLevel, diff_documents  # noqa: E402
from change_space_sweep import canonical_sha256  # noqa: E402

MUTATIONS = (
    "honest",
    "structural_input_omitted",  # never records shape at all
    "semantic_input_omitted",  # never records one unit
    "wrong_block_count",  # records a constant instead of the real count
    "partial_reading_order",  # records a truncated order
    "misrecorded_order",  # records the order sorted rather than as read
    "extra_nonexistent_input",  # records an input it never read
    "stale_record_reused",  # the prior revision's record, unchanged
    "old_receipt_on_rebuilt_artifact",  # rebuilt, but the old record attached
)

INDEX = "artifact:index:doc"
BOTH = frozenset({DependencyChannel.SEMANTIC, DependencyChannel.STRUCTURAL})
SEM = frozenset({DependencyChannel.SEMANTIC})


def graph_for(
    units: list[str], declaration: str
) -> tuple[DependencyGraph, dict[str, tuple[str, ...]], set[str]]:
    """The declared graph. `under_declared` hides the index's shape dependency.

    Without a declaration error the planner leaves nothing stale, so there is no
    staleness for a bad build record to conceal and every mutation scores zero
    for the same uninformative reason. The build record is the *second* line of
    defence; it can only be tested once the first has already failed.
    """
    inputs: dict[str, tuple[str, ...]] = {}
    edges: list[DependencyEdge] = []
    for unit in units:
        art = f"artifact:section:{unit}"
        inputs[art] = (unit,)
        edges.append(DependencyEdge(art, unit, EdgeType.DEPENDS_ON, channels=SEM))
    inputs[INDEX] = tuple(units)
    index_channels = SEM if declaration == "under_declared" else BOTH
    for unit in units:
        edges.append(DependencyEdge(INDEX, unit, EdgeType.DEPENDS_ON, channels=index_channels))
    return DependencyGraph(edges), inputs, {INDEX}


def true_hash(
    artifact: str, inputs: tuple[str, ...], texts: dict[str, str], facts: dict[str, Any]
) -> str:
    """Ground truth. Never mutated."""
    payload: dict[str, Any] = {
        "units": [{"id": u, "t": texts.get(u, "<ABSENT>")} for u in inputs]
    }
    if artifact == INDEX:
        payload["shape"] = {
            "blocks": facts["blocks"],
            "order": facts["order"],
            "headings": list(facts["headings"]),
        }
    return canonical_sha256(payload)


def recorded(
    artifact: str,
    inputs: tuple[str, ...],
    facts: dict[str, Any],
    mutation: str,
    *,
    is_expected_side: bool,
    prior_facts: dict[str, Any],
) -> tuple[tuple[str, ...], dict[str, Any] | None]:
    """What the builder claims it consumed. This is what the mutations corrupt."""
    if artifact != INDEX:
        return inputs, None

    use = facts
    if mutation == "stale_record_reused":
        use = prior_facts  # both sides record the prior revision
    elif mutation == "old_receipt_on_rebuilt_artifact" and not is_expected_side:
        use = prior_facts  # only the "now" side is wrong

    structural: dict[str, Any] | None = {
        "blocks": use["blocks"],
        "order": use["order"],
        "headings": list(use["headings"]),
    }
    recorded_inputs = inputs

    if mutation == "structural_input_omitted":
        structural = None
    elif mutation == "wrong_block_count":
        structural = {**structural, "blocks": 0}
    elif mutation == "partial_reading_order":
        structural = {**structural, "order": use["order"][:1]}
    elif mutation == "misrecorded_order":
        structural = {**structural, "order": sorted(use["order"])}
    elif mutation == "semantic_input_omitted":
        recorded_inputs = inputs[:-1]
    elif mutation == "extra_nonexistent_input":
        recorded_inputs = (*inputs, "ku_phantom")
    return recorded_inputs, structural


def run_case(case: dict[str, Any], mutation: str, declaration: str) -> dict[str, Any]:
    units = sorted({u.logical_id for u in case["before"]} | {u.logical_id for u in case["after"]})
    graph, inputs, shape_dependent = graph_for(units, declaration)
    inventory = sorted(inputs)

    before_texts = {u.logical_id: u.text for u in case["before"]}
    after_texts = {u.logical_id: u.text for u in case["after"]}
    before_hashes = {
        a: true_hash(a, inputs[a], before_texts, case["before_facts"]) for a in inventory
    }
    after_hashes = {
        a: true_hash(a, inputs[a], after_texts, case["after_facts"]) for a in inventory
    }
    genuinely_changed = {a for a in inventory if before_hashes[a] != after_hashes[a]}

    diff = diff_documents(
        before_sha256=canonical_sha256([before_texts, case["before_facts"]]),
        after_sha256=canonical_sha256([after_texts, case["after_facts"]]),
        level=DiffLevel.SEMANTIC,
        before_shape=case["before_shape"],
        after_shape=case["after_shape"],
        before_units=case["before"],
        after_units=case["after"],
        source="build-record-mutation",
    )
    plan = plan_recompilation(
        diff=diff, graph=graph, artifacts=inventory, structural_policy=StructuralPolicy.PRECISE
    )
    planned = set(plan.to_rebuild)
    escaped = genuinely_changed - planned
    current = [t.artifact_id for t in plan.targets if t.state is ArtifactState.CURRENT]

    def fingerprints(
        texts: dict[str, str], facts: dict[str, Any], *, expected: bool
    ) -> dict[str, str]:
        unit_h = {k: canonical_sha256(v) for k, v in texts.items()}
        out = {}
        for a in current:
            rec_inputs, structural = recorded(
                a, inputs[a], facts, mutation,
                is_expected_side=expected, prior_facts=case["before_facts"],
            )
            out[a] = artifact_input_fingerprint(rec_inputs, unit_h, structural=structural)
        return out

    gate = evaluate_promotion_gate(
        diff=diff,
        graph=graph,
        plan=plan,
        rebuilt=sorted(planned),
        current_input_fingerprints=fingerprints(after_texts, case["after_facts"], expected=False),
        expected_input_fingerprints=fingerprints(before_texts, case["before_facts"], expected=True),
        structural_coverage=[a for a in current if a in shape_dependent],
    )
    clean = not escaped
    return {
        "escape_artifacts": len(escaped),
        "has_escape": bool(escaped),
        "promotable": gate.promotable,
        "stale_promoted": len(escaped) if gate.promotable else 0,
        "false_refusal": clean and not gate.promotable,
        "clean": clean,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-per-cell", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    results: dict[str, Any] = {}
    for declaration in ("honest", "under_declared"):
      for mutation in MUTATIONS:
        rng = random.Random(args.seed)  # noqa: S311 -- case generation, not crypto
        counter: Counter = Counter()
        for shape_class in SHAPE_CLASSES:
            for _ in range(args.cases_per_cell):
                row = run_case(build_case(rng, shape_class), mutation, declaration)
                counter["cases"] += 1
                counter["escape_artifacts"] += row["escape_artifacts"]
                counter["escape_cases"] += int(row["has_escape"])
                counter["blocked_escape_cases"] += int(row["has_escape"] and not row["promotable"])
                counter["stale_artifacts_promoted"] += row["stale_promoted"]
                counter["clean_cases"] += int(row["clean"])
                counter["false_refusal_cases"] += int(row["false_refusal"])
        results[f"{declaration}/{mutation}"] = dict(counter)

    receipt = {
        "schema": "tavonel.build-record-mutation-sweep.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "cases_per_cell": args.cases_per_cell,
        "mutations": list(MUTATIONS),
        "results": results,
        "what_is_being_tested": (
            "whether the promotion gate can detect a build record that "
            "misrepresents what the builder consumed. The gate compares the "
            "fingerprint now against the fingerprint at build time, both "
            "produced by the same recording code, so a corruption present on "
            "both sides cancels and a corruption present on one side does not."
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    header = (
        f"  {'build-record mutation':34}{'esc.art':>9}{'esc.case':>9}"
        f"{'blocked':>9}{'STALE-PROMOTED':>16}{'false refusal':>15}"
    )
    for declaration in ("honest", "under_declared"):
        print(f"== declaration: {declaration}")
        print(header)
        for mutation in MUTATIONS:
            v = results[f"{declaration}/{mutation}"]
            print(
                f"  {mutation:34}{v['escape_artifacts']:>9}{v['escape_cases']:>9}"
                f"{v['blocked_escape_cases']:>9}{v['stale_artifacts_promoted']:>16}"
                f"{v['false_refusal_cases']:>15}"
            )
    print(f"\nreceipt: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
