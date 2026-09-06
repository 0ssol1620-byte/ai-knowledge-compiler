#!/usr/bin/env python3
"""Run hard-200 with v13's pipeline on COMMUNITY hosts instead of SECURE.

This exists because of a measured capacity fact, not a preference. At
2026-08-18 ~10:20 KST a create carrying `allowedCudaVersions: ["12.9"]` -- the
only host class that can start the v29 base image, whose label is
`NVIDIA_REQUIRE_CUDA=cuda>=12.9` -- was refused on every SECURE GPU offered:

    SECURE     RTX 4090   no instances currently available
    SECURE     RTX 5090   no instances currently available
    SECURE     A40        no instances currently available
    SECURE     RTX A6000  no instances currently available
    SECURE     L4         no instances currently available
    COMMUNITY  RTX 4090   available
    COMMUNITY  RTX 3090   available

Exactly one field changes: `cloudType`. The GPU stays the RTX 4090 the assembly
pins, the base image digest, the qualifier bytes, READY, the driver, the bundle
and the 200-document cohort are untouched, and v13's CUDA pin and v12's compat
removal both remain in force.

**Its output is not SECURE-cloud evidence and must not be labelled as such.**
A community host is hardware someone else operates, so the isolation properties
the v29 assembly assumes do not hold. That is a difference in evidence grade,
not in throughput, and it is the reason this is a separate file with a separate
name rather than a flag on v13: a reader of a receipt should be able to see
which one produced it without reading a config.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

V13_PATH = Path(__file__).with_name("run_stage1_v29_r2_v13_cuda_pin.py")
_spec = importlib.util.spec_from_file_location("stage1_v13_for_v14", V13_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v13 module cannot be loaded")
v13 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v13
_spec.loader.exec_module(v13)

v12 = v13.v12
v11 = v13.v11
v10 = v13.v10

CLOUD_TYPE = "COMMUNITY"
# Rides in the Pod env so RunPod's own record of the Pod, and therefore anything
# derived from it, carries the deviation rather than only this source file.
CLOUD_MARKER_ENV = "TAVONEL_RUNTIME_CLOUD_TYPE"

# v10 rotates across every eligible credential, which is right for a campaign and
# wrong when a human needs to watch one account's Pods in the RunPod console.
# Set TAVONEL_ONLY_CREDENTIAL to hold the run to a single label. It narrows the
# account pool, never the host pool, so it cannot change what a host does.
ONLY_CREDENTIAL_ENV = "TAVONEL_ONLY_CREDENTIAL"

_ORIGINAL_CANDIDATES = v10.candidate_transports
_ORIGINAL_BUILD_PAYLOAD = v13.build_payload_pinned_to_assembly_cuda


def candidates_limited_to_one_credential(credential_file: Path) -> list[Any]:
    """v10's preflight, then keep only the requested label."""
    wanted = os.environ.get(ONLY_CREDENTIAL_ENV, "").strip()
    candidates = _ORIGINAL_CANDIDATES(credential_file)
    if not wanted:
        return candidates
    kept = [pair for pair in candidates if pair[0] == wanted]
    if not kept:
        raise RuntimeError(
            f"{ONLY_CREDENTIAL_ENV}={wanted} but that credential did not pass "
            "Stage-1 preflight (running Pod, low balance, or active spend)"
        )
    return kept


def build_payload_on_community_hosts(**kwargs: Any) -> dict[str, Any]:
    payload = _ORIGINAL_BUILD_PAYLOAD(**kwargs)
    payload["cloudType"] = CLOUD_TYPE
    payload["env"] = {**payload["env"], CLOUD_MARKER_ENV: CLOUD_TYPE}
    return payload


def main() -> int:
    v13.build_payload_pinned_to_assembly_cuda = build_payload_on_community_hosts
    v10.candidate_transports = candidates_limited_to_one_credential
    only = os.environ.get(ONLY_CREDENTIAL_ENV, "").strip()
    if only:
        print(f"[v14] credential pinned to {only} for console inspection", flush=True)
    print(
        f"[v14] cloudType={CLOUD_TYPE} (SECURE had no cuda>=12.9 capacity on any "
        f"GPU offered); recorded as {CLOUD_MARKER_ENV}={CLOUD_TYPE} in the Pod env",
        flush=True,
    )
    print(
        "[v14] output of this run is NOT SECURE-cloud evidence and must not be "
        "labelled as v29 SECURE campaign output",
        flush=True,
    )
    return int(v13.main())


if __name__ == "__main__":
    raise SystemExit(main())
