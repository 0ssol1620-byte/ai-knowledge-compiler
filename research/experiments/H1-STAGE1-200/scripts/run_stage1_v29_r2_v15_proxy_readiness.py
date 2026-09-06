#!/usr/bin/env python3
"""Run hard-200 with v14's pipeline, deciding readiness by asking the Pod.

Pod `bea8tq6hf3sf6t` was measured serving both control ports while RunPod's API
reported it had none:

    REST portMappings      None
    GraphQL runtime.ports  []
    GET https://bea8tq6hf3sf6t-8001.proxy.runpod.net/   401
    GET https://bea8tq6hf3sf6t-8002.proxy.runpod.net/   401

401 is not the proxy shrugging. Two controls taken in the same minute say so:
a port that was never exposed on that same live Pod (9999, 7777) answered 404,
and a Pod that had been deleted and its absence verified answered 404 as well.
A 404 is "nothing here"; the 401 came from something behind the port.

v10 decides readiness from `publicPortPresent` in the API, so it would have
waited on that Pod until its 360 s cutoff and deleted a container that was
already up. The same file already records the opposite error -- port 19123
reported `publicPortPresent: true` with nothing listening -- so the API's port
view is unreliable in both directions and is not a readiness signal at all.

v15 keeps the API read for the receipt and adds the only test that reflects what
the campaign actually needs: can something be reached on 8001 and 8002? A Pod is
ready when both answer anything other than 404. It is deliberately not "answers
200": the qualifier requires a control token, so 401 is the correct healthy
response before the driver is addressed, and demanding 200 would reintroduce the
same false negative from the other side.

Everything else is v14 and below: COMMUNITY placement, the assembly CUDA pin, the
compat removal, the httpx transport, the frugal upload, and v10's audited create,
cleanup and receipt paths.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

V14_PATH = Path(__file__).with_name("run_stage1_v29_r2_v14_community.py")
_spec = importlib.util.spec_from_file_location("stage1_v14_for_v15", V14_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v14 module cannot be loaded")
v14 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v14
_spec.loader.exec_module(v14)

v13, v12, v11, v10 = v14.v13, v14.v12, v14.v11, v14.v10

PROXY_HOST = "{pod_id}-{port}.proxy.runpod.net"
PROXY_TIMEOUT_SECONDS = 15
# The proxy answers 404 for a port that is not exposed and for a Pod that no
# longer exists. Anything else means the request reached a listener.
NOT_EXPOSED_STATUS = 404

_ORIGINAL_SNAPSHOT = v10.runtime_snapshot


def control_port_reachable(pod_id: str, port: int) -> bool:
    try:
        response = httpx.get(
            f"https://{PROXY_HOST.format(pod_id=pod_id, port=port)}/",
            timeout=PROXY_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        return False
    return response.status_code != NOT_EXPOSED_STATUS


def snapshot_with_proxy_readiness(transport: Any, pod_id: str) -> dict[str, Any]:
    """v10's snapshot, with `runtime_present` decided by reaching the Pod."""
    snapshot = _ORIGINAL_SNAPSHOT(transport, pod_id)
    reachable = {
        port: control_port_reachable(pod_id, port) for port in sorted(v10.REQUIRED_CONTROL_PORTS)
    }
    snapshot["control_ports_reachable"] = reachable
    snapshot["runtime_present_per_api"] = snapshot.get("runtime_present")
    snapshot["runtime_present"] = all(reachable.values())
    return snapshot


def main() -> int:
    v10.runtime_snapshot = snapshot_with_proxy_readiness
    print(
        "[v15] readiness = both control ports answer the RunPod proxy with "
        "anything but 404; the API's publicPortPresent has been observed wrong "
        "in both directions and is kept only for the receipt",
        flush=True,
    )
    return int(v14.main())


if __name__ == "__main__":
    raise SystemExit(main())
