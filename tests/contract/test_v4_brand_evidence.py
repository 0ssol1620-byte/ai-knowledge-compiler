from __future__ import annotations

from copy import deepcopy

import pytest

from infra.release.validate_v4_brand_evidence import (
    ASSET_WEIGHTS,
    ROOT,
    VISUAL_WEIGHTS,
    BrandEvidenceError,
    load_yaml,
    validate_ledger,
    validate_quality_gates,
    validate_repository,
)


def test_repository_v4_brand_evidence_is_measured_and_fail_closed() -> None:
    validate_repository()

    gates = load_yaml(ROOT / "VISUAL_QUALITY_GATES.yml")
    assert gates["current_evidence"]["approval"] is True
    assert gates["current_evidence"]["approval_scope"] == "local_visual_quality_gate_only"
    assert gates["current_evidence"]["visual_score"] >= 90
    assert all(
        score >= 90 for score in gates["current_evidence"]["signature_asset_scores"].values()
    )
    assert gates["current_evidence"]["critical_findings"] == 0
    assert gates["current_evidence"]["high_findings"] == 0
    assert sum(ASSET_WEIGHTS.values()) == 100
    assert sum(VISUAL_WEIGHTS.values()) == 100


def test_quality_gate_rejects_approval_without_measured_current_evidence() -> None:
    gates = deepcopy(load_yaml(ROOT / "VISUAL_QUALITY_GATES.yml"))
    gates["current_evidence"]["approval"] = True
    gates["current_evidence"]["visual_score"] = None

    with pytest.raises(BrandEvidenceError, match="measured visual score"):
        validate_quality_gates(gates)


def test_ledger_rejects_generated_public_proof() -> None:
    ledger = deepcopy(load_yaml(ROOT / "ASSET_REMEDIATION_LEDGER.yml"))
    proof_link = next(asset for asset in ledger["signature_assets"] if asset["asset_id"] == "A03")
    proof_link["license"]["generated_with_ai"] = True

    with pytest.raises(BrandEvidenceError, match="may not use generated evidence"):
        validate_ledger(ledger)
