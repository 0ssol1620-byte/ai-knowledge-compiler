from __future__ import annotations

from akc_cir.inspection import FailureCode
from akc_cir.parser_verification import (
    ParserCapability,
    ParserObservation,
    VerificationGate,
    check_cross_page_consistency,
    compare_parser_outputs,
    select_verification_parsers,
)

PRIMARY = ParserCapability("paddle", "paddle", estimated_gpu_seconds=3, estimated_cost_usd=0.01)
ALT = ParserCapability(
    "glm",
    "glm",
    estimated_gpu_seconds=5,
    estimated_cost_usd=0.02,
    supports_visual=True,
)


def test_low_risk_does_not_pay_for_every_parser() -> None:
    decision = select_verification_parsers(PRIMARY, [ALT], risk=0.1, uncertainty=0.1)
    assert [item.name for item in decision.selected] == ["paddle"]
    assert not decision.multi_parser


def test_high_risk_uses_available_independent_parser_within_budget() -> None:
    decision = select_verification_parsers(
        PRIMARY, [ALT], risk=0.8, uncertainty=0.2, has_table=True
    )
    assert [item.name for item in decision.selected] == ["paddle", "glm"]
    assert decision.multi_parser
    assert decision.run_visual_round_trip


def test_unavailable_or_over_budget_parser_is_not_a_hard_dependency() -> None:
    unavailable = ParserCapability("missing", "other", available=False)
    expensive = ParserCapability("expensive", "other2", estimated_cost_usd=10)
    decision = select_verification_parsers(
        PRIMARY,
        [unavailable, expensive],
        risk=0.9,
        uncertainty=0.9,
        gate=VerificationGate(max_cost_usd=0.05),
    )
    assert [item.name for item in decision.selected] == ["paddle"]
    assert "no alternate" in decision.reason


def test_critical_failure_forces_verification_even_when_risk_score_is_low() -> None:
    decision = select_verification_parsers(
        PRIMARY,
        [ALT],
        risk=0.1,
        uncertainty=0.1,
        failure_codes=[FailureCode.F14_FORMULA],
    )
    assert decision.multi_parser


def test_parser_agreement_keeps_text_and_critical_fact_axes_separate() -> None:
    agreement = compare_parser_outputs(
        [
            ParserObservation("paddle", "Price USD 1,250 and weight -10 kg"),
            ParserObservation("glm", "Price EUR 1,250 and weight +10 lb"),
        ]
    )
    assert agreement.compared == 1
    assert not agreement.critical_token_agreement
    assert agreement.critical_token_mismatch_count > 0
    assert agreement.unresolved


def test_cross_page_check_detects_duplicate_page_without_visual_spend() -> None:
    findings = check_cross_page_consistency(["same page text", "same page text"])
    assert findings and findings[0].kind == "duplicate_page"