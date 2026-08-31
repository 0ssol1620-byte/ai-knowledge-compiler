"""Explainable semantic-risk assessment for parser routing.

The parser layer should not treat OCR confidence as equivalent to downstream
knowledge safety.  This module keeps observable risk signals separate and only
aggregates them at the final decision boundary, so every escalation can retain
an auditable feature vector and decomposition.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum

__all__ = [
    "SemanticRiskAssessment",
    "SemanticRiskBand",
    "SemanticRiskFeatures",
    "assess_semantic_risk",
]


class SemanticRiskBand(StrEnum):
    LOW = "low"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class SemanticRiskFeatures:
    """Independent, normalized semantic-damage signals.

    All values are probabilities or normalized severities in ``[0, 1]``.
    Keeping the dimensions explicit is deliberate: callers and receipts should
    preserve this vector rather than persisting only ``expected_semantic_damage``.
    """

    parser_error_probability: float = 0.0
    parsing_uncertainty: float = 0.0
    cross_model_disagreement: float = 0.0
    critical_token_sensitivity: float = 0.0
    semantic_role_criticality: float = 0.0
    entity_criticality: float = 0.0
    temporal_significance: float = 0.0
    authority_significance: float = 0.0
    dependency_blast_radius: float = 0.0
    downstream_consumer_risk: float = 0.0

    def __post_init__(self) -> None:
        for field in fields(self):
            value = float(getattr(self, field.name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field.name} must be within 0..1")

    def as_dict(self) -> dict[str, float]:
        return {field.name: float(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class SemanticRiskAssessment:
    features: SemanticRiskFeatures
    parser_error_probability: float
    downstream_semantic_impact: float
    authority_temporal_action_criticality: float
    semantic_consequence: float
    expected_semantic_damage: float
    band: SemanticRiskBand
    dominant_signals: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "features": self.features.as_dict(),
            "parser_error_probability": self.parser_error_probability,
            "downstream_semantic_impact": self.downstream_semantic_impact,
            "authority_temporal_action_criticality": self.authority_temporal_action_criticality,
            "semantic_consequence": self.semantic_consequence,
            "expected_semantic_damage": self.expected_semantic_damage,
            "band": self.band.value,
            "dominant_signals": list(self.dominant_signals),
        }


def _noisy_or(values: tuple[float, ...]) -> float:
    """Combine independent warning channels without averaging away a severe one."""

    remainder = 1.0
    for value in values:
        remainder *= 1.0 - value
    return 1.0 - remainder


def _risk_band(value: float) -> SemanticRiskBand:
    if value >= 0.75:
        return SemanticRiskBand.CRITICAL
    if value >= 0.50:
        return SemanticRiskBand.HIGH
    if value >= 0.25:
        return SemanticRiskBand.ELEVATED
    return SemanticRiskBand.LOW


def assess_semantic_risk(features: SemanticRiskFeatures) -> SemanticRiskAssessment:
    """Estimate expected semantic damage while retaining the causal axes.

    The decomposition is intentionally transparent:

    * parser-error probability comes from parser confidence/uncertainty and
      observed model disagreement;
    * downstream semantic impact captures how widely or importantly a damaged
      fact would propagate;
    * authority/temporal/action criticality captures facts where a small token
      error can alter obligations, dates, quantities, authority, or actions.

    Impact and criticality are combined with a noisy-OR before multiplying by
    parser-error probability.  This prevents either a high blast-radius fact or
    a high-criticality fact from being accidentally zeroed merely because the
    other axis is small, while preserving all component values in the receipt.
    """

    error_probability = _noisy_or(
        (
            features.parser_error_probability,
            features.parsing_uncertainty,
            features.cross_model_disagreement,
        )
    )
    downstream_impact = _noisy_or(
        (
            features.semantic_role_criticality,
            features.entity_criticality,
            features.dependency_blast_radius,
            features.downstream_consumer_risk,
        )
    )
    criticality = _noisy_or(
        (
            features.critical_token_sensitivity,
            features.temporal_significance,
            features.authority_significance,
        )
    )
    consequence = _noisy_or((downstream_impact, criticality))
    expected_damage = error_probability * consequence

    feature_values = features.as_dict()
    dominant = tuple(
        name
        for name, value in sorted(feature_values.items(), key=lambda item: (-item[1], item[0]))
        if value >= 0.50
    )

    return SemanticRiskAssessment(
        features=features,
        parser_error_probability=error_probability,
        downstream_semantic_impact=downstream_impact,
        authority_temporal_action_criticality=criticality,
        semantic_consequence=consequence,
        expected_semantic_damage=expected_damage,
        band=_risk_band(expected_damage),
        dominant_signals=dominant,
    )
