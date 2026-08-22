from __future__ import annotations

from benchmark.v6.recovery_campaign import RecoveryCaseResult, evaluate_recovery_campaign


def _case(
    item_id: str,
    *,
    initial: bool,
    selective: bool,
    full: bool,
    attempted: bool,
    verified: bool,
) -> RecoveryCaseResult:
    return RecoveryCaseResult(
        item_id=item_id,
        initial_correct=initial,
        selective_final_correct=selective,
        full_replay_correct=full,
        recovery_attempted=attempted,
        recovery_verified=verified,
        critical_failure=False,
        selective_latency_seconds=1 if attempted else 0,
        full_replay_latency_seconds=4,
        selective_cost=0.25 if attempted else 0,
        full_replay_cost=1,
    )


def test_recovery_campaign_measures_uplift_yield_and_selective_advantage() -> None:
    cases = (
        _case("fixed", initial=False, selective=True, full=True, attempted=True, verified=True),
        _case("healthy", initial=True, selective=True, full=True, attempted=False, verified=False),
        _case(
            "unresolved",
            initial=False,
            selective=False,
            full=False,
            attempted=True,
            verified=False,
        ),
    )

    metrics = evaluate_recovery_campaign(cases)

    assert metrics.initial_accuracy == 1 / 3
    assert metrics.selective_final_accuracy == 2 / 3
    assert metrics.absolute_uplift == 1 / 3
    assert metrics.accepted_precision == 1
    assert metrics.verified_coverage == 2 / 3
    assert metrics.unresolved_rate == 1 / 3
    assert metrics.recovery_yield == 0.5
    assert metrics.repair_induced_error_rate == 0
    assert metrics.latency_saved_ratio > 0
    assert metrics.cost_saved_ratio > 0
    assert metrics.gate_passed is True


def test_recovery_campaign_rejects_false_verified_and_repair_induced_error() -> None:
    cases = (
        _case("damaged", initial=True, selective=False, full=True, attempted=True, verified=True),
    )

    metrics = evaluate_recovery_campaign(cases)

    assert metrics.false_verified_count == 1
    assert metrics.accepted_precision == 0
    assert metrics.repair_induced_error_rate == 1
    assert metrics.gate_passed is False
