"""Recovery selection and arbitration — §N10 and §N11.

The blocker condition §N43 sets for this subsystem is *unbounded retry or silent
downgrade*. Most of these tests are that blocker written as assertions: every path
out of the ladder is named, and none of them is a quietly worse answer.
"""

from __future__ import annotations

import pytest
from akc_cir.inspection import FailureCode
from akc_cir.recovery_policy import (
    AgreementVector,
    ArbitrationOutcome,
    Availability,
    CircuitState,
    ConsensusTrigger,
    PolicyRegistry,
    QualityMode,
    RecoveryAttempt,
    RecoveryBudget,
    RecoveryLedger,
    RecoveryLevel,
    RecoveryOutcome,
    RecoveryPolicy,
    arbitrate,
    circuit_state,
    document_availability,
    select_recovery,
)

TABLE = FailureCode.F13_TABLE_STRUCTURE


def _policy(level: RecoveryLevel, action: str, **kw) -> RecoveryPolicy:
    return RecoveryPolicy(
        policy_id=f"{action}_v1", code=TABLE, level=level, action=action, **kw
    )


def _registry() -> PolicyRegistry:
    return PolicyRegistry(
        [
            _policy(RecoveryLevel.L3_ALTERNATE_PARSER_FAMILY, "alt_parser"),
            _policy(RecoveryLevel.L1_SAFE_RERENDER, "rerender_300dpi"),
            _policy(RecoveryLevel.L5_STRONGER_VERIFIER, "stronger_vlm"),
            _policy(RecoveryLevel.L2_SAME_PARSER_VARIATION, "language_hint"),
        ]
    )


# --------------------------------------------------------------------------
# §N11.1 — the ladder is walked cheapest first
# --------------------------------------------------------------------------


def test_the_cheapest_rung_that_applies_is_chosen_first() -> None:
    decision = select_recovery(
        code=TABLE, failure_signature="sig_a", registry=_registry()
    )

    assert decision.outcome is RecoveryOutcome.APPLY
    assert decision.policy is not None
    assert decision.policy.level is RecoveryLevel.L1_SAFE_RERENDER


def test_a_rung_already_tried_is_not_tried_again() -> None:
    history = [
        RecoveryAttempt(
            policy_signature=_policy(
                RecoveryLevel.L1_SAFE_RERENDER, "rerender_300dpi"
            ).signature,
            failure_signature="sig_a",
        )
    ]

    decision = select_recovery(
        code=TABLE,
        failure_signature="sig_b",
        registry=_registry(),
        history=history,
    )

    assert decision.policy is not None
    assert decision.policy.level is RecoveryLevel.L2_SAME_PARSER_VARIATION


def test_the_ladder_is_ordered_by_cost() -> None:
    assert RecoveryLevel.L1_SAFE_RERENDER < RecoveryLevel.L5_STRONGER_VERIFIER
    assert max(RecoveryLevel) == RecoveryLevel.L8_FAIL_CLOSED


# --------------------------------------------------------------------------
# §38 — the quality mode is a real ceiling, not a label
# --------------------------------------------------------------------------


def test_fast_mode_will_not_book_a_second_parser() -> None:
    history = [
        RecoveryAttempt(policy_signature=p.signature, failure_signature="s")
        for p in (
            _policy(RecoveryLevel.L1_SAFE_RERENDER, "rerender_300dpi"),
            _policy(RecoveryLevel.L2_SAME_PARSER_VARIATION, "language_hint"),
        )
    ]

    decision = select_recovery(
        code=TABLE,
        failure_signature="sig_new",
        registry=_registry(),
        history=history,
        mode=QualityMode.FAST,
    )

    assert decision.outcome is RecoveryOutcome.FAIL_CLOSED


def test_verified_mode_reaches_the_stronger_verifier() -> None:
    decision = select_recovery(
        code=TABLE,
        failure_signature="sig_a",
        registry=_registry(),
        mode=QualityMode.VERIFIED,
    )

    assert decision.outcome is RecoveryOutcome.APPLY


def test_the_mode_ceilings_are_the_ones_the_masterplan_set() -> None:
    assert QualityMode.FAST.max_level is RecoveryLevel.L2_SAME_PARSER_VARIATION
    assert QualityMode.BALANCED.max_level is RecoveryLevel.L4_CONDITIONAL_ENSEMBLE
    assert QualityMode.VERIFIED.max_level is RecoveryLevel.L7_HUMAN_REVIEW


def test_only_verified_mode_can_ask_a_human() -> None:
    assert QualityMode.VERIFIED.allows_review is True
    assert QualityMode.BALANCED.allows_review is False


# --------------------------------------------------------------------------
# §N11.2 — security first
# --------------------------------------------------------------------------


def test_a_security_failure_is_blocked_not_retried() -> None:
    """Retrying a poisoned document is running it again."""
    decision = select_recovery(
        code=FailureCode.F29_PROMPT_INJECTION_SUSPECTED,
        failure_signature="sig",
        registry=_registry(),
    )

    assert decision.outcome is RecoveryOutcome.BLOCK_SECURITY
    assert decision.policy is None


def test_security_is_checked_before_the_budget() -> None:
    """A poisoned document blocked for being over budget is blocked for the wrong reason."""
    spent = [
        RecoveryAttempt(
            policy_signature=f"p{i}", failure_signature="s", cost_units=1000.0
        )
        for i in range(9)
    ]

    decision = select_recovery(
        code=FailureCode.F45_ACTIVE_CONTENT_OR_MALWARE,
        failure_signature="sig",
        registry=_registry(),
        history=spent,
    )

    assert decision.outcome is RecoveryOutcome.BLOCK_SECURITY


# --------------------------------------------------------------------------
# §17.4 — retry storms
# --------------------------------------------------------------------------


def test_the_same_failure_twice_stops_rather_than_trying_harder() -> None:
    history = [
        RecoveryAttempt(policy_signature="p1", failure_signature="sig_same"),
        RecoveryAttempt(policy_signature="p2", failure_signature="sig_same"),
    ]

    decision = select_recovery(
        code=TABLE,
        failure_signature="sig_same",
        registry=_registry(),
        history=history,
    )

    assert decision.outcome is RecoveryOutcome.FAIL_CLOSED
    assert "retry storm" in decision.reason


def test_a_different_failure_each_time_keeps_climbing() -> None:
    history = [
        RecoveryAttempt(policy_signature="p1", failure_signature="sig_a"),
        RecoveryAttempt(policy_signature="p2", failure_signature="sig_b"),
    ]

    decision = select_recovery(
        code=TABLE, failure_signature="sig_c", registry=_registry(), history=history
    )

    assert decision.outcome is RecoveryOutcome.APPLY


def test_the_attempt_cap_stops_the_ladder() -> None:
    history = [
        RecoveryAttempt(policy_signature=f"p{i}", failure_signature=f"s{i}")
        for i in range(4)
    ]

    decision = select_recovery(
        code=TABLE,
        failure_signature="sig_new",
        registry=_registry(),
        history=history,
        budget=RecoveryBudget(max_attempts_per_page=4),
    )

    assert decision.outcome is RecoveryOutcome.BUDGET_EXHAUSTED


def test_an_expensive_rung_is_not_started_without_the_budget_for_it() -> None:
    registry = PolicyRegistry(
        [_policy(RecoveryLevel.L1_SAFE_RERENDER, "big", estimated_gpu_seconds=900.0)]
    )

    decision = select_recovery(
        code=TABLE,
        failure_signature="sig",
        registry=registry,
        budget=RecoveryBudget(max_gpu_seconds=600.0),
    )

    assert decision.outcome is RecoveryOutcome.BUDGET_EXHAUSTED


# --------------------------------------------------------------------------
# §N43 — no silent downgrade
# --------------------------------------------------------------------------


def test_a_failure_with_no_registered_rung_does_not_resolve_as_success() -> None:
    """A code the inspector can raise and nothing addresses must not fall through."""
    decision = select_recovery(
        code=FailureCode.F14_FORMULA,
        failure_signature="sig",
        registry=_registry(),
    )

    assert decision.outcome is RecoveryOutcome.FAIL_CLOSED
    assert "no recovery rung is registered" in decision.reason


def test_the_registry_can_name_the_codes_nothing_covers() -> None:
    uncovered = _registry().uncovered([TABLE, FailureCode.F14_FORMULA])

    assert uncovered == (FailureCode.F14_FORMULA,)


def test_every_outcome_carries_a_reason() -> None:
    decisions = [
        select_recovery(code=TABLE, failure_signature="s", registry=_registry()),
        select_recovery(
            code=FailureCode.F28_SECURITY_BLOCKED,
            failure_signature="s",
            registry=_registry(),
        ),
        select_recovery(
            code=FailureCode.F14_FORMULA, failure_signature="s", registry=_registry()
        ),
    ]

    assert all(decision.reason for decision in decisions)


def test_running_out_in_verified_mode_asks_a_human_rather_than_failing() -> None:
    decision = select_recovery(
        code=FailureCode.F14_FORMULA,
        failure_signature="sig",
        registry=_registry(),
        mode=QualityMode.VERIFIED,
    )

    assert decision.outcome is RecoveryOutcome.HUMAN_REVIEW


# --------------------------------------------------------------------------
# §N11.3 — the circuit breaker, and the four pods
# --------------------------------------------------------------------------


def test_a_provider_correlated_failure_opens_the_circuit() -> None:
    state, reason = circuit_state(provider_scoped_signatures=1)

    assert state is CircuitState.OPEN
    assert "provider" in reason


def test_an_open_circuit_pauses_instead_of_buying_capacity() -> None:
    decision = select_recovery(
        code=TABLE,
        failure_signature="sig",
        registry=_registry(),
        circuit_open=True,
    )

    assert decision.outcome is RecoveryOutcome.PAUSED_DEPENDENCY


def test_a_dependency_outage_opens_the_circuit() -> None:
    state, _ = circuit_state(provider_scoped_signatures=0, dependency_outage=True)

    assert state is CircuitState.OPEN


def test_queue_delay_eating_the_ttl_opens_the_circuit() -> None:
    state, reason = circuit_state(
        provider_scoped_signatures=0,
        queue_delay_seconds=400.0,
        ttl_budget_seconds=300.0,
    )

    assert state is CircuitState.OPEN
    assert "TTL" in reason


def test_an_ordinary_document_failure_does_not_open_the_circuit() -> None:
    state, _ = circuit_state(provider_scoped_signatures=0)

    assert state is CircuitState.CLOSED


# --------------------------------------------------------------------------
# §N11.4 — partial availability
# --------------------------------------------------------------------------


def test_a_document_missing_pages_is_partial_and_names_them() -> None:
    report = document_availability(total_pages=5, verified_pages=[1, 2, 4])

    assert report.availability is Availability.PARTIAL
    assert report.missing_pages == (3, 5)


def test_a_complete_document_says_so() -> None:
    report = document_availability(total_pages=3, verified_pages=[1, 2, 3])

    assert report.availability is Availability.COMPLETE
    assert report.missing_pages == ()


def test_nothing_verified_is_unavailable_not_partial() -> None:
    report = document_availability(total_pages=3, verified_pages=[])

    assert report.availability is Availability.UNAVAILABLE


# --------------------------------------------------------------------------
# §N10 — consensus and arbitration
# --------------------------------------------------------------------------


def _agreement(**overrides) -> AgreementVector:
    values = {
        "text_similarity": 0.94,
        "block_sequence_similarity": 0.93,
        "bbox_alignment": 0.95,
        "table_grid_similarity": 0.96,
        "reading_order_similarity": 0.94,
        "consensus_entropy": 0.10,
    }
    values.update(overrides)
    return AgreementVector(**values)


def test_agreement_plus_source_checks_accepts() -> None:
    verdict = arbitrate(_agreement(), source_aware_checks_passed=True)

    assert verdict.outcome is ArbitrationOutcome.ACCEPT


def test_agreement_without_source_checks_never_accepts() -> None:
    """Two parsers agreeing may be two parsers making the same mistake."""
    verdict = arbitrate(_agreement(), source_aware_checks_passed=False)

    assert verdict.outcome is ArbitrationOutcome.ESCALATE
    assert "same mistake" in verdict.reason


def test_disagreement_escalates_to_a_third_opinion() -> None:
    verdict = arbitrate(
        _agreement(table_grid_similarity=0.72), source_aware_checks_passed=True
    )

    assert verdict.outcome is ArbitrationOutcome.ESCALATE
    assert verdict.weakest_dimension == "table_grid_similarity"


def test_a_three_way_conflict_goes_to_a_human() -> None:
    verdict = arbitrate(
        _agreement(table_grid_similarity=0.40),
        source_aware_checks_passed=True,
        candidate_count=3,
    )

    assert verdict.outcome is ArbitrationOutcome.HUMAN_REVIEW
    assert "no majority worth trusting" in verdict.reason


def test_bad_disagreement_between_two_also_goes_to_a_human() -> None:
    verdict = arbitrate(
        _agreement(text_similarity=0.20), source_aware_checks_passed=True
    )

    assert verdict.outcome is ArbitrationOutcome.HUMAN_REVIEW


def test_parser_self_confidence_can_escalate_but_never_accept() -> None:
    low = arbitrate(
        _agreement(), source_aware_checks_passed=True, parser_self_confidence=0.2
    )
    high = arbitrate(
        _agreement(table_grid_similarity=0.75),
        source_aware_checks_passed=True,
        parser_self_confidence=0.99,
    )

    assert low.outcome is ArbitrationOutcome.ESCALATE
    assert high.outcome is ArbitrationOutcome.ESCALATE


def test_the_weakest_dimension_is_what_drives_the_verdict() -> None:
    """A single similarity number cannot tell reordering from rewriting."""
    verdict = arbitrate(
        _agreement(reading_order_similarity=0.55), source_aware_checks_passed=True
    )

    assert verdict.weakest_dimension == "reading_order_similarity"


def test_an_agreement_value_outside_zero_to_one_is_refused() -> None:
    with pytest.raises(ValueError, match=r"within 0\.\.1"):
        _agreement(text_similarity=1.5)


# --------------------------------------------------------------------------
# §N10.1 — a second parser runs for a stated reason
# --------------------------------------------------------------------------


def test_a_clean_page_does_not_get_a_second_parser() -> None:
    assert ConsensusTrigger().should_run is False


def test_a_suspicious_page_does() -> None:
    trigger = ConsensusTrigger(inspector_suspicious=True)

    assert trigger.should_run is True
    assert trigger.reasons == ("inspector_suspicious",)


# --------------------------------------------------------------------------
# The ledger
# --------------------------------------------------------------------------


def test_the_ledger_totals_what_recovery_cost() -> None:
    ledger = RecoveryLedger().with_attempt(
        RecoveryAttempt(
            policy_signature="p1",
            failure_signature="s",
            gpu_seconds=12.0,
            cost_units=3.0,
        )
    )
    ledger = ledger.with_attempt(
        RecoveryAttempt(
            policy_signature="p2",
            failure_signature="s",
            succeeded=True,
            gpu_seconds=30.0,
            cost_units=8.0,
        )
    )

    assert ledger.gpu_seconds == 42.0
    assert ledger.cost_units == 11.0
    assert ledger.succeeded is True
