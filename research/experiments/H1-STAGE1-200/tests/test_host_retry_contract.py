from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    ROOT
    / "research"
    / "experiments"
    / "H1-STAGE1-200"
    / "scripts"
    / "run_stage1_v29_r2_v8_host_retry.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_v8_contract", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def graphql(self, *, query, variables=None):
        assert "runtime" in query
        assert variables == {"podId": "pod123"}
        return {
            "pod": {
                "desiredStatus": "RUNNING",
                "runtime": {
                    "uptimeInSeconds": 17,
                    "ports": [{"privatePort": 8002, "publicPort": 12345, "type": "http"}],
                },
            }
        }


class FakeS3:
    def __init__(self):
        self.kwargs = None

    def generate_presigned_url(self, operation, **kwargs):
        self.kwargs = {"operation": operation, **kwargs}
        return "https://example.invalid/frozen"


def test_runtime_snapshot_detects_a_real_runtime() -> None:
    module = load_module()
    snapshot = module.runtime_snapshot(FakeTransport(), "pod123")
    assert snapshot["runtime_present"] is True
    assert snapshot["uptime_seconds"] == 17
    assert snapshot["ports"][0]["privatePort"] == 8002
    assert snapshot["ports"][0]["publicPortPresent"] is True


def test_presign_is_two_hours_and_payload_is_gt_free_volume_zero() -> None:
    module = load_module()
    fake = FakeS3()
    assert module.fresh_presigned(fake, "bucket", "key").startswith("https://")
    assert fake.kwargs["ExpiresIn"] == 7200

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
    payload = module.build_payload(
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
    assert payload["volumeInGb"] == 0
    assert payload["ports"] == ["8001/http", "8002/http"]
    assert not any("GROUND_TRUTH" in key.upper() for key in payload["env"])
    assert payload["env"]["TAVONEL_STAGE1_BUNDLE_URL"].startswith("https://")


def test_r2_upload_is_outside_host_retry_loop() -> None:
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
