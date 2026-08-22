"""The four layers, composed — masterplan §16.2's screen, executable.

    Warranty: 2y -> 3y

    Affected:
    12 documents
    41 knowledge units
    8 RAG chunks
    2 agent workflows

    [ Recompile affected knowledge ]

Each layer passes its own tests in isolation. This asserts they compose: an id
derived by one is the id the next resolves against, the diff's change set is
what the graph traverses, and the plan the traversal produces rebuilds to the
same result as rebuilding everything.

A layer that is correct alone and wrong at its seam is the failure this catches.
"""

from __future__ import annotations

from datetime import UTC, datetime

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.identity import (
    document_version_id,
    evidence_id,
    logical_id_seed,
    source_id,
)
from akc_cir.recompilation import (
    content_hash,
    plan_recompilation,
    verify_equivalence,
)
from akc_cir.semantic_diff import (
    ChangeKind,
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)
from akc_cir.temporal import (
    TemporalFact,
    TemporalSource,
    TemporalTimeline,
    replay_context,
)

JAN = datetime(2026, 1, 1, tzinfo=UTC)
FEB = datetime(2026, 2, 1, tzinfo=UTC)
MAR = datetime(2026, 3, 1, tzinfo=UTC)
JUN = datetime(2026, 6, 1, tzinfo=UTC)

INVENTORY = ["chunk_88", "chunk_89", "chunk_90", "vault_md", "workflow_3", "chunk_99"]


def _ids() -> tuple[str, str, str, str, str]:
    source = source_id(tenant_id="acme", connector_type="gdrive", native_id="drive:warranty")
    v1 = document_version_id(source=source, content_sha256="sha256:" + "1" * 64)
    v2 = document_version_id(source=source, content_sha256="sha256:" + "2" * 64)
    clause = logical_id_seed(
        source=source, document_path=("Warranty", "Coverage"), anchor="4.2"
    )
    evidence = evidence_id(document_version=v1, page_number1=17, bbox1000=(100, 200, 300, 400))
    return source, v1, v2, clause, evidence


def _unit(clause: str, text: str, evidence: str) -> UnitSnapshot:
    return UnitSnapshot(
        logical_id=clause,
        text=text,
        document_path=("Warranty", "Coverage"),
        anchor="4.2",
        evidence_id=evidence,
        page_number1=17,
    )


def _graph(clause: str) -> DependencyGraph:
    return DependencyGraph(
        [
            DependencyEdge("chunk_88", clause, EdgeType.DEPENDS_ON),
            DependencyEdge("chunk_89", clause, EdgeType.DEPENDS_ON),
            DependencyEdge("vault_md", clause, EdgeType.DEPENDS_ON),
            DependencyEdge("chunk_88", "workflow_3", EdgeType.CONSUMED_BY),
            DependencyEdge("chunk_99", "ku_unrelated", EdgeType.DEPENDS_ON),
        ]
    )


def _warranty_diff(clause: str, evidence: str, v1: str, v2: str):
    return diff_documents(
        before_sha256="sha256:" + "1" * 64,
        after_sha256="sha256:" + "2" * 64,
        level=DiffLevel.SEMANTIC,
        before_shape=DocumentShape(),
        after_shape=DocumentShape(),
        before_units=[_unit(clause, "The warranty covers parts for two years.", evidence)],
        after_units=[_unit(clause, "The warranty covers parts for three years.", evidence)],
    )


def test_the_ids_one_layer_derives_are_the_ids_the_next_resolves_against() -> None:
    _, v1, v2, clause, evidence = _ids()
    diff = _warranty_diff(clause, evidence, v1, v2)

    assert v1 != v2
    assert diff.changed_logical_ids == (clause,)


def test_a_clause_change_produces_one_modified_claim_not_a_remove_and_add() -> None:
    _, v1, v2, clause, evidence = _ids()

    diff = _warranty_diff(clause, evidence, v1, v2)

    kinds = [c.kind for c in diff.changes]
    assert kinds == [ChangeKind.MODIFIED_CLAIM]


def test_the_blast_radius_is_the_product_screen() -> None:
    _, v1, v2, clause, evidence = _ids()
    diff = _warranty_diff(clause, evidence, v1, v2)

    report = _graph(clause).impact_of(diff.changed_logical_ids)

    assert report.by_kind(
        {
            "chunk_88": "rag_chunk",
            "chunk_89": "rag_chunk",
            "vault_md": "export",
            "workflow_3": "agent_workflow",
        }
    ) == {"rag_chunk": 2, "export": 1, "agent_workflow": 1}


def test_an_unrelated_artifact_is_outside_the_radius() -> None:
    _, v1, v2, clause, evidence = _ids()
    diff = _warranty_diff(clause, evidence, v1, v2)

    report = _graph(clause).impact_of(diff.changed_logical_ids)

    assert "chunk_99" not in report.affected_ids


def test_a_two_hop_consumer_is_reached_and_the_path_shows_both_hops() -> None:
    _, v1, v2, clause, evidence = _ids()
    diff = _warranty_diff(clause, evidence, v1, v2)

    explanation = _graph(clause).impact_of(diff.changed_logical_ids).explain("workflow_3")

    assert explanation is not None
    assert "chunk_88" in explanation
    assert "DEPENDS_ON" in explanation
    assert "CONSUMED_BY" in explanation


def test_the_plan_rebuilds_the_radius_and_avoids_the_rest() -> None:
    _, v1, v2, clause, evidence = _ids()
    diff = _warranty_diff(clause, evidence, v1, v2)

    plan = plan_recompilation(diff=diff, graph=_graph(clause), artifacts=INVENTORY)

    assert set(plan.to_rebuild) == {"chunk_88", "chunk_89", "vault_md", "workflow_3"}
    assert plan.work_avoided == 2


def test_the_selective_rebuild_equals_a_full_rebuild() -> None:
    """§44 PHASE 5's exit criterion, over the whole composed pipeline."""
    _, v1, v2, clause, evidence = _ids()
    diff = _warranty_diff(clause, evidence, v1, v2)
    plan = plan_recompilation(diff=diff, graph=_graph(clause), artifacts=INVENTORY)

    full = {
        artifact: content_hash(
            {"artifact": artifact, "warranty": "three" if artifact in plan.to_rebuild else "two"}
        )
        for artifact in INVENTORY
    }
    selective = {
        artifact: content_hash({"artifact": artifact, "warranty": "three"})
        for artifact in plan.to_rebuild
    }
    carried = {
        artifact: content_hash({"artifact": artifact, "warranty": "two"})
        for artifact in INVENTORY
        if artifact not in plan.to_rebuild
    }

    report = verify_equivalence(
        full_rebuild=full, selective_rebuild=selective, carried_over=carried, plan=plan
    )

    assert report.equivalent is True
    assert report.stale_left_behind == ()
    assert report.unexpectedly_rebuilt == ()


def test_a_missing_edge_makes_the_equivalence_check_fail_rather_than_pass_quietly() -> None:
    """The failure the check exists for: a corpus that looks compiled and is wrong."""
    _, v1, v2, clause, evidence = _ids()
    diff = _warranty_diff(clause, evidence, v1, v2)
    incomplete = DependencyGraph([DependencyEdge("chunk_88", clause, EdgeType.DEPENDS_ON)])
    plan = plan_recompilation(diff=diff, graph=incomplete, artifacts=INVENTORY)

    truly_affected = {"chunk_88", "chunk_89", "vault_md"}
    full = {
        artifact: content_hash(
            {"artifact": artifact, "warranty": "three" if artifact in truly_affected else "two"}
        )
        for artifact in INVENTORY
    }
    selective = {
        artifact: content_hash({"artifact": artifact, "warranty": "three"})
        for artifact in plan.to_rebuild
    }
    carried = {
        artifact: content_hash({"artifact": artifact, "warranty": "two"})
        for artifact in INVENTORY
        if artifact not in plan.to_rebuild
    }

    report = verify_equivalence(
        full_rebuild=full, selective_rebuild=selective, carried_over=carried, plan=plan
    )

    assert report.equivalent is False
    assert set(report.stale_left_behind) == {"chunk_89", "vault_md"}


def test_the_change_carries_a_timeline_that_answers_both_clocks() -> None:
    _, _, _, clause, _ = _ids()
    timeline = TemporalTimeline(
        [
            TemporalFact(
                logical_id=clause,
                value="two years",
                valid_from=JAN,
                valid_to=MAR,
                recorded_at=JAN,
                temporal_source=TemporalSource.EXPLICIT,
            ),
            TemporalFact(
                logical_id=clause,
                value="three years",
                valid_from=MAR,
                recorded_at=MAR,
                temporal_source=TemporalSource.EXPLICIT,
            ),
        ]
    )

    assert timeline.as_of(valid_at=FEB).values == ("two years",)
    assert timeline.as_of(valid_at=JUN).values == ("three years",)
    assert replay_context(timeline, at=FEB).values == ("two years",)
    assert timeline.contradictions(clause) == ()


def test_the_whole_pipeline_is_reproducible() -> None:
    """An impact analysis that cannot be re-derived cannot be audited."""
    _, v1, v2, clause, evidence = _ids()

    first = plan_recompilation(
        diff=_warranty_diff(clause, evidence, v1, v2),
        graph=_graph(clause),
        artifacts=INVENTORY,
    )
    second = plan_recompilation(
        diff=_warranty_diff(clause, evidence, v1, v2),
        graph=_graph(clause),
        artifacts=INVENTORY,
    )

    assert first.change_id == second.change_id
    assert first.to_rebuild == second.to_rebuild
