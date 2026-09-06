#!/usr/bin/env python3
"""V8 phase-instrumented same-Pod runtime qualification for TAVONEL-R.

V7 proved that the provider received the intended hardened startup bytes, but a
remote FAIL payload did not reveal which stage failed.  V8 does not create a
new Pod.  It updates the stopped V7 Pod's ``dockerStartCmd`` in place so the
normal /workspace Pod volume (and expensive model/runtime cache) is retained,
then restarts that same Pod under the remaining V7 GPU-time budget.

The startup writes a coarse, outcome-free phase before each qualification
stage.  A FAIL payload contains only phase + exit code; a PASS payload must
carry complete runtime/model/smoke digests and can seal the normal Strong
runtime attestation.  Fresh confirmatory data is never mounted here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

import runpod_http_integrity_qualification as v7


base = v7.base
ATTEMPT = "v8-phase-instrumented-same-pod"
PRIVATE_ROOT = base.HERE / ".private" / "runpod-http-safe-qualification" / ATTEMPT
RECEIPT_ROOT = base.HERE / "receipts" / "runtime-qualification"
INCIDENT_ROOT = base.HERE / "receipts" / "runtime-qualification-incidents"
_TERMINAL_PHASES = frozenset(
    {"complete", "remote_fail_stopped", "hard_deadline_stopped", "start_failed"}
)


class PhaseQualificationRefused(base.SafeQualificationRefused):
    pass


class RemotePhaseFailure(PhaseQualificationRefused):
    def __init__(self, phase: str, exit_code: int):
        super().__init__(f"remote qualification FAIL at phase={phase} exit_code={exit_code}")
        self.phase = phase
        self.exit_code = exit_code


def _canonical(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    folded = raw.casefold()
    for marker in ("runpod_b", "authorization", "bearer ", "api_key", "apikey"):
        if marker in folded:
            raise PhaseQualificationRefused("secret-like material would enter v8 state")
    return raw


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _script_sha(script: str) -> str:
    return "sha256:" + hashlib.sha256(script.encode("utf-8")).hexdigest()


def state_path(role: str) -> Path:
    return PRIVATE_ROOT / role / "state.json"


def journal_path(role: str) -> Path:
    return PRIVATE_ROOT / role / "provider.jsonl"


def _write_state(role: str, value: Mapping[str, Any]) -> None:
    root = PRIVATE_ROOT / role
    root.mkdir(parents=True, exist_ok=True)
    temp = state_path(role).with_suffix(".tmp")
    temp.write_text(_canonical(dict(value)) + "\n", encoding="utf-8")
    os.replace(temp, state_path(role))


def _read_state(role: str) -> dict[str, Any]:
    path = state_path(role)
    if not path.is_file():
        raise PhaseQualificationRefused("v8 qualification state is absent")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("role") != role:
        raise PhaseQualificationRefused("v8 qualification state is malformed")
    return value


def _journal(role: str, event: str, **fields: Any) -> None:
    root = PRIVATE_ROOT / role
    root.mkdir(parents=True, exist_ok=True)
    row = {"event": event, "observed_at_utc": datetime.now(UTC).isoformat(), **fields}
    with journal_path(role).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical(row) + "\n")


def controller_pins() -> dict[str, str]:
    return {
        "phase_controller_entrypoint_sha256": _sha(Path(__file__).resolve()),
        "v7_integrity_controller_sha256": _sha(Path(v7.__file__).resolve()),
        "safe_controller_snapshot_sha256": _sha(Path(base.__file__).resolve()),
        "http_validator_sha256": _sha(Path(v7.legacy_http.__file__).resolve()),
        "runpod_provider_module_sha256": _sha(base.HERE / "runpod_qualification.py"),
        "runtime_attestation_module_sha256": _sha(base.HERE / "runtime_attestation.py"),
    }


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PhaseQualificationRefused(f"v8 startup anchor {label} resolved {count} times")
    return text.replace(old, new, 1)


def _unique_line(text: str, contains: str, *, label: str) -> str:
    rows = [line for line in text.splitlines() if contains in line]
    if len(rows) != 1:
        raise PhaseQualificationRefused(f"v8 startup line {label} resolved {len(rows)} times")
    return rows[0]


def phase_startup_script(role: str) -> tuple[str, dict[str, str]]:
    if role != "strong":
        raise PhaseQualificationRefused("v8 same-Pod phase successor currently accepts Strong only")
    payload, pins = v7.provider_payload(role)
    script = str(payload["dockerStartCmd"][0])
    mkdir_line = _unique_line(script, "mkdir -p $ROOT/runner $ROOT/input", label="workspace mkdir")
    phase_helper = (
        mkdir_line
        + "\nmkdir -p $ROOT/http\n"
        + "phase() { printf '%s\\n' \"$1\" > $ROOT/http/current-phase; }\n"
        + "phase PREPARED"
    )
    script = _replace_once(script, mkdir_line, phase_helper, label="phase helper")

    bootstrap_line = _unique_line(
        script, "RECEIPT_ROOT=$ROOT/receipts", label="strong bootstrap command"
    )
    script = _replace_once(
        script,
        bootstrap_line,
        "phase BOOTSTRAP_STARTED\n" + bootstrap_line + "\nphase BOOTSTRAP_DONE",
        label="bootstrap phases",
    )

    manifest_line = _unique_line(
        script,
        '"$SYSTEM_PYTHON" $ROOT/runner/artifact_manifest.py',
        label="manifest execution command",
    )
    script = _replace_once(
        script,
        manifest_line,
        "phase MODEL_MANIFEST_STARTED\n" + manifest_line,
        label="manifest start",
    )
    model_test = _unique_line(script, 'test "$model_sha" =', label="model digest test")
    script = _replace_once(
        script,
        model_test,
        model_test + "\nphase MODEL_MANIFEST_DONE",
        label="manifest done",
    )

    smoke_line = _unique_line(script, "MINERU_MODEL_SOURCE=local", label="strong smoke command")
    script = _replace_once(
        script,
        smoke_line,
        "phase SMOKE_STARTED\n" + smoke_line,
        label="smoke start",
    )
    smoke_digest_line = _unique_line(script, "smoke_sha=$(find", label="smoke digest assignment")
    # smoke assignment spans two lines; its integrity grep is the reliable end anchor.
    smoke_grep = _unique_line(script, '"$smoke_sha" | grep -Eq', label="smoke digest integrity")
    script = _replace_once(
        script,
        smoke_grep,
        smoke_grep + "\nphase SMOKE_DONE",
        label="smoke done",
    )
    if smoke_digest_line not in script:
        raise PhaseQualificationRefused("v8 smoke digest assignment disappeared")

    runtime_line = _unique_line(script, "runtime_sha=$(sha256sum", label="runtime digest")
    script = _replace_once(
        script,
        runtime_line,
        "phase RUNTIME_DIGEST_STARTED\n" + runtime_line,
        label="runtime start",
    )
    runtime_grep = _unique_line(script, '"$runtime_sha" | grep -Eq', label="runtime integrity")
    script = _replace_once(
        script,
        runtime_grep,
        runtime_grep + "\nphase RUNTIME_DIGEST_DONE",
        label="runtime done",
    )
    export_line = _unique_line(
        script, "export model_sha smoke_sha runtime_sha gpu", label="PASS evidence export"
    )
    script = _replace_once(
        script,
        export_line,
        "phase EVIDENCE_PASS\n" + export_line,
        label="PASS phase",
    )

    # Preserve the original FAIL receipt but add the last durable coarse phase.
    failure_export = _unique_line(script, "export rc", label="FAIL export")
    script = _replace_once(
        script,
        failure_export,
        failure_export
        + "\nexport current_phase=\"$(cat $ROOT/http/current-phase 2>/dev/null || printf UNKNOWN)\"",
        label="FAIL phase export",
    )
    failure_status = "'status':'FAIL',"
    script = _replace_once(
        script,
        failure_status,
        failure_status + '\n \'phase\':os.environ.get("current_phase","UNKNOWN"),',
        label="FAIL payload phase",
    )
    bound = dict(pins)
    bound["startup_script_sha256"] = _script_sha(script)
    bound["phase_instrumentation"] = "v8-coarse-phase-v1"
    return script, bound


def _fetch(url: str) -> dict[str, Any] | None:
    return v7._fetch_evidence(url)


def validate_remote(role: str, value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema") != "tavonel.recovery.http_runtime_evidence.v1":
        raise PhaseQualificationRefused("remote evidence schema is invalid")
    if value.get("role") != role:
        raise PhaseQualificationRefused("remote evidence role mismatch")
    if value.get("fresh_confirmatory_observation") is not False:
        raise PhaseQualificationRefused("remote evidence touched fresh confirmatory data")
    if value.get("sensitive_material_included") is not False:
        raise PhaseQualificationRefused("remote evidence reports sensitive material")
    status = str(value.get("status") or "")
    if status != "PASS":
        phase = str(value.get("phase") or "UNKNOWN")
        try:
            exit_code = int(value.get("exit_code"))
        except (TypeError, ValueError) as exc:
            raise PhaseQualificationRefused("remote FAIL evidence lacks a valid exit code") from exc
        raise RemotePhaseFailure(phase, exit_code)
    return v7._validate_remote_evidence(role, value)


def _v7_predecessor(role: str) -> dict[str, Any]:
    with v7._activated():
        value = v7.base._read_state(role)
    if value.get("role") != role:
        raise PhaseQualificationRefused("v7 predecessor role mismatch")
    if not value.get("provider_stopped"):
        raise PhaseQualificationRefused("v7 predecessor must be stopped before same-Pod update")
    remaining = float(value.get("remaining_gpu_seconds", 0.0))
    if remaining <= 0:
        raise PhaseQualificationRefused("v7 predecessor has no remaining GPU budget")
    return value


def _provider_update(provider: Any, pod_id: str, script: str) -> None:
    result = provider._request("PATCH", f"/pods/{pod_id}", {"dockerStartCmd": [script]})
    if result is not None and not isinstance(result, dict):
        raise PhaseQualificationRefused("RunPod Pod-update response shape is invalid")


def _provider_script_hash(pod: Mapping[str, Any]) -> str | None:
    command = pod.get("dockerStartCmd")
    if not isinstance(command, list) or len(command) != 1 or not isinstance(command[0], str):
        return None
    return _script_sha(command[0])


def _spawn_watchdog(role: str) -> int:
    command = [sys.executable, str(Path(__file__).resolve()), "watchdog", "--role", role]
    flags = 0
    if os.name == "nt":
        # DETACHED_PROCESS can still leave the venv launcher attached to a
        # visible conhost. CREATE_NO_WINDOW keeps the watchdog background-only
        # while preserving an independent process group for lifecycle control.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen(  # noqa: S603
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )
    return int(process.pid)


def prepare(role: str) -> dict[str, Any]:
    if role != "strong":
        raise PhaseQualificationRefused("v8 prepare supports Strong only")
    if state_path(role).exists():
        raise PhaseQualificationRefused("v8 state already exists")
    base.authorize_qualification()
    predecessor = _v7_predecessor(role)
    provider = base.Provider(base.read_runpod_b())
    pod_id = str(predecessor.get("pod_id") or "")
    pod = provider.get_pod(pod_id)
    if pod is None:
        raise PhaseQualificationRefused("v7 predecessor Pod is absent; new Pod creation is forbidden")
    if str(pod.get("desiredStatus", "")).upper() not in {"EXITED", "STOPPED"}:
        provider.stop_pod(pod_id)
        pod = provider.get_pod(pod_id)
    if pod is None or str(pod.get("desiredStatus", "")).upper() not in {"EXITED", "STOPPED"}:
        raise PhaseQualificationRefused("predecessor Pod could not be verified stopped")
    old_payload, old_pins = v7.provider_payload(role)
    old_provider_hash = _provider_script_hash(pod)
    if old_provider_hash != old_pins["startup_script_sha256"]:
        raise PhaseQualificationRefused("provider predecessor startup bytes do not match v7 instrument")
    script, startup_inputs = phase_startup_script(role)
    pins = controller_pins()
    _provider_update(provider, pod_id, script)
    updated = provider.get_pod(pod_id)
    if updated is None:
        raise PhaseQualificationRefused("updated same-Pod qualification disappeared")
    if _provider_script_hash(updated) != startup_inputs["startup_script_sha256"]:
        raise PhaseQualificationRefused("provider did not retain the v8 startup bytes")
    # Pod update is allowed only while stopped. If the provider starts it as a
    # side effect, release GPU before proceeding to the attested start phase.
    if str(updated.get("desiredStatus", "")).upper() not in {"EXITED", "STOPPED"}:
        provider.stop_pod(pod_id)
    rate = float(updated.get("costPerHr") or updated.get("adjustedCostPerHr") or 0.0)
    if rate <= 0 or rate > base.BASE_MAX_HOURLY_USD:
        raise PhaseQualificationRefused("same-Pod hourly rate exceeds frozen ceiling")
    state = {
        "schema": "tavonel.recovery.http_phase_qualification_state.v1",
        "attempt": ATTEMPT,
        "role": role,
        "phase": "prepared_stopped",
        "pod_id": pod_id,
        "hourly_rate_usd": rate,
        "remaining_gpu_seconds": float(predecessor["remaining_gpu_seconds"]),
        "gpu_seconds_consumed_local": float(predecessor.get("gpu_seconds_consumed_local", 0.0)),
        "evidence_url": base.evidence_url(pod_id),
        "startup_inputs": startup_inputs,
        "predecessor_startup_sha256": old_provider_hash,
        "controller_source_sha256": pins,
        "provider_stopped": True,
        "fresh_confirmatory_observation": False,
    }
    _write_state(role, state)
    _journal(role, "same_pod_startup_updated", pod_id=pod_id, remaining_gpu_seconds=state["remaining_gpu_seconds"])
    return {
        "role": role,
        "phase": state["phase"],
        "pod_reused": True,
        "remaining_gpu_seconds": state["remaining_gpu_seconds"],
        "startup_script_sha256": startup_inputs["startup_script_sha256"],
    }


def _verify_pins(state: Mapping[str, Any]) -> None:
    if state.get("controller_source_sha256") != controller_pins():
        raise PhaseQualificationRefused("v8 controller source drifted")


def start(role: str) -> dict[str, Any]:
    state = _read_state(role)
    _verify_pins(state)
    if state.get("phase") != "prepared_stopped":
        raise PhaseQualificationRefused(f"v8 start requires prepared_stopped, got {state.get('phase')}")
    remaining = float(state.get("remaining_gpu_seconds", 0.0))
    if remaining <= 0:
        raise PhaseQualificationRefused("v8 GPU budget is exhausted")
    provider = base.Provider(base.read_runpod_b())
    pod_id = str(state["pod_id"])
    pod = provider.get_pod(pod_id)
    if pod is None or str(pod.get("desiredStatus", "")).upper() not in {"EXITED", "STOPPED"}:
        raise PhaseQualificationRefused("v8 same Pod is not safely stopped before start")
    now = datetime.now(UTC)
    state.update(
        {
            "phase": "provider_running",
            "running_started_at_utc": now.isoformat(),
            "hard_deadline_utc": (now + timedelta(seconds=remaining)).isoformat(),
            "provider_stopped": False,
        }
    )
    _write_state(role, state)
    watchdog_pid = _spawn_watchdog(role)
    state["watchdog_pid"] = watchdog_pid
    _write_state(role, state)
    try:
        provider.start_pod(pod_id)
    except Exception:
        state["phase"] = "start_failed"
        _write_state(role, state)
        raise
    _journal(role, "same_pod_started", pod_id=pod_id, watchdog_pid=watchdog_pid, remaining_gpu_seconds=remaining)
    return {
        "role": role,
        "phase": "provider_running",
        "pod_reused": True,
        "remaining_gpu_seconds": remaining,
        "watchdog_pid": watchdog_pid,
    }


def _consume_budget(state: dict[str, Any]) -> None:
    started = state.get("running_started_at_utc")
    if not started:
        return
    try:
        start_time = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PhaseQualificationRefused("v8 running timestamp is invalid") from exc
    elapsed = max(0.0, (datetime.now(UTC) - start_time).total_seconds())
    state["remaining_gpu_seconds"] = max(0.0, float(state["remaining_gpu_seconds"]) - elapsed)
    state["gpu_seconds_consumed_local"] = float(state.get("gpu_seconds_consumed_local", 0.0)) + elapsed
    state["running_started_at_utc"] = None


def _stop(role: str, state: dict[str, Any], *, phase: str, event: str) -> dict[str, Any]:
    provider = base.Provider(base.read_runpod_b())
    _consume_budget(state)
    pod_id = str(state["pod_id"])
    pod = provider.get_pod(pod_id)
    if pod is not None and str(pod.get("desiredStatus", "")).upper() not in {"EXITED", "STOPPED"}:
        provider.stop_pod(pod_id)
    billing = base._billing_snapshot(provider, state)
    state.update(
        {
            "phase": phase,
            "provider_stopped": True,
            "last_pod_billing": billing,
            "stopped_at_utc": datetime.now(UTC).isoformat(),
        }
    )
    _write_state(role, state)
    _journal(role, event, pod_id=pod_id, remaining_gpu_seconds=state["remaining_gpu_seconds"], billing_status=billing.get("status"))
    return billing


def _seal_failure(role: str, state: Mapping[str, Any], error: RemotePhaseFailure) -> None:
    INCIDENT_ROOT.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": "tavonel.recovery.runtime_qualification_phase_failure.v1",
        "attempt": ATTEMPT,
        "role": role,
        "state": "RUNTIME_QUALIFICATION_FAIL",
        "phase": error.phase,
        "exit_code": error.exit_code,
        "provider_stopped": True,
        "remaining_gpu_seconds": state.get("remaining_gpu_seconds"),
        "fresh_confirmatory_observation": False,
        "scientific_claim_eligible": False,
    }
    report = {**body, "failure_digest": "sha256:" + hashlib.sha256(_canonical(body).encode()).hexdigest()}
    path = INCIDENT_ROOT / "strong-v8-phase-failure.json"
    if path.exists():
        raise PhaseQualificationRefused("v8 phase-failure receipt already exists")
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")


def _seal_attestation(role: str, state: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    spec = base.discover_role_spec(role)
    input_manifest = base.legacy_http.qualification_input_binding()
    source_paths = (spec.bootstrap_relpath, spec.prompt_relpath, *spec.extra_pin_paths)
    pins = base.pin_files(base.REPO, tuple(("runtime_input", path) for path in source_paths))
    billing = state.get("last_pod_billing")
    if not isinstance(billing, dict):
        raise PhaseQualificationRefused("v8 stopped without Pod billing evidence")
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
        "qualification_controller_sha256": controller_pins()["phase_controller_entrypoint_sha256"],
        "started_at_utc": state.get("started_at_utc") or state.get("running_started_at_utc") or datetime.now(UTC).isoformat(),
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "gpu_seconds_consumed_local": float(state["gpu_seconds_consumed_local"]),
        "remaining_gpu_seconds": float(state["remaining_gpu_seconds"]),
        "pod_billing": billing,
        "fresh_confirmatory_observation": False,
    }
    attestation = base.RuntimeAttestation(
        role=role,
        model_id=spec.model_id,
        model_revision=spec.model_revision,
        base_image=spec.base_image,
        base_image_digest=spec.base_image_digest,
        model_artifact_digest=spec.model_artifact_digest,
        prompt_schema_digest=base.sha256_file(base.REPO / spec.prompt_relpath),
        file_pins=pins,
        qualification_input_manifest_digest=base.canonical_digest(input_manifest),
        observed_runtime=observed_runtime,
    )
    attestation.validate(base.REPO)
    payload = attestation.as_dict()
    payload["attestation_digest"] = attestation.digest()
    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
    receipt = RECEIPT_ROOT / f"{role}.json"
    if receipt.exists():
        raise PhaseQualificationRefused("runtime qualification receipt already exists")
    with receipt.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    state.update({"phase": "complete", "attestation_digest": attestation.digest(), "provider_stopped": True})
    _write_state(role, state)
    _journal(role, "qualification_complete", pod_id=state["pod_id"], attestation_digest=attestation.digest())
    return {"role": role, "phase": "complete", "attestation_digest": attestation.digest(), "provider_stopped": True}


def advance(role: str) -> dict[str, Any]:
    state = _read_state(role)
    _verify_pins(state)
    if state.get("phase") == "complete":
        return {"role": role, "phase": "complete", "attestation_digest": state.get("attestation_digest")}
    if state.get("phase") != "provider_running":
        raise PhaseQualificationRefused(f"v8 qualification is not running: {state.get('phase')}")
    deadline = datetime.fromisoformat(str(state["hard_deadline_utc"]).replace("Z", "+00:00"))
    if datetime.now(UTC) >= deadline:
        _stop(role, state, phase="hard_deadline_stopped", event="hard_deadline_stopped_cache_preserved")
        raise PhaseQualificationRefused("v8 hard deadline reached; GPU stopped")
    remote = _fetch(str(state["evidence_url"]))
    provider = base.Provider(base.read_runpod_b())
    if remote is None:
        pod = provider.get_pod(str(state["pod_id"]))
        if pod is None:
            raise PhaseQualificationRefused("v8 same Pod disappeared without evidence")
        if str(pod.get("desiredStatus", "")).upper() in {"EXITED", "STOPPED"}:
            _stop(role, state, phase="provider_stopped_without_evidence", event="provider_stopped_without_evidence")
            raise PhaseQualificationRefused("v8 provider stopped before evidence")
        return {"role": role, "phase": "provider_running", "remote_evidence": False}
    try:
        evidence = validate_remote(role, remote)
    except RemotePhaseFailure as error:
        _stop(role, state, phase="remote_fail_stopped", event="remote_phase_fail_stopped_cache_preserved")
        _seal_failure(role, state, error)
        raise
    except Exception:
        _stop(role, state, phase="remote_evidence_refused_stopped", event="remote_evidence_refused_stopped_cache_preserved")
        raise
    _stop(role, state, phase="qualification_evidence_stopped", event="qualification_evidence_stopped_before_seal")
    return _seal_attestation(role, state, evidence)


def watchdog(role: str) -> int:
    while True:
        try:
            state = _read_state(role)
        except Exception:
            return 0
        if str(state.get("phase")) in _TERMINAL_PHASES or state.get("phase") == "prepared_stopped":
            return 0
        try:
            _verify_pins(state)
        except Exception:
            try:
                if state.get("phase") == "provider_running":
                    _stop(role, state, phase="controller_drift_stopped", event="controller_drift_stopped_cache_preserved")
            finally:
                return 2
        deadline_raw = state.get("hard_deadline_utc")
        if state.get("phase") == "provider_running" and deadline_raw:
            deadline = datetime.fromisoformat(str(deadline_raw).replace("Z", "+00:00"))
            if datetime.now(UTC) >= deadline:
                try:
                    _stop(role, state, phase="hard_deadline_stopped", event="watchdog_hard_deadline_stopped")
                    return 0
                except Exception:
                    return 3
        time.sleep(30)


def plan(role: str) -> dict[str, Any]:
    predecessor = _v7_predecessor(role)
    script, pins = phase_startup_script(role)
    return {
        "schema": "tavonel.recovery.http_phase_qualification_plan.v1",
        "attempt": ATTEMPT,
        "role": role,
        "same_pod_update_required": True,
        "new_pod_creation_forbidden": True,
        "pod_volume_cache_preserved": True,
        "remaining_gpu_seconds": float(predecessor["remaining_gpu_seconds"]),
        "startup_script_sha256": pins["startup_script_sha256"],
        "controller_source_sha256": controller_pins(),
        "failure_evidence": {"phase": True, "exit_code": True, "model_output": False},
        "fresh_confirmatory_observation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "prepare", "start", "advance", "watchdog"):
        command = sub.add_parser(name)
        command.add_argument("--role", choices=("strong",), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            value = plan(args.role)
        elif args.command == "prepare":
            value = prepare(args.role)
        elif args.command == "start":
            value = start(args.role)
        elif args.command == "advance":
            value = advance(args.role)
        else:
            return watchdog(args.role)
    except base.QualificationRefused as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
