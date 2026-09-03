#!/usr/bin/env python3
"""What happens when the dependency declaration is wrong?

`StructuralPolicy.PRECISE` buys its precision from the channel declarations, so
its correctness now rests on them being honest. That is the assumption worth
attacking, and the attack is not hypothetical: declarations are written by
adapter authors, drift as artifacts change, and nothing so far has checked them.

The design question this settles is where the promotion gate gets its evidence.
If the gate asks the *declaration* whether an artifact depends on shape, then a
single under-declaration defeats the planner and the gate together -- one wrong
line, and both the traversal and the check that was supposed to catch the
traversal go quiet. That is not defence in depth; it is one defence counted
twice.

So the fingerprint here is built from **what the builder recorded consuming**,
not from what the graph declares. The builder knows it read the block count
because it read it. That makes the two layers independent:

    planner precision   <- declarations   (may be wrong; costs correctness)
    promotion safety    <- recorded build inputs   (independent; costs nothing)

The mutations below each corrupt the declaration in a different direction while
ground truth -- the artifact's real hash function -- is held fixed. A stale
artifact reaching CURRENT is expected under several of them. A stale artifact
being *promoted* is not, under any of them.
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
from akc_cir.semantic_diff import DiffLevel, DocumentShape, diff_documents  # noqa: E402
from change_space_sweep import (  # noqa: E402
    CLASSES,
    build_case,
    canonical_sha256,
)

#: Each mutation corrupts the declaration only. The hash functions in
#: `artifact_bytes` never change, so ground truth is untouched.
MUTATIONS = (
    "honest",
    "structural_declared_as_semantic",  # under-declaration: the dangerous one
    "semantic_declared_as_structural",  # over-declaration in the other direction
    "channel_omitted",  # declares neither
    "over_declared_all",  # the current default: everything depends on everything
    "edge_missing",  # the artifact has no edges at all
)

ORDERED = "artifact:reading-order:doc"


def artifact_bytes(
    inputs: tuple[str, ...], texts: dict[str, str], present: list[str], blocks: int, artifact: str
) -> str:
    """Ground truth. Never mutated -- this is what the builder actually produces."""
    if artifact.startswith("artifact:reading-order"):
        payload: Any = {"blocks": blocks, "order": [u for u in present if u in inputs]}
    else:
        payload = {"units": [{"id": i, "text": texts.get(i, "<ABSENT>")} for i in inputs]}
    return canonical_sha256(payload)


def recorded_build_inputs(
    artifact: str, present: list[str], blocks: int, *, from_declaration: bool = False
) -> dict[str, Any] | None:
    """What the builder recorded reading, independent of any declaration.

    This is the point of the whole experiment. The reading-order builder read
    the block count and the order, so it records them; a section builder read
    neither, so it records nothing structural. Nothing here consults the graph.
    """
    if from_declaration:
        # The falsification arm: the shape facts are supplied only when the
        # declaration claims a structural dependency. Under-declare, and the
        # payload disappears along with the check that would have caught it.
        return None
    if artifact.startswith("artifact:reading-order"):
        return {"blocks": blocks, "order": present}
    return None


def build_graph(
    units: list[str], mutation: str
) -> tuple[DependencyGraph, dict[str, tuple[str, ...]]]:
    dependencies: dict[str, tuple[str, ...]] = {}
    edges: list[DependencyEdge] = []
    for unit in units:
        artifact = f"artifact:section:{unit}"
        dependencies[artifact] = (unit,)
        channels = {DependencyChannel.SEMANTIC}
        if mutation == "semantic_declared_as_structural":
            channels = {DependencyChannel.STRUCTURAL}
        elif mutation == "channel_omitted":
            channels = {DependencyChannel.METADATA}
        elif mutation == "over_declared_all":
            channels = set(DependencyChannel)
        edges.append(
            DependencyEdge(artifact, unit, EdgeType.DEPENDS_ON, channels=frozenset(channels))
        )

    dependencies[ORDERED] = tuple(units)
    if mutation != "edge_missing":
        channels = {DependencyChannel.SEMANTIC, DependencyChannel.STRUCTURAL}
        if mutation == "structural_declared_as_semantic":
            channels = {DependencyChannel.SEMANTIC}
        elif mutation == "channel_omitted":
            channels = {DependencyChannel.METADATA}
        elif mutation == "over_declared_all":
            channels = set(DependencyChannel)
        for unit in units:
            edges.append(
                DependencyEdge(ORDERED, unit, EdgeType.DEPENDS_ON, channels=frozenset(channels))
            )
    return DependencyGraph(edges), dependencies


def shape(blocks: int) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset({("Intro",)}),
        block_count=blocks,
        table_shapes=(),
        figure_refs=frozenset(),
    )


def run_case(case: dict[str, Any], mutation: str, *, source: str) -> dict[str, Any]:
    before, after = case["before"], case["after"]
    units = sorted({u.logical_id for u in before} | {u.logical_id for u in after})
    graph, dependencies = build_graph(units, mutation)
    inventory = sorted(dependencies)

    before_texts = {u.logical_id: u.text for u in before}
    after_texts = {u.logical_id: u.text for u in after}
    before_present = [u.logical_id for u in before]
    after_present = [u.logical_id for u in after]

    before_hashes = {
        a: artifact_bytes(dependencies[a], before_texts, before_present, case["blocks"], a)
        for a in inventory
    }
    after_hashes = {
        a: artifact_bytes(dependencies[a], after_texts, after_present, case["after_blocks"], a)
        for a in inventory
    }
    genuinely_changed = {a for a in inventory if before_hashes[a] != after_hashes[a]}

    diff = diff_documents(
        # Block count belongs in the document hash. Left out, a structural-only
        # change hashes identically on both sides and the diff sees no change at
        # all -- which would make every mutation below look equally safe for the
        # wrong reason.
        before_sha256=canonical_sha256(
            [(u.logical_id, u.text) for u in before] + [case["blocks"]]
        ),
        after_sha256=canonical_sha256(
            [(u.logical_id, u.text) for u in after] + [case["after_blocks"]]
        ),
        level=DiffLevel.SEMANTIC,
        before_shape=shape(case["blocks"]),
        after_shape=shape(case["after_blocks"]),
        before_units=before,
        after_units=after,
        source="declaration-mutation",
    )
    plan = plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=inventory,
        structural_policy=StructuralPolicy.PRECISE,
    )
    planned = set(plan.to_rebuild)
    escaped = sorted(genuinely_changed - planned)

    current = [t.artifact_id for t in plan.targets if t.state is ArtifactState.CURRENT]
    unit_before = {k: canonical_sha256(v) for k, v in before_texts.items()}
    unit_after = {k: canonical_sha256(v) for k, v in after_texts.items()}

    declared_structural = {
        a
        for a in current
        if any(DependencyChannel.STRUCTURAL in e.channels for e in graph.edges_from(a))
    }

    def structural_for(artifact: str, present: list[str], blocks: int) -> dict[str, Any] | None:
        if source == "declaration":
            return (
                {"blocks": blocks, "order": present}
                if artifact in declared_structural and artifact.startswith("artifact:reading-order")
                else None
            )
        return recorded_build_inputs(artifact, present, blocks)

    def fingerprints(hashes: dict[str, str], present: list[str], blocks: int) -> dict[str, str]:
        return {
            a: artifact_input_fingerprint(
                dependencies[a], hashes, structural=structural_for(a, present, blocks)
            )
            for a in current
        }

    gate = evaluate_promotion_gate(
        diff=diff,
        graph=graph,
        plan=plan,
        rebuilt=sorted(planned),
        current_input_fingerprints=fingerprints(unit_after, after_present, case["after_blocks"]),
        expected_input_fingerprints=fingerprints(unit_before, before_present, case["blocks"]),
        # Derived from the build record, not the declaration -- so a mutated
        # declaration cannot also switch off the check that would catch it.
        structural_coverage=(
            sorted(declared_structural)
            if source == "declaration"
            else [a for a in current if recorded_build_inputs(a, after_present, 0) is not None]
        ),
    )
    return {
        # artifact-level
        "planner_escape_artifacts": len(escaped),
        "genuinely_changed_artifacts": len(genuinely_changed),
        "false_invalidated_artifacts": len(planned - genuinely_changed),
        "rebuilt_artifacts": len(planned),
        "stale_artifacts_if_promoted": len(escaped) if gate.promotable else 0,
        # case-level
        "has_escape": bool(escaped),
        "promotable": gate.promotable,
        "traversal_size": len(planned),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-per-class", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    results: dict[str, Any] = {}
    for source in ("build_record", "declaration"):
      for mutation in MUTATIONS:
        rng = random.Random(args.seed)  # noqa: S311 -- case generation, not crypto
        counter: Counter = Counter()
        for change_class in CLASSES:
            for _ in range(args.cases_per_class):
                row = run_case(build_case(rng, change_class), mutation, source=source)
                counter["cases"] += 1
                # Artifact-level and case-level counters are kept apart on
                # purpose. Mixing them in one table invites reading "1595 stale,
                # 797 blocked" as a 50% block rate, when the two numbers count
                # different things entirely.
                counter["planner_escape_artifacts"] += row["planner_escape_artifacts"]
                counter["genuinely_changed_artifacts"] += row["genuinely_changed_artifacts"]
                counter["false_invalidated_artifacts"] += row["false_invalidated_artifacts"]
                counter["rebuilt_artifacts"] += row["rebuilt_artifacts"]
                counter["stale_artifacts_in_promotable_cases"] += row["stale_artifacts_if_promoted"]
                counter["cases_with_planner_escape"] += int(row["has_escape"])
                counter["gate_blocked_cases"] += int(not row["promotable"])
                counter["gate_blocked_escape_cases"] += int(
                    row["has_escape"] and not row["promotable"]
                )
                counter["gate_blocked_clean_cases"] += int(
                    not row["has_escape"] and not row["promotable"]
                )
                counter["promotable_escape_cases"] += int(row["has_escape"] and row["promotable"])
                counter["clean_cases"] += int(not row["has_escape"])
        block = dict(counter)
        cases = block["cases"]
        clean = block["clean_cases"]
        escapes = block["cases_with_planner_escape"]
        block["rates"] = {
            # The endpoint: does a stale artifact ever reach ACTIVE?
            "artifact_level_stale_promotion_rate": (
                block["stale_artifacts_in_promotable_cases"]
                / block["genuinely_changed_artifacts"]
                if block["genuinely_changed_artifacts"]
                else 0.0
            ),
            "case_level_fail_open_rate": (
                block["promotable_escape_cases"] / escapes if escapes else 0.0
            ),
            # Sensitivity: of the cases that did go stale, how many were caught?
            "gate_sensitivity_to_escape": (
                block["gate_blocked_escape_cases"] / escapes if escapes else None
            ),
            # And the other half -- a gate that refuses everything scores a
            # perfect zero above while being useless.
            "safe_case_promotion_rate": (
                (clean - block["gate_blocked_clean_cases"]) / clean if clean else None
            ),
            "false_refusal_rate": (
                block["gate_blocked_clean_cases"] / clean if clean else None
            ),
            "promotion_coverage": (cases - block["gate_blocked_cases"]) / cases if cases else 0.0,
        }
        results[f"{source}/{mutation}"] = block

    receipt = {
        "schema": "tavonel.declaration-mutation-sweep.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "cases_per_class": args.cases_per_class,
        "mutations": list(MUTATIONS),
        "results": results,
        "the_separation_being_tested": (
            "planner precision is taken from the channel declarations and may be "
            "wrong; promotion safety is taken from what the builder recorded "
            "consuming and is independent of them. If the gate read the "
            "declaration instead, one under-declaration would silence both "
            "layers at once."
        ),
        "expected": (
            "planner staleness is expected under under-declaration and edge "
            "omission. fail_open -- a stale artifact that the gate nonetheless "
            "permitted to promote -- must be zero under every mutation."
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    header = (
        f"  {'mutation':34}{'esc.art':>9}{'esc.case':>9}{'blk.esc':>9}"
        f"{'STALE-PROMOTED':>16}{'f.refuse':>10}{'promo.cov':>11}"
    )
    for source in ("build_record", "declaration"):
        print(f"== fingerprint source: {source}   (.art = artifacts, .case = cases)")
        print(header)
        for mutation in MUTATIONS:
            v = results[f"{source}/{mutation}"]
            r = v["rates"]
            fr = "n/a" if r["false_refusal_rate"] is None else f"{r['false_refusal_rate']:.3f}"
            print(
                f"  {mutation:34}{v['planner_escape_artifacts']:>9}"
                f"{v['cases_with_planner_escape']:>9}{v['gate_blocked_escape_cases']:>9}"
                f"{v['stale_artifacts_in_promotable_cases']:>16}"
                f"{fr:>10}{r['promotion_coverage']:>11.3f}"
            )
    print(f"receipt: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
