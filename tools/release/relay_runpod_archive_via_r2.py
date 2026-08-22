#!/usr/bin/env python3
"""Relay a large local archive through a temporary, verified R2 object."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def parse_r2_credentials(path: Path) -> tuple[str, str, str]:
    in_r2_block = False
    access_key = ""
    secret_key = ""
    endpoint_url = ""
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.rstrip(":=").strip().lower() == "cloudflare r2":
            in_r2_block = True
            continue
        if not in_r2_block:
            continue
        if line.rstrip(":=").strip().lower().startswith("user api tokens"):
            break
        match = line.split(":", 1) if ":" in line else line.split("=", 1)
        if len(match) != 2:
            continue
        name, value = match[0].strip().lower(), match[1].strip()
        if name == "access key id":
            access_key = value
        elif name == "secret access key":
            secret_key = value
        elif name == "use jurisdiction-specific endpoints for s3 clients":
            endpoint_url = value
    if not access_key or not secret_key or not endpoint_url.startswith("https://"):
        raise RuntimeError("Cloudflare R2 credentials are missing or malformed")
    return access_key, secret_key, endpoint_url


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--object-key", required=True)
    parser.add_argument("--bucket")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument("--known-hosts", type=Path, required=True)
    parser.add_argument("--remote-path", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive = args.archive.resolve()
    expected = args.expected_sha256.lower()
    actual = sha256_file(archive)
    if actual != expected:
        raise RuntimeError("local archive hash differs from expected sha256")
    env = parse_env(args.env_file.resolve())
    if not env.get("AKC_S3_ACCESS_KEY_ID") or not env.get("AKC_S3_SECRET_ACCESS_KEY"):
        access_key, secret_key, endpoint_url = parse_r2_credentials(
            args.credential_file.resolve()
        )
        env["AKC_S3_ACCESS_KEY_ID"] = access_key
        env["AKC_S3_SECRET_ACCESS_KEY"] = secret_key
        if env.get("AKC_S3_ENDPOINT_URL", "").startswith("http://localhost"):
            env["AKC_S3_ENDPOINT_URL"] = endpoint_url
            env["AKC_S3_REGION"] = "auto"
    required = (
        "AKC_S3_ENDPOINT_URL",
        "AKC_S3_REGION",
        "AKC_S3_ACCESS_KEY_ID",
        "AKC_S3_SECRET_ACCESS_KEY",
        "AKC_S3_BUCKET_WORKING",
    )
    if any(not env.get(name) for name in required):
        raise RuntimeError("R2 relay configuration is incomplete")
    client = boto3.client(
        "s3",
        endpoint_url=env["AKC_S3_ENDPOINT_URL"],
        region_name=env["AKC_S3_REGION"],
        aws_access_key_id=env["AKC_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AKC_S3_SECRET_ACCESS_KEY"],
    )
    bucket = args.bucket or env["AKC_S3_BUCKET_WORKING"]
    uploaded_at: str | None = None
    downloaded_at: str | None = None
    deleted_at: str | None = None
    try:
        client.upload_file(
            str(archive),
            bucket,
            args.object_key,
            ExtraArgs={"Metadata": {"sha256": actual}},
            Config=TransferConfig(
                multipart_threshold=64 * 1024 * 1024,
                multipart_chunksize=64 * 1024 * 1024,
                max_concurrency=8,
                use_threads=True,
            ),
        )
        uploaded_at = datetime.now(UTC).isoformat()
        head = client.head_object(Bucket=bucket, Key=args.object_key)
        if int(head["ContentLength"]) != archive.stat().st_size:
            raise RuntimeError("temporary R2 object size differs")
        if head.get("Metadata", {}).get("sha256") != actual:
            raise RuntimeError("temporary R2 object metadata hash differs")
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": args.object_key},
            ExpiresIn=3600,
        )
        remote_script = r'''set -euo pipefail
read -r url
destination="$1"
expected="$2"
partial="${destination}.r2-partial"
set +e
http_code=$(curl --ipv4 --silent --show-error --location --retry 5 --retry-delay 2 \
  --output "$partial" --write-out '%{http_code}' "$url" 2>/dev/null)
curl_exit=$?
set -e
if test "$curl_exit" != "0" || test "$http_code" != "200"; then
  printf 'download_failed_curl_%s_http_%s\n' "$curl_exit" "$http_code" >&2
  exit 4
fi
actual=$(sha256sum "$partial" | awk '{print $1}')
if test "$actual" != "$expected"; then
  printf '%s\n' hash_mismatch >&2
  exit 5
fi
mv "$partial" "$destination"
rm -f "${destination}.partial"
printf '%s\n' "$actual"
'''
        command = [
            "ssh",
            "-i",
            str(args.ssh_key.resolve()),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=20",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={args.known_hosts.resolve()}",
            "-p",
            str(args.port),
            f"root@{args.host}",
            "bash",
            "-c",
            remote_script,
            "relay",
            args.remote_path,
            actual,
        ]
        completed = subprocess.run(  # noqa: S603 - fixed ssh executable and validated inputs
            command,
            input=url + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0 or completed.stdout.strip() != actual:
            detail = completed.stderr.strip()[:200] or f"exit-{completed.returncode}"
            raise RuntimeError(
                f"remote R2 relay download or hash verification failed: {detail}"
            )
        downloaded_at = datetime.now(UTC).isoformat()
    finally:
        if uploaded_at is not None:
            client.delete_object(Bucket=bucket, Key=args.object_key)
            deleted_at = datetime.now(UTC).isoformat()
    receipt = {
        "schema": "folynta.runpod-r2-relay.v1",
        "archive_sha256": f"sha256:{actual}",
        "archive_bytes": archive.stat().st_size,
        "object_key_sha256": "sha256:"
        + hashlib.sha256(args.object_key.encode("utf-8")).hexdigest(),
        "temporary_object_deleted": True,
        "uploaded_at_utc": uploaded_at,
        "downloaded_at_utc": downloaded_at,
        "deleted_at_utc": deleted_at,
        "remote_host": args.host,
        "remote_port": args.port,
        "remote_path": args.remote_path,
    }
    args.receipt.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.receipt.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"relay failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
