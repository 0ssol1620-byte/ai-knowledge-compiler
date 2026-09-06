#!/usr/bin/env python3
"""Integrity-checked v7 SSH-free RunPod qualification for TAVONEL-R.

This successor exists because the v6 Strong development attempt produced a
syntactically PASS-shaped evidence document with an empty runtime digest after
an earlier bootstrap failure was masked by the outer ``set +e`` envelope.

V7 preserves the frozen role/model/input contract but strengthens only the
qualification instrument.  It fail-closes the success subshell, requires the
runtime identity receipt to exist, requires every emitted digest to be exactly
64 lowercase hexadecimal characters, uses an explicit HTTP client identity for
the RunPod proxy, and binds this controller entrypoint together with every
module whose bytes can change paid-capacity lifecycle or evidence validation.

The fresh confirmatory cohort remains unopened and is never readable here.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

import runpod_http_frozen_qualification as v6
import runpod_http_qualification as legacy_http
import runpod_http_safe_controller_snapshot_v5 as base


HERE = Path(__file__).resolve().parent
ATTEMPT = "v7-integrity-checked-evidence"
PRIVATE_ROOT = HERE / ".private" / "runpod-http-safe-qualification" / ATTEMPT
V6_PRIVATE_ROOT = HERE / ".private" / "runpod-http-safe-qualification" / "v6-frozen-controller"
INCIDENT_ROOT = HERE / "receipts" / "runtime-qualification-incidents"
# Test-only/backward-compatible explicit incident override. Production leaves
# this unset and discovers the unique semantic v6 incident by content.
V6_INCIDENT: Path | None = None
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_ORIGINAL_PROVIDER_PAYLOAD = base.provider_payload
_ORIGINAL_FETCH = legacy_http._fetch_evidence
_ORIGINAL_VALIDATE = legacy_http._validate_remote_evidence
_ORIGINAL_V6_CONTROLLER_PINS = v6.controller_pins
_ORIGINAL_V6_WATCHDOG_COMMAND = v6._watchdog_command


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise base.SafeQualificationRefused(
            f"v7 startup hardening anchor {label} resolved {count} times"
        )
    return text.replace(old, new, 1)


def _harden_startup_script(script: str) -> str:
    """Turn the legacy best-effort success block into an all-or-nothing receipt."""

    text = _replace_once(
        script,
        "set +e\n(\n",
        "set +e\n(\nset -euo pipefail\n",
        label="success subshell fail-fast",
    )
    text = _replace_once(
        text,
        "runtime_sha=$(sha256sum $ROOT/receipts/runtime-identity.json | cut -d' ' -f1)",
        "test -s $ROOT/receipts/runtime-identity.json\n"
        "runtime_sha=$(sha256sum $ROOT/receipts/runtime-identity.json | cut -d' ' -f1)\n"
        "printf '%s\\n' \"$runtime_sha\" | grep -Eq '^[0-9a-f]{64}$'",
        label="runtime digest",
    )
    text = _replace_once(
        text,
        "model_sha=$(sha256sum $ROOT/receipts/",
        "model_sha=$(sha256sum $ROOT/receipts/",
        label="model digest assignment",
    )
    # Model receipt names differ by role. Add the integrity assertion after the
    # complete assignment without assuming which one was selected.
    model_lines = [
        line
        for line in text.splitlines()
        if line.startswith("model_sha=$(sha256sum $ROOT/receipts/")
    ]
    if len(model_lines) != 1:
        raise base.SafeQualificationRefused(
            f"v7 model digest assignment resolved {len(model_lines)} times"
        )
    text = _replace_once(
        text,
        model_lines[0],
        model_lines[0]
        + "\nprintf '%s\\n' \"$model_sha\" | grep -Eq '^[0-9a-f]{64}$'",
        label="model digest integrity",
    )
    smoke_lines = [line for line in text.splitlines() if line.startswith("smoke_sha=$(find ")]
    if len(smoke_lines) != 1:
        raise base.SafeQualificationRefused(
            f"v7 smoke digest assignment resolved {len(smoke_lines)} times"
        )
    # smoke_sha is a two-line command in both role scripts; harden immediately
    # after its terminating ``cut`` line instead of inserting in the middle.
    smoke_end = "xargs -0 cat | sha256sum | cut -d' ' -f1)"
    text = _replace_once(
        text,
        smoke_end,
        smoke_end + "\nprintf '%s\\n' \"$smoke_sha\" | grep -Eq '^[0-9a-f]{64}$'",
        label="smoke digest integrity",
    )
    return text


def provider_payload(role: str) -> tuple[dict[str, Any], dict[str, str]]:
    payload, inputs = _ORIGINAL_PROVIDER_PAYLOAD(role)
    script = _harden_startup_script(str(payload["dockerStartCmd"][0]))
    payload = dict(payload)
    payload["name"] = f"tavonel-r-http-qual-{role}-{ATTEMPT}"
    payload["dockerStartCmd"] = [script]
    inputs = dict(inputs)
    inputs["startup_script_sha256"] = "sha256:" + hashlib.sha256(script.encode()).hexdigest()
    return payload, inputs


def _fetch_evidence(url: str) -> dict[str, Any] | None:
    if not url.startswith("https://") or not url.endswith("/evidence.json"):
        raise base.SafeQualificationRefused("qualification evidence URL is invalid")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "tavonel-runtime-qualification/1",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            if response.status != 200:
                return None
            raw = response.read(128 * 1024)
    except urllib.error.HTTPError as error:
        if error.code in {403, 404, 502, 503, 504}:
            return None
        raise base.SafeQualificationRefused(
            f"qualification evidence HTTP failure: {error.code}"
        ) from None
    except OSError:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise base.SafeQualificationRefused("qualification evidence is not JSON") from error
    if not isinstance(value, dict):
        raise base.SafeQualificationRefused("qualification evidence shape is invalid")
    return value


def _validate_remote_evidence(role: str, value: dict[str, Any]) -> dict[str, Any]:
    for key in ("runtime_sha256", "model_manifest_sha256", "smoke_output_sha256"):
        if SHA256_RE.fullmatch(str(value.get(key) or "")) is None:
            raise base.SafeQualificationRefused(
                f"qualification evidence {key} is not a complete sha256 digest"
            )
    return _ORIGINAL_VALIDATE(role, value)


def controller_pins() -> dict[str, str]:
    return {
        "frozen_controller_entrypoint_sha256": _sha(Path(__file__).resolve()),
        "safe_controller_snapshot_sha256": _sha(Path(base.__file__).resolve()),
        "legacy_http_validator_sha256": _sha(Path(legacy_http.__file__).resolve()),
        "runpod_provider_module_sha256": _sha(HERE / "runpod_qualification.py"),
        "runtime_attestation_module_sha256": _sha(HERE / "runtime_attestation.py"),
    }


def _watchdog_command(role: str) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "watchdog", "--role", role]


def _entrypoint_relpath() -> str:
    return str(Path(__file__).resolve().relative_to(base.REPO)).replace("\\", "/")


def _successor_budget_seconds(role: str) -> float:
    """Carry paid Strong qualification spend forward across the v6->v7 repair.

    Instrument repair is not permission to reset the frozen GPU allowance.  The
    Primary role has no v6 paid predecessor; Strong must inherit the remaining
    seconds recorded when the malformed v6 evidence was stopped.
    """

    if role != "strong":
        return float(base.MAX_RUNTIME_SECONDS)
    state_path = V6_PRIVATE_ROOT / role / "state.json"
    if not state_path.is_file() or not INCIDENT_ROOT.is_dir():
        raise base.SafeQualificationRefused(
            "v7 Strong successor requires the sealed v6 invalid-instrument state and incident"
        )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    incidents: list[dict[str, Any]] = []
    incident_paths = (
        [V6_INCIDENT]
        if V6_INCIDENT is not None
        else sorted(INCIDENT_ROOT.glob("*.json"))
    )
    for path in incident_paths:
        if path is None or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        explicit_override_match = (
            V6_INCIDENT is not None
            and value.get("role") == role
            and value.get("state") == "INVALID_INSTRUMENT"
            and value.get("successor") in {None, "", ATTEMPT}
        )
        production_match = (
            V6_INCIDENT is None
            and value.get("attempt") == "v6-frozen-controller"
            and value.get("role") == role
            and value.get("state") == "INVALID_INSTRUMENT"
            and value.get("defect") == "PASS_SHAPED_EVIDENCE_WITH_INCOMPLETE_RUNTIME_DIGEST"
            and value.get("scientific_claim_eligible") is False
        )
        if explicit_override_match or production_match:
            incidents.append(value)
    if len(incidents) != 1:
        raise base.SafeQualificationRefused(
            f"v7 Strong successor requires exactly one matching v6 incident, found {len(incidents)}"
        )
    incident = incidents[0]
    successor = incident.get("successor")
    if successor not in {None, "", ATTEMPT}:
        raise base.SafeQualificationRefused("v6 successor incident names a different successor")
    if state.get("phase") != "invalid_runtime_hash_stopped" or not state.get("provider_stopped"):
        raise base.SafeQualificationRefused("v6 Strong predecessor was not safely stopped")
    remaining = float(state.get("remaining_gpu_seconds", 0.0))
    incident_remaining = float(incident.get("remaining_gpu_seconds", -1.0))
    if remaining <= 0.0 or abs(remaining - incident_remaining) > 1e-6:
        raise base.SafeQualificationRefused("v6 successor remaining-GPU budget does not reconcile")
    if remaining > float(base.MAX_RUNTIME_SECONDS):
        raise base.SafeQualificationRefused("v6 successor budget exceeds the frozen role maximum")
    return remaining


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
        legacy_http._fetch_evidence = _fetch_evidence
        legacy_http._validate_remote_evidence = _validate_remote_evidence
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
    with _activated():
        value = v6.plan(role)
    value = dict(value)
    value["schema"] = "tavonel.recovery.http_integrity_qualification_plan.v1"
    value["attempt"] = ATTEMPT
    value["complete_digest_validation"] = True
    value["success_subshell_fail_fast"] = True
    value["watchdog_entrypoint_path"] = _entrypoint_relpath()
    value["successor_gpu_seconds"] = _successor_budget_seconds(role)
    value["gpu_budget_reset_by_instrument_repair"] = False
    return value


def start(role: str) -> dict[str, Any]:
    budget_seconds = _successor_budget_seconds(role)
    with _activated():
        old_budget = base.MAX_RUNTIME_SECONDS
        try:
            base.MAX_RUNTIME_SECONDS = budget_seconds
            result = v6.start(role)
        finally:
            base.MAX_RUNTIME_SECONDS = old_budget
        state = base._read_state(role)
        state["watchdog_entrypoint_path"] = _entrypoint_relpath()
        state["successor_gpu_budget_seconds"] = budget_seconds
        state["gpu_budget_reset_by_instrument_repair"] = False
        base._write_state(role, state)
        return {
            **result,
            "watchdog_entrypoint_path": state["watchdog_entrypoint_path"],
            "successor_gpu_budget_seconds": budget_seconds,
        }


def advance(role: str) -> dict[str, Any]:
    with _activated():
        return v6.advance(role)


def resume(role: str) -> dict[str, Any]:
    with _activated():
        result = v6.resume(role)
        state = base._read_state(role)
        state["watchdog_entrypoint_path"] = _entrypoint_relpath()
        base._write_state(role, state)
        return {**result, "watchdog_entrypoint_path": state["watchdog_entrypoint_path"]}


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