"""Routing policy contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from akc_cir import ContractModel
from pydantic import Field, model_validator

from .preflight import RiskTier


class ProcessingMode(StrEnum):
    SPEED = "speed"
    BALANCED = "balanced"
    PRECISION = "precision"
    PRIVATE = "private"
    LONG_FORM_BETA = "long_form_beta"


class RouteProfile(StrEnum):
    FAST = "parse_fast_v1"
    BALANCED = "parse_balanced_v1"
    PRECISION = "parse_precision_v1"
    LONG = "parse_long_v1"
    PRIVATE = "parse_private_v1"


MODE_PROFILE: dict[ProcessingMode, RouteProfile] = {
    ProcessingMode.SPEED: RouteProfile.FAST,
    ProcessingMode.BALANCED: RouteProfile.BALANCED,
    ProcessingMode.PRECISION: RouteProfile.PRECISION,
    ProcessingMode.PRIVATE: RouteProfile.PRIVATE,
    ProcessingMode.LONG_FORM_BETA: RouteProfile.LONG,
}


class Route(StrEnum):
    NATIVE = "native"
    PADDLE_VL = "paddle_vl"
    PADDLE_FAST = "paddle_fast"
    HPD_FAST = "hpd_fast"
    # Added 2026-09-23 so the router can name the second readers the
    # complementarity study measured. Neither is servable until a model_registry
    # row carries its revision and image digest; until then `ready_routes` never
    # contains them and every decision that would pick one falls closed.
    OVIS_VL = "ovis_vl"
    INFINITY_FLASH = "infinity_flash"
    UNLIMITED_LONG = "unlimited_long"
    MISTRAL_FALLBACK = "mistral_fallback"
    REGION_RECOVERY = "region_recovery"
    AUTHORITY_RECONSTRUCTION = "authority_reconstruction"
    UNRESOLVED = "unresolved"
    QUARANTINE = "quarantine"


class FeatureFlags(ContractModel):
    hpd_enabled: bool = False
    paddle_fast_enabled: bool = False
    ovis_vl_enabled: bool = False
    infinity_flash_enabled: bool = False
    unlimited_long_enabled: bool = False
    external_fallback_enabled: bool = False
    region_recovery_enabled: bool = False
    authority_verification_enabled: bool = False
    differential_verification_enabled: bool = False


class DataPolicy(ContractModel):
    external_api_allowed: bool = False
    retention_days: Annotated[int, Field(ge=0)] = 30
    regional_restriction: str | None = None
    private_processing: bool = False


class RouterContext(ContractModel):
    mode: ProcessingMode = ProcessingMode.BALANCED
    dominant_language: str | None = None
    risk_tier: RiskTier = RiskTier.NORMAL
    feature_flags: FeatureFlags = FeatureFlags()
    data_policy: DataPolicy = DataPolicy()
    ready_routes: frozenset[Route] = frozenset({Route.NATIVE})
    policy_version: str = "router-1.0.0"

    @model_validator(mode="after")
    def enforce_private_mode(self) -> RouterContext:
        if self.mode == ProcessingMode.PRIVATE and self.data_policy.external_api_allowed:
            raise ValueError("private mode cannot allow external model APIs")
        if self.data_policy.private_processing and self.data_policy.external_api_allowed:
            raise ValueError("private processing cannot allow external model APIs")
        terminal_routes = {Route.UNRESOLVED, Route.QUARANTINE}
        if self.ready_routes.intersection(terminal_routes):
            raise ValueError("terminal isolation states are not provider routes")
        if self.mode == ProcessingMode.PRIVATE and Route.MISTRAL_FALLBACK in self.ready_routes:
            raise ValueError("private mode cannot mark an external provider ready")
        return self


class RouteDecision(ContractModel):
    route: Route
    route_profile: RouteProfile
    reason_codes: tuple[str, ...]
    expected_credits: Annotated[float, Field(ge=0.0)]
    requires_visual_parse: bool
    require_cross_check: bool
    max_attempts: Annotated[int, Field(ge=1, le=5)]
    policy_version: str
    provider_options: dict[str, Any] = Field(default_factory=dict)
    # `require_cross_check` said a second read was wanted and never said by whom,
    # which left the choice to whatever the caller happened to have. These two
    # name it from the complementarity measurement, and default to None so a
    # decision built before this field existed still validates. None while
    # `require_cross_check` is true means no measured peer is servable: that is a
    # second read the router cannot justify, and it is not run.
    cross_check_route: Route | None = None
    cross_check_element: str | None = None

    @model_validator(mode="after")
    def enforce_cross_check_pair(self) -> RouteDecision:
        if self.cross_check_route is None and self.cross_check_element is not None:
            raise ValueError("a cross-check element without a route names no second reader")
        if self.cross_check_route is not None and self.cross_check_element is None:
            raise ValueError("a cross-check route must say which element chose it")
        if self.cross_check_route == self.route:
            raise ValueError("a route cannot cross-check itself")
        if self.cross_check_route is not None and not self.require_cross_check:
            raise ValueError("a cross-check route requires require_cross_check")
        return self


class EscalationAction(StrEnum):
    ACCEPT = "accept"
    RETRY = "retry"
    ESCALATE = "escalate"
    VERIFY_AUTHORITY = "verify_authority"
    UNRESOLVED = "unresolved"
    QUARANTINE = "quarantine"
    FAIL = "fail"
    DISCARD_CHALLENGER = "discard_challenger"


class QualitySignal(ContractModel):
    score: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    passed: bool = False
    empty_output: bool = False
    repetition_failure: bool = False
    provider_failure: bool = False
    unreadable: bool = False
    critical_numeric_mismatch: bool = False
    critical_table_error: bool = False
    engine_specific_failure: bool = False
    security_quarantine_required: bool = False
    source_integrity_failure: bool = False
    unsupported_content: bool = False
    region_recoverable: bool = False
    authority_match: bool | None = None
    independent_signal_agreement: bool | None = None
    source_evidence_complete: bool = True
    agreement_text: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    agreement_numeric: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    base_result_passed: bool = False

    @model_validator(mode="after")
    def enforce_pass_score_invariant(self) -> QualitySignal:
        if self.passed and (self.score is None or self.score < 0.82):
            raise ValueError("passed quality signal requires score >= 0.82")
        return self


class EscalationDecision(ContractModel):
    action: EscalationAction
    route: Route | None = None
    reason_codes: tuple[str, ...]
    attempt_number: Annotated[int, Field(ge=1)]
    policy_version: str


class RoutingAudit(ContractModel):
    router_policy: str
    feature_flags: FeatureFlags
    route_profile: RouteProfile
    decision: Route
    reason_codes: tuple[str, ...]
    metrics_snapshot: dict[str, Any]
    estimated_credits: Annotated[float, Field(ge=0.0)]
