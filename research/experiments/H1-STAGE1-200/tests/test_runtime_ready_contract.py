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
    / "run_stage1_v29_r2_v10_runtime_ready.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_v10_runtime_ready", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GraphQLOnlyTransport:
    def __init__(self, payload):
        self.payload = payload

    def graphql(self, *, query, variables=None):
        assert "runtime" in query
        return self.payload

    def get_pod(self, pod_id: str):
        raise RuntimeError("REST get is unavailable")


class RestFallbackTransport:
    def graphql(self, *, query, variables=None):
        return {"pod": {"desiredStatus": "RUNNING", "runtime": None}}

    def get_pod(self, pod_id: str):
        assert pod_id == "pod123"
        return {
            "desiredStatus": "RUNNING",
            "portMappings": {"8001": 21001, "8002": 21002, "19123": 19123},
        }


def test_graphql_runtime_without_control_ports_is_not_ready() -> None:
    module = load_module()
    snapshot = module.runtime_snapshot(
        GraphQLOnlyTransport(
            {
                "pod": {
                    "desiredStatus": "RUNNING",
                    "runtime": {"uptimeInSeconds": 0, "ports": []},
                }
            }
        ),
        "pod123",
    )
    assert snapshot["runtime_present"] is False
    assert snapshot["desired_status"] == "RUNNING"


def test_graphql_runtime_dict_alone_is_not_ready() -> None:
    module = load_module()
    snapshot = module.runtime_snapshot(
        GraphQLOnlyTransport({"pod": {"desiredStatus": "RUNNING", "runtime": {}}}),
        "pod123",
    )
    assert snapshot["runtime_present"] is False


def test_control_ports_on_graphql_are_ready() -> None:
    module = load_module()
    snapshot = module.runtime_snapshot(
        GraphQLOnlyTransport(
            {
                "pod": {
                    "desiredStatus": "RUNNING",
                    "runtime": {
                        "uptimeInSeconds": 17,
                        "ports": [
                            {"privatePort": 8001, "publicPort": 1, "type": "http"},
                            {"privatePort": 8002, "publicPort": 2, "type": "http"},
                        ],
                    },
                }
            }
        ),
        "pod123",
    )
    assert snapshot["runtime_present"] is True
    assert snapshot["uptime_seconds"] == 17


def test_rest_port_mappings_recover_when_graphql_runtime_is_null() -> None:
    module = load_module()
    snapshot = module.runtime_snapshot(RestFallbackTransport(), "pod123")
    assert snapshot["runtime_present"] is True
    assert "rest" in snapshot["sources"]
    privates = {item["privatePort"] for item in snapshot["ports"] if item["publicPortPresent"]}
    assert {8001, 8002}.issubset(privates)


def test_v10_allows_bounded_host_retries_and_uploads_r2_once() -> None:
    module = load_module()
    assert module.MAX_STARTUP_ATTEMPTS == 4
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    upload_calls = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "r2_upload_bundle"
    ]
    assert len(upload_calls) == 1
    assert not any(
        isinstance(parent, (ast.For, ast.While)) and upload_calls[0] in list(ast.walk(parent))
        for parent in ast.walk(main)
    )
    source = SCRIPT.read_text(encoding="utf-8")
    assert "tavonel-stage1-v29-{run_id}-v10-h" in source
    assert "gzip_b64(V4_DRIVER)" in source
    assert "[REDACTED]" not in source
