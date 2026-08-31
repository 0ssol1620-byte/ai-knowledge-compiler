from __future__ import annotations

import pytest

from akc_quality.semantic_signals import derive_peer_semantic_risk


def test_peer_agreement_stays_low_risk_for_ordinary_text() -> None:
    result = derive_peer_semantic_risk(
        "The service compiles source documents into verified knowledge.",
        "The service compiles source documents into verified knowledge.",
    )

    assert result.peer_available is True
    assert result.cross_model_disagreement == pytest.approx(0.0)
    assert result.assessment.expected_semantic_damage == pytest.approx(0.0)
    assert result.assessment.band.value == "low"


def test_numeric_disagreement_is_not_averaged_away_by_similar_body_text() -> None:
    primary = "N2 firmware version 1.5.3 was released. All other text is unchanged."
    peer = "N2 firmware version 1.5.8 was released. All other text is unchanged."
    result = derive_peer_semantic_risk(primary, peer)

    assert result.text_disagreement < 0.20
    assert result.numeric_disagreement > 0.0
    assert result.cross_model_disagreement >= result.numeric_disagreement
    assert result.critical_token_present is True
    assert result.features.critical_token_sensitivity == pytest.approx(0.85)


def test_date_disagreement_activates_temporal_criticality() -> None:
    result = derive_peer_semantic_risk(
        "The obligation begins on 2026-09-01.",
        "The obligation begins on 2026-10-01.",
        authority_significance=0.8,
    )

    assert result.date_present is True
    assert result.features.temporal_significance == pytest.approx(0.75)
    assert result.features.authority_significance == pytest.approx(0.8)
    assert result.assessment.expected_semantic_damage > 0.0


def test_missing_peer_never_fabricates_cross_model_disagreement() -> None:
    result = derive_peer_semantic_risk(
        "Image-only scan with OCR output 57.2 m/s.",
        None,
        parsing_uncertainty=0.4,
    )

    assert result.peer_available is False
    assert result.agreement is None
    assert result.cross_model_disagreement == pytest.approx(0.0)
    assert result.features.cross_model_disagreement == pytest.approx(0.0)
    assert result.features.parsing_uncertainty == pytest.approx(0.4)
    assert result.assessment.expected_semantic_damage > 0.0


def test_table_and_formula_are_detected_as_semantically_important_roles() -> None:
    result = derive_peer_semantic_risk(
        "| Model | Version |\n|---|---|\n| N2 | 1.5.3 |\n\n$$x^2+y^2=z^2$$",
        "| Model | Version |\n|---|---|\n| N2 | 1.5.8 |\n\n$$x^2+y^2=z^2$$",
    )

    assert result.table_detected is True
    assert result.formula_detected is True
    assert result.features.semantic_role_criticality == pytest.approx(0.85)
    assert result.assessment.expected_semantic_damage >= 0.25


def test_caller_supplied_compiler_consequence_signals_are_preserved() -> None:
    result = derive_peer_semantic_risk(
        "Authority value is 100.",
        "Authority value is 101.",
        entity_criticality=0.6,
        authority_significance=0.9,
        dependency_blast_radius=0.7,
        downstream_consumer_risk=0.8,
    )

    features = result.features
    assert features.entity_criticality == pytest.approx(0.6)
    assert features.authority_significance == pytest.approx(0.9)
    assert features.dependency_blast_radius == pytest.approx(0.7)
    assert features.downstream_consumer_risk == pytest.approx(0.8)
