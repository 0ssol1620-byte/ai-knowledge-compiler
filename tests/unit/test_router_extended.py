from __future__ import annotations

import pytest
from akc_router import (
    EscalationAction,
    FeatureFlags,
    KnowledgeRequest,
    KnowledgeResult,
    PageMetrics,
    PageTechnicalClass,
    ParserCapabilities,
    ParseRequest,
    ParseResult,
    ProcessingMode,
    ProviderRegistry,
    QualitySignal,
    Route,
    RouterContext,
    classify_page,
    decide_escalation,
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


class DummyParser:
    provider_id = "dummy-parser"
    capabilities = ParserCapabilities(routes=frozenset({Route.NATIVE}))

    async def parse(self, request: ParseRequest) -> ParseResult:
        return ParseResult(
            request_id=request.request_id,
            provider_id=self.provider_id,
            model_run_id="run_001",
            raw_output_object_key="raw/result.json",
            page_indexes0=request.page_indexes0,
        )


class DummyKnowledge:
    provider_id = "dummy-knowledge"

    async def compile(self, request: KnowledgeRequest) -> KnowledgeResult:
        return KnowledgeResult(
            request_id=request.request_id,
            provider_id=self.provider_id,
            model_run_id="run_001",
            output_object_key="knowledge/result.json",
        )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    (
        ({"handwriting_probability": 0.6}, PageTechnicalClass.HANDWRITTEN),
        ({"rotation_degrees": 90}, PageTechnicalClass.ROTATED_OR_WARPED),
        ({"table_density": 0.2}, PageTechnicalClass.TABLE_HEAVY),
        ({"formula_density": 0.05}, PageTechnicalClass.FORMULA_HEAVY),
        ({"chart_probability": 0.5}, PageTechnicalClass.CHART_HEAVY),
        ({"image_coverage": 0.95}, PageTechnicalClass.PHOTO_DOCUMENT),
        (
            {
                "native_text_chars": 500,
                "native_text_coverage": 0.2,
                "native_reading_order_score": 0.9,
                "image_coverage": 0.1,
            },
            PageTechnicalClass.NATIVE_CLEAN,
        ),
        (
            {
                "native_text_chars": 100,
                "native_text_coverage": 0.2,
                "native_reading_order_score": 0.9,
                "image_coverage": 0.1,
                "estimated_columns": 2,
            },
            PageTechnicalClass.NATIVE_COMPLEX,
        ),
        (
            {"native_text_chars": 50, "image_coverage": 0.3},
            PageTechnicalClass.MIXED,
        ),
        ({"image_coverage": 0.8}, PageTechnicalClass.SCAN_TEXT),
    ),
)
def test_page_classification_routes_objective_features(
    overrides: dict[str, object],
    expected: PageTechnicalClass,
) -> None:
    assert classify_page(page_metrics(**overrides)) == expected


def test_provider_registry_rejects_duplicates_and_wrong_capability() -> None:
    registry = ProviderRegistry()
    parser = DummyParser()
    registry.register_parser(parser, ready=True)
    registry.register_knowledge(DummyKnowledge(), ready=True)
    assert registry.parser_for("dummy-parser", Route.NATIVE) is parser
    assert registry.knowledge_for("dummy-knowledge").provider_id == "dummy-knowledge"
    with pytest.raises(ValueError, match="duplicate"):
        registry.register_parser(parser, ready=True)
    with pytest.raises(LookupError, match="does not support"):
        registry.parser_for("dummy-parser", Route.PADDLE_VL)
    with pytest.raises(LookupError, match="unknown"):
        registry.parser_for("missing", Route.NATIVE)
    with pytest.raises(LookupError, match="unknown"):
        registry.knowledge_for("missing")
    registry.set_parser_state("dummy-parser", ready=False)
    with pytest.raises(LookupError, match="not ready") as unavailable:
        registry.parser_for("dummy-parser", Route.NATIVE)
    assert unavailable.value.manual_review_required
    registry.set_knowledge_state("dummy-knowledge", enabled=False)
    with pytest.raises(LookupError, match="disabled") as disabled:
        registry.knowledge_for("dummy-knowledge")
    assert disabled.value.manual_review_required


def test_parse_request_requires_unique_nonnegative_pages() -> None:
    base = {
        "request_id": "request_001",
        "tenant_id": "tenant_001",
        "document_id": "document_001",
        "document_version_id": "version_001",
        "object_key": "source/object",
        "route": Route.NATIVE,
    }
    with pytest.raises(ValidationError):
        ParseRequest(**base, page_indexes0=())
    with pytest.raises(ValidationError):
        ParseRequest(**base, page_indexes0=(0, 0))
    with pytest.raises(ValidationError):
        ParseRequest(**base, page_indexes0=(-1,))


def test_remaining_escalation_outcomes_are_bounded() -> None:
    context = RouterContext(ready_routes=frozenset({Route.NATIVE, Route.PADDLE_VL}))
    assert (
        decide_escalation(
            current_route=Route.PADDLE_VL,
            signal=QualitySignal(unreadable=True),
            attempt_number=1,
            max_attempts=3,
            context=context,
        ).action
        == EscalationAction.FAIL
    )
    retry = decide_escalation(
        current_route=Route.PADDLE_VL,
        signal=QualitySignal(empty_output=True),
        attempt_number=1,
        max_attempts=3,
        context=context,
    )
    assert retry.action == EscalationAction.RETRY
    native = decide_escalation(
        current_route=Route.NATIVE,
        signal=QualitySignal(score=0.5),
        attempt_number=2,
        max_attempts=2,
        context=context,
    )
    assert native.route == Route.PADDLE_VL
    accepted = decide_escalation(
        current_route=Route.PADDLE_VL,
        signal=QualitySignal(passed=True, score=0.95),
        attempt_number=1,
        max_attempts=3,
        context=context,
    )
    assert accepted.action == EscalationAction.ACCEPT
    long_result = decide_escalation(
        current_route=Route.UNLIMITED_LONG,
        signal=QualitySignal(passed=True, score=0.95, base_result_passed=True),
        attempt_number=1,
        max_attempts=1,
        context=context,
    )
    assert long_result.action == EscalationAction.DISCARD_CHALLENGER


def test_paddle_fast_requires_explicit_flag() -> None:
    decision = select_first_route(
        RouterContext(
            mode=ProcessingMode.SPEED,
            dominant_language="ko",
            feature_flags=FeatureFlags(paddle_fast_enabled=True),
            ready_routes=frozenset({Route.NATIVE, Route.PADDLE_VL, Route.PADDLE_FAST}),
        ),
        page_metrics(),
    )
    assert decision.route == Route.PADDLE_FAST
