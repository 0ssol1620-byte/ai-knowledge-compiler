"""Mount each surviving network volume and inventory it over SSH.

INC-RUNPOD-05: fastdeploy-gpu 2.3.0 is withdrawn from PyPI and the vendor CDN,
but it is pinned in six places including the 2026-08-01 runtime manifest, and
the image patches fastdeploy/input/text_processor.py against a version-specific
sha256. Recovering the original artifact is the only option that keeps the
frozen runtime identity intact.

The 2026-08-01 Paddle bootstrap built its venv at
/workspace/folynta/venvs/paddle-fastdeploy-r1, and /workspace is a network
volume mount point. Both volumes from that era still exist, so this checks
whether the venv (or a pip cache holding the wheel) survived.

Creates one pod per volume, runs a bounded read-only inventory over SSH,
deletes the pod, and proves absence with a 404 readback. Writes nothing to the
volumes. Ambiguous creates are reconciled by name, per INC-RUNPOD-03.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

CRED = Path(r"D:\Github_API.txt")
SSH_KEY = Path.home() / ".ssh" / "tavonel_w6"
REST = "https://rest.runpod.io/v1"

VOLUMES = [
    ("j5wfgniyjx", "US-KS-2", "tavonel-r-cache-us-ks-2-v1"),
    ("o9eslyovmd", "EU-RO-1", "tavonel-r-cache-eu-ro-1-v1"),
]

PROBE = r"""
echo '===ROOT==='; ls -la /workspace 2>&1 | head -30
echo '===FOLYNTA==='; find /workspace -maxdepth 5 -iname 'folynta*' 2>/dev/null | head -20
echo '===FASTDEPLOY==='; find /workspace -maxdepth 9 -iname '*fastdeploy*' 2>/dev/null | head -40
echo '===WHEELS==='; find /workspace -maxdepth 9 -name '*.whl' 2>/dev/null | head -40
echo '===DISTINFO==='; find /workspace -maxdepth 10 -type d -name 'fastdeploy_gpu-*' 2>/dev/null | head -10
echo '===VENVS==='; ls -la /workspace/folynta/venvs 2>/dev/null | head -20
echo '===DU==='; du -sh /workspace 2>/dev/null | tail -2
echo '===END==='
"""


def key() -> str:
    for line in CRED.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Runpod_B:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("Runpod_B key not found")


def call(k: str, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{REST}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {k}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:400]


def find_by_name(k: str, name: str) -> list[str]:
    s, listing = call(k, "GET", "/pods")
    if s != 200:
        return []
    pods = listing if isinstance(listing, list) else listing.get("pods", [])
    return [p["id"] for p in pods if p.get("name") == name and p.get("id")]


def scan(k: str, vol_id: str, dc: str, vol_name: str) -> None:
    print(f"\n{'=' * 62}\n{vol_name} ({vol_id}) @ {dc}\n{'=' * 62}")
    name = f"folynta-volscan-{vol_id}"
    pub = (SSH_KEY.with_suffix(".pub")).read_text(encoding="utf-8").strip()

    # The first attempt hard-coded the 4090 and both datacenters answered
    # HTTP 500 "no instances currently available". The job here is `ls` on a
    # mounted volume, so any placeable GPU will do -- try a spread of types
    # rather than insisting on one.
    candidates = [
        "NVIDIA RTX A4000",
        "NVIDIA RTX A5000",
        "NVIDIA GeForce RTX 3090",
        "NVIDIA GeForce RTX 4090",
        "NVIDIA L4",
        "NVIDIA RTX 2000 Ada Generation",
        "NVIDIA RTX A4500",
        "NVIDIA A40",
    ]

    pod_id = None
    for gpu in candidates:
        spec = {
            "name": name,
            "imageName": "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04",
            "cloudType": "SECURE",
            "gpuTypeIds": [gpu],
            "gpuCount": 1,
            "containerDiskInGb": 10,
            "volumeMountPath": "/workspace",
            "networkVolumeId": vol_id,
            "dataCenterIds": [dc],
            "ports": ["22/tcp"],
            "env": {"PUBLIC_KEY": pub},
        }
        status, body = call(k, "POST", "/pods", spec)
        if status in (200, 201) and isinstance(body, dict) and body.get("id"):
            pod_id = body["id"]
            print(f"create -> HTTP {status} on {gpu}")
            break
        # An ambiguous write can still have created capacity (INC-RUNPOD-03).
        orphans = find_by_name(k, name)
        if orphans:
            pod_id = orphans[0]
            print(f"create -> HTTP {status} on {gpu}, but pod {pod_id} exists")
            break
        print(f"  {gpu:32s} HTTP {status}")

    if not pod_id:
        print("  no placeable GPU in this datacenter; volume not inspected")
        return

    print(f"  pod {pod_id}")
    try:
        host = port = None
        for _ in range(40):
            time.sleep(10)
            s, p = call(k, "GET", f"/pods/{pod_id}")
            if s != 200:
                continue
            ip = p.get("publicIp")
            pm = p.get("portMappings") or {}
            if ip and pm.get("22"):
                host, port = ip, pm["22"]
                print(f"  ssh {host}:{port}")
                break
        if not host:
            print("  never became reachable")
            return

        time.sleep(15)
        cmd = [
            "ssh", "-i", str(SSH_KEY), "-p", str(port),
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=25", f"root@{host}", PROBE,
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        print(out.stdout or "(no stdout)")
        if out.returncode != 0:
            print(f"  ssh rc={out.returncode} {out.stderr[:200]}")
    finally:
        ds, _ = call(k, "DELETE", f"/pods/{pod_id}")
        vs, _ = call(k, "GET", f"/pods/{pod_id}")
        print(f"  delete HTTP {ds} | readback HTTP {vs} (404 == absence proven)")


def main() -> None:
    k = key()
    for vol_id, dc, vol_name in VOLUMES:
        scan(k, vol_id, dc, vol_name)


if __name__ == "__main__":
    main()
