#!/usr/bin/env python3
"""Bounded development-only RunPod qualification for TAVONEL-R.

This is deliberately separate from historical release tooling. It reads the
Runpod_B value only into process memory, never serializes it, and uses only the
already-spent qualification smoke input. Failure/deadline paths stop paid GPU
capacity while preserving /workspace for bounded resume; deletion happens only
after sealed success evidence or an explicit cleanup request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from recovery_protocol import PRE_FREEZE_DRAFT, authorize_development_runtime_qualification
from runtime_attestation import RuntimeAttestation, canonical_digest, pin_files, sha256_file

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PRIVATE_ROOT = HERE / ".private" / "runpod-qualification"
RECEIPT_ROOT = HERE / "receipts" / "runtime-qualification"
CREDENTIAL_FILE = Path(r"D:\Github_API.txt")
RUNPOD_BASE = "https://rest.runpod.io/v1"
BASE_MAX_HOURLY_USD = 1.05
MAX_RUNTIME_SECONDS = 10_200
MAX_ESTIMATED_COST_USD = 4.00
SMOKE_ROOT = (
    REPO / "benchmark" / "datasets" / "private" / "runpod-2026-08-04" / "qualification-smoke"
)


def _required_executable(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"required local executable is unavailable: {name}")
    return str(Path(resolved).resolve())


def _required_ssh_keygen() -> str:
    # Some Windows 11 installations expose System32 OpenSSH ssh-keygen on PATH
    # but the binary returns 255 for ed25519 generation with no diagnostic. The
    # Git-for-Windows implementation is independently bundled and was verified
    # on this host. Prefer it when present, otherwise use the normal PATH lookup.
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        git_keygen = program_files / "Git" / "usr" / "bin" / "ssh-keygen.exe"
        if git_keygen.is_file():
            return str(git_keygen.resolve())
    return _required_executable("ssh-keygen.exe")


SSH_EXE = _required_executable("ssh.exe")
SCP_EXE = _required_executable("scp.exe")
SSH_KEYGEN_EXE = _required_ssh_keygen()


class QualificationRefused(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RoleSpec:
    role: str
    candidate_id: str
    model_id: str
    model_revision: str
    expected_model_manifest_sha256: str
    base_image: str
    bootstrap_relpath: str
    prompt_relpath: str
    extra_pin_paths: tuple[str, ...]

    @property
    def base_image_digest(self) -> str:
        return "sha256:" + self.base_image.rsplit("@sha256:", 1)[1]

    @property
    def model_artifact_digest(self) -> str:
        return "sha256:" + self.expected_model_manifest_sha256


@dataclass(frozen=True, slots=True)
class LocalPaths:
    role_dir: Path
    key: Path
    public_key: Path
    known_hosts: Path
    state: Path
    provider_journal: Path


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_text(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


def _one(pattern: str, text: str, *, label: str) -> str:
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    if len(matches) != 1:
        raise QualificationRefused(f"{label} must resolve exactly once; observed={len(matches)}")
    return matches[0]


def discover_role_spec(role: str) -> RoleSpec:
    if role == "strong":
        provision_rel = "tools/release/provision_folynta_mineru_recovery_worker.ps1"
        bootstrap_rel = "infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh"
        provision = _read_text(provision_rel)
        bootstrap = _read_text(bootstrap_rel)
        base_image = _one(
            r"imageName\s*=\s*'(runpod/pytorch@sha256:[0-9a-f]{64})'",
            provision,
            label="strong base image",
        )
        revision = _one(
            r'^MODEL_REVISION="([0-9a-f]{40,64})"$', bootstrap, label="strong model revision"
        )
        expected_manifest = _one(
            r"if \(\$modelSha -ne '([0-9a-f]{64})'\)",
            provision,
            label="strong model artifact manifest",
        )
        return RoleSpec(
            role=role,
            candidate_id="mineru-3.4.4-vlm-c1",
            model_id="opendatalab/MinerU2.5-Pro-2605-1.2B",
            model_revision=revision,
            expected_model_manifest_sha256=expected_manifest,
            base_image=base_image,
            bootstrap_relpath=bootstrap_rel,
            prompt_relpath="benchmark/runpod_eval/mineru_stage2.py",
            extra_pin_paths=(
                provision_rel,
                "benchmark/runpod_eval/artifact_manifest.py",
            ),
        )
    if role == "primary":
        provision_rel = "tools/release/provision_folynta_dedicated_recovery_pod.ps1"
        bootstrap_rel = "benchmark/runpod_eval/remote_bootstrap_paddle_recovery.sh"
        provision = _read_text(provision_rel)
        bootstrap = _read_text(bootstrap_rel)
        base_image = _one(
            r"imageName\s*=\s*'(runpod/pytorch@sha256:[0-9a-f]{64})'",
            provision,
            label="primary base image",
        )
        revision = _one(
            r'^model_revision="([0-9a-f]{40,64})"$', bootstrap, label="primary model revision"
        )
        expected_manifest = _one(
            r'^artifact_sha256="([0-9a-f]{64})"$',
            bootstrap,
            label="primary model artifact manifest",
        )
        return RoleSpec(
            role=role,
            candidate_id="paddleocr-vl-1.6-fastdeploy-c8",
            model_id="PaddlePaddle/PaddleOCR-VL-1.6",
            model_revision=revision,
            expected_model_manifest_sha256=expected_manifest,
            base_image=base_image,
            bootstrap_relpath=bootstrap_rel,
            prompt_relpath="benchmark/runpod_eval/paddleocr_vl_stage2.py",
            extra_pin_paths=(
                provision_rel,
                "benchmark/runpod_eval/paddle-fastdeploy-backend.yaml",
                "benchmark/runpod_eval/artifact_manifest.py",
                "benchmark/runpod_eval/input_contract.py",
                "benchmark/runpod_eval/isolated_case_process.py",
            ),
        )
    raise QualificationRefused(f"unsupported qualification role: {role}")


def qualification_input() -> tuple[Path, dict[str, Any]]:
    files = (
        sorted(path for path in SMOKE_ROOT.iterdir() if path.is_file())
        if SMOKE_ROOT.is_dir()
        else []
    )
    if not files:
        raise QualificationRefused("spent qualification smoke input is absent")
    smoke = files[0]
    manifest = {
        "schema": "tavonel.recovery.qualification_input.v1",
        "evidence_class": "SPENT_DEVELOPMENT_ONLY",
        "fresh": False,
        "page_count": 1,
        "input_sha256": sha256_file(smoke),
    }
    return smoke, manifest


def authorize_qualification() -> str:
    return authorize_development_runtime_qualification(
        protocol_state=PRE_FREEZE_DRAFT,
        fresh_cohort_opened=False,
        spent_development_only=True,
        pages=1,
        gpu_seconds=float(MAX_RUNTIME_SECONDS),
        external_cost_usd=float(MAX_ESTIMATED_COST_USD),
    )


def read_runpod_b(path: Path = CREDENTIAL_FILE) -> str:
    if not path.is_file():
        raise QualificationRefused("RunPod credential source is absent")
    pattern = re.compile(r"^\s*Runpod_B\s*[:=]\s*(\S+)\s*$", re.IGNORECASE)
    matches: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.match(line)
        if match:
            matches.append(match.group(1))
    if len(matches) != 1 or len(matches[0]) < 20:
        raise QualificationRefused("Runpod_B must appear exactly once and be well formed")
    return matches[0]


def _redacted_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    if re.search(r"(?i)(bearer\s+|runpod_b|api[_-]?key|authorization)", raw):
        raise QualificationRefused("secret-like material would enter a local receipt")
    return raw


def paths_for(role: str) -> LocalPaths:
    root = PRIVATE_ROOT / role
    return LocalPaths(
        role_dir=root,
        key=root / "id_ed25519",
        public_key=root / "id_ed25519.pub",
        known_hosts=root / "known_hosts",
        state=root / "state.json",
        provider_journal=root / "provider.jsonl",
    )


def ensure_keypair(paths: LocalPaths) -> str:
    paths.role_dir.mkdir(parents=True, exist_ok=True)
    if not paths.key.exists():
        # Executable and every argument are fixed locally; no user input reaches the shell.
        result = subprocess.run(  # noqa: S603
            [
                SSH_KEYGEN_EXE,
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(paths.key),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise QualificationRefused("ephemeral SSH key generation failed")
    if not paths.public_key.is_file() or not paths.key.is_file():
        raise QualificationRefused("ephemeral SSH keypair is incomplete")
    public = paths.public_key.read_text(encoding="ascii").strip()
    if not public.startswith("ssh-ed25519 "):
        raise QualificationRefused("ephemeral SSH public key is malformed")
    return public


class Provider:
    def __init__(self, api_key: str):
        self._api_key = api_key

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS RunPod origin
            RUNPOD_BASE + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - request URL is fixed HTTPS origin
                request, timeout=60
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise QualificationRefused(f"RunPod provider HTTP failure: {error.code}") from None
        except OSError as error:
            raise QualificationRefused(
                f"RunPod provider transport failure: {type(error).__name__}"
            ) from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise QualificationRefused("RunPod provider returned non-JSON data") from error

    def list_pods(self) -> list[dict[str, Any]]:
        value = self._request("GET", "/pods")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict) and isinstance(value.get("pods"), list):
            return [item for item in value["pods"] if isinstance(item, dict)]
        raise QualificationRefused("RunPod inventory response shape is invalid")

    def get_pod(self, pod_id: str) -> dict[str, Any] | None:
        value = self._request("GET", f"/pods/{pod_id}")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise QualificationRefused("RunPod pod response shape is invalid")
        return value

    def create_pod(self, payload: dict[str, Any]) -> dict[str, Any]:
        value = self._request("POST", "/pods", payload)
        if not isinstance(value, dict):
            raise QualificationRefused("RunPod creation response shape is invalid")
        return value

    def stop_pod(self, pod_id: str) -> None:
        # RunPod's Pod API exposes stop/start as explicit POST actions. Stopping
        # releases paid GPU capacity while retaining the normal /workspace
        # volume, which is the safe default for failed/expired qualification.
        self._request("POST", f"/pods/{pod_id}/stop")
        for _ in range(20):
            pod = self.get_pod(pod_id)
            if pod is None:
                return
            desired = str(pod.get("desiredStatus", "")).upper()
            if desired in {"EXITED", "STOPPED"}:
                return
            time.sleep(3)
        raise QualificationRefused("RunPod pod stop could not be verified")

    def start_pod(self, pod_id: str) -> None:
        self._request("POST", f"/pods/{pod_id}/start")

    def pod_billing(self, pod_id: str, *, start_time: str | None = None) -> list[dict[str, Any]]:
        query: dict[str, str] = {
            "podId": pod_id,
            "grouping": "podId",
            "bucketSize": "hour",
        }
        if start_time:
            query["startTime"] = start_time
        path = "/billing/pods?" + urllib.parse.urlencode(query)
        value = self._request("GET", path)
        if not isinstance(value, list):
            raise QualificationRefused("RunPod Pod billing response shape is invalid")
        rows = [item for item in value if isinstance(item, dict)]
        if any(str(item.get("podId", "")) not in {"", pod_id} for item in rows):
            raise QualificationRefused("RunPod Pod billing response crossed pod identity")
        return rows

    def delete_pod(self, pod_id: str) -> None:
        self._request("DELETE", f"/pods/{pod_id}")
        for _ in range(20):
            if self.get_pod(pod_id) is None:
                return
            time.sleep(3)
        raise QualificationRefused("RunPod pod deletion could not be verified")


def _start_command() -> str:
    return """set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends openssh-server git ca-certificates curl jq
rm -rf /var/lib/apt/lists/*
install -d -m 0700 /root/.ssh
printf '%s\n' "$PUBLIC_KEY" > /root/.ssh/authorized_keys
chmod 0600 /root/.ssh/authorized_keys
install -d -m 0755 /run/sshd /workspace/tavonel-r
exec /usr/sbin/sshd -D -e
"""


def provider_payload(spec: RoleSpec, public_key: str) -> dict[str, Any]:
    authorize_qualification()
    return {
        "name": f"tavonel-r-qual-{spec.role}-v1",
        "imageName": spec.base_image,
        "cloudType": "SECURE",
        "computeType": "GPU",
        "gpuTypeIds": ["NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 5090"],
        "gpuTypePriority": "availability",
        "gpuCount": 1,
        "containerDiskInGb": 100,
        "volumeInGb": 20,
        "volumeMountPath": "/workspace",
        "ports": ["22/tcp"],
        "supportPublicIp": True,
        "interruptible": False,
        "dockerEntrypoint": ["/bin/bash", "-lc"],
        "dockerStartCmd": [_start_command()],
        "env": {
            "PUBLIC_KEY": public_key,
            "TAVONEL_R_QUALIFICATION_ONLY": "1",
            "MINERU_API_MAX_CONCURRENT_REQUESTS": "1",
        },
    }


def _journal(paths: LocalPaths, event: str, **fields: Any) -> None:
    value = {"event": event, "observed_at_utc": utc_now(), **fields}
    line = _redacted_json(value)
    paths.role_dir.mkdir(parents=True, exist_ok=True)
    with paths.provider_journal.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def _write_state(paths: LocalPaths, value: dict[str, Any]) -> None:
    paths.role_dir.mkdir(parents=True, exist_ok=True)
    raw = _redacted_json(value)
    temp = paths.state.with_suffix(".tmp")
    temp.write_text(raw + "\n", encoding="utf-8")
    os.replace(temp, paths.state)


def _parse_time(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise QualificationRefused(f"qualification {label} timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QualificationRefused(f"qualification {label} timestamp must be timezone-aware")
    return parsed


def _consume_running_budget(state: dict[str, Any], *, now: datetime | None = None) -> float:
    """Conservatively charge local wall time against the role's total GPU cap."""
    current = now or datetime.now(UTC)
    started_raw = state.get("running_started_at_utc")
    if not started_raw:
        return 0.0
    started = _parse_time(started_raw, label="running start")
    elapsed = max(0.0, (current - started).total_seconds())
    remaining = float(state.get("remaining_gpu_seconds", MAX_RUNTIME_SECONDS))
    state["remaining_gpu_seconds"] = max(0.0, remaining - elapsed)
    state["gpu_seconds_consumed_local"] = float(
        state.get("gpu_seconds_consumed_local", 0.0)
    ) + elapsed
    state["running_started_at_utc"] = None
    return elapsed


def _billing_snapshot(provider: Provider, state: dict[str, Any]) -> dict[str, Any]:
    """Return Pod billing evidence, or an explicit unavailable result; never guess zero."""
    pod_id = str(state.get("pod_id") or "")
    try:
        rows = provider.pod_billing(pod_id, start_time=str(state.get("started_at_utc") or "") or None)
    except QualificationRefused as error:
        return {
            "status": "unavailable",
            "reason": str(error),
            "zero_spend_inferred": False,
        }
    amount = 0.0
    billed_ms = 0
    for row in rows:
        try:
            amount += float(row.get("amount") or 0.0)
        except (TypeError, ValueError) as error:
            raise QualificationRefused("RunPod Pod billing amount is invalid") from error
        try:
            billed_ms += int(row.get("timeBilledMs") or 0)
        except (TypeError, ValueError) as error:
            raise QualificationRefused("RunPod Pod billing duration is invalid") from error
    return {
        "status": "available",
        "provider_reported_amount_usd": amount,
        "provider_reported_time_billed_ms": billed_ms,
        "row_count": len(rows),
        "source": "runpod_pod_billing_api",
        "zero_spend_inferred": False,
    }


def _stop_preserving_cache(
    paths: LocalPaths,
    state: dict[str, Any],
    provider: Provider,
    *,
    phase: str,
    event: str,
    stderr_tail: str | None = None,
) -> dict[str, Any]:
    _consume_running_budget(state)
    pod_id = str(state["pod_id"])
    pod = provider.get_pod(pod_id)
    if pod is not None and str(pod.get("desiredStatus", "")).upper() not in {
        "EXITED",
        "STOPPED",
    }:
        provider.stop_pod(pod_id)
    billing = _billing_snapshot(provider, state)
    state.update(
        {
            "phase": phase,
            "provider_stopped": True,
            "provider_deleted": False,
            "last_pod_billing": billing,
            "stopped_at_utc": utc_now(),
        }
    )
    _write_state(paths, state)
    fields: dict[str, Any] = {
        "pod_id": pod_id,
        "billing_status": billing["status"],
        "remaining_gpu_seconds": state["remaining_gpu_seconds"],
    }
    if stderr_tail:
        fields["stderr_tail"] = stderr_tail[-2000:]
    _journal(paths, event, **fields)
    return billing


def _spawn_watchdog(role: str) -> int:
    python_exe = str(Path(os.__file__).resolve().parents[1] / "python.exe")
    command = [python_exe, str(Path(__file__).resolve()), "watchdog", "--role", role]
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    process = subprocess.Popen(  # noqa: S603
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )
    return int(process.pid)


def _read_state(paths: LocalPaths) -> dict[str, Any]:
    if not paths.state.is_file():
        raise QualificationRefused("qualification state does not exist; run start first")
    value = json.loads(paths.state.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualificationRefused("qualification state is malformed")
    return value


def _port22(pod: dict[str, Any]) -> int | None:
    mappings = pod.get("portMappings")
    if not isinstance(mappings, dict):
        return None
    value = mappings.get("22")
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def wait_ssh_ready(
    provider: Provider, pod_id: str, *, timeout_seconds: int = 600
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pod = provider.get_pod(pod_id)
        if pod is None:
            raise QualificationRefused("qualification pod disappeared before SSH readiness")
        host = str(pod.get("publicIp") or "")
        port = _port22(pod)
        if str(pod.get("desiredStatus")) == "RUNNING" and host and port is not None:
            return pod
        time.sleep(10)
    raise QualificationRefused("qualification pod did not become SSH-ready")


def _ssh_base(paths: LocalPaths, state: dict[str, Any]) -> list[str]:
    return [
        SSH_EXE,
        "-n",
        "-i",
        str(paths.key),
        "-p",
        str(state["port"]),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=4",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={paths.known_hosts}",
        f"root@{state['host']}",
    ]


def _refresh_ssh_endpoint(paths: LocalPaths, state: dict[str, Any]) -> dict[str, Any]:
    """Re-resolve the current SSH locator from the provider before every use.

    RunPod may assign a different public address/port after stop/start. The Pod
    id is the stable identity; a provisioning-time address is not.
    """
    pod_id = str(state.get("pod_id") or "")
    if not pod_id:
        raise QualificationRefused("qualification state has no pod identity")
    provider = Provider(read_runpod_b())
    pod = provider.get_pod(pod_id)
    if pod is None:
        raise QualificationRefused("qualification pod is absent while refreshing SSH endpoint")
    if str(pod.get("desiredStatus", "")).upper() != "RUNNING":
        raise QualificationRefused("qualification pod is not running while refreshing SSH endpoint")
    host = str(pod.get("publicIp") or "")
    port = _port22(pod)
    if not host or port is None:
        raise QualificationRefused("qualification provider has no current SSH endpoint")
    old_host = str(state.get("host") or "")
    try:
        old_port = int(state.get("port") or 0)
    except (TypeError, ValueError):
        old_port = 0
    if host != old_host or port != old_port:
        # Host keys belong to an ephemeral container instance. Remove only the
        # old provider-resolved host:port entry after the stable Pod id has been
        # re-confirmed, then let StrictHostKeyChecking=accept-new record the new
        # instance key on first connection.
        if old_host and old_port:
            subprocess.run(  # noqa: S603
                [
                    SSH_KEYGEN_EXE,
                    "-R",
                    f"[{old_host}]:{old_port}",
                    "-f",
                    str(paths.known_hosts),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        state.update({"host": host, "port": port})
        _write_state(paths, state)
        _journal(
            paths,
            "ssh_endpoint_refreshed",
            pod_id=pod_id,
            endpoint_changed=True,
        )
    return state


def ssh(paths: LocalPaths, state: dict[str, Any], command: str, *, check: bool = True) -> str:
    state = _refresh_ssh_endpoint(paths, state)
    # ssh.exe is fixed; remote commands are constructed from frozen local code/state.
    result = subprocess.run(  # noqa: S603
        [*_ssh_base(paths, state), command],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if check and result.returncode != 0:
        raise QualificationRefused("qualification SSH command failed")
    return result.stdout.strip()


def scp(paths: LocalPaths, state: dict[str, Any], source: Path, destination: str) -> None:
    state = _refresh_ssh_endpoint(paths, state)
    # scp.exe is fixed and source/destination are selected by this module only.
    result = subprocess.run(  # noqa: S603
        [
            SCP_EXE,
            "-i",
            str(paths.key),
            "-P",
            str(state["port"]),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=20",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={paths.known_hosts}",
            str(source),
            f"root@{state['host']}:{destination}",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise QualificationRefused(f"qualification upload failed: {source.name}")


def _launch_remote(paths: LocalPaths, state: dict[str, Any], command: str, pid_path: str) -> int:
    output = ssh(
        paths,
        state,
        f"nohup bash -lc {json.dumps(command)} >/workspace/tavonel-r/qualification.stdout.log "
        f"2>/workspace/tavonel-r/qualification.stderr.log </dev/null & echo $!",
    )
    line = output.splitlines()[-1].strip() if output else ""
    if not line.isdigit():
        raise QualificationRefused("remote qualification launch did not return a PID")
    pid = int(line)
    ssh(paths, state, f"printf '%s\\n' {pid} > {pid_path}")
    return pid


def _upload_common(paths: LocalPaths, state: dict[str, Any], spec: RoleSpec, smoke: Path) -> None:
    remote_dirs = (
        "mkdir -p /workspace/tavonel-r/runner /workspace/tavonel-r/input "
        "/workspace/tavonel-r/receipts"
    )
    ssh(
        paths,
        state,
        remote_dirs,
    )
    scp(paths, state, REPO / spec.bootstrap_relpath, "/workspace/tavonel-r/runner/bootstrap.sh")
    scp(
        paths,
        state,
        REPO / "benchmark/runpod_eval/artifact_manifest.py",
        "/workspace/tavonel-r/runner/artifact_manifest.py",
    )
    scp(paths, state, smoke, "/workspace/tavonel-r/input/input.jpg")
    if spec.role == "primary":
        for relative in (
            "benchmark/runpod_eval/paddle-fastdeploy-backend.yaml",
            "benchmark/runpod_eval/paddleocr_vl_stage2.py",
            "benchmark/runpod_eval/input_contract.py",
            "benchmark/runpod_eval/isolated_case_process.py",
        ):
            scp(paths, state, REPO / relative, "/workspace/tavonel-r/runner/" + Path(relative).name)
    else:
        scp(
            paths,
            state,
            REPO / "benchmark/runpod_eval/mineru_stage2.py",
            "/workspace/tavonel-r/runner/mineru_stage2.py",
        )


def _bootstrap_command(spec: RoleSpec) -> str:
    if spec.role == "strong":
        return (
            "chmod 700 /workspace/tavonel-r/runner/bootstrap.sh && "
            "RECEIPT_ROOT=/workspace/tavonel-r/receipts SYSTEM_PYTHON=/usr/bin/python3.11 "
            "bash /workspace/tavonel-r/runner/bootstrap.sh && "
            "touch /workspace/tavonel-r/BOOTSTRAP_COMPLETE"
        )
    return (
        "chmod 700 /workspace/tavonel-r/runner/bootstrap.sh && "
        "bash /workspace/tavonel-r/runner/bootstrap.sh "
        "/workspace/tavonel-r/runner/paddle-fastdeploy-backend.yaml "
        "/workspace/tavonel-r/receipts /workspace/tavonel-r/runner/artifact_manifest.py && "
        "touch /workspace/tavonel-r/BOOTSTRAP_COMPLETE"
    )


def start(role: str) -> dict[str, Any]:
    authorize_qualification()
    spec = discover_role_spec(role)
    smoke, input_manifest = qualification_input()
    paths = paths_for(role)
    if paths.state.exists():
        raise QualificationRefused("qualification state already exists; inspect/advance it instead")
    public_key = ensure_keypair(paths)
    api_key = read_runpod_b()
    provider = Provider(api_key)
    pod_name = f"tavonel-r-qual-{role}-v1"
    if any(str(item.get("name")) == pod_name for item in provider.list_pods()):
        raise QualificationRefused(
            "provider already contains the deterministic qualification pod name"
        )
    payload = provider_payload(spec, public_key)
    pod = provider.create_pod(payload)
    pod_id = str(pod.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}", pod_id):
        raise QualificationRefused("RunPod creation omitted a valid pod id")
    created_at = datetime.now(UTC)
    state = {
        "schema": "tavonel.recovery.runpod_qualification_state.v1",
        "role": role,
        "phase": "provisioning",
        "pod_id": pod_id,
        "host": "",
        "port": 0,
        "hourly_rate_usd": None,
        "base_image": spec.base_image,
        "started_at_utc": created_at.isoformat(),
        "running_started_at_utc": created_at.isoformat(),
        "remaining_gpu_seconds": float(MAX_RUNTIME_SECONDS),
        "gpu_seconds_consumed_local": 0.0,
        "hard_deadline_utc": (created_at + timedelta(seconds=MAX_RUNTIME_SECONDS)).isoformat(),
        "input_manifest_digest": canonical_digest(input_manifest),
        "fresh_confirmatory_observation": False,
        "provider_stopped": False,
        "provider_deleted": False,
    }
    _write_state(paths, state)
    _journal(paths, "pod_created", pod_id=pod_id, role=role)
    try:
        watchdog_pid = _spawn_watchdog(role)
        state["watchdog_pid"] = watchdog_pid
        _write_state(paths, state)
        _journal(paths, "cost_watchdog_started", pod_id=pod_id, watchdog_pid=watchdog_pid)
        ready = wait_ssh_ready(provider, pod_id)
        rate = float(ready.get("costPerHr") or ready.get("adjustedCostPerHr") or 0.0)
        if rate <= 0 or rate > BASE_MAX_HOURLY_USD:
            raise QualificationRefused("qualification hourly rate exceeds the frozen ceiling")
        host = str(ready.get("publicIp") or "")
        port = _port22(ready)
        if not host or port is None:
            raise QualificationRefused("qualification SSH address is unavailable")
        state.update(
            {
                "phase": "ssh_ready",
                "host": host,
                "port": port,
                "hourly_rate_usd": rate,
            }
        )
        _write_state(paths, state)
        _upload_common(paths, state, spec, smoke)
        remote_pid = _launch_remote(
            paths,
            state,
            _bootstrap_command(spec),
            "/workspace/tavonel-r/bootstrap.pid",
        )
        state.update({"phase": "bootstrap_running", "remote_pid": remote_pid})
        _write_state(paths, state)
        _journal(paths, "bootstrap_launched", pod_id=pod_id, remote_pid=remote_pid)
        return {"role": role, "phase": state["phase"], "pod_id": pod_id, "hourly_rate_usd": rate}
    except Exception as error:
        try:
            _stop_preserving_cache(
                paths,
                state,
                provider,
                phase="start_failed_stopped",
                event="start_failure_stopped_cache_preserved",
            )
        except Exception as stop_error:
            _journal(
                paths,
                "start_failure_stop_failed",
                pod_id=pod_id,
                original_error_type=type(error).__name__,
                stop_error_type=type(stop_error).__name__,
            )
        raise


def _remote_process_state(
    paths: LocalPaths, state: dict[str, Any], *, marker: str, pid_path: str
) -> str:
    output = ssh(
        paths,
        state,
        f"if test -f {marker}; then echo COMPLETE; "
        f"elif test -f {pid_path} && kill -0 $(cat {pid_path}) 2>/dev/null; then echo RUNNING; "
        "else echo FAILED; fi",
    )
    return output.splitlines()[-1].strip() if output else "FAILED"


def _strong_validate_and_launch_smoke(
    paths: LocalPaths, state: dict[str, Any], spec: RoleSpec
) -> int:
    identity = f"{spec.model_id}@{spec.model_revision}"
    command = (
        "set -euo pipefail; "
        "/workspace/folynta/mineru-3.4.4-venv/bin/python "
        "/workspace/tavonel-r/runner/artifact_manifest.py "
        "--root /workspace/folynta/models/MinerU2.5-Pro-2605-1.2B "
        "--output /workspace/tavonel-r/receipts/model-artifact.json "
        "--root /workspace/folynta/models/MinerU2.5-Pro-2605-1.2B "
        f"--identity {json.dumps(identity)} --exclude-prefix .cache >/dev/null; "
        "observed=$(sha256sum /workspace/tavonel-r/receipts/model-artifact.json | cut -d' ' -f1); "
        f'test "$observed" = {spec.expected_model_manifest_sha256}; '
        "rm -rf /workspace/tavonel-r/smoke-output; "
        "env MINERU_MODEL_SOURCE=local MINERU_TOOLS_CONFIG_JSON=/root/mineru.json "
        "MINERU_API_MAX_CONCURRENT_REQUESTS=1 timeout 900 "
        "/workspace/folynta/mineru-3.4.4-venv/bin/mineru "
        "-p /workspace/tavonel-r/input/input.jpg -o /workspace/tavonel-r/smoke-output "
        "-b vlm-engine -m ocr; "
        "find /workspace/tavonel-r/smoke-output -type f -name '*.md' -size +0c | grep -q .; "
        "find /workspace/tavonel-r/smoke-output -type f -name '*.md' -print0 | sort -z | "
        "xargs -0 cat | sha256sum | cut -d' ' -f1 > "
        "/workspace/tavonel-r/receipts/smoke-output.sha256; "
        "touch /workspace/tavonel-r/SMOKE_COMPLETE"
    )
    return _launch_remote(paths, state, command, "/workspace/tavonel-r/smoke.pid")


def _primary_validate_and_launch_smoke(
    paths: LocalPaths, state: dict[str, Any], spec: RoleSpec
) -> int:
    command = (
        "set -euo pipefail; cd /workspace/tavonel-r/runner; "
        "rm -rf /workspace/tavonel-r/paddle-smoke; "
        "mkdir -p /workspace/tavonel-r/paddle-smoke; "
        "/workspace/folynta/paddle-fastdeploy-venv/bin/python paddleocr_vl_stage2.py "
        "--input-dir /workspace/tavonel-r/input --output-dir /workspace/tavonel-r/paddle-smoke "
        f"--model-revision {spec.model_revision} "
        f"--artifact-manifest-sha256 sha256:{spec.expected_model_manifest_sha256} "
        "--vl-backend fastdeploy-server --vl-server-url http://127.0.0.1:8118/v1 "
        "--vl-max-concurrency 1 --repeats 1 --limit 1 --evidence-class smoke "
        "--case-timeout-seconds 600; "
        "find /workspace/tavonel-r/paddle-smoke -type f -size +0c | grep -q .; "
        "find /workspace/tavonel-r/paddle-smoke -type f -print0 | sort -z | xargs -0 cat | "
        "sha256sum | cut -d' ' -f1 > /workspace/tavonel-r/receipts/smoke-output.sha256; "
        "touch /workspace/tavonel-r/SMOKE_COMPLETE"
    )
    return _launch_remote(paths, state, command, "/workspace/tavonel-r/smoke.pid")


def _collect_safe_evidence(
    paths: LocalPaths, state: dict[str, Any], spec: RoleSpec
) -> dict[str, Any]:
    if spec.role == "strong":
        runtime_path = "/workspace/tavonel-r/receipts/runtime-identity.json"
        model_path = "/workspace/tavonel-r/receipts/model-artifact.json"
    else:
        runtime_path = "/workspace/tavonel-r/receipts/runtime-identity.json"
        model_path = "/workspace/tavonel-r/receipts/model-artifact-manifest.json"
    command = (
        "set -euo pipefail; "
        f"test -f {runtime_path}; test -f {model_path}; "
        f"printf 'runtime_sha=%s\\n' \"$(sha256sum {runtime_path} | cut -d' ' -f1)\"; "
        f"printf 'model_sha=%s\\n' \"$(sha256sum {model_path} | cut -d' ' -f1)\"; "
        "printf 'smoke_sha=%s\\n' \"$(cat /workspace/tavonel-r/receipts/smoke-output.sha256)\"; "
        "printf 'gpu=%s\\n' \"$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)\""
    )
    raw = ssh(paths, state, command)
    observed: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            observed[key.strip()] = value.strip()
    for key in ("runtime_sha", "model_sha", "smoke_sha", "gpu"):
        if not observed.get(key):
            raise QualificationRefused(f"qualification evidence is missing {key}")
    if observed["model_sha"] != spec.expected_model_manifest_sha256:
        raise QualificationRefused(
            "qualified model artifact manifest differs from frozen development identity"
        )
    return observed


def _seal_qualification_receipt(
    *,
    role: str,
    spec: RoleSpec,
    paths: LocalPaths,
    state: dict[str, Any],
    provider: Provider,
    observed: dict[str, Any],
    billing: dict[str, Any],
) -> dict[str, Any]:
    for key in ("runtime_sha", "model_sha", "smoke_sha", "gpu"):
        if not isinstance(observed.get(key), str) or not observed[key]:
            raise QualificationRefused(f"stopped qualification state is missing {key}")
    if observed["model_sha"] != spec.expected_model_manifest_sha256:
        raise QualificationRefused("stopped qualification model identity no longer matches freeze")
    smoke, input_manifest = qualification_input()
    file_paths = (spec.bootstrap_relpath, spec.prompt_relpath, *spec.extra_pin_paths)
    pins = pin_files(REPO, tuple(("runtime_input", path) for path in file_paths))
    observed_runtime = {
        "provider": "runpod_secure_cloud",
        "pod_id": str(state["pod_id"]),
        "gpu": observed["gpu"],
        "hourly_rate_usd": float(state["hourly_rate_usd"]),
        "runtime_identity_sha256": "sha256:" + observed["runtime_sha"],
        "model_manifest_sha256": "sha256:" + observed["model_sha"],
        "smoke_output_sha256": "sha256:" + observed["smoke_sha"],
        "smoke_input_sha256": sha256_file(smoke),
        "started_at_utc": state["started_at_utc"],
        "completed_at_utc": state.get("evidence_collected_at_utc") or utc_now(),
        "gpu_seconds_consumed_local": float(state["gpu_seconds_consumed_local"]),
        "remaining_gpu_seconds": float(state["remaining_gpu_seconds"]),
        "pod_billing": billing,
        "fresh_confirmatory_observation": False,
    }
    attestation = RuntimeAttestation(
        role=role,
        model_id=spec.model_id,
        model_revision=spec.model_revision,
        base_image=spec.base_image,
        base_image_digest=spec.base_image_digest,
        model_artifact_digest=spec.model_artifact_digest,
        prompt_schema_digest=sha256_file(REPO / spec.prompt_relpath),
        file_pins=pins,
        qualification_input_manifest_digest=canonical_digest(input_manifest),
        observed_runtime=observed_runtime,
    )
    attestation.validate(REPO)
    payload = attestation.as_dict()
    payload["attestation_digest"] = attestation.digest()
    receipt = RECEIPT_ROOT / f"{role}.json"
    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        with receipt.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    except FileExistsError as error:
        raise QualificationRefused("runtime qualification receipt already exists") from error

    provider_deleted = False
    try:
        provider.delete_pod(str(state["pod_id"]))
        provider_deleted = True
    except QualificationRefused:
        # The GPU is already stopped. A failed delete is a cleanup issue, not a
        # reason to discard a fully sealed scientific qualification receipt.
        provider_deleted = False
    state.update(
        {
            "phase": "complete",
            "provider_deleted": provider_deleted,
            "attestation_digest": attestation.digest(),
        }
    )
    _write_state(paths, state)
    _journal(
        paths,
        "qualification_complete",
        pod_id=str(state["pod_id"]),
        attestation_digest=attestation.digest(),
        provider_deleted=provider_deleted,
    )
    return {
        "role": role,
        "phase": "complete",
        "attestation_digest": attestation.digest(),
        "provider_deleted": provider_deleted,
    }


def finalize(role: str) -> dict[str, Any]:
    spec = discover_role_spec(role)
    paths = paths_for(role)
    state = _read_state(paths)
    api_key = read_runpod_b()
    provider = Provider(api_key)
    pod_id = str(state["pod_id"])
    phase = str(state["phase"])
    if phase == "complete":
        return {
            "role": role,
            "phase": phase,
            "attestation_digest": state.get("attestation_digest"),
            "provider_deleted": bool(state.get("provider_deleted")),
        }
    if phase == "qualification_evidence_stopped":
        observed = state.get("collected_safe_evidence")
        billing = state.get("last_pod_billing")
        if not isinstance(observed, dict) or not isinstance(billing, dict):
            raise QualificationRefused("stopped qualification evidence state is incomplete")
        return _seal_qualification_receipt(
            role=role,
            spec=spec,
            paths=paths,
            state=state,
            provider=provider,
            observed=observed,
            billing=billing,
        )
    if datetime.now(UTC) >= _parse_time(state["hard_deadline_utc"], label="hard deadline"):
        _stop_preserving_cache(
            paths,
            state,
            provider,
            phase="hard_deadline_stopped",
            event="hard_deadline_stopped_cache_preserved",
        )
        raise QualificationRefused(
            "qualification hard deadline reached; paid GPU stopped and cache preserved"
        )
    if phase == "bootstrap_running":
        remote = _remote_process_state(
            paths,
            state,
            marker="/workspace/tavonel-r/BOOTSTRAP_COMPLETE",
            pid_path="/workspace/tavonel-r/bootstrap.pid",
        )
        if remote == "RUNNING":
            return {"role": role, "phase": phase, "remote": remote}
        if remote != "COMPLETE":
            tail = ssh(
                paths,
                state,
                "tail -80 /workspace/tavonel-r/qualification.stderr.log 2>/dev/null || true",
                check=False,
            )
            _stop_preserving_cache(
                paths,
                state,
                provider,
                phase="bootstrap_failed_stopped",
                event="bootstrap_failed_stopped_cache_preserved",
                stderr_tail=tail,
            )
            raise QualificationRefused(
                "qualification bootstrap failed; paid GPU stopped and cache preserved"
            )
        smoke_pid = (
            _strong_validate_and_launch_smoke(paths, state, spec)
            if role == "strong"
            else _primary_validate_and_launch_smoke(paths, state, spec)
        )
        state.update({"phase": "smoke_running", "smoke_pid": smoke_pid})
        _write_state(paths, state)
        _journal(paths, "smoke_launched", pod_id=pod_id, remote_pid=smoke_pid)
        return {"role": role, "phase": "smoke_running"}
    if phase == "smoke_running":
        remote = _remote_process_state(
            paths,
            state,
            marker="/workspace/tavonel-r/SMOKE_COMPLETE",
            pid_path="/workspace/tavonel-r/smoke.pid",
        )
        if remote == "RUNNING":
            return {"role": role, "phase": phase, "remote": remote}
        if remote != "COMPLETE":
            tail = ssh(
                paths,
                state,
                "tail -120 /workspace/tavonel-r/qualification.stderr.log 2>/dev/null || true",
                check=False,
            )
            _stop_preserving_cache(
                paths,
                state,
                provider,
                phase="smoke_failed_stopped",
                event="smoke_failed_stopped_cache_preserved",
                stderr_tail=tail,
            )
            raise QualificationRefused(
                "qualification smoke failed; paid GPU stopped and cache preserved"
            )
        observed = _collect_safe_evidence(paths, state, spec)
        state["collected_safe_evidence"] = observed
        state["evidence_collected_at_utc"] = utc_now()
        _write_state(paths, state)
        billing = _stop_preserving_cache(
            paths,
            state,
            provider,
            phase="qualification_evidence_stopped",
            event="qualification_evidence_stopped_before_seal",
        )
        return _seal_qualification_receipt(
            role=role,
            spec=spec,
            paths=paths,
            state=state,
            provider=provider,
            observed=observed,
            billing=billing,
        )
    raise QualificationRefused(f"unsupported qualification phase: {phase}")


def cleanup(role: str) -> dict[str, Any]:
    paths = paths_for(role)
    state = _read_state(paths)
    provider = Provider(read_runpod_b())
    pod_id = str(state["pod_id"])
    if provider.get_pod(pod_id) is not None:
        provider.delete_pod(pod_id)
    state.update({"phase": "cleaned_up", "provider_deleted": True})
    _write_state(paths, state)
    _journal(paths, "manual_cleanup_verified", pod_id=pod_id)
    return {"role": role, "provider_deleted": True}


_RESUMABLE_STOPPED_PHASES = frozenset(
    {
        "start_failed_stopped",
        "bootstrap_failed_stopped",
        "smoke_failed_stopped",
        "hard_deadline_stopped",
    }
)


def resume(role: str) -> dict[str, Any]:
    """Resume the same stopped Pod/volume without resetting the GPU-time budget."""
    authorize_qualification()
    spec = discover_role_spec(role)
    smoke, _ = qualification_input()
    paths = paths_for(role)
    state = _read_state(paths)
    phase = str(state.get("phase") or "")
    if phase not in _RESUMABLE_STOPPED_PHASES:
        raise QualificationRefused(f"qualification phase is not resumable: {phase}")
    remaining = float(state.get("remaining_gpu_seconds", 0.0))
    if remaining <= 0:
        raise QualificationRefused("qualification GPU-time budget is exhausted; resume refused")
    provider = Provider(read_runpod_b())
    pod_id = str(state.get("pod_id") or "")
    pod = provider.get_pod(pod_id)
    if pod is None:
        raise QualificationRefused("stopped qualification pod is absent; duplicate creation refused")
    try:
        if str(pod.get("desiredStatus", "")).upper() != "RUNNING":
            provider.start_pod(pod_id)
        ready = wait_ssh_ready(provider, pod_id)
        rate = float(ready.get("costPerHr") or ready.get("adjustedCostPerHr") or 0.0)
        if rate <= 0 or rate > BASE_MAX_HOURLY_USD:
            raise QualificationRefused("resumed qualification hourly rate exceeds frozen ceiling")
        host = str(ready.get("publicIp") or "")
        port = _port22(ready)
        if not host or port is None:
            raise QualificationRefused("resumed qualification SSH endpoint is unavailable")
        # A restarted container may generate a new SSH host key even when the
        # public endpoint happens to be reused. This known-host file belongs only
        # to the exact qualification Pod, so reset it on an explicit resume.
        paths.known_hosts.unlink(missing_ok=True)
        now = datetime.now(UTC)
        state.update(
            {
                "phase": "ssh_ready",
                "host": host,
                "port": port,
                "hourly_rate_usd": rate,
                "running_started_at_utc": now.isoformat(),
                "hard_deadline_utc": (now + timedelta(seconds=remaining)).isoformat(),
                "provider_stopped": False,
                "stopped_at_utc": None,
                "resume_count": int(state.get("resume_count", 0)) + 1,
            }
        )
        watchdog_pid = _spawn_watchdog(role)
        state["watchdog_pid"] = watchdog_pid
        _write_state(paths, state)
        _journal(
            paths,
            "qualification_resumed",
            pod_id=pod_id,
            remaining_gpu_seconds=remaining,
            watchdog_pid=watchdog_pid,
        )
        _upload_common(paths, state, spec, smoke)
        ssh(
            paths,
            state,
            "rm -f /workspace/tavonel-r/BOOTSTRAP_COMPLETE "
            "/workspace/tavonel-r/SMOKE_COMPLETE /workspace/tavonel-r/bootstrap.pid "
            "/workspace/tavonel-r/smoke.pid",
        )
        remote_pid = _launch_remote(
            paths,
            state,
            _bootstrap_command(spec),
            "/workspace/tavonel-r/bootstrap.pid",
        )
        state.update({"phase": "bootstrap_running", "remote_pid": remote_pid})
        _write_state(paths, state)
        _journal(paths, "resume_bootstrap_launched", pod_id=pod_id, remote_pid=remote_pid)
        return {
            "role": role,
            "phase": "bootstrap_running",
            "pod_id": pod_id,
            "remaining_gpu_seconds": remaining,
        }
    except Exception as error:
        try:
            _stop_preserving_cache(
                paths,
                state,
                provider,
                phase="start_failed_stopped",
                event="resume_failure_stopped_cache_preserved",
            )
        except Exception as stop_error:
            _journal(
                paths,
                "resume_failure_stop_failed",
                pod_id=pod_id,
                original_error_type=type(error).__name__,
                stop_error_type=type(stop_error).__name__,
            )
        raise


def watchdog(role: str) -> int:
    paths = paths_for(role)
    while True:
        try:
            state = _read_state(paths)
        except QualificationRefused:
            return 0
        if str(state.get("phase")) in {
            "complete",
            "cleaned_up",
            *_RESUMABLE_STOPPED_PHASES,
            "qualification_evidence_stopped",
        }:
            return 0
        deadline_raw = state.get("hard_deadline_utc")
        pod_id = str(state.get("pod_id") or "")
        if not deadline_raw or not pod_id:
            return 0
        deadline = _parse_time(deadline_raw, label="hard deadline")
        if datetime.now(UTC) < deadline:
            time.sleep(30)
            continue
        try:
            provider = Provider(read_runpod_b())
            _stop_preserving_cache(
                paths,
                state,
                provider,
                phase="hard_deadline_stopped",
                event="hard_deadline_watchdog_stopped_cache_preserved",
            )
        except Exception as error:  # pragma: no cover - final external backstop
            _journal(paths, "hard_deadline_watchdog_failed", error_type=type(error).__name__)
            return 3
        return 0


def plan(role: str) -> dict[str, Any]:
    spec = discover_role_spec(role)
    _, input_manifest = qualification_input()
    authority = authorize_qualification()
    file_paths = (spec.bootstrap_relpath, spec.prompt_relpath, *spec.extra_pin_paths)
    pins = pin_files(REPO, tuple(("runtime_input", path) for path in file_paths))
    return {
        "schema": "tavonel.recovery.runpod_qualification_plan.v1",
        "evidence_class": "DEVELOPMENT_RUNTIME_QUALIFICATION_ONLY",
        "role": role,
        "candidate_id": spec.candidate_id,
        "model_id": spec.model_id,
        "model_revision": spec.model_revision,
        "model_artifact_digest": spec.model_artifact_digest,
        "base_image": spec.base_image,
        "base_image_digest": spec.base_image_digest,
        "qualification_input_manifest_digest": canonical_digest(input_manifest),
        "implementation_pins": [{"path": pin.path, "sha256": pin.sha256} for pin in pins],
        "authority": authority,
        "limits": {
            "pages": 1,
            "gpu_seconds": MAX_RUNTIME_SECONDS,
            "estimated_external_cost_usd": MAX_ESTIMATED_COST_USD,
            "max_hourly_rate_usd": BASE_MAX_HOURLY_USD,
        },
        "provider_contract": {
            "pod_api": "https://rest.runpod.io/v1",
            "pod_billing_surface": "/billing/pods",
            "serverless_billing_is_not_pod_billing": True,
            "failure_default": "stop_preserve_workspace_before_delete",
        },
        "runtime_persistence": {
            "volume_mount": "/workspace",
            "volume_gb": 20,
            "resume_supported": True,
            "deadline_recomputed_from_remaining_gpu_seconds": True,
            "strong_runtime_root": "/workspace/folynta/mineru-3.4.4-venv",
            "strong_model_root": "/workspace/folynta/models/MinerU2.5-Pro-2605-1.2B",
            "primary_runtime_root": "/workspace/folynta/paddle-fastdeploy-venv",
        },
        "fresh_confirmatory_observation": False,
        "sensitive_material_included": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "start", "resume", "advance", "cleanup", "watchdog"):
        command = sub.add_parser(name)
        command.add_argument("--role", choices=("strong", "primary"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            value = plan(args.role)
        elif args.command == "start":
            value = start(args.role)
        elif args.command == "resume":
            value = resume(args.role)
        elif args.command == "advance":
            value = finalize(args.role)
        elif args.command == "cleanup":
            value = cleanup(args.role)
        else:
            return watchdog(args.role)
    except QualificationRefused as error:
        print(json.dumps({"status": "REFUSED", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
