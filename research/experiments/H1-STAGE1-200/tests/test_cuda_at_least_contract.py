from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts"
SCRIPT = SCRIPTS / "run_stage1_v29_r2_v17_cuda_at_least.py"

READY_STUB = {
    "base_image_digest": "vllm/vllm-openai@sha256:" + "e" * 64,
    "container_disk_gb": 80,
    "assembly_id": "sha256:" + "c" * 64,
    "cuda_version": "12.9",
}
BOUND_STUB = {
    "bundle": {"tar_sha256": "b" * 64},
    "model": {"resolved_revision": "rev", "model_safetensors_sha256": "m" * 64},
}
OTHER_ARGS = {
    "presigned": "https://example.invalid/bundle",
    "qualifier_b64": "Qg==",
    "qualifier_sha": "4" * 64,
    "driver_b64": "RA==",
    "runner_b64": "Ug==",
    "runner_sha": "5" * 64,
    "contract_b64": "Qw==",
    "contract_sha": "6" * 64,
    "security_b64": "Uw==",
    "model_b64": "TQ==",
    "control_token": "token",
    "name": "tavonel-stage1-test",
}


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_v17_cuda_at_least", SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


class _StubBundle:
    """Stands in for the 200-document tar so no test needs the real artifact."""

    def stat(self):
        return type("S", (), {"st_size": 1})()


def _payload(mod, cuda_version="12.9") -> dict:
    return mod.build_payload_allowing_every_sufficient_cuda(
        ready={**READY_STUB, "cuda_version": cuda_version},
        bound=BOUND_STUB,
        **OTHER_ARGS,
    )


@pytest.fixture
def module(monkeypatch):
    mod = load_module()
    monkeypatch.setattr(mod.v10.base, "BUNDLE", _StubBundle())
    # v16 persists the control token beside a run directory; no test makes one.
    monkeypatch.setattr(mod.v16, "write_reattach_secret", lambda *a, **k: None)
    return mod


def test_a_host_above_the_floor_is_allowed(module) -> None:
    """The whole defect: a 13.0 host satisfies cuda>=12.9 and was being refused."""
    allowed = _payload(module)["allowedCudaVersions"]
    assert "13.0" in allowed, allowed
    assert "12.9" in allowed, allowed


def test_a_host_below_the_floor_is_still_refused(module) -> None:
    """v13's lower bound is the half that was right: a 12.8 host cannot run a
    cu129 image without forward compat, which GeForce does not support -> 804."""
    allowed = _payload(module)["allowedCudaVersions"]
    for insufficient in ("12.8", "12.7", "11.8"):
        assert insufficient not in allowed, insufficient


def test_the_floor_comes_from_the_assembly_not_a_literal(module) -> None:
    """A hard-coded version is how the payload and READY drifted apart twice."""
    allowed = _payload(module, cuda_version="12.6")["allowedCudaVersions"]
    assert "12.6" in allowed, allowed
    assert "12.5" not in allowed, allowed
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets_the_filter = any(
            isinstance(t, ast.Subscript)
            and isinstance(t.slice, ast.Constant)
            and t.slice.value == "allowedCudaVersions"
            for t in node.targets
        )
        if targets_the_filter:
            assert not isinstance(node.value, ast.List | ast.Constant), (
                "allowedCudaVersions is assigned a literal again"
            )


def test_the_order_is_numeric_not_lexical(module) -> None:
    """'13.0' sorts below '12.9' as text, and a text sort would put the largest
    pool last in the request."""
    assert _payload(module)["allowedCudaVersions"] == ["12.9", "13.0"]


def test_an_assembly_version_the_platform_rejects_fails_loudly(module) -> None:
    """A value RunPod does not recognise matches no host at all -- silently,
    which is the exact failure mode v17 exists to remove."""
    with pytest.raises(RuntimeError, match="does not accept"):
        _payload(module, cuda_version="12.95")


def test_the_floor_is_visible_in_runpods_own_record(module) -> None:
    assert _payload(module)["env"][module.CUDA_FILTER_MARKER_ENV] == "12.9"


def test_only_the_cuda_filter_and_its_marker_differ_from_v16(module) -> None:
    """Wrapping, not reimplementing: image, GPU, ports, disk, entrypoint and
    every inherited env key must survive, or this is a different campaign."""
    patched = _payload(module)
    original = module._ORIGINAL_BUILD_PAYLOAD(
        ready=READY_STUB, bound=BOUND_STUB, **OTHER_ARGS
    )
    for key in set(patched) | set(original):
        if key in ("allowedCudaVersions", "env"):
            continue
        assert patched[key] == original[key], key
    added = set(patched["env"]) - set(original["env"])
    assert added == {module.CUDA_FILTER_MARKER_ENV}, added
    for key, value in original["env"].items():
        assert patched["env"][key] == value, key


def test_v17_reuses_the_v16_pipeline_instead_of_reimplementing_it() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert functions == {
        "main",
        "build_payload_allowing_every_sufficient_cuda",
        "versions_at_or_above",
        "_as_tuple",
    }, functions
    assert "v16.main()" in source
    for restated in (
        "STARTUP_TIMEOUT_SECONDS =",
        "MAX_STARTUP_ATTEMPTS =",
        "RunPodHttpxTransport(",
        "cloudType",
    ):
        assert restated not in source, restated


def test_v17_does_not_touch_ready_or_the_v4_qualifier() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "[REDACTED]" not in source
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "write_text" not in called, "READY and the qualifier are read-only here"


def test_the_compat_removal_and_capacity_polling_are_kept(module) -> None:
    """Both were justified by measurement and neither is undone by v17."""
    payload = _payload(module)
    assert payload["env"][module.v12.COMPAT_MARKER_ENV] == "1"
    assert "ldconfig" in payload["dockerEntrypoint"][2]
    assert module.v13.CAPACITY_POLL_ATTEMPTS > 3


def test_the_community_deviation_is_still_declared(module) -> None:
    """v17 must not quietly re-label a COMMUNITY run as SECURE evidence."""
    payload = _payload(module)
    assert payload["cloudType"] == "COMMUNITY"
    assert payload["env"][module.v14.CLOUD_MARKER_ENV] == "COMMUNITY"


def test_the_original_builder_is_bound_before_the_patch(module) -> None:
    assert (
        module._ORIGINAL_BUILD_PAYLOAD
        is not module.build_payload_allowing_every_sufficient_cuda
    )
    module.v16.build_payload_recording_the_token = (
        module.build_payload_allowing_every_sufficient_cuda
    )
    try:
        allowed = _payload(module)["allowedCudaVersions"]
    finally:
        module.v16.build_payload_recording_the_token = module._ORIGINAL_BUILD_PAYLOAD
    assert allowed == ["12.9", "13.0"], "the widening was applied twice"


def test_every_wrapper_below_v17_still_reaches_the_payload(module, monkeypatch) -> None:
    """v14 and v16 install into the same v13 slot and v14 runs last, so v16 was
    being overwritten and no control token was written. One payload built through
    the top of the chain must carry every layer's mark, including v16's write."""
    written: list[tuple] = []
    monkeypatch.setattr(
        module.v16,
        "write_reattach_secret",
        lambda run_dir, pod_name, token: written.append((pod_name, token)),
    )
    monkeypatch.setattr(module.v10, "RUN_DIR", Path("."), raising=False)
    payload = _payload(module)
    assert payload["env"][module.v12.COMPAT_MARKER_ENV] == "1"
    assert payload["env"][module.v14.CLOUD_MARKER_ENV] == "COMMUNITY"
    assert payload["env"][module.CUDA_FILTER_MARKER_ENV] == "12.9"
    assert written == [("tavonel-stage1-test", "token")], written
