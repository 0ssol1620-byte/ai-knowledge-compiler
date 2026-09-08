"""WP-R6 adaptive execution planner (program §7-§10, blueprint §18-§24).

Deterministic. No learned component, no scalar blind quality score, no
capability inferred from a model name. The planner turns per-unit `RiskVector`s
into a `DocumentExecutionPlan` by asking one question per unit: *what is the
least expensive path that can be shown to meet the trust floor?*

Four rules it is built around.

**Data policy filters before scoring.** `filter_candidate_routes()` runs on every
unit's candidate set before any cost is computed, so an excluded route is never
even a contender. An empty permitted set is a refusal, not a licence to relax.

**An unknown risk is not a low risk.** A route's failure probability is a
*lower bound* over the §16 features it is sensitive to, plus the names of the
sensitive features nobody measured. A route with unmeasured sensitive features
can only be chosen with verification behind it -- the bound alone is not
evidence it clears the floor.

**The cheapest plan that breaks the trust floor is never chosen.**
`select_expected_verified_cost` filters by the floor first and minimises second,
and a unit with no eligible route becomes an unresolved constraint that makes
the whole plan non-executable.

**Speculation is paid for, not assumed.** A §21 peer lane is launched only when
the primary has an unmeasured sensitive feature, or when the expected reduction
in critical-failure cost exceeds what the peer costs. Nothing here ever runs
every model.

Every threshold and every cost in this module is **uncalibrated**. `PlannerResult
.calibrated` is False unless the caller supplies a calibrated cost model, and the
result carries `uncalibrated_thresholds` in its reason codes so no number here
can be quoted as measured.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .data_policy import filter_candidate_routes
from .execution_plan import (
    TERMINAL_ROUTES,
    CropGeometry,
    DeadlineClass,
    DependencyEdge,
    DocumentExecutionPlan,
    EscalationPolicy,
    ExecutionLane,
    ExecutionWave,
    PageExecutionPlan,
    RegionExecutionPlan,
    RegionType,
    RouterReplayRecord,
    VerificationPolicy,
)
from .expected_verified_cost import RouteCostCandidate, select_expected_verified_cost
from .models import DataPolicy, ProcessingMode, Route
from .portfolio import Portfolio, UnboundLaneError
from .preflight import PageTechnicalClass
from .research import ScheduleScenario, estimate_schedule
from .risk import RiskFeature, RiskVector
from .speculation import SpeculationClass, SpeculationPolicy, speculate

PLANNER_REVISION = "planner-v2.0.0-shadow"

_F = RiskFeature

#: Uncalibrated. Which §16 features each route is known to struggle with, and
#: how strongly. Derived from what the route *is* -- a native text extractor
#: cannot read a scan, a fast visual pass loses small and degraded text -- never
#: from a model's name and never from a benchmark leaderboard row.
ROUTE_SENSITIVITY: Mapping[Route, Mapping[RiskFeature, float]] = {
    Route.NATIVE: {
        _F.SCAN_NEED: 1.0,
        _F.SOURCE_INTEGRITY_RISK: 1.0,
        _F.TEXT_LOSS_RISK: 0.9,
        _F.READING_ORDER_RISK: 0.6,
        _F.CHART_VISUAL_RISK: 0.8,
        _F.HANDWRITING_RISK: 1.0,
    },
    Route.HPD_FAST: {
        _F.DEGRADATION_RISK: 0.9,
        _F.SMALL_TEXT_RISK: 0.8,
        _F.HANDWRITING_RISK: 0.9,
        _F.FORMULA_RISK: 0.7,
        _F.TABLE_STRUCTURE_RISK: 0.6,
    },
    Route.PADDLE_FAST: {
        _F.DEGRADATION_RISK: 0.8,
        _F.SMALL_TEXT_RISK: 0.7,
        _F.HANDWRITING_RISK: 0.9,
        _F.FORMULA_RISK: 0.7,
        _F.TABLE_STRUCTURE_RISK: 0.6,
    },
    Route.PADDLE_VL: {
        _F.DEGRADATION_RISK: 0.5,
        _F.HANDWRITING_RISK: 0.7,
        _F.ROTATION_SKEW_RISK: 0.4,
        _F.FORMULA_RISK: 0.4,
    },
    Route.UNLIMITED_LONG: {
        _F.DEGRADATION_RISK: 0.6,
        _F.TABLE_STRUCTURE_RISK: 0.5,
        _F.HANDWRITING_RISK: 0.8,
    },
    Route.MISTRAL_FALLBACK: {
        _F.DEGRADATION_RISK: 0.6,
        _F.HANDWRITING_RISK: 0.8,
        _F.SENSITIVE_DATA_RISK: 1.0,
    },
    Route.REGION_RECOVERY: {_F.DEGRADATION_RISK: 0.4, _F.HANDWRITING_RISK: 0.6},
    Route.AUTHORITY_RECONSTRUCTION: {_F.AUTHORITY_CONFLICT_RISK: 1.0},
}


@dataclass(frozen=True, slots=True)
class RouteCost:
    """Uncalibrated per-route cost terms, in the `RouteDecision` credit unit."""

    inference: float
    verification: float = 0.0
    recovery: float = 0.0
    seconds_per_unit: float = 1.0
    cold_start_seconds: float = 0.0
    cold_start_probability: float = 0.0


@dataclass(frozen=True, slots=True)
class CostModel:
    """What a plan is scored against. Predictions, not measurements."""

    routes: Mapping[Route, RouteCost]
    critical_failure_penalty: float = 40.0
    silent_loss_penalty: float = 25.0
    p95_penalty_per_second: float = 0.0
    #: Assumed share of the primary's failure that a peer *also* fails on. 1.0
    #: assumes no independence at all. This is an assumption written by the
    #: planner's author; no measurement fixes it.
    assumed_peer_joint_failure_ratio: float = 0.8
    calibrated: bool = False

    def cost(self, route: Route) -> RouteCost:
        found = self.routes.get(route)
        if found is None:
            raise UnknownRouteCostError(f"no cost model entry for route {route.value}")
        return found


class UnknownRouteCostError(ValueError):
    """Raised instead of assuming a price for an unpriced route."""


#: A starting cost model so the planner runs in shadow without a caller having
#: to invent one. Relative shape follows the existing credit schedule
#: (`engine.estimate_route_credits`): native is cheap, OCR is one credit,
#: external and human lanes are expensive. Uncalibrated, and it says so.
DEFAULT_COST_MODEL = CostModel(
    routes={
        Route.NATIVE: RouteCost(inference=0.25, seconds_per_unit=0.2),
        Route.HPD_FAST: RouteCost(inference=1.0, seconds_per_unit=1.5, cold_start_seconds=90.0),
        Route.PADDLE_FAST: RouteCost(inference=1.0, seconds_per_unit=1.6, cold_start_seconds=90.0),
        Route.PADDLE_VL: RouteCost(
            inference=1.6, verification=0.2, seconds_per_unit=3.0, cold_start_seconds=120.0
        ),
        Route.UNLIMITED_LONG: RouteCost(
            inference=2.0, seconds_per_unit=4.0, cold_start_seconds=120.0
        ),
        Route.MISTRAL_FALLBACK: RouteCost(inference=3.0, verification=0.5, seconds_per_unit=2.0),
        Route.REGION_RECOVERY: RouteCost(inference=0.8, seconds_per_unit=1.0),
        Route.AUTHORITY_RECONSTRUCTION: RouteCost(
            inference=0.5, verification=0.5, seconds_per_unit=2.0
        ),
    },
    calibrated=False,
)


@dataclass(frozen=True, slots=True)
class RegionFeatures:
    """A region the caller actually located. No bbox is ever invented."""

    region_id: str
    source_locator: str
    region_type: RegionType
    risk_vector: RiskVector
    crop_geometry: CropGeometry
    scale_dpi: int = 300


@dataclass(frozen=True, slots=True)
class UnitFeatures:
    """One planning unit: a page, plus any regions located inside it."""

    unit_id: str
    page_index0: int
    technical_class: PageTechnicalClass
    risk_vector: RiskVector
    authority_domain: str | None = None
    secret_detected: bool = False
    regions: tuple[RegionFeatures, ...] = ()


@dataclass(frozen=True, slots=True)
class CapacityState:
    """Queue, warm/cold and GPU facts the plan has to live inside."""

    parallelism_budget: int = 4
    gpu_capacity: int = 4
    warm_routes: frozenset[Route] = frozenset()
    queue_seconds: float = 0.0
    max_speculative_units: int | None = None


@dataclass(frozen=True, slots=True)
class PlannerRequest:
    source_version_id: str
    units: tuple[UnitFeatures, ...]
    data_policy: DataPolicy
    mode: ProcessingMode
    portfolio: Portfolio
    ready_routes: frozenset[Route]
    deadline_class: DeadlineClass = DeadlineClass.STANDARD
    deadline_ms: float | None = None
    cost_budget: float = 0.0
    trust_floor: float = 0.10
    #: The floor that applies when an *independent* check follows the model --
    #: a human reviewer or an authority match. It is deliberately a separate,
    #: explicit number rather than a discount applied to `trust_floor`: the
    #: floor is on verified output, and a handwriting page a person reads is a
    #: different bet from one nobody reads. `None` keeps the strict floor
    #: everywhere, which refuses handwriting rather than guessing at it.
    verified_trust_floor: float | None = None
    trust_floor_calibrated: bool = False
    capacity: CapacityState = CapacityState()
    dependency_edges: tuple[DependencyEdge, ...] = ()
    authority_available: bool = False
    cost_model: CostModel = DEFAULT_COST_MODEL
    feature_manifest_sha256: str = "sha256:" + "0" * 64


@dataclass(frozen=True, slots=True)
class RouteRisk:
    """A lower bound on critical failure, and what was not measured."""

    route: Route
    lower_bound: float
    unmeasured_sensitive: tuple[RiskFeature, ...] = ()

    @property
    def bounded(self) -> bool:
        return not self.unmeasured_sensitive


@dataclass(frozen=True, slots=True)
class UnitPlan:
    """Per-unit decision, kept beside the contract types for replay and audit."""

    unit_id: str
    speculation_class: SpeculationClass
    page_plan: PageExecutionPlan | None
    region_plans: tuple[RegionExecutionPlan, ...] = ()
    primary_lane: ExecutionLane | None = None
    speculative_lanes: tuple[ExecutionLane, ...] = ()
    expected_verified_cost: float = 0.0
    reason_codes: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannerResult:
    """The plan, or an honest refusal, plus why."""

    plan: DocumentExecutionPlan | None
    unit_plans: tuple[UnitPlan, ...] = ()
    reason_codes: tuple[str, ...] = ()
    unresolved_constraints: tuple[str, ...] = ()
    calibrated: bool = False

    @property
    def is_executable(self) -> bool:
        return self.plan is not None and self.plan.is_executable


def plan_document(request: PlannerRequest) -> PlannerResult:
    """Plan one source version. Deterministic for a given request."""
    reasons: list[str] = []
    if not request.cost_model.calibrated or not request.trust_floor_calibrated:
        reasons.append("uncalibrated_thresholds")
    if not request.units:
        return PlannerResult(
            plan=None,
            reason_codes=(*reasons, "no_units_to_plan"),
            unresolved_constraints=("no_units_to_plan",),
        )

    unit_plans = tuple(_plan_unit(unit, request, speculate_allowed=True) for unit in request.units)
    total = sum(item.expected_verified_cost for item in unit_plans)
    if total > request.cost_budget and request.cost_budget > 0:
        # Speculation is the first thing to go: it is the only optional spend.
        reasons.append("speculation_dropped_for_cost_budget")
        unit_plans = tuple(
            _plan_unit(unit, request, speculate_allowed=False) for unit in request.units
        )
        total = sum(item.expected_verified_cost for item in unit_plans)

    unresolved = tuple(dict.fromkeys(code for item in unit_plans for code in item.unresolved))
    if total > request.cost_budget:
        unresolved = (*unresolved, "cost_budget_exceeded")
    if unresolved:
        return PlannerResult(
            plan=None,
            unit_plans=unit_plans,
            reason_codes=tuple(reasons),
            unresolved_constraints=unresolved,
            calibrated=False,
        )

    waves, edges = _build_waves(unit_plans, request)
    p50_ms, p95_ms = _estimate_latency(unit_plans, request)
    if request.deadline_ms is not None and p95_ms > request.deadline_ms:
        unresolved = ("deadline_p95_exceeded",)
        return PlannerResult(
            plan=None,
            unit_plans=unit_plans,
            reason_codes=tuple(reasons),
            unresolved_constraints=unresolved,
            calibrated=False,
        )

    plan = DocumentExecutionPlan(
        plan_id=_plan_id(request),
        source_version_id=request.source_version_id,
        planner_revision=PLANNER_REVISION,
        feature_manifest_sha256=request.feature_manifest_sha256,
        portfolio_revision=request.portfolio.revision,
        data_policy=request.data_policy,
        deadline_class=request.deadline_class,
        cost_budget=request.cost_budget,
        parallelism_budget=max(1, min(request.capacity.parallelism_budget, 1024)),
        execution_waves=waves,
        dependency_edges=edges,
        predicted_p50=p50_ms,
        predicted_p95=p95_ms,
        predicted_verified_cost=total,
    )
    return PlannerResult(
        plan=plan,
        unit_plans=unit_plans,
        reason_codes=tuple(reasons),
        calibrated=request.cost_model.calibrated and request.trust_floor_calibrated,
    )


# --- unit planning -----------------------------------------------------------


def classify_speculation(unit: UnitFeatures) -> SpeculationClass:
    """Pick the §21 row from *named* features, never from one blended score.

    An unknown feature never selects a class: a class is a claim about the page,
    and the fall-through classes carry more verification, not less.
    """
    risk = unit.risk_vector
    if unit.authority_domain == "sec":
        return SpeculationClass.SEC_FILING
    if unit.authority_domain == "opendart":
        return SpeculationClass.OPENDART_FINANCE
    if _observed(risk, _F.HANDWRITING_RISK) >= 0.5:
        return SpeculationClass.HANDWRITING
    if _observed(risk, _F.DEGRADATION_RISK) >= 0.5:
        return SpeculationClass.DEGRADED_PHOTO
    table = _observed(risk, _F.TABLE_STRUCTURE_RISK)
    if table >= 0.2:
        if risk.authority_available or _observed(risk, _F.NUMERIC_RISK) >= 0.5:
            return SpeculationClass.CRITICAL_FINANCIAL_TABLE
        if _observed(risk, _F.CROSS_PAGE_DEPENDENCY_RISK) >= 0.5:
            return SpeculationClass.CROSS_PAGE_TABLE
        return SpeculationClass.REGULAR_TABLE
    if _observed(risk, _F.CHART_VISUAL_RISK) >= 0.5:
        return SpeculationClass.CHART_HEAVY
    if _observed(risk, _F.FORMULA_RISK) >= 0.2:
        return SpeculationClass.FORMULA_HEAVY
    if unit.technical_class is PageTechnicalClass.NATIVE_CLEAN:
        return SpeculationClass.NATIVE_CLEAN
    if _observed(risk, _F.TEXT_LOSS_RISK) >= 0.5:
        return SpeculationClass.HIGH_RISK_TEXT
    return SpeculationClass.ORDINARY_SCAN


def route_risk(route: Route, risk: RiskVector) -> RouteRisk:
    """Lower-bound critical-failure probability, plus the unmeasured features."""
    sensitivity = ROUTE_SENSITIVITY.get(route, {})
    bound = 0.0
    unmeasured: list[RiskFeature] = []
    for feature, weight in sensitivity.items():
        if risk.is_unknown(feature):
            unmeasured.append(feature)
            continue
        signal = risk.signals.get(feature)
        value = 0.0 if signal is None or signal.value is None else signal.value
        bound = max(bound, weight * value)
    return RouteRisk(
        route=route,
        lower_bound=min(1.0, bound),
        unmeasured_sensitive=tuple(sorted(unmeasured, key=lambda item: item.value)),
    )


def _plan_unit(unit: UnitFeatures, request: PlannerRequest, *, speculate_allowed: bool) -> UnitPlan:
    speculation_class = classify_speculation(unit)
    policy = speculate(speculation_class)
    reasons: list[str] = [f"speculation_class:{speculation_class.value}"]

    primary_routes, dropped_lanes = _routes_for_lanes(policy.primary_lanes, request)
    peer_routes, dropped_peers = _routes_for_lanes(policy.peer_lanes, request)
    reasons.extend(f"lane_unavailable:{lane.value}" for lane in dropped_lanes + dropped_peers)

    candidates = tuple(dict.fromkeys(primary_routes + peer_routes))
    if not candidates:
        return UnitPlan(
            unit_id=unit.unit_id,
            speculation_class=speculation_class,
            page_plan=None,
            reason_codes=tuple(reasons),
            unresolved=(f"no_qualified_lane:{unit.unit_id}",),
        )

    # §27: policy filters the candidate set BEFORE anything is scored.
    permitted = filter_candidate_routes(
        candidates,
        request.data_policy,
        mode=request.mode,
        secret_detected=unit.secret_detected,
    )
    reasons.extend(permitted.reason_codes)
    if permitted.is_empty:
        return UnitPlan(
            unit_id=unit.unit_id,
            speculation_class=speculation_class,
            page_plan=None,
            reason_codes=tuple(reasons),
            unresolved=(f"data_policy_removed_every_route:{unit.unit_id}",),
        )

    floor = _effective_floor(policy, request)
    if floor != request.trust_floor:
        reasons.append("independent_verification_floor")
    # The primary is chosen from the §21 row's *primary* lanes only. A peer lane
    # is a second opinion, not a cheaper way to do the job: letting a peer win
    # the primary slot would quietly replace the row's policy with the cost
    # model's preference.
    primary_permitted = tuple(
        route for route in permitted.permitted_routes if route in set(primary_routes)
    )
    eligible = _eligible_candidates(primary_permitted, unit, request, policy, floor)
    if not eligible:
        return UnitPlan(
            unit_id=unit.unit_id,
            speculation_class=speculation_class,
            page_plan=None,
            reason_codes=(*reasons, "trust_floor_unreachable"),
            unresolved=(f"trust_floor_unreachable:{unit.unit_id}",),
        )

    chosen = select_expected_verified_cost(
        tuple(candidate for candidate, _ in eligible),
        maximum_critical_failure_probability=floor,
    )
    if chosen is None:
        return UnitPlan(
            unit_id=unit.unit_id,
            speculation_class=speculation_class,
            page_plan=None,
            reason_codes=(*reasons, "trust_floor_unreachable"),
            unresolved=(f"trust_floor_unreachable:{unit.unit_id}",),
        )
    primary = Route(chosen.route_id)
    primary_risk = next(risk for candidate, risk in eligible if candidate is chosen)

    speculative, spec_reasons = _speculative_routes(
        primary=primary,
        primary_risk=primary_risk,
        peer_routes=tuple(route for route in peer_routes if route in permitted.permitted_routes),
        unit=unit,
        request=request,
        policy=policy,
        allowed=speculate_allowed,
    )
    reasons.extend(spec_reasons)

    verification = policy.verification
    if not primary_risk.bounded and verification is VerificationPolicy.NONE:
        # An unmeasured sensitive feature is not permission to skip a check.
        verification = (
            VerificationPolicy.PEER_AGREEMENT
            if speculative
            else (VerificationPolicy.INDEPENDENT_VERIFIER)
        )
        reasons.append("verification_raised_for_unmeasured_risk")

    total_cost = chosen.expected_verified_cost + sum(
        request.cost_model.cost(route).inference for route in speculative
    )
    page_plan = PageExecutionPlan(
        page_id=unit.unit_id,
        technical_class=unit.technical_class,
        risk_vector=unit.risk_vector,
        authority_sources=(unit.authority_domain,) if unit.authority_domain else (),
        candidate_routes=permitted.permitted_routes,
        primary_route=primary,
        speculative_routes=speculative,
        verification_policy=verification,
        escalation_policy=_escalation_policy(policy, primary_risk),
        batch_group=f"{primary.value}:{unit.technical_class.value}",
        priority=_priority(request.deadline_class, unit),
        dependencies=tuple(
            edge for edge in request.dependency_edges if edge.to_unit_id == unit.unit_id
        ),
    )
    return UnitPlan(
        unit_id=unit.unit_id,
        speculation_class=speculation_class,
        page_plan=page_plan,
        region_plans=_region_plans(unit, primary, speculative, verification, request),
        primary_lane=_lane_of(primary, request.portfolio),
        speculative_lanes=tuple(
            lane
            for lane in (_lane_of(route, request.portfolio) for route in speculative)
            if lane is not None
        ),
        expected_verified_cost=total_cost,
        reason_codes=tuple(reasons),
    )


def _effective_floor(policy: SpeculationPolicy, request: PlannerRequest) -> float:
    """The floor for this unit. Only an independent check can relax it.

    Peer agreement does not: two models agreeing is not truth. A human reviewer
    or an authority match is an independent check, and only then -- and only
    when the caller stated a `verified_trust_floor` -- does the bar move.
    """
    independent = policy.verification in {
        VerificationPolicy.HUMAN_REVIEW,
        VerificationPolicy.AUTHORITY_MATCH,
        VerificationPolicy.INDEPENDENT_VERIFIER,
    }
    if independent and request.verified_trust_floor is not None:
        return max(request.trust_floor, request.verified_trust_floor)
    return request.trust_floor


def _eligible_candidates(
    routes: Sequence[Route],
    unit: UnitFeatures,
    request: PlannerRequest,
    policy: SpeculationPolicy,
    floor: float,
) -> tuple[tuple[RouteCostCandidate, RouteRisk], ...]:
    """Price the permitted routes, dropping the ones that cannot clear the floor.

    A route with an unmeasured sensitive feature survives only when the §21 row
    puts a verifier behind it; otherwise its bound is not evidence of anything.
    """
    verified = policy.verification is not VerificationPolicy.NONE or bool(policy.peer_lanes)
    priced: list[tuple[RouteCostCandidate, RouteRisk]] = []
    for route in routes:
        if route in TERMINAL_ROUTES or route not in request.ready_routes:
            continue
        risk = route_risk(route, unit.risk_vector)
        if not risk.bounded and not verified:
            continue
        if risk.lower_bound > floor:
            continue
        cost = request.cost_model.cost(route)
        cold = 0.0 if route in request.capacity.warm_routes else cost.cold_start_seconds
        priced.append(
            (
                RouteCostCandidate(
                    route_id=route.value,
                    inference_cost=cost.inference
                    + cold * 0.01
                    + request.capacity.queue_seconds * 0.001,
                    verification_cost=cost.verification,
                    recovery_probability=risk.lower_bound,
                    recovery_cost=cost.recovery or cost.inference,
                    critical_failure_probability=risk.lower_bound,
                    critical_failure_penalty=request.cost_model.critical_failure_penalty,
                ),
                risk,
            )
        )
    return tuple(priced)


def _speculative_routes(
    *,
    primary: Route,
    primary_risk: RouteRisk,
    peer_routes: Sequence[Route],
    unit: UnitFeatures,
    request: PlannerRequest,
    policy: SpeculationPolicy,
    allowed: bool,
) -> tuple[tuple[Route, ...], list[str]]:
    """§9: a peer runs only when predicted risk x expected value pays for it.

    With one exception. When the §21 row's verification is `AUTHORITY_MATCH` or
    `HUMAN_REVIEW`, the peer *is* the verification mechanism, not an
    optimisation, and dropping it would silently break the verification
    contract. Those peers are mandatory. A `PEER_AGREEMENT` row's peer can
    instead be reached by escalation, so pre-launching it is the optional spend
    that §9 governs.
    """
    reasons: list[str] = []
    if not policy.parallel_peers or not peer_routes:
        return (), reasons
    mandatory = policy.verification in {
        VerificationPolicy.AUTHORITY_MATCH,
        VerificationPolicy.HUMAN_REVIEW,
    }
    if not allowed and not mandatory:
        return (), reasons
    model = request.cost_model
    selected: list[Route] = []
    for route in peer_routes:
        if route == primary or route not in request.ready_routes:
            continue
        peer = route_risk(route, unit.risk_vector)
        peer_cost = model.cost(route).inference
        if mandatory:
            selected.append(route)
            reasons.append(f"peer_required_by_verification_contract:{route.value}")
            continue
        if not primary_risk.bounded:
            selected.append(route)
            reasons.append(f"speculative_for_unmeasured_risk:{route.value}")
            continue
        joint = primary_risk.lower_bound * max(
            peer.lower_bound, model.assumed_peer_joint_failure_ratio
        )
        expected_value = (primary_risk.lower_bound - joint) * model.critical_failure_penalty
        if expected_value > peer_cost:
            selected.append(route)
            reasons.append(f"speculative_expected_value:{route.value}")
        else:
            reasons.append(f"speculation_not_worth_cost:{route.value}")
    limit = request.capacity.max_speculative_units
    if limit is not None and len(selected) > limit:
        reasons.append("speculation_capped_by_capacity")
        selected = selected[:limit]
    return tuple(selected), reasons


def _routes_for_lanes(
    lanes: Sequence[ExecutionLane], request: PlannerRequest
) -> tuple[tuple[Route, ...], tuple[ExecutionLane, ...]]:
    routes: list[Route] = []
    dropped: list[ExecutionLane] = []
    for lane in lanes:
        try:
            route = request.portfolio.route_for(lane)
        except UnboundLaneError:
            dropped.append(lane)
            continue
        if route in request.ready_routes and route not in TERMINAL_ROUTES:
            routes.append(route)
        else:
            dropped.append(lane)
    return tuple(routes), tuple(dropped)


def _lane_of(route: Route, portfolio: Portfolio) -> ExecutionLane | None:
    for binding in portfolio.bindings:
        if binding.route == route:
            return binding.lane
    return None


def _escalation_policy(policy: SpeculationPolicy, risk: RouteRisk) -> EscalationPolicy:
    if policy.verification is VerificationPolicy.AUTHORITY_MATCH:
        return EscalationPolicy.AUTHORITY_LANE
    if policy.verification is VerificationPolicy.HUMAN_REVIEW:
        return EscalationPolicy.FAIL_CLOSED
    if not risk.bounded:
        return EscalationPolicy.PEER_ESCALATION
    if risk.lower_bound >= 0.5:
        return EscalationPolicy.REGION_RECOVERY
    return EscalationPolicy.BOUNDED_RETRY


def _priority(deadline: DeadlineClass, unit: UnitFeatures) -> int:
    base = {DeadlineClass.INTERACTIVE: 800, DeadlineClass.STANDARD: 500, DeadlineClass.BATCH: 200}[
        deadline
    ]
    return min(1000, base + (100 if unit.authority_domain else 0))


def _region_plans(
    unit: UnitFeatures,
    primary: Route,
    speculative: Sequence[Route],
    verification: VerificationPolicy,
    request: PlannerRequest,
) -> tuple[RegionExecutionPlan, ...]:
    """Region plans only for regions the caller located. No bbox is invented."""
    plans: list[RegionExecutionPlan] = []
    for region in unit.regions:
        region_primary = primary
        peer = next((route for route in speculative if route != region_primary), None)
        plans.append(
            RegionExecutionPlan(
                region_id=region.region_id,
                source_locator=region.source_locator,
                type=region.region_type,
                risk_vector=region.risk_vector,
                crop_geometry=region.crop_geometry,
                scale_dpi=region.scale_dpi,
                primary=region_primary,
                peer=peer,
                specialist=None,
                verification_contract=verification,
            )
        )
    return tuple(plans)


# --- waves, schedule, identity ----------------------------------------------


def _build_waves(
    unit_plans: Sequence[UnitPlan], request: PlannerRequest
) -> tuple[tuple[ExecutionWave, ...], tuple[DependencyEdge, ...]]:
    """Layer units over the dependency DAG, then split each layer by lane."""
    planned = {item.unit_id: item for item in unit_plans if item.page_plan is not None}
    edges = tuple(
        edge
        for edge in request.dependency_edges
        if edge.from_unit_id in planned and edge.to_unit_id in planned
    )
    depth = _dependency_depth(planned, edges)
    grouped: dict[tuple[int, ExecutionLane], list[str]] = {}
    for unit_id, item in planned.items():
        lane = item.primary_lane or ExecutionLane.FAST_VISUAL
        grouped.setdefault((depth[unit_id], lane), []).append(unit_id)
    waves = tuple(
        ExecutionWave(
            wave_index=index,
            lane=lane,
            unit_ids=tuple(sorted(unit_ids)),
            batch_group=_batch_group(planned, unit_ids),
        )
        for (index, lane), unit_ids in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1].value)
        )
    )
    return waves, edges


def _dependency_depth(
    planned: Mapping[str, UnitPlan], edges: Sequence[DependencyEdge]
) -> dict[str, int]:
    """Longest-path layering. A cycle stops growing rather than hanging."""
    depth = dict.fromkeys(planned, 0)
    for _ in range(len(planned)):
        changed = False
        for edge in edges:
            if not edge.blocking:
                continue
            candidate = depth[edge.from_unit_id] + 1
            if candidate > depth[edge.to_unit_id]:
                depth[edge.to_unit_id] = candidate
                changed = True
        if not changed:
            break
    return depth


def _batch_group(planned: Mapping[str, UnitPlan], unit_ids: Sequence[str]) -> str | None:
    """One batch group only when every unit in the wave shares it."""
    groups = {
        page.batch_group
        for page in (planned[unit_id].page_plan for unit_id in unit_ids)
        if page is not None
    }
    return groups.pop() if len(groups) == 1 else None


def _estimate_latency(
    unit_plans: Sequence[UnitPlan], request: PlannerRequest
) -> tuple[float, float]:
    credits: list[float] = []
    cold_probability = 0.0
    cold_seconds = 0.0
    for item in unit_plans:
        if item.page_plan is None:
            continue
        for route in (item.page_plan.primary_route, *item.page_plan.speculative_routes):
            cost = request.cost_model.cost(route)
            credits.append(max(0.001, cost.seconds_per_unit))
            if route not in request.capacity.warm_routes and cost.cold_start_seconds > 0:
                cold_probability = 1.0
                cold_seconds = max(cold_seconds, cost.cold_start_seconds)
    if not credits:
        return 0.0, 0.0
    estimate = estimate_schedule(
        ScheduleScenario(
            page_credits=tuple(credits),
            parallelism=max(
                1, min(request.capacity.parallelism_budget, request.capacity.gpu_capacity)
            ),
            seconds_per_credit_mean=1.0,
            seconds_per_credit_stddev=0.25,
            cold_start_probability=cold_probability,
            cold_start_seconds=cold_seconds,
        ),
        simulations=2_000,
        seed=0,
    )
    queue_ms = request.capacity.queue_seconds * 1000.0
    return estimate.p50_seconds * 1000.0 + queue_ms, estimate.p95_seconds * 1000.0 + queue_ms


def _plan_id(request: PlannerRequest) -> str:
    payload = json.dumps(
        {
            "source_version_id": request.source_version_id,
            "planner_revision": PLANNER_REVISION,
            "portfolio_revision": request.portfolio.revision,
            "units": [unit.unit_id for unit in request.units],
            "mode": request.mode.value,
            "deadline": request.deadline_class.value,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "plan_" + hashlib.sha256(payload).hexdigest()[:24]


def _observed(risk: RiskVector, feature: RiskFeature) -> float:
    """Observed value, or 0.0 when unknown -- and unknown never selects a class."""
    if risk.is_unknown(feature):
        return 0.0
    signal = risk.signals.get(feature)
    return 0.0 if signal is None or signal.value is None else signal.value


def replay_record(result: PlannerResult, unit_plan: UnitPlan) -> RouterReplayRecord:
    """Appendix D record for one planned unit. Hidden truth cannot enter it."""
    page = unit_plan.page_plan
    disposition = "accepted" if page is not None else "unresolved"
    return RouterReplayRecord(
        unit_id=unit_plan.unit_id,
        features_revision=result.plan.feature_manifest_sha256 if result.plan else "unplanned",
        router_revision=PLANNER_REVISION,
        allowed_routes=page.candidate_routes if page is not None else (),
        selected_plan=page.primary_route.value if page is not None else "none",
        speculative_plans=tuple(route.value for route in page.speculative_routes)
        if page is not None
        else (),
        escalations=unit_plan.reason_codes,
        verification=page.verification_policy if page is not None else VerificationPolicy.NONE,
        final_disposition=disposition,
    )


def build_replay_policy(strong: str, primary: str = "") -> object:
    """Entry point the WP-R10 replay harness looks for on this module.

    Imported lazily so `akc_router.planner` never pulls the adapter (and its
    duck-typed research-tree shim) into a normal runtime import.
    """
    from .replay_adapter import build_replay_policy as _build

    return _build(strong=strong, primary=primary)


__all__ = [
    "DEFAULT_COST_MODEL",
    "PLANNER_REVISION",
    "ROUTE_SENSITIVITY",
    "CapacityState",
    "CostModel",
    "PlannerRequest",
    "PlannerResult",
    "RegionFeatures",
    "RouteCost",
    "RouteRisk",
    "UnitFeatures",
    "UnitPlan",
    "UnknownRouteCostError",
    "build_replay_policy",
    "classify_speculation",
    "plan_document",
    "replay_record",
    "route_risk",
]
