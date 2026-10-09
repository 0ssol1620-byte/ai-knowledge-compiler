"""Synthetic incremental scenarios, held to a from-scratch full rebuild.

Each scenario diffs two versions, plans a selective rebuild, and then compares
what the selective run produced against an oracle that rebuilds every artifact
from the new version with no access to the previous outputs. The oracle is the
judge; the plan is what is being judged.

Two kinds of number come out of every run and they are kept apart on purpose:

* `*_build_invocations` count calls to the expensive artifact callback. They are
  the only thing here that resembles work done.
* `plan.work_avoided` and `logical_artifacts_carried` count artifacts the plan
  chose not to rebuild. They are logical reuse, and a carried artifact that the
  oracle disagrees with is not a saving -- it is a stale answer.

Nothing in this file measures cost, and no assertion should be read as one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from akc_cir.authority import (
    AuthorityClass,
    ClaimContext,
    ResolutionStatus,
    ScopedClaim,
    resolve_authority,
)
from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.entity import (
    EntityMention,
    EntityRegistry,
    MergeVerdict,
    ResolutionTier,
    resolve_mention,
)
from akc_cir.recompilation import (
    ArtifactState,
    EquivalenceReport,
    RecompilationPlan,
    content_hash,
    plan_recompilation,
    verify_equivalence,
)
from akc_cir.semantic_diff import (
    ChangeKind,
    DiffLevel,
    DocumentShape,
    SemanticDiff,
    UnitSnapshot,
    diff_documents,
)
from akc_cir.temporal import (
    TemporalFact,
    TemporalPolicy,
    TemporalSource,
    TemporalTimeline,
)

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64

JAN1_2024 = datetime(2024, 1, 1, tzinfo=UTC)
JUN1_2025 = datetime(2025, 6, 1, tzinfo=UTC)
JAN1_2026 = datetime(2026, 1, 1, tzinfo=UTC)
JAN15_2026 = datetime(2026, 1, 15, tzinfo=UTC)
FEB1_2026 = datetime(2026, 2, 1, tzinfo=UTC)
MAR1_2026 = datetime(2026, 3, 1, tzinfo=UTC)
JUN1_2026 = datetime(2026, 6, 1, tzinfo=UTC)

TWO_YEARS = "The warranty covers parts and labour for two years from delivery."
THREE_YEARS = "The warranty covers parts and labour for three years from delivery."
SHIPPING = "Shipments are tendered to the earliest carrier."
WATER_COVERED = (
    "The warranty covers accidental water damage to the pump housing during normal operation."
)
WATER_NOT_COVERED = (
    "The warranty does not cover accidental water damage to the pump housing during "
    "normal operation."
)


def _unit(
    logical_id: str,
    text: str,
    *,
    path: tuple[str, ...] = ("Warranty", "Coverage"),
    anchor: str = "4.2 Exceptions",
    neighbours: tuple[str, ...] = ("4.1 Scope", "4.3 Claims"),
    evidence: str | None = "ev_one",
    page: int | None = 17,
    entities: frozenset[str] = frozenset(),
    relationships: frozenset[tuple[str, str, str]] = frozenset(),
    authority: str | None = None,
) -> UnitSnapshot:
    return UnitSnapshot(
        logical_id=logical_id,
        text=text,
        document_path=path,
        anchor=anchor,
        neighbour_anchors=neighbours,
        evidence_id=evidence,
        page_number1=page,
        entities=entities,
        relationships=relationships,
        authority=authority,
    )


def _shipping() -> UnitSnapshot:
    return _unit(
        "ku_shipping",
        SHIPPING,
        path=("Shipping",),
        anchor="9.1 Carriers",
        neighbours=(),
        evidence="ev_ship",
        page=30,
    )


def _pump() -> UnitSnapshot:
    return _unit(
        "ku_pump",
        "The M-012 pump is rated for 40 bar.",
        path=("Equipment", "Pumps"),
        anchor="8.1 Pumps",
        neighbours=(),
        evidence="ev_pump",
        page=5,
    )


# --------------------------------------------------------------------------
# Fixture machinery: versions, a workspace of artifacts, a counted builder
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Version:
    """One synthetic document version.

    `acl` exists because `UnitSnapshot` has no access-control field. It feeds the
    artifact builder only; the diff never sees it.
    """

    sha256: str
    units: tuple[UnitSnapshot, ...]
    acl: Mapping[str, str] = field(default_factory=dict)

    def by_id(self) -> dict[str, UnitSnapshot]:
        return {unit.logical_id: unit for unit in self.units}


@dataclass(frozen=True)
class _ArtifactSpec:
    """What an artifact is built from: units it reads, artifacts it consumes."""

    reads: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()


def _graph_for(workspace: Mapping[str, _ArtifactSpec]) -> DependencyGraph:
    """The dependency graph the plan walks, derived from the same specs the
    builder reads, so a missed edge would be a fixture bug rather than a hidden one.
    """
    edges: list[DependencyEdge] = []
    for artifact, spec in workspace.items():
        edges.extend(
            DependencyEdge(artifact, logical_id, EdgeType.DEPENDS_ON) for logical_id in spec.reads
        )
        edges.extend(
            DependencyEdge(upstream, artifact, EdgeType.CONSUMED_BY) for upstream in spec.consumes
        )
    return DependencyGraph(edges)


def _unit_inputs(workspace: Mapping[str, _ArtifactSpec], artifact_id: str) -> tuple[str, ...]:
    spec = workspace[artifact_id]
    found = set(spec.reads)
    for upstream in spec.consumes:
        found.update(_unit_inputs(workspace, upstream))
    return tuple(sorted(found))


class CountedArtifactBuilder:
    """Test-only stand-in for an artifact executor; production exposes none.

    `build` is the expensive callback. `expensive_build_invocations` counts how
    many times it actually ran and `invoked_for` records for which artifacts.
    Neither is derived from the plan, so the two can disagree and a test can see it.
    """

    def __init__(self, workspace: Mapping[str, _ArtifactSpec]) -> None:
        self._workspace = workspace
        self.expensive_build_invocations = 0
        self.invoked_for: list[str] = []

    def build(self, artifact_id: str, version: _Version) -> str:
        self.expensive_build_invocations += 1
        self.invoked_for.append(artifact_id)
        units = version.by_id()
        inputs: list[dict[str, object]] = []
        for logical_id in _unit_inputs(self._workspace, artifact_id):
            unit = units.get(logical_id)
            if unit is None:
                # A unit that is gone is part of the content: the artifact built
                # without it is not the artifact built with it.
                continue
            inputs.append(
                {
                    "logical_id": logical_id,
                    "text": unit.text,
                    "authority": unit.authority,
                    "acl": version.acl.get(logical_id),
                    "entities": sorted(unit.entities),
                    "relationships": [list(rel) for rel in sorted(unit.relationships)],
                    "evidence_id": unit.evidence_id,
                }
            )
        return content_hash({"artifact": artifact_id, "inputs": inputs})

    def build_all(self, artifact_ids: Iterable[str], version: _Version) -> dict[str, str]:
        return {artifact: self.build(artifact, version) for artifact in artifact_ids}


@dataclass(frozen=True)
class _IncrementalRun:
    diff: SemanticDiff
    plan: RecompilationPlan
    previous: dict[str, str]
    full_oracle: dict[str, str]
    selective: dict[str, str]
    carried: dict[str, str]
    report: EquivalenceReport
    #: Actual callback calls, per builder. The previous run's outputs had to be
    #: built once too; that count is reported, never subtracted from anything.
    baseline_build_invocations: int
    oracle_build_invocations: int
    selective_build_invocations: int
    selective_invoked_for: tuple[str, ...]

    @property
    def logical_artifacts_carried(self) -> int:
        """Artifacts reused untouched. Logical reuse, not measured work."""
        return len(self.carried)


def _run(
    workspace: Mapping[str, _ArtifactSpec],
    before: _Version,
    after: _Version,
    *,
    level: DiffLevel = DiffLevel.GRAPH,
) -> _IncrementalRun:
    inventory = list(workspace)
    diff = diff_documents(
        before_sha256=before.sha256,
        after_sha256=after.sha256,
        level=level,
        before_shape=DocumentShape(),
        after_shape=DocumentShape(),
        before_units=before.units,
        after_units=after.units,
    )
    plan = plan_recompilation(diff=diff, graph=_graph_for(workspace), artifacts=inventory)

    baseline = CountedArtifactBuilder(workspace)
    previous = baseline.build_all(inventory, before)

    # The oracle: a fresh builder, every artifact, the new version only. It never
    # sees the plan, the previous outputs or the selective outputs.
    oracle = CountedArtifactBuilder(workspace)
    full = oracle.build_all(inventory, after)

    selective_builder = CountedArtifactBuilder(workspace)
    selective = selective_builder.build_all(plan.to_rebuild, after)
    carried = {a: previous[a] for a in inventory if a not in plan.to_rebuild}

    report = verify_equivalence(
        full_rebuild=full, selective_rebuild=selective, carried_over=carried, plan=plan
    )
    return _IncrementalRun(
        diff=diff,
        plan=plan,
        previous=previous,
        full_oracle=full,
        selective=selective,
        carried=carried,
        report=report,
        baseline_build_invocations=baseline.expensive_build_invocations,
        oracle_build_invocations=oracle.expensive_build_invocations,
        selective_build_invocations=selective_builder.expensive_build_invocations,
        selective_invoked_for=tuple(selective_builder.invoked_for),
    )


def _kinds(diff: SemanticDiff) -> list[ChangeKind]:
    return [change.kind for change in diff.changes]


WARRANTY_WORKSPACE: dict[str, _ArtifactSpec] = {
    "chunk_88": _ArtifactSpec(reads=("ku_warranty",)),
    "chunk_89": _ArtifactSpec(reads=("ku_warranty",)),
    "vault_md": _ArtifactSpec(reads=("ku_warranty",)),
    "chunk_90": _ArtifactSpec(reads=("ku_shipping",)),
    "workflow_3": _ArtifactSpec(consumes=("chunk_88",)),
}
WARRANTY_DEPENDENTS = ("chunk_88", "chunk_89", "vault_md", "workflow_3")


# --------------------------------------------------------------------------
# Revised assertion -- the worked case, with the counters kept apart
# --------------------------------------------------------------------------


def _revised_run() -> _IncrementalRun:
    return _run(
        WARRANTY_WORKSPACE,
        _Version(A, (_unit("ku_warranty", TWO_YEARS), _shipping())),
        _Version(B, (_unit("ku_warranty", THREE_YEARS), _shipping())),
    )


def test_a_revised_assertion_is_one_modified_claim() -> None:
    run = _revised_run()

    assert _kinds(run.diff) == [ChangeKind.MODIFIED_CLAIM]
    assert run.diff.changed_logical_ids == ("ku_warranty",)
    assert run.diff.unresolved == ()


def test_a_revised_assertion_matches_the_full_rebuild_oracle() -> None:
    run = _revised_run()

    assert set(run.plan.stale) == set(WARRANTY_DEPENDENTS)
    assert run.plan.explain("chunk_90") == "no change reached it"
    assert run.report.equivalent is True
    assert run.report.stale_left_behind == ()
    assert run.report.unexpectedly_rebuilt == ()
    # Every rebuilt artifact really did change under the oracle; the carried one
    # really did not.
    for artifact in run.plan.to_rebuild:
        assert run.full_oracle[artifact] != run.previous[artifact]
    assert run.full_oracle["chunk_90"] == run.previous["chunk_90"]


def test_callback_invocations_and_logical_reuse_are_counted_separately() -> None:
    run = _revised_run()

    # Actual expensive calls.
    assert run.oracle_build_invocations == len(WARRANTY_WORKSPACE) == 5
    assert run.selective_build_invocations == 4
    assert sorted(run.selective_invoked_for) == sorted(run.plan.to_rebuild)
    assert run.baseline_build_invocations == 5
    # Logical reuse. Equal to work_avoided by construction, and not a cost figure.
    assert run.logical_artifacts_carried == run.plan.work_avoided == 1
    assert set(run.carried) == {"chunk_90"}


def test_a_revised_assertion_keeps_both_clocks() -> None:
    """A correction recorded in March replaces what was known, not what was valid."""
    timeline = TemporalTimeline(
        [
            TemporalFact(
                logical_id="ku_warranty",
                value="two years",
                valid_from=JAN1_2024,
                recorded_at=JAN1_2024,
                superseded_at=MAR1_2026,
                temporal_source=TemporalSource.EXPLICIT,
                evidence_id="ev_one",
            ),
            TemporalFact(
                logical_id="ku_warranty",
                value="three years",
                valid_from=JAN1_2024,
                recorded_at=MAR1_2026,
                temporal_source=TemporalSource.EXPLICIT,
                evidence_id="ev_one",
            ),
        ]
    )

    assert timeline.as_of(valid_at=JUN1_2025, known_at=FEB1_2026).values == ("two years",)
    assert timeline.as_of(valid_at=JUN1_2025, known_at=JUN1_2026).values == ("three years",)
    assert timeline.contradictions("ku_warranty") == ()
    assert [f.value for f in timeline.history("ku_warranty")] == ["two years", "three years"]


def test_the_whole_scenario_is_deterministic() -> None:
    first, second = _revised_run(), _revised_run()

    assert first.diff.change_id == second.diff.change_id
    assert first.plan.as_record() == second.plan.as_record()
    assert first.full_oracle == second.full_oracle
    assert first.report.as_record() == second.report.as_record()


# --------------------------------------------------------------------------
# Ambiguous merge -- an unsettled identity is rebuilt and labelled, never merged
# --------------------------------------------------------------------------


def _merge_run() -> _IncrementalRun:
    workspace = {
        "chunk_left": _ArtifactSpec(reads=("ku_left",)),
        "chunk_right": _ArtifactSpec(reads=("ku_right",)),
        "chunk_90": _ArtifactSpec(reads=("ku_shipping",)),
    }
    return _run(
        workspace,
        _Version(A, (_unit("ku_left", TWO_YEARS), _unit("ku_right", TWO_YEARS), _shipping())),
        _Version(B, (_unit("ku_incoming", THREE_YEARS), _shipping())),
    )


def test_an_ambiguous_unit_merge_is_unresolved_not_modified_or_removed() -> None:
    run = _merge_run()

    kinds = _kinds(run.diff)
    assert kinds == [ChangeKind.IDENTITY_UNRESOLVED]
    assert set(run.diff.unresolved[0].candidates) == {"ku_left", "ku_right"}
    assert run.diff.unresolved[0].logical_id is None
    assert run.diff.changed_logical_ids == ()


def test_an_ambiguous_unit_merge_rebuilds_both_candidates_and_says_why() -> None:
    run = _merge_run()

    assert run.plan.stale == ()
    assert set(run.plan.unresolved) == {"chunk_left", "chunk_right"}
    for artifact in ("chunk_left", "chunk_right"):
        target = next(t for t in run.plan.targets if t.artifact_id == artifact)
        assert target.state is ArtifactState.UNRESOLVED
        assert "could not settle" in target.reason
    assert run.report.equivalent is True
    # Rebuilding the unsettled pair is real work; only chunk_90 is logical reuse.
    assert run.selective_build_invocations == 2
    assert run.logical_artifacts_carried == run.plan.work_avoided == 1


def test_an_ambiguous_entity_merge_goes_to_review_and_the_system_cannot_execute_it() -> None:
    mention = EntityMention("m_new", "Acme", "ev_new", type_candidate="supplier")
    candidates = [
        ("ent_acme_corp", EntityMention("m1", "Acme", "ev_1", type_candidate="supplier")),
        ("ent_acme_inc", EntityMention("m2", "Acme", "ev_2", type_candidate="supplier")),
    ]

    decision = resolve_mention(mention, candidates)

    assert decision.verdict is MergeVerdict.REVIEW
    assert decision.entity_id is None
    assert set(decision.candidates) == {"ent_acme_corp", "ent_acme_inc"}

    registry = EntityRegistry()
    registry.add("ent_acme_corp", "m1")
    registry.add("ent_acme_inc", "m2")
    with pytest.raises(ValueError, match="named human reviewer"):
        registry.merge(
            merge_id="mg_1", into="ent_acme_corp", absorbed="ent_acme_inc", decision=decision
        )
    assert registry.members("ent_acme_corp") == ("m1",)
    assert registry.members("ent_acme_inc") == ("m2",)
    assert registry.merges == ()


def test_a_high_risk_resemblance_is_not_an_identifier() -> None:
    decision = resolve_mention(
        EntityMention("m_new", "Acme", "ev_new", type_candidate="supplier"),
        [("ent_acme", EntityMention("m1", "Acme", "ev_1", type_candidate="supplier"))],
    )

    assert decision.verdict is MergeVerdict.REVIEW
    assert decision.tier is ResolutionTier.NAME_SIMILARITY
    assert decision.merged is False


# --------------------------------------------------------------------------
# Ambiguous split -- the old identity is not quietly continued or deleted
# --------------------------------------------------------------------------


def _split_run() -> _IncrementalRun:
    workspace = {
        "chunk_w": _ArtifactSpec(reads=("ku_warranty",)),
        "chunk_90": _ArtifactSpec(reads=("ku_shipping",)),
    }
    halves = (
        _unit(
            "ku_split_a",
            "The warranty covers parts for two years from delivery.",
            anchor="4.2a Parts",
            neighbours=("4.1 Scope", "4.2b Labour"),
        ),
        _unit(
            "ku_split_b",
            "The warranty covers labour for two years from delivery.",
            anchor="4.2b Labour",
            neighbours=("4.2a Parts", "4.3 Claims"),
        ),
    )
    return _run(
        workspace,
        _Version(A, (_unit("ku_warranty", TWO_YEARS), _shipping())),
        _Version(B, (*halves, _shipping())),
    )


def test_an_ambiguous_split_leaves_the_old_identity_unresolved() -> None:
    run = _split_run()

    unresolved = run.diff.unresolved
    assert len(unresolved) == 1
    assert unresolved[0].candidates == ("ku_warranty",)
    assert "ku_warranty" not in run.diff.changed_logical_ids
    for change in run.diff.changes:
        if change.kind in {ChangeKind.MODIFIED_CLAIM, ChangeKind.UNIT_REMOVED}:
            assert change.logical_id != "ku_warranty"
    added = {c.logical_id for c in run.diff.changes if c.kind is ChangeKind.UNIT_ADDED}
    assert added <= {"ku_split_a", "ku_split_b"}


def test_an_ambiguous_split_rebuilds_the_dependent_and_matches_the_oracle() -> None:
    run = _split_run()

    assert run.plan.unresolved == ("chunk_w",)
    assert "chunk_w" not in run.plan.stale
    assert run.carried.keys() == {"chunk_90"}
    assert run.report.equivalent is True
    assert run.selective_invoked_for == ("chunk_w",)


def test_an_entity_split_is_an_entity_change_and_a_merge_is_reversible() -> None:
    registry = EntityRegistry()
    registry.add("ent_acme_corp", "m1")
    registry.add("ent_acme_inc", "m2")
    erp = {"erp": "V-100"}
    decision = resolve_mention(
        EntityMention("m2", "Acme Inc", "ev_2", external_ids=erp),
        [("ent_acme_corp", EntityMention("m1", "Acme Corp", "ev_1", external_ids=erp))],
    )
    assert decision.verdict is MergeVerdict.AUTO_MERGE
    assert decision.tier is ResolutionTier.SYSTEM_OF_RECORD

    registry.merge(
        merge_id="mg_1", into="ent_acme_corp", absorbed="ent_acme_inc", decision=decision
    )
    registry.unmerge("mg_1")

    assert registry.members("ent_acme_corp") == ("m1",)
    assert registry.members("ent_acme_inc") == ("m2",)

    def acme(entities: frozenset[str]) -> UnitSnapshot:
        return _unit(
            "ku_acme",
            "Acme supplies pumps to Plant B.",
            path=("Supply chain", "Vendors"),
            anchor="7.1 Vendors",
            neighbours=(),
            entities=entities,
        )

    # Built from pairs so a repeated artifact id fails loudly instead of the
    # later spec silently replacing the earlier one in a dict literal.
    inventory = (
        ("entity_page_acme", _ArtifactSpec(reads=("ku_acme",))),
        ("chunk_pump", _ArtifactSpec(reads=("ku_pump",))),
    )
    workspace = dict(inventory)
    assert len(workspace) == len(inventory)

    run = _run(
        workspace,
        _Version(A, (acme(frozenset({"ent_acme_corp"})), _pump())),
        _Version(B, (acme(frozenset({"ent_acme_corp", "ent_acme_inc"})), _pump())),
    )

    assert _kinds(run.diff) == [ChangeKind.ENTITY_CHANGED]
    assert run.plan.stale == ("entity_page_acme",)
    assert run.carried.keys() == {"chunk_pump"}
    assert run.report.equivalent is True


# --------------------------------------------------------------------------
# Removed bridge evidence -- the link and everything consuming it goes stale
# --------------------------------------------------------------------------


def _bridge_run() -> _IncrementalRun:
    supplies = frozenset({("acme", "supplies", "m012")})
    acme_kwargs = {
        "path": ("Supply chain", "Vendors"),
        "anchor": "7.1 Vendors",
        "neighbours": (),
        "evidence": "ev_acme",
        "page": 3,
    }
    acme_text = "Acme Corp is an approved vendor for pumps."
    bridge = _unit(
        "ku_bridge",
        "Acme Corp supplies the M-012 pump installed at Plant B.",
        path=("Supply chain", "Plant B"),
        anchor="7.2 Bridge",
        neighbours=(),
        evidence="ev_bridge",
        page=3,
        relationships=supplies,
    )
    workspace = {
        "chunk_acme": _ArtifactSpec(reads=("ku_acme",)),
        "chunk_bridge": _ArtifactSpec(reads=("ku_bridge",)),
        "rel_acme_m012": _ArtifactSpec(reads=("ku_acme", "ku_bridge")),
        "workflow_sourcing": _ArtifactSpec(consumes=("rel_acme_m012",)),
        "chunk_pump": _ArtifactSpec(reads=("ku_pump",)),
    }
    return _run(
        workspace,
        _Version(
            A,
            (_unit("ku_acme", acme_text, relationships=supplies, **acme_kwargs), bridge, _pump()),
        ),
        _Version(B, (_unit("ku_acme", acme_text, **acme_kwargs), _pump())),
    )


def test_removed_bridge_evidence_is_a_removal_and_a_lost_relationship() -> None:
    run = _bridge_run()

    removed = [c for c in run.diff.changes if c.kind is ChangeKind.UNIT_REMOVED]
    assert [c.logical_id for c in removed] == ["ku_bridge"]
    lost = [c for c in run.diff.changes if c.kind is ChangeKind.RELATIONSHIP_REMOVED]
    assert [(c.logical_id, c.before) for c in lost] == [("ku_acme", "acme supplies m012")]
    assert run.diff.unresolved == ()
    assert set(run.diff.changed_logical_ids) == {"ku_acme", "ku_bridge"}


def test_removed_bridge_evidence_reaches_the_consuming_workflow() -> None:
    run = _bridge_run()

    assert set(run.plan.stale) == {
        "chunk_acme",
        "chunk_bridge",
        "rel_acme_m012",
        "workflow_sourcing",
    }
    reason = run.plan.explain("workflow_sourcing")
    assert reason and "rel_acme_m012" in reason
    assert run.carried.keys() == {"chunk_pump"}
    assert run.report.equivalent is True
    assert run.full_oracle["rel_acme_m012"] != run.previous["rel_acme_m012"]


# --------------------------------------------------------------------------
# Authority- and ACL-only change -- where a carried artifact goes quietly stale
# --------------------------------------------------------------------------


def _authority_versions() -> tuple[_Version, _Version]:
    return (
        _Version(A, (_unit("ku_warranty", TWO_YEARS, authority="informal"), _shipping())),
        _Version(B, (_unit("ku_warranty", TWO_YEARS, authority="contractual"), _shipping())),
    )


def test_an_authority_only_change_is_seen_at_graph_level_and_rebuilt() -> None:
    run = _run(WARRANTY_WORKSPACE, *_authority_versions(), level=DiffLevel.GRAPH)

    assert _kinds(run.diff) == [ChangeKind.AUTHORITY_CHANGED]
    assert run.diff.changed_logical_ids == ("ku_warranty",)
    assert set(run.plan.stale) == set(WARRANTY_DEPENDENTS)
    assert run.report.equivalent is True


def test_a_text_level_plan_leaves_authority_artifacts_stale_and_the_oracle_says_so() -> None:
    """The deliberately stale carry. L3 cannot see authority, so its plan reuses
    every artifact; zero callback invocations here is a wrong answer, not a saving.
    """
    run = _run(WARRANTY_WORKSPACE, *_authority_versions(), level=DiffLevel.SEMANTIC)

    assert run.diff.content_changed is True
    assert ChangeKind.AUTHORITY_CHANGED not in _kinds(run.diff)
    assert run.selective_build_invocations == 0
    assert run.logical_artifacts_carried == 5

    assert run.report.equivalent is False
    assert run.report.stale_left_behind == ("chunk_88", "chunk_89", "vault_md", "workflow_3")
    assert set(run.report.diverged) == set(run.report.stale_left_behind)
    assert "chunk_90" not in run.report.diverged


def test_an_acl_only_change_left_carried_is_caught_by_the_oracle() -> None:
    """`UnitSnapshot` has no ACL channel, so no diff level can name this change.
    The equivalence oracle is what refuses the carried artifacts.
    """
    units = (_unit("ku_warranty", TWO_YEARS, authority="contractual"), _shipping())
    run = _run(
        WARRANTY_WORKSPACE,
        _Version(A, units),
        _Version(B, units, acl={"ku_warranty": "legal:read"}),
    )

    assert run.report.equivalent is False
    assert run.report.stale_left_behind == ("chunk_88", "chunk_89", "vault_md", "workflow_3")


def test_a_permission_the_asker_lacks_removes_the_claim_rather_than_ranking_it() -> None:
    claim = ScopedClaim(
        claim_id="c_warranty",
        subject="warranty",
        value="two years",
        authority=AuthorityClass.CONTRACTUAL,
        required_permission="legal:read",
        evidence_id="ev_one",
    )

    hidden = resolve_authority([claim], ClaimContext(subject="warranty", as_of=JUN1_2026))
    shown = resolve_authority(
        [claim],
        ClaimContext(subject="warranty", as_of=JUN1_2026, permissions=frozenset({"legal:read"})),
    )

    assert hidden.status is ResolutionStatus.NO_CANDIDATE
    assert hidden.claim is None
    assert hidden.permission_filtered == 1
    assert hidden.as_record()["value"] is None
    assert shown.status is ResolutionStatus.RESOLVED
    assert shown.claim == claim


def test_an_authority_change_decides_on_authority_not_recency() -> None:
    informal = ScopedClaim(
        claim_id="c_informal",
        subject="warranty",
        value="two years",
        authority=AuthorityClass.INFORMAL,
        recorded_at=JUN1_2026,
        evidence_id="ev_one",
    )
    contractual = ScopedClaim(
        claim_id="c_contract",
        subject="warranty",
        value="three years",
        authority=AuthorityClass.CONTRACTUAL,
        recorded_at=JAN15_2026,
        evidence_id="ev_two",
    )

    resolution = resolve_authority(
        [informal, contractual], ClaimContext(subject="warranty", as_of=JUN1_2026)
    )

    assert resolution.status is ResolutionStatus.RESOLVED
    assert resolution.claim == contractual
    assert "authority_rank" in resolution.reason


# --------------------------------------------------------------------------
# Historical and current statements
# --------------------------------------------------------------------------


def _historical_timeline() -> TemporalTimeline:
    return TemporalTimeline(
        [
            TemporalFact(
                logical_id="ku_warranty",
                value="two years",
                valid_from=JAN1_2024,
                valid_to=JAN1_2026,
                recorded_at=JAN15_2026,
                temporal_source=TemporalSource.EXPLICIT,
            ),
            TemporalFact(
                logical_id="ku_warranty",
                value="three years",
                valid_from=JAN1_2026,
                recorded_at=JAN15_2026,
                temporal_source=TemporalSource.EXPLICIT,
            ),
            # "Previously the warranty was shorter." No date given, none invented.
            TemporalFact(
                logical_id="ku_warranty_history",
                value="a shorter warranty",
                recorded_at=JAN15_2026,
            ),
        ]
    )


def test_historical_and_current_statements_answer_different_moments() -> None:
    timeline = _historical_timeline()

    assert timeline.as_of(valid_at=JUN1_2025, logical_id="ku_warranty").values == ("two years",)
    assert timeline.as_of(valid_at=JUN1_2026, logical_id="ku_warranty").values == ("three years",)
    assert timeline.contradictions("ku_warranty") == ()


def test_an_undated_historical_statement_is_not_treated_as_current() -> None:
    timeline = _historical_timeline()

    default = timeline.as_of(valid_at=JUN1_2026)
    assert "a shorter warranty" not in default.values
    assert default.excluded_unknown == ("ku_warranty_history",)

    included = timeline.as_of(valid_at=JUN1_2026, policy=TemporalPolicy.INCLUDE_UNKNOWN)
    assert "a shorter warranty" in included.values
    assert included.included_unknown == ("ku_warranty_history",)
    assert "include_unknown" in included.describe()


def test_historical_dependency_edges_propagate_only_inside_their_window() -> None:
    graph = DependencyGraph(
        [
            DependencyEdge(
                "chunk_2025_terms",
                "ku_warranty",
                EdgeType.DEPENDS_ON,
                valid_from=JAN1_2024,
                valid_to=JAN1_2026,
            ),
            DependencyEdge(
                "chunk_current_terms", "ku_warranty", EdgeType.DEPENDS_ON, valid_from=JAN1_2026
            ),
        ]
    )

    assert graph.impact_of(["ku_warranty"], as_of=JUN1_2026).affected_ids == (
        "chunk_current_terms",
    )
    assert graph.impact_of(["ku_warranty"], as_of=JUN1_2025).affected_ids == ("chunk_2025_terms",)

    # plan_recompilation takes no as_of, so it walks every edge: conservative,
    # and the current artifact is certainly in the rebuild.
    diff = diff_documents(
        before_sha256=A,
        after_sha256=B,
        level=DiffLevel.SEMANTIC,
        before_shape=DocumentShape(),
        after_shape=DocumentShape(),
        before_units=[_unit("ku_warranty", TWO_YEARS)],
        after_units=[_unit("ku_warranty", THREE_YEARS)],
    )
    plan = plan_recompilation(
        diff=diff, graph=graph, artifacts=["chunk_2025_terms", "chunk_current_terms"]
    )
    assert "chunk_current_terms" in plan.to_rebuild


# --------------------------------------------------------------------------
# Negated statements
# --------------------------------------------------------------------------


def _water_workspace() -> dict[str, _ArtifactSpec]:
    return {
        "chunk_water": _ArtifactSpec(reads=("ku_water",)),
        "chunk_90": _ArtifactSpec(reads=("ku_shipping",)),
    }


def test_a_negated_statement_is_a_modified_claim_not_reformatting() -> None:
    run = _run(
        _water_workspace(),
        _Version(A, (_unit("ku_water", WATER_COVERED, anchor="4.5 Water"), _shipping())),
        _Version(B, (_unit("ku_water", WATER_NOT_COVERED, anchor="4.5 Water"), _shipping())),
    )

    modified = [c for c in run.diff.changes if c.kind is ChangeKind.MODIFIED_CLAIM]
    assert len(modified) == 1
    assert modified[0].logical_id == "ku_water"
    assert "does not cover" in (modified[0].after or "")
    assert run.plan.stale == ("chunk_water",)
    assert run.report.equivalent is True


def test_a_short_negation_that_unsettles_identity_stays_unresolved() -> None:
    """Few tokens, so the negation drags the score into the review band."""
    run = _run(
        _water_workspace(),
        _Version(A, (_unit("ku_water", "The warranty covers water damage."), _shipping())),
        _Version(
            B, (_unit("ku_water", "The warranty does not cover water damage."), _shipping())
        ),
    )

    assert _kinds(run.diff) == [ChangeKind.IDENTITY_UNRESOLVED]
    assert run.diff.unresolved[0].candidates == ("ku_water",)
    assert run.diff.changed_logical_ids == ()
    assert run.plan.unresolved == ("chunk_water",)
    assert run.report.equivalent is True


def test_an_unretracted_negation_contradicts_the_original() -> None:
    covered = TemporalFact(
        logical_id="ku_water",
        value="covers water damage",
        valid_from=JAN1_2026,
        recorded_at=JAN1_2026,
        temporal_source=TemporalSource.EXPLICIT,
    )
    negated = TemporalFact(
        logical_id="ku_water",
        value="does not cover water damage",
        valid_from=JAN1_2026,
        recorded_at=MAR1_2026,
        temporal_source=TemporalSource.EXPLICIT,
    )
    retracted = TemporalFact(
        logical_id="ku_water",
        value="covers water damage",
        valid_from=JAN1_2026,
        recorded_at=JAN1_2026,
        superseded_at=MAR1_2026,
        temporal_source=TemporalSource.EXPLICIT,
    )

    assert TemporalTimeline([covered, negated]).contradictions("ku_water")
    assert TemporalTimeline([retracted, negated]).contradictions("ku_water") == ()
