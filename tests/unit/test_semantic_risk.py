from __future__ import annotations

import pytest

from akc_cir.parser_verification import ParserCapability, select_verification_parsers
from akc_cir.semantic_risk import (
    SemanticRiskBand,
    SemanticRiskFeatures,
    assess_semantic_risk,
)

PRIMARY = ParserCapability("paddle", "paddle", estimated_gpu_seconds=3, estimated_cost_usd=0.01)
STRONG = ParserCapability(
    "mineru",
    "mineru",
    estimated_gpu_seconds=35,
    estimated_cost_usd=0.07,
    supports_visual=True,
)


def test_low_value_courtesy_text_can_remain_low_risk_despite_parser_uncertainty() -> None:
    assessment = assess_semantic_risk(
        SemanticRiskFeatures(
            parser_error_probability=0.25,
            parsing_uncertainty=0.25,
            cross_model_disagreement=0.10,
            critical_token_sensitivity=0.02,
            semantic_role_criticality=0.05,
            entity_criticality=0.02,
            temporal_significance=0.01,
            authority_significance=0.01,
            dependency_blast_radius=0.02,
            downstream_consumer_risk=0.03,
        )
    )

    assert assessment.band is SemanticRiskBand.LOW
    assert assessment.expected_semantic_damage < 0.25
    assert assessment.parser_error_probability > 0.4
    assert assessment.downstream_semantic_impact < 0.15


def test_high_confidence_date_disagreement_becomes_critical_semantic_risk() -> None:
    assessment = assess_semantic_risk(
        SemanticRiskFeatures(
            parser_error_probability=0.05,
            parsing_uncertainty=0.05,
            cross_model_disagreement=0.90,
            critical_token_sensitivity=0.95,
            semantic_role_criticality=0.95,
            entity_criticality=0.70,
            temporal_significance=1.00,
            authority_significance=0.90,
            dependency_blast_radius=0.80,
            downstream_consumer_risk=0.90,
        )
    )

    assert assessment.band is SemanticRiskBand.CRITICAL
    assert assessment.expected_semantic_damage > 0.85
    assert "temporal_significance" in assessment.dominant_signals
    assert "cross_model_disagreement" in assessment.dominant_signals


def test_parser_routing_prefers_semantic_risk_over_legacy_scalar() -> None:
    assessment = assess_semantic_risk(
        SemanticRiskFeatures(
            parser_error_probability=0.05,
            cross_model_disagreement=0.90,
            critical_token_sensitivity=0.95,
            temporal_significance=1.00,
            semantic_role_criticality=0.95,
            dependency_blast_radius=0.80,
            downstream_consumer_risk=0.90,
        )
    )

    decision = select_verification_parsers(
        PRIMARY,
        [STRONG],
        risk=0.01,
        uncertainty=0.05,
        semantic_risk=assessment,
        has_table=True,
    )

    assert decision.multi_parser
    assert decision.risk_source == "semantic_risk_engine"
    assert decision.effective_risk == assessment.expected_semantic_damage
    assert decision.run_visual_round_trip


def test_legacy_scalar_route_remains_explicit_during_migration() -> None:
    decision = select_verification_parsers(PRIMARY, [STRONG], risk=0.10, uncertainty=0.10)

    assert decision.risk_source == "legacy_scalar"
    assert decision.effective_risk == 0.10
    assert not decision.multi_parser


def test_feature_values_are_fail_closed_to_unit_interval() -> None:
    with pytest.raises(ValueError, match="temporal_significance"):
        SemanticRiskFeatures(temporal_significance=1.01)
