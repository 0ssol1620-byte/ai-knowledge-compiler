from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import runpod_http_integrity_qualification as v7


def _valid_evidence(role: str) -> dict:
    spec = v7.legacy_http.discover_role_spec(role)
    return {
        "schema": "tavonel.recovery.http_runtime_evidence.v1",
        "status": "PASS",
        "role": role,
        "model_id": spec.model_id,
        "model_revision": spec.model_revision,
        "base_image": spec.base_image,
        "runtime_sha256": "sha256:" + "a" * 64,
        "model_manifest_sha256": spec.model_artifact_digest,
        "smoke_output_sha256": "sha256:" + "b" * 64,
        "gpu": "NVIDIA GeForce RTX 4090",
        "fresh_confirmatory_observation": False,
        "sensitive_material_included": False,
    }


def test_v7_fail_closes_success_subshell_and_requires_complete_digests():
    for role in ("strong", "primary"):
        payload, startup = v7.provider_payload(role)
        script = payload["dockerStartCmd"][0]
        assert "set +e\n(\nset -euo pipefail\n" in script
        assert "test -s $ROOT/receipts/runtime-identity.json" in script
        assert script.count("grep -Eq '^[0-9a-f]{64}$'") == 3
        assert startup["startup_script_sha256"] == (
            "sha256:" + hashlib.sha256(script.encode()).hexdigest()
        )
        assert payload["name"].endswith(v7.ATTEMPT)


@pytest.mark.parametrize(
    "field,bad_value",
    (
        ("runtime_sha256", "sha256:"),
        ("runtime_sha256", "sha256:" + "A" * 64),
        ("model_manifest_sha256", "sha256:" + "0" * 63),
        ("smoke_output_sha256", "not-a-digest"),
    ),
)
def test_v7_rejects_incomplete_or_noncanonical_digest_fields(field: str, bad_value: str):
    value = _valid_evidence("strong")
    value[field] = bad_value
    with pytest.raises(v7.base.SafeQualificationRefused, match="complete sha256 digest"):
        v7._validate_remote_evidence("strong", value)


def test_v7_accepts_complete_digest_shape_before_legacy_identity_checks():
    value = _valid_evidence("strong")
    assert v7._validate_remote_evidence("strong", value) == value


def test_v7_plan_self_binds_new_watchdog_and_controller_entrypoint():
    plan = v7.plan("strong")
    expected = "sha256:" + hashlib.sha256(Path(v7.__file__).read_bytes()).hexdigest()
    assert plan["attempt"] == v7.ATTEMPT
    assert plan["success_subshell_fail_fast"] is True
    assert plan["complete_digest_validation"] is True
    assert plan["controller_source_sha256"]["frozen_controller_entrypoint_sha256"] == expected
    assert Path(plan["watchdog_entrypoint_path"]).resolve() == Path(v7.__file__).resolve()


def test_v7_fetch_uses_explicit_proxy_client_identity(monkeypatch):
    observed = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({"schema": "fixture"}).encode()

    def fake_urlopen(request, timeout):
        observed["user_agent"] = request.get_header("User-agent")
        observed["cache_control"] = request.get_header("Cache-control")
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(v7.urllib.request, "urlopen", fake_urlopen)
    value = v7._fetch_evidence("https://pod-v7-8001.proxy.runpod.net/evidence.json")
    assert value == {"schema": "fixture"}
    assert observed == {
        "user_agent": "tavonel-runtime-qualification/1",
        "cache_control": "no-cache",
        "timeout": 20,
    }


def test_v7_activation_restores_shared_modules_after_action():
    old_attempt = v7.base.ATTEMPT
    old_private = v7.base.PRIVATE_ROOT
    old_payload = v7.base.provider_payload
    old_fetch = v7.legacy_http._fetch_evidence
    old_validate = v7.legacy_http._validate_remote_evidence
    old_pins = v7.v6.controller_pins
    old_watchdog = v7.v6._watchdog_command
    with v7._activated():
        assert v7.base.ATTEMPT == v7.ATTEMPT
        assert v7.base.PRIVATE_ROOT == v7.PRIVATE_ROOT
        assert v7.base.provider_payload is v7.provider_payload
        assert v7.legacy_http._fetch_evidence is v7._fetch_evidence
        assert v7.legacy_http._validate_remote_evidence is v7._validate_remote_evidence
        assert v7.v6.controller_pins is v7.controller_pins
        assert v7.v6._watchdog_command is v7._watchdog_command
    assert v7.base.ATTEMPT == old_attempt
    assert v7.base.PRIVATE_ROOT == old_private
    assert v7.base.provider_payload is old_payload
    assert v7.legacy_http._fetch_evidence is old_fetch
    assert v7.legacy_http._validate_remote_evidence is old_validate
    assert v7.v6.controller_pins is old_pins
    assert v7.v6._watchdog_command is old_watchdog


def test_v7_strong_successor_budget_reconciles_with_v6_incident(tmp_path, monkeypatch):
    v6_root = tmp_path / "v6-frozen-controller"
    role_root = v6_root / "strong"
    role_root.mkdir(parents=True)
    incident = tmp_path / "incident.json"
    remaining = 7639.5
    (role_root / "state.json").write_text(
        json.dumps(
            {
                "phase": "invalid_runtime_hash_stopped",
                "provider_stopped": True,
                "remaining_gpu_seconds": remaining,
            }
        ),
        encoding="utf-8",
    )
    incident.write_text(
        json.dumps(
            {
                "state": "INVALID_INSTRUMENT",
                "role": "strong",
                "successor": v7.ATTEMPT,
                "remaining_gpu_seconds": remaining,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(v7, "V6_PRIVATE_ROOT", v6_root)
    monkeypatch.setattr(v7, "V6_INCIDENT", incident)
    assert v7._successor_budget_seconds("strong") == remaining
    assert v7._successor_budget_seconds("primary") == float(v7.base.MAX_RUNTIME_SECONDS)


def test_v7_strong_successor_budget_refuses_mismatched_incident(tmp_path, monkeypatch):
    v6_root = tmp_path / "v6-frozen-controller"
    role_root = v6_root / "strong"
    role_root.mkdir(parents=True)
    incident = tmp_path / "incident.json"
    (role_root / "state.json").write_text(
        json.dumps(
            {
                "phase": "invalid_runtime_hash_stopped",
                "provider_stopped": True,
                "remaining_gpu_seconds": 100.0,
            }
        ),
        encoding="utf-8",
    )
    incident.write_text(
        json.dumps(
            {
                "state": "INVALID_INSTRUMENT",
                "role": "strong",
                "successor": v7.ATTEMPT,
                "remaining_gpu_seconds": 99.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(v7, "V6_PRIVATE_ROOT", v6_root)
    monkeypatch.setattr(v7, "V6_INCIDENT", incident)
    with pytest.raises(v7.base.SafeQualificationRefused, match="does not reconcile"):
        v7._successor_budget_seconds("strong")


def test_v7_start_temporarily_applies_successor_budget_and_restores_global(monkeypatch):
    observed = {}
    state = {}

    monkeypatch.setattr(v7, "_successor_budget_seconds", lambda role: 321.0)

    def fake_start(role):
        observed["during_start_budget"] = v7.base.MAX_RUNTIME_SECONDS
        return {"role": role, "phase": "provider_running"}

    monkeypatch.setattr(v7.v6, "start", fake_start)
    monkeypatch.setattr(v7.base, "_read_state", lambda role: state)
    monkeypatch.setattr(v7.base, "_write_state", lambda role, value: None)
    original = v7.base.MAX_RUNTIME_SECONDS
    result = v7.start("strong")
    assert observed["during_start_budget"] == 321.0
    assert v7.base.MAX_RUNTIME_SECONDS == original
    assert state["successor_gpu_budget_seconds"] == 321.0
    assert state["gpu_budget_reset_by_instrument_repair"] is False
    assert result["successor_gpu_budget_seconds"] == 321.0