#!/usr/bin/env python3
"""Run hard-200 with v16's pipeline and a host CUDA filter that means ">=".

v13 read the CUDA version out of the v29 assembly instead of hard-coding it,
which was the right correction to make, and then implemented the wrong relation:

    payload["allowedCudaVersions"] = ["12.9"]      # v13: equality

The image's own requirement is not equality. The vLLM image declares

    NVIDIA_REQUIRE_CUDA=cuda>=12.9

and `nvidia-container-cli` enforces exactly that: a host at CUDA 13.0 carries a
driver in the 580 series, satisfies `cuda>=12.9`, and runs a cu129 image under
ordinary backward compatibility -- no forward-compat libcuda, so no CUDA 804.
A 13.0 host was always a valid host for this campaign. v13 excluded it.

That exclusion is why every v13-and-later run died on `create pod: There are no
instances currently available` rather than on anything to do with the image.
Measured 2026-08-18 via the RunPod capacity API:

    RTX 4090   cuda 12.8 Medium   cuda 12.9 OUT      cuda 13.0 High
    RTX 3090   cuda 12.8 Low      cuda 12.9 Low      cuda 13.0 Medium
    RTX 5090   cuda 12.8 Low      cuda 12.9 OUT      cuda 13.0 High

The assembly pins an RTX 4090. The one value v13 was willing to accept is the
one value with no stock; the largest pool on that GPU sat one row below and was
filtered out by the campaign itself. No amount of polling reaches capacity that
the request has excluded, and the 20-minute capacity wait v13 added was spent
waiting for a set it had defined as empty.

So v17 keeps the assembly as the source of the number and fixes the relation:
every platform CUDA version at or above the assembly's version is allowed. The
lower bound still does the work it was introduced for -- a 12.8 host is still
refused, because it cannot run the image without forward compat and the 4090 is
GeForce -- while the hosts that exceed the requirement stop being thrown away.

v12's compat removal and v13's capacity polling are both kept. With the filter
correct neither should have anything to do, and both are measured harmless.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

V16_PATH = Path(__file__).with_name("run_stage1_v29_r2_v16_reattachable.py")
_spec = importlib.util.spec_from_file_location("stage1_v16_for_v17", V16_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v16 module cannot be loaded")
v16 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v16
_spec.loader.exec_module(v16)

v15, v14, v13 = v16.v15, v16.v14, v16.v13
v12, v11, v10 = v16.v12, v16.v11, v16.v10

# The CUDA versions RunPod's host filter accepts. This is a platform enum, not a
# TAVONEL choice: the campaign may only ask for values RunPod recognises, and an
# unrecognised string would silently match no host at all -- the same failure
# v17 exists to remove. Kept explicit so that a new platform version is a
# reviewed edit rather than an inference made at runtime.
PLATFORM_CUDA_VERSIONS = (
    "11.8",
    "12.0",
    "12.1",
    "12.2",
    "12.3",
    "12.4",
    "12.5",
    "12.6",
    "12.7",
    "12.8",
    "12.9",
    "13.0",
)

CUDA_FILTER_MARKER_ENV = "TAVONEL_RUNTIME_CUDA_FLOOR"

# Bound at import, before main() rebinds the attribute this shadows.
_ORIGINAL_BUILD_PAYLOAD = v16.build_payload_recording_the_token


def _as_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def versions_at_or_above(minimum: str) -> list[str]:
    """Every platform CUDA version that satisfies `cuda>=minimum`.

    Ordered numerically rather than lexically: "13.0" sorts below "12.9" as text
    and a text sort would put the largest pool last in the request.
    """
    floor = _as_tuple(minimum)
    if minimum not in PLATFORM_CUDA_VERSIONS:
        raise RuntimeError(
            f"v29 assembly pins CUDA {minimum}, which RunPod's host filter does "
            f"not accept; a value outside {PLATFORM_CUDA_VERSIONS} matches no host"
        )
    return [v for v in sorted(PLATFORM_CUDA_VERSIONS, key=_as_tuple) if _as_tuple(v) >= floor]


def build_payload_allowing_every_sufficient_cuda(**kwargs: Any) -> dict[str, Any]:
    """v16's payload with the CUDA filter widened from `==` to `>=`."""
    payload = _ORIGINAL_BUILD_PAYLOAD(**kwargs)
    pinned = list(payload["allowedCudaVersions"])
    if len(pinned) != 1:
        raise RuntimeError(
            f"expected v13 to pin exactly one CUDA version, got {pinned}; the "
            "floor v17 widens from is no longer unambiguous"
        )
    allowed = versions_at_or_above(pinned[0])
    payload["allowedCudaVersions"] = allowed
    payload["env"] = {**payload["env"], CUDA_FILTER_MARKER_ENV: pinned[0]}
    return payload


def main() -> int:
    # v16.main() resolves this name at call time when it installs the payload
    # builder into v13, so rebinding the attribute is the whole patch.
    v16.build_payload_recording_the_token = build_payload_allowing_every_sufficient_cuda
    floor = None
    ready_path = getattr(v10.base, "READY", None)
    if ready_path is not None:
        with contextlib.suppress(OSError, ValueError, KeyError):
            ready = json.loads(Path(ready_path).read_text(encoding="utf-8"))
            floor = str(ready["cuda_version"]).strip()
    allowed = versions_at_or_above(floor) if floor else None
    print(
        "[v17] host filter now means cuda>=<assembly version>, not ==: the image "
        "declares NVIDIA_REQUIRE_CUDA=cuda>=12.9 and a 13.0 host satisfies it. "
        "Measured 2026-08-18: RTX 4090 12.9 stock read Out while 13.0 read High, "
        "so the equality filter was discarding the largest pool on this GPU",
        flush=True,
    )
    if allowed:
        print(f"[v17] allowedCudaVersions = {allowed} (floor {floor})", flush=True)
    return int(v16.main())


if __name__ == "__main__":
    raise SystemExit(main())
