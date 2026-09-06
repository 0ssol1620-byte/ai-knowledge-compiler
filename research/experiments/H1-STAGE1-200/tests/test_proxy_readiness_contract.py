from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts"
SCRIPT = SCRIPTS / "run_stage1_v29_r2_v15_proxy_readiness.py"


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_v15_proxy", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _fake_get(status_by_port: dict[int, object]):
    def get(url: str, timeout: float = 0):
        port = int(url.split("-", 1)[1].split(".", 1)[0])
        outcome = status_by_port[port]
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)

    return get


def test_a_401_on_both_ports_is_ready(monkeypatch) -> None:
    """The measured case: the qualifier demands a control token, so 401 is what
    a healthy Pod says before the driver authenticates."""
    module = load_module()
    monkeypatch.setattr(module.httpx, "get", _fake_get({8001: 401, 8002: 401}))
    monkeypatch.setattr(module, "_ORIGINAL_SNAPSHOT", lambda _t, _p: {"runtime_present": False})
    snap = module.snapshot_with_proxy_readiness(object(), "pod1")
    assert snap["runtime_present"] is True
    assert snap["runtime_present_per_api"] is False


def test_requiring_200_would_reintroduce_the_false_negative(monkeypatch) -> None:
    module = load_module()
    monkeypatch.setattr(module.httpx, "get", _fake_get({8001: 401, 8002: 401}))
    monkeypatch.setattr(module, "_ORIGINAL_SNAPSHOT", lambda _t, _p: {})
    assert module.snapshot_with_proxy_readiness(object(), "pod1")["runtime_present"] is True
    assert module.NOT_EXPOSED_STATUS == 404


def test_404_on_either_port_is_not_ready(monkeypatch) -> None:
    """404 is what an unexposed port and a deleted Pod both returned."""
    module = load_module()
    monkeypatch.setattr(module, "_ORIGINAL_SNAPSHOT", lambda _t, _p: {})
    for ports in ({8001: 404, 8002: 401}, {8001: 401, 8002: 404}, {8001: 404, 8002: 404}):
        monkeypatch.setattr(module.httpx, "get", _fake_get(ports))
        assert module.snapshot_with_proxy_readiness(object(), "pod1")["runtime_present"] is False


def test_a_transport_error_is_not_ready(monkeypatch) -> None:
    """A probe that cannot complete must never be read as success."""
    module = load_module()
    monkeypatch.setattr(module, "_ORIGINAL_SNAPSHOT", lambda _t, _p: {})
    monkeypatch.setattr(
        module.httpx, "get", _fake_get({8001: module.httpx.ConnectError("boom"), 8002: 401})
    )
    assert module.snapshot_with_proxy_readiness(object(), "pod1")["runtime_present"] is False


def test_the_api_verdict_is_kept_for_the_receipt(monkeypatch) -> None:
    """The disagreement between the API and the Pod is the finding; losing it
    would make the receipt unable to show why this layer exists."""
    module = load_module()
    monkeypatch.setattr(module.httpx, "get", _fake_get({8001: 401, 8002: 401}))
    monkeypatch.setattr(
        module, "_ORIGINAL_SNAPSHOT", lambda _t, _p: {"runtime_present": False, "ports": []}
    )
    snap = module.snapshot_with_proxy_readiness(object(), "pod1")
    assert snap["runtime_present_per_api"] is False
    assert snap["control_ports_reachable"] == {8001: True, 8002: True}
    assert snap["ports"] == []


def test_both_control_ports_are_required(monkeypatch) -> None:
    module = load_module()
    assert set(module.v10.REQUIRED_CONTROL_PORTS) == {8001, 8002}


def test_v15_reuses_the_v14_pipeline_instead_of_reimplementing_it() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert functions == {
        "main",
        "control_port_reachable",
        "snapshot_with_proxy_readiness",
    }, functions
    assert "v14.main()" in source
    assert "[REDACTED]" not in source


def test_the_original_snapshot_is_bound_before_the_patch(monkeypatch) -> None:
    module = load_module()
    assert module._ORIGINAL_SNAPSHOT is not module.snapshot_with_proxy_readiness
    monkeypatch.setattr(module.httpx, "get", _fake_get({8001: 401, 8002: 401}))
    calls = []

    def original(_t, _p):
        calls.append(1)
        return {}

    monkeypatch.setattr(module, "_ORIGINAL_SNAPSHOT", original)
    module.v10.runtime_snapshot = module.snapshot_with_proxy_readiness
    try:
        module.snapshot_with_proxy_readiness(object(), "pod1")
    finally:
        module.v10.runtime_snapshot = module._ORIGINAL_SNAPSHOT
    assert calls == [1], "the original snapshot must run exactly once"
