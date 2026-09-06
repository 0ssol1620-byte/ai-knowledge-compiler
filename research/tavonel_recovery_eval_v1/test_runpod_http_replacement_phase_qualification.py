from __future__ import annotations

import json

import pytest

import runpod_http_replacement_phase_qualification as v9


def test_v9_payload_uses_v8_phase_startup_and_only_changes_attempt_identity():
    payload, pins = v9.provider_payload("strong")
    script, expected = v9.v8.phase_startup_script("strong")
    assert payload["dockerStartCmd"] == [script]
    assert payload["name"].endswith(v9.ATTEMPT)
    assert pins == expected
    assert payload["gpuTypeIds"] == ["NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 5090"]
    assert payload["gpuTypePriority"] == "availability"


def test_v9_activation_uses_phase_validator_and_restores_shared_modules():
    old_attempt = v9.base.ATTEMPT
    old_private = v9.base.PRIVATE_ROOT
    old_payload = v9.base.provider_payload
    old_fetch = v9.legacy_http._fetch_evidence
    old_validate = v9.legacy_http._validate_remote_evidence
    old_pins = v9.v6.controller_pins
    old_watchdog = v9.v6._watchdog_command
    with v9._activated():
        assert v9.base.ATTEMPT == v9.ATTEMPT
        assert v9.base.PRIVATE_ROOT == v9.PRIVATE_ROOT
        assert v9.base.provider_payload is v9.provider_payload
        assert v9.legacy_http._fetch_evidence is v9.v7._fetch_evidence
        assert v9.legacy_http._validate_remote_evidence is v9.v8.validate_remote
        assert v9.v6.controller_pins is v9.controller_pins
        assert v9.v6._watchdog_command is v9._watchdog_command
    assert v9.base.ATTEMPT == old_attempt
    assert v9.base.PRIVATE_ROOT == old_private
    assert v9.base.provider_payload is old_payload
    assert v9.legacy_http._fetch_evidence is old_fetch
    assert v9.legacy_http._validate_remote_evidence is old_validate
    assert v9.v6.controller_pins is old_pins
    assert v9.v6._watchdog_command is old_watchdog


def test_v9_predecessor_budget_requires_normalized_v8_incident(tmp_path, monkeypatch):
    incident_root = tmp_path / "incidents"
    incident_root.mkdir()
    incident = {
        "schema": "tavonel.recovery.runtime_qualification_operational_incident.v1",
        "attempt": v9.v8.ATTEMPT,
        "role": "strong",
        "state": "START_FAILED_PROVIDER_CAPACITY",
        "provider_http_status": 500,
        "provider_stopped": True,
        "gpu_budget_debited_for_failed_start": False,
        "new_pod_created": False,
        "scientific_claim_eligible": False,
        "successor": v9.ATTEMPT,
        "remaining_gpu_seconds": 6781.0,
    }
    (incident_root / "incident.json").write_text(json.dumps(incident), encoding="utf-8")
    monkeypatch.setattr(v9, "V8_INCIDENT_ROOT", incident_root)
    monkeypatch.setattr(
        v9.v8,
        "_read_state",
        lambda role: {
            "role": role,
            "phase": "start_failed",
            "provider_stopped": True,
            "remaining_gpu_seconds": 6781.0,
        },
    )
    assert v9.predecessor_budget_seconds("strong") == 6781.0


def test_v9_predecessor_budget_refuses_wrong_predecessor_phase(tmp_path, monkeypatch):
    incident_root = tmp_path / "incidents"
    incident_root.mkdir()
    incident = {
        "schema": "tavonel.recovery.runtime_qualification_operational_incident.v1",
        "attempt": v9.v8.ATTEMPT,
        "role": "strong",
        "state": "START_FAILED_PROVIDER_CAPACITY",
        "provider_http_status": 500,
        "provider_stopped": True,
        "gpu_budget_debited_for_failed_start": False,
        "new_pod_created": False,
        "scientific_claim_eligible": False,
        "successor": v9.ATTEMPT,
        "remaining_gpu_seconds": 6781.0,
    }
    (incident_root / "incident.json").write_text(json.dumps(incident), encoding="utf-8")
    monkeypatch.setattr(v9, "V8_INCIDENT_ROOT", incident_root)
    monkeypatch.setattr(
        v9.v8,
        "_read_state",
        lambda role: {
            "role": role,
            "phase": "provider_running",
            "provider_stopped": False,
            "remaining_gpu_seconds": 6781.0,
        },
    )
    with pytest.raises(v9.base.SafeQualificationRefused, match="recorded start failure"):
        v9.predecessor_budget_seconds("strong")


def test_v9_phase_failure_receipt_preserves_negative_result(tmp_path, monkeypatch):
    monkeypatch.setattr(v9, "HERE", tmp_path)
    monkeypatch.setattr(
        v9.base,
        "_read_state",
        lambda role: {
            "role": role,
            "provider_stopped": True,
            "remaining_gpu_seconds": 6000.0,
        },
    )
    error = v9.v8.RemotePhaseFailure("BOOTSTRAP_STARTED", 2)
    v9._seal_phase_failure("strong", error)
    paths = list((tmp_path / "receipts" / "runtime-qualification-incidents").glob("*.json"))
    assert len(paths) == 1
    value = json.loads(paths[0].read_text(encoding="utf-8"))
    assert value["phase"] == "BOOTSTRAP_STARTED"
    assert value["exit_code"] == 2
    assert value["scientific_claim_eligible"] is False
    assert value["fresh_confirmatory_observation"] is False