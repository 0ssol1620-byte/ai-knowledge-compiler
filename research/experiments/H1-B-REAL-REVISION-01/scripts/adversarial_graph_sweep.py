#!/usr/bin/env python3
"""B-EQUIV under adversarial dependency graphs and shape changes.

Everything measured so far used one graph topology: artifacts depending directly
on units, one hop, no cycles. That is the easy case, and equivalence holding
there says little about equivalence holding where dependencies chain, loop, or
mix channels on the same artifact.

The primary criterion here is **equivalence**, not safety:

    PRECISE selective result == independent full rebuild, artifact by artifact

A case where the planner leaves an artifact stale and the promotion gate blocks
the run is an equivalence FAILURE that was contained. It is not a pass, and it
is not counted as one -- that conflation is exactly how a weak B-EQUIV would
look strong.

Topologies:

    direct              artifacts depend on units only (the baseline so far)
    multi_hop           artifact -> artifact -> unit, three deep
    artifact_to_artifact  a summary artifact over other artifacts
    cyclic              two artifacts depending on each other
    mixed_channel       one artifact declaring SEMANTIC and STRUCTURAL together
    partial_edges       half the real dependencies are simply not declared
    stale_declaration   a declaration that was correct for a previous revision

Shape-change classes, layered on top of the text-change classes:

    block_count, heading_hierarchy, table_shape, figure_order, unit_reorder

and `unresolved_plus_structural`, which fires an ambiguous identity and a shape
change in the same revision -- the combination that produced the original
Family B defect.
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
from akc_cir.semantic_diff import (  # noqa: E402
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)
from change_space_sweep import canonical_sha256, text_for  # noqa: E402

TOPOLOGIES = (
    "direct",
    "multi_hop",
    "artifact_to_artifact",
    "cyclic",
    "mixed_channel",
    "partial_edges",
    "stale_declaration",
)

SHAPE_CLASSES = (
    "text_only",
    "block_count",
    "heading_hierarchy",
    "table_shape",
    "figure_order",
    "unit_reorder",
    "unresolved_plus_structural",
)

SEM = frozenset({DependencyChannel.SEMANTIC})
STRUCT = frozenset({DependencyChannel.STRUCTURAL})
BOTH = frozenset({DependencyChannel.SEMANTIC, DependencyChannel.STRUCTURAL})


def make_shape(
    *,
    blocks: int,
    headings: tuple[str, ...],
    tables: tuple[tuple[int, int], ...],
    figures: tuple[str, ...],
    order: tuple[str, ...] = (),
) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset({(h,) for h in headings}),
        block_count=blocks,
        table_shapes=tables,
        figure_refs=frozenset(figures),
        unit_order=order,
    )


def build_case(rng: random.Random, shape_class: str) -> dict[str, Any]:
    """A revision pair whose text change and shape change are both known."""
    used: set[str] = set()
    n = rng.randint(3, 6)
    before = [UnitSnapshot(logical_id=f"ku_{i}", text=text_for(rng, i, used)) for i in range(n)]
    after = list(before)
    order_after = [u.logical_id for u in after]

    blocks = n
    headings: tuple[str, ...] = ("Intro", "Body")
    tables: tuple[tuple[int, int], ...] = ((2, 3),)
    figures: tuple[str, ...] = ("fig1",)
    b_blocks, b_head, b_tab, b_fig = blocks, headings, tables, figures

    if shape_class == "text_only":
        i = rng.randrange(n)
        after = list(before)
        after[i] = UnitSnapshot(logical_id=before[i].logical_id, text=text_for(rng, i + 100, used))
        order_after = [u.logical_id for u in after]
    elif shape_class == "block_count":
        blocks = b_blocks + rng.randint(1, 3)
    elif shape_class == "heading_hierarchy":
        headings = ("Intro", "Body", "Appendix")
    elif shape_class == "table_shape":
        tables = ((2, 4),)
    elif shape_class == "figure_order":
        figures = ("fig1", "fig2")
    elif shape_class == "unit_reorder":
        after = list(reversed(before))
        order_after = [u.logical_id for u in after]
    elif shape_class == "unresolved_plus_structural":
        shared = text_for(rng, 300, used)
        twin = UnitSnapshot(logical_id="ku_twin", text=shared)
        before = [UnitSnapshot(logical_id="ku_left", text=shared), twin, *before]
        after = [UnitSnapshot(logical_id="ku_new", text=text_for(rng, 301, used)), *before[2:]]
        b_blocks = len(before)
        blocks = len(after) + 2
        order_after = [u.logical_id for u in after]

    return {
        "before": before,
        "after": after,
        "before_shape": make_shape(
            blocks=b_blocks,
            headings=b_head,
            tables=b_tab,
            figures=b_fig,
            order=tuple(u.logical_id for u in before),
        ),
        "after_shape": make_shape(
            blocks=blocks,
            headings=headings,
            tables=tables,
            figures=figures,
            order=tuple(order_after),
        ),
        "before_facts": {
            "blocks": b_blocks,
            "headings": b_head,
            "tables": b_tab,
            "figures": b_fig,
            "order": [u.logical_id for u in before],
        },
        "after_facts": {
            "blocks": blocks,
            "headings": headings,
            "tables": tables,
            "figures": figures,
            "order": order_after,
        },
    }


def build_model(
    units: list[str], topology: str
) -> tuple[DependencyGraph, dict[str, tuple[str, ...]], dict[str, tuple[str, ...]], set[str]]:
    """Returns (declared graph, TRUE unit inputs, TRUE artifact inputs, shape-dependent set).

    `dependencies` is ground truth -- what each artifact really consumes. The
    graph is what was *declared*, and under `partial_edges` and
    `stale_declaration` the two deliberately disagree.
    """
    unit_inputs: dict[str, tuple[str, ...]] = {}
    artifact_inputs: dict[str, tuple[str, ...]] = {}
    shape_dependent: set[str] = set()
    edges: list[DependencyEdge] = []

    for unit in units:
        art = f"artifact:section:{unit}"
        unit_inputs[art] = (unit,)
        artifact_inputs[art] = ()
        edges.append(DependencyEdge(art, unit, EdgeType.DEPENDS_ON, channels=SEM))

    index = "artifact:index:doc"
    unit_inputs[index] = tuple(units)
    artifact_inputs[index] = ()
    shape_dependent.add(index)
    for unit in units:
        edges.append(DependencyEdge(index, unit, EdgeType.DEPENDS_ON, channels=BOTH))

    if topology in ("multi_hop", "artifact_to_artifact", "cyclic"):
        digest = "artifact:digest:doc"
        unit_inputs[digest] = ()
        artifact_inputs[digest] = (index,)
        shape_dependent.add(digest)
        edges.append(DependencyEdge(digest, index, EdgeType.DEPENDS_ON, channels=BOTH))
        if topology == "multi_hop":
            top = "artifact:report:doc"
            unit_inputs[top] = ()
            artifact_inputs[top] = (digest,)
            shape_dependent.add(top)
            edges.append(DependencyEdge(top, digest, EdgeType.DEPENDS_ON, channels=BOTH))
        if topology == "cyclic":
            # index also consumes digest: a genuine cycle, not a diamond.
            artifact_inputs[index] = (digest,)
            edges.append(DependencyEdge(index, digest, EdgeType.DEPENDS_ON, channels=BOTH))

    if topology == "mixed_channel":
        mixed = "artifact:mixed:doc"
        unit_inputs[mixed] = tuple(units)
        artifact_inputs[mixed] = ()
        shape_dependent.add(mixed)
        for unit in units:
            edges.append(DependencyEdge(mixed, unit, EdgeType.DEPENDS_ON, channels=BOTH))

    if topology == "partial_edges":
        # Half the index's real inputs are never declared.
        edges = [e for e in edges if not (e.source_id == index and units.index(e.target_id) % 2)]
    if topology == "stale_declaration":
        # Declared against a previous revision: names a unit that no longer
        # exists and omits one that does.
        edges = [e for e in edges if not (e.source_id == index and e.target_id == units[-1])]
        edges.append(DependencyEdge(index, "ku_gone", EdgeType.DEPENDS_ON, channels=BOTH))

    return DependencyGraph(edges), unit_inputs, artifact_inputs, shape_dependent


def compute_hashes(
    order: list[str],
    unit_inputs: dict[str, tuple[str, ...]],
    artifact_inputs: dict[str, tuple[str, ...]],
    shape_dependent: set[str],
    texts: dict[str, str],
    facts: dict[str, Any],
) -> dict[str, str]:
    """Ground truth, resolved to a fixed point so cycles terminate."""
    hashes = {a: "seed" for a in unit_inputs}
    for _ in range(len(unit_inputs) + 2):
        updated = {}
        for art in unit_inputs:
            payload: dict[str, Any] = {
                "units": [{"id": u, "t": texts.get(u, "<ABSENT>")} for u in unit_inputs[art]],
                "arts": [hashes[a] for a in artifact_inputs[art]],
            }
            if art in shape_dependent:
                payload["shape"] = {
                    "blocks": facts["blocks"],
                    "headings": list(facts["headings"]),
                    "tables": [list(t) for t in facts["tables"]],
                    "figures": list(facts["figures"]),
                    "order": facts["order"],
                }
            updated[art] = canonical_sha256(payload)
        if updated == hashes:
            break
        hashes = updated
    return hashes


def run_case(case: dict[str, Any], topology: str) -> dict[str, Any]:
    units = sorted({u.logical_id for u in case["before"]} | {u.logical_id for u in case["after"]})
    graph, unit_inputs, artifact_inputs, shape_dependent = build_model(units, topology)
    inventory = sorted(unit_inputs)

    before_texts = {u.logical_id: u.text for u in case["before"]}
    after_texts = {u.logical_id: u.text for u in case["after"]}
    before_hashes = compute_hashes(
        [], unit_inputs, artifact_inputs, shape_dependent, before_texts, case["before_facts"]
    )
    after_hashes = compute_hashes(
        [], unit_inputs, artifact_inputs, shape_dependent, after_texts, case["after_facts"]
    )
    genuinely_changed = {a for a in inventory if before_hashes[a] != after_hashes[a]}

    diff = diff_documents(
        before_sha256=canonical_sha256([before_texts, case["before_facts"]]),
        after_sha256=canonical_sha256([after_texts, case["after_facts"]]),
        level=DiffLevel.SEMANTIC,
        before_shape=case["before_shape"],
        after_shape=case["after_shape"],
        before_units=case["before"],
        after_units=case["after"],
        source="adversarial-graph",
    )
    plan = plan_recompilation(
        diff=diff, graph=graph, artifacts=inventory, structural_policy=StructuralPolicy.PRECISE
    )
    planned = set(plan.to_rebuild)
    escaped = genuinely_changed - planned

    current = [t.artifact_id for t in plan.targets if t.state is ArtifactState.CURRENT]

    def fingerprints(
        texts: dict[str, str], facts: dict[str, Any], hashes: dict[str, str]
    ) -> dict[str, str]:
        unit_h = {k: canonical_sha256(v) for k, v in texts.items()}
        out = {}
        for a in current:
            # From the build record: the real inputs, including upstream
            # artifacts and shape facts where the builder consumed them.
            combined = dict(unit_h)
            for upstream in artifact_inputs[a]:
                combined[upstream] = hashes[upstream]
            structural = (
                {k: str(facts[k]) for k in ("blocks", "headings", "tables", "figures", "order")}
                if a in shape_dependent
                else None
            )
            out[a] = artifact_input_fingerprint(
                (*unit_inputs[a], *artifact_inputs[a]), combined, structural=structural
            )
        return out

    gate = evaluate_promotion_gate(
        diff=diff,
        graph=graph,
        plan=plan,
        rebuilt=sorted(planned),
        current_input_fingerprints=fingerprints(after_texts, case["after_facts"], after_hashes),
        expected_input_fingerprints=fingerprints(before_texts, case["before_facts"], before_hashes),
        structural_coverage=[a for a in current if a in shape_dependent],
    )
    return {
        "equivalent": not escaped,
        "escape_artifacts": len(escaped),
        "has_escape": bool(escaped),
        "promotable": gate.promotable,
        "stale_promoted": len(escaped) if gate.promotable else 0,
        "changed": len(genuinely_changed),
        "rebuilt": len(planned),
        "false_invalidated": len(planned - genuinely_changed),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-per-cell", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cells: dict[str, dict[str, Any]] = {}
    for topology in TOPOLOGIES:
        rng = random.Random(args.seed)  # noqa: S311 -- case generation, not crypto
        counter: Counter = Counter()
        per_shape: dict[str, dict[str, int]] = {}
        for shape_class in SHAPE_CLASSES:
            sub: Counter = Counter()
            for _ in range(args.cases_per_cell):
                row = run_case(build_case(rng, shape_class), topology)
                for key in ("escape_artifacts", "changed", "rebuilt", "false_invalidated",
                            "stale_promoted"):
                    sub[key] += row[key]
                sub["cases"] += 1
                sub["equivalent_cases"] += int(row["equivalent"])
                sub["escape_cases"] += int(row["has_escape"])
                sub["blocked_escape_cases"] += int(row["has_escape"] and not row["promotable"])
            per_shape[shape_class] = dict(sub)
            for key, value in sub.items():
                counter[key] += value
        cells[topology] = {"total": dict(counter), "by_shape_class": per_shape}

    receipt = {
        "schema": "tavonel.adversarial-graph-sweep.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "cases_per_cell": args.cases_per_cell,
        "topologies": list(TOPOLOGIES),
        "shape_classes": list(SHAPE_CLASSES),
        "cells": cells,
        "primary_criterion": (
            "equivalence: the PRECISE selective result must equal an independent "
            "full rebuild artifact by artifact. A contained failure -- planner "
            "leaves an artifact stale, gate blocks the run -- is an equivalence "
            "FAILURE that was contained, and is not counted as a pass."
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    header = (
        f"  {'topology':22}{'cases':>7}{'EQUIV':>8}{'esc.case':>10}"
        f"{'blocked':>9}{'STALE-PROM':>12}{'rebuilt':>9}{'needed':>8}"
    )
    print(header)
    for topology in TOPOLOGIES:
        t = cells[topology]["total"]
        print(
            f"  {topology:22}{t['cases']:>7}{t['equivalent_cases']:>8}{t['escape_cases']:>10}"
            f"{t['blocked_escape_cases']:>9}{t['stale_promoted']:>12}{t['rebuilt']:>9}{t['changed']:>8}"
        )
    print("\n  failing (topology, shape class) cells:")
    any_fail = False
    for topology in TOPOLOGIES:
        for shape_class, sub in cells[topology]["by_shape_class"].items():
            if sub["equivalent_cases"] != sub["cases"]:
                any_fail = True
                print(
                    f"    {topology:22}{shape_class:28}"
                    f"{sub['equivalent_cases']}/{sub['cases']} equivalent, "
                    f"{sub['stale_promoted']} stale promoted"
                )
    if not any_fail:
        print("    none")
    print(f"\nreceipt: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
