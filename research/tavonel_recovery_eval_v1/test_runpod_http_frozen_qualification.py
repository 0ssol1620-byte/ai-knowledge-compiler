from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import runpod_http_frozen_qualification as v6


def _fixture_state(role: str = "strong") -> dict:
    now = datetime.now(UTC)
    return {
        "schema": "tavonel.recovery.http_safe_qualification_state.v1",
        "role": role,
        "phase": "provider_running",
        "pod_id": "pod-v6",
        "hourly_rate_usd": 0.74,
        "started_at_utc": now.isoformat(),
        "running_started_at_utc": now.isoformat(),
        "hard_deadline_utc": (now + timedelta(minutes=5)).isoformat(),
        "remaining_gpu_seconds": 300.0,
        "gpu_seconds_consumed_local": 0.0,
        "evidence_url": v6.base.evidence_url("pod-v6"),
        "startup_inputs": {"startup_script_sha256": "sha256:" + "a" * 64},
        "provider_stopped": False,
        "provider_deleted": False,
        "fresh_confirmatory_observation": False,
    }


def test_plan_binds_all_controller_sources_and_final_startup_bytes():
    for role in ("strong", "primary"):
        plan = v6.plan(role)
        pins = plan["controller_source_sha256"]
        assert set(pins) == {
            "frozen_controller_entrypoint_sha256",
            "safe_controller_snapshot_sha256",
            "legacy_http_validator_sha256",
            "runpod_provider_module_sha256",
            "runtime_attestation_module_sha256",
        }
        assert all(value.startswith("sha256:") for value in pins.values())
        assert plan["watchdog_entrypoint_bound"] is True
        assert plan["watchdog_spawn_deferred_until_controller_pins_written"] is True
        payload, startup = v6.base.provider_payload(role)
        script = payload["dockerStartCmd"][0]
        assert startup["startup_script_sha256"] == (
            "sha256:" + hashlib.sha256(script.encode("utf-8")).hexdigest()
        )
        assert payload["ports"] == ["8001/http"]
        assert "/usr/bin/python3.11" not in script
        assert "sshd" not in script


def test_watchdog_command_is_bound_to_v6_entrypoint():
    command = v6._watchdog_command("strong")
    assert Path(command[1]).resolve() == Path(v6.__file__).resolve()
    assert command[-2:] == ["--role", "strong"]


def test_start_writes_controller_pins_before_attaching_watchdog(tmp_path, monkeypatch):
    monkeypatch.setattr(v6.base, "PRIVATE_ROOT", tmp_path / "private")
    observed: dict[str, object] = {}

    def fake_base_start(role: str):
        v6.base._write_state(role, _fixture_state(role))
        return {"role": role, "phase": "provider_running", "pod_id": "pod-v6"}

    def fake_spawn(role: str) -> int:
        state = v6.base._read_state(role)
        observed["pins_present_before_spawn"] = isinstance(state.get("controller_source_sha256"), dict)
        observed["entrypoint_present_before_spawn"] = bool(state.get("watchdog_entrypoint_sha256"))
        return 4321

    monkeypatch.setattr(v6, "_BASE_START", fake_base_start)
    monkeypatch.setattr(v6, "_spawn_attested_watchdog", fake_spawn)
    result = v6.start("strong")
    assert observed == {
        "pins_present_before_spawn": True,
        "entrypoint_present_before_spawn": True,
    }
    assert result["watchdog_pid"] == 4321
    state = v6.base._read_state("strong")
    assert state["watchdog_pid"] == 4321
    assert state["controller_source_sha256"] == v6.controller_pins()


def test_advance_detects_controller_drift_and_fail_closes(tmp_path, monkeypatch):
    monkeypatch.setattr(v6.base, "PRIVATE_ROOT", tmp_path / "private")
    state = _fixture_state()
    state["controller_source_sha256"] = {"wrong": "sha256:" + "0" * 64}
    state["watchdog_entrypoint_sha256"] = "sha256:" + "0" * 64
    v6.base._write_state("strong", state)
    stopped: list[str] = []
    monkeypatch.setattr(v6, "_stop_for_controller_drift", lambda role, _state: stopped.append(role))
    with pytest.raises(v6.base.SafeQualificationRefused, match="source drifted"):
        v6.advance("strong")
    assert stopped == ["strong"]


def test_resume_attaches_new_v6_watchdog_without_resetting_state(tmp_path, monkeypatch):
    monkeypatch.setattr(v6.base, "PRIVATE_ROOT", tmp_path / "private")
    state = _fixture_state()
    state["phase"] = "hard_deadline_stopped"
    state["provider_stopped"] = True
    state["controller_source_sha256"] = v6.controller_pins()
    state["watchdog_entrypoint_sha256"] = v6.controller_pins()["frozen_controller_entrypoint_sha256"]
    v6.base._write_state("strong", state)

    def fake_resume(role: str):
        current = v6.base._read_state(role)
        current["phase"] = "provider_running"
        current["provider_stopped"] = False
        v6.base._write_state(role, current)
        return {"role": role, "phase": "provider_running", "remaining_gpu_seconds": current["remaining_gpu_seconds"]}

    monkeypatch.setattr(v6, "_BASE_RESUME", fake_resume)
    monkeypatch.setattr(v6, "_spawn_attested_watchdog", lambda _role: 9876)
    result = v6.resume("strong")
    assert result["watchdog_pid"] == 9876
    assert result["watchdog_entrypoint_bound"] is True
    assert v6.base._read_state("strong")["watchdog_pid"] == 9876
