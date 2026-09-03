#!/usr/bin/env python3
"""Hash-bound v4 entrypoint for the SSH-free TAVONEL-R RunPod qualification.

The v3 safe controller established the stop/resume/billing contract.  This
successor changes no scientific model role or smoke input; it closes one
bookkeeping defect discovered during a development qualification attempt: the
startup hash must describe the *post-hardening bytes actually sent to RunPod*,
not the legacy pre-transform script.

A separate attempt namespace/pod name prevents an invalid v3 attempt from being
silently resumed or reinterpreted.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import runpod_http_safe_qualification as base

ATTEMPT = "v4-hashbound-persisted-safe"
PRIVATE_ROOT = base.HERE / ".private" / "runpod-http-safe-qualification" / ATTEMPT

# Capture the v3 hardening transformation, then isolate all controller state for
# this process before delegating any provider operation.
_V3_SAFE_STARTUP = base.safe_startup_script
base.ATTEMPT = ATTEMPT
base.PRIVATE_ROOT = PRIVATE_ROOT


def safe_startup_script(role: str) -> tuple[str, dict[str, str]]:
    script, pins = _V3_SAFE_STARTUP(role)
    bound = dict(pins)
    bound["startup_script_sha256"] = "sha256:" + hashlib.sha256(script.encode("utf-8")).hexdigest()
    return script, bound


# provider_payload resolves `safe_startup_script` through the base module global
# at call time, so install the hash-bound function for this process only.
base.safe_startup_script = safe_startup_script

# Public aliases make this entrypoint independently testable without duplicating
# the already-reviewed stop/resume/watchdog implementation.
SafeQualificationRefused = base.SafeQualificationRefused
provider_payload = base.provider_payload
plan = base.plan
start = base.start
advance = base.advance
resume = base.resume
cleanup = base.cleanup
watchdog = base.watchdog
state_path = base.state_path
_read_state = base._read_state
_stop_preserving_cache = base._stop_preserving_cache


def main(argv: list[str] | None = None) -> int:
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
