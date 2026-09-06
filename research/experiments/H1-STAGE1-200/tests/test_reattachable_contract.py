from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts"
SCRIPT = SCRIPTS / "run_stage1_v29_r2_v16_reattachable.py"
GITIGNORE = ROOT / ".gitignore"


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_v16_reattach", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_secret_lands_where_git_cannot_see_it() -> None:
    """The whole justification for writing a token to disk is this line."""
    ignored = GITIGNORE.read_text(encoding="utf-8").splitlines()
    assert any(line.strip().rstrip("/") == ".chatgpt2codex" for line in ignored), ignored


def test_it_records_what_a_human_would_need(tmp_path) -> None:
    module = load_module()
    path = module.write_reattach_secret(tmp_path, "tavonel-stage1-v29-abc-v10-h1", "tok-123")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["control_token"] == "tok-123"  # noqa: S105
    assert saved["pod_name"] == "tavonel-stage1-v29-abc-v10-h1"
    assert path.name == module.REATTACH_FILENAME


def test_the_token_is_never_printed_or_put_in_a_receipt() -> None:
    """Receipts keep control_token_sha256; the token itself must not leak into
    stdout, an argv, or any receipt field."""
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            printed = ast.dump(node)
            assert "control_token" not in printed, "the token must never be printed"
    # Check imports, not prose: the docstring legitimately discusses subprocesses
    # and control_token_sha256, and matching on raw text reads those as code.
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "subprocess" not in imported, imported
    assert "os" not in imported, "no environ or exec path for the token"
    # v16 writes no receipt at all; the receipt fields stay v10's.
    tree_functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert not any("receipt" in name for name in tree_functions), tree_functions


def test_v16_reuses_the_v15_pipeline_instead_of_reimplementing_it() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert functions == {
        "main",
        "write_reattach_secret",
        "build_payload_recording_the_token",
        "_run_dir_from_active_state",
    }, functions
    assert "v15.main()" in source
    assert "[REDACTED]" not in source


def test_it_does_not_silently_resume_a_half_finished_run() -> None:
    """Deciding whether a partial Stage-1 run is still coherent evidence is a
    human call; a wrapper that guessed would be worse than losing the Pod."""
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("def reattach", "resume(", "monitor_campaign", "drive_pod"):
        assert forbidden not in source, forbidden


def test_the_payload_is_unchanged_by_recording_the_token(monkeypatch, tmp_path) -> None:
    module = load_module()

    class _StubBundle:
        def stat(self):
            return type("S", (), {"st_size": 1})()

    monkeypatch.setattr(module.v10.base, "BUNDLE", _StubBundle())
    monkeypatch.setattr(module, "_run_dir_from_active_state", lambda: tmp_path)
    kwargs = dict(
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
    patched = module.build_payload_recording_the_token(**kwargs)
    original = module._ORIGINAL_BUILD_PAYLOAD(**kwargs)
    assert patched == original
    assert (tmp_path / module.REATTACH_FILENAME).exists()
