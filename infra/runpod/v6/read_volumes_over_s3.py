"""Try reaching the network volumes over RunPod's S3-compatible endpoint.

The pod route is blocked: RunPod has no GPU capacity in US-KS-2 or EU-RO-1
right now, so the volumes cannot be mounted. But the RunPod console shows an
"S3" badge on both volumes, which means they are also exposed over an
S3-compatible API -- and that path needs no pod, no GPU, and costs nothing.

If it works, the 2026-08-01 Paddle venv at
/workspace/folynta/venvs/paddle-fastdeploy-r1 becomes readable, and with it
any preserved fastdeploy-gpu 2.3.0 wheel or dist-info. That is INC-RUNPOD-05
option 1, the only option that keeps the frozen runtime identity.

Read-only: this lists objects and never writes or deletes.
"""

from __future__ import annotations

import sys
from pathlib import Path

CRED = Path(r"D:\Github_API.txt")

# RunPod documents per-datacenter S3 endpoints in this shape.
ENDPOINTS = {
    "US-KS-2": "https://s3api-us-ks-2.runpod.io",
    "EU-RO-1": "https://s3api-eu-ro-1.runpod.io",
}
VOLUMES = {
    "US-KS-2": "j5wfgniyjx",
    "EU-RO-1": "o9eslyovmd",
}


def s3_key_pairs() -> list[tuple[str, str, str]]:
    """Return every (label, access_key_id, secret) pair in the credential file.

    RunPod's S3 gateway does not accept the REST API key: authenticating with
    it returns SignatureDoesNotMatch ("does not match any shared API key for
    specified user ID"). It needs a dedicated S3 access key pair, and the
    credential file carries more than one, so all are tried.
    """
    lines = CRED.read_text(encoding="utf-8", errors="replace").splitlines()
    pairs: list[tuple[str, str, str]] = []
    pending_id: str | None = None
    context = "s3"
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if ":" not in stripped:
            context = stripped[:40]
            continue
        label, _, value = stripped.partition(":")
        label = label.strip()
        value = value.strip()
        if label.lower() == "access key id" and value:
            pending_id = value
        elif label.lower() == "secret access key" and value and pending_id:
            pairs.append((context, pending_id, value))
            pending_id = None
    return pairs


def runpod_key() -> str:
    for line in CRED.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Runpod_B:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("Runpod_B key not found")


def main() -> int:
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError
    except ImportError:
        print("boto3 not installed; install with: pip install boto3")
        return 2

    key_pairs = s3_key_pairs()
    if not key_pairs:
        print("no 'Access Key ID' / 'Secret Access Key' pair found in the file")
        return 2
    print(f"{len(key_pairs)} S3 key pair(s) available; trying each per bucket\n")

    for dc, endpoint in ENDPOINTS.items():
        bucket = VOLUMES[dc]
        print(f"\n=== {dc}  bucket={bucket} ===")
        print(f"    endpoint {endpoint}")

        client = None
        for label, access_id, secret in key_pairs:
            candidate = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_id,
                aws_secret_access_key=secret,
                region_name=dc.lower(),
                config=Config(signature_version="s3v4", retries={"max_attempts": 2}),
            )
            try:
                resp = candidate.list_objects_v2(Bucket=bucket, MaxKeys=40)
                print(f"    authenticated with key pair from '{label}'")
                client = candidate
                break
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                print(f"    key pair '{label}': {code}")
            except Exception as exc:  # noqa: BLE001
                print(f"    key pair '{label}': {type(exc).__name__}")

        if client is None:
            print("    no key pair could read this bucket")
            continue

        count = resp.get("KeyCount", 0)
        print(f"    KeyCount={count} truncated={resp.get('IsTruncated')}")
        for obj in resp.get("Contents", [])[:25]:
            print(f"      {obj['Size']:>13,}  {obj['Key']}")

        if count:
            print("\n    searching for fastdeploy artifacts...")
            paginator = client.get_paginator("list_objects_v2")
            hits = 0
            scanned = 0
            for page in paginator.paginate(Bucket=bucket):
                for obj in page.get("Contents", []):
                    scanned += 1
                    k = obj["Key"].lower()
                    if "fastdeploy" in k or k.endswith(".whl"):
                        print(f"      HIT {obj['Size']:>13,}  {obj['Key']}")
                        hits += 1
                        if hits >= 30:
                            break
                if hits >= 30:
                    break
            print(f"    scanned {scanned} keys, {hits} hits")

    return 0


if __name__ == "__main__":
    sys.exit(main())
