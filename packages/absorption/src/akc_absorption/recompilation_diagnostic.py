"""`DIAG-B-01` — why selective recompilation degenerates to a full rebuild.

`EXP-0101` measured `mean_rebuild_fraction = 1.0000` for every arm routed
through `akc_cir.semantic_diff`, against 0.0800 for the prior-art baseline. This
module decomposes that into the four candidate causes the diagnostic contract
names, **read-only**. Nothing in Protected Core is modified, and nothing here
proposes a fix: which cause is real decides what a fix would even be.

Every counterfactual is built by constructing inputs *outside* the core and
handing them to the core's public entry points -- `diff_documents`,
`plan_recompilation`, `verify_equivalence`. None of them monkey-patches, and
none of them edits a core module.

**Rebuild fraction alone is not the metric, and reading it alone is the trap.**
A plan that rebuilds nothing is cheapest and may leave a stale artifact behind,
which is the failure the prior-art baseline actually committed in `EXP-0101`
(equivalence 0.9470). So every counterfactual reports the cost *and* the
equivalence, and a counterfactual that lowers the fraction while breaking
equivalence is reported as a regression, not a saving.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.recompilation import plan_recompilation, verify_equivalence
from akc_cir.semantic_diff import ChangeKind, DiffLevel, SemanticDiff, diff_documents

from .evolution_suite import MutationCase

# `_CaseGraph` and `_artifact_hashes` are module-private to `harness`, and this
# is the same package: the diagnostic must build its plans over exactly the
# graph and artifact hashes `EXP-0101` used, or it would be explaining a
# different experiment's number.
from .harness import _artifact_hashes, _CaseGraph, artifact_id_for
from .type_reasoning import SEMANTIC_CHANGE_KINDS

__all__ = [
    "COUNTERFACTUALS",
    "Cause",
    "PlanOutcome",
    "attribute_changed_set",
    "diff_for",
    "evidence_id_is_version_scoped",
    "run_counterfactuals",
]


class Cause(StrEnum):
    """The four candidates. Named, not ranked -- ranking them is the output."""

    C1_EVIDENCE_IDENTITY_DESIGN = "C1_evidence_identity_design"
    C2_VERSION_SCOPED_EVIDENCE_ID = "C2_version_scoped_evidence_id"
    C3_SEMANTIC_EVIDENCE_CONFLATION = "C3_semantic_evidence_conflation"
    C4_DEPENDENCY_INVALIDATION_RULE = "C4_dependency_invalidation_rule"


#: Which counterfactual speaks to which cause. A counterfactual that moves the
#: number is evidence for its cause; one that does not is evidence against.
COUNTERFACTUALS: dict[str, tuple[Cause, ...]] = {
    "actual": (),
    "c2_stable_evidence_ids": (Cause.C2_VERSION_SCOPED_EVIDENCE_ID,),
    "c3_semantic_channel_only": (Cause.C3_SEMANTIC_EVIDENCE_CONFLATION,),
    "c2_and_c3": (
        Cause.C2_VERSION_SCOPED_EVIDENCE_ID,
        Cause.C3_SEMANTIC_EVIDENCE_CONFLATION,
    ),
    "c4_no_document_rollup": (Cause.C4_DEPENDENCY_INVALIDATION_RULE,),
}


@dataclass(frozen=True, slots=True)
class PlanOutcome:
    """What one counterfactual's rebuild plan would have done."""

    label: str
    rebuilt: int
    total: int
    equivalent: bool
    stale_left_behind: int
    changed_ids: int

    @property
    def rebuild_fraction(self) -> float:
        return self.rebuilt / self.total if self.total else 0.0

    def as_record(self) -> dict[str, object]:
        return {
            "label": self.label,
            "rebuilt": self.rebuilt,
            "total": self.total,
            "rebuild_fraction": self.rebuild_fraction,
            "equivalent": self.equivalent,
            "stale_left_behind": self.stale_left_behind,
            "changed_ids": self.changed_ids,
        }


def attribute_changed_set(diff: SemanticDiff) -> dict[str, int]:
    """Which change kind is the *only* reason each id is in the changed set.

    An id reported by both `EVIDENCE_MOVED` and `MODIFIED_CLAIM` would be in the
    set either way, so it is attributed to neither exclusively; it lands under
    `multiple`. The number that matters is `evidence_moved_only`: ids that are
    in the traversal seed set because a unit moved and for no other reason.
    """
    by_id: dict[str, set[str]] = {}
    for change in diff.changes:
        if change.kind is ChangeKind.IDENTITY_UNRESOLVED or not change.logical_id:
            continue
        by_id.setdefault(change.logical_id, set()).add(change.kind.value)

    tally: dict[str, int] = {"total": len(by_id), "multiple": 0}
    for kinds in by_id.values():
        if len(kinds) > 1:
            tally["multiple"] += 1
            continue
        only = next(iter(kinds))
        tally[f"{only}_only"] = tally.get(f"{only}_only", 0) + 1
    return tally


def _stable_evidence_after(case: MutationCase) -> MutationCase:
    """C2: hand the after-version the before-version's evidence ids.

    Only where the unit genuinely did not move -- same anchor, same page. That
    restriction is the whole point: this asks what would happen if an evidence
    id were stable under a re-render, not what would happen if evidence ids were
    ignored. A unit that really did move keeps its new id and still reports
    `EVIDENCE_MOVED`, which is correct and must stay correct.
    """
    before_by_anchor = {unit.anchor: unit for unit in case.before.units}
    rebuilt = []
    for unit in case.after.units:
        prior = before_by_anchor.get(unit.anchor)
        if prior is not None and prior.page_number1 == unit.page_number1:
            rebuilt.append(replace(unit, evidence_id=prior.evidence_id))
        else:
            rebuilt.append(unit)
    return replace(case, after=replace(case.after, units=tuple(rebuilt)))


def _semantic_channel_only(diff: SemanticDiff) -> SemanticDiff:
    """C3: keep only the changes that assert a meaning change.

    `IDENTITY_UNRESOLVED` is kept deliberately. It is not a change, but
    `plan_recompilation` reads it separately to mark candidates unresolved, and
    dropping it would silently remove the fail-closed path this repository
    keeps. A counterfactual that improves the number by deleting a safety
    mechanism has measured nothing.
    """
    kept = tuple(
        change
        for change in diff.changes
        if change.kind in SEMANTIC_CHANGE_KINDS
        or change.kind is ChangeKind.MODIFIED_CLAIM
        or change.kind is ChangeKind.IDENTITY_UNRESOLVED
    )
    return SemanticDiff(
        level=diff.level,
        content_changed=diff.content_changed,
        changes=kept,
        change_id=f"{diff.change_id}~semantic",
    )


def _graph_without_rollup(case: MutationCase) -> _CaseGraph:
    """C4: the same graph with the document-level rollup removed.

    `art_doc` depends on every unit, so any single changed unit reaches it. If
    the fraction barely moves without it, breadth of the dependency rule is not
    what is driving the result.
    """
    edges: list[DependencyEdge] = []
    artifacts: list[str] = []
    unit_artifact: dict[str, str] = {}
    for unit in case.before.units:
        artifact = artifact_id_for(unit.logical_id)
        unit_artifact[unit.logical_id] = artifact
        artifacts.append(artifact)
        edges.append(
            DependencyEdge(
                source_id=artifact,
                target_id=unit.logical_id,
                edge_type=EdgeType.DERIVED_FROM,
            )
        )
    return _CaseGraph(
        graph=DependencyGraph(edges),
        artifacts=tuple(artifacts),
        unit_artifact=unit_artifact,
    )


def diff_for(case: MutationCase) -> SemanticDiff:
    return diff_documents(
        before_sha256=case.before.content_sha256,
        after_sha256=case.after.content_sha256,
        level=DiffLevel.GRAPH,
        before_shape=case.before.shape,
        after_shape=case.after.shape,
        before_units=case.before.units,
        after_units=case.after.units,
        source=case.before.source,
    )


def _outcome(
    label: str, case: MutationCase, diff: SemanticDiff, graph: _CaseGraph
) -> PlanOutcome:
    plan = plan_recompilation(diff=diff, graph=graph.graph, artifacts=graph.artifacts)
    full = _artifact_hashes(case, "after", graph)
    before_hashes = _artifact_hashes(case, "before", graph)
    planned = set(plan.to_rebuild)
    report = verify_equivalence(
        full_rebuild=full,
        selective_rebuild={a: full[a] for a in planned if a in full},
        carried_over={a: h for a, h in before_hashes.items() if a not in planned},
        plan=plan,
    )
    return PlanOutcome(
        label=label,
        rebuilt=len(planned),
        total=len(graph.artifacts),
        equivalent=report.equivalent,
        stale_left_behind=len(report.stale_left_behind),
        changed_ids=len(diff.changed_logical_ids),
    )


def run_counterfactuals(case: MutationCase) -> dict[str, PlanOutcome]:
    """Every counterfactual for one case, all through the core's public API."""
    graph = _CaseGraph.of(case)
    actual = diff_for(case)
    stable = diff_for(_stable_evidence_after(case))

    return {
        "actual": _outcome("actual", case, actual, graph),
        "c2_stable_evidence_ids": _outcome("c2_stable_evidence_ids", case, stable, graph),
        "c3_semantic_channel_only": _outcome(
            "c3_semantic_channel_only", case, _semantic_channel_only(actual), graph
        ),
        "c2_and_c3": _outcome(
            "c2_and_c3", case, _semantic_channel_only(stable), graph
        ),
        "c4_no_document_rollup": _outcome(
            "c4_no_document_rollup",
            case,
            _semantic_channel_only(actual),
            _graph_without_rollup(case),
        ),
    }


def evidence_id_is_version_scoped() -> dict[str, object]:
    """C1, stated as the design question it is rather than measured as a rate.

    `evidence_id()` refuses a document version that does not start with `dv_`
    (`identity.py:164`) and folds it into the digest (`identity.py:177`), so two
    versions of a unit that did not move **cannot** share an evidence id under
    the current scheme. Expressing one that is stable under re-render is not a
    parameter change; it needs a different derivation, and every id already
    issued was computed under `IDENTITY_SCHEME_VERSION = "1"`.
    """
    return {
        "cause": Cause.C1_EVIDENCE_IDENTITY_DESIGN.value,
        "question": (
            "Can an evidence identity that is stable under re-render be expressed "
            "under the current scheme at all?"
        ),
        "answer": "No, not without a new derivation and a scheme version bump.",
        "why": (
            "evidence_id() requires a dv_ prefixed document version "
            "(identity.py:164) and includes it in the digest (identity.py:177). "
            "The id is therefore a location *within one version* by construction, "
            "which is a coherent design -- it is what makes an evidence id "
            "unambiguous -- and it is also why an unchanged unit gets a new one."
        ),
        "cost_of_changing": (
            "IDENTITY_SCHEME_VERSION is 1 and every derived id was computed under "
            "it. identity.py:65 says an id computed under one scheme must never be "
            "silently compared against another, so this is a migration, not an "
            "edit."
        ),
        "not_concluded": (
            "Whether the design should change. That depends on the shares C2, C3 "
            "and C4 carry, which is what the counterfactuals measure."
        ),
    }
