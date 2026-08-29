#!/usr/bin/env python3
"""Development-only phase diagnostic for TAVONEL-R GPU qualification.

This does not qualify a model and cannot open the fresh cohort.  It uses the
same prospectively selected role pins and one already-spent OmniDocBench page,
starts a secret-free HTTP evidence server immediately, records coarse bootstrap
phases on-pod, and deletes paid capacity at terminal evidence or a hard deadline.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from recovery_protocol import PRE_FREEZE_DRAFT, authorize_development_runtime_qualification
from runpod_http_qualification import qualification_input_binding
from runpod_qualification import (
    BASE_MAX_HOURLY_USD,
    Provider,
    QualificationRefused,
    discover_role_spec,
    read_runpod_b,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ATTEMPT = "phase-diagnostic-v1"
PRIVATE_ROOT = HERE / ".private" / "runpod-phase-diagnostic" / ATTEMPT
RECEIPT_ROOT = HERE / "receipts" / "runtime-phase-diagnostic"
PORT = 8001
MAX_RUNTIME_SECONDS = 2700
MAX_EXTERNAL_COST_USD = 1.0
POLL_SECONDS = 15


def _canonical(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    folded = raw.casefold()
    for marker in ("runpod_b", "authorization", "bearer ", "api_key", "apikey"):
        if marker in folded:
            raise QualificationRefused("secret-like material would enter diagnostic evidence")
    return raw


def _sha_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _write_cmd(path: str, data: bytes) -> str:
    return f"printf '%s' '{_b64(data)}' | base64 -d > {path}"


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise QualificationRefused(f"diagnostic anchor {label} resolved {count} times")
    return text.replace(old, new, 1)


def _phase_function(role: str) -> str:
    return f"""phase() {{
  local name="$1"
  local status="${{2:-RUNNING}}"
  local rc="${{3:-0}}"
  PHASE_NAME="$name" PHASE_STATUS="$status" PHASE_RC="$rc" /usr/bin/python3.11 - <<'PY'
import json, os, time
from pathlib import Path
path=Path(os.environ["PHASE_HTTP_FILE"])
try:
    old=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {{}}
except Exception:
    old={{}}
history=list(old.get("history") or [])
event={{"phase":os.environ["PHASE_NAME"],"status":os.environ["PHASE_STATUS"],"unix":int(time.time())}}
if os.environ.get("PHASE_RC") not in (None,"","0"):
    event["exit_code"]=int(os.environ["PHASE_RC"])
history.append(event)
value={{
 "schema":"tavonel.recovery.runtime_phase_diagnostic.v1",
 "role":{json.dumps(role)},
 "status":os.environ["PHASE_STATUS"],
 "phase":os.environ["PHASE_NAME"],
 "history":history,
 "fresh_confirmatory_observation":False,
 "sensitive_material_included":False,
}}
path.write_text(json.dumps(value,sort_keys=True,separators=(",",":"))+"\\n",encoding="utf-8")
PY
}}
"""


def _decorate_strong(raw: str) -> str:
    text = raw
    text = _replace_once(
        text,
        '"$PYTHON_BIN" -m pip install --no-cache-dir \\\n  --index-url https://download.pytorch.org/whl/cu128',
        'phase TORCH_INSTALL_STARTED\n"$PYTHON_BIN" -m pip install --no-cache-dir \\\n  --index-url https://download.pytorch.org/whl/cu128',
        label="strong torch start",
    )
    text = _replace_once(
        text,
        'rm -rf "$SOURCE_ROOT"',
        'phase TORCH_INSTALL_DONE\nphase MINERU_CLONE_STARTED\nrm -rf "$SOURCE_ROOT"',
        label="strong clone start",
    )
    text = _replace_once(
        text,
        "\"$PYTHON_BIN\" -m pip install --no-cache-dir \\\n  'accelerate==1.14.0'",
        "phase MINERU_CLONE_DONE\nphase MINERU_DEPS_STARTED\n\"$PYTHON_BIN\" -m pip install --no-cache-dir \\\n  'accelerate==1.14.0'",  # noqa: E501
        label="strong deps start",
    )
    text = _replace_once(
        text,
        'MODEL_ROOT="$MODEL_ROOT" MODEL_REVISION="$MODEL_REVISION" "$PYTHON_BIN" - <<\'PY\'',
        'phase MINERU_DEPS_DONE\nphase MODEL_DOWNLOAD_STARTED\nMODEL_ROOT="$MODEL_ROOT" MODEL_REVISION="$MODEL_REVISION" "$PYTHON_BIN" - <<\'PY\'',  # noqa: E501
        label="strong model start",
    )
    text = _replace_once(
        text,
        "cat > /root/mineru.json <<EOF",
        "phase MODEL_DOWNLOAD_DONE\nphase RECEIPTS_STARTED\ncat > /root/mineru.json <<EOF",
        label="strong receipt start",
    )
    text = _replace_once(
        text,
        'touch "$RECEIPT_ROOT/BOOTSTRAP_COMPLETE"',
        'touch "$RECEIPT_ROOT/BOOTSTRAP_COMPLETE"\nphase BOOTSTRAP_DONE',
        label="strong done",
    )
    return text


def _decorate_primary(raw: str) -> str:
    text = raw
    text = _replace_once(
        text,
        'if [[ ! -x "$venv/bin/python" ]]; then',
        'phase RUNTIME_INSTALL_STARTED\nif [[ ! -x "$venv/bin/python" ]]; then',
        label="primary runtime start",
    )
    text = _replace_once(
        text,
        "fi\n\n# PaddlePaddle 3.2.1 still reads FieldDescriptor.label",
        "fi\nphase RUNTIME_INSTALL_DONE\n\n# PaddlePaddle 3.2.1 still reads FieldDescriptor.label",
        label="primary runtime done",
    )
    text = _replace_once(
        text,
        'export PADDLE_PDX_MODEL_SOURCE="HF"',
        'phase MODEL_DOWNLOAD_STARTED\nexport PADDLE_PDX_MODEL_SOURCE="HF"',
        label="primary model start",
    )
    text = _replace_once(
        text,
        'nohup "$venv/bin/paddleocr" genai_server',
        'phase MODEL_DOWNLOAD_DONE\nphase SERVICE_START_STARTED\nnohup "$venv/bin/paddleocr" genai_server',  # noqa: E501
        label="primary service start",
    )
    text = _replace_once(
        text,
        "# Bind the immutable Hugging Face revision to primary model bytes only.",
        "phase SERVICE_READY\nphase ARTIFACT_VERIFY_STARTED\n# Bind the immutable Hugging Face revision to primary model bytes only.",  # noqa: E501
        label="primary artifact start",
    )
    text = _replace_once(
        text,
        'printf \'{"event":"model_artifact_verified","unix":%s}\\n\' "$(date -u +%s)" >>"$state"',
        'printf \'{"event":"model_artifact_verified","unix":%s}\\n\' "$(date -u +%s)" >>"$state"\nphase ARTIFACT_VERIFY_DONE',  # noqa: E501
        label="primary artifact done",
    )
    text += "\nphase BOOTSTRAP_DONE\n"
    return text


def _startup(role: str) -> tuple[str, dict[str, str]]:
    spec = discover_role_spec(role)
    public_input = qualification_input_binding()
    bootstrap_path = REPO / spec.bootstrap_relpath
    raw = bootstrap_path.read_text(encoding="utf-8")
    decorated = _decorate_strong(raw) if role == "strong" else _decorate_primary(raw)
    decorated = decorated.replace(
        "set -euo pipefail", "set -euo pipefail\n" + _phase_function(role), 1
    )
    input_url = str(public_input["url"])
    input_sha = str(public_input["sha256"]).removeprefix("sha256:")
    root = "/workspace/tavonel-r-phase"
    setup = [
        "set -Eeuo pipefail",
        f"ROOT={root}",
        "mkdir -p $ROOT/http $ROOT/runner $ROOT/input $ROOT/receipts",
        "export PHASE_HTTP_FILE=$ROOT/http/evidence.json",
        _phase_function(role),
        "phase STARTED",
        "/usr/bin/python3.11 -m http.server 8001 --bind 0.0.0.0 --directory $ROOT/http >/tmp/tavonel-phase-http.log 2>&1 &",  # noqa: E501
        "server=$!",
        "phase HTTP_SERVER_STARTED",
        "trap 'rc=$?; phase FAILED FAIL $rc; wait $server' ERR",
        "phase APT_STARTED",
        "apt-get update -qq && apt-get install -y -qq --no-install-recommends git ca-certificates curl jq && rm -rf /var/lib/apt/lists/*",  # noqa: E501
        "phase APT_DONE",
        _write_cmd("$ROOT/runner/bootstrap.sh", decorated.encode()),
        "chmod 700 $ROOT/runner/bootstrap.sh",
        f"curl -fL --retry 4 --retry-delay 3 {json.dumps(input_url)} -o $ROOT/input/input.png",
        f"printf '%s  %s\\n' '{input_sha}' \"$ROOT/input/input.png\" | sha256sum -c -",
        "phase BOOTSTRAP_STARTED",
    ]
    if role == "strong":
        setup.extend(
            [
                "RECEIPT_ROOT=$ROOT/receipts PYTHON_BIN=/usr/bin/python3.11 bash $ROOT/runner/bootstrap.sh",  # noqa: E501
                "phase DIAGNOSTIC_COMPLETE PASS",
                "wait $server",
            ]
        )
    else:
        backend = REPO / "benchmark/runpod_eval/paddle-fastdeploy-backend.yaml"
        artifact = REPO / "benchmark/runpod_eval/artifact_manifest.py"
        setup.insert(-1, _write_cmd("$ROOT/runner/backend.yaml", backend.read_bytes()))
        setup.insert(-1, _write_cmd("$ROOT/runner/artifact_manifest.py", artifact.read_bytes()))
        setup.extend(
            [
                "bash $ROOT/runner/bootstrap.sh $ROOT/runner/backend.yaml $ROOT/receipts $ROOT/runner/artifact_manifest.py >/tmp/paddle-service-pid.txt",  # noqa: E501
                "phase DIAGNOSTIC_COMPLETE PASS",
                "wait $server",
            ]
        )
    script = "\n".join(setup) + "\n"
    return script, {
        "startup_script_sha256": _sha_text(script),
        "bootstrap_sha256": "sha256:" + hashlib.sha256(bootstrap_path.read_bytes()).hexdigest(),
        "public_input_binding_sha256": "sha256:"
        + hashlib.sha256((HERE / "PUBLIC_QUALIFICATION_INPUT.json").read_bytes()).hexdigest(),
        "smoke_input_sha256": str(public_input["sha256"]),
    }


def _authorize() -> str:
    return authorize_development_runtime_qualification(
        protocol_state=PRE_FREEZE_DRAFT,
        fresh_cohort_opened=False,
        spent_development_only=True,
        pages=1,
        gpu_seconds=float(MAX_RUNTIME_SECONDS),
        external_cost_usd=float(MAX_EXTERNAL_COST_USD),
    )


def _paths(role: str) -> tuple[Path, Path]:
    root = PRIVATE_ROOT / role
    return root / "state.json", root / "provider.jsonl"


def _write_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical(value) + "\n", encoding="utf-8")


def _journal(path: Path, event: str, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            _canonical({"event": event, "observed_at_utc": datetime.now(UTC).isoformat(), **fields})
            + "\n"
        )


def _url(pod_id: str) -> str:
    if not pod_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in pod_id):
        raise QualificationRefused("invalid pod id")
    return f"https://{pod_id}-{PORT}.proxy.runpod.net/evidence.json"


def _payload(role: str) -> tuple[dict[str, Any], dict[str, str]]:
    _authorize()
    spec = discover_role_spec(role)
    script, pins = _startup(role)
    payload = {
        "name": f"tavonel-r-phase-{role}-{ATTEMPT}",
        "imageName": spec.base_image,
        "cloudType": "SECURE",
        "computeType": "GPU",
        "gpuTypeIds": ["NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 5090"],
        "gpuTypePriority": "availability",
        "gpuCount": 1,
        "containerDiskInGb": 100,
        "volumeInGb": 20,
        "volumeMountPath": "/workspace",
        "ports": [f"{PORT}/http"],
        "supportPublicIp": True,
        "interruptible": False,
        "dockerEntrypoint": ["/bin/bash", "-lc"],
        "dockerStartCmd": [script],
        "env": {"TAVONEL_R_PHASE_DIAGNOSTIC_ONLY": "1"},
    }
    if len(_canonical(payload).encode()) > 512_000:
        raise QualificationRefused("diagnostic payload too large")
    return payload, pins


def _spawn_watchdog(role: str) -> int:
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    proc = subprocess.Popen(  # noqa: S603 - fixed interpreter/script/role argv only
        [sys.executable, str(Path(__file__).resolve()), "watchdog", "--role", role],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )
    return int(proc.pid)


def start(role: str) -> dict[str, Any]:
    state_path, journal = _paths(role)
    if state_path.exists():
        raise QualificationRefused("phase diagnostic state already exists")
    payload, pins = _payload(role)
    provider = Provider(read_runpod_b())
    name = str(payload["name"])
    if any(str(row.get("name")) == name for row in provider.list_pods()):
        raise QualificationRefused("deterministic phase diagnostic pod already exists")
    pod = provider.create_pod(payload)
    pod_id = str(pod.get("id") or "")
    if not pod_id:
        raise QualificationRefused("provider omitted pod id")
    rate = float(pod.get("costPerHr") or pod.get("adjustedCostPerHr") or 0.0)
    if rate <= 0 or rate > BASE_MAX_HOURLY_USD:
        provider.delete_pod(pod_id)
        raise QualificationRefused("diagnostic hourly rate exceeds ceiling")
    state = {
        "schema": "tavonel.recovery.runtime_phase_diagnostic_state.v1",
        "role": role,
        "phase": "provider_running",
        "pod_id": pod_id,
        "hourly_rate_usd": rate,
        "evidence_url": _url(pod_id),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "hard_deadline_utc": (
            datetime.now(UTC) + timedelta(seconds=MAX_RUNTIME_SECONDS)
        ).isoformat(),
        "startup_inputs": pins,
        "fresh_confirmatory_observation": False,
    }
    _write_state(state_path, state)
    state["watchdog_pid"] = _spawn_watchdog(role)
    _write_state(state_path, state)
    _journal(journal, "pod_created", pod_id=pod_id, hourly_rate_usd=rate)
    return {"role": role, "pod_id": pod_id, "phase": "provider_running", "hourly_rate_usd": rate}


def _fetch(url: str) -> dict[str, Any] | None:
    if not url.startswith("https://") or not url.endswith("/evidence.json"):
        raise QualificationRefused("diagnostic evidence URL is invalid")
    request = urllib.request.Request(  # noqa: S310 - prevalidated HTTPS proxy URL
        url, headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            raw = response.read(256 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 404, 502, 503, 504}:
            return None
        raise QualificationRefused(f"diagnostic proxy HTTP failure {exc.code}") from None
    except OSError:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationRefused("diagnostic evidence is not JSON") from exc
    if not isinstance(value, dict):
        raise QualificationRefused("diagnostic evidence shape invalid")
    return value


def _validate_evidence(role: str, value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema") != "tavonel.recovery.runtime_phase_diagnostic.v1":
        raise QualificationRefused("diagnostic schema mismatch")
    if value.get("role") != role:
        raise QualificationRefused("diagnostic role mismatch")
    if value.get("fresh_confirmatory_observation") is not False:
        raise QualificationRefused("diagnostic touched fresh data")
    if value.get("sensitive_material_included") is not False:
        raise QualificationRefused("diagnostic reports sensitive material")
    if not isinstance(value.get("history"), list):
        raise QualificationRefused("diagnostic history missing")
    return value


def inspect(role: str) -> dict[str, Any]:
    state_path, journal = _paths(role)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    provider = Provider(read_runpod_b())
    pod_id = str(state["pod_id"])
    evidence = _fetch(str(state["evidence_url"]))
    if evidence is not None:
        evidence = _validate_evidence(role, evidence)
        _journal(
            journal, "phase_observed", phase=evidence.get("phase"), status=evidence.get("status")
        )
        if evidence.get("status") in {"PASS", "FAIL"}:
            RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
            receipt = RECEIPT_ROOT / f"{role}.json"
            if not receipt.exists():
                receipt.write_text(
                    json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            if provider.get_pod(pod_id) is not None:
                provider.delete_pod(pod_id)
            state.update(
                {
                    "phase": "terminal_cleaned",
                    "provider_deleted": True,
                    "terminal_status": evidence["status"],
                }
            )
            _write_state(state_path, state)
            return {
                "role": role,
                "phase": evidence.get("phase"),
                "status": evidence["status"],
                "provider_deleted": True,
                "history": evidence["history"],
            }
    if datetime.now(UTC) >= datetime.fromisoformat(str(state["hard_deadline_utc"])):
        if provider.get_pod(pod_id) is not None:
            provider.delete_pod(pod_id)
        state.update({"phase": "hard_deadline_cleaned", "provider_deleted": True})
        _write_state(state_path, state)
        _journal(journal, "hard_deadline_cleanup", pod_id=pod_id)
        return {
            "role": role,
            "phase": (evidence or {}).get("phase"),
            "status": "HARD_DEADLINE",
            "provider_deleted": True,
            "history": (evidence or {}).get("history", []),
        }
    if provider.get_pod(pod_id) is None:
        raise QualificationRefused("diagnostic pod disappeared without terminal evidence")
    return {
        "role": role,
        "phase": (evidence or {}).get("phase", "PROXY_NOT_READY"),
        "status": (evidence or {}).get("status", "RUNNING"),
        "provider_deleted": False,
        "history": (evidence or {}).get("history", []),
    }


def cleanup(role: str) -> dict[str, Any]:
    state_path, journal = _paths(role)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    provider = Provider(read_runpod_b())
    pod_id = str(state.get("pod_id") or "")
    if pod_id and provider.get_pod(pod_id) is not None:
        provider.delete_pod(pod_id)
    state.update({"phase": "cleaned_up", "provider_deleted": True})
    _write_state(state_path, state)
    _journal(journal, "manual_cleanup_verified", pod_id=pod_id)
    return {"role": role, "provider_deleted": True}


def watchdog(role: str) -> int:
    state_path, journal = _paths(role)
    while True:
        if not state_path.exists():
            return 0
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("provider_deleted") is True:
            return 0
        deadline = datetime.fromisoformat(str(state["hard_deadline_utc"]))
        if datetime.now(UTC) < deadline:
            time.sleep(30)
            continue
        provider = Provider(read_runpod_b())
        pod_id = str(state.get("pod_id") or "")
        if pod_id and provider.get_pod(pod_id) is not None:
            provider.delete_pod(pod_id)
        state.update({"phase": "hard_deadline_cleaned", "provider_deleted": True})
        _write_state(state_path, state)
        _journal(journal, "watchdog_cleanup", pod_id=pod_id)
        return 0


def plan(role: str) -> dict[str, Any]:
    payload, pins = _payload(role)
    safe = dict(payload)
    safe["dockerStartCmd"] = ["[REDACTED]"]
    return {
        "schema": "tavonel.recovery.runtime_phase_diagnostic_plan.v1",
        "role": role,
        "evidence_class": "DEVELOPMENT_DIAGNOSTIC_ONLY",
        "provider_request_without_startup_bytes": safe,
        "startup_inputs": pins,
        "payload_bytes": len(_canonical(payload).encode()),
        "max_runtime_seconds": MAX_RUNTIME_SECONDS,
        "max_external_cost_usd": MAX_EXTERNAL_COST_USD,
        "fresh_confirmatory_observation": False,
        "sensitive_material_included": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "start", "inspect", "cleanup", "watchdog"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--role", choices=("strong", "primary"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = plan(args.role)
        elif args.command == "start":
            result = start(args.role)
        elif args.command == "inspect":
            result = inspect(args.role)
        elif args.command == "cleanup":
            result = cleanup(args.role)
        else:
            return watchdog(args.role)
    except (QualificationRefused, FileNotFoundError, KeyError, ValueError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
