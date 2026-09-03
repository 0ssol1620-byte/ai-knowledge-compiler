from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest
import runpod_qualification as rq


def test_role_specs_bind_existing_pinned_runtime_inputs() -> None:
    strong = rq.discover_role_spec("strong")
    primary = rq.discover_role_spec("primary")
    assert strong.candidate_id == "mineru-3.4.4-vlm-c1"
    assert primary.candidate_id == "paddleocr-vl-1.6-fastdeploy-c8"
    for spec in (strong, primary):
        assert spec.base_image.startswith("runpod/pytorch@sha256:")
        assert len(spec.base_image_digest) == 71
        assert len(spec.model_artifact_digest) == 71
        assert (rq.REPO / spec.bootstrap_relpath).is_file()
        assert (rq.REPO / spec.prompt_relpath).is_file()


def test_plan_is_spent_only_bounded_and_secret_free() -> None:
    for role in ("strong", "primary"):
        plan = rq.plan(role)
        encoded = json.dumps(plan, sort_keys=True).casefold()
        assert plan["authority"] == "DEVELOPMENT_RUNTIME_QUALIFICATION_AUTHORIZED"
        assert plan["fresh_confirmatory_observation"] is False
        assert plan["sensitive_material_included"] is False
        assert plan["limits"] == {
            "pages": 1,
            "gpu_seconds": 10200,
            "estimated_external_cost_usd": 4.0,
            "max_hourly_rate_usd": 1.05,
        }
        assert "runpod_b" not in encoded
        assert "authorization" not in encoded
        assert "bearer " not in encoded


def test_read_runpod_b_never_transforms_value(tmp_path: Path) -> None:
    secret = "rp_" + "x" * 40
    path = tmp_path / "keys.txt"
    path.write_text(f"Other: no\nRunpod_B: {secret}\n", encoding="utf-8")
    assert rq.read_runpod_b(path) == secret


@pytest.mark.parametrize(
    "contents",
    [
        "Runpod: abcdefghijklmnopqrstuvwxyz\n",
        "Runpod_B: short\n",
        "Runpod_B: " + "x" * 30 + "\nRunpod_B: " + "y" * 30 + "\n",
    ],
)
def test_read_runpod_b_fails_closed(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "keys.txt"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(rq.QualificationRefused):
        rq.read_runpod_b(path)


def test_provider_payload_is_qualification_only_and_bounded() -> None:
    spec = rq.discover_role_spec("strong")
    payload = rq.provider_payload(spec, "ssh-ed25519 AAAATEST paper2")
    assert payload["gpuCount"] == 1
    assert payload["interruptible"] is False
    assert payload["env"]["TAVONEL_R_QUALIFICATION_ONLY"] == "1"
    assert payload["env"]["MINERU_API_MAX_CONCURRENT_REQUESTS"] == "1"
    assert payload["imageName"] == spec.base_image
    assert payload["ports"] == ["22/tcp"]


def test_redacted_json_rejects_secret_bearing_field_names() -> None:
    for value in (
        {"authorization": "anything"},
        {"api_key": "anything"},
        {"nested": {"Runpod_B": "anything"}},
        {"header": "Bearer anything"},
    ):
        with pytest.raises(rq.QualificationRefused):
            rq._redacted_json(value)


def test_provider_stop_and_start_use_pod_lifecycle_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = rq.Provider("rp_" + "x" * 32)
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, payload=None):  # type: ignore[no-untyped-def]
        calls.append((method, path))
        if method == "GET":
            return {"id": "pod123", "desiredStatus": "EXITED"}
        return None

    monkeypatch.setattr(provider, "_request", fake_request)
    provider.stop_pod("pod123")
    provider.start_pod("pod123")
    assert ("POST", "/pods/pod123/stop") in calls
    assert ("POST", "/pods/pod123/start") in calls


def test_pod_billing_is_separate_and_identity_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = rq.Provider("rp_" + "x" * 32)
    paths: list[str] = []

    def fake_request(method: str, path: str, payload=None):  # type: ignore[no-untyped-def]
        assert method == "GET"
        paths.append(path)
        return [{"podId": "pod123", "amount": 0.25, "timeBilledMs": 1_000}]

    monkeypatch.setattr(provider, "_request", fake_request)
    rows = provider.pod_billing("pod123", start_time="2026-08-30T10:00:00+00:00")
    assert rows[0]["amount"] == 0.25
    assert paths and paths[0].startswith("/billing/pods?")
    assert "podId=pod123" in paths[0]
    assert "grouping=podId" in paths[0]


def test_billing_unavailable_never_becomes_zero_spend() -> None:
    class NoBilling:
        def pod_billing(self, pod_id: str, *, start_time: str | None = None):  # type: ignore[no-untyped-def]
            raise rq.QualificationRefused("RunPod provider HTTP failure: 403")

    snapshot = rq._billing_snapshot(
        NoBilling(),  # type: ignore[arg-type]
        {"pod_id": "pod123", "started_at_utc": "2026-08-30T10:00:00+00:00"},
    )
    assert snapshot["status"] == "unavailable"
    assert snapshot["zero_spend_inferred"] is False
    assert "provider_reported_amount_usd" not in snapshot


def test_running_budget_is_cumulative_across_resume() -> None:
    state = {
        "running_started_at_utc": "2026-08-30T10:00:00+00:00",
        "remaining_gpu_seconds": 100.0,
        "gpu_seconds_consumed_local": 20.0,
    }
    elapsed = rq._consume_running_budget(
        state,
        now=rq.datetime.fromisoformat("2026-08-30T10:00:30+00:00"),
    )
    assert elapsed == 30.0
    assert state["remaining_gpu_seconds"] == 70.0
    assert state["gpu_seconds_consumed_local"] == 50.0
    assert state["running_started_at_utc"] is None


def test_endpoint_refresh_replaces_stale_provider_locator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = rq.LocalPaths(
        role_dir=tmp_path,
        key=tmp_path / "id_ed25519",
        public_key=tmp_path / "id_ed25519.pub",
        known_hosts=tmp_path / "known_hosts",
        state=tmp_path / "state.json",
        provider_journal=tmp_path / "provider.jsonl",
    )
    local.known_hosts.write_text("old\n", encoding="utf-8")
    state = {
        "pod_id": "pod123",
        "host": "10.0.0.1",
        "port": 22001,
        "phase": "ssh_ready",
    }

    class FakeProvider:
        def __init__(self, _key: str):
            pass

        def get_pod(self, pod_id: str):  # type: ignore[no-untyped-def]
            assert pod_id == "pod123"
            return {
                "id": pod_id,
                "desiredStatus": "RUNNING",
                "publicIp": "10.0.0.2",
                "portMappings": {"22": 22002},
            }

    removals: list[list[str]] = []
    monkeypatch.setattr(rq, "Provider", FakeProvider)
    monkeypatch.setattr(rq, "read_runpod_b", lambda: "rp_" + "x" * 32)
    monkeypatch.setattr(
        rq.subprocess,
        "run",
        lambda args, **kwargs: removals.append(list(args)) or SimpleNamespace(returncode=0),
    )
    refreshed = rq._refresh_ssh_endpoint(local, state)
    assert refreshed["host"] == "10.0.0.2"
    assert refreshed["port"] == 22002
    assert any("[10.0.0.1]:22001" in command for command in removals)


def test_mineru_runtime_and_model_are_persistent_workspace_assets() -> None:
    bootstrap = (rq.REPO / "infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh").read_text(
        encoding="utf-8"
    )
    provisioner = (rq.REPO / "tools/release/provision_folynta_mineru_recovery_worker.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "/workspace/folynta/mineru-3.4.4-venv" in bootstrap
    assert "/workspace/folynta/models/MinerU2.5-Pro-2605-1.2B" in bootstrap
    assert "PIP_CACHE_DIR" in bootstrap and "HF_HOME" in bootstrap
    assert "--no-cache-dir" not in bootstrap
    assert "/workspace/folynta/mineru-3.4.4-venv/bin/mineru" in provisioner
    assert "/workspace/folynta/models/MinerU2.5-Pro-2605-1.2B" in provisioner
