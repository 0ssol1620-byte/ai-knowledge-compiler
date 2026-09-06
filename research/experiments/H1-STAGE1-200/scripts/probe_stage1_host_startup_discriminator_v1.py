#!/usr/bin/env python3
"""Measure when a Secure RTX 4090 Pod on the v29 base image binds 8001/8002.

The v10 campaign (run-72ff5d21f453) lost four hosts in a row: every attempt sat
at desiredStatus RUNNING with uptime 0 and no public ports, and every attempt
ended at the 600 s cutoff (603.5 / 616.5 / 607.3 / 606.2).  The only host that
ever bound ports did so in 102 s (v8, run-e2b132a1c61f).  Two explanations fit
that shape and they demand opposite fixes:

  A  the cold image pull is longer than the 600 s cutoff, so v10 deletes hosts
     that were still coming up  ->  raise the cutoff
  B  our dockerEntrypoint or env payload stops the container from starting at
     all  ->  raising the cutoff burns budget and changes nothing

This probe separates them and does nothing else.  It never fetches the bundle,
never uploads to R2, never mounts ground truth, and never runs Stage-1.

Arms
  minimal   trivial entrypoint that binds 8001/8002, no TAVONEL env payload.
            Times pull + container start + port bind on their own.
  payload   the same trivial entrypoint plus the full v10 env payload, so the
            27 KB of base64 env is the only difference from `minimal`.
  v10       the v10 dockerEntrypoint and env unchanged, as the control.

Read `minimal` first:
  ports in ~2 min   -> pull and container start are fine  -> hypothesis B
  ports in 15-25 min -> the pull is the bottleneck        -> hypothesis A
  no ports at all    -> neither; the failure is in create, not in our payload

Exactly one Pod is created per invocation.  A create that returns a transport
error is reconciled by unique name and never blindly retried.  The Pod is
deleted and its absence verified on every exit path, including Ctrl-C.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import secrets
import signal
import sys
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import FrameType
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[4]
SCRATCH = ROOT / ".chatgpt2codex"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRATCH))

from runpod_registry_auth_v27 import RegistryAuthClient, read_labeled_secret  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runpod_httpx_transport import RunPodHttpxTransport  # noqa: E402

BASE_PATH = Path(__file__).with_name("run_stage1_v29_r2_v7_r2_verified.py")
_spec = importlib.util.spec_from_file_location("stage1_v7_probe", BASE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v7 module cannot be loaded")
base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = base
_spec.loader.exec_module(base)

V11_PATH = Path(__file__).with_name("run_stage1_v29_r2_v11_fast_fail_hosts.py")
_v11_spec = importlib.util.spec_from_file_location("stage1_v11_for_probe", V11_PATH)
if _v11_spec is None or _v11_spec.loader is None:
    raise RuntimeError("Stage-1 v11 module cannot be loaded")
v11 = importlib.util.module_from_spec(_v11_spec)
sys.modules[_v11_spec.name] = v11
_v11_spec.loader.exec_module(v11)

# RunPod answers POST /v1/pods with 500 "This machine does not have the resources
# to deploy your pod" when it schedules onto a host that cannot take the Pod. The
# probe used to die on the first one and throw away a draw that cost nothing: no
# Pod is created, so a retry is free and RunPod picks a different machine. v11
# already solved this correctly -- reconcile by unique name, and only try again
# once the inventory proves nothing was created -- so the probe borrows it rather
# than growing a second implementation that could drift into a blind retry.
v11.CREATE_5XX_ATTEMPTS = 6

V4_DRIVER = Path(__file__).with_name("stage1_same_pod_driver_v4_observability.py")
QUALIFIER = base.QUALIFIER
REQUIRED_CONTROL_PORTS = frozenset({8001, 8002})
POLL_SECONDS = 10
HARD_MAX_TIMEOUT_SECONDS = 60 * 60
OUT_ROOT = SCRATCH / "formal-runtime-v29" / "startup-probe"
REGISTRY_AUTH_URL = "https://rest.runpod.io/v1/containerregistryauth"

# A presigned R2 URL is ~700 chars.  The `payload` arm needs the env to be the
# right SIZE, not functional -- its entrypoint never reads the bundle.  A
# synthetic same-order-of-magnitude string keeps the arm honest without an
# external write, and the receipt records that it was synthetic.
SYNTHETIC_BUNDLE_URL = "https://probe.invalid/synthetic?placeholder=" + ("x" * 640)

GRAPHQL_POD = """
query ProbePod($podId: String!) {
  pod(input: {podId: $podId}) {
    id
    desiredStatus
    runtime {
      uptimeInSeconds
      ports { privatePort publicPort type }
    }
  }
}
"""


def now() -> str:
    return datetime.now(UTC).isoformat()


def port_records_from_runtime(runtime: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not isinstance(runtime, dict):
        return records
    for item in runtime.get("ports") or []:
        if not isinstance(item, dict):
            continue
        private = item.get("privatePort")
        if private is None:
            continue
        records.append(
            {
                "privatePort": int(private),
                "publicPortPresent": item.get("publicPort") is not None,
                "type": item.get("type"),
            }
        )
    return records


def port_records_from_rest(pod: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    mappings = pod.get("portMappings")
    if isinstance(mappings, dict):
        for key, value in mappings.items():
            try:
                private = int(key)
            except (TypeError, ValueError):
                continue
            records.append({"privatePort": private, "publicPortPresent": value is not None})
    records.extend(port_records_from_runtime(pod.get("runtime")))
    return records


def merge_ports(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            private = int(item["privatePort"])
            current = merged.setdefault(private, dict(item))
            if item.get("publicPortPresent"):
                current["publicPortPresent"] = True
            if item.get("type") and not current.get("type"):
                current["type"] = item["type"]
    return [merged[key] for key in sorted(merged)]


def control_ports_ready(ports: list[dict[str, Any]]) -> bool:
    ready = {
        int(item["privatePort"])
        for item in ports
        if item.get("publicPortPresent") is True
        and int(item["privatePort"]) in REQUIRED_CONTROL_PORTS
    }
    return REQUIRED_CONTROL_PORTS.issubset(ready)


def runtime_snapshot(transport: RunPodHttpxTransport, pod_id: str) -> dict[str, Any]:
    """Same dual-source read as v10: GraphQL first, REST fills the gaps."""
    sources: list[str] = []
    desired_status: object = None
    ports: list[dict[str, Any]] = []
    uptime_seconds: int | None = None
    machine_id: object = None
    last_status_change: object = None

    try:
        payload = transport.graphql(query=GRAPHQL_POD, variables={"podId": pod_id})
        pod = payload.get("pod") if isinstance(payload, dict) else None
        if isinstance(pod, dict):
            sources.append("graphql")
            desired_status = pod.get("desiredStatus")
            runtime = pod.get("runtime")
            if isinstance(runtime, dict):
                uptime_seconds = int(runtime.get("uptimeInSeconds") or 0)
                ports = merge_ports(ports, port_records_from_runtime(runtime))
    except RuntimeError:
        sources.append("graphql_error")

    try:
        rest = transport.get_pod(pod_id)
    except RuntimeError:
        sources.append("rest_error")
        rest = None
    if isinstance(rest, dict):
        sources.append("rest")
        if desired_status is None:
            desired_status = rest.get("desiredStatus")
        machine_id = rest.get("machineId")
        last_status_change = rest.get("lastStatusChange")
        ports = merge_ports(ports, port_records_from_rest(rest))
        rest_runtime = rest.get("runtime")
        if uptime_seconds is None and isinstance(rest_runtime, dict):
            uptime_seconds = int(rest_runtime.get("uptimeInSeconds") or 0)

    return {
        "desired_status": desired_status,
        "ports": ports,
        "runtime_present": control_ports_ready(ports),
        "uptime_seconds": uptime_seconds,
        "machine_id": machine_id,
        "last_status_change": last_status_change,
        "sources": sources,
    }


def build_v10_env(ready: dict[str, Any], control_token: str) -> dict[str, str]:
    """The v10 env payload, byte-for-byte in shape, with a synthetic bundle URL."""
    qualifier_b64, qualifier_sha = base.gzip_b64(QUALIFIER)
    driver_b64, _ = base.gzip_b64(V4_DRIVER)
    runner_b64, runner_sha = base.gzip_b64(base.RUNNER)
    contract_b64, contract_sha = base.gzip_b64(base.INPUT_CONTRACT)
    security_b64, _ = base.canonical_b64(base.read_object(base.SECURITY_RECEIPT))
    model_b64, _ = base.canonical_b64(base.read_object(base.MODEL_RECEIPT))
    return {
        "FOLYNTA_QUALIFICATION_ONLY": "1",
        "HF_HOME": "/opt/tavonel/hf-cache",
        "TAVONEL_ASSEMBLY_ID": str(ready["assembly_id"]),
        "TAVONEL_BASE_IMAGE_DIGEST": str(ready["base_image_digest"]),
        "TAVONEL_BOOTSTRAP_SHA256": qualifier_sha,
        "TAVONEL_SECURITY_RECEIPT_B64": security_b64,
        "TAVONEL_MODEL_RECEIPT_B64": model_b64,
        "TAVONEL_STAGE1_DRIVER_GZ_B64": driver_b64,
        "TAVONEL_QUALIFIER_GZ_B64": qualifier_b64,
        "TAVONEL_QUALIFIER_SHA256": qualifier_sha,
        "TAVONEL_STAGE1_RUNNER_GZ_B64": runner_b64,
        "TAVONEL_STAGE1_RUNNER_SHA256": runner_sha,
        "TAVONEL_INPUT_CONTRACT_GZ_B64": contract_b64,
        "TAVONEL_INPUT_CONTRACT_SHA256": contract_sha,
        "TAVONEL_STAGE1_BUNDLE_URL": SYNTHETIC_BUNDLE_URL,
        "TAVONEL_STAGE1_BUNDLE_SHA256": "sha256:" + "0" * 64,
        "TAVONEL_STAGE1_BUNDLE_BYTES": "0",
        "TAVONEL_STAGE1_CONTROL_TOKEN": control_token,
        "TAVONEL_MODEL_REVISION": "probe",
        "TAVONEL_ARTIFACT_MANIFEST_SHA256": "sha256:" + "0" * 64,
    }


MINIMAL_ENTRYPOINT = (
    "python3 -m http.server 8001 --bind 0.0.0.0 & "
    "python3 -m http.server 8002 --bind 0.0.0.0 & "
    "wait"
)

# The v29 qualifier dies before it ever reaches the model:
#   Error 804: forward compatibility was attempted on non supported HW
# NVIDIA's CUDA images ship a forward-compat libcuda under /usr/local/cuda/compat
# that only supports data-center GPUs. When ld.so prefers it over the host driver
# the container cannot init CUDA at all on a GeForce card such as the 4090.
# This arm records the state before and after removing that layer, so the fix is
# demonstrated on the real image rather than assumed. It touches nothing outside
# the container and never starts Stage-1.
CUDA_DIAG_ENTRYPOINT = (
    "mkdir -p /diag; "
    "{ "
    "echo '== nvidia-smi =='; nvidia-smi 2>&1 || true; "
    "echo '== /proc/driver/nvidia/version =='; cat /proc/driver/nvidia/version 2>&1 || true; "
    "echo '== compat dir =='; ls -la /usr/local/cuda/compat 2>&1 || true; "
    "echo '== ld.so.conf.d =='; ls -la /etc/ld.so.conf.d 2>&1; "
    "cat /etc/ld.so.conf.d/*.conf 2>&1 || true; "
    "echo '== LD_LIBRARY_PATH =='; echo \"$LD_LIBRARY_PATH\"; "
    "echo '== ldconfig libcuda BEFORE =='; ldconfig -p 2>&1 | grep -i libcuda || true; "
    "echo '== torch BEFORE =='; "
    "python3 -c 'import torch;print(\"available\", torch.cuda.is_available());"
    "print(\"count\", torch.cuda.device_count())' 2>&1 || true; "
    "echo '== remove compat =='; "
    "rm -f /etc/ld.so.conf.d/*compat*.conf 2>/dev/null || true; "
    "rm -rf /usr/local/cuda/compat 2>/dev/null || true; ldconfig 2>&1 || true; "
    "echo '== ldconfig libcuda AFTER =='; ldconfig -p 2>&1 | grep -i libcuda || true; "
    "echo '== torch AFTER =='; "
    "python3 -c 'import torch;print(\"available\", torch.cuda.is_available());"
    "print(\"count\", torch.cuda.device_count());print(\"name\", torch.cuda.get_device_name(0));"
    "print(\"capability\", torch.cuda.get_device_capability(0))' 2>&1 || true; "
    "} > /diag/report.txt 2>&1; "
    "cd /diag; "
    "python3 -m http.server 8001 --bind 0.0.0.0 & "
    "python3 -m http.server 8002 --bind 0.0.0.0 & "
    "wait"
)

V10_ENTRYPOINT = (
    "mkdir -p /opt/tavonel/stage1 && "
    "printf '%s' \"$TAVONEL_STAGE1_DRIVER_GZ_B64\" | base64 -d | gzip -d > "
    "/opt/tavonel/stage1/stage1_same_pod_driver_v4_observability.py && "
    "exec python3 /opt/tavonel/stage1/stage1_same_pod_driver_v4_observability.py"
)


def build_payload(*, arm: str, ready: dict[str, Any], name: str) -> dict[str, Any]:
    control_token = secrets.token_urlsafe(24)
    payload: dict[str, Any] = {
        "name": name,
        "imageName": str(ready["base_image_digest"]),
        "cloudType": "SECURE",
        "computeType": "GPU",
        "gpuTypeIds": [base.GPU],
        "gpuTypePriority": "availability",
        "gpuCount": 1,
        "containerDiskInGb": int(ready["container_disk_gb"]),
        "volumeInGb": 0,
        "ports": ["8001/http", "8002/http"],
        "interruptible": False,
        "allowedCudaVersions": ["12.8", "12.9"],
    }
    if arm == "cudadiag":
        payload["dockerEntrypoint"] = ["/bin/bash", "-lc", CUDA_DIAG_ENTRYPOINT]
        payload["env"] = {"FOLYNTA_QUALIFICATION_ONLY": "1"}
    elif arm == "minimal":
        payload["dockerEntrypoint"] = ["/bin/bash", "-lc", MINIMAL_ENTRYPOINT]
        payload["env"] = {"FOLYNTA_QUALIFICATION_ONLY": "1"}
    elif arm == "payload":
        payload["dockerEntrypoint"] = ["/bin/bash", "-lc", MINIMAL_ENTRYPOINT]
        payload["env"] = build_v10_env(ready, control_token)
    elif arm == "v10":
        payload["dockerEntrypoint"] = ["/bin/bash", "-lc", V10_ENTRYPOINT]
        payload["env"] = build_v10_env(ready, control_token)
    else:  # pragma: no cover - argparse constrains this
        raise RuntimeError(f"unknown arm {arm!r}")
    return payload


def env_bytes(payload: dict[str, Any]) -> int:
    env = payload.get("env")
    if not isinstance(env, dict):
        return 0
    return sum(len(str(k)) + len(str(v)) for k, v in env.items())


def select_credential(
    credential_file: Path, requested: str | None
) -> tuple[str, str, RunPodHttpxTransport]:
    labels = (requested,) if requested else ("Runpod_B", "Runpod_A")
    problems: list[str] = []
    for label in labels:
        assert label is not None
        key = read_labeled_secret(credential_file, label)
        # httpx, not curl: the create is the one call that can produce a billing
        # Pod, and it must not depend on spawning a process. It also quotes the
        # server's own words on an error, which a bare status code does not.
        transport = RunPodHttpxTransport(api_key=key)
        running = [
            pod for pod in transport.list_pods() if str(pod.get("desiredStatus", "")) == "RUNNING"
        ]
        if running:
            problems.append(f"{label} has {len(running)} RUNNING Pod(s)")
            continue
        balance, spend = base.spend_state(transport)
        if balance < Decimal("3.00"):
            problems.append(f"{label} balance {balance} below 3.00")
            continue
        print(f"[probe] credential={label} balance={balance} spend_per_hr={spend}", flush=True)
        return label, key, transport
    raise RuntimeError("no eligible RunPod credential: " + "; ".join(problems))


class HttpxPodClient:
    """In-process RunPod reads and deletes, with no child process.

    The first probe run leaked a Pod because RunPodCurlTransport shells out to
    curl for every call: the host ran out of commit charge, CreateProcess began
    failing with WinError 8, and the same failure took out the poll loop AND the
    cleanup that was supposed to handle it.  A cleanup path must not share a
    failure mode with the thing it cleans up after, so everything from create
    onwards runs through httpx instead.  Create still goes through the audited
    curl transport, because a create that cannot start is harmless.
    """

    def __init__(self, api_key: str, *, timeout: float = 45.0) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        self._timeout = timeout

    def graphql(self, *, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"query": query}
        if variables is not None:
            body["variables"] = variables
        response = httpx.post(
            base.GRAPHQL_URL, headers=self._headers, json=body, timeout=self._timeout
        )
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("errors"):
            raise RuntimeError("RunPod GraphQL query returned errors")
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def get_pod(self, pod_id: str) -> dict[str, Any]:
        response = httpx.get(
            f"{base.PODS_URL}/{pod_id}", headers=self._headers, timeout=self._timeout
        )
        if response.status_code == 404:
            raise RuntimeError("Pod not found")
        value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("RunPod pod read returned invalid data")
        return value

    def delete_pod(self, pod_id: str) -> int:
        response = httpx.delete(
            f"{base.PODS_URL}/{pod_id}", headers=self._headers, timeout=self._timeout
        )
        return response.status_code

    def raw_pod(self, pod_id: str) -> dict[str, Any]:
        """The whole REST record, unfiltered -- runtime_snapshot keeps only what
        it needs, and a stalled Pod's reason is usually in a field it drops."""
        response = httpx.get(
            f"{base.PODS_URL}/{pod_id}", headers=self._headers, timeout=self._timeout
        )
        return {"status_code": response.status_code, "body": response.json()}

    def logs(self, pod_id: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for suffix in ("logs", "systemLogs", "system-logs"):
            try:
                response = httpx.get(
                    f"{base.PODS_URL}/{pod_id}/{suffix}",
                    headers=self._headers,
                    timeout=self._timeout,
                )
                body: Any
                try:
                    body = response.json()
                except ValueError:
                    body = response.text[:4000]
                out[suffix] = {"status_code": response.status_code, "body": body}
            except (RuntimeError, OSError, httpx.HTTPError) as exc:
                out[suffix] = {"error": repr(exc)}
        return out

    def verify_deleted(self, pod_id: str) -> bool:
        response = httpx.get(base.PODS_URL, headers=self._headers, timeout=self._timeout)
        pods = response.json()
        if not isinstance(pods, list):
            raise RuntimeError("RunPod pod inventory is invalid")
        return not any(isinstance(pod, dict) and pod.get("id") == pod_id for pod in pods)

    def delete_registry_auth(self, auth_id: str) -> int:
        """A leaked auth object does not bill, but it does leave a credential on
        RunPod's side, so its removal must not depend on spawning a process."""
        response = httpx.delete(
            f"{REGISTRY_AUTH_URL}/{auth_id}", headers=self._headers, timeout=self._timeout
        )
        return response.status_code

    def verify_registry_auth_deleted(self, auth_id: str, name: str) -> bool:
        response = httpx.get(REGISTRY_AUTH_URL, headers=self._headers, timeout=self._timeout)
        if response.status_code != 200:
            raise RuntimeError(f"registry auth list failed with status {response.status_code}")
        records = response.json() or []
        if not isinstance(records, list):
            raise RuntimeError("registry auth inventory is invalid")
        return not any(
            isinstance(item, dict) and (item.get("id") == auth_id or item.get("name") == name)
            for item in records
        )


def fetch_diag_report(pod_id: str, *, attempts: int = 10) -> str | None:
    """Read /diag/report.txt back through RunPod's 8001 proxy.

    The port mapping can be published a moment before the proxy actually routes,
    so this retries rather than reading one 502 as a verdict.
    """
    url = f"https://{pod_id}-8001.proxy.runpod.net/report.txt"
    for _ in range(attempts):
        try:
            response = httpx.get(url, timeout=30, follow_redirects=True)
            if response.status_code == 200 and response.text.strip():
                return response.text
        except httpx.HTTPError:
            pass
        time.sleep(6)
    return None


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument(
        "--arm", choices=("minimal", "payload", "v10", "cudadiag"), default="minimal"
    )
    parser.add_argument("--credential-label", choices=("Runpod_A", "Runpod_B"), default=None)
    parser.add_argument("--timeout-seconds", type=int, default=30 * 60)
    parser.add_argument("--max-cost-usd", type=Decimal, default=Decimal("0.60"))
    parser.add_argument(
        "--container-disk-gb",
        type=int,
        default=None,
        help=(
            "Override READY's containerDiskInGb (80). RunPod's own words on a "
            "failed create are 'This machine does not have the resources to "
            "deploy your pod', so how much we ask for decides how many hosts can "
            "take us. Diagnosis only; recorded in the receipt."
        ),
    )
    parser.add_argument(
        "--gpu",
        default=None,
        help=(
            "Override the v29 GPU type. Diagnosis only: it answers whether the "
            "start failures are specific to the 4090 pool. It does NOT make the "
            "v29 assembly qualification valid on another GPU. Recorded in the receipt."
        ),
    )
    parser.add_argument(
        "--registry-auth-username",
        default=None,
        help=(
            "Registry username to attach as a temporary RunPod containerRegistryAuth. "
            "Required for any non-Docker-Hub image: create answers HTTP 500 without it."
        ),
    )
    parser.add_argument(
        "--registry-auth-token-label",
        default="Github",
        help="Label in the credential file holding the registry token. Never printed.",
    )
    parser.add_argument(
        "--dump-at-seconds",
        type=int,
        default=0,
        help=(
            "Once past this many seconds, write the unfiltered REST pod record and "
            "any log endpoint that answers to pod-diagnostics.json. 0 disables."
        ),
    )
    parser.add_argument(
        "--allowed-cuda-versions",
        nargs="+",
        default=None,
        help=(
            "Replace the campaign's allowedCudaVersions. Naming a version BELOW "
            "the image's CUDA deliberately lands the Pod on a host whose driver "
            "is older than the image needs -- the exact condition under which "
            "the vLLM image's forward-compat libcuda engages and GeForce "
            "returns CUDA 804. This is how the compat fix gets measured without "
            "waiting for that host to appear by chance. Diagnosis only."
        ),
    )
    parser.add_argument(
        "--no-cuda-version-filter",
        action="store_true",
        help=(
            "Drop allowedCudaVersions from the create payload. RunPod treats it "
            "as a host filter -- 'if not set, any CUDA version is acceptable' -- "
            "so the campaign's ['12.8','12.9'] narrows the eligible pool by an "
            "unmeasured amount. This measures how much. Diagnosis only: a Pod "
            "drawn without the filter can land on an older driver, which is the "
            "condition that produces CUDA 804 on GeForce."
        ),
    )
    parser.add_argument(
        "--cloud-type",
        choices=("SECURE", "COMMUNITY"),
        default=None,
        help=(
            "Override the v29 cloud type. COMMUNITY draws from a far larger host "
            "pool and is for diagnosis only: it answers questions about the GPU "
            "and the container image, never about Stage-1 output, which the v29 "
            "assembly pins to SECURE. Recorded in the receipt."
        ),
    )
    parser.add_argument(
        "--image",
        default=None,
        help=(
            "Override the v29 base image. Only for diagnosis: a tiny image that "
            "binds ports fast proves the host can start containers at all, which "
            "the v29 image alone cannot tell us. Recorded in the receipt."
        ),
    )
    args = parser.parse_args()

    if not 60 <= args.timeout_seconds <= HARD_MAX_TIMEOUT_SECONDS:
        raise RuntimeError(f"--timeout-seconds must be 60..{HARD_MAX_TIMEOUT_SECONDS}")

    ready = base.read_object(base.READY)
    if str(ready.get("qualification_state")) != "READY":
        raise RuntimeError("v29 READY is not in state READY")

    hourly = Decimal(str(ready.get("maximum_hourly_rate_usd", base.MAX_HOURLY)))
    if hourly > base.MAX_HOURLY:
        raise RuntimeError(f"hourly rate {hourly} exceeds ceiling {base.MAX_HOURLY}")
    worst_case = (hourly * Decimal(args.timeout_seconds) / Decimal(3600)).quantize(Decimal("0.01"))
    if worst_case > args.max_cost_usd:
        raise RuntimeError(
            f"worst-case cost {worst_case} exceeds --max-cost-usd {args.max_cost_usd}"
        )

    probe_id = uuid.uuid4().hex[:12]
    run_dir = OUT_ROOT / f"probe-{probe_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    name = f"tavonel-startup-probe-{probe_id}-{args.arm}"

    print(
        f"[probe] id={probe_id} arm={args.arm} name={name} "
        f"timeout={args.timeout_seconds}s worst_case_usd={worst_case}",
        flush=True,
    )
    print(f"[probe] run_dir={run_dir}", flush=True)

    label, api_key, transport = select_credential(
        args.credential_file.resolve(), args.credential_label
    )
    reader = HttpxPodClient(api_key)
    payload = build_payload(arm=args.arm, ready=ready, name=name)
    if args.image:
        payload["imageName"] = args.image
    if args.gpu:
        payload["gpuTypeIds"] = [args.gpu]
    if args.container_disk_gb:
        payload["containerDiskInGb"] = args.container_disk_gb
    if args.cloud_type:
        payload["cloudType"] = args.cloud_type
    if args.no_cuda_version_filter:
        payload.pop("allowedCudaVersions", None)
    elif args.allowed_cuda_versions:
        payload["allowedCudaVersions"] = list(args.allowed_cuda_versions)

    print(f"[probe] env_bytes={env_bytes(payload)} image={payload['imageName']}", flush=True)

    # The active-state file must exist BEFORE the paid create, so a crash between
    # create and the cleanup block still leaves enough to find and delete the Pod.
    active_path = run_dir / "internal-active-state.json"
    write_json(
        active_path,
        {
            "schema": "tavonel.stage1-startup-probe-active.v1",
            "active_credential_label": label,
            "active_pod_id": None,
            "pod_name": name,
            "arm": args.arm,
            "updated_at": now(),
        },
    )

    # RunPod answers HTTP 500 to a create that names a non-Docker-Hub registry
    # with no containerRegistryAuthId, so a registry control needs a real auth
    # object.  It holds a credential on RunPod's side and is deleted on the way
    # out, with absence verified, exactly like the Pod.
    auth_id: str | None = None
    auth_name: str | None = None
    auth_client: RegistryAuthClient | None = None
    if args.registry_auth_username:
        auth_client = RegistryAuthClient(runpod_api_key=api_key)
        auth_name = f"tavonel-v27-ghcr-{probe_id}"
        if auth_client.reconcile_unique_name(auth_name) is not None:
            raise RuntimeError("temporary registry auth name already exists before create")
        secret = read_labeled_secret(
            args.credential_file.resolve(), args.registry_auth_token_label
        )
        record = auth_client.create(
            name=auth_name, username=args.registry_auth_username, password=secret
        )
        auth_id = str(record["id"])
        del secret
        payload["containerRegistryAuthId"] = auth_id
        write_json(
            active_path,
            {
                "schema": "tavonel.stage1-startup-probe-active.v1",
                "active_credential_label": label,
                "active_pod_id": None,
                "active_registry_auth_id": auth_id,
                "active_registry_auth_name": auth_name,
                "pod_name": name,
                "arm": args.arm,
                "updated_at": now(),
            },
        )
        print(f"[probe] registry auth created name={auth_name}", flush=True)

    pod_id: str | None = None
    reconciled = False
    try:
        created, reconciled = v11.create_tolerating_server_errors(
            transport, payload=payload, name=name
        )
        pod_id = str(created.get("id"))
        if not pod_id or pod_id == "None":
            raise RuntimeError("probe Pod create returned no id")
        write_json(
            active_path,
            {
                "schema": "tavonel.stage1-startup-probe-active.v1",
                "active_credential_label": label,
                "active_pod_id": pod_id,
                "active_registry_auth_id": auth_id,
                "active_registry_auth_name": auth_name,
                "pod_name": name,
                "arm": args.arm,
                "updated_at": now(),
            },
        )
        print(f"[probe] created pod={pod_id} reconciled={reconciled}", flush=True)
    except BaseException:
        # A create that never produced a Pod still leaves the auth object behind.
        if auth_client is not None and auth_id and auth_name:
            try:
                reader.delete_registry_auth(auth_id)
                ok = reader.verify_registry_auth_deleted(auth_id, auth_name)
                print(f"[probe] registry auth removed after failed create: {ok}", flush=True)
            except (RuntimeError, OSError, httpx.HTTPError) as exc:
                print(f"[probe] WARNING registry auth cleanup failed: {exc!r}", flush=True)
        raise
    assert pod_id is not None

    timeline: list[dict[str, Any]] = []
    ready_at: float | None = None
    interrupted = False
    dumped = False

    def _on_signal(_sig: int, _frame: FrameType | None) -> None:
        nonlocal interrupted
        interrupted = True
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _on_signal)

    started = time.monotonic()
    read_errors = 0
    try:
        while True:
            elapsed = round(time.monotonic() - started, 3)
            try:
                snapshot = runtime_snapshot(reader, pod_id)
            except (RuntimeError, OSError, httpx.HTTPError) as exc:
                # A transient read failure must never end the run: the Pod is
                # already billing, and abandoning the loop is how one leaks.
                read_errors += 1
                print(f"[probe] t={elapsed:7.1f}s read error #{read_errors}: {exc!r}", flush=True)
                if elapsed >= args.timeout_seconds:
                    break
                time.sleep(POLL_SECONDS)
                continue
            record = {"elapsed_seconds": elapsed, "at": now(), **snapshot}
            timeline.append(record)
            write_json(
                run_dir / "timeline.json",
                {"schema": "tavonel.stage1-startup-probe-timeline.v1", "records": timeline},
            )
            public = [
                item["privatePort"] for item in snapshot["ports"] if item.get("publicPortPresent")
            ]
            print(
                f"[probe] t={elapsed:7.1f}s status={snapshot['desired_status']} "
                f"uptime={snapshot['uptime_seconds']} public_ports={public}",
                flush=True,
            )
            if args.dump_at_seconds and not dumped and elapsed >= args.dump_at_seconds:
                dumped = True
                try:
                    write_json(
                        run_dir / "pod-diagnostics.json",
                        {
                            "schema": "tavonel.stage1-startup-probe-diagnostics.v1",
                            "elapsed_seconds": elapsed,
                            "rest": reader.raw_pod(pod_id),
                            "logs": reader.logs(pod_id),
                        },
                    )
                    print(f"[probe] diagnostics dumped at {elapsed:.1f}s", flush=True)
                except (RuntimeError, OSError, httpx.HTTPError) as exc:
                    print(f"[probe] diagnostics dump failed: {exc!r}", flush=True)

            if snapshot["runtime_present"]:
                ready_at = elapsed
                print(f"[probe] RUNTIME READY at {elapsed:.1f}s", flush=True)
                if args.arm == "cudadiag":
                    # The whole point of this arm is the file, not the timing.
                    report = fetch_diag_report(pod_id)
                    if report:
                        (run_dir / "cuda-report.txt").write_text(report, encoding="utf-8")
                        print(f"[probe] cuda report saved ({len(report)} bytes)", flush=True)
                        print(report, flush=True)
                    else:
                        print("[probe] WARNING cuda report could not be fetched", flush=True)
                break
            if elapsed >= args.timeout_seconds:
                print(f"[probe] timeout at {elapsed:.1f}s without ports", flush=True)
                break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("[probe] interrupted; cleaning up", flush=True)
    finally:
        # Delete and verify go through httpx, and each is retried: this block is
        # the only thing standing between a failed run and a Pod that bills until
        # someone notices.
        cleanup_errors: list[str] = []
        absent = False
        for attempt in range(12):
            try:
                status = reader.delete_pod(pod_id)
                print(f"[probe] delete attempt={attempt} status={status}", flush=True)
            except (RuntimeError, OSError, httpx.HTTPError) as exc:
                cleanup_errors.append(f"delete[{attempt}]: {exc!r}")
            try:
                if reader.verify_deleted(pod_id):
                    absent = True
                    break
            except (RuntimeError, OSError, httpx.HTTPError) as exc:
                cleanup_errors.append(f"verify[{attempt}]: {exc!r}")
            time.sleep(5)

        auth_absent: bool | None = None
        if auth_client is not None and auth_id and auth_name:
            auth_absent = False
            for attempt in range(6):
                try:
                    reader.delete_registry_auth(auth_id)
                    if reader.verify_registry_auth_deleted(auth_id, auth_name):
                        auth_absent = True
                        break
                except (RuntimeError, OSError, httpx.HTTPError) as exc:
                    cleanup_errors.append(f"registry_auth[{attempt}]: {exc!r}")
                time.sleep(5)

        verdict = (
            "READY"
            if ready_at is not None
            else ("INTERRUPTED" if interrupted else "NO_PORTS_WITHIN_TIMEOUT")
        )
        receipt = {
            "schema": "tavonel.stage1-startup-probe-receipt.v1",
            "probe_id": probe_id,
            "arm": args.arm,
            "verdict": verdict,
            "runtime_ready_seconds": ready_at,
            "timeout_seconds": args.timeout_seconds,
            "poll_seconds": POLL_SECONDS,
            "credential_label": label,
            "pod_id": pod_id,
            "pod_name": name,
            "pod_create_reconciled_after_ambiguity": reconciled,
            "image_name": str(payload["imageName"]),
            "image_overridden": bool(args.image),
            "gpu_type_ids": list(payload["gpuTypeIds"]),
            "gpu_overridden": bool(args.gpu),
            "allowed_cuda_versions": payload.get("allowedCudaVersions"),
            "cuda_version_filter_dropped": bool(args.no_cuda_version_filter),
            "cloud_type": str(payload["cloudType"]),
            "cloud_type_overridden": bool(args.cloud_type),
            # A COMMUNITY host is not a v29 host: the assembly pins SECURE, so a
            # result from one diagnoses the image and the GPU and nothing else.
            "v29_qualification_valid_for_this_gpu": not args.gpu
            and payload["cloudType"] == "SECURE",
            "machine_id": timeline[-1].get("machine_id") if timeline else None,
            "container_disk_gb": int(payload["containerDiskInGb"]),
            "hourly_rate_usd": str(hourly),
            "env_bytes": env_bytes(payload),
            "env_bundle_url_synthetic": args.arm in {"payload", "v10"},
            "ground_truth_mounted": False,
            "bundle_fetched": False,
            "r2_touched": False,
            "record_count": len(timeline),
            "read_error_count": read_errors,
            "final_snapshot": timeline[-1] if timeline else None,
            "pod_delete_attempted": True,
            "pod_absence_verified": absent,
            "registry_auth_used": auth_client is not None,
            "registry_auth_name": auth_name,
            "registry_auth_absence_verified": auth_absent,
            "cleanup_errors": cleanup_errors,
            "completed_at": now(),
        }
        write_json(run_dir / "probe-receipt.json", receipt)
        if absent:
            active_path.unlink(missing_ok=True)
        print(json.dumps(receipt, indent=2, sort_keys=True), flush=True)
        print(f"[probe] receipt={run_dir / 'probe-receipt.json'}", flush=True)
        if not absent:
            print("[probe] WARNING: pod absence NOT verified; check the console", flush=True)

    return 0 if ready_at is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
