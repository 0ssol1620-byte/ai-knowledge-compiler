"""Deterministic first-route and escalation policy."""

from __future__ import annotations

from .models import (
    MODE_PROFILE,
    EscalationAction,
    EscalationDecision,
    ProcessingMode,
    QualitySignal,
    Route,
    RouteDecision,
    RouterContext,
)
from .preflight import (
    PageMetrics,
    RiskTier,
    native_candidate,
    native_requires_visual_cross_check,
    preflight_difficulty,
)

_OCR_ROUTES = frozenset(
    {
        Route.PADDLE_VL,
        Route.PADDLE_FAST,
        Route.HPD_FAST,
        Route.UNLIMITED_LONG,
        Route.MISTRAL_FALLBACK,
        Route.REGION_RECOVERY,
    }
)


def _unresolved_for_unavailable(
    *,
    context: RouterContext,
    attempted_route: Route,
    reason_codes: tuple[str, ...],
) -> RouteDecision:
    return RouteDecision(
        route=Route.UNRESOLVED,
        route_profile=MODE_PROFILE[context.mode],
        reason_codes=(
            *reason_codes,
            f"route_unavailable:{attempted_route.value}",
            "fail_closed_unresolved",
        ),
        expected_credits=0.0,
        requires_visual_parse=False,
        require_cross_check=True,
        max_attempts=1,
        policy_version=context.policy_version,
    )


def _require_ready_route(
    decision: RouteDecision,
    *,
    context: RouterContext,
) -> RouteDecision:
    if decision.route in {Route.UNRESOLVED, Route.QUARANTINE}:
        return decision
    if decision.route in context.ready_routes:
        return decision
    return _unresolved_for_unavailable(
        context=context,
        attempted_route=decision.route,
        reason_codes=decision.reason_codes,
    )


def estimate_route_credits(
    route: Route,
    *,
    context: RouterContext,
    page: PageMetrics,
) -> float:
    """Apply the later-priority v2 credit schedule deterministically."""
    if route in {Route.UNRESOLVED, Route.QUARANTINE, Route.AUTHORITY_RECONSTRUCTION}:
        return 0.0
    credits = 0.25 if route == Route.NATIVE else 1.0 if route in _OCR_ROUTES else 0.0
    complex_page = preflight_difficulty(page) >= 50 or native_requires_visual_cross_check(page)
    if complex_page:
        credits += 0.5
    if context.mode == ProcessingMode.PRECISION:
        credits += 1.0
    return credits


def select_first_route(context: RouterContext, page: PageMetrics) -> RouteDecision:
    profile = MODE_PROFILE[context.mode]
    high_risk = context.risk_tier == RiskTier.HIGH
    if native_candidate(page):
        return _require_ready_route(
            RouteDecision(
                route=Route.NATIVE,
                route_profile=profile,
                reason_codes=("native_text_quality_pass",),
                expected_credits=estimate_route_credits(
                    Route.NATIVE,
                    context=context,
                    page=page,
                ),
                requires_visual_parse=native_requires_visual_cross_check(page),
                require_cross_check=high_risk or native_requires_visual_cross_check(page),
                max_attempts=2,
                policy_version=context.policy_version,
            ),
            context=context,
        )

    language = (context.dominant_language or "").casefold()
    if (
        context.feature_flags.hpd_enabled
        and context.mode == ProcessingMode.SPEED
        and language in {"en", "zh", "zh-cn", "zh-tw"}
        and preflight_difficulty(page) < 65
        and page.handwriting_probability < 0.2
    ):
        return _require_ready_route(
            RouteDecision(
                route=Route.HPD_FAST,
                route_profile=profile,
                reason_codes=("speed_mode", "supported_language", "hpd_eligible"),
                expected_credits=estimate_route_credits(
                    Route.HPD_FAST,
                    context=context,
                    page=page,
                ),
                requires_visual_parse=True,
                require_cross_check=high_risk,
                max_attempts=2,
                policy_version=context.policy_version,
            ),
            context=context,
        )

    if context.feature_flags.paddle_fast_enabled and context.mode == ProcessingMode.SPEED:
        return _require_ready_route(
            RouteDecision(
                route=Route.PADDLE_FAST,
                route_profile=profile,
                reason_codes=("speed_mode", "paddle_fast_enabled"),
                expected_credits=estimate_route_credits(
                    Route.PADDLE_FAST,
                    context=context,
                    page=page,
                ),
                requires_visual_parse=True,
                require_cross_check=high_risk,
                max_attempts=2,
                policy_version=context.policy_version,
            ),
            context=context,
        )

    return _require_ready_route(
        RouteDecision(
            route=Route.PADDLE_VL,
            route_profile=profile,
            reason_codes=("visual_parse_required",),
            expected_credits=estimate_route_credits(
                Route.PADDLE_VL,
                context=context,
                page=page,
            ),
            requires_visual_parse=True,
            require_cross_check=high_risk or context.mode == ProcessingMode.PRECISION,
            max_attempts=3,
            policy_version=context.policy_version,
        ),
        context=context,
    )


def _external_fallback_allowed(context: RouterContext) -> bool:
    return (
        context.feature_flags.external_fallback_enabled
        and context.data_policy.external_api_allowed
        and context.mode != ProcessingMode.PRIVATE
        and not context.data_policy.private_processing
        and Route.MISTRAL_FALLBACK in context.ready_routes
    )


def decide_escalation(
    *,
    current_route: Route,
    signal: QualitySignal,
    attempt_number: int,
    max_attempts: int,
    context: RouterContext,
) -> EscalationDecision:
    if attempt_number < 1 or max_attempts < 1:
        raise ValueError("attempt counts start at one")

    if signal.security_quarantine_required or signal.source_integrity_failure:
        return EscalationDecision(
            action=EscalationAction.QUARANTINE,
            route=Route.QUARANTINE,
            reason_codes=(
                "security_quarantine_required"
                if signal.security_quarantine_required
                else "source_integrity_failure",
            ),
            attempt_number=attempt_number,
            policy_version=context.policy_version,
        )

    if signal.unreadable or signal.unsupported_content:
        return EscalationDecision(
            action=EscalationAction.QUARANTINE,
            route=Route.QUARANTINE,
            reason_codes=("unreadable_source" if signal.unreadable else "unsupported_content",),
            attempt_number=attempt_number,
            policy_version=context.policy_version,
        )

    if signal.critical_numeric_mismatch or signal.critical_table_error:
        reason = (
            "critical_numeric_mismatch"
            if signal.critical_numeric_mismatch
            else "critical_table_error"
        )
        if signal.authority_match is True:
            return EscalationDecision(
                action=EscalationAction.VERIFY_AUTHORITY,
                route=Route.AUTHORITY_RECONSTRUCTION,
                reason_codes=(reason, "authority_exact_reconstruction"),
                attempt_number=attempt_number,
                policy_version=context.policy_version,
            )
        if context.feature_flags.authority_verification_enabled:
            return EscalationDecision(
                action=EscalationAction.VERIFY_AUTHORITY,
                route=Route.AUTHORITY_RECONSTRUCTION,
                reason_codes=(reason, "authority_check_required"),
                attempt_number=attempt_number,
                policy_version=context.policy_version,
            )
        return EscalationDecision(
            action=EscalationAction.UNRESOLVED,
            route=Route.UNRESOLVED,
            reason_codes=(reason, "authority_unavailable"),
            attempt_number=attempt_number,
            policy_version=context.policy_version,
        )

    if context.risk_tier == RiskTier.HIGH and signal.agreement_numeric != 1.0:
        if context.feature_flags.authority_verification_enabled:
            return EscalationDecision(
                action=EscalationAction.VERIFY_AUTHORITY,
                route=Route.AUTHORITY_RECONSTRUCTION,
                reason_codes=(
                    "high_risk_numeric_exact_match_required",
                    "numeric_agreement_missing"
                    if signal.agreement_numeric is None
                    else "numeric_agreement_below_one",
                    "authority_check_required",
                ),
                attempt_number=attempt_number,
                policy_version=context.policy_version,
            )
        return EscalationDecision(
            action=EscalationAction.UNRESOLVED,
            route=Route.UNRESOLVED,
            reason_codes=(
                "high_risk_numeric_exact_match_required",
                "numeric_agreement_missing"
                if signal.agreement_numeric is None
                else "numeric_agreement_below_one",
                "authority_unavailable",
            ),
            attempt_number=attempt_number,
            policy_version=context.policy_version,
        )

    if current_route == Route.UNLIMITED_LONG:
        return EscalationDecision(
            action=EscalationAction.DISCARD_CHALLENGER,
            reason_codes=(
                "long_document_result_is_comparison_only",
                "base_result_retained",
            ),
            attempt_number=attempt_number,
            policy_version=context.policy_version,
        )

    if current_route not in context.ready_routes:
        return EscalationDecision(
            action=EscalationAction.UNRESOLVED,
            route=Route.UNRESOLVED,
            reason_codes=(
                f"route_unavailable:{current_route.value}",
                "fail_closed_unresolved",
            ),
            attempt_number=attempt_number,
            policy_version=context.policy_version,
        )

    if (
        signal.passed
        and signal.score is not None
        and signal.score >= 0.82
        and not signal.empty_output
        and not signal.repetition_failure
        and not signal.provider_failure
        and not signal.engine_specific_failure
    ):
        return EscalationDecision(
            action=EscalationAction.ACCEPT,
            route=current_route,
            reason_codes=(
                "quality_gate_passed"
                if signal.score >= 0.90
                else "quality_gate_passed_with_warnings",
            ),
            attempt_number=attempt_number,
            policy_version=context.policy_version,
        )

    retryable_output_failure = (
        signal.empty_output
        or signal.repetition_failure
        or signal.provider_failure
        or signal.engine_specific_failure
    )
    if retryable_output_failure and attempt_number < max_attempts:
        return EscalationDecision(
            action=EscalationAction.RETRY,
            route=current_route,
            reason_codes=("bounded_retry",),
            attempt_number=attempt_number + 1,
            policy_version=context.policy_version,
        )

    if current_route in {Route.NATIVE, Route.HPD_FAST, Route.PADDLE_FAST}:
        if Route.PADDLE_VL not in context.ready_routes:
            return EscalationDecision(
                action=EscalationAction.UNRESOLVED,
                route=Route.UNRESOLVED,
                reason_codes=(
                    "primary_route_quality_failed",
                    "paddle_precision_unavailable",
                    "fail_closed_unresolved",
                ),
                attempt_number=attempt_number,
                policy_version=context.policy_version,
            )
        return EscalationDecision(
            action=EscalationAction.ESCALATE,
            route=Route.PADDLE_VL,
            reason_codes=("primary_route_quality_failed", "paddle_precision_escalation"),
            attempt_number=1,
            policy_version=context.policy_version,
        )

    if current_route == Route.PADDLE_VL and _external_fallback_allowed(context):
        return EscalationDecision(
            action=EscalationAction.ESCALATE,
            route=Route.MISTRAL_FALLBACK,
            reason_codes=("internal_parser_failed", "explicit_external_consent"),
            attempt_number=1,
            policy_version=context.policy_version,
        )

    if (
        signal.region_recoverable
        and context.feature_flags.region_recovery_enabled
        and Route.REGION_RECOVERY in context.ready_routes
    ):
        return EscalationDecision(
            action=EscalationAction.ESCALATE,
            route=Route.REGION_RECOVERY,
            reason_codes=("failed_region_isolated", "region_recovery_enqueued"),
            attempt_number=1,
            policy_version=context.policy_version,
        )

    if context.feature_flags.authority_verification_enabled:
        return EscalationDecision(
            action=EscalationAction.VERIFY_AUTHORITY,
            route=Route.AUTHORITY_RECONSTRUCTION,
            reason_codes=("quality_gate_failed", "authority_check_required"),
            attempt_number=attempt_number,
            policy_version=context.policy_version,
        )

    return EscalationDecision(
        action=EscalationAction.UNRESOLVED,
        route=Route.UNRESOLVED,
        reason_codes=("quality_gate_failed", "automatic_recovery_exhausted"),
        attempt_number=attempt_number,
        policy_version=context.policy_version,
    )
