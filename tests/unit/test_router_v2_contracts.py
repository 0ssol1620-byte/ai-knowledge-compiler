"""Router v2 contract tests (blueprint 2026-09-08 §16, §18, §21, §24, §27, §55, Appendix D/G)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from akc_router import (
    CUSTOMER_VISIBLE_COPY,
    INTERNAL_ONLY_PLAN_FIELDS,
    CropGeometry,
    CustomerVisibleState,
    DataPolicy,
    DeadlineClass,
    DependencyEdge,
    DependencyKind,
    DocumentExecutionPlan,
    DynamicReplanEvent,
    EscalationPolicy,
    ExecutionLane,
    ExecutionWave,
    ObservationSource,
    OperationalFailure,
    PageExecutionPlan,
    PageTechnicalClass,
    ProcessingMode,
    RegionExecutionPlan,
    RegionType,
    ReplanAction,
    RiskFeature,
    RiskSignal,
    RiskVector,
    Route,
    RouterReplayRecord,
    SemanticFailure,
    SpeculationClass,
    UnknownSpeculationClassError,
    VerificationPolicy,
    filter_candidate_routes,
    public_router_status,
    speculate,
)
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ValidationError
from referencing import Registry, Resource

SCHEMAS = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "schemas"
DIGEST = "sha256:" + "a" * 64


def _registry() -> Registry[Any]:
    resources = []
    for path in SCHEMAS.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((str(schema["$id"]), Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def _validate(name: str, model: BaseModel) -> dict[str, Any]:
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=_registry(), format_checker=FormatChecker())
    payload = model.model_dump(mode="json", by_alias=True)
    validator.validate(payload)
    validator.validate(model.model_dump(mode="json", by_alias=True, exclude_none=True))
    assert type(model).model_validate(payload) == model
    return payload


def _risk_vector() -> RiskVector:
    return RiskVector(
        signals={
            RiskFeature.NUMERIC_RISK: RiskSignal(
                value=0.71,
                confidence=0.55,
                observation_source=ObservationSource.NATIVE_INSPECT,
                calibrated=True,
            ),
            RiskFeature.HANDWRITING_RISK: RiskSignal(
                observation_source=ObservationSource.UNAVAILABLE, unknown=True
            ),
        },
        unknown_features=(RiskFeature.HANDWRITING_RISK, RiskFeature.SMALL_TEXT_RISK),
        language_script=("Latn", "Hang"),
        authority_available=True,
    )


def _page_plan() -> PageExecutionPlan:
    return PageExecutionPlan(
        page_id="page-1",
        technical_class=PageTechnicalClass.TABLE_HEAVY,
        risk_vector=_risk_vector(),
        authority_sources=("xbrl:us-gaap:Revenues",),
        candidate_routes=(Route.NATIVE, Route.PADDLE_VL, Route.PADDLE_FAST),
        primary_route=Route.NATIVE,
        speculative_routes=(Route.PADDLE_VL,),
        verification_policy=VerificationPolicy.AUTHORITY_MATCH,
        escalation_policy=EscalationPolicy.REGION_RECOVERY,
        batch_group="batch-a",
        priority=800,
        dependencies=(
            DependencyEdge(
                from_unit_id="page-1", to_unit_id="page-2", kind=DependencyKind.CONTINUED_TABLE
            ),
        ),
    )


def _document_plan(**overrides: Any) -> DocumentExecutionPlan:
    fields: dict[str, Any] = {
        "plan_id": "plan-1",
        "source_version_id": "source-version-1",
        "planner_revision": "planner-0.1.0",
        "feature_manifest_sha256": DIGEST,
        "portfolio_revision": "portfolio-0.1.0",
        "data_policy": DataPolicy(),
        "deadline_class": DeadlineClass.STANDARD,
        "cost_budget": 12.0,
        "parallelism_budget": 8,
        "execution_waves": (
            ExecutionWave(
                wave_index=0,
                lane=ExecutionLane.NATIVE,
                unit_ids=("page-1", "page-2"),
                batch_group="batch-a",
            ),
            ExecutionWave(wave_index=0, lane=ExecutionLane.FAST_VISUAL, unit_ids=("page-3",)),
        ),
        "dependency_edges": (
            DependencyEdge(
                from_unit_id="page-1", to_unit_id="page-2", kind=DependencyKind.CONTINUED_TABLE
            ),
        ),
        "predicted_p50": 1200.0,
        "predicted_p95": 4800.0,
        "predicted_verified_cost": 3.5,
        "unresolved_constraints": (),
    }
    fields.update(overrides)
    return DocumentExecutionPlan(**fields)


def test_risk_vector_round_trips_and_validates() -> None:
    payload = _validate("risk-vector", _risk_vector())
    assert payload["signals"]["handwriting_risk"]["confidence"] is None


def test_document_page_and_region_plans_round_trip_and_validate() -> None:
    _validate("document-execution-plan", _document_plan())
    _validate("page-execution-plan", _page_plan())
    _validate(
        "region-execution-plan",
        RegionExecutionPlan(
            region_id="region-1",
            source_locator="page-1#table-0",
            type=RegionType.TABLE,
            risk_vector=_risk_vector(),
            crop_geometry=CropGeometry(page_index0=0, x=12.0, y=40.0, width=380.0, height=220.0),
            scale_dpi=300,
            primary=Route.PADDLE_VL,
            peer=Route.PADDLE_FAST,
            verification_contract=VerificationPolicy.INDEPENDENT_VERIFIER,
        ),
    )


def test_replay_record_cannot_admit_hidden_evaluation() -> None:
    record = RouterReplayRecord(
        unit_id="page-1",
        features_revision="features-0.1.0",
        router_revision="router-0.1.0",
        allowed_routes=(Route.NATIVE, Route.PADDLE_VL),
        selected_plan="plan-1",
        verification=VerificationPolicy.PEER_AGREEMENT,
        final_disposition="accepted",
    )
    payload = _validate("router-replay-record", record)
    assert payload["hiddenEvaluationVisibleToRuntime"] is False
    with pytest.raises(ValidationError):
        RouterReplayRecord.model_validate(payload | {"hiddenEvaluationVisibleToRuntime": True})


def test_unknown_signal_is_never_read_as_confident() -> None:
    vector = _risk_vector()
    assert vector.confidence(RiskFeature.HANDWRITING_RISK) == 0.0
    assert vector.confidence(RiskFeature.SMALL_TEXT_RISK) == 0.0
    assert vector.is_unknown(RiskFeature.ROTATION_SKEW_RISK)
    with pytest.raises(ValidationError):
        RiskSignal(
            value=1.0,
            confidence=1.0,
            observation_source=ObservationSource.VISUAL_SCAN,
            unknown=True,
        )
    with pytest.raises(ValidationError):
        RiskSignal(observation_source=ObservationSource.UNAVAILABLE)
    with pytest.raises(ValidationError):
        # An unknown signal that is not declared in unknown_features would let a
        # reader believe every listed signal was observed.
        RiskVector(
            signals={
                RiskFeature.SMALL_TEXT_RISK: RiskSignal(
                    observation_source=ObservationSource.UNAVAILABLE, unknown=True
                )
            }
        )


def test_document_plan_rejects_bad_digest_and_negative_budget() -> None:
    with pytest.raises(ValidationError):
        _document_plan(feature_manifest_sha256="not-a-digest")
    with pytest.raises(ValidationError):
        _document_plan(cost_budget=-1.0)
    with pytest.raises(ValidationError):
        _document_plan(parallelism_budget=0)
    with pytest.raises(ValidationError):
        _document_plan(predicted_p95=10.0)
    with pytest.raises(ValidationError):
        _document_plan(predicted_verified_cost=99.0)
    assert not _document_plan(unresolved_constraints=("authority_source_missing",)).is_executable


def test_page_plan_route_set_is_closed() -> None:
    with pytest.raises(ValidationError):
        PageExecutionPlan.model_validate(
            _page_plan().model_dump() | {"primary_route": Route.HPD_FAST}
        )
    with pytest.raises(ValidationError):
        PageExecutionPlan.model_validate(
            _page_plan().model_dump() | {"speculative_routes": (Route.UNLIMITED_LONG,)}
        )
    with pytest.raises(ValidationError):
        PageExecutionPlan.model_validate(
            _page_plan().model_dump()
            | {"primary_route": Route.QUARANTINE, "candidate_routes": (Route.QUARANTINE,)}
        )


def test_speculation_returns_the_section_21_row_and_refuses_unknown_classes() -> None:
    native = speculate(SpeculationClass.NATIVE_CLEAN)
    assert native.primary_lanes == (ExecutionLane.NATIVE,)
    assert native.peer_lanes == ()
    high_risk = speculate("high_risk_text")
    assert high_risk.parallel_peers is True
    assert speculate(SpeculationClass.CROSS_PAGE_TABLE).dependency_group is True
    assert speculate(SpeculationClass.HANDWRITING).verification is VerificationPolicy.HUMAN_REVIEW
    with pytest.raises(UnknownSpeculationClassError):
        speculate("everything_to_every_model")
    assert len({row.speculation_class for row in map(speculate, SpeculationClass)}) == len(
        SpeculationClass
    )


def test_data_policy_filters_external_routes_before_planning() -> None:
    candidates = (Route.NATIVE, Route.PADDLE_VL, Route.MISTRAL_FALLBACK)
    private = filter_candidate_routes(
        candidates, DataPolicy(private_processing=True), mode=ProcessingMode.PRIVATE
    )
    assert Route.MISTRAL_FALLBACK not in private.permitted_routes
    assert private.removed_routes == (Route.MISTRAL_FALLBACK,)
    assert "private_mode" in private.reason_codes

    allowed = filter_candidate_routes(candidates, DataPolicy(external_api_allowed=True))
    assert allowed.permitted_routes == candidates

    secret = filter_candidate_routes(
        candidates, DataPolicy(external_api_allowed=True), secret_detected=True
    )
    assert secret.permitted_routes == (Route.NATIVE, Route.PADDLE_VL)
    assert "secret_detected" in secret.reason_codes
    assert filter_candidate_routes((Route.MISTRAL_FALLBACK,), DataPolicy()).is_empty


def test_replan_keeps_operational_and_semantic_failure_apart() -> None:
    infra = DynamicReplanEvent(
        plan_id="plan-1",
        unit_id="page-1",
        operational_trigger=OperationalFailure.PROVIDER_TIMEOUT,
        action=ReplanAction.INFRA_RETRY,
        attempt_number=1,
        reason_codes=("provider_timeout",),
    )
    assert infra.semantic_trigger is None
    with pytest.raises(ValidationError):
        DynamicReplanEvent(
            plan_id="plan-1",
            unit_id="page-1",
            operational_trigger=OperationalFailure.PROVIDER_TIMEOUT,
            semantic_trigger=SemanticFailure.EMPTY_OUTPUT,
            action=ReplanAction.INFRA_RETRY,
            attempt_number=1,
            reason_codes=("both",),
        )
    with pytest.raises(ValidationError):
        DynamicReplanEvent(
            plan_id="plan-1",
            unit_id="page-1",
            action=ReplanAction.INFRA_RETRY,
            attempt_number=1,
            reason_codes=("neither",),
        )
    with pytest.raises(ValidationError):
        DynamicReplanEvent(
            plan_id="plan-1",
            unit_id="page-1",
            operational_trigger=OperationalFailure.WORKER_LOST,
            action=ReplanAction.AUTHORITY_LANE,
            attempt_number=1,
            reason_codes=("infra_failure_is_not_a_semantic_recovery",),
        )


def test_public_projection_excludes_every_internal_field() -> None:
    plan = _document_plan()
    internal = set(plan.model_dump(mode="json", by_alias=True)) | set(
        _page_plan().model_dump(mode="json", by_alias=True)
    )
    assert INTERNAL_ONLY_PLAN_FIELDS & internal
    status = public_router_status(
        plan, CustomerVisibleState.VERIFYING_VISUAL_CONTENT, units_completed=1
    )
    public = status.model_dump(mode="json", by_alias=True)
    assert not INTERNAL_ONLY_PLAN_FIELDS & set(public)
    assert public["label"] == CUSTOMER_VISIBLE_COPY[CustomerVisibleState.VERIFYING_VISUAL_CONTENT]
    assert public["unitsTotal"] == 3
    with pytest.raises(ValidationError):
        public_router_status(plan, CustomerVisibleState.NEEDS_REVIEW, units_completed=99)
