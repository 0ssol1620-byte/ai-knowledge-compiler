from __future__ import annotations

import json
from pathlib import Path

from tests.load.validate_profiles import (
    EXPECTED_DIMENSIONS,
    emit_not_run,
    validate_catalog,
    validate_evidence,
)


def test_catalog_is_exact_and_guarded() -> None:
    assert validate_catalog() == []
    catalog = json.loads(Path("tests/load/profiles.json").read_text(encoding="utf-8"))
    assert set(catalog["profiles"]) == set(EXPECTED_DIMENSIONS)
    assert catalog["safety"] == {
        "required_confirmation_env": "AKC_LOAD_CONFIRM",
        "required_confirmation": "NONPRODUCTION_LOAD_ONLY",
        "remote_https_required": True,
        "exact_origin_allowlist_required": True,
        "customer_data_permitted": False,
        "synthetic_fixtures_only": True,
        "automatic_production_execution": False,
        "production_evidence_permitted": False,
        "default_execution": "disabled",
    }


def test_not_run_receipt_is_honest_but_never_gate_admissible(tmp_path: Path) -> None:
    receipt = tmp_path / "not-run.json"
    emit_not_run("collection_resume_10gib", receipt)
    errors = validate_evidence(receipt)
    assert "execution.status: only passed receipts are gate-admissible" in errors
    assert "target.revision_verified: independent revision evidence is required" in errors
    assert any(error.startswith("observations: missing required metrics") for error in errors)
    assert "cleanup: mutating profiles require a completed cleanup receipt" in errors


def test_receipt_cannot_claim_production_or_close_a_release_gate(tmp_path: Path) -> None:
    receipt = tmp_path / "tampered.json"
    emit_not_run("processing_ui_1000_pages", receipt)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["target"]["production"] = True
    payload["declarations"]["release_gate_closed"] = True
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    errors = validate_evidence(receipt)
    assert any("target.production" in error for error in errors)
    assert any("declarations" in error for error in errors)


def test_complete_nonproduction_receipt_is_admissible_but_not_a_release_claim(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "passed.json"
    emit_not_run("graph_5000_nodes", receipt)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    digest = "sha256:" + ("a" * 64)
    payload["harness_revision"] = "b" * 40
    payload["target"].update(
        {
            "environment": "performance",
            "deployment_revision": "c" * 40,
            "revision_verified": True,
            "revision_evidence_sha256": digest,
            "origin_allowlist_match": True,
            "origin_allowlist_sha256": digest,
        }
    )
    payload["execution"] = {
        "status": "passed",
        "started_at": "2026-07-31T00:00:00Z",
        "finished_at": "2026-07-31T00:01:00Z",
        "exit_code": 0,
        "command_sha256": digest,
        "raw_summary_sha256": digest,
    }
    required = json.loads(Path("tests/load/profiles.json").read_text(encoding="utf-8"))["profiles"][
        "graph_5000_nodes"
    ]["required_evidence_metrics"]
    payload["observations"] = [
        {
            "name": name,
            "value": 0,
            "unit": "count",
            "threshold": 0,
            "passed": True,
            "source_sha256": digest,
        }
        for name in required
    ]
    payload["acceptance"] = {
        "all_required_metrics_present": True,
        "all_thresholds_passed": True,
    }
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_evidence(receipt) == []
    assert payload["declarations"]["production_slo_proven"] is False
    assert payload["declarations"]["release_gate_closed"] is False
