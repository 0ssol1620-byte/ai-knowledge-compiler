"""Hierarchical adaptive routing with health-aware deterministic selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from .models import WorkerSnapshot, WorkerState


class RouteTier(StrEnum):
    NATIVE = "native"
    FAST = "fast"
    PRECISION = "precision"
    SPECIALIST = "specialist"
    AUTHORITY = "authority"


class RouterStage(StrEnum):
    DOCUMENT = "document"
    PAGE = "page"
    REGION = "region"
    RECOVERY = "recovery"


class CascadeStage(StrEnum):
    NATIVE = "native"
    FAST = "fast"
    PRECISION = "precision"
    SPECIALIST = "specialist"
    AUTHORITY = "authority"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class RecipeProfile:
    recipe_id: str
    model_revision: str
    runtime_image_digest: str
    tier: RouteTier
    capabilities: frozenset[str]
    supported_languages: frozenset[str]
    external_provider: bool = False
    authority_capable: bool = False
    independent_family: str = ""

    def __post_init__(self) -> None:
        if not self.recipe_id or not self.model_revision or not self.runtime_image_digest:
            raise ValueError("recipe identity fields are required")
        if not self.independent_family:
            raise ValueError("independent_family is required for differential routing")


@dataclass(frozen=True, slots=True)
class QualityEstimate:
    pass_hard_gate: float
    numeric_exact: float
    row_complete: float
    repetition_probability: float
    timeout_probability: float
    oom_probability: float
    expected_latency_seconds: float
    expected_cost: float

    def __post_init__(self) -> None:
        probabilities = (
            self.pass_hard_gate,
            self.numeric_exact,
            self.row_complete,
            self.repetition_probability,
            self.timeout_probability,
            self.oom_probability,
        )
        if any(not 0 <= value <= 1 for value in probabilities):
            raise ValueError("quality probabilities must be between 0 and 1")
        if self.expected_latency_seconds < 0 or self.expected_cost < 0:
            raise ValueError("latency and cost estimates cannot be negative")


@dataclass(frozen=True, slots=True)
class RouteRequest:
    stage: RouterStage
    required_capabilities: frozenset[str]
    language: str
    high_risk: bool
    private_processing: bool
    external_api_allowed: bool
    financial_numeric: bool = False
    long_complex_table: bool = False
    photographed_low_quality: bool = False
    benchmark_critical: bool = False
    production_canary: bool = False
    prior_template_failure: bool = False

    def __post_init__(self) -> None:
        if not self.language:
            raise ValueError("route language is required")
        if self.private_processing and self.external_api_allowed:
            raise ValueError("private processing cannot allow external APIs")


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    recipe: RecipeProfile
    worker: WorkerSnapshot
    estimate: QualityEstimate
    objective_score: float


@dataclass(frozen=True, slots=True)
class RouteDecision:
    primary: RouteCandidate
    secondary: RouteCandidate | None
    speculative: bool
    reason_codes: tuple[str, ...]
    policy_version: str


class RoutingUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CascadeDecision:
    stage: CascadeStage
    terminal: bool
    ready_for_arbitration: bool
    reason_code: str


class CascadeController:
    _ORDER: ClassVar[tuple[CascadeStage, ...]] = (
        CascadeStage.NATIVE,
        CascadeStage.FAST,
        CascadeStage.PRECISION,
        CascadeStage.SPECIALIST,
        CascadeStage.AUTHORITY,
    )

    def advance(
        self,
        *,
        current: CascadeStage,
        hard_gates_passed: bool,
        authority_required: bool,
        authority_exact: bool,
        available_stages: frozenset[CascadeStage],
    ) -> CascadeDecision:
        if current is CascadeStage.UNRESOLVED:
            return CascadeDecision(current, True, False, "already_unresolved")
        if hard_gates_passed and (not authority_required or authority_exact):
            return CascadeDecision(current, True, True, "candidate_ready_for_arbitration")
        if hard_gates_passed and authority_required and not authority_exact:
            if CascadeStage.AUTHORITY in available_stages:
                return CascadeDecision(
                    CascadeStage.AUTHORITY,
                    False,
                    False,
                    "authority_verification_required",
                )
            return CascadeDecision(
                CascadeStage.UNRESOLVED,
                True,
                False,
                "authority_unavailable",
            )
        current_index = self._ORDER.index(current)
        next_stage = next(
            (
                stage
                for stage in self._ORDER[current_index + 1 :]
                if stage in available_stages
            ),
            None,
        )
        if next_stage is None:
            return CascadeDecision(
                CascadeStage.UNRESOLVED,
                True,
                False,
                "cascade_exhausted",
            )
        return CascadeDecision(next_stage, False, False, "hard_gate_escalation")


@dataclass(frozen=True, slots=True)
class RouterPromotionEvidence:
    shadow_sample_count: int
    candidate_critical_failures: int
    baseline_verified_quality: float
    candidate_verified_quality: float
    baseline_cost: float
    candidate_cost: float
    baseline_latency: float
    candidate_latency: float
    canary_percent: int
    low_risk_only: bool
    rollback_ready: bool

    def __post_init__(self) -> None:
        if self.shadow_sample_count < 0 or self.candidate_critical_failures < 0:
            raise ValueError("router promotion counts cannot be negative")
        if any(
            not 0 <= value <= 1
            for value in (self.baseline_verified_quality, self.candidate_verified_quality)
        ):
            raise ValueError("router quality values must be between zero and one")
        if any(
            value < 0
            for value in (
                self.baseline_cost,
                self.candidate_cost,
                self.baseline_latency,
                self.candidate_latency,
            )
        ):
            raise ValueError("router cost and latency cannot be negative")
        if self.canary_percent not in {1, 5, 20}:
            raise ValueError("router canary must follow the 1, 5, or 20 percent ladder")


@dataclass(frozen=True, slots=True)
class RouterPromotionDecision:
    promote: bool
    reason_codes: tuple[str, ...]


def evaluate_router_promotion(
    evidence: RouterPromotionEvidence, *, minimum_shadow_samples: int = 100
) -> RouterPromotionDecision:
    if minimum_shadow_samples < 1:
        raise ValueError("minimum shadow sample count must be positive")
    reasons: list[str] = []
    if evidence.shadow_sample_count < minimum_shadow_samples:
        reasons.append("shadow_sample_insufficient")
    if evidence.candidate_critical_failures:
        reasons.append("candidate_critical_failure")
    if evidence.candidate_verified_quality < evidence.baseline_verified_quality:
        reasons.append("verified_quality_regression")
    if not (
        evidence.candidate_cost < evidence.baseline_cost
        or evidence.candidate_latency < evidence.baseline_latency
    ):
        reasons.append("cost_and_latency_not_improved")
    if not evidence.low_risk_only:
        reasons.append("canary_scope_not_low_risk")
    if not evidence.rollback_ready:
        reasons.append("rollback_not_ready")
    return RouterPromotionDecision(
        promote=not reasons,
        reason_codes=tuple(sorted(reasons)),
    )


class AdaptiveRouter:
    """Bootstrap router whose objective can later consume calibrated estimates."""

    _TIER_ORDER: ClassVar[dict[RouteTier, int]] = {
        RouteTier.NATIVE: 0,
        RouteTier.FAST: 1,
        RouteTier.PRECISION: 2,
        RouteTier.SPECIALIST: 3,
        RouteTier.AUTHORITY: 4,
    }

    def __init__(self, *, policy_version: str = "adaptive-router-v2-bootstrap") -> None:
        self.policy_version = policy_version

    @staticmethod
    def _compatible(
        request: RouteRequest, recipe: RecipeProfile, worker: WorkerSnapshot
    ) -> bool:
        if worker.state not in {WorkerState.HEALTHY, WorkerState.DEGRADED}:
            return False
        if worker.model_revision != recipe.model_revision:
            return False
        if worker.runtime_image_digest != recipe.runtime_image_digest:
            return False
        if not request.required_capabilities.issubset(recipe.capabilities):
            return False
        if not recipe.capabilities.issubset(worker.capabilities):
            return False
        if (
            request.language not in recipe.supported_languages
            and "multilingual" not in recipe.supported_languages
        ):
            return False
        return not (
            recipe.external_provider
            and (request.private_processing or not request.external_api_allowed)
        )

    @staticmethod
    def _objective(
        request: RouteRequest, estimate: QualityEstimate, worker: WorkerSnapshot
    ) -> float:
        quality_weight = 7.0 if request.high_risk else 4.0
        numeric_weight = 4.0 if request.financial_numeric else 1.5
        row_weight = 2.5 if request.long_complex_table else 1.0
        cost_weight = 0.15 if request.high_risk else 0.6
        latency_weight = 0.002 if request.high_risk else 0.008
        failure_risk = (
            1 - estimate.pass_hard_gate
            + estimate.repetition_probability
            + estimate.timeout_probability
            + estimate.oom_probability
        )
        reliability = worker.semantic_score / 100
        score = (
            quality_weight * estimate.pass_hard_gate
            + numeric_weight * estimate.numeric_exact
            + row_weight * estimate.row_complete
            + reliability
            - cost_weight * estimate.expected_cost
            - latency_weight * estimate.expected_latency_seconds
            - 2.0 * failure_risk
        )
        if worker.warm:
            score += 0.1
        return round(score, 12)

    @staticmethod
    def _speculation_reasons(
        request: RouteRequest, ordered: tuple[RouteCandidate, ...]
    ) -> tuple[str, ...]:
        reasons: set[str] = set()
        if request.financial_numeric:
            reasons.add("financial_numeric")
        if request.long_complex_table:
            reasons.add("long_complex_table")
        if request.photographed_low_quality:
            reasons.add("photographed_low_quality")
        if request.prior_template_failure:
            reasons.add("prior_template_failure")
        if request.benchmark_critical:
            reasons.add("benchmark_critical")
        if request.production_canary:
            reasons.add("production_canary")
        if ordered and 0.35 <= ordered[0].estimate.pass_hard_gate <= 0.75:
            reasons.add("quality_estimator_uncertain")
        if (
            len(ordered) > 1
            and abs(ordered[0].objective_score - ordered[1].objective_score) <= 0.25
        ):
            reasons.add("candidate_win_rates_close")
        return tuple(sorted(reasons))

    def route(
        self,
        request: RouteRequest,
        *,
        recipes: tuple[RecipeProfile, ...],
        workers: tuple[WorkerSnapshot, ...],
        estimates: dict[tuple[str, str], QualityEstimate],
    ) -> RouteDecision:
        candidates: list[RouteCandidate] = []
        for recipe in recipes:
            for worker in workers:
                if not self._compatible(request, recipe, worker):
                    continue
                estimate = estimates.get((recipe.recipe_id, worker.worker_id))
                if estimate is None:
                    continue
                candidates.append(
                    RouteCandidate(
                        recipe=recipe,
                        worker=worker,
                        estimate=estimate,
                        objective_score=self._objective(request, estimate, worker),
                    )
                )
        if not candidates:
            raise RoutingUnavailable("no compatible healthy worker with a quality estimate")
        ordered = tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.objective_score,
                    self._TIER_ORDER[candidate.recipe.tier],
                    candidate.recipe.recipe_id,
                    candidate.worker.worker_id,
                ),
            )
        )
        reasons = self._speculation_reasons(request, ordered)
        secondary = next(
            (
                candidate
                for candidate in ordered[1:]
                if candidate.recipe.independent_family != ordered[0].recipe.independent_family
                and candidate.worker.worker_id != ordered[0].worker.worker_id
            ),
            None,
        )
        speculative = bool(reasons and secondary is not None)
        return RouteDecision(
            primary=ordered[0],
            secondary=secondary if speculative else None,
            speculative=speculative,
            reason_codes=reasons if speculative else (),
            policy_version=self.policy_version,
        )


__all__ = [
    "AdaptiveRouter",
    "CascadeController",
    "CascadeDecision",
    "CascadeStage",
    "QualityEstimate",
    "RecipeProfile",
    "RouteCandidate",
    "RouteDecision",
    "RouteRequest",
    "RouteTier",
    "RouterPromotionDecision",
    "RouterPromotionEvidence",
    "RouterStage",
    "RoutingUnavailable",
    "evaluate_router_promotion",
]
