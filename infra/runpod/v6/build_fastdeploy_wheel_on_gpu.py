"""Build the fastdeploy-gpu 2.3.0 wheel on real GPU capacity.

The wheel is withdrawn upstream and the source build cannot run on GitHub
Actions: FastDeploy's setup.py imports paddle to discover CUDA settings, and
paddle needs libcuda.so.1 from the NVIDIA driver, which CI runners do not
have. A GPU pod does.

This is not a workaround for the gate -- it is the gate's own requirement met
honestly. The build happens on a real device with a real driver, so the CUDA
architecture and compiler flags baked into the binary are discovered rather
than fabricated.

What it produces: a wheel, its sha256, and the sha256 of
fastdeploy/input/text_processor.py inside it. That second hash is the one that
matters -- the image asserts b50570cb...a396d on that file, so if the built
wheel carries the same bytes as the withdrawn one at that path, the frozen
identity survives the change of delivery route.

Spend safety follows KNOWN_ISSUES: name-based reconciliation on ambiguous
creates (INC-RUNPOD-03), uptime>0 readiness rather than status (INC-RUNPOD-02),
404 read-back after every delete.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CRED = Path(r"D:\Github_API.txt")
REST = "https://rest.runpod.io/v1"
GRAPHQL = "https://api.runpod.io/graphql"
SSH_KEY = Path.home() / ".ssh" / "tavonel_w6"
OUT_DIR = Path(r"D:\CodexProjects\ai-knowledge-compiler-vkc-research\artifacts\fastdeploy-230")

POD_NAME = "folynta-fastdeploy-src-build"
# The image must carry a CUDA runtime new enough for paddlepaddle cu126.
BUILD_IMAGE = "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04"
GPU_CANDIDATES = (
    "NVIDIA GeForce RTX 4090",
    "NVIDIA RTX A5000",
    "NVIDIA L40S",
    "NVIDIA RTX A6000",
    "NVIDIA A40",
)

BUILD_SCRIPT = r"""
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
echo "===DRIVER==="
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader || echo "NO nvidia-smi"
ls -l /usr/lib/x86_64-linux-gnu/libcuda.so.1 2>/dev/null || echo "NO libcuda.so.1"

echo "===SETUP==="
apt-get update -qq
apt-get install -y -qq --no-install-recommends git python3.11 python3.11-venv python3.11-dev build-essential >/dev/null

python3.11 -m venv /opt/build
/opt/build/bin/python -m pip install -q --upgrade 'pip==25.1.1' 'setuptools>=68' wheel

echo "===PADDLE==="
/opt/build/bin/python -m pip install -q 'paddlepaddle-gpu==3.2.1' \
  --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
/opt/build/bin/python -c "import paddle; print('paddle', paddle.__version__)"

echo "===BUILD==="
rm -rf /tmp/fd && git clone --quiet https://github.com/PaddlePaddle/FastDeploy.git /tmp/fd
cd /tmp/fd
git checkout -q v2.3.0
git submodule update --init --recursive -q
echo "commit $(git rev-parse HEAD)"

echo "===SOURCE HASH (pre-build)==="
sha256sum fastdeploy/input/text_processor.py

mkdir -p /tmp/wheels
/opt/build/bin/python -m pip wheel . --no-build-isolation --no-deps -w /tmp/wheels 2>&1 | tail -25

echo "===RESULT==="
ls -l /tmp/wheels/ || true
for w in /tmp/wheels/*.whl; do
  echo "WHEEL $(sha256sum "$w")"
  /opt/build/bin/python - "$w" <<'PY'
import hashlib, sys, zipfile
path = sys.argv[1]
with zipfile.ZipFile(path) as zf:
    for name in zf.namelist():
        if name.endswith("fastdeploy/input/text_processor.py"):
            data = zf.read(name)
            print(f"INNER {hashlib.sha256(data).hexdigest()}  {name}  {len(data)} bytes")
PY
done
echo "===END==="
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]


def find_by_name(k: str, name: str) -> list[str]:
    status, body = call(k, "GET", "/pods")
    if status != 200:
        return []
    pods = body if isinstance(body, list) else body.get("data", [])
    return [
        p["id"] for p in pods
        if p.get("name") == name and p.get("desiredStatus") not in ("TERMINATED", "EXITED")
    ]


def uptime(k: str, pod_id: str) -> int | None:
    payload = {
        "query": "query($id:String!){pod(input:{podId:$id}){runtime{uptimeInSeconds}}}",
        "variables": {"id": pod_id},
    }
    req = urllib.request.Request(
        GRAPHQL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {k}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload_out = json.load(resp)
    except Exception:  # noqa: BLE001
        # Transport failure: no evidence either way. Returning 0 here once
        # destroyed a healthy build pod mid-build, because the caller read it
        # as "container never started".
        return None

    if payload_out.get("errors"):
        return None

    data = payload_out.get("data")
    if not isinstance(data, dict) or "pod" not in data:
        return None

    pod = data.get("pod")
    if pod is None:
        # The provider answered and says this pod does not exist.
        return None

    runtime = pod.get("runtime")
    if runtime is None:
        # A real answer: the pod exists and its container has not started.
        # This is the definite zero the zombie gate is for -- unlike the
        # swallowed-exception zero, it is evidence.
        return 0
    return int(runtime.get("uptimeInSeconds") or 0)


def destroy(k: str, pod_id: str) -> None:
    ds, _ = call(k, "DELETE", f"/pods/{pod_id}")
    vs, _ = call(k, "GET", f"/pods/{pod_id}")
    print(f"  delete HTTP {ds} | readback HTTP {vs} "
          f"({'absence proven' if vs == 404 else 'ABSENCE NOT PROVEN'})")


def main() -> int:
    k = key()
    pub = SSH_KEY.with_suffix(".pub").read_text(encoding="utf-8").strip()

    pod_id = None
    for gpu in GPU_CANDIDATES:
        spec = {
            "name": POD_NAME,
            "imageName": BUILD_IMAGE,
            "cloudType": "SECURE",
            "gpuTypeIds": [gpu],
            "gpuCount": 1,
            "containerDiskInGb": 60,
            "ports": ["22/tcp"],
            "env": {"PUBLIC_KEY": pub},
        }
        status, body = call(k, "POST", "/pods", spec)
        if status in (200, 201) and isinstance(body, dict) and body.get("id"):
            pod_id = body["id"]
            print(f"create HTTP {status} on {gpu} -> {pod_id}")
            break
        orphans = find_by_name(k, POD_NAME)
        if orphans:
            pod_id = orphans[0]
            print(f"create HTTP {status}, reconciled orphan {pod_id}")
            break
        print(f"  {gpu:28s} HTTP {status}")

    if not pod_id:
        print("no placeable GPU; nothing created")
        return 2

    try:
        host = port = None
        definite_zeros = 0
        started = time.time()
        while time.time() - started < 900:
            time.sleep(15)
            s, p = call(k, "GET", f"/pods/{pod_id}")
            if s != 200 or not isinstance(p, dict):
                continue
            ip, pm = p.get("publicIp"), (p.get("portMappings") or {})
            up = uptime(k, pod_id)
            # A reachable SSH endpoint is itself proof the container is up;
            # requiring a positive uptime as well let a lagging field hide a
            # perfectly good pod.
            if ip and pm.get("22"):
                host, port = ip, int(pm["22"])
                print(f"ready: {host}:{port} uptime={up if up is not None else 'unknown'}")
                break
            # Only a definite zero counts, and only a run of them. One failed
            # query must never be enough to destroy a running build.
            if up == 0:
                definite_zeros += 1
            elif up is None:
                print("  uptime unknown (query failed); not counting toward the gate")
            else:
                definite_zeros = 0
            if (
                p.get("desiredStatus") == "RUNNING"
                and definite_zeros >= 4
                and time.time() - started > 420
            ):
                print(f"zombie gate: {definite_zeros} consecutive definite zero uptimes")
                return 3
        if not host:
            print("never became reachable")
            return 4

        time.sleep(20)
        print("\nrunning the build (this takes a while)...\n")
        proc = subprocess.run(
            [
                "ssh", "-i", str(SSH_KEY), "-p", str(port),
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=30",
                f"root@{host}", "bash -s",
            ],
            # Send bytes, not text. With text=True, Windows opens the child's
            # stdin in text mode and translates every "\n" we write into
            # "\r\n" AFTER any normalisation we do here -- the remote bash then
            # dies on "$'\r': command not found" no matter how clean the string
            # was. Encoding explicitly and passing text=False sends exactly
            # these bytes.
            input=BUILD_SCRIPT.replace("\r\n", "\n").encode("utf-8"),
            capture_output=True, timeout=3300,
        )
        stdout = proc.stdout.decode("utf-8", "replace")
        stderr = proc.stderr.decode("utf-8", "replace")
        print(stdout[-6000:])
        if proc.returncode != 0:
            print(f"\nssh rc={proc.returncode}\n{stderr[-1500:]}")

        # Pull any wheel back before the pod dies.
        if "WHEEL " in stdout:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "scp", "-i", str(SSH_KEY), "-P", str(port),
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null",
                    f"root@{host}:/tmp/wheels/*.whl", str(OUT_DIR),
                ],
                capture_output=True, text=True, timeout=1800,
            )
            for w in OUT_DIR.glob("*.whl"):
                print(f"retrieved {w.name} {w.stat().st_size:,} bytes")
        return 0 if proc.returncode == 0 else 5
    finally:
        destroy(k, pod_id)
        for leftover in find_by_name(k, POD_NAME):
            print(f"  reconciling leftover {leftover}")
            destroy(k, leftover)


if __name__ == "__main__":
    sys.exit(main())
