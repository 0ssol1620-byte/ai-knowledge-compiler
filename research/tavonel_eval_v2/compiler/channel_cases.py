"""Synthetic, adversarial differential cases for the executor's dependency channels.

`SOURCE_FACT_IR_HELDOUT_V2` (SFI2) was a frozen FAIL: 14 confirmed selective
stale escapes, on the same 14 pairs the typed cross-check said would move. Those
14 came from a held-out corpus -- nothing in the test suite could have produced
them. This module is the fix for *that* gap: build the adversarial cases from
the channel definitions themselves, not from the 14 fixtures (which stay a
forensic-lane fixture, never a development one here).

Two vocabularies are in play and they do not line up one-to-one:

    source_fact_ir.ir.CHANNELS       SEMANTIC, STRUCTURAL, REFERENTIAL,
                                      TEMPORAL, DESCRIPTIVE
                                      -- what a fact *kind* is declared to mean.

    akc_cir.dependency.DependencyChannel
                                      SEMANTIC, LOCATOR, VISUAL, TEMPORAL,
                                      STRUCTURAL, METADATA
                                      -- what a graph *edge* can be tagged with.

    akc_cir.semantic_diff.ChangeChannel
                                      UNCHANGED, STRUCTURAL, LOCATOR, SEMANTIC,
                                      GRAPH, TEMPORAL, VISUAL, METADATA,
                                      UNRESOLVED
                                      -- what a detected *change* is tagged
                                      with, and only {SEMANTIC, GRAPH} of those
                                      ever seed `plan_recompilation`'s traversal
                                      (`SemanticDiff.changed_logical_ids`).

`compiler/selective_build.py`'s `graph_for` is the one that matters: it is the
executor's actual dependency graph, and it only ever emits edges carrying
`DependencyChannel.SEMANTIC` and/or `DependencyChannel.STRUCTURAL`
(`SEMANTIC_ONLY`, `STRUCTURAL_ONLY`, `SEMANTIC_AND_STRUCTURAL` -- see its
module docstring). No artifact prefix there ever produces a `LOCATOR`,
`TEMPORAL`, `VISUAL` or `METADATA` edge. So of the IR's five named channels:

    SEMANTIC     -> DependencyChannel.SEMANTIC   -- has edges, seeds traversal
    STRUCTURAL   -> DependencyChannel.STRUCTURAL -- has edges, seeds traversal
    REFERENTIAL  -> closest analogue is DependencyChannel.LOCATOR /
                     ChangeChannel.LOCATOR -- no edges, and explicitly excluded
                     from `_SEMANTIC_RECOMPILATION_CHANNELS`
    TEMPORAL     -> DependencyChannel.TEMPORAL / ChangeChannel.TEMPORAL --
                     no edges, excluded the same way
    DESCRIPTIVE  -> closest analogue is DependencyChannel.METADATA /
                     ChangeChannel.METADATA -- no edges, excluded the same way

Each `*_case` function below is built from real production machinery
(`canonical_document`, `diff_documents`, `graph_for`, `plan_recompilation`,
`run_pair`) so that what a case proves or fails to prove is a property of the
executor, not of a stand-in.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "canonicalization"),
    str(NS / "compiler"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from akc_cir.recompilation import (  # noqa: E402
    RecompilationPlan,
    StructuralPolicy,
    plan_recompilation,
)
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeChannel,
    DiffLevel,
    DocumentShape,
    SemanticDiff,
    diff_documents,
)
from canonicalization.canonical_document import canonical_document  # noqa: E402
from compiler import selective_build as engine  # noqa: E402

LINEAGE = "lineage:test/channel-cases"

#: `canonical_document.MIN_TEXT_CHARS` is 120. Every body below clears it with
#: room to spare so a fixture is never dropped as boilerplate by accident.
BODY_ALPHA = (
    "Section Alpha states a rule about retention windows and the authority that "
    "issued it, at sufficient length that the canonicaliser keeps it as a unit "
    "rather than discarding it as boilerplate text."
)
BODY_BETA = (
    "Section Beta describes the reporting obligation, its effective date and the "
    "office responsible, again at sufficient length that the canonicaliser keeps "
    "it as a unit of its own rather than merging it away."
)
BODY_GAMMA = (
    "Section Gamma covers the escalation procedure and the parties who must be "
    "notified, written at enough length to clear the canonicaliser's minimum "
    "text threshold on its own."
)


def markdown(*bodies: str) -> bytes:
    headings = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"]
    parts = [f"# {headings[i]}\n\n{body}\n" for i, body in enumerate(bodies)]
    return "\n".join(parts).encode()


def document(raw: bytes, version: str, source_id: str = LINEAGE) -> dict[str, Any]:
    return canonical_document(
        source_family="generic_markdown",
        source_id=source_id,
        version_id=version,
        payload=raw,
        source_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        known_at="2026-08-23T00:00:00Z",
        valid_from="2026-08-23T00:00:00Z",
        licence="test",
    )


def declaring(doc: dict[str, Any], index: int, **facets: str) -> dict[str, Any]:
    """A copy of `doc` in which unit `index` declares `facets`.

    The facet is declared on the DOCUMENT, not patched onto the snapshot
    afterwards, and that is the whole point. `selective_build.snapshots` reads a
    unit's facets from the document (`unit.get("evidence_id")` and friends) and
    `selective_build.section_spec` reads them from the same place, so declaring
    once here is what makes the diff and the artifact see one revision.

    The earlier cases built a byte-identical `after_doc` and then replaced one
    `UnitSnapshot` by hand. That produced a real detected change -- the diff
    consumes snapshots -- while `build_all`, which consumes the document, was
    handed a revision in which nothing had happened. The digest then could not
    move for any reason connected to the repair, and a facet-propagation check
    reading these cases reported the artifact spec broken long after it was
    fixed. The defect was in the fixture's wiring, not in the spec.
    """
    units = [dict(unit) for unit in doc["units"]]
    units[index] = {**units[index], **{k: v for k, v in facets.items() if v}}
    return {**doc, "units": units}


# ---------------------------------------------------------------------------
# result shape shared by every case


@dataclass(frozen=True)
class ChannelCase:
    """What one channel case produced, in a shape the test file can assert on.

    `ir_channel` is the name from `source_fact_ir.ir.CHANNELS`. `exercised`
    records whether the executor's graph (`selective_build.graph_for`) can even
    carry an edge for it -- False for every channel but SEMANTIC and STRUCTURAL,
    per this module's docstring. A case with `exercised=False` still runs real
    production code; it demonstrates the change is *detected* and then traces
    exactly why it fails to seed a rebuild.
    """

    ir_channel: str
    exercised: bool
    diff: SemanticDiff
    plan: RecompilationPlan | None
    rebuilt: tuple[str, ...] = ()
    carried: tuple[str, ...] = ()
    target_artifact: str = ""
    note: str = ""
    result: dict[str, Any] | None = None
    #: Present when the case actually executed a rebuild (not merely planned
    #: one): the artifact's digest before and after, so a test can assert they
    #: differ -- proof of point 2, that a real rebuild ran rather than the plan
    #: being taken on faith.
    prior_value: str | None = None
    rebuilt_value: str | None = None


# ---------------------------------------------------------------------------
# SEMANTIC -- content text changed. The executor's other well-exercised
# channel, alongside STRUCTURAL.


def semantic_case() -> ChannelCase:
    before_doc = document(markdown(BODY_ALPHA, BODY_BETA), "v1")
    after_raw = markdown(BODY_ALPHA, BODY_BETA.replace("reporting obligation", "disclosure duty"))
    after_doc = document(after_raw, "v2")

    result = engine.run_pair(before_doc, after_doc)
    prior_state = engine.build_all(before_doc)
    changed_unit = engine.logical_id(after_doc["source_id"], after_doc["units"][1]["explicit_path"])
    target = "section:" + changed_unit

    return ChannelCase(
        ir_channel="SEMANTIC",
        exercised=True,
        diff=None,  # not needed separately; run_pair's internal diff is proven via result
        plan=None,
        rebuilt=tuple(result["selective_rebuild_set"]),
        carried=tuple(result["carried_forward_set"]),
        target_artifact=target,
        result=result,
        prior_value=prior_state.get(target),
        rebuilt_value=result["state"].get(target),
    )


# ---------------------------------------------------------------------------
# STRUCTURAL -- a pure reorder, same units, same text, same headings, only
# reading order moved. `semantic_diff._structural_changes` names this
# specifically as the case that produced 0/60 equivalence before `unit_order`
# was added to `DocumentShape`.


def structural_case() -> ChannelCase:
    """A pure reorder: same units, same text, same headings, order only.

    Physically reordering the source markdown also reorders each unit's
    neighbour anchors, which is itself a semantic-identity signal and pushes
    the resolver toward AMBIGUOUS (score 0.85-0.87, below the 0.92 merge bar)
    rather than a clean reorder -- confirmed by running `diff_documents` over
    a physically-reordered `canonical_document` pair before writing this: it
    produces `identity_unresolved`, not `structure_changed`. That is itself a
    real, separate finding about the identity resolver (see report), but it is
    not what this case is testing.

    So the diff here is held identical to the physical reorder only at the
    shape level: `before_units`/`after_units` are the *same* snapshot list
    (same anchors, zero semantic-diff changes), and only
    `DocumentShape.unit_order` differs -- exactly the isolation
    `_structural_changes`' reorder branch (`semantic_diff.py` line ~364) exists
    to catch on its own. The *rebuild execution* proof (points 2 and 3 below)
    still runs against a real, physically-reordered document pair through
    `build_all`, so the digest actually read is the one the reordered document
    would produce, not a stand-in.
    """
    before_doc = document(markdown(BODY_ALPHA, BODY_BETA, BODY_GAMMA), "v1")
    # Swap Beta and Gamma's positions -- text/heading/explicit_path travel with
    # their unit, so Beta stays Beta, Gamma stays Gamma, just reordered.
    raw_units = list(before_doc["units"])
    after_units_raw = [raw_units[0], raw_units[2], raw_units[1]]
    after_doc = {**before_doc, "units": after_units_raw, "version_id": "v2"}

    units, before_shape = engine.snapshots(before_doc)
    _, after_shape_real = engine.snapshots(after_doc)
    after_shape = DocumentShape(
        heading_path_set=before_shape.heading_path_set,
        block_count=before_shape.block_count,
        table_shapes=before_shape.table_shapes,
        figure_refs=before_shape.figure_refs,
        unit_order=after_shape_real.unit_order,
    )

    diff = diff_documents(
        before_sha256=before_doc["source_digest"],
        after_sha256="sha256:" + "4" * 64,
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=units,
        after_units=units,
        source=before_doc["source_id"],
    )
    assert diff.structural_change_present, "fixture did not produce a structural change"
    assert not any(c.channel is ChangeChannel.SEMANTIC for c in diff.changes), (
        "fixture leaked a semantic change; the case is no longer isolated"
    )

    before_deps, _ = engine.inventory_and_dependencies(before_doc)
    after_deps, _ = engine.inventory_and_dependencies(after_doc)
    graph = engine.graph_for(before_deps, after_deps)
    inventory = sorted({*before_deps, *after_deps})
    plan = plan_recompilation(
        diff=diff, graph=graph, artifacts=inventory, structural_policy=StructuralPolicy.PRECISE
    )

    key = engine.doc_key(before_doc["source_id"])
    target = "structure-map:" + key

    prior_state = engine.build_all(before_doc)
    after_full = engine.build_all(after_doc)
    planned = set(plan.to_rebuild)
    rebuilt: list[str] = []
    carried: list[str] = []
    for artifact in sorted(after_deps):
        if artifact in planned:
            rebuilt.append(artifact)
        elif artifact in prior_state:
            carried.append(artifact)

    return ChannelCase(
        ir_channel="STRUCTURAL",
        exercised=True,
        diff=diff,
        plan=plan,
        rebuilt=tuple(rebuilt),
        carried=tuple(carried),
        target_artifact=target,
        prior_value=prior_state.get(target),
        rebuilt_value=after_full.get(target) if target in planned else prior_state.get(target),
    )


# ---------------------------------------------------------------------------
# Multi-hop propagation. Production `inventory_and_dependencies` never builds
# an artifact that depends on another artifact -- every artifact depends
# directly on one or more logical ids, so the real graph is depth 1. That is a
# genuine limitation of the fixture this repo builds today, named here rather
# than hidden: to prove the *traversal* (`DependencyGraph.impact_of`, called
# from `plan_recompilation`) actually walks more than one hop, this case feeds
# `selective_build.graph_for` a synthetic three-level chain -- leaf unit -> A ->
# B -> C -- using the same production `graph_for`/`plan_recompilation` call
# path a real run uses, with a real content diff seeding the leaf.


def multi_hop_case() -> ChannelCase:
    before_doc = document(markdown(BODY_ALPHA, BODY_BETA), "v1")
    after_raw = markdown(BODY_ALPHA, BODY_BETA.replace("reporting obligation", "disclosure duty"))
    after_doc = document(after_raw, "v2")

    before_units, before_shape = engine.snapshots(before_doc)
    after_units, after_shape = engine.snapshots(after_doc)
    diff = diff_documents(
        before_sha256=before_doc["source_digest"],
        after_sha256=after_doc["source_digest"],
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=after_doc["source_id"],
    )
    leaf = engine.logical_id(after_doc["source_id"], after_doc["units"][1]["explicit_path"])
    assert leaf in diff.changed_logical_ids, "fixture did not change the intended leaf unit"

    deps = {"chain:A": (leaf,), "chain:B": ("chain:A",), "chain:C": ("chain:B",)}
    graph = engine.graph_for(deps, deps)
    plan = plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=sorted(deps),
        structural_policy=StructuralPolicy.PRECISE,
    )

    return ChannelCase(
        ir_channel="SEMANTIC (multi-hop)",
        exercised=True,
        diff=diff,
        plan=plan,
        target_artifact="chain:C",
        note="synthetic 3-hop artifact chain over graph_for/plan_recompilation; "
        "production inventory_and_dependencies never builds artifact-on-artifact "
        "edges, so this depth is not exercised by any real run today",
    )


# ---------------------------------------------------------------------------
# REFERENTIAL -- ir.py's channel for REFERENCE_TARGET / REFERENCE_DEFINITION /
# INCLUDE_TARGET / LOCATOR fact kinds: something that names or points at a
# location. `semantic_diff`'s closest analogue is EVIDENCE_MOVED
# (ChangeChannel.LOCATOR): the same logical unit, same text, whose anchor
# moved. This is SFI2's failure shape in miniature: a change the diff detects
# and correctly types, which then disappears before it can seed a rebuild.
#
# NOT "the typed delta named every moved artifact and the executor failed to
# rebuild them" -- that reading was withdrawn by INC-V2-037. The cross-check's
# 191/191 held only over units that had already entered its own denominator,
# which sits downstream of the change detector; it never established that the
# delta named everything that actually moved. Rebuilt here as a synthetic case
# from the channel definitions, not from the forensic fixture.


def referential_case() -> ChannelCase:
    before_doc = document(markdown(BODY_ALPHA, BODY_BETA), "v1")
    #: Byte-identical text; the ONLY difference is the declared facet, so
    #: anything that moves downstream moves because of this channel alone.
    after_doc = declaring(
        document(markdown(BODY_ALPHA, BODY_BETA), "v2"), 1, evidence_id="e:moved-anchor"
    )

    before_units, before_shape = engine.snapshots(before_doc)
    after_units, after_shape = engine.snapshots(after_doc)
    moved = after_units[1]

    diff = diff_documents(
        before_sha256=before_doc["source_digest"],
        after_sha256="sha256:" + "1" * 64,  # force content_changed; text is identical
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=tuple(after_units),
        source=after_doc["source_id"],
    )
    assert any(c.channel is ChangeChannel.LOCATOR for c in diff.changes), (
        "fixture did not produce an EVIDENCE_MOVED / LOCATOR change"
    )

    before_deps, _ = engine.inventory_and_dependencies(before_doc)
    after_deps, _ = engine.inventory_and_dependencies(after_doc)
    graph = engine.graph_for(before_deps, after_deps)
    inventory = sorted({*before_deps, *after_deps})
    plan = plan_recompilation(
        diff=diff, graph=graph, artifacts=inventory, structural_policy=StructuralPolicy.PRECISE
    )

    target = "section:" + moved.logical_id
    before_full = engine.build_all(before_doc)
    after_full = engine.build_all(after_doc)

    return ChannelCase(
        ir_channel="REFERENTIAL",
        #: Measured from the contract, never asserted: whether this artifact is
        #: declared sensitive to a facet channel at all.
        exercised=bool(engine.declared_facets(target) & engine.FACET_CHANNELS),
        diff=diff,
        plan=plan,
        target_artifact=target,
        prior_value=before_full.get(target),
        rebuilt_value=after_full.get(target),
        note=("The unit's evidence anchor moves and its text does not. Since "
            "INC-V2-038 `section_spec` writes a declared `evidence_id` under "
            "`locator`, so the artifact's bytes differ too -- the change is "
            "detected, carried, and visible in the representation, which is what "
            "makes a rebuild here a repair rather than a re-emission of "
            "identical bytes."),
    )


# ---------------------------------------------------------------------------
# TEMPORAL -- ir.py's channel for EFFECTIVE_TIME / AUTHORITY fact kinds.
# `UnitSnapshot.temporal_fingerprint` is the field semantic_diff compares for
# exactly this; a change to it alone (same text) produces TEMPORAL_CHANGED.


def temporal_case() -> ChannelCase:
    before_doc = document(markdown(BODY_ALPHA, BODY_BETA), "v1")
    #: Byte-identical text; the ONLY difference is the declared facet, so
    #: anything that moves downstream moves because of this channel alone.
    after_doc = declaring(
        document(markdown(BODY_ALPHA, BODY_BETA), "v2"),
        1,
        temporal_fingerprint="effective_time:2027-01-01",
    )

    before_units, before_shape = engine.snapshots(before_doc)
    after_units, after_shape = engine.snapshots(after_doc)
    moved = after_units[1]

    diff = diff_documents(
        before_sha256=before_doc["source_digest"],
        after_sha256="sha256:" + "2" * 64,  # force content_changed; text is identical
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=tuple(after_units),
        source=after_doc["source_id"],
    )
    assert any(c.channel is ChangeChannel.TEMPORAL for c in diff.changes), (
        "fixture did not produce a TEMPORAL_CHANGED change"
    )

    before_deps, _ = engine.inventory_and_dependencies(before_doc)
    after_deps, _ = engine.inventory_and_dependencies(after_doc)
    graph = engine.graph_for(before_deps, after_deps)
    inventory = sorted({*before_deps, *after_deps})
    plan = plan_recompilation(
        diff=diff, graph=graph, artifacts=inventory, structural_policy=StructuralPolicy.PRECISE
    )

    target = "section:" + moved.logical_id
    before_full = engine.build_all(before_doc)
    after_full = engine.build_all(after_doc)

    return ChannelCase(
        ir_channel="TEMPORAL",
        #: Measured from the contract, never asserted: whether this artifact is
        #: declared sensitive to a facet channel at all.
        exercised=bool(engine.declared_facets(target) & engine.FACET_CHANNELS),
        diff=diff,
        plan=plan,
        target_artifact=target,
        prior_value=before_full.get(target),
        rebuilt_value=after_full.get(target),
        note=("The unit's effective time moves and its text does not. Since "
            "INC-V2-038 `section_spec` writes a declared `temporal_fingerprint`, "
            "the artifact digest moves with it, and an equivalence check can no "
            "longer read agreement out of a facet the artifact never held."),
    )


# ---------------------------------------------------------------------------
# DESCRIPTIVE -- ir.py's channel for LANGUAGE / ACCESSIBILITY / APPLICABILITY
# fact kinds. Closest production analogue is `metadata_fingerprint` /
# ChangeChannel.METADATA (DependencyChannel has METADATA, not "descriptive").


def descriptive_case() -> ChannelCase:
    before_doc = document(markdown(BODY_ALPHA, BODY_BETA), "v1")
    #: Byte-identical text; the ONLY difference is the declared facet, so
    #: anything that moves downstream moves because of this channel alone.
    after_doc = declaring(
        document(markdown(BODY_ALPHA, BODY_BETA), "v2"), 1, metadata_fingerprint="language:fr-CA"
    )

    before_units, before_shape = engine.snapshots(before_doc)
    after_units, after_shape = engine.snapshots(after_doc)
    moved = after_units[1]

    diff = diff_documents(
        before_sha256=before_doc["source_digest"],
        after_sha256="sha256:" + "3" * 64,  # force content_changed; text is identical
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=tuple(after_units),
        source=after_doc["source_id"],
    )
    assert any(c.channel is ChangeChannel.METADATA for c in diff.changes), (
        "fixture did not produce a METADATA_CHANGED change"
    )

    before_deps, _ = engine.inventory_and_dependencies(before_doc)
    after_deps, _ = engine.inventory_and_dependencies(after_doc)
    graph = engine.graph_for(before_deps, after_deps)
    inventory = sorted({*before_deps, *after_deps})
    plan = plan_recompilation(
        diff=diff, graph=graph, artifacts=inventory, structural_policy=StructuralPolicy.PRECISE
    )

    target = "section:" + moved.logical_id
    before_full = engine.build_all(before_doc)
    after_full = engine.build_all(after_doc)

    return ChannelCase(
        ir_channel="DESCRIPTIVE",
        #: Measured from the contract, never asserted: whether this artifact is
        #: declared sensitive to a facet channel at all.
        exercised=bool(engine.declared_facets(target) & engine.FACET_CHANNELS),
        diff=diff,
        plan=plan,
        target_artifact=target,
        prior_value=before_full.get(target),
        rebuilt_value=after_full.get(target),
        note=("The unit's declared language moves and its text does not. Since "
            "INC-V2-038 `section_spec` writes a declared `metadata_fingerprint`, "
            "the artifact digest moves with it."),
    )
