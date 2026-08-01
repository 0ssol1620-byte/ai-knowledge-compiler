from __future__ import annotations

from dataclasses import replace

import pytest
from akc_parallel_runtime import (
    AdaptiveRouter,
    AdaptiveShardPredictor,
    CascadeController,
    CascadeStage,
    ContinuitySignal,
    DeterministicShardPlanner,
    PageClass,
    PageDescriptor,
    QualityEstimate,
    RecipeProfile,
    RouteRequest,
    RouterPromotionEvidence,
    RouterStage,
    RouteTier,
    RoutingUnavailable,
    WorkerState,
    deterministic_benchmark_assignments,
    evaluate_router_promotion,
    ideal_worker_target,
)
from helpers import HASH_A, worker


def page(
    index: int,
    *,
    page_class: PageClass = PageClass.NORMAL_SCAN,
    continuity: frozenset[ContinuitySignal] = frozenset(),
    prior_oom: bool = False,
) -> PageDescriptor:
    return PageDescriptor(
        page_id=f"p{index + 1}",
        index0=index,
        page_class=page_class,
        width_px=1200,
        height_px=1600,
        token_estimate=800,
        expected_output_tokens=500,
        table_density=0.1,
        formula_density=0.0,
        prior_oom=prior_oom,
        continuity_to_next=continuity,
    )


def estimate(
    *,
    passed: float = 0.9,
    numeric: float = 0.9,
    row: float = 0.9,
    latency: float = 10,
    cost: float = 1,
) -> QualityEstimate:
    return QualityEstimate(
        pass_hard_gate=passed,
        numeric_exact=numeric,
        row_complete=row,
        repetition_probability=0.01,
        timeout_probability=0.01,
        oom_probability=0.01,
        expected_latency_seconds=latency,
        expected_cost=cost,
    )


def recipe(
    recipe_id: str,
    *,
    family: str,
    external: bool = False,
    model_revision: str = "model@abc123",
    image: str = "sha256:image-a",
) -> RecipeProfile:
    return RecipeProfile(
        recipe_id=recipe_id,
        model_revision=model_revision,
        runtime_image_digest=image,
        tier=RouteTier.PRECISION,
        capabilities=frozenset({"scan", "table"}),
        supported_languages=frozenset({"ko"}),
        external_provider=external,
        independent_family=family,
    )


def request(**overrides: object) -> RouteRequest:
    values: dict[str, object] = {
        "stage": RouterStage.PAGE,
        "required_capabilities": frozenset({"scan"}),
        "language": "ko",
        "high_risk": False,
        "private_processing": False,
        "external_api_allowed": True,
    }
    values.update(overrides)
    return RouteRequest(**values)  # type: ignore[arg-type]


def test_adaptive_predictor_respects_complexity_and_oom() -> None:
    predictor = AdaptiveShardPredictor(model_context_tokens=32_768, vram_gib=24)
    normal = predictor.predict(page(0))
    complex_page = predictor.predict(page(0, page_class=PageClass.COMPLEX_LAYOUT))
    oom = predictor.predict(page(0, prior_oom=True))
    assert normal.pages_per_shard > complex_page.pages_per_shard
    assert oom.pages_per_shard < normal.pages_per_shard
    assert complex_page.required_worker_class == "large_context_precision"


def test_shard_planner_preserves_continuity_group_even_above_target() -> None:
    pages = tuple(
        page(
            index,
            page_class=PageClass.FORMULA_HEAVY,
            continuity=(
                frozenset({ContinuitySignal.REPEATED_TABLE_HEADER})
                if index < 3
                else frozenset()
            ),
        )
        for index in range(4)
    )
    plan = DeterministicShardPlanner(AdaptiveShardPredictor()).plan(
        document_id="doc-1",
        document_version_id="docv-1",
        source_sha256=HASH_A,
        pages=pages,
    )
    assert len(plan.shards) == 1
    assert plan.shards[0].primary_page_ids == ("p1", "p2", "p3", "p4")


def test_shard_plan_has_exactly_one_owner_and_context_only_overlap() -> None:
    pages = tuple(page(index) for index in range(20))
    planner = DeterministicShardPlanner(AdaptiveShardPredictor(model_context_tokens=4_096))
    plan = planner.plan(
        document_id="doc-1",
        document_version_id="docv-1",
        source_sha256=HASH_A,
        pages=pages,
    )
    assert plan.owned_page_ids == tuple(item.page_id for item in pages)
    assert len(set(plan.owned_page_ids)) == 20
    assert len(plan.shards) > 1
    assert any(shard.context_page_ids for shard in plan.shards)
    assert all(
        not set(shard.primary_page_ids) & set(shard.context_page_ids)
        for shard in plan.shards
    )
    page_positions = {item.page_id: item.index0 for item in pages}
    assert all(
        list(shard.input_page_ids)
        == sorted(shard.input_page_ids, key=lambda page_id: page_positions[page_id])
        for shard in plan.shards
    )


def test_shard_planning_is_byte_deterministic() -> None:
    pages = tuple(page(index) for index in range(12))
    planner = DeterministicShardPlanner(AdaptiveShardPredictor())
    arguments = {
        "document_id": "doc-1",
        "document_version_id": "docv-1",
        "source_sha256": HASH_A,
        "pages": pages,
    }
    assert planner.plan(**arguments) == planner.plan(**arguments)


def test_sharding_exhaustively_conserves_pages_across_classes_and_sizes() -> None:
    planner = DeterministicShardPlanner(AdaptiveShardPredictor(model_context_tokens=8_192))
    for page_class in PageClass:
        for page_count in range(1, 33):
            pages = tuple(page(index, page_class=page_class) for index in range(page_count))
            plan = planner.plan(
                document_id=f"doc-{page_class.value}-{page_count}",
                document_version_id=f"docv-{page_class.value}-{page_count}",
                source_sha256=HASH_A,
                pages=pages,
            )
            assert plan.owned_page_ids == tuple(item.page_id for item in pages)
            assert len(plan.owned_page_ids) == len(set(plan.owned_page_ids))


def test_shard_planner_rejects_dangling_continuity() -> None:
    with pytest.raises(ValueError, match="final page"):
        DeterministicShardPlanner(AdaptiveShardPredictor()).plan(
            document_id="doc-1",
            document_version_id="docv-1",
            source_sha256=HASH_A,
            pages=(page(0, continuity=frozenset({ContinuitySignal.NUMBERED_LIST})),),
        )


def test_benchmark_assignment_preserves_document_groups_and_is_deterministic() -> None:
    groups = {"doc-a": ("a1", "a2"), "doc-b": ("b1",), "doc-c": ("c1", "c2")}
    first = deterministic_benchmark_assignments(groups, 3)
    second = deterministic_benchmark_assignments(dict(reversed(tuple(groups.items()))), 3)
    assert first == second
    assert any("a1" in values and "a2" in values for values in first.values())
    assert sorted(value for values in first.values() for value in values) == [
        "a1",
        "a2",
        "b1",
        "c1",
        "c2",
    ]


def test_dynamic_worker_target_obeys_every_capacity_limit() -> None:
    assert ideal_worker_target(
        1_000,
        100,
        provider_limit=20,
        account_limit=8,
        queue_limit=12,
        evaluator_limit=6,
        database_limit=9,
    ) == 6
    assert ideal_worker_target(
        0,
        100,
        provider_limit=20,
        account_limit=8,
        queue_limit=12,
        evaluator_limit=6,
        database_limit=9,
    ) == 0


def test_router_selects_highest_verified_quality_objective() -> None:
    router = AdaptiveRouter()
    recipes = (recipe("strong", family="a"), recipe("weak", family="b"))
    workers = (worker("w1"), worker("w2"))
    estimates = {
        ("strong", "w1"): estimate(passed=0.98, numeric=0.98),
        ("weak", "w2"): estimate(passed=0.60, numeric=0.60),
    }
    decision = router.route(request(), recipes=recipes, workers=workers, estimates=estimates)
    assert decision.primary.recipe.recipe_id == "strong"


@pytest.mark.parametrize(
    "state",
    [WorkerState.DRAINING, WorkerState.QUARANTINED, WorkerState.TERMINATED],
)
def test_router_excludes_non_serving_worker_states(state: WorkerState) -> None:
    router = AdaptiveRouter()
    with pytest.raises(RoutingUnavailable):
        router.route(
            request(),
            recipes=(recipe("r", family="a"),),
            workers=(worker(state=state),),
            estimates={("r", "worker-a"): estimate()},
        )


def test_router_fails_closed_on_model_or_image_identity_mismatch() -> None:
    with pytest.raises(RoutingUnavailable):
        AdaptiveRouter().route(
            request(),
            recipes=(recipe("r", family="a"),),
            workers=(worker(model_revision="wrong@revision"),),
            estimates={("r", "worker-a"): estimate()},
        )


def test_router_blocks_external_provider_for_private_data() -> None:
    with pytest.raises(RoutingUnavailable):
        AdaptiveRouter().route(
            request(private_processing=True, external_api_allowed=False),
            recipes=(recipe("external", family="a", external=True),),
            workers=(worker(),),
            estimates={("external", "worker-a"): estimate()},
        )


def test_router_speculates_only_with_independent_secondary_and_high_risk_reason() -> None:
    router = AdaptiveRouter()
    recipes = (recipe("a", family="family-a"), recipe("b", family="family-b"))
    workers = (worker("w1"), worker("w2"))
    estimates = {
        ("a", "w1"): estimate(passed=0.7),
        ("b", "w2"): estimate(passed=0.69),
    }
    decision = router.route(
        request(high_risk=True, financial_numeric=True),
        recipes=recipes,
        workers=workers,
        estimates=estimates,
    )
    assert decision.speculative is True
    assert decision.secondary is not None
    assert "financial_numeric" in decision.reason_codes


def test_router_does_not_speculate_without_independent_family() -> None:
    router = AdaptiveRouter()
    recipes = (recipe("a", family="same"), recipe("b", family="same"))
    workers = (worker("w1"), worker("w2"))
    estimates = {("a", "w1"): estimate(), ("b", "w2"): estimate()}
    decision = router.route(
        request(financial_numeric=True),
        recipes=recipes,
        workers=workers,
        estimates=estimates,
    )
    assert decision.speculative is False
    assert decision.secondary is None


def test_router_requires_estimator_and_capability_evidence() -> None:
    with pytest.raises(RoutingUnavailable):
        AdaptiveRouter().route(
            request(required_capabilities=frozenset({"formula"})),
            recipes=(recipe("r", family="a"),),
            workers=(worker(),),
            estimates={},
        )


def test_cascade_early_exit_marks_candidate_for_arbitration_not_direct_acceptance() -> None:
    decision = CascadeController().advance(
        current=CascadeStage.NATIVE,
        hard_gates_passed=True,
        authority_required=False,
        authority_exact=False,
        available_stages=frozenset(CascadeStage),
    )
    assert decision.terminal is True
    assert decision.ready_for_arbitration is True
    assert decision.reason_code == "candidate_ready_for_arbitration"


def test_cascade_escalates_to_next_available_stage_and_then_unresolved() -> None:
    controller = CascadeController()
    escalated = controller.advance(
        current=CascadeStage.NATIVE,
        hard_gates_passed=False,
        authority_required=False,
        authority_exact=False,
        available_stages=frozenset({CascadeStage.PRECISION}),
    )
    assert escalated.stage is CascadeStage.PRECISION
    exhausted = controller.advance(
        current=CascadeStage.PRECISION,
        hard_gates_passed=False,
        authority_required=False,
        authority_exact=False,
        available_stages=frozenset(),
    )
    assert exhausted.stage is CascadeStage.UNRESOLVED
    assert exhausted.terminal is True


def test_cascade_authority_requirement_never_falls_back_to_model_agreement() -> None:
    controller = CascadeController()
    routed = controller.advance(
        current=CascadeStage.PRECISION,
        hard_gates_passed=True,
        authority_required=True,
        authority_exact=False,
        available_stages=frozenset({CascadeStage.AUTHORITY}),
    )
    assert routed.stage is CascadeStage.AUTHORITY
    unresolved = controller.advance(
        current=CascadeStage.PRECISION,
        hard_gates_passed=True,
        authority_required=True,
        authority_exact=False,
        available_stages=frozenset(),
    )
    assert unresolved.stage is CascadeStage.UNRESOLVED


def test_learned_router_promotion_requires_no_regression_and_rollback() -> None:
    evidence = RouterPromotionEvidence(
        shadow_sample_count=1_000,
        candidate_critical_failures=0,
        baseline_verified_quality=0.95,
        candidate_verified_quality=0.96,
        baseline_cost=10,
        candidate_cost=9,
        baseline_latency=100,
        candidate_latency=90,
        canary_percent=1,
        low_risk_only=True,
        rollback_ready=True,
    )
    assert evaluate_router_promotion(evidence).promote is True
    rejected = evaluate_router_promotion(
        replace(
            evidence,
            candidate_critical_failures=1,
            candidate_verified_quality=0.90,
            candidate_cost=11,
            candidate_latency=110,
            low_risk_only=False,
            rollback_ready=False,
        )
    )
    assert rejected.promote is False
    assert set(rejected.reason_codes) == {
        "candidate_critical_failure",
        "canary_scope_not_low_risk",
        "cost_and_latency_not_improved",
        "rollback_not_ready",
        "verified_quality_regression",
    }
