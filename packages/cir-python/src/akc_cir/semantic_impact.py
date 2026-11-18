"""Semantic-impact channel for selective knowledge recompilation.

The source diff intentionally records more than downstream knowledge consumers
need. In particular, an evidence region may move to another page while the
claim, entities, relations, authority, and meaning remain unchanged. Treating
that positional observation as a semantic invalidation turns harmless layout
motion into a corpus-wide rebuild.

This module is an additive policy layer over the existing protected diff and
recompilation code. It does not change how evidence movement is recorded. It
only decides which recorded changes are allowed to seed semantic dependency
traversal.

Contract:

* semantic changes seed STALE propagation;
* EVIDENCE_MOVED is observable provenance but does not by itself seed semantic
  propagation;
* unresolved identity remains fail-closed: downstream artifacts reached only
  through unresolved candidates are rebuilt as UNRESOLVED;
* every affected artifact still carries the dependency path that reached it.
"""

from __future__ import annotations

from collections.abc import Iterable

from .dependency import DependencyGraph, ImpactReport
from .recompilation import ArtifactState, RecompilationPlan, RecompilationTarget
from .semantic_diff import ChangeKind, SemanticDiff

__all__ = [
    "IMPACT_BEARING_CHANGE_KINDS",
    "plan_semantic_recompilation",
    "semantic_impact_seeds",
]


# These change kinds can make a derived knowledge artifact semantically stale.
# Positional/provenance-only observations such as EVIDENCE_MOVED are deliberately
# absent. STRUCTURE_CHANGED has no logical-id seed in the current CIR contract;
# structure-specific artifacts should be connected through their own typed
# dependency channel rather than by pretending a document shape is a claim.
IMPACT_BEARING_CHANGE_KINDS: frozenset[ChangeKind] = frozenset(
    {
        ChangeKind.UNIT_ADDED,
        ChangeKind.UNIT_REMOVED,
        ChangeKind.MODIFIED_CLAIM,
        ChangeKind.ENTITY_CHANGED,
        ChangeKind.RELATIONSHIP_ADDED,
        ChangeKind.RELATIONSHIP_REMOVED,
        ChangeKind.AUTHORITY_CHANGED,
    }
)


def semantic_impact_seeds(diff: SemanticDiff) -> tuple[str, ...]:
    """Return stable logical ids whose *meaning* can invalidate consumers.

    The order is deterministic and follows the diff record. An identity the
    resolver could not settle never becomes a stale seed here; unresolved
    candidates are handled separately by :func:`plan_semantic_recompilation` so
    they retain the stronger UNRESOLVED state instead of being mislabeled STALE.
    """

    seen: list[str] = []
    for change in diff.changes:
        if change.kind not in IMPACT_BEARING_CHANGE_KINDS:
            continue
        if change.logical_id and change.logical_id not in seen:
            seen.append(change.logical_id)
    return tuple(seen)


def plan_semantic_recompilation(
    *,
    diff: SemanticDiff,
    graph: DependencyGraph,
    artifacts: Iterable[str],
    max_depth: int | None = None,
) -> RecompilationPlan:
    """Plan rebuilds from semantic change while preserving fail-closed identity.

    This is the product-facing challenger for the positional/semantic channel
    split. It intentionally reuses the existing ``RecompilationPlan`` contract
    so equivalence verification and downstream receipts remain compatible.
    """

    inventory = list(dict.fromkeys(artifacts))

    if not diff.content_changed:
        return RecompilationPlan(
            change_id=diff.change_id,
            targets=tuple(
                RecompilationTarget(
                    artifact_id=artifact,
                    state=ArtifactState.CURRENT,
                    reason="the source content did not change",
                )
                for artifact in inventory
            ),
            total_artifacts=len(inventory),
        )

    semantic_seeds = semantic_impact_seeds(diff)
    report: ImpactReport = graph.impact_of(semantic_seeds, max_depth=max_depth)
    reached = {path.node_id: path for path in report.affected}

    # An unresolved identity is not a semantic stale seed because continuity was
    # never established. It is nevertheless unsafe to carry over consumers of
    # its candidates, so those consumers are rebuilt and labelled UNRESOLVED.
    unresolved_seeds: list[str] = []
    for change in diff.unresolved:
        unresolved_seeds.extend(change.candidates)

    unresolved_reached: dict[str, str] = {}
    if unresolved_seeds:
        shadow = graph.impact_of(list(dict.fromkeys(unresolved_seeds)), max_depth=max_depth)
        for path in shadow.affected:
            if path.node_id not in reached:
                unresolved_reached[path.node_id] = path.describe()
        for seed in dict.fromkeys(unresolved_seeds):
            if seed not in reached:
                unresolved_reached.setdefault(
                    seed, f"{seed} is a candidate in an unsettled identity"
                )

    targets: list[RecompilationTarget] = []
    for artifact in inventory:
        if artifact in reached:
            path = reached[artifact]
            targets.append(
                RecompilationTarget(
                    artifact_id=artifact,
                    state=ArtifactState.STALE,
                    reason=path.describe(),
                    depth=path.depth,
                    path=path.describe(),
                )
            )
        elif artifact in unresolved_reached:
            targets.append(
                RecompilationTarget(
                    artifact_id=artifact,
                    state=ArtifactState.UNRESOLVED,
                    reason=(
                        "reached only through an identity the diff could not settle: "
                        + unresolved_reached[artifact]
                    ),
                )
            )
        else:
            targets.append(
                RecompilationTarget(
                    artifact_id=artifact,
                    state=ArtifactState.CURRENT,
                    reason=(
                        "no semantic change reached it"
                        if diff.content_changed
                        else "the source content did not change"
                    ),
                )
            )

    return RecompilationPlan(
        change_id=diff.change_id,
        targets=tuple(targets),
        total_artifacts=len(inventory),
        cycles_detected=report.cycles_detected,
        truncated_at_depth=report.truncated_at_depth,
    )
