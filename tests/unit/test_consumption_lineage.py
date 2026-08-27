from __future__ import annotations

from akc_cir.consumption_lineage import (
    ConsumptionReceipt,
    consumption_dependency_edges,
    trace_stale_consumptions,
)
from akc_cir.dependency import (
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)


def _receipt(
    consumption_id: str,
    units: tuple[str, ...],
    *,
    world_state_id: str = "world-7",
    downstream_action_ref: str | None = None,
) -> ConsumptionReceipt:
    return ConsumptionReceipt(
        consumption_id=consumption_id,
        world_state_id=world_state_id,
        consumed_unit_ids=units,
        answer_claim_ids=(f"claim:{consumption_id}",),
        response_hash=f"sha256:{consumption_id}",
        downstream_action_ref=downstream_action_ref,
    )


def test_consumption_edges_are_explicit_typed_lineage() -> None:
    receipt = _receipt("answer-1", ("answer:warranty", "claim:exception"))
    edges = consumption_dependency_edges(receipt)

    assert len(edges) == 2
    assert all(edge.edge_type is EdgeType.CONSUMED_BY for edge in edges)
    assert {edge.source_id for edge in edges} == {"answer:warranty", "claim:exception"}
    assert {edge.target_id for edge in edges} == {"consumption:answer-1"}


def test_semantic_change_traces_exact_prior_answer_with_reason_path_and_world() -> None:
    affected = _receipt(
        "answer-affected",
        ("answer:warranty",),
        downstream_action_ref="agent-action-91",
    )
    unrelated = _receipt("answer-unrelated", ("answer:shipping",))
    graph = DependencyGraph(
        [
            DependencyEdge(
                source_id="answer:warranty",
                target_id="claim:warranty",
                edge_type=EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.SEMANTIC}),
            ),
            *consumption_dependency_edges(affected),
            *consumption_dependency_edges(unrelated),
        ]
    )

    risks = trace_stale_consumptions(
        changed_ids=["claim:warranty"],
        graph=graph,
        receipts=[affected, unrelated],
        candidate_world_state_id="world-8",
    )

    assert len(risks) == 1
    risk = risks[0]
    assert risk.consumption_id == "answer-affected"
    assert risk.source_world_state_id == "world-7"
    assert risk.candidate_world_state_id == "world-8"
    assert risk.downstream_action_ref == "agent-action-91"
    assert "claim:warranty" in risk.reason_path
    assert "answer:warranty" in risk.reason_path
    assert risk.affected_node_id == "consumption:answer-affected"


def test_receipt_is_not_marked_stale_without_explicit_consumed_by_edge() -> None:
    receipt = _receipt("unproven", ("answer:warranty",))
    graph = DependencyGraph(
        [
            DependencyEdge(
                source_id="answer:warranty",
                target_id="claim:warranty",
                edge_type=EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.SEMANTIC}),
            )
        ]
    )

    risks = trace_stale_consumptions(
        changed_ids=["claim:warranty"],
        graph=graph,
        receipts=[receipt],
        candidate_world_state_id="world-8",
    )

    assert risks == ()


def test_locator_only_change_does_not_mark_semantic_consumption_stale() -> None:
    receipt = _receipt("answer-1", ("answer:warranty",))
    graph = DependencyGraph(
        [
            DependencyEdge(
                source_id="answer:warranty",
                target_id="claim:warranty",
                edge_type=EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.LOCATOR}),
            ),
            *consumption_dependency_edges(receipt),
        ]
    )

    semantic_risks = trace_stale_consumptions(
        changed_ids=["claim:warranty"],
        graph=graph,
        receipts=[receipt],
        candidate_world_state_id="world-8",
        channel=DependencyChannel.SEMANTIC,
    )
    locator_risks = trace_stale_consumptions(
        changed_ids=["claim:warranty"],
        graph=graph,
        receipts=[receipt],
        candidate_world_state_id="world-8",
        channel=DependencyChannel.LOCATOR,
    )

    assert semantic_risks == ()
    # The receipt edge is intentionally semantic/temporal, not locator-sensitive;
    # evidence relocation may require citation reprojection but does not make the
    # semantic answer stale.
    assert locator_risks == ()


def test_temporal_change_can_trace_consumption_separately_from_semantic_change() -> None:
    receipt = _receipt("as-of-answer", ("timeline:warranty",))
    graph = DependencyGraph(
        [
            DependencyEdge(
                source_id="timeline:warranty",
                target_id="claim:warranty",
                edge_type=EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.TEMPORAL}),
            ),
            *consumption_dependency_edges(receipt),
        ]
    )

    risks = trace_stale_consumptions(
        changed_ids=["claim:warranty"],
        graph=graph,
        receipts=[receipt],
        candidate_world_state_id="world-9",
        channel=DependencyChannel.TEMPORAL,
    )

    assert [risk.consumption_id for risk in risks] == ["as-of-answer"]
