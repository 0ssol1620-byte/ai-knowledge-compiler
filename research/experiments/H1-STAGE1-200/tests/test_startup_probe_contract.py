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
    / "probe_stage1_host_startup_discriminator_v1.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_startup_probe_v1", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


READY = {
    "assembly_id": "sha256:" + "a" * 64,
    "base_image_digest": "vllm/vllm-openai@sha256:" + "b" * 64,
    "container_disk_gb": 80,
    "maximum_hourly_rate_usd": "0.80",
    "qualification_state": "READY",
}


class PortlessTransport:
    def graphql(self, *, query, variables=None):
        return {"pod": {"desiredStatus": "RUNNING", "runtime": {"uptimeInSeconds": 0, "ports": []}}}

    def get_pod(self, pod_id: str):
        return {"desiredStatus": "RUNNING", "portMappings": None, "machineId": "m1"}


class ReadyTransport:
    def graphql(self, *, query, variables=None):
        return {"pod": {"desiredStatus": "RUNNING", "runtime": None}}

    def get_pod(self, pod_id: str):
        return {
            "desiredStatus": "RUNNING",
            "portMappings": {"8001": 21001, "8002": 21002},
            "machineId": "m1",
            "lastStatusChange": "Rented by User",
        }


def test_portless_running_pod_is_not_runtime_ready() -> None:
    """The exact shape of all four v10 hosts: RUNNING, uptime 0, no ports."""
    module = load_module()
    snapshot = module.runtime_snapshot(PortlessTransport(), "pod123")
    assert snapshot["runtime_present"] is False
    assert snapshot["desired_status"] == "RUNNING"
    assert snapshot["uptime_seconds"] == 0


def test_rest_port_mappings_make_the_pod_ready() -> None:
    module = load_module()
    snapshot = module.runtime_snapshot(ReadyTransport(), "pod123")
    assert snapshot["runtime_present"] is True
    assert snapshot["machine_id"] == "m1"


def test_minimal_arm_carries_no_tavonel_payload() -> None:
    """The whole point of `minimal`: nothing of ours is in the container start."""
    module = load_module()
    payload = module.build_payload(arm="minimal", ready=READY, name="probe-minimal")
    assert not any(key.startswith("TAVONEL_") for key in payload["env"])
    assert module.env_bytes(payload) < 200
    assert "http.server 8001" in payload["dockerEntrypoint"][2]
    assert "http.server 8002" in payload["dockerEntrypoint"][2]


def test_payload_arm_differs_from_minimal_only_by_env() -> None:
    module = load_module()
    minimal = module.build_payload(arm="minimal", ready=READY, name="probe-minimal")
    payload = module.build_payload(arm="payload", ready=READY, name="probe-payload")
    assert payload["dockerEntrypoint"] == minimal["dockerEntrypoint"]
    assert module.env_bytes(payload) > 20_000


def _v10_bootstrap_command() -> str:
    v10_script = SCRIPT.with_name("run_stage1_v29_r2_v10_runtime_ready.py")
    tree = ast.parse(v10_script.read_text(encoding="utf-8"))
    build = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_payload"
    )
    for node in ast.walk(build):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "bootstrap_command"
            for target in node.targets
        ):
            return str(ast.literal_eval(node.value))
    raise AssertionError("v10 build_payload has no bootstrap_command")


def test_v10_arm_reproduces_the_v10_entrypoint() -> None:
    """The control arm is only a control if it is byte-identical to v10."""
    module = load_module()
    assert _v10_bootstrap_command() == module.V10_ENTRYPOINT
    payload = module.build_payload(arm="v10", ready=READY, name="probe-v10")
    assert payload["dockerEntrypoint"][2] == module.V10_ENTRYPOINT
    assert payload["env"]["TAVONEL_STAGE1_DRIVER_GZ_B64"]


def test_every_arm_requests_the_same_control_ports_as_v10() -> None:
    module = load_module()
    for arm in ("minimal", "payload", "v10"):
        payload = module.build_payload(arm=arm, ready=READY, name=f"probe-{arm}")
        assert payload["ports"] == ["8001/http", "8002/http"]
        assert payload["cloudType"] == "SECURE"
        assert payload["volumeInGb"] == 0
        assert payload["interruptible"] is False


def test_probe_creates_at_most_one_pod_and_never_blind_retries() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    # Either audited entry point is acceptable; both reconcile by unique name
    # before they ever try again. A bare create_pod is not.
    reconciling = {"create_once_or_reconcile", "create_tolerating_server_errors"}
    creates = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in reconciling | {"create_pod"}
    ]
    assert len(creates) == 1
    assert creates[0].func.attr in reconciling
    # The 5xx-tolerant wrapper must be v11's, not a second implementation here
    # that could drift into the blind retry the v9 critique forbade.
    if creates[0].func.attr == "create_tolerating_server_errors":
        assert isinstance(creates[0].func.value, ast.Name)
        assert creates[0].func.value.id == "v11"
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert "create_tolerating_server_errors" not in defined
    loops = [node for node in ast.walk(main) if isinstance(node, (ast.For, ast.While))]
    assert not any(creates[0] in list(ast.walk(loop)) for loop in loops)


def test_probe_writes_active_state_before_the_paid_create() -> None:
    """Critic finding from v9: a crash after create must still be recoverable."""
    source = SCRIPT.read_text(encoding="utf-8")
    create_at = min(
        source.index(marker)
        for marker in ("create_once_or_reconcile(", "create_tolerating_server_errors(")
        if marker in source
    )
    assert source.index("internal-active-state.json") < create_at


def test_probe_never_touches_ground_truth_bundle_or_r2() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "r2_upload_bundle",
        "r2_delete_verify",
        "make_r2_client",
        "base.BUNDLE",
        "import boto3",
        "import tarfile",
        "[REDACTED]",
    ):
        assert forbidden not in source, forbidden
    module = load_module()
    payload = module.build_payload(arm="v10", ready=READY, name="probe-v10")
    # The bundle URL is synthetic and unreachable, so even the v10 entrypoint
    # cannot pull the cohort if the container does start.
    assert payload["env"]["TAVONEL_STAGE1_BUNDLE_URL"].startswith("https://probe.invalid/")


class ProcessExhaustedTransport:
    """Stands in for RunPodCurlTransport once CreateProcess starts failing."""

    def graphql(self, *, query, variables=None):
        raise OSError(8, "insufficient resources to process this command")

    def get_pod(self, pod_id: str):
        raise OSError(8, "insufficient resources to process this command")


def test_runtime_snapshot_propagates_process_exhaustion_rather_than_reporting_ready() -> None:
    """The failure that leaked pod b3rk1h2v9ciis2: curl could not be spawned.

    runtime_snapshot must not swallow OSError into an empty-port snapshot -- an
    empty snapshot is indistinguishable from a healthy portless Pod, and the
    caller has to know the difference to keep polling instead of giving up.
    """
    module = load_module()
    try:
        module.runtime_snapshot(ProcessExhaustedTransport(), "pod123")
    except OSError:
        return
    raise AssertionError("runtime_snapshot swallowed OSError")


def test_poll_loop_survives_read_errors_instead_of_abandoning_a_billing_pod() -> None:
    module = load_module()
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    handlers = [
        handler
        for node in ast.walk(main)
        if isinstance(node, ast.Try)
        for handler in node.handlers
    ]
    caught: set[str] = set()
    for handler in handlers:
        expr = handler.type
        parts = expr.elts if isinstance(expr, ast.Tuple) else [expr]
        for part in parts:
            if isinstance(part, ast.Name):
                caught.add(part.id)
            elif isinstance(part, ast.Attribute):
                caught.add(part.attr)
    assert {"OSError", "RuntimeError"}.issubset(caught)
    assert hasattr(module, "HttpxPodClient")


def test_cleanup_does_not_share_a_failure_mode_with_the_curl_transport() -> None:
    """Cleanup must not need a child process, because that is what broke."""
    module = load_module()
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    tries = [node for node in ast.walk(main) if isinstance(node, ast.Try) and node.finalbody]
    final_calls = [
        stmt
        for node in tries
        for stmt in ast.walk(ast.Module(body=node.finalbody, type_ignores=[]))
        if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute)
    ]
    targets = {
        stmt.func.value.id
        for stmt in final_calls
        if (stmt.func.attr.startswith("delete") or stmt.func.attr.startswith("verify"))
        and isinstance(stmt.func.value, ast.Name)
    }
    # Every removal in the cleanup block -- Pod and registry auth alike -- must go
    # through the httpx client. RegistryAuthClient shells out to curl, which is
    # the exact failure mode that leaked a Pod, and a leaked auth object holds a
    # credential on RunPod's side.
    assert targets == {"reader"}, targets
    for name in (
        "delete_pod",
        "verify_deleted",
        "get_pod",
        "graphql",
        "delete_registry_auth",
        "verify_registry_auth_deleted",
    ):
        assert hasattr(module.HttpxPodClient, name), name


def test_registry_auth_is_removed_even_when_the_pod_create_fails() -> None:
    """RunPod answers 500 for a non-Docker-Hub image with no auth, and that path
    still has an auth object to clean up."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    handlers = [
        handler
        for node in ast.walk(main)
        if isinstance(node, ast.Try)
        for handler in node.handlers
    ]
    cleanup_in_handler = {
        stmt.func.attr
        for handler in handlers
        for stmt in ast.walk(ast.Module(body=handler.body, type_ignores=[]))
        if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute)
    }
    assert "delete_registry_auth" in cleanup_in_handler
    assert "verify_registry_auth_deleted" in cleanup_in_handler


def test_registry_token_is_read_by_label_and_never_printed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "registry_auth_token_label" in source
    assert "read_labeled_secret(" in source
    # The secret is bound to `secret`; it must not reach any print or receipt.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id == "print":
            names = {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}
            assert "secret" not in names
            assert "password" not in names


def test_probe_deletes_and_verifies_absence_on_every_exit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    tries = [node for node in ast.walk(main) if isinstance(node, ast.Try) and node.finalbody]
    finals = [
        stmt
        for node in tries
        for stmt in ast.walk(ast.Module(body=node.finalbody, type_ignores=[]))
    ]
    attrs = {
        stmt.func.attr
        for stmt in finals
        if isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Attribute)
    }
    assert {"delete_pod", "verify_deleted"}.issubset(attrs)
