from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts"
SCRIPT = SCRIPTS / "run_stage1_v29_r2_v14_community.py"


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_v14_community", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _StubBundle:
    def stat(self):
        return type("S", (), {"st_size": 1})()


def _payload(module, monkeypatch):
    monkeypatch.setattr(module.v10.base, "BUNDLE", _StubBundle())
    return module.build_payload_on_community_hosts(
        ready={
            "base_image_digest": "vllm/vllm-openai@sha256:" + "e" * 64,
            "container_disk_gb": 80,
            "assembly_id": "sha256:" + "c" * 64,
            "cuda_version": "12.9",
        },
        bound={
            "bundle": {"tar_sha256": "b" * 64},
            "model": {"resolved_revision": "rev", "model_safetensors_sha256": "m" * 64},
        },
        presigned="https://example.invalid/bundle",
        qualifier_b64="Qg==",
        qualifier_sha="4" * 64,
        driver_b64="RA==",
        runner_b64="Ug==",
        runner_sha="5" * 64,
        contract_b64="Qw==",
        contract_sha="6" * 64,
        security_b64="Uw==",
        model_b64="TQ==",
        control_token="token",  # noqa: S106
        name="tavonel-stage1-test",
    )


def test_only_the_cloud_type_changes(monkeypatch) -> None:
    """The GPU, image, disk, ports and every inherited fix must survive."""
    module = load_module()
    payload = _payload(module, monkeypatch)
    assert payload["cloudType"] == "COMMUNITY"
    assert payload["gpuTypeIds"] == [module.v10.base.GPU]
    assert payload["allowedCudaVersions"] == ["12.9"]          # v13
    assert "ldconfig" in payload["dockerEntrypoint"][2]         # v12
    assert payload["ports"] == ["8001/http", "8002/http"]
    assert payload["containerDiskInGb"] == 80
    assert payload["interruptible"] is False


def test_the_deviation_is_visible_in_runpods_own_record(monkeypatch) -> None:
    """A receipt must not require reading this file to learn it was COMMUNITY."""
    module = load_module()
    payload = _payload(module, monkeypatch)
    assert payload["env"][module.CLOUD_MARKER_ENV] == "COMMUNITY"


def test_v14_reuses_the_v13_pipeline_instead_of_reimplementing_it() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert functions == {
        "main",
        "build_payload_on_community_hosts",
        "candidates_limited_to_one_credential",
    }, functions
    assert "v13.main()" in source
    assert "[REDACTED]" not in source


def test_pinning_a_credential_narrows_accounts_not_hosts(monkeypatch) -> None:
    """A console-inspection convenience must not become a silent host filter."""
    module = load_module()
    pairs = [("Runpod_B", object()), ("Runpod_A", object())]
    monkeypatch.setattr(module, "_ORIGINAL_CANDIDATES", lambda _f: list(pairs))

    monkeypatch.delenv(module.ONLY_CREDENTIAL_ENV, raising=False)
    assert module.candidates_limited_to_one_credential(Path("x")) == pairs

    monkeypatch.setenv(module.ONLY_CREDENTIAL_ENV, "Runpod_B")
    assert module.candidates_limited_to_one_credential(Path("x")) == [pairs[0]]

    # The payload must be byte-identical either way: no host-affecting field.
    monkeypatch.setattr(module.v10.base, "BUNDLE", _StubBundle())
    monkeypatch.delenv(module.ONLY_CREDENTIAL_ENV, raising=False)
    without = _payload(module, monkeypatch)
    monkeypatch.setenv(module.ONLY_CREDENTIAL_ENV, "Runpod_B")
    assert _payload(module, monkeypatch) == without


def test_pinning_an_ineligible_credential_fails_loudly(monkeypatch) -> None:
    """Silently falling back to the other account would put the Pods where the
    person watching the console cannot see them."""
    module = load_module()
    monkeypatch.setattr(module, "_ORIGINAL_CANDIDATES", lambda _f: [("Runpod_A", object())])
    monkeypatch.setenv(module.ONLY_CREDENTIAL_ENV, "Runpod_B")
    try:
        module.candidates_limited_to_one_credential(Path("x"))
    except RuntimeError as exc:
        assert "Runpod_B" in str(exc)
        return
    raise AssertionError("an ineligible pinned credential must not be ignored")


def test_v14_says_out_loud_that_its_output_is_not_secure_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "NOT SECURE-cloud evidence" in source


def test_the_original_build_payload_is_bound_before_the_patch(monkeypatch) -> None:
    module = load_module()
    assert module._ORIGINAL_BUILD_PAYLOAD is not module.build_payload_on_community_hosts
    module.v13.build_payload_pinned_to_assembly_cuda = module.build_payload_on_community_hosts
    try:
        payload = _payload(module, monkeypatch)
    finally:
        module.v13.build_payload_pinned_to_assembly_cuda = module._ORIGINAL_BUILD_PAYLOAD
    assert payload["dockerEntrypoint"][2].count("ldconfig") == 1
