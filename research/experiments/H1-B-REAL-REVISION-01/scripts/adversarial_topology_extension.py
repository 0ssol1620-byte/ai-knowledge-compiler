#!/usr/bin/env python3
"""Development-only Family-B topology gaps before the sealed holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.dependency import (  # noqa: E402
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.recompilation import StructuralPolicy, plan_recompilation  # noqa: E402
from akc_cir.semantic_diff import (  # noqa: E402
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)

PROTOCOL = Path(__file__).resolve().parent.parent / "ADVERSARIAL_EXTENSION_PROTOCOL_2026-08-19.md"
SEED = 2026081907
CASES = 200
SEM = frozenset({DependencyChannel.SEMANTIC})
STRUCT = frozenset({DependencyChannel.STRUCTURAL})


def sha256_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    )


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def edge(source: str, target: str, channels: frozenset[DependencyChannel]) -> DependencyEdge:
    return DependencyEdge(source, target, EdgeType.DEPENDS_ON, channels=channels)


def shape(order: tuple[str, ...], blocks: int, marker: str = "base") -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset({("Body",), (marker,)}),
        block_count=blocks,
        unit_order=order,
    )


def make_diff(
    *,
    before_units: list[UnitSnapshot],
    after_units: list[UnitSnapshot],
    before_shape: DocumentShape,
    after_shape: DocumentShape,
    source: str,
) -> Any:
    return diff_documents(
        before_sha256=canonical_sha256(
            {
                "units": [(u.logical_id, u.text) for u in before_units],
                "shape": repr(before_shape),
            }
        ),
        after_sha256=canonical_sha256(
            {
                "units": [(u.logical_id, u.text) for u in after_units],
                "shape": repr(after_shape),
            }
        ),
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=source,
    )


def hash_artifact(
    artifact: str,
    *,
    unit_inputs: tuple[str, ...],
    artifact_inputs: tuple[str, ...],
    unit_text: dict[str, str],
    artifact_hashes: dict[str, str],
    structural_marker: str | None = None,
) -> str:
    return canonical_sha256(
        {
            "artifact": artifact,
            "units": [(unit, unit_text.get(unit, "<ABSENT>")) for unit in unit_inputs],
            "artifacts": [(up, artifact_hashes[up]) for up in artifact_inputs],
            "structure": structural_marker,
        }
    )


def full_build(
    order: list[str],
    unit_inputs: dict[str, tuple[str, ...]],
    artifact_inputs: dict[str, tuple[str, ...]],
    unit_text: dict[str, str],
    structural_markers: dict[str, str],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for artifact in order:
        hashes[artifact] = hash_artifact(
            artifact,
            unit_inputs=unit_inputs[artifact],
            artifact_inputs=artifact_inputs[artifact],
            unit_text=unit_text,
            artifact_hashes=hashes,
            structural_marker=structural_markers.get(artifact),
        )
    return hashes


def run_model(
    *,
    graph: DependencyGraph,
    order: list[str],
    unit_inputs: dict[str, tuple[str, ...]],
    artifact_inputs: dict[str, tuple[str, ...]],
    structural_artifacts: set[str],
    before_units: list[UnitSnapshot],
    after_units: list[UnitSnapshot],
    before_shape: DocumentShape,
    after_shape: DocumentShape,
    before_marker: str,
    after_marker: str,
    source: str,
) -> dict[str, Any]:
    before_text = {u.logical_id: u.text for u in before_units}
    after_text = {u.logical_id: u.text for u in after_units}
    before_struct = {artifact: before_marker for artifact in structural_artifacts}
    after_struct = {artifact: after_marker for artifact in structural_artifacts}
    before_hashes = full_build(
        order, unit_inputs, artifact_inputs, before_text, before_struct
    )
    after_hashes = full_build(order, unit_inputs, artifact_inputs, after_text, after_struct)
    genuinely_changed = {
        artifact for artifact in order if before_hashes[artifact] != after_hashes[artifact]
    }
    diff = make_diff(
        before_units=before_units,
        after_units=after_units,
        before_shape=before_shape,
        after_shape=after_shape,
        source=source,
    )
    plan = plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=order,
        structural_policy=StructuralPolicy.PRECISE,
    )
    planned = set(plan.to_rebuild)
    escaped = genuinely_changed - planned
    false_invalidated = planned - genuinely_changed
    return {
        "equivalent": not escaped,
        "genuinely_changed": len(genuinely_changed),
        "planned": len(planned),
        "escaped": sorted(escaped),
        "false_invalidated": sorted(false_invalidated),
        "max_target_depth": max((target.depth for target in plan.targets), default=0),
        "cycles_detected": len(plan.cycles_detected),
    }


def deep_chain_case(rng: random.Random, index: int) -> dict[str, Any]:
    unit = "docA:unit:root"
    before = [UnitSnapshot(logical_id=unit, text=f"root value {rng.randrange(10**12)}")]
    after = [UnitSnapshot(logical_id=unit, text=before[0].text + f" revised {index}")]
    order = [f"artifact:chain:{depth:02d}" for depth in range(64)]
    unit_inputs = {artifact: () for artifact in order}
    artifact_inputs = {artifact: () for artifact in order}
    unit_inputs[order[0]] = (unit,)
    edges = [edge(order[0], unit, SEM)]
    for depth in range(1, len(order)):
        artifact_inputs[order[depth]] = (order[depth - 1],)
        edges.append(edge(order[depth], order[depth - 1], SEM))
    return run_model(
        graph=DependencyGraph(edges),
        order=order,
        unit_inputs=unit_inputs,
        artifact_inputs=artifact_inputs,
        structural_artifacts=set(),
        before_units=before,
        after_units=after,
        before_shape=shape((unit,), 1),
        after_shape=shape((unit,), 1),
        before_marker="same",
        after_marker="same",
        source="adversarial-extension:deep-chain",
    )


def cross_document_case(rng: random.Random, index: int) -> dict[str, Any]:
    unit_a = "docA:unit:source"
    unit_b = "docB:unit:stable"
    before = [
        UnitSnapshot(logical_id=unit_a, text=f"A {rng.randrange(10**12)}"),
        UnitSnapshot(logical_id=unit_b, text=f"B {rng.randrange(10**12)}"),
    ]
    after = [
        UnitSnapshot(logical_id=unit_a, text=before[0].text + f" revised {index}"),
        before[1],
    ]
    a = "artifact:docA:section"
    cross = "artifact:crossdoc:aggregate"
    b = "artifact:docB:derived"
    order = [a, cross, b]
    unit_inputs = {a: (unit_a,), cross: (), b: (unit_b,)}
    artifact_inputs = {a: (), cross: (a,), b: (cross,)}
    edges = [edge(a, unit_a, SEM), edge(cross, a, SEM), edge(b, cross, SEM)]
    return run_model(
        graph=DependencyGraph(edges),
        order=order,
        unit_inputs=unit_inputs,
        artifact_inputs=artifact_inputs,
        structural_artifacts=set(),
        before_units=before,
        after_units=after,
        before_shape=shape((unit_a, unit_b), 2),
        after_shape=shape((unit_a, unit_b), 2),
        before_marker="same",
        after_marker="same",
        source="adversarial-extension:cross-document",
    )


def diamond_case(rng: random.Random, index: int, change_kind: str) -> dict[str, Any]:
    unit = "doc:unit:root"
    before = [UnitSnapshot(logical_id=unit, text=f"value {rng.randrange(10**12)}")]
    after = list(before)
    before_shape = shape((unit,), 1, "base")
    after_shape = before_shape
    before_marker = "shape-v1"
    after_marker = before_marker
    if change_kind == "semantic":
        after = [UnitSnapshot(logical_id=unit, text=before[0].text + f" revised {index}")]
    elif change_kind == "structural":
        after_shape = shape((unit,), 2, "shape-v2")
        after_marker = "shape-v2"
    else:
        raise ValueError(change_kind)

    semantic_branch = "artifact:diamond:semantic"
    structural_branch = "artifact:diamond:structural"
    merge = "artifact:diamond:merge"
    order = [semantic_branch, structural_branch, merge]
    unit_inputs = {
        semantic_branch: (unit,),
        # The frozen protocol calls this branch STRUCTURAL-only. Its graph edge
        # is anchored to the unit whose document position/shape it observes,
        # but its independent oracle hash must not consume that unit's semantic
        # text. Attempt 1 did so and therefore manufactured a semantic change in
        # the structural branch; that receipt is retained and invalidated.
        structural_branch: (),
        merge: (),
    }
    artifact_inputs = {
        semantic_branch: (),
        structural_branch: (),
        merge: (semantic_branch, structural_branch),
    }
    edges = [
        edge(semantic_branch, unit, SEM),
        edge(structural_branch, unit, STRUCT),
        edge(merge, semantic_branch, SEM),
        edge(merge, structural_branch, STRUCT),
    ]
    return run_model(
        graph=DependencyGraph(edges),
        order=order,
        unit_inputs=unit_inputs,
        artifact_inputs=artifact_inputs,
        structural_artifacts={structural_branch, merge},
        before_units=before,
        after_units=after,
        before_shape=before_shape,
        after_shape=after_shape,
        before_marker=before_marker,
        after_marker=after_marker,
        source=f"adversarial-extension:diamond-{change_kind}",
    )


def accumulate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counter: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for row in rows:
        counter["cases"] += 1
        counter["equivalent_cases"] += int(row["equivalent"])
        counter["escape_cases"] += int(bool(row["escaped"]))
        counter["escape_artifacts"] += len(row["escaped"])
        counter["false_invalidated_artifacts"] += len(row["false_invalidated"])
        counter["genuinely_changed_artifacts"] += row["genuinely_changed"]
        counter["planned_artifacts"] += row["planned"]
        counter["max_target_depth"] = max(counter["max_target_depth"], row["max_target_depth"])
        if row["escaped"] and len(examples) < 5:
            examples.append(row)
    return {"totals": dict(counter), "escape_examples": examples}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rng = random.Random(SEED)  # noqa: S311 -- deterministic research cases

    cells = {
        "deep_chain_64": accumulate([deep_chain_case(rng, i) for i in range(CASES)]),
        "cross_document_dependency": accumulate(
            [cross_document_case(rng, i) for i in range(CASES)]
        ),
        "diamond_conflicting_channels_semantic": accumulate(
            [diamond_case(rng, i, "semantic") for i in range(CASES)]
        ),
        "diamond_conflicting_channels_structural": accumulate(
            [diamond_case(rng, i, "structural") for i in range(CASES)]
        ),
    }
    all_equivalent = all(
        cell["totals"].get("escape_cases", 0) == 0 for cell in cells.values()
    )
    receipt: dict[str, Any] = {
        "schema": "tavonel.family-b-adversarial-topology-extension.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": file_sha256(PROTOCOL),
        "script_sha256": file_sha256(Path(__file__)),
        "seed": SEED,
        "cases_per_cell": CASES,
        "cells": cells,
        "primary_criterion": "zero stale escapes / exact full-oracle artifact equivalence",
        "all_cells_equivalent": all_equivalent,
        "evidence_class": "development controlled topology sweep; not final holdout",
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for name, cell in cells.items():
        totals = cell["totals"]
        print(
            f"{name}: {totals.get('equivalent_cases', 0)}/{totals.get('cases', 0)} "
            f"equivalent; escapes={totals.get('escape_cases', 0)}; "
            f"max_depth={totals.get('max_target_depth', 0)}"
        )
    print(f"all cells equivalent: {all_equivalent}")
    return 0 if all_equivalent else 2


if __name__ == "__main__":
    raise SystemExit(main())
