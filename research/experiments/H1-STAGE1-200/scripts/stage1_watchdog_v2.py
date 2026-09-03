#!/usr/bin/env python3
"""Independent hard cleanup guard for a paid Stage-1 RunPod/R2 run."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[4]
SCRATCH = ROOT / ".chatgpt2codex"
sys.path.insert(0, str(SCRATCH))
sys.path.insert(0, str(ROOT))

from runpod_curl_transport_v2 import RunPodCurlTransport  # noqa: E402
from runpod_registry_auth_v27 import read_labeled_secret  # noqa: E402

from tools.release.relay_runpod_archive_via_r2 import parse_r2_credentials  # noqa: E402


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_cleanup(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return dict(value) if isinstance(value, dict) else None


def r2_delete_verify(credential_file: Path, bucket: str, key: str) -> bool:
    access_key, secret_key, endpoint = parse_r2_credentials(credential_file)
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    client.delete_object(Bucket=bucket, Key=key)
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return True
        raise
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--runpod-label", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--r2-bucket", required=True)
    parser.add_argument("--r2-key", required=True)
    parser.add_argument("--deadline-seconds", type=int, default=110 * 60)
    args = parser.parse_args()
    if not 10 * 60 <= args.deadline_seconds <= 3 * 60 * 60:
        raise RuntimeError("watchdog deadline is outside bounded range")
    run_dir = args.run_dir.resolve()
    if ROOT not in run_dir.parents:
        raise RuntimeError("watchdog run directory escaped project root")
    cleanup_path = run_dir / "cleanup-receipt.json"
    deadline = time.monotonic() + args.deadline_seconds
    while time.monotonic() < deadline:
        cleanup = read_cleanup(cleanup_path)
        if (
            cleanup is not None
            and cleanup.get("pod_absence_verified") is True
            and cleanup.get("r2_absence_verified") is True
        ):
            receipt = {
                "schema": "tavonel.stage1-watchdog.v1",
                "completed_at": now(),
                "action": "NOOP_CONTROLLER_CLEANUP_VERIFIED",
                "pod_absence_verified": True,
                "r2_absence_verified": True,
            }
            (run_dir / "watchdog-receipt.json").write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return 0
        time.sleep(15)

    errors: list[str] = []
    key = read_labeled_secret(args.credential_file.resolve(), args.runpod_label)
    transport = RunPodCurlTransport(api_key=key)
    pod_absent = transport.verify_deleted(args.pod_id)
    if not pod_absent:
        try:
            transport.delete_pod(args.pod_id)
            for _ in range(30):
                if transport.verify_deleted(args.pod_id):
                    pod_absent = True
                    break
                time.sleep(3)
        except Exception as exc:
            errors.append("pod:" + type(exc).__name__)
    r2_absent = False
    try:
        r2_absent = r2_delete_verify(
            args.credential_file.resolve(),
            args.r2_bucket,
            args.r2_key,
        )
    except Exception as exc:
        errors.append("r2:" + type(exc).__name__)
    receipt = {
        "schema": "tavonel.stage1-watchdog.v1",
        "completed_at": now(),
        "action": "HARD_DEADLINE_CLEANUP",
        "pod_absence_verified": pod_absent,
        "r2_absence_verified": r2_absent,
        "cleanup_errors": errors,
    }
    (run_dir / "watchdog-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if pod_absent and r2_absent and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
