from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    ROOT
    / "research"
    / "experiments"
    / "H1-STAGE1-200"
    / "scripts"
    / "stage1_same_pod_driver_v4_observability.py"
)
DENIED_EXACT = {
    "TAVONEL_STAGE1_CONTROL_TOKEN",
    "TAVONEL_STAGE1_BUNDLE_URL",
    "TAVONEL_STAGE1_BUNDLE_SHA256",
    "TAVONEL_STAGE1_BUNDLE_BYTES",
}
DENIED_PREFIXES = (
    "TAVONEL_STAGE1_DRIVER_",
    "TAVONEL_STAGE1_RUNNER_",
    "TAVONEL_INPUT_CONTRACT_",
)
ERROR_V2_FIELDS = (
    "error_type",
    "message",
    "child_pid",
    "child_returncode",
    "child_alive",
    "vllm_server_log_present",
    "vllm_server_log_sha256",
    "vllm_server_log_bytes",
    "vllm_server_log_tail",
)


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_driver_v4_observability", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def test_denied_keys_absent_from_child_env_builder() -> None:
    module = load_module()
    parent = {
        "PATH": "/usr/bin",
        "HF_HOME": "/opt/tavonel/hf-cache",
        "TAVONEL_STAGE1_CONTROL_TOKEN": "secret-token",
        "TAVONEL_STAGE1_BUNDLE_URL": "https://example.invalid/bundle",
        "TAVONEL_STAGE1_BUNDLE_SHA256": "sha256:" + "a" * 64,
        "TAVONEL_STAGE1_BUNDLE_BYTES": "12",
        "TAVONEL_QUALIFIER_GZ_B64": "qualifier-bytes",
        "TAVONEL_STAGE1_DRIVER_GZ_B64": "driver-bytes",
        "TAVONEL_STAGE1_DRIVER_SHA256": "sha256:" + "b" * 64,
        "TAVONEL_STAGE1_RUNNER_GZ_B64": "runner-bytes",
        "TAVONEL_STAGE1_RUNNER_SHA256": "sha256:" + "c" * 64,
        "TAVONEL_INPUT_CONTRACT_GZ_B64": "contract-bytes",
        "TAVONEL_INPUT_CONTRACT_SHA256": "sha256:" + "d" * 64,
        "SOME_OTHER_GZ_B64": "other-bytes",
    }
    child = module.build_qualifier_child_env(parent)
    for key in DENIED_EXACT:
        assert key not in child
    for key in parent:
        if key.endswith("_GZ_B64") or key.startswith(DENIED_PREFIXES):
            assert key not in child
    assert child["PATH"] == "/usr/bin"
    assert child["HF_HOME"] == "/opt/tavonel/hf-cache"


def test_child_env_keeps_cuda_and_vllm_parent_vars() -> None:
    module = load_module()
    parent = {
        "CUDA_VISIBLE_DEVICES": "0",
        "VLLM_FOO": "keep-me",
        "NVIDIA_VISIBLE_DEVICES": "all",
        "TORCH_NCCL_ASYNC_ERROR_HANDLING": "1",
        "NCCL_P2P_DISABLE": "0",
        "OMP_NUM_THREADS": "4",
        "TAVONEL_STAGE1_CONTROL_TOKEN": "secret-token",
    }
    child = module.build_qualifier_child_env(parent)
    assert child["CUDA_VISIBLE_DEVICES"] == "0"
    assert child["VLLM_FOO"] == "keep-me"
    assert child["NVIDIA_VISIBLE_DEVICES"] == "all"
    assert child["TORCH_NCCL_ASYNC_ERROR_HANDLING"] == "1"
    assert child["NCCL_P2P_DISABLE"] == "0"
    assert child["OMP_NUM_THREADS"] == "4"
    assert "TAVONEL_STAGE1_CONTROL_TOKEN" not in child


def test_harvest_copies_log_and_writes_tail_and_child_json(
    tmp_path: Path, monkeypatch: Any
) -> None:
    module = load_module()
    assembly = tmp_path / "assembly"
    root = tmp_path / "stage1"
    assembly.mkdir()
    root.mkdir()
    monkeypatch.setattr(module, "ASSEMBLY_ROOT", assembly)
    monkeypatch.setattr(module, "ROOT", root)
    payload = b"alpha\x00beta" + (b"z" * 32)
    (assembly / "vllm-server.log").write_bytes(payload)
    (assembly / "status.json").write_text(
        json.dumps({"state": "error", "passed": False}) + "\n",
        encoding="utf-8",
    )

    class Proc:
        pid = 4242

        def poll(self) -> int:
            return 1

    evidence = module.harvest_qualifier_evidence(Proc())
    copied = root / "vllm-server.log"
    assert copied.is_file()
    assert copied.read_bytes() == payload
    tail = json.loads((root / "vllm-server-log-tail.json").read_text(encoding="utf-8"))
    assert tail["vllm_server_log_sha256"] == evidence["vllm_server_log_sha256"]
    assert tail["vllm_server_log_sha256"].startswith("sha256:")
    assert "\x00" not in tail["vllm_server_log_tail"]
    assert tail["vllm_server_log_tail"].endswith("z" * 32)
    child = json.loads((root / "qualifier-child.json").read_text(encoding="utf-8"))
    assert child == {
        "child_pid": 4242,
        "child_returncode": 1,
        "child_alive": False,
    }
    assert evidence["vllm_server_log_present"] is True
    assert evidence["vllm_server_log_bytes"] == len(payload)
    mirror = json.loads((root / "qualifier-status-mirror.json").read_text(encoding="utf-8"))
    assert mirror["state"] == "error"


def test_failure_path_does_not_call_terminate_process_group() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    wait = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "wait_qualification"
    )
    assert not any(_call_name(node) == "terminate_process_group" for node in ast.walk(wait))
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    for handler in (node for node in ast.walk(main) if isinstance(node, ast.ExceptHandler)):
        assert not any(
            _call_name(node) == "terminate_process_group" for node in ast.walk(handler)
        )
    for block in ast.walk(main):
        if isinstance(block, ast.Try):
            for final_node in block.finalbody:
                assert not any(
                    _call_name(node) == "terminate_process_group"
                    for node in ast.walk(final_node)
                )


def test_success_path_calls_terminate_process_group() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    terminate_calls = [
        node for node in ast.walk(main) if _call_name(node) == "terminate_process_group"
    ]
    assert terminate_calls
    wait_calls = [node for node in ast.walk(main) if _call_name(node) == "wait_qualification"]
    assert wait_calls
    assert min(node.lineno for node in wait_calls) < min(node.lineno for node in terminate_calls)


def test_stage1_error_v2_fields_present_in_source() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"schema": "tavonel.stage1-same-pod-error.v2"' in source
    for field in ERROR_V2_FIELDS:
        assert f'"{field}"' in source


def test_8002_auth_handler_still_present() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "def auth_handler()" in source
    assert "Bearer {token}" in source
    assert 'start_http_server(8002, "stage1-bootstrap-heartbeat")' in source
    tree = ast.parse(source)
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    start_calls = [
        node
        for node in ast.walk(main)
        if _call_name(node) == "start_http_server"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == 8002
    ]
    wait_calls = [node for node in ast.walk(main) if _call_name(node) == "wait_qualification"]
    assert start_calls
    assert wait_calls
    assert min(node.lineno for node in start_calls) < min(node.lineno for node in wait_calls)
