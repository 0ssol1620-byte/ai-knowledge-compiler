"""Execution plan contracts (blueprint 2026-09-08 §18, §23, §24, §55, Appendix D/G).

These are contracts only. Nothing here plans, schedules or executes anything:
the planner is WP-R6 and is not part of this work package.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from akc_cir import ContractModel, Sha256
from pydantic import Field, model_validator

from .models import DataPolicy, Route
from .preflight import PageTechnicalClass
from .risk import RiskVector

Identifier = Annotated[str, Field(min_length=1, max_length=256)]
LatencyMs = Annotated[float, Field(ge=0.0)]
TERMINAL_ROUTES = frozenset({Route.UNRESOLVED, Route.QUARANTINE})


class DeadlineClass(StrEnum):
    INTERACTIVE = "interactive"
    STANDARD = "standard"
    BATCH = "batch"


class ExecutionLane(StrEnum):
    """The ten §25 execution roles. A role is not a model.

    Separating the role from the model is the point: a lane names *what job the
    page needs done*, and `portfolio.py` binds it to a concrete model only where
    registry and Arena evidence supports the binding. Nothing here asserts that
    any model can do any of these jobs.
    """

    NATIVE = "native"
    AUTHORITY = "authority"
    FAST_VISUAL = "fast_visual"
    PEER_VISUAL = "peer_visual"
    TABLE_SPECIALIST = "table_specialist"
    FORMULA_SPECIALIST = "formula_specialist"
    CHART_SPECIALIST = "chart_specialist"
    DEGRADED_SCAN_SPECIALIST = "degraded_scan_specialist"
    EXTERNAL_ADJUDICATOR = "external_adjudicator"
    HUMAN_REVIEW = "human_review"


class DependencyKind(StrEnum):
    """§23 cross-page dependency kinds."""

    CONTINUED_TABLE = "continued_table"
    FIGURE_CAPTION = "figure_caption"
    FOOTNOTE = "footnote"
    SLIDE_NOTES = "slide_notes"
    SHEET_FORMULA = "sheet_formula"
    IMAGE_CALLOUT = "image_callout"
    EMAIL_ATTACHMENT = "email_attachment"
    XBRL_CONTEXT = "xbrl_context"


class VerificationPolicy(StrEnum):
    NONE = "none"
    PEER_AGREEMENT = "peer_agreement"
    AUTHORITY_MATCH = "authority_match"
    INDEPENDENT_VERIFIER = "independent_verifier"
    HUMAN_REVIEW = "human_review"


class EscalationPolicy(StrEnum):
    BOUNDED_RETRY = "bounded_retry"
    PEER_ESCALATION = "peer_escalation"
    REGION_RECOVERY = "region_recovery"
    AUTHORITY_LANE = "authority_lane"
    FAIL_CLOSED = "fail_closed"


class RegionType(StrEnum):
    TEXT_BLOCK = "text_block"
    TABLE = "table"
    FORMULA = "formula"
    CHART = "chart"
    FIGURE = "figure"
    SIGNATURE = "signature"
    HANDWRITING = "handwriting"
    STAMP = "stamp"


class CustomerVisibleState(StrEnum):
    """Appendix G. The only router states a customer surface may show."""

    INSPECTING_SOURCE = "inspecting_source"
    READING_NATIVE_STRUCTURE = "reading_native_structure"
    VERIFYING_VISUAL_CONTENT = "verifying_visual_content"
    RECOVERING_DIFFICULT_REGIONS = "recovering_difficult_regions"
    CHECKING_EVIDENCE = "checking_evidence"
    COMPILING_CANDIDATE_WORLD = "compiling_candidate_world"
    NEEDS_REVIEW = "needs_review"
    READY_TO_ACTIVATE = "ready_to_activate"


CUSTOMER_VISIBLE_COPY: dict[CustomerVisibleState, str] = {
    CustomerVisibleState.INSPECTING_SOURCE: "Inspecting source",
    CustomerVisibleState.READING_NATIVE_STRUCTURE: "Reading native structure",
    CustomerVisibleState.VERIFYING_VISUAL_CONTENT: "Verifying visual content",
    CustomerVisibleState.RECOVERING_DIFFICULT_REGIONS: "Recovering difficult regions",
    CustomerVisibleState.CHECKING_EVIDENCE: "Checking evidence",
    CustomerVisibleState.COMPILING_CANDIDATE_WORLD: "Compiling candidate World",
    CustomerVisibleState.NEEDS_REVIEW: "Needs review",
    CustomerVisibleState.READY_TO_ACTIVATE: "Ready to activate",
}

#: §55 / Appendix G. Wire names that must never appear in a public DTO.
INTERNAL_ONLY_PLAN_FIELDS: frozenset[str] = frozenset(
    {
        "riskVector",
        "candidateRoutes",
        "primaryRoute",
        "speculativeRoutes",
        "verificationPolicy",
        "escalationPolicy",
        "costBudget",
        "predictedVerifiedCost",
        "plannerRevision",
        "portfolioRevision",
        "featureManifestSha256",
        "parallelismBudget",
        "batchGroup",
        "priority",
        "peer",
        "specialist",
        "verificationContract",
    }
)


class ExecutionWave(ContractModel):
    """One lane's slice of a wave. Pages are executed by risk, not 1..N (§19)."""

    wave_index: Annotated[int, Field(ge=0)]
    lane: ExecutionLane
    unit_ids: tuple[Identifier, ...]
    batch_group: Identifier | None = None

    @model_validator(mode="after")
    def enforce_non_empty_unique_units(self) -> ExecutionWave:
        if not self.unit_ids:
            raise ValueError("an execution wave must carry at least one unit")
        if len(set(self.unit_ids)) != len(self.unit_ids):
            raise ValueError("an execution wave must not repeat a unit")
        return self


class DependencyEdge(ContractModel):
    """§23 edge. `to_unit_id` cannot be assembled before `from_unit_id` lands."""

    from_unit_id: Identifier
    to_unit_id: Identifier
    kind: DependencyKind
    blocking: bool = True

    @model_validator(mode="after")
    def enforce_no_self_edge(self) -> DependencyEdge:
        if self.from_unit_id == self.to_unit_id:
            raise ValueError("a dependency edge must connect two different units")
        return self


class CropGeometry(ContractModel):
    page_index0: Annotated[int, Field(ge=0)]
    x: Annotated[float, Field(ge=0.0)]
    y: Annotated[float, Field(ge=0.0)]
    width: Annotated[float, Field(gt=0.0)]
    height: Annotated[float, Field(gt=0.0)]


class RegionExecutionPlan(ContractModel):
    """§18 RegionExecutionPlan."""

    region_id: Identifier
    source_locator: Identifier
    type: RegionType
    risk_vector: RiskVector
    crop_geometry: CropGeometry
    scale_dpi: Annotated[int, Field(ge=72, le=1200)]
    primary: Route
    peer: Route | None = None
    specialist: Route | None = None
    verification_contract: VerificationPolicy

    @model_validator(mode="after")
    def enforce_executable_routes(self) -> RegionExecutionPlan:
        if self.primary in TERMINAL_ROUTES:
            raise ValueError("a terminal isolation state is not an executable primary route")
        if self.peer is not None and self.peer == self.primary:
            raise ValueError("a peer route must differ from the primary route")
        return self


class PageExecutionPlan(ContractModel):
    """§18 PageExecutionPlan."""

    page_id: Identifier
    technical_class: PageTechnicalClass
    risk_vector: RiskVector
    authority_sources: tuple[Identifier, ...] = ()
    candidate_routes: tuple[Route, ...]
    primary_route: Route
    speculative_routes: tuple[Route, ...] = ()
    verification_policy: VerificationPolicy
    escalation_policy: EscalationPolicy
    batch_group: Identifier | None = None
    priority: Annotated[int, Field(ge=0, le=1000)] = 500
    dependencies: tuple[DependencyEdge, ...] = ()

    @model_validator(mode="after")
    def enforce_route_set_is_closed(self) -> PageExecutionPlan:
        if not self.candidate_routes:
            raise ValueError("a page plan requires at least one candidate route")
        candidates = set(self.candidate_routes)
        if len(candidates) != len(self.candidate_routes):
            raise ValueError("candidate routes must not repeat")
        if self.primary_route not in candidates:
            raise ValueError("the primary route must be one of the candidate routes")
        if self.primary_route in TERMINAL_ROUTES:
            raise ValueError("a terminal isolation state is not an executable primary route")
        speculative = set(self.speculative_routes)
        if not speculative <= candidates:
            raise ValueError("speculative routes must be drawn from the candidate routes")
        if self.primary_route in speculative:
            raise ValueError("the primary route is not also a speculative route")
        return self


class DocumentExecutionPlan(ContractModel):
    """§18 DocumentExecutionPlan.

    `predicted_p50` / `predicted_p95` are wall-clock milliseconds. A plan with
    unresolved constraints is not executable; it is reported, never guessed past.
    """

    plan_id: Identifier
    source_version_id: Identifier
    planner_revision: Identifier
    feature_manifest_sha256: Sha256
    portfolio_revision: Identifier
    data_policy: DataPolicy
    deadline_class: DeadlineClass
    cost_budget: Annotated[float, Field(ge=0.0)]
    parallelism_budget: Annotated[int, Field(ge=1, le=1024)]
    execution_waves: tuple[ExecutionWave, ...] = ()
    dependency_edges: tuple[DependencyEdge, ...] = ()
    predicted_p50: LatencyMs
    predicted_p95: LatencyMs
    predicted_verified_cost: Annotated[float, Field(ge=0.0)]
    unresolved_constraints: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_plan_shape(self) -> DocumentExecutionPlan:
        if self.predicted_p95 < self.predicted_p50:
            raise ValueError("predicted p95 cannot be below predicted p50")
        if self.predicted_verified_cost > self.cost_budget:
            raise ValueError("predicted verified cost exceeds the cost budget")
        waves = [(wave.wave_index, wave.lane) for wave in self.execution_waves]
        if len(set(waves)) != len(waves):
            raise ValueError("a wave index carries each lane at most once")
        return self

    @property
    def is_executable(self) -> bool:
        """Fail closed: a plan with an unresolved constraint is not dispatched."""
        return not self.unresolved_constraints and bool(self.execution_waves)


class OperationalFailure(StrEnum):
    """§24 infrastructure failure. Never merged with the semantic family."""

    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    WORKER_LOST = "worker_lost"
    QUEUE_BACKPRESSURE = "queue_backpressure"
    RATE_LIMITED = "rate_limited"


class SemanticFailure(StrEnum):
    """§24 model/content failure. Never merged with the operational family."""

    EMPTY_OUTPUT = "empty_output"
    REPETITION_FAILURE = "repetition_failure"
    ABNORMAL_OUTPUT = "abnormal_output"
    PEER_DISAGREEMENT = "peer_disagreement"
    CHART_DISCOVERED = "chart_discovered"
    CRITICAL_NUMERIC_MISMATCH = "critical_numeric_mismatch"
    SECRET_DETECTED = "secret_detected"  # noqa: S105 - a detection trigger, not a credential
    VERIFICATION_FAILED = "verification_failed"


class ReplanAction(StrEnum):
    RETRY_SAME_ROUTE = "retry_same_route"
    INFRA_RETRY = "infra_retry"
    SWITCH_ROUTE = "switch_route"
    ISOLATE_REGION = "isolate_region"
    ADD_SPECIALIST = "add_specialist"
    AUTHORITY_LANE = "authority_lane"
    REMOVE_EXTERNAL_ROUTES = "remove_external_routes"
    UNRESOLVED = "unresolved"


#: §24, verbatim. An operational failure never justifies a semantic recovery.
OPERATIONAL_ACTIONS: dict[OperationalFailure, frozenset[ReplanAction]] = {
    OperationalFailure.PROVIDER_TIMEOUT: frozenset(
        {ReplanAction.INFRA_RETRY, ReplanAction.SWITCH_ROUTE}
    ),
    OperationalFailure.PROVIDER_UNAVAILABLE: frozenset(
        {ReplanAction.INFRA_RETRY, ReplanAction.SWITCH_ROUTE}
    ),
    OperationalFailure.WORKER_LOST: frozenset({ReplanAction.INFRA_RETRY}),
    OperationalFailure.QUEUE_BACKPRESSURE: frozenset({ReplanAction.INFRA_RETRY}),
    OperationalFailure.RATE_LIMITED: frozenset(
        {ReplanAction.INFRA_RETRY, ReplanAction.SWITCH_ROUTE}
    ),
}

SEMANTIC_ACTIONS: dict[SemanticFailure, frozenset[ReplanAction]] = {
    SemanticFailure.EMPTY_OUTPUT: frozenset({ReplanAction.RETRY_SAME_ROUTE}),
    SemanticFailure.REPETITION_FAILURE: frozenset({ReplanAction.RETRY_SAME_ROUTE}),
    SemanticFailure.ABNORMAL_OUTPUT: frozenset({ReplanAction.SWITCH_ROUTE}),
    SemanticFailure.PEER_DISAGREEMENT: frozenset({ReplanAction.ISOLATE_REGION}),
    SemanticFailure.CHART_DISCOVERED: frozenset({ReplanAction.ADD_SPECIALIST}),
    SemanticFailure.CRITICAL_NUMERIC_MISMATCH: frozenset({ReplanAction.AUTHORITY_LANE}),
    SemanticFailure.SECRET_DETECTED: frozenset({ReplanAction.REMOVE_EXTERNAL_ROUTES}),
    SemanticFailure.VERIFICATION_FAILED: frozenset({ReplanAction.UNRESOLVED}),
}


class DynamicReplanEvent(ContractModel):
    """§24 replan. Exactly one trigger family fires, and it is recorded as itself."""

    plan_id: Identifier
    unit_id: Identifier
    operational_trigger: OperationalFailure | None = None
    semantic_trigger: SemanticFailure | None = None
    action: ReplanAction
    attempt_number: Annotated[int, Field(ge=1, le=5)]
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def enforce_single_trigger_family(self) -> DynamicReplanEvent:
        if (self.operational_trigger is None) == (self.semantic_trigger is None):
            raise ValueError("exactly one of operational_trigger or semantic_trigger is recorded")
        if not self.reason_codes:
            raise ValueError("a replan event requires at least one reason code")
        if self.operational_trigger is not None:
            allowed = OPERATIONAL_ACTIONS[self.operational_trigger]
        else:
            assert self.semantic_trigger is not None
            allowed = SEMANTIC_ACTIONS[self.semantic_trigger]
        if self.action not in allowed:
            raise ValueError(f"action {self.action} is not a permitted response to this trigger")
        return self


class RouterReplayRecord(ContractModel):
    """Appendix D. Hidden evaluation truth is never visible to the runtime."""

    unit_id: Identifier
    features_revision: Identifier
    router_revision: Identifier
    allowed_routes: tuple[Route, ...]
    selected_plan: Identifier
    speculative_plans: tuple[Identifier, ...] = ()
    escalations: tuple[str, ...] = ()
    verification: VerificationPolicy
    final_disposition: Literal["accepted", "unresolved", "quarantined"]
    hidden_evaluation_visible_to_runtime: Literal[False] = False


class PublicRouterStatus(ContractModel):
    """The public projection (§55). Carries no internal field of any plan."""

    state: CustomerVisibleState
    label: Identifier
    units_total: Annotated[int, Field(ge=0)]
    units_completed: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def enforce_completion_bound(self) -> PublicRouterStatus:
        if self.units_completed > self.units_total:
            raise ValueError("completed units cannot exceed total units")
        if self.label != CUSTOMER_VISIBLE_COPY[self.state]:
            raise ValueError("public label must be the Appendix G copy for the state")
        return self


def public_router_status(
    plan: DocumentExecutionPlan,
    state: CustomerVisibleState,
    *,
    units_completed: int,
) -> PublicRouterStatus:
    """Project a plan to the customer surface. Only §55-public facts survive."""
    units_total = sum(len(wave.unit_ids) for wave in plan.execution_waves)
    return PublicRouterStatus(
        state=state,
        label=CUSTOMER_VISIBLE_COPY[state],
        units_total=units_total,
        units_completed=units_completed,
    )


__all__ = [
    "CUSTOMER_VISIBLE_COPY",
    "INTERNAL_ONLY_PLAN_FIELDS",
    "OPERATIONAL_ACTIONS",
    "SEMANTIC_ACTIONS",
    "TERMINAL_ROUTES",
    "CropGeometry",
    "CustomerVisibleState",
    "DeadlineClass",
    "DependencyEdge",
    "DependencyKind",
    "DocumentExecutionPlan",
    "DynamicReplanEvent",
    "EscalationPolicy",
    "ExecutionLane",
    "ExecutionWave",
    "OperationalFailure",
    "PageExecutionPlan",
    "PublicRouterStatus",
    "RegionExecutionPlan",
    "RegionType",
    "ReplanAction",
    "RouterReplayRecord",
    "SemanticFailure",
    "VerificationPolicy",
    "public_router_status",
]
