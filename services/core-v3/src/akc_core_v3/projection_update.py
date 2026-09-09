"""Explicit source-bound candidate updates; legacy/default receipts stay intact.

This module has no publish authority and performs no network I/O. It composes
existing Protected Core functions with the corrected projection declarations.
The caller still owes source/tenant authorization, fact-ledger qualification,
and the compatibility/shadow/benchmark/canary promotion ladder.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from akc_cir.dependency import DependencyGraph
from akc_cir.recompilation import (
    EquivalenceReport,
    RecompilationPlan,
    StructuralPolicy,
    plan_recompilation,
    verify_equivalence,
)
from akc_cir.semantic_diff import DiffLevel, UnitSnapshot, diff_documents

from .contract import artifact_content, digest
from .projections import ProjectionPolicy, plan_artifacts
from .sources import ResolvedSource, document_shape

SOURCE_BOUND_PROFILE = "source-bound-v2"


def source_bound_snapshots(resolved: ResolvedSource) -> tuple[UnitSnapshot, ...]:
    """Expose observed witness changes without changing logical identity signals.

    Legacy snapshots omit bbox, region id and authority. Two outputs can then
    have different provenance while their snapshots compare equal. The visual
    facet carries a digest of the observed witness, not a made-up confidence or
    a new evidence id. Geometry is not injected into identity matching.
    """
    return tuple(
        replace(
            unit.snapshot(),
            authority=unit.authority,
            visual_fingerprint=digest(artifact_content(unit.provenance())),
        )
        for unit in resolved.units
    )


@dataclass(frozen=True, slots=True)
class SourceBoundUpdate:
    profile: str
    plan: RecompilationPlan
    equivalence: EquivalenceReport
    rebuilt: Mapping[str, str]
    carried: Mapping[str, str]

    @property
    def candidate_hashes(self) -> dict[str, str]:
        """A candidate, not an active World or a security qualification."""
        return {**self.carried, **self.rebuilt}


def compile_source_bound_update(
    *,
    before: ResolvedSource,
    after: ResolvedSource,
    previous_hashes: Mapping[str, str],
    source_lineage: str,
) -> SourceBoundUpdate:
    if not source_lineage.strip():
        raise ValueError("SOURCE_LINEAGE_REQUIRED")
    previous_plan = plan_artifacts(before, policy=ProjectionPolicy.SOURCE_BOUND)
    if dict(previous_hashes) != previous_plan.full_rebuild():
        raise ValueError("PREVIOUS_ARTIFACT_BINDING_MISMATCH")
    current = plan_artifacts(after, policy=ProjectionPolicy.SOURCE_BOUND)
    diff = diff_documents(
        before_sha256=before.source_sha256,
        after_sha256=after.source_sha256,
        level=DiffLevel.GRAPH,
        before_shape=document_shape(before.units),
        after_shape=document_shape(after.units),
        before_units=source_bound_snapshots(before),
        after_units=source_bound_snapshots(after),
        source=source_lineage,
    )
    # Deleted units are absent from the new graph but their old dependants must
    # still be invalidated. Union the declared edges, not the artifact inventory:
    # removed artifacts must never be carried into the new candidate.
    edges = {
        (edge.source_id, edge.target_id, edge.edge_type, edge.channels): edge
        for graph in (previous_plan.graph, current.graph)
        for node in graph.nodes
        for edge in graph.edges_from(node)
    }
    plan = plan_recompilation(
        diff=diff,
        graph=DependencyGraph(edges.values()),
        artifacts=current.artifacts,
        structural_policy=StructuralPolicy.PRECISE,
        include_visual_facet=True,
    )
    rebuilt = {artifact: current.build(artifact) for artifact in plan.to_rebuild}
    carried = {
        artifact: previous_hashes[artifact]
        for artifact in current.artifacts
        if artifact not in rebuilt and artifact in previous_hashes
    }
    # Do not fill gaps from this oracle. A planning defect remains a refusal,
    # rather than a full rebuild secretly described as selective execution.
    equivalence = verify_equivalence(
        full_rebuild=current.full_rebuild(),
        selective_rebuild=rebuilt,
        carried_over=carried,
        plan=plan,
    )
    if not equivalence.equivalent:
        raise ValueError("SOURCE_BOUND_EQUIVALENCE_REFUSED")
    return SourceBoundUpdate(
        SOURCE_BOUND_PROFILE,
        plan,
        equivalence,
        MappingProxyType(rebuilt),
        MappingProxyType(carried),
    )
