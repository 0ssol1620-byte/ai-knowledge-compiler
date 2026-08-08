#!/usr/bin/env python3
"""Collect one completed RunPod worker's bounded public-core evidence archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")
_SAFE_MEMBER = re.compile(
    r"^(?:"
    r"worker-state\.jsonl|stall-watchdog\.jsonl|"
    r"(?:parsebench|omnidocbench|olmocr-bench)/(?:"
    r"run-summary\.json|"
    r"repeat-1\.(?:stdout|stderr)\.log|"
    r"straggler-[A-Za-z0-9._-]+\.txt|"
    r"markdown-repeat-1/[A-Za-z0-9._-]+\.md|"
    r"repeat-1/[A-Za-z0-9._-]+/vlm/[A-Za-z0-9._-]+_model\.json"
    r")"
    r")$"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _ssh_base(*, key: Path, known_hosts: Path, port: int) -> list[str]:
    return [
        "ssh",
        "-i",
        str(key),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        # ConnectTimeout only bounds the handshake. A Pod that disappears
        # mid-session — deleted by a cost watchdog, or dropped by the provider
        # proxy — leaves ssh blocked forever without keepalives, which stalled a
        # live audit poll for three hours. These make a dead session fail in
        # about a minute so the caller can observe it.
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=4",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-p",
        str(port),
    ]


def _scp_base(*, key: Path, known_hosts: Path, port: int) -> list[str]:
    return [
        "scp",
        "-i",
        str(key),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        # ConnectTimeout only bounds the handshake. A Pod that disappears
        # mid-session — deleted by a cost watchdog, or dropped by the provider
        # proxy — leaves ssh blocked forever without keepalives, which stalled a
        # live audit poll for three hours. These make a dead session fail in
        # about a minute so the caller can observe it.
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=4",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-P",
        str(port),
    ]


def _normalize_member(name: str) -> str:
    normalized = name.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def validate_archive(archive: Path) -> tuple[str, ...]:
    observed: list[str] = []
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            normalized = _normalize_member(member.name)
            if member.isdir():
                continue
            if not member.isfile() or not _SAFE_MEMBER.fullmatch(normalized):
                raise ValueError(f"unsafe or unexpected worker evidence member: {member.name}")
            observed.append(normalized)
    required = {"worker-state.jsonl", *(f"{suite}/run-summary.json" for suite in SUITES)}
    missing = sorted(required - set(observed))
    if missing:
        raise ValueError(f"worker evidence archive is incomplete: {missing}")
    if len(observed) != len(set(observed)):
        raise ValueError("worker evidence archive contains duplicate members")
    return tuple(sorted(observed))


def collect_worker(
    *,
    worker_index: int,
    host: str,
    port: int,
    key: Path,
    known_hosts: Path,
    output_root: Path,
) -> dict[str, Any]:
    if worker_index not in range(4):
        raise ValueError("worker index must be between 0 and 3")
    if not key.is_file() or not known_hosts.is_file():
        raise FileNotFoundError("SSH identity or known-hosts file is missing")
    worker_name = f"worker-{worker_index:02d}"
    target = output_root / worker_name
    archive = output_root / f"{worker_name}-evidence.tar.gz"
    receipt = output_root / f"{worker_name}-collection-receipt.json"
    for path in (target, archive, receipt):
        if path.exists():
            raise FileExistsError(f"collection target already exists: {path}")
    output_root.mkdir(parents=True, exist_ok=True)

    remote_archive = f"/workspace/folynta/results/{worker_name}-evidence.tar.gz"
    remote_script = f"""set -euo pipefail
root=/workspace/folynta/results/full
test -f "$root/worker-state.jsonl"
for suite in parsebench omnidocbench olmocr-bench; do
  test -f "$root/$suite/run-summary.json"
done
rm -f {remote_archive}
cd "$root"
find . -type f \\
  \\( -path './worker-state.jsonl' \\
     -o -path './stall-watchdog.jsonl' \\
     -o -path './*/run-summary.json' \\
     -o -path './*/repeat-1.stdout.log' \\
     -o -path './*/repeat-1.stderr.log' \\
     -o -path './*/straggler-*.txt' \\
     -o -path './*/markdown-repeat-1/*.md' \\
     -o -path './*/repeat-1/*/vlm/*_model.json' \\) \\
  -print0 | sort -z | tar --null --files-from=- -czf {remote_archive}
sha256sum {remote_archive}
"""
    ssh = _ssh_base(key=key, known_hosts=known_hosts, port=port)
    # The fixed script is passed through stdin to avoid shell interpolation of credentials.
    try:
        remote = subprocess.run(
            [*ssh, f"root@{host}", "bash", "-s"],
            input=remote_script.encode("utf-8"),
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "remote worker evidence archive failed "
            f"(exit={exc.returncode}, stdout={stdout!r}, stderr={stderr!r})"
        ) from exc
    remote_hash = remote.stdout.decode("utf-8", errors="replace").strip().split()[0]
    if not re.fullmatch(r"[0-9a-f]{64}", remote_hash):
        raise ValueError("remote archive SHA-256 receipt is invalid")

    _run(
        [
            *_scp_base(key=key, known_hosts=known_hosts, port=port),
            f"root@{host}:{remote_archive}",
            str(archive),
        ]
    )
    local_hash = sha256_file(archive)
    if local_hash != f"sha256:{remote_hash}":
        raise ValueError("downloaded worker archive hash differs from remote receipt")
    members = validate_archive(archive)
    target.mkdir()
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(target, filter="data")

    summaries: dict[str, dict[str, Any]] = {}
    for suite in SUITES:
        payload = json.loads((target / suite / "run-summary.json").read_text(encoding="utf-8"))
        runs = payload.get("runs", [])
        if len(runs) != 1:
            raise ValueError(f"unexpected repeat count in {suite} worker summary")
        summaries[suite] = {
            "input_count": int(payload["input_count"]),
            "completed": int(runs[0]["completed"]),
            "failed": int(runs[0]["failed"]),
            "run_summary_sha256": sha256_file(target / suite / "run-summary.json"),
        }
    payload = {
        "schema": "folynta.public-core-worker-collection.v1",
        "worker_index": worker_index,
        "archive_sha256": local_hash,
        "archive_bytes": archive.stat().st_size,
        "member_count": len(members),
        "summaries": summaries,
    }
    receipt.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return {**payload, "receipt_sha256": sha256_file(receipt)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-index", required=True, type=int)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--known-hosts", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = collect_worker(
        worker_index=args.worker_index,
        host=args.host,
        port=args.port,
        key=args.key.resolve(),
        known_hosts=args.known_hosts.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["collect_worker", "sha256_file", "validate_archive"]
