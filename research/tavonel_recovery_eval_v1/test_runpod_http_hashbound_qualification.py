from __future__ import annotations

import hashlib

import runpod_http_hashbound_qualification as v4


def test_v4_binds_hash_to_final_transformed_startup_bytes():
    for role in ("strong", "primary"):
        script, pins = v4.safe_startup_script(role)
        observed = "sha256:" + hashlib.sha256(script.encode("utf-8")).hexdigest()
        assert pins["startup_script_sha256"] == observed
        assert "/usr/bin/python3.11" not in script
        assert "sshd" not in script


def test_v4_uses_new_attempt_namespace_and_deterministic_pod_name():
    assert v4.ATTEMPT == "v4-hashbound-persisted-safe"
    assert v4.PRIVATE_ROOT.name == v4.ATTEMPT
    for role in ("strong", "primary"):
        payload, pins = v4.provider_payload(role)
        assert v4.ATTEMPT in payload["name"]
        assert payload["ports"] == ["8001/http"]
        assert payload["volumeMountPath"] == "/workspace"
        script = payload["dockerStartCmd"][0]
        assert pins["startup_script_sha256"] == (
            "sha256:" + hashlib.sha256(script.encode("utf-8")).hexdigest()
        )


def test_v4_plan_carries_hashbound_startup_and_stop_resume_contract():
    for role in ("strong", "primary"):
        plan = v4.plan(role)
        assert plan["startup_inputs"]["startup_script_sha256"].startswith("sha256:")
        assert plan["failure_default"] == "stop_preserve_workspace_before_delete"
        assert plan["runtime_persistence"]["resume_supported"] is True
        assert plan["fresh_confirmatory_observation"] is False
        assert plan["sensitive_material_included"] is False
