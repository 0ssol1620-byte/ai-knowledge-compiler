#!/usr/bin/env python3
"""Run hard-200 with v12's pipeline and the host CUDA filter taken from READY.

The v10 payload asks RunPod for a host running CUDA 12.8 *or* 12.9:

    "allowedCudaVersions": ["12.8", "12.9"]

The v29 assembly pins `cuda_version = 12.9`, and the base image is a cu129
build. The payload was therefore looser than the contract it implements, and
that gap has a concrete failure attached to it:

  * CUDA 12.9 requires an NVIDIA driver >= 575.51.03 on Linux.
  * CUDA 12.8 requires only >= 570.26.
  * So a "12.8" host can satisfy the filter while being unable to run the image.
  * On such a host the container falls back to the forward-compatibility libcuda
    the vLLM image ships in /usr/local/cuda/compat (575.57.08).
  * NVIDIA supports forward compatibility on "NVIDIA Data Center GPUs, Select
    NGC Server Ready SKUs of RTX cards, Jetson boards" -- not GeForce.
  * The v29 assembly pins an RTX 4090, which is GeForce, so CUDA initialisation
    returns 804 CUDA_ERROR_COMPAT_NOT_SUPPORTED_ON_DEVICE: "the system was
    upgraded to run with forward compatibility but the visible hardware detected
    by CUDA does not support this configuration".

That is the error `run-337b29eba37a` died on. It was not RunPod's fault and not
the driver's: the request asked for a host class the image cannot run on.

The fix is to stop asking. v13 sets the filter from the assembly rather than
from a literal, so the payload cannot disagree with READY again -- if a future
assembly moves to another CUDA version, the request moves with it and no one has
to remember this file exists.

This also explains why the 3090 diagnostic (`probe-ff93e6235cbc`) could not
reproduce 804: that host ran driver 575.51.03, exactly the 12.9 minimum, so
compat was never engaged and CUDA worked with the directory still in place.

v12's compat removal is kept as a second line of defence. With the filter
correct it should never do anything, and it is measured harmless when it does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

V12_PATH = Path(__file__).with_name("run_stage1_v29_r2_v12_cuda_compat.py")
_spec = importlib.util.spec_from_file_location("stage1_v12_for_v13", V12_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v12 module cannot be loaded")
v12 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v12
_spec.loader.exec_module(v12)

v11 = v12.v11
v10 = v12.v10

# Bound at import: v12.main() resolves the name it installs at call time, so
# rebinding the module attribute below is what puts this function in the path.
_ORIGINAL_BUILD_PAYLOAD = v12.build_payload_without_cuda_compat


def build_payload_pinned_to_assembly_cuda(**kwargs: Any) -> dict[str, Any]:
    """v12's payload with allowedCudaVersions taken from the assembly.

    Read from `ready` rather than written as a literal: a hard-coded version is
    exactly how the payload and the assembly drifted apart in the first place.
    """
    ready = kwargs["ready"]
    cuda_version = str(ready["cuda_version"]).strip()
    if not cuda_version:
        raise RuntimeError("v29 assembly does not pin a cuda_version")
    payload = _ORIGINAL_BUILD_PAYLOAD(**kwargs)
    payload["allowedCudaVersions"] = [cuda_version]
    return payload


# Pinning to 12.9 makes the eligible host set much smaller, and RunPod answers a
# create it cannot place with `create pod: There are no instances currently
# available`. That response creates no Pod and costs nothing, so waiting for
# capacity is free -- unlike a host draw, which costs six minutes of GPU rental
# before it can fail. v11's tolerance is sized for a transient server error, not
# for waiting out a capacity window, so v13 widens it.
# Measured 2026-08-18: cuda>=12.9 capacity on COMMUNITY RTX 4090 was present at
# 10:20 KST and gone by 10:52. It comes and goes in minutes. Polling costs
# nothing -- the refused create makes no Pod and is not billed -- so the wait is
# sized to the thing being waited for rather than to a server-error retry.
CAPACITY_POLL_ATTEMPTS = 60
CAPACITY_POLL_DELAY_SECONDS = 20


def main() -> int:
    # v12.main() assigns v10.build_payload from this module-level name, so
    # replacing the attribute is enough; no second patch of v10 is needed.
    v12.build_payload_without_cuda_compat = build_payload_pinned_to_assembly_cuda
    v11.CREATE_5XX_ATTEMPTS = CAPACITY_POLL_ATTEMPTS
    v11.CREATE_5XX_DELAY_SECONDS = CAPACITY_POLL_DELAY_SECONDS
    print(
        "[v13] host filter: allowedCudaVersions taken from the v29 assembly "
        "(was ['12.8','12.9']; a 12.8 host cannot run a cu129 image and forces "
        "forward compat, which GeForce does not support -> CUDA 804)",
        flush=True,
    )
    print(
        f"[v13] free capacity polling: up to {CAPACITY_POLL_ATTEMPTS} creates "
        f"every {CAPACITY_POLL_DELAY_SECONDS}s "
        f"(~{CAPACITY_POLL_ATTEMPTS * CAPACITY_POLL_DELAY_SECONDS // 60} min) per host "
        "attempt; a 'no instances currently available' 500 creates no Pod and is not billed",
        flush=True,
    )
    return int(v12.main())


if __name__ == "__main__":
    raise SystemExit(main())
