#!/usr/bin/env python3
"""HTTP-only, bounded RunPod development qualification for TAVONEL-R.

No SSH key or interactive remote shell exists in this path.  The controller
builds a self-contained, non-secret startup command from frozen local runtime
inputs plus one already-spent smoke page.  The pod runs the exact pinned
bootstrap, verifies model bytes, runs one smoke inference, serves a small safe
JSON receipt on RunPod's HTTP proxy, and is then deleted by the controller.
A detached local provider-only watchdog deletes the pod at the hard deadline.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from runpod_qualification import (
    BASE_MAX_HOURLY_USD,
    MAX_ESTIMATED_COST_USD,
    MAX_RUNTIME_SECONDS,
    Provider,
    QualificationRefused,
    authorize_qualification,
    discover_role_spec,
    read_runpod_b,
)
from runtime_attestation import RuntimeAttestation, canonical_digest, pin_files, sha256_file

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
QUALIFICATION_ATTEMPT = "v2-long-dev"
PRIVATE_ROOT = HERE / ".private" / "runpod-http-qualification" / QUALIFICATION_ATTEMPT
RECEIPT_ROOT = HERE / "receipts" / "runtime-qualification"
PUBLIC_INPUT_BINDING = HERE / "PUBLIC_QUALIFICATION_INPUT.json"
EVIDENCE_PORT = 8001
HTTP_POLL_SECONDS = 15


@dataclass(frozen=True, slots=True)
class Paths:
    role_dir: Path
    state: Path
    journal: Path


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def paths_for(role: str) -> Paths:
    root = PRIVATE_ROOT / role
    return Paths(role_dir=root, state=root / "state.json", journal=root / "provider.jsonl")


def _secret_free_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    folded = raw.casefold()
    for marker in ("runpod_b", "authorization", "bearer ", "api_key", "apikey"):
        if marker in folded:
            raise QualificationRefused("secret-like material would enter a qualification receipt")
    return raw


def _write_state(paths: Paths, value: dict[str, Any]) -> None:
    paths.role_dir.mkdir(parents=True, exist_ok=True)
    raw = _secret_free_json(value)
    tmp = paths.state.with_suffix(".tmp")
    tmp.write_text(raw + "\n", encoding="utf-8")
    os.replace(tmp, paths.state)


def _read_state(paths: Paths) -> dict[str, Any]:
    if not paths.state.is_file():
        raise QualificationRefused("HTTP qualification state is absent")
    value = json.loads(paths.state.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualificationRefused("HTTP qualification state is malformed")
    return value


def _journal(paths: Paths, event: str, **fields: Any) -> None:
    paths.role_dir.mkdir(parents=True, exist_ok=True)
    line = _secret_free_json({"event": event, "observed_at_utc": utc_now(), **fields})
    with paths.journal.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _shell_write(path: str, data: bytes) -> str:
    return f"printf '%s' '{_b64(data)}' | base64 -d > {path}"


def qualification_input_binding() -> dict[str, Any]:
    if not PUBLIC_INPUT_BINDING.is_file():
        raise QualificationRefused("public qualification input binding is absent")
    value = json.loads(PUBLIC_INPUT_BINDING.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualificationRefused("public qualification input binding is malformed")
    if value.get("schema") != "tavonel.recovery.public_qualification_input.v1":
        raise QualificationRefused("public qualification input binding schema mismatch")
    if value.get("historical_family") != "OMNIDOCBENCH_2026_08_09_1651":
        raise QualificationRefused("qualification input is not from the spent OmniDocBench family")
    if value.get("fresh") is not False or value.get("confirmatory_eligible") is not False:
        raise QualificationRefused("qualification input must be development-only")
    url = str(value.get("url") or "")
    digest = str(value.get("sha256") or "")
    if not url.startswith("https://huggingface.co/datasets/opendatalab/OmniDocBench/resolve/"):
        raise QualificationRefused("qualification input URL is outside the frozen public source")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise QualificationRefused("qualification input SHA is invalid")
    return value


def _strong_startup_script() -> tuple[str, dict[str, str]]:
    spec = discover_role_spec("strong")
    public_input = qualification_input_binding()
    bootstrap_path = REPO / spec.bootstrap_relpath
    artifact_path = REPO / "benchmark/runpod_eval/artifact_manifest.py"
    bootstrap_bytes = bootstrap_path.read_bytes()
    artifact_bytes = artifact_path.read_bytes()
    identity = f"{spec.model_id}@{spec.model_revision}"
    input_url = str(public_input["url"])
    input_sha = str(public_input["sha256"]).removeprefix("sha256:")

    setup = "\n".join(
        (
            "set -uo pipefail",
            "ROOT=/workspace/tavonel-r-http",
            "mkdir -p $ROOT/runner $ROOT/input $ROOT/receipts $ROOT/http $ROOT/smoke-output",
            "apt-get update -qq && apt-get install -y -qq --no-install-recommends "
            "git ca-certificates curl && rm -rf /var/lib/apt/lists/*",
            _shell_write("$ROOT/runner/bootstrap.sh", bootstrap_bytes),
            _shell_write("$ROOT/runner/artifact_manifest.py", artifact_bytes),
            f"curl -fL --retry 4 --retry-delay 3 {json.dumps(input_url)} -o $ROOT/input/input.png",
            f"printf '%s  %s\\n' '{input_sha}' \"$ROOT/input/input.png\" | sha256sum -c -",
            "chmod 700 $ROOT/runner/bootstrap.sh",
        )
    )
    success = "\n".join(
        (
            "export MINERU_API_MAX_CONCURRENT_REQUESTS=1",
            "RECEIPT_ROOT=$ROOT/receipts PYTHON_BIN=/usr/bin/python3.11 "
            "bash $ROOT/runner/bootstrap.sh",
            "/usr/bin/python3.11 $ROOT/runner/artifact_manifest.py "
            "--root /workspace/folynta/models/MinerU2.5-Pro-2605-1.2B "
            "--output $ROOT/receipts/model-artifact.json "
            f"--identity '{identity}' --exclude-prefix .cache >/dev/null",
            "model_sha=$(sha256sum $ROOT/receipts/model-artifact.json | cut -d' ' -f1)",
            f"test \"$model_sha\" = '{spec.expected_model_manifest_sha256}'",
            "env MINERU_MODEL_SOURCE=local MINERU_TOOLS_CONFIG_JSON=/root/mineru.json "
            "MINERU_API_MAX_CONCURRENT_REQUESTS=1 timeout 900 /usr/local/bin/mineru "
            "-p $ROOT/input/input.png -o $ROOT/smoke-output -b vlm-engine -m ocr",
            "find $ROOT/smoke-output -type f -name '*.md' -size +0c | grep -q .",
            "smoke_sha=$(find $ROOT/smoke-output -type f -name '*.md' -print0 | sort -z | "
            "xargs -0 cat | sha256sum | cut -d' ' -f1)",
            "runtime_sha=$(sha256sum $ROOT/receipts/runtime-identity.json | cut -d' ' -f1)",
            "gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)",
            "export model_sha smoke_sha runtime_sha gpu",
            "/usr/bin/python3.11 - <<'PY'\n"
            "import json, os\n"
            "from pathlib import Path\n"
            "value={\n"
            " 'schema':'tavonel.recovery.http_runtime_evidence.v1',\n"
            " 'status':'PASS',\n"
            " 'role':'strong',\n"
            f" 'model_id':{json.dumps(spec.model_id)},\n"
            f" 'model_revision':{json.dumps(spec.model_revision)},\n"
            f" 'base_image':{json.dumps(spec.base_image)},\n"
            " 'runtime_sha256':'sha256:'+os.environ['runtime_sha'],\n"
            " 'model_manifest_sha256':'sha256:'+os.environ['model_sha'],\n"
            " 'smoke_output_sha256':'sha256:'+os.environ['smoke_sha'],\n"
            " 'gpu':os.environ['gpu'],\n"
            " 'fresh_confirmatory_observation':False,\n"
            " 'sensitive_material_included':False,\n"
            "}\n"
            "Path('/workspace/tavonel-r-http/http/evidence.json').write_text("
            "json.dumps(value,sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')\n"
            "PY",
        )
    )
    failure = "\n".join(
        (
            "export rc",
            "/usr/bin/python3.11 - <<'PY'\n"
            "import json, os\n"
            "from pathlib import Path\n"
            "value={\n"
            " 'schema':'tavonel.recovery.http_runtime_evidence.v1',\n"
            " 'status':'FAIL',\n"
            " 'role':'strong',\n"
            " 'exit_code':int(os.environ.get('rc','1')),\n"
            " 'fresh_confirmatory_observation':False,\n"
            " 'sensitive_material_included':False,\n"
            "}\n"
            "Path('/workspace/tavonel-r-http/http/evidence.json').write_text("
            "json.dumps(value,sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')\n"
            "PY",
        )
    )
    script = (
        setup
        + "\nset +e\n(\n"
        + success
        + "\n)\nrc=$?\nset -e\nif [ $rc -ne 0 ]; then\n"
        + failure
        + "\nfi\nexec /usr/bin/python3.11 -m http.server "
        + str(EVIDENCE_PORT)
        + " --bind 0.0.0.0 --directory $ROOT/http\n"
    )
    inputs = {
        "startup_script_sha256": "sha256:"
        + __import__("hashlib").sha256(script.encode()).hexdigest(),
        "bootstrap_sha256": sha256_file(bootstrap_path),
        "artifact_manifest_sha256": sha256_file(artifact_path),
        "smoke_input_sha256": str(public_input["sha256"]),
        "public_input_binding_sha256": sha256_file(PUBLIC_INPUT_BINDING),
    }
    return script, inputs


def _primary_startup_script() -> tuple[str, dict[str, str]]:
    spec = discover_role_spec("primary")
    public_input = qualification_input_binding()
    input_url = str(public_input["url"])
    input_sha = str(public_input["sha256"]).removeprefix("sha256:")
    relative_paths = (
        spec.bootstrap_relpath,
        "benchmark/runpod_eval/paddle-fastdeploy-backend.yaml",
        "benchmark/runpod_eval/artifact_manifest.py",
        "benchmark/runpod_eval/paddleocr_vl_stage2.py",
        "benchmark/runpod_eval/input_contract.py",
        "benchmark/runpod_eval/isolated_case_process.py",
    )
    local = {path: REPO / path for path in relative_paths}

    setup_lines = [
        "set -uo pipefail",
        "ROOT=/workspace/tavonel-r-http",
        "mkdir -p $ROOT/runner $ROOT/input $ROOT/http $ROOT/paddle-smoke",
        "apt-get update -qq && apt-get install -y -qq --no-install-recommends "
        "git ca-certificates curl jq && rm -rf /var/lib/apt/lists/*",
    ]
    destinations = {
        spec.bootstrap_relpath: "$ROOT/runner/bootstrap.sh",
        "benchmark/runpod_eval/paddle-fastdeploy-backend.yaml": "$ROOT/runner/backend.yaml",
        "benchmark/runpod_eval/artifact_manifest.py": "$ROOT/runner/artifact_manifest.py",
        "benchmark/runpod_eval/paddleocr_vl_stage2.py": "$ROOT/runner/paddleocr_vl_stage2.py",
        "benchmark/runpod_eval/input_contract.py": "$ROOT/runner/input_contract.py",
        "benchmark/runpod_eval/isolated_case_process.py": "$ROOT/runner/isolated_case_process.py",
    }
    for relative in relative_paths:
        setup_lines.append(_shell_write(destinations[relative], local[relative].read_bytes()))
    setup_lines.extend(
        (
            f"curl -fL --retry 4 --retry-delay 3 {json.dumps(input_url)} -o $ROOT/input/input.png",
            f"printf '%s  %s\\n' '{input_sha}' \"$ROOT/input/input.png\" | sha256sum -c -",
            "chmod 700 $ROOT/runner/bootstrap.sh",
        )
    )
    setup = "\n".join(setup_lines)
    success = "\n".join(
        (
            "bash $ROOT/runner/bootstrap.sh $ROOT/runner/backend.yaml "
            "$ROOT/receipts $ROOT/runner/artifact_manifest.py",
            "cd $ROOT/runner",
            "/workspace/folynta/paddle-fastdeploy-venv/bin/python paddleocr_vl_stage2.py "
            "--input-dir $ROOT/input --output-dir $ROOT/paddle-smoke "
            f"--model-revision {spec.model_revision} "
            f"--artifact-manifest-sha256 {spec.model_artifact_digest} "
            "--vl-backend fastdeploy-server --vl-server-url http://127.0.0.1:8118/v1 "
            "--vl-max-concurrency 1 --repeats 1 --limit 1 --evidence-class smoke "
            "--case-timeout-seconds 600",
            "find $ROOT/paddle-smoke -type f -size +0c | grep -q .",
            "model_sha=$(sha256sum $ROOT/receipts/model-artifact-manifest.json | cut -d' ' -f1)",
            f"test \"$model_sha\" = '{spec.expected_model_manifest_sha256}'",
            "runtime_sha=$(sha256sum $ROOT/receipts/runtime-identity.json | cut -d' ' -f1)",
            "smoke_sha=$(find $ROOT/paddle-smoke -type f -print0 | sort -z | "
            "xargs -0 cat | sha256sum | cut -d' ' -f1)",
            "gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)",
            "export model_sha smoke_sha runtime_sha gpu",
            "/usr/bin/python3.11 - <<'PY'\n"
            "import json, os\n"
            "from pathlib import Path\n"
            "value={\n"
            " 'schema':'tavonel.recovery.http_runtime_evidence.v1',\n"
            " 'status':'PASS',\n"
            " 'role':'primary',\n"
            f" 'model_id':{json.dumps(spec.model_id)},\n"
            f" 'model_revision':{json.dumps(spec.model_revision)},\n"
            f" 'base_image':{json.dumps(spec.base_image)},\n"
            " 'runtime_sha256':'sha256:'+os.environ['runtime_sha'],\n"
            " 'model_manifest_sha256':'sha256:'+os.environ['model_sha'],\n"
            " 'smoke_output_sha256':'sha256:'+os.environ['smoke_sha'],\n"
            " 'gpu':os.environ['gpu'],\n"
            " 'fresh_confirmatory_observation':False,\n"
            " 'sensitive_material_included':False,\n"
            "}\n"
            "Path('/workspace/tavonel-r-http/http/evidence.json').write_text("
            "json.dumps(value,sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')\n"
            "PY",
        )
    )
    failure = "\n".join(
        (
            "export rc",
            "/usr/bin/python3.11 - <<'PY'\n"
            "import json, os\n"
            "from pathlib import Path\n"
            "value={\n"
            " 'schema':'tavonel.recovery.http_runtime_evidence.v1',\n"
            " 'status':'FAIL',\n"
            " 'role':'primary',\n"
            " 'exit_code':int(os.environ.get('rc','1')),\n"
            " 'fresh_confirmatory_observation':False,\n"
            " 'sensitive_material_included':False,\n"
            "}\n"
            "Path('/workspace/tavonel-r-http/http/evidence.json').write_text("
            "json.dumps(value,sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')\n"
            "PY",
        )
    )
    script = (
        setup
        + "\nset +e\n(\n"
        + success
        + "\n)\nrc=$?\nset -e\nif [ $rc -ne 0 ]; then\n"
        + failure
        + "\nfi\nexec /usr/bin/python3.11 -m http.server "
        + str(EVIDENCE_PORT)
        + " --bind 0.0.0.0 --directory $ROOT/http\n"
    )
    inputs = {
        "startup_script_sha256": "sha256:"
        + __import__("hashlib").sha256(script.encode()).hexdigest(),
        "smoke_input_sha256": str(public_input["sha256"]),
        "public_input_binding_sha256": sha256_file(PUBLIC_INPUT_BINDING),
    }
    for relative in relative_paths:
        key = Path(relative).name.replace(".", "_") + "_sha256"
        inputs[key] = sha256_file(local[relative])
    return script, inputs


def startup_script(role: str) -> tuple[str, dict[str, str]]:
    if role == "strong":
        return _strong_startup_script()
    if role == "primary":
        return _primary_startup_script()
    raise QualificationRefused(f"HTTP qualification role is unsupported: {role}")


def evidence_url(pod_id: str) -> str:
    if not pod_id or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for ch in pod_id
    ):
        raise QualificationRefused("invalid RunPod pod id for HTTP evidence")
    return f"https://{pod_id}-{EVIDENCE_PORT}.proxy.runpod.net/evidence.json"


def provider_payload(role: str) -> tuple[dict[str, Any], dict[str, str]]:
    authorize_qualification()
    spec = discover_role_spec(role)
    script, inputs = startup_script(role)
    payload = {
        "name": f"tavonel-r-http-qual-{role}-{QUALIFICATION_ATTEMPT}",
        "imageName": spec.base_image,
        "cloudType": "SECURE",
        "computeType": "GPU",
        "gpuTypeIds": ["NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 5090"],
        "gpuTypePriority": "availability",
        "gpuCount": 1,
        "containerDiskInGb": 100,
        "volumeInGb": 20,
        "volumeMountPath": "/workspace",
        "ports": [f"{EVIDENCE_PORT}/http"],
        "supportPublicIp": True,
        "interruptible": False,
        "dockerEntrypoint": ["/bin/bash", "-lc"],
        "dockerStartCmd": [script],
        "env": {"TAVONEL_R_QUALIFICATION_ONLY": "1"},
    }
    encoded = _secret_free_json(payload)
    if len(encoded.encode("utf-8")) > 512_000:
        raise QualificationRefused("self-contained RunPod qualification payload is too large")
    return payload, inputs


def _spawn_watchdog(role: str) -> int:
    command = [sys.executable, str(Path(__file__).resolve()), "watchdog", "--role", role]
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


def start(role: str) -> dict[str, Any]:
    paths = paths_for(role)
    if paths.state.exists():
        raise QualificationRefused("HTTP qualification state already exists")
    payload, inputs = provider_payload(role)
    provider = Provider(read_runpod_b())
    name = str(payload["name"])
    if any(str(item.get("name")) == name for item in provider.list_pods()):
        raise QualificationRefused(
            "provider already contains the deterministic qualification pod name"
        )
    pod = provider.create_pod(payload)
    pod_id = str(pod.get("id") or "")
    if not pod_id:
        raise QualificationRefused("RunPod creation omitted pod id")
    rate = float(pod.get("costPerHr") or pod.get("adjustedCostPerHr") or 0.0)
    if rate <= 0 or rate > BASE_MAX_HOURLY_USD:
        provider.delete_pod(pod_id)
        raise QualificationRefused("qualification hourly rate exceeds frozen ceiling")
    state = {
        "schema": "tavonel.recovery.http_qualification_state.v1",
        "role": role,
        "phase": "provider_running",
        "pod_id": pod_id,
        "hourly_rate_usd": rate,
        "started_at_utc": utc_now(),
        "hard_deadline_utc": (
            datetime.now(UTC) + timedelta(seconds=MAX_RUNTIME_SECONDS)
        ).isoformat(),
        "evidence_url": evidence_url(pod_id),
        "startup_inputs": inputs,
        "fresh_confirmatory_observation": False,
    }
    _write_state(paths, state)
    watchdog_pid = _spawn_watchdog(role)
    state["watchdog_pid"] = watchdog_pid
    _write_state(paths, state)
    _journal(paths, "pod_created", pod_id=pod_id, hourly_rate_usd=rate, watchdog_pid=watchdog_pid)
    return {
        "role": role,
        "phase": "provider_running",
        "pod_id": pod_id,
        "hourly_rate_usd": rate,
        "evidence_url": evidence_url(pod_id),
    }


def _fetch_evidence(url: str) -> dict[str, Any] | None:
    if not url.startswith("https://") or not url.endswith("/evidence.json"):
        raise QualificationRefused("qualification evidence URL is invalid")
    request = urllib.request.Request(  # noqa: S310 - URL prevalidated as HTTPS RunPod proxy
        url, headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            if response.status != 200:
                return None
            raw = response.read(128 * 1024)
    except urllib.error.HTTPError as error:
        # RunPod's public proxy can answer 403/404 while the Pod exists but the
        # exposed service has not started accepting traffic yet.  Provider state
        # and our hard deadline decide liveness; proxy pre-readiness is not a
        # scientific failure signal.
        if error.code in {403, 404, 502, 503, 504}:
            return None
        raise QualificationRefused(f"qualification evidence HTTP failure: {error.code}") from None
    except OSError:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise QualificationRefused("qualification evidence is not JSON") from error
    if not isinstance(value, dict):
        raise QualificationRefused("qualification evidence shape is invalid")
    return value


def _validate_remote_evidence(role: str, value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema") != "tavonel.recovery.http_runtime_evidence.v1":
        raise QualificationRefused("qualification evidence schema mismatch")
    if value.get("role") != role:
        raise QualificationRefused("qualification role mismatch")
    if value.get("fresh_confirmatory_observation") is not False:
        raise QualificationRefused("qualification evidence touched fresh confirmatory data")
    if value.get("sensitive_material_included") is not False:
        raise QualificationRefused("qualification evidence reports sensitive material")
    if value.get("status") != "PASS":
        raise QualificationRefused("qualification pod reported FAIL")
    spec = discover_role_spec(role)
    if value.get("model_id") != spec.model_id or value.get("model_revision") != spec.model_revision:
        raise QualificationRefused("qualified model identity drifted")
    if value.get("base_image") != spec.base_image:
        raise QualificationRefused("qualified base image drifted")
    model_manifest = str(value.get("model_manifest_sha256") or "")
    if model_manifest != spec.model_artifact_digest:
        raise QualificationRefused("qualified model artifact manifest drifted")
    for key in ("runtime_sha256", "smoke_output_sha256"):
        item = str(value.get(key) or "")
        if not item.startswith("sha256:") or len(item) != 71:
            raise QualificationRefused(f"qualification evidence {key} is invalid")
    if not str(value.get("gpu") or "").strip():
        raise QualificationRefused("qualification GPU identity is missing")
    return value


def advance(role: str) -> dict[str, Any]:
    paths = paths_for(role)
    state = _read_state(paths)
    if str(state.get("phase")) == "complete":
        return {
            "role": role,
            "phase": "complete",
            "attestation_digest": state.get("attestation_digest"),
            "provider_deleted": bool(state.get("provider_deleted")),
        }
    provider = Provider(read_runpod_b())
    pod_id = str(state.get("pod_id") or "")
    if datetime.now(UTC) >= datetime.fromisoformat(str(state["hard_deadline_utc"])):
        if provider.get_pod(pod_id) is not None:
            provider.delete_pod(pod_id)
        state.update({"phase": "hard_deadline_cleaned", "provider_deleted": True})
        _write_state(paths, state)
        _journal(paths, "hard_deadline_cleanup", pod_id=pod_id)
        raise QualificationRefused("qualification hard deadline reached")
    remote = _fetch_evidence(str(state["evidence_url"]))
    if remote is None:
        pod = provider.get_pod(pod_id)
        if pod is None:
            raise QualificationRefused("qualification pod disappeared without evidence")
        return {"role": role, "phase": "provider_running", "remote_evidence": False}
    try:
        evidence = _validate_remote_evidence(role, remote)
    except Exception:
        if provider.get_pod(pod_id) is not None:
            provider.delete_pod(pod_id)
        state.update({"phase": "failed_cleaned", "provider_deleted": True})
        _write_state(paths, state)
        _journal(paths, "remote_evidence_refused_cleanup", pod_id=pod_id)
        raise

    spec = discover_role_spec(role)
    input_manifest = qualification_input_binding()
    source_paths = (spec.bootstrap_relpath, spec.prompt_relpath, *spec.extra_pin_paths)
    pins = pin_files(REPO, tuple(("runtime_input", path) for path in source_paths))
    observed_runtime = {
        "provider": "runpod_secure_cloud",
        "pod_id": pod_id,
        "gpu": evidence["gpu"],
        "hourly_rate_usd": float(state["hourly_rate_usd"]),
        "runtime_identity_sha256": evidence["runtime_sha256"],
        "model_manifest_sha256": evidence["model_manifest_sha256"],
        "smoke_output_sha256": evidence["smoke_output_sha256"],
        "smoke_input_sha256": state["startup_inputs"]["smoke_input_sha256"],
        "startup_script_sha256": state["startup_inputs"]["startup_script_sha256"],
        "started_at_utc": state["started_at_utc"],
        "completed_at_utc": utc_now(),
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
    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
    receipt = RECEIPT_ROOT / f"{role}.json"
    if receipt.exists():
        raise QualificationRefused("runtime qualification receipt already exists")
    receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if provider.get_pod(pod_id) is not None:
        provider.delete_pod(pod_id)
    state.update(
        {
            "phase": "complete",
            "provider_deleted": True,
            "attestation_digest": attestation.digest(),
        }
    )
    _write_state(paths, state)
    _journal(
        paths, "qualification_complete", pod_id=pod_id, attestation_digest=attestation.digest()
    )
    return {
        "role": role,
        "phase": "complete",
        "attestation_digest": attestation.digest(),
        "provider_deleted": True,
    }


def cleanup(role: str) -> dict[str, Any]:
    paths = paths_for(role)
    state = _read_state(paths)
    provider = Provider(read_runpod_b())
    pod_id = str(state.get("pod_id") or "")
    if pod_id and provider.get_pod(pod_id) is not None:
        provider.delete_pod(pod_id)
    state.update({"phase": "cleaned_up", "provider_deleted": True})
    _write_state(paths, state)
    _journal(paths, "manual_cleanup_verified", pod_id=pod_id)
    return {"role": role, "provider_deleted": True}


def watchdog(role: str) -> int:
    paths = paths_for(role)
    while True:
        try:
            state = _read_state(paths)
        except QualificationRefused:
            return 0
        if str(state.get("phase")) in {"complete", "cleaned_up", "failed_cleaned"}:
            return 0
        deadline = datetime.fromisoformat(str(state.get("hard_deadline_utc")))
        if datetime.now(UTC) < deadline:
            time.sleep(30)
            continue
        pod_id = str(state.get("pod_id") or "")
        try:
            provider = Provider(read_runpod_b())
            if pod_id and provider.get_pod(pod_id) is not None:
                provider.delete_pod(pod_id)
            state.update({"phase": "hard_deadline_cleaned", "provider_deleted": True})
            _write_state(paths, state)
            _journal(paths, "hard_deadline_watchdog_cleanup", pod_id=pod_id)
            return 0
        except Exception as error:  # pragma: no cover - final external backstop
            _journal(paths, "hard_deadline_watchdog_failed", error_type=type(error).__name__)
            return 3


def plan(role: str) -> dict[str, Any]:
    spec = discover_role_spec(role)
    input_manifest = qualification_input_binding()
    payload, startup_inputs = provider_payload(role)
    safe_payload = dict(payload)
    safe_payload["dockerStartCmd"] = ["sha256-bound-self-contained-startup"]
    return {
        "schema": "tavonel.recovery.http_qualification_plan.v1",
        "evidence_class": "DEVELOPMENT_RUNTIME_QUALIFICATION_ONLY",
        "role": role,
        "candidate_id": spec.candidate_id,
        "model_id": spec.model_id,
        "model_revision": spec.model_revision,
        "model_artifact_digest": spec.model_artifact_digest,
        "base_image": spec.base_image,
        "qualification_input_manifest_digest": canonical_digest(input_manifest),
        "startup_inputs": startup_inputs,
        "provider_request_without_startup_bytes": safe_payload,
        "payload_bytes": len(_secret_free_json(payload).encode("utf-8")),
        "limits": {
            "pages": 1,
            "gpu_seconds": MAX_RUNTIME_SECONDS,
            "estimated_external_cost_usd": MAX_ESTIMATED_COST_USD,
            "max_hourly_rate_usd": BASE_MAX_HOURLY_USD,
        },
        "fresh_confirmatory_observation": False,
        "sensitive_material_included": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "start", "advance", "cleanup", "watchdog"):
        command = sub.add_parser(name)
        command.add_argument("--role", choices=("strong", "primary"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            value = plan(args.role)
        elif args.command == "start":
            value = start(args.role)
        elif args.command == "advance":
            value = advance(args.role)
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
