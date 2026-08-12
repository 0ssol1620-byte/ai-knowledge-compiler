"""Deterministic research primitives for evidence-aware routing.

These components are intentionally authority-limited. Statistical forecasts
may rank or abstain, but they cannot bypass hard validation or provenance gates.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BetaBinomialPosterior:
    successes: int = 0
    failures: int = 0
    prior_alpha: float = 1.0
    prior_beta: float = 1.0

    def __post_init__(self) -> None:
        if self.successes < 0 or self.failures < 0:
            raise ValueError("successes and failures must be non-negative")
        if self.prior_alpha <= 0 or self.prior_beta <= 0:
            raise ValueError("beta prior parameters must be positive")

    @property
    def alpha(self) -> float:
        return self.prior_alpha + self.successes

    @property
    def beta(self) -> float:
        return self.prior_beta + self.failures

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        total = self.alpha + self.beta
        return self.alpha * self.beta / (total * total * (total + 1))

    def observe(self, *, successes: int, trials: int) -> BetaBinomialPosterior:
        if trials < 0 or successes < 0 or successes > trials:
            raise ValueError("successes must be within the non-negative trial count")
        return BetaBinomialPosterior(
            successes=self.successes + successes,
            failures=self.failures + trials - successes,
            prior_alpha=self.prior_alpha,
            prior_beta=self.prior_beta,
        )

    def normal_interval(self, z: float = 1.959963984540054) -> tuple[float, float]:
        """Return a bounded, deterministic approximation for UI/preflight use."""
        if z <= 0:
            raise ValueError("z must be positive")
        radius = z * math.sqrt(self.variance)
        return max(0.0, self.mean - radius), min(1.0, self.mean + radius)

    def stop_decision(
        self,
        *,
        required_rate: float,
        minimum_trials: int,
        z: float = 1.959963984540054,
    ) -> str:
        if not 0 <= required_rate <= 1 or minimum_trials < 1:
            raise ValueError("invalid sequential stopping policy")
        if self.successes + self.failures < minimum_trials:
            return "continue"
        lower, upper = self.normal_interval(z)
        if lower >= required_rate:
            return "accept"
        if upper < required_rate:
            return "reject"
        return "continue"


@dataclass(frozen=True, slots=True)
class ScheduleScenario:
    page_credits: tuple[float, ...]
    parallelism: int
    seconds_per_credit_mean: float
    seconds_per_credit_stddev: float
    cold_start_probability: float = 0.0
    cold_start_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.page_credits or any(value <= 0 for value in self.page_credits):
            raise ValueError("page credits must be positive")
        if self.parallelism < 1 or self.seconds_per_credit_mean <= 0:
            raise ValueError("parallelism and mean duration must be positive")
        if self.seconds_per_credit_stddev < 0:
            raise ValueError("duration standard deviation cannot be negative")
        if not 0 <= self.cold_start_probability <= 1 or self.cold_start_seconds < 0:
            raise ValueError("invalid cold-start assumptions")


@dataclass(frozen=True, slots=True)
class MonteCarloScheduleEstimate:
    simulations: int
    p50_seconds: float
    p95_seconds: float
    mean_seconds: float
    seed: int


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * probability
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def estimate_schedule(
    scenario: ScheduleScenario, *, simulations: int = 2_000, seed: int = 0
) -> MonteCarloScheduleEstimate:
    if simulations < 100:
        raise ValueError("at least 100 simulations are required")
    # The seeded generator provides reproducible simulation, not security tokens.
    rng = random.Random(seed)  # noqa: S311
    totals: list[float] = []
    for _ in range(simulations):
        lanes = [0.0] * scenario.parallelism
        for credit in sorted(scenario.page_credits, reverse=True):
            sampled = max(
                0.001,
                rng.gauss(
                    scenario.seconds_per_credit_mean,
                    scenario.seconds_per_credit_stddev,
                ),
            )
            lane = min(range(scenario.parallelism), key=lanes.__getitem__)
            lanes[lane] += credit * sampled
        total = max(lanes)
        if rng.random() < scenario.cold_start_probability:
            total += scenario.cold_start_seconds
        totals.append(total)
    return MonteCarloScheduleEstimate(
        simulations=simulations,
        p50_seconds=_percentile(totals, 0.50),
        p95_seconds=_percentile(totals, 0.95),
        mean_seconds=statistics.fmean(totals),
        seed=seed,
    )


@dataclass(frozen=True, slots=True)
class CandidateForecast:
    candidate_id: str
    expected_quality: float
    quality_stddev: float
    expected_cost_usd: float
    latency_p95_seconds: float
    failure_probability: float
    calibrated: bool

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate id is required")
        if not 0 <= self.expected_quality <= 1 or self.quality_stddev < 0:
            raise ValueError("invalid quality forecast")
        if self.expected_cost_usd < 0 or self.latency_p95_seconds < 0:
            raise ValueError("cost and latency cannot be negative")
        if not 0 <= self.failure_probability <= 1:
            raise ValueError("failure probability must be between zero and one")


@dataclass(frozen=True, slots=True)
class SelectiveRouteDecision:
    disposition: str
    candidate_id: str | None
    reason_codes: tuple[str, ...]
    quality_lower_bound: float | None


def select_risk_constrained_candidate(
    candidates: Iterable[CandidateForecast],
    *,
    required_quality: float,
    max_cost_usd: float,
    max_latency_p95_seconds: float,
    max_failure_probability: float,
    uncertainty_z: float = 1.645,
) -> SelectiveRouteDecision:
    if not 0 <= required_quality <= 1:
        raise ValueError("required quality must be between zero and one")
    if min(max_cost_usd, max_latency_p95_seconds, uncertainty_z) < 0:
        raise ValueError("routing constraints cannot be negative")
    if not 0 <= max_failure_probability <= 1:
        raise ValueError("invalid failure constraint")
    eligible: list[tuple[float, CandidateForecast, float]] = []
    observed = tuple(candidates)
    for candidate in observed:
        if not candidate.calibrated:
            continue
        lower = max(0.0, candidate.expected_quality - uncertainty_z * candidate.quality_stddev)
        if (
            lower >= required_quality
            and candidate.expected_cost_usd <= max_cost_usd
            and candidate.latency_p95_seconds <= max_latency_p95_seconds
            and candidate.failure_probability <= max_failure_probability
        ):
            objective = (
                candidate.expected_cost_usd
                + candidate.failure_probability * max_cost_usd
                + candidate.latency_p95_seconds / max(max_latency_p95_seconds, 1e-9) * 1e-6
            )
            eligible.append((objective, candidate, lower))
    if eligible:
        _, winner, lower = min(eligible, key=lambda item: (item[0], item[1].candidate_id))
        return SelectiveRouteDecision(
            disposition="route",
            candidate_id=winner.candidate_id,
            reason_codes=("calibrated", "risk_constraints_satisfied"),
            quality_lower_bound=lower,
        )
    reasons = ["no_candidate_satisfied_risk_constraints"]
    if observed and not any(candidate.calibrated for candidate in observed):
        reasons.append("uncalibrated_candidates_shadow_only")
    return SelectiveRouteDecision(
        disposition="abstain",
        candidate_id=None,
        reason_codes=tuple(reasons),
        quality_lower_bound=None,
    )


__all__ = [
    "BetaBinomialPosterior",
    "CandidateForecast",
    "MonteCarloScheduleEstimate",
    "ScheduleScenario",
    "SelectiveRouteDecision",
    "estimate_schedule",
    "select_risk_constrained_candidate",
]
