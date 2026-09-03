#!/usr/bin/env python3
"""Frozen-controller v6 SSH-free RunPod qualification for TAVONEL-R.

This is the first successor that binds all operational code used by a paid
qualification attempt before the Pod is created:

* final post-hardening startup-script bytes;
* an immutable snapshot of the stop/resume/billing controller;
* the HTTP evidence validator;
* the RunPod provider/lifecycle module;
* runtime-attestation validation code;
* this watchdog/controller entrypoint itself.

The watchdog is started only after those source pins are written to state, so it
cannot race against an unbound attempt. Any later source drift fail-closes by
stopping paid GPU and preserving /workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import runpod_http_safe_controller_snapshot_v5 as base
import runpod_qualification as runpod_module
import runtime_attestation as attestation_module

ATTEMPT = "v6-frozen-controller"
PRIVATE_ROOT = base.HERE / ".private" / "runpod-http-safe-qualification" / ATTEMPT

_BASE_SAFE_STARTUP = base.safe_startup_script
_BASE_START = base.start
_BASE_ADVANCE = base.advance
_BASE_RESUME = base.resume
_BASE_CLEANUP = base.cleanup
_BASE_WATCHDOG = base.watchdog
_BASE_PLAN = base.plan

base.ATTEMPT = ATTEMPT
base.PRIVATE_ROOT = PRIVATE_ROOT


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def controller_pins() -> dict[str, str]:
    return {
        "frozen_controller_entrypoint_sha256": _sha(Path(__file__).resolve()),
        "safe_controller_snapshot_sha256": _sha(Path(base.__file__).resolve()),
        "legacy_http_validator_sha256": _sha(Path(base.legacy_http.__file__).resolve()),
        "runpod_provider_module_sha256": _sha(Path(runpod_module.__file__).resolve()),
        "runtime_attestation_module_sha256": _sha(Path(attestation_module.__file__).resolve()),
    }


def safe_startup_script(role: str) -> tuple[str, dict[str, str]]:
    script, pins = _BASE_SAFE_STARTUP(role)
    bound = dict(pins)
    bound["startup_script_sha256"] = "sha256:" + hashlib.sha256(script.encode("utf-8")).hexdigest()
    return script, bound


base.safe_startup_script = safe_startup_script


def _watchdog_command(role: str) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "watchdog", "--role", role]


def _spawn_attested_watchdog(role: str) -> int:
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    process = subprocess.Popen(  # noqa: S603 - fixed local executable and file path
        _watchdog_command(role),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )
    return int(process.pid)


def _deferred_watchdog(_role: str) -> int:
    # base.start historically spawns immediately after writing its first state.
    # v6 defers the child until controller pins are atomically added below.
    return 0


base._spawn_watchdog = _deferred_watchdog


def _read_state(role: str) -> dict[str, Any]:
    return base._read_state(role)


def _write_state(role: str, value: dict[str, Any]) -> None:
    base._write_state(role, value)


def _verify_controller_pins(role: str) -> dict[str, Any]:
    state = _read_state(role)
    expected = state.get("controller_source_sha256")
    current = controller_pins()
    if not isinstance(expected, dict) or expected != current:
        raise base.SafeQualificationRefused("qualification controller source drifted after paid attempt start")
    if state.get("watchdog_entrypoint_sha256") != current["frozen_controller_entrypoint_sha256"]:
        raise base.SafeQualificationRefused("watchdog entrypoint pin differs from frozen controller")
    return state


def _stop_for_controller_drift(role: str, state: dict[str, Any]) -> None:
    provider = base.Provider(base.read_runpod_b())
    base._stop_preserving_cache(
        role,
        state,
        provider,
        phase="controller_source_drift_stopped",
        event="controller_source_drift_stopped_cache_preserved",
    )


def _attach_watchdog(role: str, state: dict[str, Any]) -> int:
    pid = _spawn_attested_watchdog(role)
    state["watchdog_pid"] = pid
    state["watchdog_entrypoint_sha256"] = controller_pins()["frozen_controller_entrypoint_sha256"]
    _write_state(role, state)
    base._journal(role, "attested_watchdog_started", pod_id=state.get("pod_id"), watchdog_pid=pid)
    return pid


def start(role: str) -> dict[str, Any]:
    pins_before = controller_pins()
    result = _BASE_START(role)
    state = _read_state(role)
    pins_after = controller_pins()
    if pins_before != pins_after:
        _stop_for_controller_drift(role, state)
        raise base.SafeQualificationRefused("controller source changed while qualification Pod was created")
    state["controller_source_sha256"] = pins_before
    state["watchdog_entrypoint_sha256"] = pins_before["frozen_controller_entrypoint_sha256"]
    state["watchdog_entrypoint_path"] = str(Path(__file__).resolve().relative_to(base.REPO)).replace("\\", "/")
    _write_state(role, state)
    watchdog_pid = _attach_watchdog(role, state)
    return {
        **result,
        "controller_source_sha256": pins_before,
        "watchdog_entrypoint_bound": True,
        "watchdog_pid": watchdog_pid,
    }


def advance(role: str) -> dict[str, Any]:
    try:
        _verify_controller_pins(role)
    except base.SafeQualificationRefused:
        state = _read_state(role)
        if str(state.get("phase")) == "provider_running":
            _stop_for_controller_drift(role, state)
        raise
    return _BASE_ADVANCE(role)


def resume(role: str) -> dict[str, Any]:
    try:
        _verify_controller_pins(role)
    except base.SafeQualificationRefused:
        state = _read_state(role)
        if str(state.get("phase")) == "provider_running":
            _stop_for_controller_drift(role, state)
        raise
    result = _BASE_RESUME(role)
    state = _read_state(role)
    watchdog_pid = _attach_watchdog(role, state)
    return {**result, "watchdog_pid": watchdog_pid, "watchdog_entrypoint_bound": True}


def cleanup(role: str) -> dict[str, Any]:
    return _BASE_CLEANUP(role)


def watchdog(role: str) -> int:
    try:
        _verify_controller_pins(role)
    except base.SafeQualificationRefused:
        try:
            state = _read_state(role)
            if str(state.get("phase")) == "provider_running":
                _stop_for_controller_drift(role, state)
        except Exception:
            return 3
        return 2
    return _BASE_WATCHDOG(role)


def plan(role: str) -> dict[str, Any]:
    value = dict(_BASE_PLAN(role))
    value["controller_source_sha256"] = controller_pins()
    value["watchdog_entrypoint_path"] = str(Path(__file__).resolve().relative_to(base.REPO)).replace("\\", "/")
    value["watchdog_entrypoint_bound"] = True
    value["watchdog_spawn_deferred_until_controller_pins_written"] = True
    return value


def state_path(role: str) -> Path:
    return base.state_path(role)


def _stop_preserving_cache(
    role: str,
    state: dict[str, Any],
    provider: Any,
    *,
    phase: str,
    event: str,
) -> dict[str, Any]:
    return base._stop_preserving_cache(role, state, provider, phase=phase, event=event)


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
    except base.QualificationRefused as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
