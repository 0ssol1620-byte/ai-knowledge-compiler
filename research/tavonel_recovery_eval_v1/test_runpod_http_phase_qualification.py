from __future__ import annotations

import json
import subprocess

import pytest

import runpod_http_phase_qualification as v8


def _pass_evidence():
    spec = v8.base.discover_role_spec("strong")
    return {
        "schema": "tavonel.recovery.http_runtime_evidence.v1",
        "status": "PASS",
        "role": "strong",
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


def test_phase_startup_is_fail_fast_and_phase_instrumented():
    script, pins = v8.phase_startup_script("strong")
    for phase in (
        "PREPARED",
        "BOOTSTRAP_STARTED",
        "BOOTSTRAP_DONE",
        "MODEL_MANIFEST_STARTED",
        "MODEL_MANIFEST_DONE",
        "SMOKE_STARTED",
        "SMOKE_DONE",
        "RUNTIME_DIGEST_STARTED",
        "RUNTIME_DIGEST_DONE",
        "EVIDENCE_PASS",
    ):
        assert f"phase {phase}" in script
    assert "'phase':os.environ.get(\"current_phase\",\"UNKNOWN\")" in script
    assert "set +e\n(\nset -euo pipefail\n" in script
    assert pins["startup_script_sha256"] == v8._script_sha(script)


def test_fail_evidence_is_interpreted_before_pass_digest_requirements():
    value = {
        "schema": "tavonel.recovery.http_runtime_evidence.v1",
        "status": "FAIL",
        "role": "strong",
        "phase": "BOOTSTRAP_STARTED",
        "exit_code": 17,
        "fresh_confirmatory_observation": False,
        "sensitive_material_included": False,
    }
    with pytest.raises(v8.RemotePhaseFailure) as captured:
        v8.validate_remote("strong", value)
    assert captured.value.phase == "BOOTSTRAP_STARTED"
    assert captured.value.exit_code == 17


def test_fail_evidence_requires_numeric_exit_code():
    value = {
        "schema": "tavonel.recovery.http_runtime_evidence.v1",
        "status": "FAIL",
        "role": "strong",
        "phase": "SMOKE_STARTED",
        "exit_code": "bad",
        "fresh_confirmatory_observation": False,
        "sensitive_material_included": False,
    }
    with pytest.raises(v8.PhaseQualificationRefused, match="valid exit code"):
        v8.validate_remote("strong", value)


def test_pass_evidence_delegates_to_complete_digest_validator():
    value = _pass_evidence()
    assert v8.validate_remote("strong", value) == value
    value["runtime_sha256"] = "sha256:"
    with pytest.raises(v8.base.SafeQualificationRefused, match="complete sha256"):
        v8.validate_remote("strong", value)


def test_provider_update_only_changes_start_command(monkeypatch):
    observed = {}

    class Provider:
        def _request(self, method, path, payload):
            observed.update({"method": method, "path": path, "payload": payload})
            return {"id": "pod"}

    v8._provider_update(Provider(), "pod-1", "echo phase")
    assert observed == {
        "method": "PATCH",
        "path": "/pods/pod-1",
        "payload": {"dockerStartCmd": ["echo phase"]},
    }


def test_provider_script_hash_requires_single_string_command():
    assert v8._provider_script_hash({"dockerStartCmd": ["abc"]}) == v8._script_sha("abc")
    assert v8._provider_script_hash({"dockerStartCmd": []}) is None
    assert v8._provider_script_hash({"dockerStartCmd": ["a", "b"]}) is None


def test_windows_watchdog_is_spawned_without_a_console(monkeypatch):
    observed = {}

    class Process:
        pid = 1234

    def fake_popen(command, **kwargs):
        observed.update({"command": command, **kwargs})
        return Process()

    monkeypatch.setattr(v8.os, "name", "nt")
    monkeypatch.setattr(v8.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(v8.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(v8.subprocess, "Popen", fake_popen)

    assert v8._spawn_watchdog("strong") == 1234
    assert observed["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert not observed["creationflags"] & getattr(subprocess, "DETACHED_PROCESS", 0)


def test_start_failed_is_terminal_for_the_watchdog():
    assert "start_failed" in v8._TERMINAL_PHASES


def test_phase_failure_receipt_is_claim_ineligible(tmp_path, monkeypatch):
    monkeypatch.setattr(v8, "INCIDENT_ROOT", tmp_path)
    state = {"remaining_gpu_seconds": 100.0}
    error = v8.RemotePhaseFailure("MODEL_MANIFEST_STARTED", 2)
    v8._seal_failure("strong", state, error)
    paths = list(tmp_path.glob("*.json"))
    assert len(paths) == 1
    value = json.loads(paths[0].read_text(encoding="utf-8"))
    assert value["phase"] == "MODEL_MANIFEST_STARTED"
    assert value["exit_code"] == 2
    assert value["scientific_claim_eligible"] is False
    assert value["fresh_confirmatory_observation"] is False
