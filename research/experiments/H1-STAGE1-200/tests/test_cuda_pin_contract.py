from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts"
SCRIPT = SCRIPTS / "run_stage1_v29_r2_v13_cuda_pin.py"
READY = ROOT / ".chatgpt2codex" / "formal-runtime-v29" / "ovisocr2-v29-assembly-ready.json"


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_v13_cuda_pin", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _StubBundle:
    def stat(self):
        return type("S", (), {"st_size": 1})()


def _payload(module, monkeypatch, *, cuda_version="12.9"):
    monkeypatch.setattr(module.v10.base, "BUNDLE", _StubBundle())
    return module.build_payload_pinned_to_assembly_cuda(
        ready={
            "base_image_digest": "vllm/vllm-openai@sha256:" + "e" * 64,
            "container_disk_gb": 80,
            "assembly_id": "sha256:" + "c" * 64,
            "cuda_version": cuda_version,
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


def test_the_filter_names_only_the_assembly_cuda_version(monkeypatch) -> None:
    """A cu129 image on a 12.8 host forces forward compat, which GeForce does
    not support -- that is CUDA 804."""
    module = load_module()
    payload = _payload(module, monkeypatch)
    assert payload["allowedCudaVersions"] == ["12.9"]
    assert "12.8" not in payload["allowedCudaVersions"]


def test_the_filter_follows_the_assembly_instead_of_a_literal(monkeypatch) -> None:
    """Hard-coding the version is how the payload and READY drifted apart."""
    module = load_module()
    payload = _payload(module, monkeypatch, cuda_version="13.1")
    assert payload["allowedCudaVersions"] == ["13.1"]
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstring = tree.body[0].value if isinstance(tree.body[0], ast.Expr) else None
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node is not docstring
    ]
    assert "12.9" not in literals, "the version must come from the assembly"


def test_an_assembly_without_a_cuda_pin_is_refused(monkeypatch) -> None:
    """Silently falling back to 'any host' is what this version exists to stop."""
    module = load_module()
    with pytest.raises(RuntimeError, match="cuda_version"):
        _payload(module, monkeypatch, cuda_version="  ")


def test_the_real_assembly_pins_a_version_this_wrapper_can_read() -> None:
    import json

    ready = json.loads(READY.read_text(encoding="utf-8"))
    assert str(ready["cuda_version"]).strip(), "READY must pin cuda_version"


def test_everything_else_is_v12s_payload(monkeypatch) -> None:
    module = load_module()
    payload = _payload(module, monkeypatch)
    # v12's compat removal survives: it is the second line of defence.
    assert module.v12.COMPAT_MARKER_ENV in payload["env"]
    assert "ldconfig" in payload["dockerEntrypoint"][2]
    assert payload["gpuTypeIds"] == [module.v10.base.GPU]
    assert payload["cloudType"] == "SECURE"
    assert payload["ports"] == ["8001/http", "8002/http"]


def test_v13_reuses_the_v12_pipeline_instead_of_reimplementing_it() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert functions == {"main", "build_payload_pinned_to_assembly_cuda"}, functions
    assert "v12.main()" in source
    assert "[REDACTED]" not in source


def test_the_original_build_payload_is_bound_before_the_patch(monkeypatch) -> None:
    module = load_module()
    assert module._ORIGINAL_BUILD_PAYLOAD is not module.build_payload_pinned_to_assembly_cuda
    module.v12.build_payload_without_cuda_compat = module.build_payload_pinned_to_assembly_cuda
    try:
        payload = _payload(module, monkeypatch)
    finally:
        module.v12.build_payload_without_cuda_compat = module._ORIGINAL_BUILD_PAYLOAD
    assert payload["dockerEntrypoint"][2].count("ldconfig") == 1


def test_v12_installs_whatever_name_this_module_rebinds() -> None:
    """The override works only because v12.main() resolves the global at call time."""
    v12_source = (SCRIPTS / "run_stage1_v29_r2_v12_cuda_compat.py").read_text(encoding="utf-8")
    assert "v10.build_payload = build_payload_without_cuda_compat" in v12_source


def test_capacity_polling_waits_long_enough_to_outlast_a_closed_window() -> None:
    """Measured: cuda>=12.9 capacity was present at 10:20 KST and gone by 10:52.
    A wait shorter than that window is a wait that always loses."""
    module = load_module()
    total_seconds = module.CAPACITY_POLL_ATTEMPTS * module.CAPACITY_POLL_DELAY_SECONDS
    assert total_seconds >= 15 * 60, total_seconds
    # It must still fit inside the campaign's own deadline with room to run.
    assert total_seconds < module.v10.base.MAX_TOTAL_SECONDS / 3


def test_the_delay_is_separate_from_the_attempt_count() -> None:
    """v11's 5 s is right for a transient 500 and wrong for GPU capacity; the two
    callers must be able to differ."""
    module = load_module()
    assert module.CAPACITY_POLL_DELAY_SECONDS > module.v11.CREATE_5XX_DELAY_SECONDS or (
        module.v11.CREATE_5XX_DELAY_SECONDS == module.CAPACITY_POLL_DELAY_SECONDS
    )
    source = (
        Path(module.v11.__file__).read_text(encoding="utf-8")
        if getattr(module.v11, "__file__", None)
        else ""
    )
    assert "time.sleep(CREATE_5XX_DELAY_SECONDS)" in source
    assert "time.sleep(5)" not in source
