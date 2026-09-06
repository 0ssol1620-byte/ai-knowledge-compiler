#!/usr/bin/env python3
"""Reproduce the Family B confirmatory `stale_left_behind = 2` in isolation.

`receipts/wikipedia-real-revision-confirmatory-v1.json` reports one non-equivalent
pair -- "Self-driving car", revisions 1359295324 -> 1359295913 -- with:

    change_kinds            ['identity_unresolved', 'structure_changed']
    changed_logical_ids     0
    unresolved_identity_count 3
    stale_left_behind       2
    diverged                artifact:section:wiki-unit:5a8b712ff07d910bc3d685ef
                            artifact:topic-bucket:b0c6b3d5400b62b3:1

Two explanations were checked against the code and both were wrong:

  * It is not the acquisition error. That error is on a different article
    ("Claude (language model)"), whose pair was never scored at all.
  * It is not an unresolved identity being carried over. `RecompilationPlan
    .to_rebuild` is `stale + unresolved`, and its docstring is explicit that
    rebuilding an unresolved artifact needlessly is the cheaper mistake.

What is left is the structural channel. `_structural_changes` in
`akc_cir.semantic_diff` constructs every `STRUCTURE_CHANGED` without a
`logical_id`, and `SemanticDiff.changed_logical_ids` keeps only changes that
carry one. So a structural change can never seed the dependency traversal in
`plan_recompilation`, and an artifact whose content depends on document
structure -- ordering, bucketing, anything aggregated over position -- is
classified CURRENT and carried over unchanged.

This program builds the smallest case with that shape: two units whose text is
byte-identical in both revisions, a document whose block structure moved, and an
artifact whose bytes depend on that structure. Nothing about identity is
unsettled and no unit's meaning changed, so the diff reports the structural
channel alone. The artifact is carried over while a full rebuild would have
produced different bytes, which reproduces the reported defect without Wikipedia
and without a network call.

It asserts nothing about the fix. `akc_cir.semantic_diff` and
`akc_cir.recompilation` are Protected Core, and a replacement goes through
compatibility contract -> shadow -> benchmark -> canary -> rollout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.dependency import (  # noqa: E402
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.recompilation import plan_recompilation, verify_equivalence  # noqa: E402
from akc_cir.semantic_diff import (  # noqa: E402
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)

ARTIFACT = "artifact:ordered-digest:demo"
UNIT_A = "wiki-unit:aaaaaaaaaaaaaaaa"
UNIT_B = "wiki-unit:bbbbbbbbbbbbbbbb"

TEXT_A = "Autonomous vehicles were first demonstrated on public roads in 1995."
TEXT_B = "Regulatory approval followed in several jurisdictions after 2020."


def unit(logical_id: str, text: str) -> UnitSnapshot:
    return UnitSnapshot(logical_id=logical_id, text=text)


def digest(units: list[UnitSnapshot], shape: DocumentShape) -> str:
    """An artifact whose bytes depend on document structure, not only unit text.

    A table of contents, a topic bucket, a reading-order projection -- anything
    aggregated over position or block structure behaves this way.
    `artifact:topic-bucket:b0c6b3d5400b62b3:1` in the confirmatory receipt is one
    of these, and it is one of the two artifacts that diverged.
    """
    return f"blocks={shape.block_count}|" + "|".join(u.text for u in units)


def main() -> int:
    # Identical text on both sides: nothing about identity is unsettled and no
    # unit's meaning changed. Only the document's block structure moved, which is
    # what a Wikipedia edit that splits a paragraph or moves a template does.
    before_units = [unit(UNIT_A, TEXT_A), unit(UNIT_B, TEXT_B)]
    after_units = [unit(UNIT_A, TEXT_A), unit(UNIT_B, TEXT_B)]

    headings = frozenset({("Intro",), ("History",)})
    before_shape = DocumentShape(
        heading_path_set=headings, block_count=2, table_shapes=(), figure_refs=frozenset()
    )
    after_shape = DocumentShape(
        heading_path_set=headings, block_count=3, table_shapes=(), figure_refs=frozenset()
    )

    diff = diff_documents(
        before_sha256="sha256:" + "1" * 64,
        after_sha256="sha256:" + "2" * 64,
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source="reproduction:structure-only",
    )

    graph = DependencyGraph(
        [
            DependencyEdge(ARTIFACT, UNIT_A, EdgeType.DEPENDS_ON),
            DependencyEdge(ARTIFACT, UNIT_B, EdgeType.DEPENDS_ON),
        ]
    )
    plan = plan_recompilation(diff=diff, graph=graph, artifacts=[ARTIFACT])

    full = {ARTIFACT: digest(after_units, after_shape)}
    planned = set(plan.to_rebuild)
    selective = {a: full[a] for a in full if a in planned}
    carried = (
        {ARTIFACT: digest(before_units, before_shape)} if ARTIFACT not in planned else {}
    )

    report = verify_equivalence(
        full_rebuild=full,
        selective_rebuild=selective,
        carried_over=carried,
        plan=plan,
    )

    result = {
        "case": "structure changed (block_count 2 -> 3); no unit text changed",
        "schema": "tavonel.family-b-structure-only-stale-reproduction.v1",
        "reproduces_confirmatory_defect": bool(report.stale_left_behind),
        "change_kinds": sorted({c.kind.value for c in diff.changes}),
        "content_changed": diff.content_changed,
        "changed_logical_ids": list(diff.changed_logical_ids),
        "unresolved_count": len(diff.unresolved),
        "planned_rebuild": list(plan.to_rebuild),
        "stale_left_behind": list(report.stale_left_behind),
        "diverged": list(report.diverged),
        "root_cause": (
            "_structural_changes builds every STRUCTURE_CHANGED without a logical_id, "
            "and SemanticDiff.changed_logical_ids keeps only changes that carry one, so "
            "plan_recompilation has nothing to seed its traversal with. An artifact "
            "aggregated over document position is then classified CURRENT and carried "
            "over stale."
        ),
        "why_this_matters": (
            "The repository rule is fail closed on integrity violations. This path fails "
            "open: the run reports success and the artifact is wrong."
        ),
        "not_attempted_here": (
            "akc_cir.semantic_diff and akc_cir.recompilation are Protected Core. A change "
            "goes through compatibility contract -> shadow -> benchmark -> canary -> "
            "rollout, and this program only establishes the defect."
        ),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if report.stale_left_behind else 1


if __name__ == "__main__":
    raise SystemExit(main())
