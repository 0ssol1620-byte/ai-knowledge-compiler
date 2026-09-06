#!/usr/bin/env python3
"""V9 replacement-Pod phase qualification for TAVONEL-R Strong runtime.

V8 updated the stopped V7 Pod in place, but RunPod refused to restart that Pod
with HTTP 500 while the Pod remained EXITED.  RunPod documents that stopped Pods
stay tied to their original machine and can become unstartable when that GPU is
no longer available.  V9 therefore permits exactly one operational change: a
new Pod may be scheduled on any GPU type already allowed by the frozen role
contract (4090/5090).

Everything scientific is inherited unchanged:

* same spent one-page qualification input;
* same Strong model/revision/base image;
* same V7 fail-fast digest checks;
* same V8 coarse phase/exit-code instrumentation;
* same total Strong qualification budget, carrying forward V8's remaining
  seconds rather than resetting after the infrastructure repair.

Fresh confirmatory data remains inaccessible.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

import runpod_http_frozen_qualification as v6
import runpod_http_integrity_qualification as v7
import runpod_http_phase_qualification as v8


base = v7.base
legacy_http = v7.legacy_http
HERE = Path(__file__).resolve().parent
ATTEMPT = "v9-phase-new-pod-after-host-gpu-unavailable"
PRIVATE_ROOT = HERE / ".private" / "runpod-http-safe-qualification" / ATTEMPT
V8_INCIDENT_ROOT = HERE / "receipts" / "runtime-qualification-incidents"


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def controller_pins() -> dict[str, str]:
    return {
        "replacement_controller_entrypoint_sha256": _sha(Path(__file__).resolve()),
        "v8_phase_controller_sha256": _sha(Path(v8.__file__).resolve()),
        "v7_integrity_controller_sha256": _sha(Path(v7.__file__).resolve()),
        "v6_frozen_controller_sha256": _sha(Path(v6.__file__).resolve()),
        "safe_controller_snapshot_sha256": _sha(Path(base.__file__).resolve()),
        "http_validator_sha256": _sha(Path(legacy_http.__file__).resolve()),
        "runpod_provider_module_sha256": _sha(HERE / "runpod_qualification.py"),
        "runtime_attestation_module_sha256": _sha(HERE / "runtime_attestation.py"),
    }


def _watchdog_command(role: str) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "watchdog", "--role", role]


def _entrypoint_relpath() -> str:
    return str(Path(__file__).resolve().relative_to(base.REPO)).replace("\\", "/")


def _matching_v8_incident(role: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    if not V8_INCIDENT_ROOT.is_dir():
        raise base.SafeQualificationRefused("v9 requires the sealed v8 operational incident")
    for path in sorted(V8_INCIDENT_ROOT.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        if (
            value.get("schema") == "tavonel.recovery.runtime_qualification_operational_incident.v1"
            and value.get("attempt") == v8.ATTEMPT
            and value.get("role") == role
            and value.get("state") == "START_FAILED_PROVIDER_CAPACITY"
            and value.get("provider_http_status") == 500
            and value.get("provider_stopped") is True
            and value.get("gpu_budget_debited_for_failed_start") is False
            and value.get("new_pod_created") is False
            and value.get("scientific_claim_eligible") is False
            and value.get("successor") == ATTEMPT
        ):
            matches.append(value)
    if len(matches) != 1:
        raise base.SafeQualificationRefused(
            f"v9 requires exactly one matching v8 host-capacity incident, found {len(matches)}"
        )
    return matches[0]


def predecessor_budget_seconds(role: str) -> float:
    if role != "strong":
        raise base.SafeQualificationRefused("v9 replacement qualification currently accepts Strong only")
    state = v8._read_state(role)
    incident = _matching_v8_incident(role)
    # The shared private v8 state is not scientific authority because multiple
    # active sessions may rewrite operational flags.  The tracked incident was
    # created only after an independent provider read verified desiredStatus
    # EXITED.  Here private state is used only to bind the exact failed phase and
    # remaining budget back to that immutable incident.
    if state.get("phase") != "start_failed":
        raise base.SafeQualificationRefused("v8 predecessor is not the recorded start failure")
    remaining = float(state.get("remaining_gpu_seconds", 0.0))
    recorded = float(incident.get("remaining_gpu_seconds", -1.0))
    if remaining <= 0.0 or abs(remaining - recorded) > 1e-6:
        raise base.SafeQualificationRefused("v8/v9 remaining GPU budget does not reconcile")
    if remaining > float(base.MAX_RUNTIME_SECONDS):
        raise base.SafeQualificationRefused("v9 successor budget exceeds the frozen role maximum")
    return remaining


def provider_payload(role: str) -> tuple[dict[str, Any], dict[str, str]]:
    if role != "strong":
        raise base.SafeQualificationRefused("v9 provider payload accepts Strong only")
    # Preserve all frozen provider/model/base-image terms from the original
    # qualification request; replace only attempt identity and startup bytes.
    payload, _ = v7._ORIGINAL_PROVIDER_PAYLOAD(role)
    script, startup_inputs = v8.phase_startup_script(role)
    payload = dict(payload)
    payload["name"] = f"tavonel-r-http-qual-{role}-{ATTEMPT}"
    payload["dockerStartCmd"] = [script]
    return payload, startup_inputs


@contextlib.contextmanager
def _activated() -> Iterator[None]:
    old_attempt = base.ATTEMPT
    old_private = base.PRIVATE_ROOT
    old_payload = base.provider_payload
    old_fetch = legacy_http._fetch_evidence
    old_validate = legacy_http._validate_remote_evidence
    old_pins = v6.controller_pins
    old_watchdog = v6._watchdog_command
    try:
        base.ATTEMPT = ATTEMPT
        base.PRIVATE_ROOT = PRIVATE_ROOT
        base.provider_payload = provider_payload
        legacy_http._fetch_evidence = v7._fetch_evidence
        legacy_http._validate_remote_evidence = v8.validate_remote
        v6.controller_pins = controller_pins
        v6._watchdog_command = _watchdog_command
        yield
    finally:
        base.ATTEMPT = old_attempt
        base.PRIVATE_ROOT = old_private
        base.provider_payload = old_payload
        legacy_http._fetch_evidence = old_fetch
        legacy_http._validate_remote_evidence = old_validate
        v6.controller_pins = old_pins
        v6._watchdog_command = old_watchdog


def plan(role: str) -> dict[str, Any]:
    budget = predecessor_budget_seconds(role)
    with _activated():
        value = dict(v6.plan(role))
    value["schema"] = "tavonel.recovery.http_replacement_phase_qualification_plan.v1"
    value["attempt"] = ATTEMPT
    value["predecessor_attempt"] = v8.ATTEMPT
    value["replacement_reason"] = "STOPPED_POD_HOST_GPU_UNAVAILABLE"
    value["new_pod_creation_allowed"] = True
    value["permitted_gpu_types_unchanged"] = True
    value["startup_has_phase_and_exit_code_evidence"] = True
    value["gpu_budget_reset_by_replacement"] = False
    value["successor_gpu_seconds"] = budget
    value["watchdog_entrypoint_path"] = _entrypoint_relpath()
    value["limits"] = dict(value.get("limits") or {})
    value["limits"]["gpu_seconds"] = budget
    value["controller_source_sha256"] = controller_pins()
    return value


def start(role: str) -> dict[str, Any]:
    budget = predecessor_budget_seconds(role)
    with _activated():
        old_budget = base.MAX_RUNTIME_SECONDS
        try:
            base.MAX_RUNTIME_SECONDS = budget
            result = v6.start(role)
        finally:
            base.MAX_RUNTIME_SECONDS = old_budget
        state = base._read_state(role)
        state["predecessor_attempt"] = v8.ATTEMPT
        state["replacement_reason"] = "STOPPED_POD_HOST_GPU_UNAVAILABLE"
        state["successor_gpu_budget_seconds"] = budget
        state["gpu_budget_reset_by_replacement"] = False
        state["watchdog_entrypoint_path"] = _entrypoint_relpath()
        base._write_state(role, state)
        return {
            **result,
            "predecessor_attempt": v8.ATTEMPT,
            "replacement_reason": state["replacement_reason"],
            "successor_gpu_budget_seconds": budget,
            "watchdog_entrypoint_path": state["watchdog_entrypoint_path"],
        }


def _seal_phase_failure(role: str, error: v8.RemotePhaseFailure) -> None:
    with _activated():
        state = base._read_state(role)
    body = {
        "schema": "tavonel.recovery.runtime_qualification_phase_failure.v1",
        "attempt": ATTEMPT,
        "role": role,
        "state": "RUNTIME_QUALIFICATION_FAIL",
        "phase": error.phase,
        "exit_code": error.exit_code,
        "provider_stopped": bool(state.get("provider_stopped")),
        "remaining_gpu_seconds": state.get("remaining_gpu_seconds"),
        "fresh_confirmatory_observation": False,
        "scientific_claim_eligible": False,
    }
    digest = "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    report = {**body, "failure_digest": digest}
    path = HERE / "receipts" / "runtime-qualification-incidents" / "strong-v9-phase-failure.json"
    if path.exists():
        raise base.SafeQualificationRefused("v9 phase-failure receipt already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")


def advance(role: str) -> dict[str, Any]:
    try:
        with _activated():
            return v6.advance(role)
    except v8.RemotePhaseFailure as error:
        _seal_phase_failure(role, error)
        raise


def resume(role: str) -> dict[str, Any]:
    with _activated():
        return v6.resume(role)


def cleanup(role: str) -> dict[str, Any]:
    with _activated():
        return v6.cleanup(role)


def watchdog(role: str) -> int:
    with _activated():
        return v6.watchdog(role)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "start", "advance", "resume", "cleanup", "watchdog"):
        command = sub.add_parser(name)
        command.add_argument("--role", choices=("strong",), required=True)
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
    except base.QualificationRefused as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())