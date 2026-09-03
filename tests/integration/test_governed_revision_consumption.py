from __future__ import annotations

from datetime import UTC, datetime

from akc_cir.authority import AuthorityClass, ClaimContext, ScopedClaim, SourceStatus
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
from akc_cir.revision_resolution import ResolutionDimension, recompute_revision_resolution
from akc_cir.world_state import WorldStateRegistry, WorldStateStatus

NOW = datetime(2026, 8, 16, tzinfo=UTC)


def _claim(
    *,
    claim_id: str,
    value: str,
    authority: AuthorityClass,
) -> ScopedClaim:
    return ScopedClaim(
        claim_id=claim_id,
        subject="warranty",
        value=value,
        authority=authority,
        source_status=SourceStatus.ACTIVE,
        recorded_at=NOW,
        evidence_id=f"evidence:{claim_id}",
    )


def test_governed_revision_marks_only_exact_prior_consumption_at_risk() -> None:
    affected = ConsumptionReceipt(
        consumption_id="answer-before-change",
        world_state_id="world-7",
        consumed_unit_ids=("answer:warranty",),
        answer_claim_ids=("claim:warranty",),
        response_hash="sha256:prior-answer",
        downstream_action_ref="agent-action-17",
    )
    unrelated = ConsumptionReceipt(
        consumption_id="unrelated-answer",
        world_state_id="world-7",
        consumed_unit_ids=("answer:shipping",),
        answer_claim_ids=("claim:shipping",),
        response_hash="sha256:unrelated",
    )
    graph = DependencyGraph(
        [
            DependencyEdge(
                source_id="answer:warranty",
                target_id="warranty",
                edge_type=EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.SEMANTIC}),
            ),
            DependencyEdge(
                source_id="answer:shipping",
                target_id="shipping",
                edge_type=EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.SEMANTIC}),
            ),
            *consumption_dependency_edges(affected),
            *consumption_dependency_edges(unrelated),
        ]
    )
    worlds = WorldStateRegistry("workspace-a")
    before = [
        _claim(
            claim_id="warranty-policy-v6",
            value="2 years",
            authority=AuthorityClass.OFFICIAL,
        )
    ]
    after = [
        _claim(
            claim_id="warranty-policy-v7",
            value="3 years",
            authority=AuthorityClass.REGULATORY,
        )
    ]

    recomputed = recompute_revision_resolution(
        logical_id="warranty",
        before_claims=before,
        after_claims=after,
        context=ClaimContext(subject="warranty", as_of=NOW),
        graph=graph,
        artifacts=["answer:warranty", "answer:shipping"],
        world_registry=worlds,
        candidate_world_state_id="world-8",
        compiler_version="integration-test",
    )
    risks = trace_stale_consumptions(
        changed_ids=["warranty"],
        graph=graph,
        receipts=[affected, unrelated],
        candidate_world_state_id="world-8",
        as_of=NOW,
        channel=DependencyChannel.SEMANTIC,
    )

    assert ResolutionDimension.AUTHORITY in recomputed.changed_dimensions
    assert recomputed.before.selected_value == "2 years"
    assert recomputed.after.selected_value == "3 years"
    assert recomputed.plan.to_rebuild == ("answer:warranty",)
    assert recomputed.candidate_world is not None
    assert recomputed.candidate_world.status is WorldStateStatus.CANDIDATE
    assert worlds.current is None

    assert [risk.consumption_id for risk in risks] == ["answer-before-change"]
    risk = risks[0]
    assert risk.source_world_state_id == "world-7"
    assert risk.candidate_world_state_id == "world-8"
    assert risk.downstream_action_ref == "agent-action-17"
    assert "warranty" in risk.reason_path
    assert "answer:warranty" in risk.reason_path
    assert "consumption:answer-before-change" in risk.reason_path
