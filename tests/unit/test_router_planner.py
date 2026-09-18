"""WP-R6: the adaptive execution planner and its shadow hook."""

from __future__ import annotations

import pytest
from akc_router import (
    DataPolicy,
    DependencyEdge,
    DependencyKind,
    EscalationPolicy,
    ExecutionLane,
    PageMetrics,
    PageTechnicalClass,
    ProcessingMode,
    Route,
    RouterContext,
    VerificationPolicy,
    select_first_route,
)
from akc_router.engine import (
    ROUTER_V2_SHADOW_ENV,
    router_v2_shadow_enabled,
    set_router_v2_shadow_sink,
)
from akc_router.execution_plan import CropGeometry, RegionType, RouterReplayRecord
from akc_router.planner import (
    DEFAULT_COST_MODEL,
    CapacityState,
    CostModel,
    PlannerRequest,
    RegionFeatures,
    RouteCost,
    UnitFeatures,
    classify_speculation,
    plan_document,
    route_risk,
)
from akc_router.portfolio import ModelEvidence, build_portfolio
from akc_router.risk import ObservationSource, RiskFeature, RiskSignal, RiskVector
from akc_router.speculation import SpeculationClass

_F = RiskFeature

_ALL_ROUTES = frozenset(
    {
        Route.NATIVE,
        Route.PADDLE_FAST,
        Route.PADDLE_VL,
        Route.HPD_FAST,
        Route.AUTHORITY_RECONSTRUCTION,
        Route.REGION_RECOVERY,
    }
)

_PROPOSALS: dict[ExecutionLane, tuple[Route, str | None]] = {
    ExecutionLane.NATIVE: (Route.NATIVE, None),
    ExecutionLane.FAST_VISUAL: (Route.PADDLE_FAST, None),
    ExecutionLane.PEER_VISUAL: (Route.PADDLE_VL, None),
    ExecutionLane.AUTHORITY: (Route.AUTHORITY_RECONSTRUCTION, None),
    ExecutionLane.HUMAN_REVIEW: (Route.REGION_RECOVERY, None),
}

#: A model with every §5 receipt bound, for the specialist lanes that need one.
_QUALIFIED = ModelEvidence(
    model_key="specialist",
    weights_repo="example/spec",
    weights_revision="a" * 40,
    container_reference="example/spec@sha256:" + "b" * 64,
    container_digest_observed="sha256:" + "b" * 64,
    runtime_version="1.0.0",
    inference_args_sha256="sha256:" + "c" * 64,
    gpu_min_vram_gb=24,
    gpu_count_min=1,
    licence_id="Apache-2.0",
    licence_status="verified",
    licence_url="https://example.invalid/licence",
    prompt_id="spec_v1",
    warm_latency_seconds=2.0,
    cold_start_seconds=90.0,
    throughput_pages_per_gpu_hour=900.0,
    failure_modes=("none_observed",),
    page_class_evidence=("old_scans",),
    data_policy="in_tenant_gpu_only",
    confirmatory_receipt_sha256="sha256:" + "d" * 64,
    confirmatory_evidence_class="fresh_holdout",
    confirmatory_scope=("old_scans",),
)


def _risk(
    observed: dict[RiskFeature, float] | None = None,
    *,
    unknown: set[RiskFeature] | None = None,
    authority_available: bool = False,
) -> RiskVector:
    """Everything not named is observed at 0.0; `unknown` is genuinely unknown."""
    values = observed or {}
    blind = unknown or set()
    signals: dict[RiskFeature, RiskSignal] = {}
    for feature in RiskFeature:
        if feature in blind:
            signals[feature] = RiskSignal(
                unknown=True, observation_source=ObservationSource.UNAVAILABLE
            )
        else:
            signals[feature] = RiskSignal(
                value=values.get(feature, 0.0),
                observation_source=ObservationSource.DERIVED,
            )
    return RiskVector(
        signals=signals,
        unknown_features=tuple(feature for feature in RiskFeature if feature in blind),
        authority_available=authority_available,
    )


def _request(units: tuple[UnitFeatures, ...], **overrides: object) -> PlannerRequest:
    base: dict[str, object] = {
        "source_version_id": "sv-1",
        "units": units,
        "data_policy": DataPolicy(),
        "mode": ProcessingMode.BALANCED,
        "portfolio": build_portfolio(_PROPOSALS, {}),
        "ready_routes": _ALL_ROUTES,
        "cost_budget": 500.0,
    }
    base.update(overrides)
    return PlannerRequest(**base)  # type: ignore[arg-type]


def _unit(
    unit_id: str = "p1",
    *,
    technical_class: PageTechnicalClass = PageTechnicalClass.SCAN_TEXT,
    risk: RiskVector | None = None,
    **extra: object,
) -> UnitFeatures:
    return UnitFeatures(
        unit_id=unit_id,
        page_index0=0,
        technical_class=technical_class,
        risk_vector=risk if risk is not None else _risk(),
        **extra,  # type: ignore[arg-type]
    )


# --- the §21 speculation cases the program names -----------------------------


def test_native_clean_runs_native_only() -> None:
    unit = _unit(technical_class=PageTechnicalClass.NATIVE_CLEAN)
    result = plan_document(_request((unit,)))
    assert result.is_executable
    page = result.unit_plans[0].page_plan
    assert page is not None
    assert result.unit_plans[0].speculation_class is SpeculationClass.NATIVE_CLEAN
    assert page.primary_route is Route.NATIVE
    assert page.speculative_routes == ()


def test_critical_financial_table_adds_a_visual_peer_to_authority_or_native() -> None:
    unit = _unit(
        technical_class=PageTechnicalClass.TABLE_HEAVY,
        risk=_risk(
            {_F.TABLE_STRUCTURE_RISK: 0.9, _F.NUMERIC_RISK: 0.9},
            authority_available=True,
        ),
    )
    result = plan_document(_request((unit,)))
    plan = result.unit_plans[0]
    assert plan.speculation_class is SpeculationClass.CRITICAL_FINANCIAL_TABLE
    page = plan.page_plan
    assert page is not None
    assert page.primary_route in {Route.AUTHORITY_RECONSTRUCTION, Route.NATIVE}
    assert page.speculative_routes  # a visual peer runs in parallel
    assert page.verification_policy is VerificationPolicy.AUTHORITY_MATCH
    assert page.escalation_policy is EscalationPolicy.AUTHORITY_LANE


def _handwriting_unit() -> UnitFeatures:
    return _unit(
        technical_class=PageTechnicalClass.HANDWRITTEN,
        risk=_risk({_F.HANDWRITING_RISK: 0.9}),
    )


def test_handwriting_without_a_qualified_specialist_refuses() -> None:
    """A specialist lane is a capability claim; unevidenced, it cannot run."""
    result = plan_document(_request((_handwriting_unit(),), verified_trust_floor=0.7))
    assert result.plan is None
    assert "lane_unavailable:degraded_scan_specialist" in result.unit_plans[0].reason_codes


def test_handwriting_goes_to_the_specialist_with_review() -> None:
    portfolio = build_portfolio(
        {**_PROPOSALS, ExecutionLane.DEGRADED_SCAN_SPECIALIST: (Route.PADDLE_VL, "specialist")},
        {"specialist": _QUALIFIED},
    )
    # A handwriting page is high-risk by construction. It is plannable only
    # because a person reads the output; that is what `verified_trust_floor` is.
    result = plan_document(
        _request((_handwriting_unit(),), portfolio=portfolio, verified_trust_floor=0.7)
    )
    plan = result.unit_plans[0]
    assert plan.speculation_class is SpeculationClass.HANDWRITING
    page = plan.page_plan
    assert page is not None
    assert page.primary_route is Route.PADDLE_VL
    assert page.verification_policy is VerificationPolicy.HUMAN_REVIEW
    assert page.escalation_policy is EscalationPolicy.FAIL_CLOSED


def test_speculation_is_declined_when_it_does_not_pay_for_itself() -> None:
    """A cheap penalty makes the peer not worth pre-launching (§9).

    High-risk text verifies by peer agreement, and a peer-agreement peer is also
    reachable by escalation -- so pre-launching it is the optional spend.
    """
    model = CostModel(routes=DEFAULT_COST_MODEL.routes, critical_failure_penalty=0.01)
    unit = _unit(
        technical_class=PageTechnicalClass.SCAN_TEXT,
        risk=_risk({_F.TEXT_LOSS_RISK: 0.9}),
    )
    result = plan_document(_request((unit,), cost_model=model))
    plan = result.unit_plans[0]
    assert plan.speculation_class is SpeculationClass.HIGH_RISK_TEXT
    assert plan.page_plan is not None
    assert plan.page_plan.speculative_routes == ()
    assert any(code.startswith("speculation_not_worth_cost") for code in plan.reason_codes)


def test_a_verification_peer_is_not_dropped_as_an_optimisation() -> None:
    """AUTHORITY_MATCH's peer is the verifier, so cost cannot silently remove it."""
    unit = _unit(
        technical_class=PageTechnicalClass.TABLE_HEAVY,
        risk=_risk(
            {_F.TABLE_STRUCTURE_RISK: 0.9, _F.NUMERIC_RISK: 0.9},
            authority_available=True,
        ),
    )
    cheap = CostModel(routes=DEFAULT_COST_MODEL.routes, critical_failure_penalty=0.0)
    result = plan_document(_request((unit,), cost_model=cheap))
    page = result.unit_plans[0].page_plan
    assert page is not None
    assert page.speculative_routes
    assert any(
        code.startswith("peer_required_by_verification_contract")
        for code in result.unit_plans[0].reason_codes
    )


# --- the trust floor ---------------------------------------------------------


def test_the_cheapest_plan_that_breaks_the_trust_floor_is_never_chosen() -> None:
    """Native is cheapest, but it cannot read a scan; the floor rules it out."""
    unit = _unit(
        technical_class=PageTechnicalClass.SCAN_TEXT,
        risk=_risk({_F.TEXT_LOSS_RISK: 0.9, _F.SCAN_NEED: 1.0}),
    )
    result = plan_document(_request((unit,), trust_floor=0.2))
    page = result.unit_plans[0].page_plan
    assert page is not None
    assert page.primary_route is not Route.NATIVE
    assert route_risk(Route.NATIVE, unit.risk_vector).lower_bound > 0.2


def test_a_unit_no_route_can_carry_refuses_the_whole_plan() -> None:
    unit = _unit(
        technical_class=PageTechnicalClass.HANDWRITTEN,
        risk=_risk({_F.HANDWRITING_RISK: 1.0, _F.DEGRADATION_RISK: 1.0}),
    )
    result = plan_document(_request((unit,), trust_floor=0.01))
    assert result.plan is None
    assert not result.is_executable
    assert any("trust_floor_unreachable" in code for code in result.unresolved_constraints)


def test_an_unmeasured_sensitive_feature_is_not_a_low_risk() -> None:
    risk = route_risk(Route.PADDLE_FAST, _risk(unknown={_F.HANDWRITING_RISK}))
    assert not risk.bounded
    assert risk.unmeasured_sensitive == (_F.HANDWRITING_RISK,)


def test_an_unmeasured_risk_forces_a_peer_and_raises_verification() -> None:
    unit = _unit(
        technical_class=PageTechnicalClass.SCAN_COMPLEX,
        risk=_risk({_F.TEXT_LOSS_RISK: 0.9}, unknown={_F.DEGRADATION_RISK}),
    )
    result = plan_document(_request((unit,)))
    plan = result.unit_plans[0]
    assert plan.page_plan is not None
    assert plan.page_plan.speculative_routes
    assert any(code.startswith("speculative_for_unmeasured_risk") for code in plan.reason_codes)


def test_an_unverified_route_with_unmeasured_risk_is_not_eligible() -> None:
    """Native-clean has no verifier, so an unmeasured native risk disqualifies it."""
    unit = _unit(
        technical_class=PageTechnicalClass.NATIVE_CLEAN,
        risk=_risk(unknown={_F.SCAN_NEED}),
    )
    result = plan_document(_request((unit,)))
    assert result.plan is None
    assert any("trust_floor_unreachable" in code for code in result.unresolved_constraints)


# --- data policy, budgets, capacity -----------------------------------------


def test_data_policy_filters_before_scoring() -> None:
    private = _request(
        (_unit(),),
        mode=ProcessingMode.PRIVATE,
        ready_routes=frozenset({Route.PADDLE_FAST, Route.PADDLE_VL, Route.MISTRAL_FALLBACK}),
        portfolio=build_portfolio(
            {
                **_PROPOSALS,
                ExecutionLane.EXTERNAL_ADJUDICATOR: (Route.MISTRAL_FALLBACK, None),
            },
            {},
        ),
    )
    result = plan_document(private)
    for plan in result.unit_plans:
        if plan.page_plan is not None:
            assert Route.MISTRAL_FALLBACK not in plan.page_plan.candidate_routes
            assert Route.MISTRAL_FALLBACK not in plan.page_plan.speculative_routes


def test_over_budget_drops_speculation_first_then_refuses() -> None:
    unit = _unit(
        technical_class=PageTechnicalClass.SCAN_COMPLEX,
        risk=_risk({_F.TEXT_LOSS_RISK: 0.9, _F.DEGRADATION_RISK: 0.4}),
    )
    generous = plan_document(_request((unit,), cost_budget=500.0, trust_floor=0.5))
    assert generous.is_executable
    with_speculation = generous.unit_plans[0].expected_verified_cost
    assert generous.unit_plans[0].page_plan is not None
    assert generous.unit_plans[0].page_plan.speculative_routes

    trimmed = plan_document(_request((unit,), cost_budget=with_speculation - 0.5, trust_floor=0.5))
    assert trimmed.is_executable
    assert "speculation_dropped_for_cost_budget" in trimmed.reason_codes
    assert trimmed.unit_plans[0].page_plan is not None
    assert trimmed.unit_plans[0].page_plan.speculative_routes == ()
    assert trimmed.unit_plans[0].expected_verified_cost < with_speculation

    refused = plan_document(_request((unit,), cost_budget=0.01, trust_floor=0.5))
    assert refused.plan is None
    assert "cost_budget_exceeded" in refused.unresolved_constraints


def test_a_missed_deadline_is_a_refusal_not_a_shorter_plan() -> None:
    units = tuple(_unit(f"p{index}") for index in range(20))
    result = plan_document(
        _request(units, deadline_ms=1.0, capacity=CapacityState(parallelism_budget=1))
    )
    assert result.plan is None
    assert "deadline_p95_exceeded" in result.unresolved_constraints


def test_an_unpriced_route_raises_rather_than_being_free() -> None:
    model = CostModel(routes={Route.NATIVE: RouteCost(inference=0.25)})
    with pytest.raises(Exception, match="no cost model entry"):
        plan_document(_request((_unit(),), cost_model=model))


def test_capacity_caps_speculative_work() -> None:
    unit = _unit(
        technical_class=PageTechnicalClass.SCAN_COMPLEX,
        risk=_risk({_F.TEXT_LOSS_RISK: 0.9}, unknown={_F.DEGRADATION_RISK}),
    )
    result = plan_document(_request((unit,), capacity=CapacityState(max_speculative_units=0)))
    plan = result.unit_plans[0]
    assert plan.page_plan is not None
    assert plan.page_plan.speculative_routes == ()
    assert "speculation_capped_by_capacity" in plan.reason_codes


# --- waves, dependencies, regions -------------------------------------------


def test_waves_respect_a_blocking_dependency_edge() -> None:
    units = (_unit("p1"), _unit("p2"))
    edge = DependencyEdge(from_unit_id="p1", to_unit_id="p2", kind=DependencyKind.CONTINUED_TABLE)
    result = plan_document(_request(units, dependency_edges=(edge,)))
    assert result.plan is not None
    index_of = {
        unit_id: wave.wave_index
        for wave in result.plan.execution_waves
        for unit_id in wave.unit_ids
    }
    assert index_of["p2"] > index_of["p1"]
    assert result.plan.dependency_edges == (edge,)


def test_a_dependency_cycle_terminates_instead_of_hanging() -> None:
    units = (_unit("p1"), _unit("p2"))
    edges = (
        DependencyEdge(from_unit_id="p1", to_unit_id="p2", kind=DependencyKind.FOOTNOTE),
        DependencyEdge(from_unit_id="p2", to_unit_id="p1", kind=DependencyKind.FOOTNOTE),
    )
    result = plan_document(_request(units, dependency_edges=edges))
    assert result.plan is not None


def test_region_plans_only_exist_for_located_regions() -> None:
    plain = plan_document(_request((_unit("p1"),)))
    assert plain.unit_plans[0].region_plans == ()

    located = _unit(
        "p2",
        regions=(
            RegionFeatures(
                region_id="r1",
                source_locator="p2#r1",
                region_type=RegionType.TABLE,
                risk_vector=_risk({_F.TABLE_STRUCTURE_RISK: 0.8}),
                crop_geometry=CropGeometry(page_index0=0, x=10, y=10, width=100, height=50),
            ),
        ),
    )
    result = plan_document(_request((located,)))
    regions = result.unit_plans[0].region_plans
    assert len(regions) == 1
    assert regions[0].source_locator == "p2#r1"


def test_planning_is_deterministic() -> None:
    units = (_unit("p1"), _unit("p2"))
    first = plan_document(_request(units))
    second = plan_document(_request(units))
    assert first.plan == second.plan


def test_uncalibrated_thresholds_are_declared() -> None:
    result = plan_document(_request((_unit(),)))
    assert result.calibrated is False
    assert "uncalibrated_thresholds" in result.reason_codes
    assert DEFAULT_COST_MODEL.calibrated is False


def test_classify_speculation_never_selects_a_class_from_an_unknown() -> None:
    unit = _unit(
        technical_class=PageTechnicalClass.SCAN_TEXT,
        risk=_risk(unknown={_F.HANDWRITING_RISK, _F.CHART_VISUAL_RISK}),
    )
    assert classify_speculation(unit) is SpeculationClass.ORDINARY_SCAN


# --- the shadow hook ---------------------------------------------------------


def _page(**overrides: object) -> PageMetrics:
    values: dict[str, object] = {
        "page_index0": 0,
        "width": 612,
        "height": 792,
        "native_text_chars": 3000,
        "native_word_count": 500,
        "native_block_count": 24,
        "native_text_coverage": 0.90,
        "image_coverage": 0.02,
        "invalid_unicode_ratio": 0.0,
        "replacement_char_ratio": 0.0,
        "whitespace_anomaly_score": 0.0,
        "native_reading_order_score": 0.98,
        "font_size_p10": None,
        "estimated_columns": 1,
        "table_density": 0.0,
        "formula_density": 0.0,
        "chart_probability": 0.0,
        "handwriting_probability": 0.0,
        "rotation_degrees": 0,
        "skew_degrees": 0.0,
        "blur_score": 0.0,
        "contrast_score": 1.0,
        "small_text_score": 0.0,
        "script_distribution": {"Latin": 1.0},
        "suspected_prompt_injection": False,
    }
    values.update(overrides)
    return PageMetrics.model_validate(values)


def test_the_shadow_is_off_without_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ROUTER_V2_SHADOW_ENV, raising=False)
    seen: list[RouterReplayRecord] = []
    set_router_v2_shadow_sink(seen.append)
    try:
        assert not router_v2_shadow_enabled()
        select_first_route(RouterContext(), _page())
        assert seen == []
    finally:
        set_router_v2_shadow_sink(None)


def test_the_shadow_emits_beside_the_legacy_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ROUTER_V2_SHADOW_ENV, "1")
    seen: list[RouterReplayRecord] = []
    set_router_v2_shadow_sink(seen.append)
    try:
        context = RouterContext(ready_routes=frozenset({Route.NATIVE, Route.PADDLE_VL}))
        page = _page()
        with_shadow = select_first_route(context, page)
        set_router_v2_shadow_sink(None)
        without_shadow = select_first_route(context, page)
    finally:
        set_router_v2_shadow_sink(None)
    # Zero decision authority: the legacy route is byte-identical either way.
    assert with_shadow == without_shadow
    assert with_shadow.route is Route.NATIVE
    assert len(seen) == 1
    assert seen[0].hidden_evaluation_visible_to_runtime is False
    assert seen[0].router_revision.startswith("planner-v2")


def test_a_failing_shadow_sink_cannot_break_the_legacy_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ROUTER_V2_SHADOW_ENV, "1")

    def explode(_record: RouterReplayRecord) -> None:
        raise RuntimeError("shadow sink is broken")

    set_router_v2_shadow_sink(explode)
    try:
        decision = select_first_route(RouterContext(), _page())
    finally:
        set_router_v2_shadow_sink(None)
    assert decision.route is Route.NATIVE


# --- WP-R10 replay adapter ----------------------------------------------------


class _StubOutput:
    def __init__(self, *, present: bool = True) -> None:
        self.present = present


class _StubUnitFeatures:
    """The harness's runtime-visible shape, duck-typed."""

    def __init__(self, **overrides: object) -> None:
        self.case_key = "olmocr/old_scans/1.pdf"
        self.page_index = 0
        self.native_text_chars = 0
        self.native_word_count = 0
        self.native_text_available = False
        self.native_invalid_unicode_ratio = 0.0
        self.native_replacement_ratio = 0.0
        self.render_edge_density: float | None = 0.1
        self.render_near_white_ratio: float | None = 0.8
        self.render_entropy: float | None = None
        self.render_probably_blank: bool | None = False
        self.critical_token_risk = 0.0
        self.critical_token_kinds: tuple[str, ...] = ()
        self.outputs = {"fast": _StubOutput(), "strong": _StubOutput()}
        self.unknown_fields: tuple[str, ...] = ()
        for key, value in overrides.items():
            setattr(self, key, value)


def test_the_replay_adapter_plans_from_runtime_visible_features_only() -> None:
    from akc_router.planner import build_replay_policy

    policy = build_replay_policy(strong="strong", primary="fast")
    plan = policy.plan(_StubUnitFeatures())
    assert plan.routes[0] == "fast"
    assert plan.accepted == "fast"
    assert any(code.startswith("speculation_class:") for code in plan.reason_codes)


def test_the_replay_adapter_reports_unresolved_when_no_output_exists() -> None:
    from akc_router.planner import build_replay_policy

    policy = build_replay_policy(strong="strong", primary="fast")
    plan = policy.plan(_StubUnitFeatures(outputs={"fast": _StubOutput(present=False)}))
    assert plan.accepted is None
    assert plan.unresolved_reason


def test_the_replay_adapter_keeps_unmeasured_signals_unknown() -> None:
    from akc_router.replay_adapter import replay_risk_vector

    vector = replay_risk_vector(
        _StubUnitFeatures(render_edge_density=None, unknown_fields=("render_near_white_ratio",))
    )
    assert vector.is_unknown(RiskFeature.SMALL_TEXT_RISK)
    assert vector.is_unknown(RiskFeature.IMAGE_SEMANTICS_RISK)
    assert vector.is_unknown(RiskFeature.HANDWRITING_RISK)
    assert set(vector.signals) == set(RiskFeature)
