"""The three arms of EXP-0101, reduced to one comparable record.

Contract §0.2: same corpus manifest, same split, same downstream configuration,
three arms. The arms disagree about almost everything internally -- one has no
element types, one has no abstention -- so this module is where each is mapped
onto a single vocabulary that the metrics can be computed over without
privileging the shape of any one of them.

The mapping is the part worth reviewing. Three decisions in it are load-bearing:

* **`IDENTITY_UNRESOLVED` is not a detected change.** It is recorded in its own
  field. `semantic_diff.py:195` already excludes it from `changed_logical_ids`
  precisely because it is a statement that nothing was established, and a
  metric that counted it as a detection would score an abstention as a success.
  It is also not counted as a false split; abstaining is the third outcome, not
  a failed merge.
* **`EVIDENCE_MOVED` is not a semantic change.** Every matched unit reports it
  on every version pair, because an evidence id is derived from the document
  version (`identity.py:177`) and therefore always differs. See the note in
  `run_arm`.
* **The baseline's output is projected into the core change vocabulary** rather
  than scored on its own terms, so the same `plan_recompilation` runs over all
  three arms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.identity import LogicalIdentityResolver, LogicalMatch, assign_one_to_one
from akc_cir.recompilation import (
    RecompilationPlan,
    content_hash,
    plan_recompilation,
    verify_equivalence,
)
from akc_cir.semantic_diff import (
    ChangeKind,
    DiffLevel,
    SemanticChange,
    SemanticDiff,
    diff_documents,
)

from .alignment import ALIGNMENT_SIGNAL_NAMES
from .baseline_xversion import baseline_diff
from .element_model import ElementType
from .evolution_suite import MutationCase
from .identity_bridge import AlignmentAwareResolver
from .type_reasoning import (
    CRITICAL_REFINEMENTS,
    SEMANTIC_CHANGE_KINDS,
    ChangeRefinement,
    refine,
)

__all__ = [
    "ARMS",
    "DOCUMENT_ARTIFACT",
    "Arm",
    "ArmOutcome",
    "ArmSpec",
    "RebuildOutcome",
    "artifact_id_for",
    "run_arm",
    "run_case",
]

#: The rollup artifact every unit feeds. One name, defined once, because the
#: metrics have to reconstruct the same artifact ids to score against gold.
DOCUMENT_ARTIFACT = "art_doc"


def artifact_id_for(logical_id: str) -> str:
    return f"art_{logical_id[-12:]}"


class Arm(StrEnum):
    CURRENT = "current"
    BASELINE = "baseline"
    CHALLENGER = "challenger"
    #: Contract ablation: -spatial signals.
    CHALLENGER_NO_SPATIAL = "challenger_no_spatial"
    #: Contract ablation: -type-specific reasoning.
    CHALLENGER_NO_TYPE_REASONING = "challenger_no_type_reasoning"
    #: Diagnostic ablation beyond the contract's four. It exists because the
    #: contract's four cannot say *which* alignment signal moved a result, and
    #: without that a regression is a number with no mechanism behind it.
    CHALLENGER_NO_CONTENT = "challenger_no_content"


@dataclass(frozen=True, slots=True)
class ArmSpec:
    arm: Arm
    uses_alignment: bool
    uses_type_reasoning: bool
    enabled_signals: frozenset[str] = frozenset(ALIGNMENT_SIGNAL_NAMES)


#: The contract's third ablation, "identity without alignment", is `CURRENT`
#: by definition -- the seven-signal resolver with nothing added. It is not run
#: as a fourth arm because it would be the same computation under a second name.
ARMS: tuple[ArmSpec, ...] = (
    ArmSpec(Arm.CURRENT, uses_alignment=False, uses_type_reasoning=False),
    ArmSpec(Arm.BASELINE, uses_alignment=True, uses_type_reasoning=True),
    ArmSpec(Arm.CHALLENGER, uses_alignment=True, uses_type_reasoning=True),
    ArmSpec(
        Arm.CHALLENGER_NO_SPATIAL,
        uses_alignment=True,
        uses_type_reasoning=True,
        enabled_signals=frozenset(ALIGNMENT_SIGNAL_NAMES) - {"align_spatial"},
    ),
    ArmSpec(
        Arm.CHALLENGER_NO_TYPE_REASONING,
        uses_alignment=True,
        uses_type_reasoning=False,
    ),
    ArmSpec(
        Arm.CHALLENGER_NO_CONTENT,
        uses_alignment=True,
        uses_type_reasoning=True,
        enabled_signals=frozenset(ALIGNMENT_SIGNAL_NAMES) - {"align_content"},
    ),
)

_NON_SEMANTIC_REFINEMENTS = frozenset(
    {ChangeRefinement.RENDERING_ONLY, ChangeRefinement.VALUE_ORDER_CHANGE}
)


@dataclass(frozen=True, slots=True)
class RebuildOutcome:
    """What a selective recompilation from this arm's diff would have done."""

    equivalent: bool
    rebuilt: int
    total: int
    stale_left_behind: tuple[str, ...] = ()

    @property
    def rebuild_fraction(self) -> float:
        return self.rebuilt / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class ArmOutcome:
    """One arm on one case, in the vocabulary the metrics are computed over."""

    case_id: str
    arm: Arm
    aligned_pairs: tuple[tuple[str, str], ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    unresolved_candidates: tuple[str, ...]
    semantic_change_ids: tuple[str, ...]
    critical_change_ids: tuple[str, ...]
    refinements: tuple[str, ...] = ()
    impacted: tuple[str, ...] = ()
    rebuild: RebuildOutcome | None = None

    @property
    def reports_semantic_change(self) -> bool:
        return bool(self.semantic_change_ids)

    def as_record(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "arm": self.arm.value,
            "aligned_pairs": [list(pair) for pair in self.aligned_pairs],
            "added": list(self.added),
            "removed": list(self.removed),
            "unresolved_candidates": list(self.unresolved_candidates),
            "semantic_change_ids": list(self.semantic_change_ids),
            "critical_change_ids": list(self.critical_change_ids),
            "refinements": list(self.refinements),
            "impacted": list(self.impacted),
            "rebuild": None
            if self.rebuild is None
            else {
                "equivalent": self.rebuild.equivalent,
                "rebuilt": self.rebuild.rebuilt,
                "total": self.rebuild.total,
                "stale_left_behind": list(self.rebuild.stale_left_behind),
            },
        }


@dataclass(frozen=True, slots=True)
class _CaseGraph:
    """A two-level artifact graph over one case's before-side units."""

    graph: DependencyGraph
    artifacts: tuple[str, ...]
    unit_artifact: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def of(case: MutationCase) -> _CaseGraph:
        edges: list[DependencyEdge] = []
        artifacts: list[str] = [DOCUMENT_ARTIFACT]
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
            edges.append(
                DependencyEdge(
                    source_id=DOCUMENT_ARTIFACT,
                    target_id=unit.logical_id,
                    edge_type=EdgeType.DERIVED_FROM,
                )
            )
        return _CaseGraph(
            graph=DependencyGraph(edges),
            artifacts=tuple(artifacts),
            unit_artifact=unit_artifact,
        )


def _element_types(case: MutationCase) -> dict[str, ElementType]:
    types: dict[str, ElementType] = {}
    for element in case.after.elements:
        types[element.logical_id] = element.element_type
    for element in case.before.elements:
        types.setdefault(element.logical_id, element.element_type)
    return types


def _artifact_hashes(case: MutationCase, side: str, graph: _CaseGraph) -> dict[str, str]:
    """Artifact content, derived from unit *text* and nothing positional.

    An artifact rebuilt from a clause that only moved would produce the same
    bytes, so a layout mutation must leave every hash alone. If position were in
    the hash, every arm would look equally correct on the layout classes and the
    equivalence check would be measuring the fixture.
    """
    version = case.before if side == "before" else case.after
    by_anchor = {unit.anchor: unit.text for unit in version.units}
    hashes: dict[str, str] = {}
    for unit in case.before.units:
        artifact = graph.unit_artifact[unit.logical_id]
        hashes[artifact] = content_hash(by_anchor.get(unit.anchor, ""))
    hashes[DOCUMENT_ARTIFACT] = content_hash(
        [by_anchor.get(unit.anchor, "") for unit in case.before.units]
    )
    return hashes


def _rebuild_outcome(
    case: MutationCase, plan: RecompilationPlan, graph: _CaseGraph
) -> RebuildOutcome:
    full = _artifact_hashes(case, "after", graph)
    before_hashes = _artifact_hashes(case, "before", graph)
    planned = set(plan.to_rebuild)
    selective = {artifact: full[artifact] for artifact in planned if artifact in full}
    carried = {
        artifact: digest
        for artifact, digest in before_hashes.items()
        if artifact not in planned
    }
    report = verify_equivalence(
        full_rebuild=full, selective_rebuild=selective, carried_over=carried, plan=plan
    )
    return RebuildOutcome(
        equivalent=report.equivalent,
        rebuilt=len(planned),
        total=len(graph.artifacts),
        stale_left_behind=report.stale_left_behind,
    )


def _baseline_as_diff(case: MutationCase) -> tuple[SemanticDiff, ArmOutcome]:
    result = baseline_diff(case.before.index, case.after.index)
    changes: list[SemanticChange] = []
    semantic_ids: list[str] = []
    critical_ids: list[str] = []
    refinements: list[str] = []
    for pair in result.pairs:
        if pair.refinement is None:
            continue
        refinements.append(pair.refinement.value)
        if pair.refinement in _NON_SEMANTIC_REFINEMENTS:
            continue
        semantic_ids.append(pair.before_logical_id)
        changes.append(
            SemanticChange(
                kind=ChangeKind.MODIFIED_CLAIM, logical_id=pair.before_logical_id
            )
        )
        if any(item in CRITICAL_REFINEMENTS for item in pair.fired):
            critical_ids.append(pair.before_logical_id)
    for logical_id in result.added:
        semantic_ids.append(logical_id)
        changes.append(SemanticChange(kind=ChangeKind.UNIT_ADDED, logical_id=logical_id))
    for logical_id in result.removed:
        semantic_ids.append(logical_id)
        changes.append(SemanticChange(kind=ChangeKind.UNIT_REMOVED, logical_id=logical_id))

    diff = SemanticDiff(
        level=DiffLevel.GRAPH,
        content_changed=True,
        changes=tuple(changes),
        change_id=f"baseline_{case.case_id}",
    )
    outcome = ArmOutcome(
        case_id=case.case_id,
        arm=Arm.BASELINE,
        aligned_pairs=result.aligned_pairs,
        added=result.added,
        removed=result.removed,
        unresolved_candidates=(),
        semantic_change_ids=tuple(dict.fromkeys(semantic_ids)),
        critical_change_ids=tuple(dict.fromkeys(critical_ids)),
        refinements=tuple(sorted(refinements)),
    )
    return diff, outcome


def run_arm(case: MutationCase, spec: ArmSpec, *, env: dict[str, str] | None = None) -> ArmOutcome:
    """Run one arm over one case and normalise its answer."""
    graph = _CaseGraph.of(case)

    if spec.arm is Arm.BASELINE:
        diff, outcome = _baseline_as_diff(case)
    else:
        resolver: LogicalIdentityResolver
        if spec.uses_alignment:
            resolver = AlignmentAwareResolver(
                before_index=case.before.index,
                after_index=case.after.index,
                enabled=spec.enabled_signals,
                env=env,
            )
        else:
            resolver = LogicalIdentityResolver()

        diff = diff_documents(
            before_sha256=case.before.content_sha256,
            after_sha256=case.after.content_sha256,
            level=DiffLevel.GRAPH,
            before_shape=case.before.shape,
            after_shape=case.after.shape,
            before_units=case.before.units,
            after_units=case.after.units,
            resolver=resolver,
            source=case.before.source,
        )
        outcome = _project_core_diff(case, spec, diff, resolver)

    report = graph.graph.impact_of(
        [uid for uid in outcome.semantic_change_ids if uid in graph.unit_artifact]
    )
    impacted = tuple(
        sorted(path.node_id for path in report.affected if path.node_id in set(graph.artifacts))
    )
    plan = plan_recompilation(diff=diff, graph=graph.graph, artifacts=graph.artifacts)
    return ArmOutcome(
        case_id=outcome.case_id,
        arm=outcome.arm,
        aligned_pairs=outcome.aligned_pairs,
        added=outcome.added,
        removed=outcome.removed,
        unresolved_candidates=outcome.unresolved_candidates,
        semantic_change_ids=outcome.semantic_change_ids,
        critical_change_ids=outcome.critical_change_ids,
        refinements=outcome.refinements,
        impacted=impacted,
        rebuild=_rebuild_outcome(case, plan, graph),
    )


def _project_core_diff(
    case: MutationCase,
    spec: ArmSpec,
    diff: SemanticDiff,
    resolver: LogicalIdentityResolver,
) -> ArmOutcome:
    lineage = case.before.source
    before_fingerprints = [
        unit.fingerprint(source_lineage=lineage) for unit in case.before.units
    ]
    after_fingerprints = [
        unit.fingerprint(source_lineage=lineage) for unit in case.after.units
    ]
    # The same call `diff_documents` makes internally, with the same resolver and
    # the same inputs, so the alignment reported here is the one the diff used.
    decisions = assign_one_to_one(
        after_fingerprints, before_fingerprints, resolver=resolver
    )

    pairs: list[tuple[str, str]] = []
    added: list[str] = []
    unresolved: list[str] = []
    matched_before: set[str] = set()
    for unit, decision in zip(case.after.units, decisions, strict=True):
        if decision.match is LogicalMatch.MATCHED and decision.logical_id:
            pairs.append((decision.logical_id, unit.logical_id))
            matched_before.add(decision.logical_id)
        elif decision.match is LogicalMatch.AMBIGUOUS:
            unresolved.extend(decision.candidates)
        else:
            added.append(unit.logical_id)
    unsettled = set(unresolved)
    removed = tuple(
        unit.logical_id
        for unit in case.before.units
        if unit.logical_id not in matched_before and unit.logical_id not in unsettled
    )

    semantic_ids: list[str] = []
    critical_ids: list[str] = []
    refinements: list[str] = []
    if spec.uses_type_reasoning:
        for refined in refine(diff, element_types=_element_types(case)):
            if refined.refinement is not None:
                refinements.append(refined.refinement.value)
            if refined.semantic and refined.logical_id:
                semantic_ids.append(refined.logical_id)
            if refined.critical and refined.logical_id:
                critical_ids.append(refined.logical_id)
    else:
        for change in diff.changes:
            if not change.logical_id:
                continue
            if change.kind in SEMANTIC_CHANGE_KINDS or change.kind is ChangeKind.MODIFIED_CLAIM:
                semantic_ids.append(change.logical_id)

    return ArmOutcome(
        case_id=case.case_id,
        arm=spec.arm,
        aligned_pairs=tuple(pairs),
        added=tuple(added),
        removed=removed,
        unresolved_candidates=tuple(dict.fromkeys(unresolved)),
        semantic_change_ids=tuple(dict.fromkeys(semantic_ids)),
        critical_change_ids=tuple(dict.fromkeys(critical_ids)),
        refinements=tuple(sorted(refinements)),
    )


def run_case(
    case: MutationCase, *, env: dict[str, str] | None = None
) -> dict[Arm, ArmOutcome]:
    return {spec.arm: run_arm(case, spec, env=env) for spec in ARMS}
