from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

import runpod_http_safe_qualification as safe


class FakeProvider:
    def __init__(self, pod: dict | None = None):
        self.pod = pod or {
            "id": "pod123",
            "name": "fixture",
            "desiredStatus": "RUNNING",
            "costPerHr": 0.74,
        }
        self.stop_calls: list[str] = []
        self.start_calls: list[str] = []
        self.delete_calls: list[str] = []

    def get_pod(self, pod_id: str):
        if self.pod is None or self.pod.get("id") != pod_id:
            return None
        return dict(self.pod)

    def list_pods(self):
        return [] if self.pod is None else [dict(self.pod)]

    def stop_pod(self, pod_id: str):
        self.stop_calls.append(pod_id)
        assert self.pod is not None
        self.pod["desiredStatus"] = "STOPPED"

    def start_pod(self, pod_id: str):
        self.start_calls.append(pod_id)
        assert self.pod is not None
        self.pod["desiredStatus"] = "RUNNING"

    def delete_pod(self, pod_id: str):
        self.delete_calls.append(pod_id)
        self.pod = None

    def pod_billing(self, pod_id: str, *, start_time: str | None = None):
        return [{"podId": pod_id, "amount": 0.12, "timeBilledMs": 30_000}]


def _state(*, phase: str = "provider_running", remaining: float = 600.0):
    now = datetime.now(UTC)
    return {
        "schema": "tavonel.recovery.http_safe_qualification_state.v1",
        "role": "strong",
        "phase": phase,
        "pod_id": "pod123",
        "hourly_rate_usd": 0.74,
        "started_at_utc": (now - timedelta(seconds=60)).isoformat(),
        "running_started_at_utc": (now - timedelta(seconds=10)).isoformat(),
        "hard_deadline_utc": (now + timedelta(seconds=remaining)).isoformat(),
        "remaining_gpu_seconds": remaining,
        "gpu_seconds_consumed_local": 0.0,
        "evidence_url": safe.evidence_url("pod123"),
        "startup_inputs": {"smoke_input_sha256": "sha256:" + "a" * 64},
        "provider_stopped": False,
        "provider_deleted": False,
        "fresh_confirmatory_observation": False,
    }


@pytest.mark.parametrize("role", ["strong", "primary"])
def test_plan_is_ssh_free_persistent_and_bounded(role: str):
    plan = safe.plan(role)
    provider = plan["provider_request_without_startup_bytes"]
    assert provider["ports"] == ["8001/http"]
    assert provider["volumeMountPath"] == "/workspace"
    assert provider["volumeInGb"] == 20
    assert plan["failure_default"] == "stop_preserve_workspace_before_delete"
    assert plan["runtime_persistence"]["resume_supported"] is True
    assert plan["fresh_confirmatory_observation"] is False
    assert plan["sensitive_material_included"] is False
    raw = json.dumps(plan, sort_keys=True).casefold()
    assert "ssh-" not in raw
    assert "public_key" not in raw
    assert "authorization" not in raw
    assert "bearer " not in raw


def test_strong_startup_uses_persistent_runtime_and_no_fixed_python():
    script, _ = safe.safe_startup_script("strong")
    assert safe.STRONG_VENV + "/bin/mineru" in script
    assert safe.STRONG_MODEL in script
    assert "/usr/local/bin/mineru" not in script
    assert "/usr/bin/python3.11" not in script
    assert "command -v python3 || command -v python" in script
    assert "rm -f $ROOT/http/evidence.json" in script
    assert "sshd" not in script


def test_primary_startup_uses_persistent_runtime_and_no_fixed_python():
    script, _ = safe.safe_startup_script("primary")
    assert safe.PRIMARY_VENV in script
    assert "/usr/bin/python3.11" not in script
    assert "command -v python3 || command -v python" in script
    assert "rm -f $ROOT/http/evidence.json" in script
    assert "sshd" not in script


def test_stop_preserves_pod_and_records_real_pod_billing(tmp_path, monkeypatch):
    monkeypatch.setattr(safe, "PRIVATE_ROOT", tmp_path / "private")
    provider = FakeProvider()
    state = _state()
    safe._write_state("strong", state)
    billing = safe._stop_preserving_cache(
        "strong",
        state,
        provider,
        phase="hard_deadline_stopped",
        event="fixture_stop",
    )
    assert provider.stop_calls == ["pod123"]
    assert provider.delete_calls == []
    assert billing["status"] == "available"
    assert billing["provider_reported_amount_usd"] == pytest.approx(0.12)
    saved = safe._read_state("strong")
    assert saved["provider_stopped"] is True
    assert saved["provider_deleted"] is False
    assert saved["remaining_gpu_seconds"] < 600.0


def test_resume_reuses_same_pod_and_never_resets_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(safe, "PRIVATE_ROOT", tmp_path / "private")
    state = _state(phase="hard_deadline_stopped", remaining=321.0)
    state["running_started_at_utc"] = None
    state["provider_stopped"] = True
    safe._write_state("strong", state)
    provider = FakeProvider()
    provider.pod["desiredStatus"] = "STOPPED"
    monkeypatch.setattr(safe, "Provider", lambda _token: provider)
    monkeypatch.setattr(safe, "read_runpod_b", lambda: "fixture-token")
    monkeypatch.setattr(safe, "authorize_qualification", lambda: None)
    result = safe.resume("strong")
    assert provider.start_calls == ["pod123"]
    assert result["pod_id"] == "pod123"
    assert result["remaining_gpu_seconds"] == pytest.approx(321.0)
    saved = safe._read_state("strong")
    assert saved["remaining_gpu_seconds"] == pytest.approx(321.0)
    deadline = safe._parse_time(saved["hard_deadline_utc"], label="deadline")
    started = safe._parse_time(saved["running_started_at_utc"], label="started")
    assert 319.0 <= (deadline - started).total_seconds() <= 322.0


def test_non_resumable_phase_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(safe, "PRIVATE_ROOT", tmp_path / "private")
    safe._write_state("strong", _state(phase="provider_running"))
    monkeypatch.setattr(safe, "authorize_qualification", lambda: None)
    with pytest.raises(safe.SafeQualificationRefused, match="not resumable"):
        safe.resume("strong")


def test_watchdog_exits_without_delete_for_already_stopped_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(safe, "PRIVATE_ROOT", tmp_path / "private")
    state = _state(phase="hard_deadline_stopped")
    state["provider_stopped"] = True
    safe._write_state("strong", state)
    assert safe.watchdog("strong") == 0
