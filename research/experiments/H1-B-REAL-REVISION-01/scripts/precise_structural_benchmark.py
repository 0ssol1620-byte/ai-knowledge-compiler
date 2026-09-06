#!/usr/bin/env python3
"""Does precise structural invalidation remove the 80.5% false-invalidation cost?

The real-revision corpora measured a blunt choice: structural propagation off
left staleness possible, and on it invalidated 80.5% of artifacts unnecessarily.
Neither is acceptable, and the sweep showed the cost is not the propagation
mechanism's -- the traversal is already channel-filtered.

It is the declarations. `DependencyEdge.channels` defaults to every channel, so
the v3 adapter, which declares nothing, has asserted that every artifact depends
on document shape. It does not. Every v3 artifact hashes
`sorted(logical_ids)` plus each unit's normalised text; document order and block
count cannot reach it. The honest declaration for all of them is SEMANTIC.

This measures three arms over the same frozen pairs:

    legacy        structural off, ALL-channel edges  (what shipped)
    always        structural on,  ALL-channel edges  (the 80.5% arm)
    precise       StructuralPolicy.PRECISE with **declared** channels

The frozen adapter is not modified -- its edges are re-declared here, so the
replayed bytes and the recorded receipts stay exactly as they were.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
EXP = ROOT / "research/experiments/H1-B-REAL-REVISION-01"
ADAPTER = EXP / "scripts/run_public_real_revision_holdout_v3.py"

from akc_cir.dependency import (  # noqa: E402
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.recompilation import (  # noqa: E402
    StructuralPolicy,
    plan_recompilation,
    verify_equivalence,
)
from akc_cir.semantic_diff import DiffLevel, diff_documents  # noqa: E402

CORPORA = [
    ("holdout-v2", EXP / "receipts/wikipedia-real-revision-holdout-v2.json", EXP / "corpus"),
    (
        "confirmatory-v1",
        EXP / "receipts/wikipedia-real-revision-confirmatory-v1.json",
        EXP / "corpus-confirmatory-v1",
    ),
]
# extension-v1 is deliberately absent. Its receipt has no per-pair `records`
# block -- it was written by the structural benchmark under a different schema --
# and including it would print a row of zeros that reads like a clean pass. A
# corpus that was not scored is not a corpus that scored well.


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_adapter() -> Any:
    spec = importlib.util.spec_from_file_location("real_revision_v3_precise", ADAPTER)
    if spec is None or spec.loader is None:
        raise SystemExit("the v3 adapter cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def declared_graph(dependencies: dict[str, tuple[str, ...]]) -> DependencyGraph:
    """The same graph, with channels declared instead of defaulted.

    Every v3 artifact is SEMANTIC-only, and that is a statement about its hash
    function rather than a convenient setting: the payload is built from
    `sorted(logical_ids)` and normalised unit text, so neither reordering nor a
    block-count change can alter the bytes. Declaring STRUCTURAL here would be
    asserting a dependency the code does not have.
    """
    edges = [
        DependencyEdge(
            artifact,
            logical_id,
            EdgeType.DEPENDS_ON,
            channels=frozenset({DependencyChannel.SEMANTIC}),
        )
        for artifact, inputs in dependencies.items()
        for logical_id in inputs
    ]
    return DependencyGraph(edges)


def read_side(adapter: Any, corpus: Path, record: dict[str, Any], side: str) -> Any:
    directory = corpus / adapter.slug(record["title"])
    path = directory / f"{record[side + '_revision_id']}.wikitext"
    text = path.read_text(encoding="utf-8")
    if adapter.sha_text(text) != record[side + "_sha256"]:
        raise SystemExit(f"{path} no longer matches its recorded sha256")
    return adapter.Revision(
        title=record["title"],
        revid=record[side + "_revision_id"],
        parentid=0,
        timestamp=record[side + "_timestamp"],
        mw_sha1=record[side + "_mw_sha1"],
        text=text,
    )


def score_pair(adapter: Any, corpus: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    before = read_side(adapter, corpus, record, "before")
    after = read_side(adapter, corpus, record, "after")
    before_units, before_shape = adapter.section_units(before)
    after_units, after_shape = adapter.section_units(after)
    if not before_units or not after_units:
        return None

    diff = diff_documents(
        before_sha256=adapter.sha_text(before.text),
        after_sha256=adapter.sha_text(after.text),
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source="precise-bench",
    )
    default_graph, inventory, dependencies = adapter.make_graph_and_inventory(
        record["title"], before_units, after_units
    )
    before_hashes = adapter.artifact_hashes(dependencies, before_units)
    full_hashes = adapter.artifact_hashes(dependencies, after_units)
    genuinely_changed = {a for a in inventory if before_hashes[a] != full_hashes[a]}

    arms = {
        "legacy": (default_graph, {"structural_channel": False}),
        "always": (default_graph, {"structural_channel": True}),
        "precise": (
            declared_graph(dependencies),
            {"structural_policy": StructuralPolicy.PRECISE},
        ),
    }
    row: dict[str, Any] = {"title": record["title"], "artifacts": len(inventory)}
    for name, (graph, options) in arms.items():
        plan = plan_recompilation(
            diff=diff, graph=graph, artifacts=inventory, **options
        )
        planned = set(plan.to_rebuild)
        equivalence = verify_equivalence(
            full_rebuild=full_hashes,
            selective_rebuild={a: full_hashes[a] for a in inventory if a in planned},
            carried_over={a: before_hashes[a] for a in inventory if a not in planned},
            plan=plan,
        )
        row[name] = {
            "equivalent": equivalence.equivalent,
            "stale": len(genuinely_changed - planned),
            "rebuilt": len(planned),
            "needed": len(genuinely_changed),
            "false_invalidated": len(planned - genuinely_changed),
        }
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    adapter = load_adapter()

    corpora: dict[str, Any] = {}
    for name, receipt_path, corpus in CORPORA:
        records = json.loads(receipt_path.read_text(encoding="utf-8")).get("records", [])
        rows = [r for r in (score_pair(adapter, corpus, rec) for rec in records) if r]
        totals: dict[str, dict[str, Any]] = {}
        for arm in ("legacy", "always", "precise"):
            rebuilt = sum(r[arm]["rebuilt"] for r in rows)
            false_inv = sum(r[arm]["false_invalidated"] for r in rows)
            totals[arm] = {
                "all_equivalent": all(r[arm]["equivalent"] for r in rows),
                "stale": sum(r[arm]["stale"] for r in rows),
                "rebuilt": rebuilt,
                "needed": sum(r[arm]["needed"] for r in rows),
                "false_invalidation_rate": round(false_inv / rebuilt, 4) if rebuilt else 0.0,
            }
        corpora[name] = {
            "pairs": len(rows),
            "artifacts": sum(r["artifacts"] for r in rows),
            "arms": totals,
        }

    receipt = {
        "schema": "tavonel.precise-structural-invalidation.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "corpora": corpora,
        "why_precise_differs": (
            "the traversal was already channel-filtered; the cost came from "
            "DependencyEdge.channels defaulting to every channel, so an adapter "
            "that declares nothing asserts that every artifact depends on "
            "document shape. Every v3 artifact hashes sorted(logical_ids) plus "
            "normalised unit text, so none of them do."
        ),
        "scope": (
            "this shows precise invalidation removes the cost on THIS adapter, "
            "whose artifacts are genuinely all semantic. It does not show that "
            "production graphs are mostly semantic, nor that enabling structural "
            "propagation globally is cost-effective."
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for name, block in corpora.items():
        print(f"== {name}: {block['pairs']} pairs, {block['artifacts']} artifacts")
        print("   arm       equiv  stale  rebuilt  needed  false-inval")
        for arm in ("legacy", "always", "precise"):
            t = block["arms"][arm]
            print(
                f"   {arm:10}{t['all_equivalent']!s:>6}{t['stale']:>7}"
                f"{t['rebuilt']:>9}{t['needed']:>8}{t['false_invalidation_rate']:>13}"
            )
    print(f"receipt: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
