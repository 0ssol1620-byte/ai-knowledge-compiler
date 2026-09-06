from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts"
SCRIPT = SCRIPTS / "run_stage1_v29_r2_v12_cuda_compat.py"
V10 = SCRIPTS / "run_stage1_v29_r2_v10_runtime_ready.py"


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_v12_cuda_compat", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _StubBundle:
    """Stands in for the 200-document tar so no test needs the real artifact."""

    def stat(self):
        return type("S", (), {"st_size": 1})()


def _stub_bundle(module, monkeypatch) -> None:
    monkeypatch.setattr(module.v10.base, "BUNDLE", _StubBundle())


def _literals_outside_the_module_docstring(tree: ast.Module) -> str:
    """Prose in the docstring explains what v12 does not touch; it must not be
    mistaken for v12 touching it."""
    docstring_node = None
    if tree.body and isinstance(tree.body[0], ast.Expr):
        value = tree.body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            docstring_node = value
    return "\n".join(
        sorted(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node is not docstring_node
        )
    )


def _payload(module) -> dict:
    """A v10 payload built through the v12 wrapper, with stub inputs."""
    return module.build_payload_without_cuda_compat(
        ready={
            "base_image_digest": "vllm/vllm-openai@sha256:" + "e" * 64,
            "container_disk_gb": 80,
            "assembly_id": "sha256:" + "c" * 64,
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


def test_the_compat_removal_runs_before_the_driver(monkeypatch) -> None:
    module = load_module()
    _stub_bundle(module, monkeypatch)
    command = _payload(module)["dockerEntrypoint"][2]
    removal_end = command.index("ldconfig")
    driver_start = command.index("stage1_same_pod_driver")
    assert removal_end < driver_start, "compat is still on the path when vLLM starts"
    for fragment in ("/usr/local/cuda/compat", "compat*.conf", "ldconfig"):
        assert fragment in command, fragment


def test_removal_failures_cannot_abort_the_container(monkeypatch) -> None:
    """A host with no compat directory must run the campaign identically."""
    module = load_module()
    _stub_bundle(module, monkeypatch)
    prefix = module.COMPAT_REMOVAL_COMMAND
    for statement in [s.strip() for s in prefix.split(";") if s.strip()]:
        assert statement.endswith("|| true"), statement


def test_only_the_entrypoint_prefix_and_the_marker_differ_from_v10(monkeypatch) -> None:
    """Wrapping, not reimplementing: the image, GPU, ports, disk and every v10 env
    key must survive untouched, or this is a different campaign."""
    module = load_module()
    _stub_bundle(module, monkeypatch)
    patched = _payload(module)
    # Rebuild the unpatched payload through the same stub inputs.
    saved = module.v10.build_payload
    module.v10.build_payload = module._ORIGINAL_BUILD_PAYLOAD
    try:
        original = module._ORIGINAL_BUILD_PAYLOAD(
            ready={
                "base_image_digest": "vllm/vllm-openai@sha256:" + "e" * 64,
                "container_disk_gb": 80,
                "assembly_id": "sha256:" + "c" * 64,
            },
            bound={
                "bundle": {"tar_sha256": "b" * 64},
                "model": {
                    "resolved_revision": "rev",
                    "model_safetensors_sha256": "m" * 64,
                },
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
    finally:
        module.v10.build_payload = saved

    for key in set(patched) | set(original):
        if key in ("dockerEntrypoint", "env"):
            continue
        assert patched[key] == original[key], key

    assert patched["dockerEntrypoint"][:2] == original["dockerEntrypoint"][:2]
    assert patched["dockerEntrypoint"][2].endswith(original["dockerEntrypoint"][2])

    added = set(patched["env"]) - set(original["env"])
    assert added == {module.COMPAT_MARKER_ENV}, added
    for key, value in original["env"].items():
        assert patched["env"][key] == value, key


def test_the_runtime_change_is_visible_in_runpods_own_record(monkeypatch) -> None:
    """A silent library change would make every Stage-1 receipt unfalsifiable."""
    module = load_module()
    _stub_bundle(module, monkeypatch)
    assert _payload(module)["env"][module.COMPAT_MARKER_ENV] == "1"


def test_the_removal_is_unconditional(monkeypatch) -> None:
    """Per-host branching would mean two library configurations across the 200
    documents and a receipt that cannot say which produced its outputs."""
    module = load_module()
    prefix = module.COMPAT_REMOVAL_COMMAND
    for branch in ("if ", "nvidia-smi", "case ", "grep "):
        assert branch not in prefix, branch


def test_v12_does_not_touch_ready_or_the_v4_qualifier() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    body = _literals_outside_the_module_docstring(tree)
    for forbidden in ("ovisocr2-v29-assembly-ready.json", "assembly_qualification_http"):
        assert forbidden not in body, forbidden
    assert "[REDACTED]" not in source


def test_v12_reuses_the_v11_pipeline_instead_of_reimplementing_it() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert functions == {"main", "build_payload_without_cuda_compat"}, functions
    assert "v11.main()" in source
    # v12 must inherit v11's transport and budget rather than restating them.
    for restated in (
        "STARTUP_TIMEOUT_SECONDS =",
        "MAX_STARTUP_ATTEMPTS =",
        "RunPodHttpxTransport(",
    ):
        assert restated not in source, restated


def test_the_original_build_payload_is_bound_before_the_patch(monkeypatch) -> None:
    module = load_module()
    assert module._ORIGINAL_BUILD_PAYLOAD is not module.build_payload_without_cuda_compat
    _stub_bundle(module, monkeypatch)
    module.v10.build_payload = module.build_payload_without_cuda_compat
    try:
        command = _payload(module)["dockerEntrypoint"][2]
    finally:
        module.v10.build_payload = module._ORIGINAL_BUILD_PAYLOAD
    assert command.count("ldconfig") == 1, "the prefix was applied twice"


def test_v10_still_resolves_build_payload_as_a_global() -> None:
    """The override only works because the host loop looks the name up at call time."""
    tree = ast.parse(V10.read_text(encoding="utf-8"))
    main = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    called = {
        n.func.id
        for n in ast.walk(main)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "build_payload" in called
