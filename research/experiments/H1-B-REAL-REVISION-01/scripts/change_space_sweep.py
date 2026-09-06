#!/usr/bin/env python3
"""Sweep the change space, not the corpus, and check equivalence against a full rebuild.

The real-revision corpora answer "does this work on documents we have". They
cannot answer "does this work on changes we have not seen", and that is the
question a post-hoc-fitting objection actually asks. The untouched extension
holdout makes the point: it passes, and every arm is identical on it, because no
unsettled identity occurs in those five pairs. A corpus that never triggers the
defect cannot confirm the fix.

So this enumerates the change space directly. For each generated document pair
the change class is *known by construction*:

    semantic_only     unit text changes; document shape held fixed
    structural_only   shape changes; every unit's text byte-identical
    mixed             both
    ambiguous         two prior units with identical text and one incoming --
                      the case that made the real corpus fail
    unchanged         identical bytes; nothing may be rebuilt

Ground truth is a full rebuild, computed independently of the plan. An artifact
must be rebuilt if and only if its bytes differ, and both directions are counted:
a missed rebuild is a stale artifact escaping (fail-open, the defect), and an
unnecessary rebuild is wasted work that equivalence checking cannot see.

The generator is seeded and the seed is recorded. A sweep that cannot be re-run
to the same cases is an anecdote.
"""

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
from akc_cir.promotion_gate import (  # noqa: E402
    artifact_input_fingerprint,
    evaluate_promotion_gate,
)
from akc_cir.recompilation import (  # noqa: E402
    ArtifactState,
    StructuralPolicy,
    plan_recompilation,
    verify_equivalence,
)
from akc_cir.semantic_diff import (  # noqa: E402
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)

CLASSES = ("unchanged", "semantic_only", "structural_only", "mixed", "ambiguous")

SENTENCES = [
    "The warranty period is {n} years from the date of delivery.",
    "Notice must be given within {n} days of discovery.",
    "Liability is capped at {n} times the annual fee.",
    "The service level target is {n} percent availability.",
    "Records are retained for {n} years after termination.",
]


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def text_for(rng: random.Random, seed_n: int, used: set[str] | None = None) -> str:
    """A sentence that is not byte-identical to any other in the same case.

    Uniqueness is a correctness requirement of the ground-truth model, not a
    cosmetic one. When a newly created unit happens to draw text identical to an
    existing unit, "new unit" and "continuation of the existing unit" become
    indistinguishable from the data -- the resolver settles it as a continuation,
    correctly, and the generator's own label of "new" is unrecoverable. The case
    then has no ground truth to score against, and the harness scored it anyway
    by keying an artifact on the surface id.

    Without this, `honest` reported 1 escape at seed 20260820 (ambiguous #56).
    That escape was the harness, not the system. See
    `receipts/generator-collision-correction-2026-08-19.json`.
    """
    for _ in range(64):
        candidate = SENTENCES[seed_n % len(SENTENCES)].format(n=rng.randint(1, 99))
        if used is None or candidate not in used:
            if used is not None:
                used.add(candidate)
            return candidate
    raise RuntimeError("exhausted the sentence space; widen SENTENCES or the range")


def build_case(rng: random.Random, change_class: str) -> dict[str, Any]:
    """One document pair whose change class is known because it was constructed."""
    unit_count = rng.randint(3, 8)
    used: set[str] = set()
    before = [
        UnitSnapshot(logical_id=f"ku_{i}", text=text_for(rng, i, used)) for i in range(unit_count)
    ]
    blocks = unit_count
    after = list(before)
    after_blocks = blocks

    if change_class == "semantic_only":
        index = rng.randrange(unit_count)
        after = list(before)
        after[index] = UnitSnapshot(
            logical_id=before[index].logical_id, text=text_for(rng, index + 100, used)
        )
    elif change_class == "structural_only":
        after_blocks = blocks + rng.randint(1, 3)
    elif change_class == "mixed":
        index = rng.randrange(unit_count)
        after = list(before)
        after[index] = UnitSnapshot(
            logical_id=before[index].logical_id, text=text_for(rng, index + 200, used)
        )
        after_blocks = blocks + rng.randint(1, 3)
    elif change_class == "ambiguous":
        # Two priors with identical text and one incoming: the resolver cannot
        # settle which is continued, which is exactly the real failure.
        shared = text_for(rng, 300, used)
        before = [
            UnitSnapshot(logical_id="ku_left", text=shared),
            UnitSnapshot(logical_id="ku_right", text=shared),
            *before[: unit_count - 2],
        ]
        after = [
            UnitSnapshot(logical_id="ku_incoming", text=text_for(rng, 301, used)),
            *before[2:],
        ]
        blocks = len(before)
        after_blocks = len(after)
    return {"before": before, "after": after, "blocks": blocks, "after_blocks": after_blocks}


def shape(blocks: int) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset({("Intro",)}),
        block_count=blocks,
        table_shapes=(),
        figure_refs=frozenset(),
    )


def make_graph(units: list[str]) -> tuple[DependencyGraph, dict[str, tuple[str, ...]]]:
    """Three artifact kinds, deliberately including one that is position-aggregating.

    The real-revision adapter has no artifact whose bytes depend on document
    order, which is why the structural channel never fired there. Including one
    here is what makes the structural class testable at all -- and the
    text-extract artifact, which disclaims the structural channel, is what shows
    the channels discriminate rather than all firing together.
    """
    dependencies: dict[str, tuple[str, ...]] = {}
    edges: list[DependencyEdge] = []
    for unit in units:
        artifact = f"artifact:section:{unit}"
        dependencies[artifact] = (unit,)
        edges.append(
            DependencyEdge(
                artifact,
                unit,
                EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.SEMANTIC}),
            )
        )
    ordered = "artifact:reading-order:doc"
    dependencies[ordered] = tuple(units)
    for unit in units:
        edges.append(
            DependencyEdge(
                ordered,
                unit,
                EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.SEMANTIC, DependencyChannel.STRUCTURAL}),
            )
        )
    return DependencyGraph(edges), dependencies


def artifact_hashes(
    dependencies: dict[str, tuple[str, ...]],
    units: list[UnitSnapshot],
    blocks: int,
) -> dict[str, str]:
    by_id = {u.logical_id: u.text for u in units}
    present = [u.logical_id for u in units]
    out: dict[str, str] = {}
    for artifact, inputs in dependencies.items():
        if artifact.startswith("artifact:reading-order"):
            # Position-aggregating: its bytes depend on the order and count of
            # what is present, not only on the text.
            payload = {"blocks": blocks, "order": [u for u in present if u in inputs]}
        else:
            payload = {"units": [{"id": i, "text": by_id.get(i, "<ABSENT>")} for i in inputs]}
        out[artifact] = canonical_sha256(payload)
    return out


def run_case(case: dict[str, Any], *, policy: StructuralPolicy) -> dict[str, Any]:
    before, after = case["before"], case["after"]
    units = sorted({u.logical_id for u in before} | {u.logical_id for u in after})
    graph, dependencies = make_graph(units)

    before_hashes = artifact_hashes(dependencies, before, case["blocks"])
    full_hashes = artifact_hashes(dependencies, after, case["after_blocks"])

    before_text = canonical_sha256([(u.logical_id, u.text) for u in before] + [case["blocks"]])
    after_text = canonical_sha256([(u.logical_id, u.text) for u in after] + [case["after_blocks"]])

    diff = diff_documents(
        before_sha256=before_text,
        after_sha256=after_text,
        level=DiffLevel.SEMANTIC,
        before_shape=shape(case["blocks"]),
        after_shape=shape(case["after_blocks"]),
        before_units=before,
        after_units=after,
        source="sweep",
    )
    inventory = sorted(dependencies)
    plan = plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=inventory,
        structural_policy=policy,
    )
    planned = set(plan.to_rebuild)
    genuinely_changed = {a for a in inventory if before_hashes[a] != full_hashes[a]}

    equivalence = verify_equivalence(
        full_rebuild=full_hashes,
        selective_rebuild={a: full_hashes[a] for a in inventory if a in planned},
        carried_over={a: before_hashes[a] for a in inventory if a not in planned},
        plan=plan,
    )

    # The promotion gate, with no full-rebuild oracle -- the production case.
    unit_hashes_before = {u.logical_id: canonical_sha256(u.text) for u in before}
    unit_hashes_after = {u.logical_id: canonical_sha256(u.text) for u in after}
    current = [t.artifact_id for t in plan.targets if t.state is ArtifactState.CURRENT]

    def fingerprints(
        hashes: dict[str, str], units: list[UnitSnapshot], blocks: int
    ) -> dict[str, str]:
        present = [u.logical_id for u in units]
        out = {}
        for a in current:
            structural = None
            if a.startswith("artifact:reading-order"):
                # Declared because this artifact's bytes are a function of shape.
                # Omitting it is what let 400 of 400 structural-only changes pass.
                structural = {"blocks": blocks, "order": present}
            out[a] = artifact_input_fingerprint(
                dependencies[a], hashes, structural=structural
            )
        return out

    gate = evaluate_promotion_gate(
        diff=diff,
        graph=graph,
        plan=plan,
        rebuilt=sorted(planned),
        current_input_fingerprints=fingerprints(unit_hashes_after, after, case["after_blocks"]),
        expected_input_fingerprints=fingerprints(unit_hashes_before, before, case["blocks"]),
        structural_coverage=[a for a in current if a.startswith("artifact:reading-order")],
    )

    escaped = sorted(genuinely_changed - planned)
    return {
        "equivalent": equivalence.equivalent,
        "stale_escaped": escaped,
        "falsely_invalidated": len(planned - genuinely_changed),
        "rebuilt": len(planned),
        "genuinely_changed": len(genuinely_changed),
        "artifacts": len(inventory),
        # A gate that permits promotion while an artifact escaped is the exact
        # fail-open this whole programme exists to close.
        "gate_promotable": gate.promotable,
        "gate_missed_an_escape": bool(escaped) and gate.promotable,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-per-class", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    results: dict[str, dict[str, Any]] = {}
    for arm, policy in (
        ("default", StructuralPolicy.OFF),
        ("structural_always", StructuralPolicy.ALWAYS),
        # Activates exactly when the graph declares a shape-dependent artifact
        # and the diff carries a structural change.
        ("structural_precise", StructuralPolicy.PRECISE),
    ):
        rng = random.Random(args.seed)  # noqa: S311 -- case generation, not crypto
        per_class: dict[str, Counter] = {c: Counter() for c in CLASSES}
        escapes: list[dict[str, Any]] = []
        for change_class in CLASSES:
            for _ in range(args.cases_per_class):
                case = build_case(rng, change_class)
                row = run_case(case, policy=policy)
                counter = per_class[change_class]
                counter["cases"] += 1
                counter["equivalent"] += int(row["equivalent"])
                counter["rebuilt"] += row["rebuilt"]
                counter["genuinely_changed"] += row["genuinely_changed"]
                counter["falsely_invalidated"] += row["falsely_invalidated"]
                counter["stale_escaped"] += len(row["stale_escaped"])
                counter["gate_blocked"] += int(not row["gate_promotable"])
                counter["gate_missed_an_escape"] += int(row["gate_missed_an_escape"])
                if row["stale_escaped"]:
                    escapes.append({"class": change_class, **row})
        results[arm] = {
            "per_class": {c: dict(v) for c, v in per_class.items()},
            "total_stale_escaped": sum(v["stale_escaped"] for v in per_class.values()),
            "total_gate_missed_an_escape": sum(
                v["gate_missed_an_escape"] for v in per_class.values()
            ),
            "example_escapes": escapes[:10],
        }

    receipt = {
        "schema": "tavonel.recompilation-change-space-sweep.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "cases_per_class": args.cases_per_class,
        "classes": list(CLASSES),
        "arms": results,
        "what_this_answers": (
            "whether selective recompilation equals a full rebuild across the "
            "change space rather than across one corpus. Ground truth is the "
            "full rebuild, computed independently of the plan, so neither "
            "direction of error can hide: a missed rebuild is a stale artifact "
            "escaping and an extra rebuild is wasted work."
        ),
        "what_this_is_not": (
            "real data. The documents are generated, so this says nothing about "
            "real change distributions -- the corpora do that. It says the "
            "mechanism is correct on change classes the corpora happen not to "
            "contain, which is precisely what a corpus cannot say."
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for arm, block in results.items():
        print(f"== {arm}")
        header = (
            f"  {'class':18}{'cases':>7}{'equiv':>7}{'escaped':>9}"
            f"{'rebuilt':>9}{'needed':>8}{'false':>7}{'gate blocked':>14}"
        )
        print(header)
        for change_class in CLASSES:
            v = block["per_class"][change_class]
            print(
                f"  {change_class:18}{v['cases']:>7}{v['equivalent']:>7}"
                f"{v['stale_escaped']:>9}{v['rebuilt']:>9}{v['genuinely_changed']:>8}"
                f"{v['falsely_invalidated']:>7}{v['gate_blocked']:>14}"
            )
        print(f"  total stale escaped        : {block['total_stale_escaped']}")
        print(f"  gate permitted an escape   : {block['total_gate_missed_an_escape']}")
    print(f"\nreceipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
