from __future__ import annotations

import pytest
import runpod_phase_diagnostic as d


def test_strong_startup_exposes_frozen_bootstrap_phases():
    script, pins = d._startup("strong")
    spec = d.discover_role_spec("strong")
    raw = (d.REPO / spec.bootstrap_relpath).read_text(encoding="utf-8")
    decorated = d._decorate_strong(raw)
    for phase in (
        "STARTED",
        "APT_DONE",
        "TORCH_INSTALL_STARTED",
        "MINERU_CLONE_STARTED",
        "MINERU_DEPS_STARTED",
        "MODEL_DOWNLOAD_STARTED",
        "RECEIPTS_STARTED",
        "BOOTSTRAP_DONE",
        "DIAGNOSTIC_COMPLETE",
    ):
        if phase in {"STARTED", "APT_DONE", "DIAGNOSTIC_COMPLETE"}:
            assert f"phase {phase}" in script
        else:
            assert f"phase {phase}" in decorated
    assert pins["startup_script_sha256"].startswith("sha256:")


def test_primary_startup_exposes_runtime_model_service_and_artifact_phases():
    script, pins = d._startup("primary")
    spec = d.discover_role_spec("primary")
    raw = (d.REPO / spec.bootstrap_relpath).read_text(encoding="utf-8")
    decorated = d._decorate_primary(raw)
    for phase in (
        "STARTED",
        "APT_DONE",
        "RUNTIME_INSTALL_STARTED",
        "RUNTIME_INSTALL_DONE",
        "MODEL_DOWNLOAD_STARTED",
        "SERVICE_START_STARTED",
        "SERVICE_READY",
        "ARTIFACT_VERIFY_STARTED",
        "ARTIFACT_VERIFY_DONE",
        "BOOTSTRAP_DONE",
        "DIAGNOSTIC_COMPLETE",
    ):
        if phase in {"STARTED", "APT_DONE", "DIAGNOSTIC_COMPLETE"}:
            assert f"phase {phase}" in script
        else:
            assert f"phase {phase}" in decorated
    assert pins["smoke_input_sha256"].startswith("sha256:")


def test_plans_are_development_only_secret_free_and_bounded():
    for role in ("strong", "primary"):
        plan = d.plan(role)
        assert plan["evidence_class"] == "DEVELOPMENT_DIAGNOSTIC_ONLY"
        assert plan["fresh_confirmatory_observation"] is False
        assert plan["sensitive_material_included"] is False
        assert plan["max_runtime_seconds"] == 2700
        assert plan["max_external_cost_usd"] == 1.0
        assert plan["payload_bytes"] < 512_000
        assert plan["provider_request_without_startup_bytes"]["dockerStartCmd"] == ["[REDACTED]"]


def test_phase_function_never_serializes_secret_material():
    text = d._phase_function("strong")
    folded = text.casefold()
    assert "runpod_b" not in folded
    assert "authorization" not in folded
    assert "bearer " not in folded
    assert "fresh_confirmatory_observation\":False" in text
    assert "sensitive_material_included\":False" in text


def test_replace_once_rejects_missing_or_ambiguous_anchor():
    with pytest.raises(d.QualificationRefused):
        d._replace_once("abc", "z", "x", label="missing")
    with pytest.raises(d.QualificationRefused):
        d._replace_once("aa", "a", "x", label="ambiguous")


def test_invalid_evidence_url_is_rejected_before_network():
    with pytest.raises(d.QualificationRefused, match="URL is invalid"):
        d._fetch("file:///tmp/evidence.json")


def test_evidence_validation_rejects_fresh_or_sensitive():
    base = {
        "schema": "tavonel.recovery.runtime_phase_diagnostic.v1",
        "role": "strong",
        "status": "RUNNING",
        "phase": "MODEL_DOWNLOAD_STARTED",
        "history": [],
        "fresh_confirmatory_observation": False,
        "sensitive_material_included": False,
    }
    assert d._validate_evidence("strong", dict(base))["phase"] == "MODEL_DOWNLOAD_STARTED"
    fresh = dict(base)
    fresh["fresh_confirmatory_observation"] = True
    with pytest.raises(d.QualificationRefused, match="fresh"):
        d._validate_evidence("strong", fresh)
    sensitive = dict(base)
    sensitive["sensitive_material_included"] = True
    with pytest.raises(d.QualificationRefused, match="sensitive"):
        d._validate_evidence("strong", sensitive)


def test_role_mismatch_and_missing_history_are_rejected():
    value = {
        "schema": "tavonel.recovery.runtime_phase_diagnostic.v1",
        "role": "primary",
        "status": "RUNNING",
        "phase": "STARTED",
        "history": [],
        "fresh_confirmatory_observation": False,
        "sensitive_material_included": False,
    }
    with pytest.raises(d.QualificationRefused, match="role mismatch"):
        d._validate_evidence("strong", value)
    value["role"] = "strong"
    value.pop("history")
    with pytest.raises(d.QualificationRefused, match="history"):
        d._validate_evidence("strong", value)
