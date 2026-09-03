#!/usr/bin/env python3
"""SSH-free, stop/resume-safe RunPod qualification controller for TAVONEL-R.

This is the preferred paid qualification route when a Pod is RUNNING but RunPod
has not assigned a public SSH endpoint.  It reuses the already-reviewed HTTP
proxy evidence protocol while fixing three operational hazards from earlier
attempts:

* no SSH/public-IP dependency at all;
* every failure/deadline releases paid GPU with STOP before any destructive
  cleanup, preserving /workspace caches for a bounded resume;
* local wall-clock budget and RunPod Pod-billing evidence are carried across
  resumes instead of resetting the qualification allowance.

Only the already-spent public qualification page is visible here.  Fresh
confirmatory data must not be mounted until both primary and strong roles have
sealed runtime attestations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import runpod_http_qualification as legacy_http
from runpod_qualification import (
    BASE_MAX_HOURLY_USD,
    MAX_ESTIMATED_COST_USD,
    MAX_RUNTIME_SECONDS,
    Provider,
    QualificationRefused,
    _billing_snapshot,
    _consume_running_budget,
    authorize_qualification,
    discover_role_spec,
    read_runpod_b,
)
from runtime_attestation import RuntimeAttestation, canonical_digest, pin_files, sha256_file

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ATTEMPT = "v3-persisted-safe"
PRIVATE_ROOT = HERE / ".private" / "runpod-http-safe-qualification" / ATTEMPT
RECEIPT_ROOT = HERE / "receipts" / "runtime-qualification"
EVIDENCE_PORT = 8001
PERSIST_ROOT = "/workspace/folynta"
STRONG_VENV = f"{PERSIST_ROOT}/mineru-3.4.4-venv"
STRONG_MODEL = f"{PERSIST_ROOT}/models/MinerU2.5-Pro-2605-1.2B"
PRIMARY_VENV = f"{PERSIST_ROOT}/paddle-fastdeploy-venv"


class SafeQualificationRefused(QualificationRefused):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_time(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SafeQualificationRefused(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SafeQualificationRefused(f"{label} timestamp must be timezone-aware")
    return parsed


def role_root(role: str) -> Path:
    return PRIVATE_ROOT / role


def state_path(role: str) -> Path:
    return role_root(role) / "state.json"


def journal_path(role: str) -> Path:
    return role_root(role) / "provider.jsonl"


def _secret_free_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    folded = raw.casefold()
    for marker in ("runpod_b", "authorization", "bearer ", "api_key", "apikey"):
        if marker in folded:
            raise SafeQualificationRefused("secret-like material would enter safe qualification state")
    return raw


def _write_state(role: str, value: dict[str, Any]) -> None:
    root = role_root(role)
    root.mkdir(parents=True, exist_ok=True)
    temp = state_path(role).with_suffix(".tmp")
    temp.write_text(_secret_free_json(value) + "\n", encoding="utf-8")
    os.replace(temp, state_path(role))


def _read_state(role: str) -> dict[str, Any]:
    path = state_path(role)
    if not path.is_file():
        raise SafeQualificationRefused("safe HTTP qualification state is absent")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SafeQualificationRefused("safe HTTP qualification state is malformed")
    if value.get("role") != role:
        raise SafeQualificationRefused("safe HTTP qualification role/state mismatch")
    return value


def _journal(role: str, event: str, **fields: Any) -> None:
    root = role_root(role)
    root.mkdir(parents=True, exist_ok=True)
    row = {"event": event, "observed_at_utc": utc_now(), **fields}
    with journal_path(role).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_secret_free_json(row) + "\n")


def _replace_exact(text: str, old: str, new: str, *, label: str, minimum: int = 1) -> str:
    count = text.count(old)
    if count < minimum:
        raise SafeQualificationRefused(f"safe startup transform anchor missing: {label}")
    return text.replace(old, new)


def safe_startup_script(role: str) -> tuple[str, dict[str, str]]:
    """Derive the HTTP startup from reviewed legacy bytes, then harden it deterministically."""
    raw, pins = legacy_http.startup_script(role)
    script = raw
    # The pinned RunPod image family has changed Python patch versions across
    # availability pools. Resolve Python on the Pod instead of claiming 3.11.
    script = script.replace(
        "set -uo pipefail",
        "set -uo pipefail\nSYSTEM_PYTHON=\"$(command -v python3 || command -v python || true)\"\n"
        "test -n \"$SYSTEM_PYTHON\"",
        1,
    )
    script = _replace_exact(
        script,
        "/usr/bin/python3.11",
        '"$SYSTEM_PYTHON"',
        label="system python hardcode",
    )
    # Every container restart must discard stale qualification *evidence* while
    # retaining the expensive role runtime/model caches under /workspace/folynta.
    script = script.replace(
        "mkdir -p $ROOT/runner $ROOT/input",
        "rm -rf $ROOT/receipts $ROOT/paddle-smoke $ROOT/smoke-output; "
        "rm -f $ROOT/http/evidence.json 2>/dev/null || true\n"
        "mkdir -p $ROOT/runner $ROOT/input",
        1,
    )
    if role == "strong":
        script = _replace_exact(
            script,
            "/usr/local/bin/mineru",
            f"{STRONG_VENV}/bin/mineru",
            label="strong executable",
        )
        # The current bootstrap stores the exact model snapshot on the persistent
        # workspace. Bind the manifest verifier to that same directory.
        script, count = re.subn(
            r"--root\s+\S*MinerU2\.5-Pro-2605-1\.2B",
            f"--root {STRONG_MODEL}",
            script,
        )
        if count != 1:
            raise SafeQualificationRefused(
                f"strong persisted model-root transform resolved {count} times"
            )
    elif role == "primary":
        if PRIMARY_VENV not in script:
            raise SafeQualificationRefused("primary persistent runtime root is absent from startup")
    else:
        raise SafeQualificationRefused(f"unsupported safe qualification role: {role}")
    if "/usr/bin/python3.11" in script or "sshd" in script:
        raise SafeQualificationRefused("safe qualification retained a hardcoded Python/SSH dependency")
    return script, dict(pins)


def provider_payload(role: str) -> tuple[dict[str, Any], dict[str, str]]:
    authorize_qualification()
    spec = discover_role_spec(role)
    script, pins = safe_startup_script(role)
    payload = {
        "name": f"tavonel-r-http-safe-{role}-{ATTEMPT}",
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
    if len(_secret_free_json(payload).encode("utf-8")) > 512_000:
        raise SafeQualificationRefused("safe HTTP qualification payload exceeds frozen bound")
    return payload, pins


def evidence_url(pod_id: str) -> str:
    return legacy_http.evidence_url(pod_id)


def _spawn_watchdog(role: str) -> int:
    command = [sys.executable, str(Path(__file__).resolve()), "watchdog", "--role", role]
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    process = subprocess.Popen(  # noqa: S603
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )
    return int(process.pid)


def _stop_preserving_cache(
    role: str,
    state: dict[str, Any],
    provider: Provider,
    *,
    phase: str,
    event: str,
) -> dict[str, Any]:
    _consume_running_budget(state)
    pod_id = str(state.get("pod_id") or "")
    pod = provider.get_pod(pod_id)
    if pod is not None and str(pod.get("desiredStatus", "")).upper() not in {"STOPPED", "EXITED"}:
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
    _write_state(role, state)
    _journal(
        role,
        event,
        pod_id=pod_id,
        billing_status=billing.get("status"),
        remaining_gpu_seconds=state.get("remaining_gpu_seconds"),
    )
    return billing


def start(role: str) -> dict[str, Any]:
    authorize_qualification()
    if state_path(role).exists():
        raise SafeQualificationRefused("safe HTTP qualification state already exists")
    payload, startup_inputs = provider_payload(role)
    provider = Provider(read_runpod_b())
    name = str(payload["name"])
    if any(str(item.get("name")) == name for item in provider.list_pods()):
        raise SafeQualificationRefused("provider already contains deterministic safe qualification pod")
    pod = provider.create_pod(payload)
    pod_id = str(pod.get("id") or "")
    if not pod_id:
        raise SafeQualificationRefused("RunPod creation omitted pod identity")
    rate = float(pod.get("costPerHr") or pod.get("adjustedCostPerHr") or 0.0)
    if rate <= 0 or rate > BASE_MAX_HOURLY_USD:
        try:
            provider.stop_pod(pod_id)
        finally:
            raise SafeQualificationRefused("qualification hourly rate exceeds frozen ceiling")
    now = datetime.now(UTC)
    state = {
        "schema": "tavonel.recovery.http_safe_qualification_state.v1",
        "role": role,
        "phase": "provider_running",
        "pod_id": pod_id,
        "hourly_rate_usd": rate,
        "started_at_utc": now.isoformat(),
        "running_started_at_utc": now.isoformat(),
        "hard_deadline_utc": (now + timedelta(seconds=MAX_RUNTIME_SECONDS)).isoformat(),
        "remaining_gpu_seconds": float(MAX_RUNTIME_SECONDS),
        "gpu_seconds_consumed_local": 0.0,
        "evidence_url": evidence_url(pod_id),
        "startup_inputs": startup_inputs,
        "provider_stopped": False,
        "provider_deleted": False,
        "fresh_confirmatory_observation": False,
    }
    _write_state(role, state)
    watchdog_pid = _spawn_watchdog(role)
    state["watchdog_pid"] = watchdog_pid
    _write_state(role, state)
    _journal(role, "pod_created", pod_id=pod_id, hourly_rate_usd=rate, watchdog_pid=watchdog_pid)
    return {
        "role": role,
        "phase": "provider_running",
        "pod_id": pod_id,
        "hourly_rate_usd": rate,
        "evidence_url": state["evidence_url"],
    }


def _seal_attestation(role: str, state: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    spec = discover_role_spec(role)
    input_manifest = legacy_http.qualification_input_binding()
    source_paths = (spec.bootstrap_relpath, spec.prompt_relpath, *spec.extra_pin_paths)
    pins = pin_files(REPO, tuple(("runtime_input", path) for path in source_paths))
    billing = state.get("last_pod_billing")
    if not isinstance(billing, dict):
        raise SafeQualificationRefused("safe qualification stopped without Pod billing evidence")
    observed_runtime = {
        "provider": "runpod_secure_cloud",
        "pod_id": str(state["pod_id"]),
        "gpu": evidence["gpu"],
        "hourly_rate_usd": float(state["hourly_rate_usd"]),
        "runtime_identity_sha256": evidence["runtime_sha256"],
        "model_manifest_sha256": evidence["model_manifest_sha256"],
        "smoke_output_sha256": evidence["smoke_output_sha256"],
        "smoke_input_sha256": state["startup_inputs"]["smoke_input_sha256"],
        "startup_script_sha256": state["startup_inputs"]["startup_script_sha256"],
        "started_at_utc": state["started_at_utc"],
        "completed_at_utc": utc_now(),
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
    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
    receipt = RECEIPT_ROOT / f"{role}.json"
    if receipt.exists():
        raise SafeQualificationRefused("runtime qualification receipt already exists")
    with receipt.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    provider_deleted = False
    provider = Provider(read_runpod_b())
    try:
        if provider.get_pod(str(state["pod_id"])) is not None:
            provider.delete_pod(str(state["pod_id"]))
        provider_deleted = True
    except QualificationRefused:
        # Scientific qualification is already sealed and paid GPU is stopped.
        # Cleanup may be retried explicitly without invalidating the receipt.
        provider_deleted = False
    state.update(
        {
            "phase": "complete",
            "attestation_digest": attestation.digest(),
            "provider_deleted": provider_deleted,
        }
    )
    _write_state(role, state)
    _journal(
        role,
        "qualification_complete",
        pod_id=state["pod_id"],
        attestation_digest=attestation.digest(),
        provider_deleted=provider_deleted,
    )
    return {
        "role": role,
        "phase": "complete",
        "attestation_digest": attestation.digest(),
        "provider_deleted": provider_deleted,
    }


def advance(role: str) -> dict[str, Any]:
    state = _read_state(role)
    phase = str(state.get("phase") or "")
    if phase == "complete":
        return {
            "role": role,
            "phase": "complete",
            "attestation_digest": state.get("attestation_digest"),
            "provider_deleted": bool(state.get("provider_deleted")),
        }
    if phase != "provider_running":
        raise SafeQualificationRefused(f"safe HTTP qualification is not running: {phase}")
    provider = Provider(read_runpod_b())
    if datetime.now(UTC) >= _parse_time(state["hard_deadline_utc"], label="hard deadline"):
        _stop_preserving_cache(
            role,
            state,
            provider,
            phase="hard_deadline_stopped",
            event="hard_deadline_stopped_cache_preserved",
        )
        raise SafeQualificationRefused("qualification hard deadline reached; GPU stopped, cache preserved")
    remote = legacy_http._fetch_evidence(str(state["evidence_url"]))
    if remote is None:
        pod = provider.get_pod(str(state["pod_id"]))
        if pod is None:
            raise SafeQualificationRefused("safe qualification pod disappeared without evidence")
        if str(pod.get("desiredStatus", "")).upper() in {"STOPPED", "EXITED"}:
            _consume_running_budget(state)
            state["phase"] = "provider_stopped_without_evidence"
            state["provider_stopped"] = True
            _write_state(role, state)
            raise SafeQualificationRefused("provider stopped before qualification evidence; resume is required")
        return {"role": role, "phase": "provider_running", "remote_evidence": False}
    try:
        evidence = legacy_http._validate_remote_evidence(role, remote)
    except Exception:
        _stop_preserving_cache(
            role,
            state,
            provider,
            phase="remote_evidence_refused_stopped",
            event="remote_evidence_refused_stopped_cache_preserved",
        )
        raise
    _stop_preserving_cache(
        role,
        state,
        provider,
        phase="qualification_evidence_stopped",
        event="qualification_evidence_stopped_before_seal",
    )
    return _seal_attestation(role, state, evidence)


_RESUMABLE = frozenset(
    {
        "hard_deadline_stopped",
        "remote_evidence_refused_stopped",
        "provider_stopped_without_evidence",
    }
)


def resume(role: str) -> dict[str, Any]:
    authorize_qualification()
    state = _read_state(role)
    phase = str(state.get("phase") or "")
    if phase not in _RESUMABLE:
        raise SafeQualificationRefused(f"safe qualification phase is not resumable: {phase}")
    remaining = float(state.get("remaining_gpu_seconds", 0.0))
    if remaining <= 0:
        raise SafeQualificationRefused("qualification GPU-time budget is exhausted")
    provider = Provider(read_runpod_b())
    pod_id = str(state.get("pod_id") or "")
    pod = provider.get_pod(pod_id)
    if pod is None:
        raise SafeQualificationRefused("stopped safe qualification Pod is absent; duplicate creation refused")
    if str(pod.get("desiredStatus", "")).upper() != "RUNNING":
        provider.start_pod(pod_id)
    now = datetime.now(UTC)
    state.update(
        {
            "phase": "provider_running",
            "running_started_at_utc": now.isoformat(),
            "hard_deadline_utc": (now + timedelta(seconds=remaining)).isoformat(),
            "provider_stopped": False,
            "stopped_at_utc": None,
        }
    )
    _write_state(role, state)
    _journal(role, "qualification_resumed", pod_id=pod_id, remaining_gpu_seconds=remaining)
    return {
        "role": role,
        "phase": "provider_running",
        "pod_id": pod_id,
        "remaining_gpu_seconds": remaining,
        "evidence_url": state["evidence_url"],
    }


def cleanup(role: str) -> dict[str, Any]:
    state = _read_state(role)
    provider = Provider(read_runpod_b())
    pod_id = str(state.get("pod_id") or "")
    pod = provider.get_pod(pod_id) if pod_id else None
    if pod is not None and str(pod.get("desiredStatus", "")).upper() not in {"STOPPED", "EXITED"}:
        provider.stop_pod(pod_id)
    if pod_id and provider.get_pod(pod_id) is not None:
        provider.delete_pod(pod_id)
    state.update({"phase": "cleaned_up", "provider_stopped": True, "provider_deleted": True})
    _write_state(role, state)
    _journal(role, "manual_cleanup_verified", pod_id=pod_id)
    return {"role": role, "provider_deleted": True}


def watchdog(role: str) -> int:
    while True:
        try:
            state = _read_state(role)
        except QualificationRefused:
            return 0
        phase = str(state.get("phase") or "")
        if phase in {"complete", "cleaned_up"} or phase in _RESUMABLE:
            return 0
        deadline_raw = state.get("hard_deadline_utc")
        if not deadline_raw:
            return 0
        deadline = _parse_time(deadline_raw, label="hard deadline")
        if datetime.now(UTC) < deadline:
            time.sleep(30)
            continue
        try:
            provider = Provider(read_runpod_b())
            _stop_preserving_cache(
                role,
                state,
                provider,
                phase="hard_deadline_stopped",
                event="hard_deadline_watchdog_stopped_cache_preserved",
            )
            return 0
        except Exception as exc:  # pragma: no cover - external final backstop
            _journal(role, "hard_deadline_watchdog_failed", error_type=type(exc).__name__)
            return 3


def plan(role: str) -> dict[str, Any]:
    spec = discover_role_spec(role)
    input_manifest = legacy_http.qualification_input_binding()
    payload, pins = provider_payload(role)
    safe_payload = dict(payload)
    safe_payload["dockerStartCmd"] = ["[REDACTED]"]
    return {
        "schema": "tavonel.recovery.http_safe_qualification_plan.v1",
        "evidence_class": "DEVELOPMENT_RUNTIME_QUALIFICATION_ONLY",
        "role": role,
        "candidate_id": spec.candidate_id,
        "model_id": spec.model_id,
        "model_revision": spec.model_revision,
        "model_artifact_digest": spec.model_artifact_digest,
        "qualification_input_manifest_digest": canonical_digest(input_manifest),
        "startup_inputs": pins,
        "provider_request_without_startup_bytes": safe_payload,
        "limits": {
            "pages": 1,
            "gpu_seconds": MAX_RUNTIME_SECONDS,
            "estimated_external_cost_usd": MAX_ESTIMATED_COST_USD,
            "max_hourly_rate_usd": BASE_MAX_HOURLY_USD,
        },
        "runtime_persistence": {
            "volume_mount": "/workspace",
            "strong_runtime_root": STRONG_VENV,
            "strong_model_root": STRONG_MODEL,
            "primary_runtime_root": PRIMARY_VENV,
            "resume_supported": True,
            "deadline_recomputed_from_remaining_gpu_seconds": True,
        },
        "failure_default": "stop_preserve_workspace_before_delete",
        "pod_billing_surface": "/billing/pods",
        "fresh_confirmatory_observation": False,
        "sensitive_material_included": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "start", "advance", "resume", "cleanup", "watchdog"):
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
        elif args.command == "resume":
            value = resume(args.role)
        elif args.command == "cleanup":
            value = cleanup(args.role)
        else:
            return watchdog(args.role)
    except QualificationRefused as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
