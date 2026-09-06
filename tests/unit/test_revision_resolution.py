from __future__ import annotations

from datetime import UTC, datetime

from akc_cir.authority import AuthorityClass, ClaimContext, ScopedClaim, SourceStatus
from akc_cir.dependency import (
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.revision_resolution import ResolutionDimension, recompute_revision_resolution
from akc_cir.world_state import WorldStateRegistry, WorldStateStatus

NOW = datetime(2026, 8, 16, tzinfo=UTC)


def _context(**kw) -> ClaimContext:
    values = {
        "subject": "warranty",
        "as_of": NOW,
        "customer_id": "customer-a",
    }
    values.update(kw)
    return ClaimContext(**values)


def _claim(
    claim_id: str = "warranty-current",
    value: str = "3 years",
    *,
    authority: AuthorityClass = AuthorityClass.OFFICIAL,
    source_status: SourceStatus = SourceStatus.ACTIVE,
    scope: dict[str, str] | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> ScopedClaim:
    return ScopedClaim(
        claim_id=claim_id,
        subject="warranty",
        value=value,
        authority=authority,
        source_status=source_status,
        scope=scope or {},
        valid_from=valid_from,
        valid_to=valid_to,
        recorded_at=NOW,
        evidence_id=f"evidence:{claim_id}",
    )


def _semantic_graph() -> DependencyGraph:
    return DependencyGraph(
        [
            DependencyEdge(
                source_id="answer:warranty",
                target_id="warranty",
                edge_type=EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.SEMANTIC}),
            )
        ]
    )


def test_authority_recompute_marks_semantic_dependents_dirty_and_only_stages_candidate() -> None:
    worlds = WorldStateRegistry("workspace-a")
    result = recompute_revision_resolution(
        logical_id="warranty",
        before_claims=[_claim(authority=AuthorityClass.OFFICIAL)],
        after_claims=[_claim(authority=AuthorityClass.REGULATORY)],
        context=_context(),
        graph=_semantic_graph(),
        artifacts=["answer:warranty", "answer:unrelated"],
        world_registry=worlds,
        candidate_world_state_id="world-candidate-1",
        compiler_version="test",
    )

    assert ResolutionDimension.AUTHORITY in result.changed_dimensions
    assert result.plan.to_rebuild == ("answer:warranty",)
    assert result.plan.explain("answer:warranty").startswith("AUTHORITY:")
    assert result.candidate_world is not None
    assert result.candidate_world.status is WorldStateStatus.CANDIDATE
    assert worlds.current is None
    assert worlds.active_count() == 0
    assert result.as_record()["publish_authorized"] is False


def test_applicability_scope_change_recomputes_dirty_set() -> None:
    result = recompute_revision_resolution(
        logical_id="warranty",
        before_claims=[_claim(scope={})],
        after_claims=[_claim(scope={"customer_id": "customer-a"})],
        context=_context(),
        graph=_semantic_graph(),
        artifacts=["answer:warranty"],
    )

    assert ResolutionDimension.APPLICABILITY in result.changed_dimensions
    assert result.plan.to_rebuild == ("answer:warranty",)


def test_valid_time_change_only_reaches_temporal_sensitive_projection() -> None:
    graph = DependencyGraph(
        [
            DependencyEdge(
                source_id="timeline:warranty",
                target_id="warranty",
                edge_type=EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.TEMPORAL}),
            ),
            DependencyEdge(
                source_id="semantic-only:warranty",
                target_id="warranty",
                edge_type=EdgeType.DEPENDS_ON,
                channels=frozenset({DependencyChannel.SEMANTIC}),
            ),
        ]
    )
    before = _claim(valid_from=datetime(2026, 1, 1, tzinfo=UTC))
    after = _claim(valid_from=datetime(2026, 2, 1, tzinfo=UTC))

    result = recompute_revision_resolution(
        logical_id="warranty",
        before_claims=[before],
        after_claims=[after],
        context=_context(),
        graph=graph,
        artifacts=["timeline:warranty", "semantic-only:warranty"],
    )

    assert result.changed_dimensions == (ResolutionDimension.VALID_TIME,)
    assert result.plan.to_rebuild == ("timeline:warranty",)
    assert result.plan.explain("timeline:warranty").startswith("VALID_TIME:")


def test_no_governed_resolution_change_does_not_stage_a_world() -> None:
    worlds = WorldStateRegistry("workspace-a")
    claim = _claim()

    result = recompute_revision_resolution(
        logical_id="warranty",
        before_claims=[claim],
        after_claims=[claim],
        context=_context(),
        graph=_semantic_graph(),
        artifacts=["answer:warranty"],
        world_registry=worlds,
        candidate_world_state_id="should-not-exist",
    )

    assert result.changed is False
    assert result.plan.to_rebuild == ()
    assert result.candidate_world is None
    assert worlds.get("should-not-exist") is None


def test_new_equal_authority_conflict_is_review_blocked_and_never_activated() -> None:
    worlds = WorldStateRegistry("workspace-a")
    before = [_claim(claim_id="old", value="3 years")]
    after = [
        _claim(claim_id="left", value="3 years"),
        _claim(claim_id="right", value="5 years"),
    ]

    result = recompute_revision_resolution(
        logical_id="warranty",
        before_claims=before,
        after_claims=after,
        context=_context(),
        graph=_semantic_graph(),
        artifacts=["answer:warranty"],
        world_registry=worlds,
        candidate_world_state_id="conflicted-candidate",
    )

    assert result.after.status == "CONFLICTED"
    assert result.blocked_on_review is True
    assert result.candidate_world is not None
    assert result.candidate_world.status is WorldStateStatus.CANDIDATE
    assert worlds.current is None
