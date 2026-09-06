#!/usr/bin/env python3
"""Attested v5 entrypoint for SSH-free TAVONEL-R RunPod qualification.

This successor preserves the v3 stop/resume/billing controller and the v4
post-transform startup hash binding, while additionally binding the controller
source bytes and watchdog entrypoint to the attempt state.  Any controller drift
on advance/resume/watchdog stops paid GPU and preserves /workspace rather than
silently changing the qualification instrument.
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

import runpod_http_safe_qualification as base

ATTEMPT = "v5-attested-watchdog-safe"
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
        "attested_controller_sha256": _sha(Path(__file__).resolve()),
        "base_safe_controller_sha256": _sha(Path(base.__file__).resolve()),
    }


def safe_startup_script(role: str) -> tuple[str, dict[str, str]]:
    script, pins = _BASE_SAFE_STARTUP(role)
    bound = dict(pins)
    bound["startup_script_sha256"] = "sha256:" + hashlib.sha256(script.encode("utf-8")).hexdigest()
    return script, bound


base.safe_startup_script = safe_startup_script


def _watchdog_command(role: str) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "watchdog", "--role", role]


def _spawn_watchdog(role: str) -> int:
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


base._spawn_watchdog = _spawn_watchdog


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


def start(role: str) -> dict[str, Any]:
    pins_before = controller_pins()
    result = _BASE_START(role)
    state = _read_state(role)
    pins_after = controller_pins()
    if pins_before != pins_after:
        _stop_for_controller_drift(role, state)
        raise base.SafeQualificationRefused("controller source changed while qualification Pod was created")
    state["controller_source_sha256"] = pins_before
    state["watchdog_entrypoint_sha256"] = pins_before["attested_controller_sha256"]
    state["watchdog_entrypoint_path"] = str(Path(__file__).resolve().relative_to(base.REPO)).replace("\\", "/")
    _write_state(role, state)
    return {
        **result,
        "controller_source_sha256": pins_before,
        "watchdog_entrypoint_bound": True,
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
    return _BASE_RESUME(role)


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
