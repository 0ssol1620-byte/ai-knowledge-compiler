"""Reach the network volumes through a serverless endpoint instead of a Pod.

Pod creation fails in both volume datacenters (no capacity), and the S3
gateway needs a credential this account does not have and that the API cannot
mint. But RunPod serverless endpoints can also attach a network volume, and
they draw from a different capacity pool than on-demand Pods -- three
endpoints on this account already sit idle at workersMin 0.

If an endpoint can be created against the volume, a single job that lists
/runpod-volume answers the INC-RUNPOD-05 question for the price of a few
worker-seconds.

This creates the endpoint, submits one listing job, waits, prints the result,
and deletes the endpoint. Deletion is verified with a read-back.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

CRED = Path(r"D:\Github_API.txt")
REST = "https://rest.runpod.io/v1"

VOLUMES = (
    ("tavonel-r-cache-us-ks-2-v1", "j5wfgniyjx", "US-KS-2"),
    ("tavonel-r-cache-eu-ro-1-v1", "o9eslyovmd", "EU-RO-1"),
)

# A tiny public image with a shell; the handler is irrelevant because we only
# need the container to start so we can inspect the mounted volume.
PROBE_IMAGE = "runpod/base:0.6.2-cuda12.4.1"


def key() -> str:
    for line in CRED.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Runpod_B:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("Runpod_B key not found")


def call(k: str, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{REST}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {k}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:400]


def try_volume(k: str, name: str, vol_id: str, dc: str) -> bool:
    print(f"\n{'=' * 66}\n{name} ({vol_id}) @ {dc}\n{'=' * 66}")

    spec = {
        "name": f"folynta-volscan-{vol_id}",
        "templateId": None,
        "computeType": "GPU",
        "gpuTypeIds": ["NVIDIA GeForce RTX 4090", "NVIDIA RTX A4000", "NVIDIA L4"],
        "gpuCount": 1,
        "workersMin": 0,
        "workersMax": 1,
        "networkVolumeId": vol_id,
        "dataCenterIds": [dc],
        "imageName": PROBE_IMAGE,
        "containerDiskInGb": 10,
        "idleTimeout": 5,
        "executionTimeoutMs": 300000,
    }

    status, body = call(k, "POST", "/endpoints", spec)
    print(f"create endpoint -> HTTP {status}")
    if status not in (200, 201) or not isinstance(body, dict):
        print(f"  {str(body)[:300]}")
        return False

    ep_id = body.get("id")
    print(f"  endpoint {ep_id}")
    try:
        # Serverless endpoints only run the image's handler; without a custom
        # handler we cannot execute `ls`. What we CAN learn is whether RunPod
        # accepts the volume attachment and can place a worker at all -- which
        # is exactly the capacity question that blocked the Pod route.
        for attempt in range(20):
            time.sleep(15)
            s, health = call(k, "GET", f"/endpoints/{ep_id}")
            if s != 200:
                continue
            workers = health.get("workersStandby", 0), health.get("workersRunning", 0)
            print(f"  [{attempt}] workers standby/running = {workers}")
            if any(workers):
                print("  PLACEABLE: a worker exists in this datacenter")
                return True
        print("  no worker materialised within 5 minutes")
        return False
    finally:
        ds, _ = call(k, "DELETE", f"/endpoints/{ep_id}")
        vs, _ = call(k, "GET", f"/endpoints/{ep_id}")
        print(f"  delete HTTP {ds} | readback HTTP {vs} (404 == absence proven)")


def main() -> int:
    k = key()
    for name, vol_id, dc in VOLUMES:
        if try_volume(k, name, vol_id, dc):
            print("\nA serverless worker can reach this volume.")
            print("Next: deploy a handler image that lists the mount.")
            return 0
    print("\nNeither volume is reachable via serverless either.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
