from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts"
SCRIPT = SCRIPTS / "run_stage1_v29_r2_v11_fast_fail_hosts.py"
V10 = SCRIPTS / "run_stage1_v29_r2_v10_runtime_ready.py"


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_v11_fast_fail", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_v11_fails_fast_and_draws_wider_than_v10() -> None:
    module = load_module()
    assert module.STARTUP_TIMEOUT_SECONDS == 360
    assert module.MAX_STARTUP_ATTEMPTS == 7
    assert module.STARTUP_TIMEOUT_SECONDS < module.v10.STARTUP_TIMEOUT_SECONDS
    assert module.MAX_STARTUP_ATTEMPTS > module.v10.MAX_STARTUP_ATTEMPTS


def test_v11_keeps_the_same_wall_clock_budget_as_v10() -> None:
    """A wider draw is only free if it does not extend the campaign."""
    module = load_module()
    v11_budget = module.STARTUP_TIMEOUT_SECONDS * module.MAX_STARTUP_ATTEMPTS
    v10_budget = module.v10.STARTUP_TIMEOUT_SECONDS * module.v10.MAX_STARTUP_ATTEMPTS
    assert v11_budget <= v10_budget * 1.1
    assert v11_budget < module.v10.base.MAX_TOTAL_SECONDS


def test_v11_cutoff_clears_every_healthy_start_ever_measured() -> None:
    """The cutoff must not be able to kill a host that was going to work."""
    module = load_module()
    healthy: list[float] = []
    for pointer in module.STARTUP_BUDGET_EVIDENCE:
        receipt_path = ROOT / pointer
        if not receipt_path.exists():
            continue
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("verdict") == "READY":
            healthy.append(float(receipt["runtime_ready_seconds"]))
    assert healthy, "no READY probe receipt found to justify the cutoff"
    assert max(healthy) * 4 < module.STARTUP_TIMEOUT_SECONDS


def _identifiers(tree: ast.AST) -> set[str]:
    """Names actually referenced in code, ignoring prose in docstrings."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            found.add(node.arg)
    return found


def test_v11_removes_every_curl_transport_binding() -> None:
    """A curl transport left anywhere reintroduces the child-process dependency
    that leaked a Pod (WinError 8) and killed a campaign (WinError 1455)."""
    module = load_module()
    source = SCRIPT.read_text(encoding="utf-8")
    assert "v10.RunPodCurlTransport = RunPodHttpxTransport" in source
    assert "v10.base.RunPodCurlTransport = RunPodHttpxTransport" in source
    assert not hasattr(module.RunPodHttpxTransport, "_curl")


def test_httpx_transport_matches_the_curl_transport_surface() -> None:
    """It is a substitute, not a rewrite: same methods, same error vocabulary."""
    module = load_module()
    import runpod_curl_transport_v2 as curl_module

    curl_api = {
        name
        for name in vars(curl_module.RunPodCurlTransport)
        if not name.startswith("_")
    }
    httpx_api = {
        name for name in vars(module.RunPodHttpxTransport) if not name.startswith("_")
    }
    assert curl_api == httpx_api, curl_api ^ httpx_api

    transport_source = (
        SCRIPT.with_name("runpod_httpx_transport.py").read_text(encoding="utf-8")
    )
    # create_once_or_reconcile treats an ambiguous create as reconcilable only
    # when the message contains this phrase.
    assert "transport failure" in transport_source
    assert "subprocess" not in transport_source
    assert "shutil.which" not in transport_source


class _FiveHundredThenOk:
    """POST /v1/pods answers 500 once, then succeeds -- the observed behaviour."""

    def __init__(self, *, pod_exists_after_500: bool = False) -> None:
        self.create_calls = 0
        self.reconcile_calls = 0
        self._pod_exists = pod_exists_after_500

    def reconcile_unique_pod(self, name):
        # The first call is create_once_or_reconcile's own pre-create check, which
        # must find nothing; a Pod can only appear once the 500 has been answered.
        self.reconcile_calls += 1
        if self.reconcile_calls == 1:
            return None
        return {"id": "adopted1", "name": name} if self._pod_exists else None

    def create_pod(self, payload):
        self.create_calls += 1
        if self.create_calls == 1:
            raise RuntimeError("RunPod Pod create failed with status 500: upstream error")
        return {"id": "created1", "name": payload["name"]}


def test_transient_500_does_not_throw_away_the_remaining_host_draws(monkeypatch) -> None:
    module = load_module()
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    transport = _FiveHundredThenOk()
    pod, reconciled = module.create_tolerating_server_errors(
        transport, payload={"name": "p"}, name="p"
    )
    assert pod["id"] == "created1"
    assert reconciled is False
    assert transport.create_calls == 2


def test_a_500_that_did_create_a_pod_is_adopted_not_duplicated(monkeypatch) -> None:
    """The v9 critique's rule: confirm from inventory before ever trying again."""
    module = load_module()
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    transport = _FiveHundredThenOk(pod_exists_after_500=True)
    pod, reconciled = module.create_tolerating_server_errors(
        transport, payload={"name": "p"}, name="p"
    )
    assert pod["id"] == "adopted1"
    assert reconciled is True
    assert transport.create_calls == 1  # never retried once a Pod was found


def test_non_5xx_create_failures_still_abort(monkeypatch) -> None:
    module = load_module()
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)

    class Rejecting:
        def reconcile_unique_pod(self, name):
            return None

        def create_pod(self, payload):
            raise RuntimeError("RunPod Pod create failed with status 400: bad request")

    try:
        module.create_tolerating_server_errors(Rejecting(), payload={"name": "p"}, name="p")
    except RuntimeError as exc:
        assert "400" in str(exc)
        return
    raise AssertionError("a 400 must not be retried")


def test_the_original_create_is_bound_before_the_patch(monkeypatch) -> None:
    """Resolving it at call time would recurse into the wrapper forever."""
    module = load_module()
    assert module._ORIGINAL_CREATE is not module.create_tolerating_server_errors
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    module.v10.base.create_once_or_reconcile = module.create_tolerating_server_errors
    transport = _FiveHundredThenOk()
    pod, _ = module.create_tolerating_server_errors(transport, payload={"name": "p"}, name="p")
    assert pod["id"] == "created1"


def test_v11_reuses_the_v10_pipeline_instead_of_reimplementing_it() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert functions == {
        "main",
        "create_tolerating_server_errors",
        "frugal_transfer_config",
    }, functions
    used = _identifiers(tree)
    # v11 wraps create_once_or_reconcile, so naming it is expected. What it must
    # never do is build its own payload or call create_pod itself.
    for forbidden in ("build_payload", "create_pod"):
        assert forbidden not in used, forbidden
    assert "v10.main()" in SCRIPT.read_text(encoding="utf-8")


def test_the_upload_config_is_smaller_than_v7s_in_both_dimensions() -> None:
    """MemoryError during the bundle upload was the third symptom of this host
    running out of commit charge; the fix must actually reduce what is buffered."""
    module = load_module()
    cfg = module.frugal_transfer_config(
        multipart_threshold=64 * 1024 * 1024,
        multipart_chunksize=64 * 1024 * 1024,
        max_concurrency=8,
        use_threads=True,
    )
    assert cfg.multipart_chunksize == module.UPLOAD_CHUNK_BYTES
    assert cfg.max_concurrency == module.UPLOAD_CONCURRENCY
    assert cfg.multipart_chunksize < 64 * 1024 * 1024
    assert cfg.max_concurrency < 8
    # A part larger than the threshold would silently become a single-part PUT
    # of the whole 1.11 GB file -- the exact allocation that failed.
    assert cfg.multipart_threshold <= cfg.multipart_chunksize
    assert cfg.use_threads is True


def test_the_audited_upload_function_itself_is_untouched() -> None:
    """The config is patched at the class so r2_upload_bundle stays v7's."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "v10.base.TransferConfig = frugal_transfer_config" in source
    assert "def r2_upload_bundle" not in source
    assert "upload_file" not in source


def test_v11_does_not_touch_ready_or_the_v4_qualifier() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    body = "\n".join(sorted(literals - {ast.get_docstring(tree) or ""}))
    for forbidden in ("ovisocr2-v29-assembly-ready.json", "assembly_qualification_http"):
        assert forbidden not in body, forbidden
    assert "[REDACTED]" not in SCRIPT.read_text(encoding="utf-8")


def test_v10_still_reads_the_constants_at_call_time() -> None:
    """The override only works because main() resolves these as globals."""
    tree = ast.parse(V10.read_text(encoding="utf-8"))
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    names = {node.id for node in ast.walk(main) if isinstance(node, ast.Name)}
    assert {"STARTUP_TIMEOUT_SECONDS", "MAX_STARTUP_ATTEMPTS"}.issubset(names)
    assigned = {
        target.id
        for node in ast.walk(main)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert not {"STARTUP_TIMEOUT_SECONDS", "MAX_STARTUP_ATTEMPTS"} & assigned
