from __future__ import annotations

import pytest
from akc_router import (
    DataPolicy,
    EscalationAction,
    FeatureFlags,
    PageMetrics,
    ProcessingMode,
    QualitySignal,
    RiskTier,
    Route,
    RouterContext,
    decide_escalation,
    detect_script_distribution,
    native_candidate,
    preflight_difficulty,
    select_first_route,
)
from pydantic import ValidationError


def page_metrics(**overrides: object) -> PageMetrics:
    values: dict[str, object] = {
        "page_index0": 0,
        "width": 1000,
        "height": 1400,
        "native_text_chars": 0,
        "native_word_count": 0,
        "native_block_count": 0,
        "native_text_coverage": 0.0,
        "image_coverage": 0.9,
        "invalid_unicode_ratio": 0.0,
        "replacement_char_ratio": 0.0,
        "whitespace_anomaly_score": 0.0,
        "native_reading_order_score": 0.0,
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
        "script_distribution": {"Hangul": 1.0},
        "suspected_prompt_injection": False,
    }
    values.update(overrides)
    return PageMetrics.model_validate(values)


def test_native_gate_and_exact_difficulty() -> None:
    page = page_metrics(
        native_text_chars=500,
        native_word_count=100,
        native_block_count=10,
        native_text_coverage=0.2,
        image_coverage=0.1,
        native_reading_order_score=0.9,
    )
    assert native_candidate(page)
    assert preflight_difficulty(page) == pytest.approx(1.2)
    decision = select_first_route(RouterContext(), page)
    assert decision.route == Route.NATIVE
    assert decision.expected_credits == 0.25


def test_hpd_is_closed_by_default_and_korean_uses_paddle() -> None:
    scan = page_metrics()
    speed = RouterContext(
        mode=ProcessingMode.SPEED,
        dominant_language="ko",
        ready_routes=frozenset({Route.NATIVE, Route.PADDLE_VL}),
    )
    paddle = select_first_route(speed, scan)
    assert paddle.route == Route.PADDLE_VL
    assert paddle.expected_credits == 1.0
    hpd = RouterContext(
        mode=ProcessingMode.SPEED,
        dominant_language="en",
        feature_flags=FeatureFlags(hpd_enabled=True),
        ready_routes=frozenset({Route.NATIVE, Route.PADDLE_VL, Route.HPD_FAST}),
    )
    assert select_first_route(hpd, scan).route == Route.HPD_FAST


def test_precision_and_complexity_credit_surcharges_are_additive() -> None:
    complex_scan = page_metrics(
        table_density=1.0,
        formula_density=0.2,
        blur_score=1.0,
    )
    decision = select_first_route(
        RouterContext(
            mode=ProcessingMode.PRECISION,
            ready_routes=frozenset({Route.NATIVE, Route.PADDLE_VL}),
        ),
        complex_scan,
    )
    assert decision.route == Route.PADDLE_VL
    assert decision.expected_credits == 2.5


def test_external_fallback_requires_capability_and_consent() -> None:
    signal = QualitySignal(provider_failure=True)
    no_consent = decide_escalation(
        current_route=Route.PADDLE_VL,
        signal=signal,
        attempt_number=3,
        max_attempts=3,
        context=RouterContext(feature_flags=FeatureFlags(external_fallback_enabled=True)),
    )
    assert no_consent.action == EscalationAction.REVIEW
    consent = RouterContext(
        feature_flags=FeatureFlags(external_fallback_enabled=True),
        data_policy=DataPolicy(external_api_allowed=True),
        ready_routes=frozenset({Route.NATIVE, Route.PADDLE_VL, Route.MISTRAL_FALLBACK}),
    )
    decision = decide_escalation(
        current_route=Route.PADDLE_VL,
        signal=signal,
        attempt_number=3,
        max_attempts=3,
        context=consent,
    )
    assert decision.route == Route.MISTRAL_FALLBACK


def test_private_mode_cannot_enable_external_api() -> None:
    with pytest.raises(ValidationError, match="private mode"):
        RouterContext(
            mode=ProcessingMode.PRIVATE,
            data_policy=DataPolicy(external_api_allowed=True),
        )


def test_critical_numeric_mismatch_always_reviews() -> None:
    decision = decide_escalation(
        current_route=Route.NATIVE,
        signal=QualitySignal(
            passed=True,
            score=0.99,
            critical_numeric_mismatch=True,
        ),
        attempt_number=1,
        max_attempts=2,
        context=RouterContext(risk_tier=RiskTier.HIGH),
    )
    assert decision.action == EscalationAction.REVIEW


def test_quality_pass_cannot_bypass_score_threshold_or_provider_failure() -> None:
    with pytest.raises(ValidationError, match=r"score >= 0\.82"):
        QualitySignal(passed=True, score=0.81)
    decision = decide_escalation(
        current_route=Route.PADDLE_VL,
        signal=QualitySignal(passed=True, score=0.99, provider_failure=True),
        attempt_number=1,
        max_attempts=2,
        context=RouterContext(ready_routes=frozenset({Route.NATIVE, Route.PADDLE_VL})),
    )
    assert decision.action == EscalationAction.RETRY
    warning_pass = decide_escalation(
        current_route=Route.PADDLE_VL,
        signal=QualitySignal(passed=True, score=0.85),
        attempt_number=1,
        max_attempts=2,
        context=RouterContext(ready_routes=frozenset({Route.NATIVE, Route.PADDLE_VL})),
    )
    assert warning_pass.action == EscalationAction.ACCEPT
    assert warning_pass.reason_codes == ("quality_gate_passed_with_warnings",)


def test_unready_route_fails_closed_to_manual_review() -> None:
    context = RouterContext(ready_routes=frozenset({Route.NATIVE}))
    decision = select_first_route(context, page_metrics())
    assert decision.route == Route.MANUAL_REVIEW
    assert "fail_closed_manual_review" in decision.reason_codes


def test_unicode_script_detection_does_not_guess_language() -> None:
    distribution = detect_script_distribution("한글 English 中文")
    assert set(distribution) == {"Hangul", "Latin", "Han"}
    assert sum(distribution.values()) == pytest.approx(1.0)
