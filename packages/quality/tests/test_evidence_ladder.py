import pytest
from akc_quality.evidence_ladder import (
    EvidenceLevel,
    EvidencePolicy,
    SelectivePrediction,
    ValidationEvidence,
    risk_coverage_curve,
    verify_evidence,
)


def test_evidence_ladder_fails_closed_on_hard_gate() -> None:
    evidence = ValidationEvidence(
        evidence_id="ev-1",
        level=EvidenceLevel.INDEPENDENTLY_VERIFIED,
        source_ids=("dart", "page-image"),
        source_hashes=("sha256:a", "sha256:b"),
        hard_gate_failures=("critical_numeric_mismatch",),
    )
    decision = verify_evidence(
        evidence,
        EvidencePolicy(
            minimum_level=EvidenceLevel.CROSS_CHECKED,
            minimum_independent_sources=2,
        ),
    )
    assert not decision.accepted
    assert decision.disposition == "escalate"


def test_repair_level_requires_repair_identity() -> None:
    with pytest.raises(ValueError, match="repair attempt"):
        ValidationEvidence(
            evidence_id="ev-2",
            level=EvidenceLevel.REPAIR_REVERIFIED,
            source_ids=("source",),
            source_hashes=("sha256:a",),
        )


def test_risk_coverage_reports_abstention_truthfully() -> None:
    points = risk_coverage_curve(
        [
            SelectivePrediction(0.99, True),
            SelectivePrediction(0.80, False),
            SelectivePrediction(0.40, True),
        ],
        thresholds=(0.0, 0.9, 1.0),
    )
    assert points[0].coverage == 1
    assert points[0].risk == pytest.approx(1 / 3)
    assert points[1].coverage == pytest.approx(1 / 3)
    assert points[1].risk == 0
    assert points[2].accepted_count == 0
    assert points[2].risk is None
