#!/usr/bin/env python3
"""Run hard-200 with v11's pipeline, minus the CUDA forward-compat libraries.

v11 is the first version of this campaign that ever reached its own driver.  On
2026-08-17 it took a healthy host at 274.65 s (Pod `9sgv0x8cakezxb`, run
`run-337b29eba37a`), started the v4 observability driver, launched vLLM -- and
vLLM died before serving:

    RuntimeError: Unexpected error from cudaGetDeviceCount().
    Error 804: forward compatibility was attempted on non supported HW
      ... torch._C._cuda_init()
    EngineCore failed to start

That is not a Stage-1 fault and not a host fault.  The vLLM base image ships
`/usr/local/cuda/compat`, NVIDIA's *forward compatibility* libcuda, and puts it
ahead of the driver's own libcuda on the loader path.  Forward compatibility is
supported on data-center GPUs only.  The v29 assembly pins an RTX 4090, which is
GeForce, so the compat libcuda refuses the hardware and CUDA never initialises.

The fix is to stop preloading it and let the container use the driver libcuda
that the host already provides:

    rm -f  /etc/ld.so.conf.d/*compat*.conf
    rm -rf /usr/local/cuda/compat
    ldconfig

This is a **runtime configuration change and it is recorded as one**, not hidden
inside a bootstrap string: `TAVONEL_RUNTIME_COMPAT_REMOVED=1` rides in the Pod
env, so RunPod's own record of the Pod carries it and any receipt derived from
that Pod shows the container did not run stock.

What it does NOT touch, because the hash contract depends on those bytes:

  * `assembly_qualification_http_v4.py` -- unread, unmodified.  READY still
    verifies `sha256(qualifier) == bootstrap_sha256` on the Pod.
  * `ovisocr2-v29-assembly-ready.json` -- not edited.  Manual READY edits are
    forbidden and none is needed: the entrypoint is ours, the qualifier is not.
  * the base image digest, the GPU, the ports, the disk, the bundle.

The removal is unconditional.  A conditional "remove only if CUDA fails" would
mean two different library configurations across the 200 documents depending on
which host each Pod landed on, and a receipt that cannot say which one produced
its outputs.  Every Pod runs the same configuration or the evidence is worthless.

Everything else is v11 and, through it, v10: the fast-fail startup budget, the
httpx transport, 5xx-tolerant create-by-reconciliation, one R2 upload outside the
host loop, the watchdog before the paid create, and v10's cleanup and receipt.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

V11_PATH = Path(__file__).with_name("run_stage1_v29_r2_v11_fast_fail_hosts.py")
_spec = importlib.util.spec_from_file_location("stage1_v11_for_v12", V11_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v11 module cannot be loaded")
v11 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v11
_spec.loader.exec_module(v11)

v10 = v11.v10

# Prefixed to v10's bootstrap command.  Every step is failure-tolerant: on a host
# where the compat directory is absent there is nothing to undo and the campaign
# proceeds identically.
COMPAT_REMOVAL_COMMAND = (
    "rm -f /etc/ld.so.conf.d/*compat*.conf 2>/dev/null || true; "
    "rm -rf /usr/local/cuda/compat 2>/dev/null || true; "
    "ldconfig 2>/dev/null || true; "
)

# The env key that makes the change visible in RunPod's own record of the Pod.
COMPAT_MARKER_ENV = "TAVONEL_RUNTIME_COMPAT_REMOVED"

# Bound at import: reading the attribute at call time would resolve to the
# wrapper and recurse forever.  Same rule as v11's _ORIGINAL_CREATE.
_ORIGINAL_BUILD_PAYLOAD = v10.build_payload


def build_payload_without_cuda_compat(**kwargs: Any) -> dict[str, Any]:
    """v10's payload with the forward-compat libcuda removed before the driver runs.

    It wraps rather than copies build_payload so the image digest, GPU, ports,
    disk, allowed CUDA versions and all 21 env keys stay exactly what the audited
    v10 path produces.  Only the first characters of the entrypoint change.
    """
    payload = _ORIGINAL_BUILD_PAYLOAD(**kwargs)
    entrypoint = list(payload["dockerEntrypoint"])
    if len(entrypoint) != 3 or entrypoint[:2] != ["/bin/bash", "-lc"]:
        raise RuntimeError(f"unexpected v10 entrypoint shape: {entrypoint[:2]}")
    entrypoint[2] = COMPAT_REMOVAL_COMMAND + entrypoint[2]
    payload["dockerEntrypoint"] = entrypoint
    payload["env"] = {**payload["env"], COMPAT_MARKER_ENV: "1"}
    return payload


def main() -> int:
    v10.build_payload = build_payload_without_cuda_compat
    print(
        "[v12] runtime change: /usr/local/cuda/compat removed before the driver "
        "starts (CUDA 804 on GeForce); recorded as "
        f"{COMPAT_MARKER_ENV}=1 in the Pod env",
        flush=True,
    )
    return int(v11.main())


if __name__ == "__main__":
    raise SystemExit(main())
