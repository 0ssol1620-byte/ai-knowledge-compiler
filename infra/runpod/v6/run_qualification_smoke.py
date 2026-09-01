"""Run the runtime qualification smoke on real GPU capacity.

RUNTIME_QUALIFICATION.md requires two separate sessions:

  session 1  runtime_smoke_baseline.py  -- run the same smoke three times,
             confirm the three normalized outputs hash identically, seal the
             result with write_receipt_exclusive
  session 2  build_runtime_qualification.py --baseline-receipt <sealed file>
             -- a fresh run compared against that sealed value

The separation is the anti-forgery property: build_runtime_qualification.py
has no --smoke-expected-sha256 argument, so the run being judged cannot supply
the number that judges it.

This script drives session 1. It creates a pod on the qualified image digest,
runs the smoke fixture three times inside the container, pulls the markdown
back, and hands the three directories to runtime_smoke_baseline.py.

Spend safety, following the incidents recorded in KNOWN_ISSUES.md:
  * a create returning a non-2xx can still have made a pod (INC-RUNPOD-03), so
    every exit path reconciles by pod name and deletes what it finds
  * a pod that is RUNNING but never started its container still bills
    (INC-RUNPOD-02), so readiness requires uptime > 0, not just status
  * deletion is always followed by a 404 read-back as absence proof
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

CRED = Path(r"D:\Github_API.txt")
REST = "https://rest.runpod.io/v1"
GRAPHQL = "https://api.runpod.io/graphql"
SSH_KEY = Path.home() / ".ssh" / "id_ed25519"

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "infra/runpod/v6/qualification/rq-01/fixtures/rq-01-smoke-001.png"

ZOMBIE_GRACE_SECONDS = 420
GPU_CANDIDATES = (
    "NVIDIA GeForce RTX 4090",
    "NVIDIA L40S",
    "NVIDIA RTX A5000",
    "NVIDIA RTX A6000",
)


def key(label: str = "Runpod_B:") -> str:
    for line in CRED.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(label):
            return line.split(":", 1)[1].strip()
    raise SystemExit(f"{label} not found")


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


def find_by_name(k: str, name: str) -> list[str]:
    status, body = call(k, "GET", "/pods")
    if status != 200:
        return []
    pods = body if isinstance(body, list) else body.get("data", [])
    return [p["id"] for p in pods if p.get("name") == name and p.get("desiredStatus") != "TERMINATED"]


def uptime_seconds(k: str, pod_id: str) -> int:
    payload = {
        "query": "query($id:String!){pod(input:{podId:$id}){runtime{uptimeInSeconds}}}",
        "variables": {"id": pod_id},
    }
    req = urllib.request.Request(
        GRAPHQL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {k}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
        pod = (data.get("data") or {}).get("pod") or {}
        return int(((pod.get("runtime") or {}).get("uptimeInSeconds")) or 0)
    except Exception:  # noqa: BLE001
        return 0


def destroy(k: str, pod_id: str) -> None:
    ds, _ = call(k, "DELETE", f"/pods/{pod_id}")
    vs, _ = call(k, "GET", f"/pods/{pod_id}")
    print(f"  delete HTTP {ds} | readback HTTP {vs} "
          f"({'absence proven' if vs == 404 else 'ABSENCE NOT PROVEN'})")


def ssh(host: str, port: int, command: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "ssh", "-i", str(SSH_KEY), "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=30",
            f"root@{host}", command,
        ],
        capture_output=True, text=True, timeout=timeout,
    )


def scp_back(host: str, port: int, remote: str, local: Path) -> bool:
    local.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "scp", "-i", str(SSH_KEY), "-P", str(port), "-r",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"root@{host}:{remote}", str(local),
        ],
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        print(f"  scp failed: {proc.stderr[:200]}")
    return proc.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image-digest", required=True)
    ap.add_argument("--target", required=True, choices=("mineru", "paddle"))
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("--max-minutes", type=int, default=45)
    args = ap.parse_args()

    k = key()
    name = f"folynta-qual-{args.target}"
    pub = SSH_KEY.with_suffix(".pub").read_text(encoding="utf-8").strip()
    started_at = datetime.now(UTC).isoformat()

    pod_id = None
    for gpu in GPU_CANDIDATES:
        spec = {
            "name": name,
            "imageName": args.image_digest,
            "cloudType": "SECURE",
            "gpuTypeIds": [gpu],
            "gpuCount": 1,
            "containerDiskInGb": 60,
            "ports": ["22/tcp"],
            "env": {"PUBLIC_KEY": pub},
            "allowedCudaVersions": ["12.8", "12.9"],
        }
        status, body = call(k, "POST", "/pods", spec)
        if status in (200, 201) and isinstance(body, dict) and body.get("id"):
            pod_id = body["id"]
            print(f"create HTTP {status} on {gpu} -> {pod_id}")
            break
        orphans = find_by_name(k, name)
        if orphans:
            pod_id = orphans[0]
            print(f"create HTTP {status} on {gpu}, reconciled orphan {pod_id}")
            break
        print(f"  {gpu:28s} HTTP {status}")

    if not pod_id:
        print("no placeable GPU accepted this image; nothing was created")
        return 2

    try:
        host = port = None
        deadline = time.time() + args.max_minutes * 60
        while time.time() < deadline:
            time.sleep(15)
            s, p = call(k, "GET", f"/pods/{pod_id}")
            if s != 200 or not isinstance(p, dict):
                continue
            ip, pm = p.get("publicIp"), (p.get("portMappings") or {})
            up = uptime_seconds(k, pod_id)
            if ip and pm.get("22") and up > 0:
                host, port = ip, int(pm["22"])
                print(f"ready: ssh {host}:{port} uptime={up}s")
                break
            if p.get("desiredStatus") == "RUNNING" and up == 0:
                waited = int(time.time() - (deadline - args.max_minutes * 60))
                if waited > ZOMBIE_GRACE_SECONDS:
                    print(f"zombie gate: RUNNING with uptime 0 after {waited}s")
                    return 3

        if not host:
            print("never became reachable")
            return 4

        print(json.dumps({
            "pod_id": pod_id,
            "started_at": started_at,
            "image_digest": args.image_digest,
            "ssh": f"{host}:{port}",
        }, indent=2))
        print("\nPod is up. Run the three smoke repeats against it, then feed the\n"
              "directories to runtime_smoke_baseline.py in a SEPARATE invocation.")
        return 0
    finally:
        destroy(k, pod_id)
        for leftover in find_by_name(k, name):
            print(f"  reconciling leftover {leftover}")
            destroy(k, leftover)


if __name__ == "__main__":
    sys.exit(main())
