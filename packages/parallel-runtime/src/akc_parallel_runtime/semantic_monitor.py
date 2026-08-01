"""Online semantic-health statistics separated from infrastructure health."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SemanticSample:
    stratum: str
    passed: bool
    loss: float

    def __post_init__(self) -> None:
        if not self.stratum:
            raise ValueError("semantic sample requires a stratum")
        if not 0 <= self.loss <= 1:
            raise ValueError("semantic loss must be between zero and one")


@dataclass(frozen=True, slots=True)
class StratumPosterior:
    stratum: str
    successes: int
    failures: int
    posterior_mean_pass_rate: float
    lower_bound: float
    upper_bound: float


@dataclass(frozen=True, slots=True)
class SemanticHealthProjection:
    state: str
    ewma_loss: float
    cusum_positive: float
    reason_codes: tuple[str, ...]
    strata: tuple[StratumPosterior, ...]


@dataclass(slots=True)
class SemanticDriftMonitor:
    ewma_alpha: float = 0.2
    target_loss: float = 0.05
    cusum_slack: float = 0.01
    degraded_threshold: float = 0.10
    quarantine_threshold: float = 0.25
    prior_alpha: float = 1.0
    prior_beta: float = 1.0
    _ewma: float | None = field(default=None, init=False)
    _cusum: float = field(default=0.0, init=False)
    _strata: dict[str, list[int]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if not 0 < self.ewma_alpha <= 1:
            raise ValueError("EWMA alpha must be in (0, 1]")
        if not 0 <= self.target_loss <= 1:
            raise ValueError("target loss must be between zero and one")
        if not 0 <= self.degraded_threshold < self.quarantine_threshold <= 1:
            raise ValueError("semantic thresholds must be ordered")
        if min(self.prior_alpha, self.prior_beta) <= 0:
            raise ValueError("beta prior parameters must be positive")

    def observe(self, sample: SemanticSample) -> SemanticHealthProjection:
        self._ewma = (
            sample.loss
            if self._ewma is None
            else self.ewma_alpha * sample.loss + (1 - self.ewma_alpha) * self._ewma
        )
        self._cusum = max(
            0.0,
            self._cusum + sample.loss - self.target_loss - self.cusum_slack,
        )
        counts = self._strata.setdefault(sample.stratum, [0, 0])
        counts[0 if sample.passed else 1] += 1
        return self.project()

    def project(self) -> SemanticHealthProjection:
        ewma = self._ewma if self._ewma is not None else 0.0
        reasons: list[str] = []
        state = "healthy"
        if ewma >= self.quarantine_threshold:
            state = "quarantined"
            reasons.append("semantic_ewma_quarantine")
        elif ewma >= self.degraded_threshold:
            state = "degraded"
            reasons.append("semantic_ewma_degraded")
        if self._cusum >= self.quarantine_threshold:
            state = "quarantined"
            reasons.append("semantic_cusum_change_detected")
        strata: list[StratumPosterior] = []
        for name, (successes, failures) in sorted(self._strata.items()):
            alpha = self.prior_alpha + successes
            beta = self.prior_beta + failures
            total = alpha + beta
            mean = alpha / total
            variance = alpha * beta / (total * total * (total + 1))
            radius = 1.959963984540054 * math.sqrt(variance)
            strata.append(
                StratumPosterior(
                    stratum=name,
                    successes=successes,
                    failures=failures,
                    posterior_mean_pass_rate=mean,
                    lower_bound=max(0.0, mean - radius),
                    upper_bound=min(1.0, mean + radius),
                )
            )
        return SemanticHealthProjection(
            state=state,
            ewma_loss=ewma,
            cusum_positive=self._cusum,
            reason_codes=tuple(sorted(set(reasons or ["semantic_health_nominal"]))),
            strata=tuple(strata),
        )


__all__ = [
    "SemanticDriftMonitor",
    "SemanticHealthProjection",
    "SemanticSample",
    "StratumPosterior",
]
