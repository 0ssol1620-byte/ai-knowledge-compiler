from akc_router.research import (
    BetaBinomialPosterior,
    CandidateForecast,
    ScheduleScenario,
    estimate_schedule,
    select_risk_constrained_candidate,
)


def test_beta_binomial_is_immutable_and_stops_only_with_evidence() -> None:
    prior = BetaBinomialPosterior()
    posterior = prior.observe(successes=98, trials=100)
    assert prior.successes == 0
    assert posterior.mean > 0.97
    assert posterior.stop_decision(required_rate=0.93, minimum_trials=30) == "accept"
    assert BetaBinomialPosterior().observe(successes=2, trials=10).stop_decision(
        required_rate=0.9, minimum_trials=30
    ) == "continue"


def test_schedule_estimate_is_seeded_and_p95_is_not_below_p50() -> None:
    scenario = ScheduleScenario(
        page_credits=(1.0, 1.2, 2.0, 0.8, 3.0),
        parallelism=2,
        seconds_per_credit_mean=4.0,
        seconds_per_credit_stddev=0.4,
        cold_start_probability=0.1,
        cold_start_seconds=6.0,
    )
    first = estimate_schedule(scenario, simulations=500, seed=17)
    second = estimate_schedule(scenario, simulations=500, seed=17)
    assert first == second
    assert first.p95_seconds >= first.p50_seconds > 0


def test_router_abstains_on_uncalibrated_or_risky_candidates() -> None:
    shadow = CandidateForecast("shadow", 0.99, 0.01, 0.01, 1, 0.01, False)
    assert select_risk_constrained_candidate(
        [shadow], required_quality=0.9, max_cost_usd=1, max_latency_p95_seconds=10,
        max_failure_probability=0.1,
    ).disposition == "abstain"

    safe = CandidateForecast("safe", 0.97, 0.01, 0.03, 4, 0.01, True)
    decision = select_risk_constrained_candidate(
        [shadow, safe], required_quality=0.94, max_cost_usd=0.1,
        max_latency_p95_seconds=5, max_failure_probability=0.05,
    )
    assert decision.disposition == "route"
    assert decision.candidate_id == "safe"
