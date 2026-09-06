from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts"
SCRIPT = SCRIPTS / "run_stage1_v29_r2_v9_failure_evidence.py"
V4_DRIVER = SCRIPTS / "stage1_same_pod_driver_v4_observability.py"
QUALIFIER = (
    ROOT / "infra" / "runpod" / "v6" / "images" / "ovisocr2-m1" / "assembly_qualification_http_v4.py"
)
READY = ROOT / ".chatgpt2codex" / "formal-runtime-v29" / "ovisocr2-v29-assembly-ready.json"
WATCHDOG_ACTIVE_KEYS = {
    "active_pod_id",
    "active_credential_label",
    "bucket",
    "r2_key",
    "r2_uploaded",
    "r2_deleted",
}


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_v9_failure_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _gzip_input_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if _call_name(node) != "gzip_b64":
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Name):
            names.append(arg.id)
        elif isinstance(arg, ast.Attribute):
            names.append(arg.attr)
    return names


def _sample_payload(module):
    ready = {
        "assembly_id": "sha256:" + "a" * 64,
        "base_image_digest": "vllm/vllm-openai@sha256:" + "b" * 64,
        "container_disk_gb": 80,
    }
    bound = {
        "bundle": {"tar_sha256": "sha256:" + "c" * 64},
        "model": {
            "resolved_revision": "d" * 40,
            "model_safetensors_sha256": "sha256:" + "e" * 64,
        },
    }
    return module.build_payload(
        ready=ready,
        bound=bound,
        presigned="https://example.invalid/source-only",
        qualifier_b64="q",
        qualifier_sha="sha256:" + "f" * 64,
        driver_b64="d",
        runner_b64="r",
        runner_sha="sha256:" + "1" * 64,
        contract_b64="c",
        contract_sha="sha256:" + "2" * 64,
        security_b64="s",
        model_b64="m",
        control_token=str(123456789),
        name="tavonel-test",
    )


def test_launched_driver_sha256_matches_v4_observability_file() -> None:
    module = load_module()
    assert module.V4_DRIVER.resolve() == V4_DRIVER.resolve()
    _, digest = module.base.gzip_b64(module.V4_DRIVER)
    assert digest == file_sha256(V4_DRIVER)


def test_qualifier_sha256_matches_v4_and_ready_bootstrap() -> None:
    module = load_module()
    ready = json.loads(READY.read_text(encoding="utf-8"))
    assert module.QUALIFIER.resolve() == QUALIFIER.resolve()
    actual = file_sha256(QUALIFIER)
    assert actual == ready["bootstrap_sha256"]
    _, qualifier_sha = module.base.gzip_b64(module.QUALIFIER)
    assert qualifier_sha == ready["bootstrap_sha256"]


def test_bootstrap_dest_basename_matches_gzip_source() -> None:
    module = load_module()
    source = SCRIPT.read_text(encoding="utf-8")
    dest = "/opt/tavonel/stage1/stage1_same_pod_driver_v4_observability.py"
    assert dest in source
    assert Path(dest).name == module.V4_DRIVER.name
    assert Path(dest).name == V4_DRIVER.name
    command = _sample_payload(module)["dockerEntrypoint"][2]
    assert dest in command
    assert command.count(dest) == 2


def test_v9_does_not_gzip_v7_driver_constant() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "gzip_b64(base.DRIVER)" not in source
    tree = ast.parse(source)
    assert "DRIVER" not in _gzip_input_names(tree)
    assert "V4_DRIVER" in _gzip_input_names(tree)


def test_v9_source_has_no_redacted_placeholder() -> None:
    assert "[REDACTED]" not in SCRIPT.read_text(encoding="utf-8")


def test_payload_binds_artifact_manifest_volume_zero_and_control_ports() -> None:
    module = load_module()
    payload = _sample_payload(module)
    assert payload["env"]["TAVONEL_ARTIFACT_MANIFEST_SHA256"] == "sha256:" + "e" * 64
    assert payload["volumeInGb"] == 0
    assert payload["ports"] == ["8001/http", "8002/http"]
    assert not any("GROUND_TRUTH" in key.upper() for key in payload["env"])
    assert not any("GROUND_TRUTH" in key.upper() for key in payload)


def test_max_startup_attempts_is_one() -> None:
    module = load_module()
    assert module.MAX_STARTUP_ATTEMPTS == 1


def test_harvest_failure_evidence_called_before_raise() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    harvest = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "harvest_failure_evidence"
    )
    assert harvest
    monitor = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "monitor_campaign"
    )
    excepts = [node for node in ast.walk(monitor) if isinstance(node, ast.ExceptHandler)]
    assert excepts
    assert any(
        any(_call_name(child) == "harvest_failure_evidence" for child in ast.walk(handler))
        and any(isinstance(child, ast.Raise) for child in ast.walk(handler))
        for handler in excepts
    )
    for handler in excepts:
        harvest_lines = [
            child.lineno
            for child in ast.walk(handler)
            if _call_name(child) == "harvest_failure_evidence"
        ]
        raise_lines = [child.lineno for child in ast.walk(handler) if isinstance(child, ast.Raise)]
        if harvest_lines and raise_lines:
            assert min(harvest_lines) < min(raise_lines)


def test_internal_active_state_write_happens_before_create() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    write_pos = source.find("write_internal_active_state")
    create_pos = min(
        pos
        for pos in (
            source.find("create_once_or_reconcile"),
            source.find("create_pod"),
        )
        if pos >= 0
    )
    assert 0 <= write_pos < create_pos
    tree = ast.parse(source)
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    write_lines = [
        node.lineno for node in ast.walk(main) if _call_name(node) == "write_internal_active_state"
    ]
    create_lines = [
        node.lineno
        for node in ast.walk(main)
        if _call_name(node) in {"create_once_or_reconcile", "create_pod"}
    ]
    assert write_lines
    assert create_lines
    assert min(write_lines) < min(create_lines)


def test_first_active_state_has_bucket_key_and_null_pod(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "internal-active-state.json"
    state = module.write_internal_active_state(path, bucket="working-bucket", r2_key="tavonel/k.tar")
    assert state["bucket"] == "working-bucket"
    assert state["r2_key"] == "tavonel/k.tar"
    assert state["active_pod_id"] is None
    assert state["active_credential_label"] is None
    assert state["r2_uploaded"] is False
    assert state["r2_deleted"] is False
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["active_pod_id"] is None
    assert persisted["bucket"] == "working-bucket"


def test_active_state_keys_include_every_watchdog_field(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "internal-active-state.json"
    state = module.write_internal_active_state(path, bucket="b", r2_key="k")
    assert WATCHDOG_ACTIVE_KEYS <= set(state)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert WATCHDOG_ACTIVE_KEYS <= set(persisted)
    watchdog = (SCRIPTS / "stage1_host_retry_watchdog.py").read_text(encoding="utf-8")
    for key in WATCHDOG_ACTIVE_KEYS:
        assert f'"{key}"' in watchdog or f"state.get(\"{key}\")" in watchdog


def test_r2_upload_is_outside_create_loop() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    upload_calls = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "r2_upload_bundle"
    ]
    assert len(upload_calls) == 1
    upload = upload_calls[0]
    assert not any(
        isinstance(parent, (ast.For, ast.While)) and upload in list(ast.walk(parent))
        for parent in ast.walk(main)
    )
