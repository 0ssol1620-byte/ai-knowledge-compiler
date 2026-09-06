from __future__ import annotations

import json

import pytest
import runpod_http_qualification as httpq


@pytest.mark.parametrize("role", ["strong", "primary"])
def test_http_plan_is_self_contained_bounded_and_ssh_free(role: str) -> None:
    value = httpq.plan(role)
    assert value["evidence_class"] == "DEVELOPMENT_RUNTIME_QUALIFICATION_ONLY"
    assert value["fresh_confirmatory_observation"] is False
    assert value["sensitive_material_included"] is False
    assert value["payload_bytes"] < 512_000
    provider = value["provider_request_without_startup_bytes"]
    assert provider["ports"] == ["8001/http"]
    assert provider["volumeInGb"] == 20
    assert "PUBLIC_KEY" not in provider["env"]
    assert provider["env"] == {"TAVONEL_R_QUALIFICATION_ONLY": "1"}
    assert provider["dockerStartCmd"] == ["sha256-bound-self-contained-startup"]
    encoded = json.dumps(value, sort_keys=True).casefold()
    assert "runpod_b" not in encoded
    assert "authorization" not in encoded
    assert "bearer " not in encoded


def test_http_startup_binds_exact_spent_input_and_runtime_sources() -> None:
    script, pins = httpq.startup_script("strong")
    assert len(script.encode("utf-8")) < 512_000
    assert "MINERU_API_MAX_CONCURRENT_REQUESTS=1" in script
    assert "fresh_confirmatory_observation':False" in script
    assert "http.server 8001" in script
    assert "sshd" not in script
    assert pins["startup_script_sha256"].startswith("sha256:")
    assert pins["bootstrap_sha256"].startswith("sha256:")
    assert pins["artifact_manifest_sha256"].startswith("sha256:")
    assert pins["smoke_input_sha256"].startswith("sha256:")

    primary_script, primary_pins = httpq.startup_script("primary")
    assert "PaddleOCR-VL" in primary_script
    assert "--evidence-class smoke" in primary_script
    assert "http://127.0.0.1:8118/v1" in primary_script
    assert "sshd" not in primary_script
    assert primary_pins["startup_script_sha256"].startswith("sha256:")
    assert primary_pins["smoke_input_sha256"] == pins["smoke_input_sha256"]


def test_http_evidence_url_is_runpod_proxy_only() -> None:
    assert (
        httpq.evidence_url("abc_DEF-123")
        == "https://abc_DEF-123-8001.proxy.runpod.net/evidence.json"
    )
    with pytest.raises(httpq.QualificationRefused):
        httpq.evidence_url("bad/name")


def test_remote_evidence_refuses_failure_and_identity_drift() -> None:
    spec = httpq.discover_role_spec("strong")
    good = {
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
    assert httpq._validate_remote_evidence("strong", good) == good
    failed = dict(good, status="FAIL")
    with pytest.raises(httpq.QualificationRefused, match="reported FAIL"):
        httpq._validate_remote_evidence("strong", failed)
    drift = dict(good, model_revision="wrong")
    with pytest.raises(httpq.QualificationRefused, match="identity drifted"):
        httpq._validate_remote_evidence("strong", drift)


@pytest.mark.parametrize("role", ["strong", "primary"])
def test_http_payload_contains_no_secret_bearing_field_or_ssh_material(role: str) -> None:
    payload, _ = httpq.provider_payload(role)
    raw = json.dumps(payload, sort_keys=True).casefold()
    assert "public_key" not in raw
    assert "ssh-" not in raw
    assert "authorization" not in raw
    assert "runpod_b" not in raw
    assert payload["gpuCount"] == 1
    assert payload["interruptible"] is False


def test_failure_receipts_preserve_outer_exit_code_variable() -> None:
    for role in ("strong", "primary"):
        script, _ = httpq.startup_script(role)
        assert "\nrc=$?\nset -e\nif [ $rc -ne 0 ]; then\nexport rc\n" in script
        assert "if [ $rc -ne 0 ]; then\nrc=$?" not in script
