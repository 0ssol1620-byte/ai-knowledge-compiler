#!/usr/bin/env python3
"""Collect a bounded different-worker operational retry result archive."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from collect_public_core_worker import (
    _run,
    _scp_base,
    _ssh_base,
    sha256_file,
)

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")
_SAFE_MEMBER = re.compile(
    r"^(?:worker-state\.jsonl|stall-watchdog\.jsonl|"
    r"(?:parsebench|omnidocbench|olmocr-bench)\.runner\.log|"
    r"(?:parsebench|omnidocbench|olmocr-bench)/(?:"
    r"run-summary\.json|repeat-1\.(?:stdout|stderr)\.log|"
    r"markdown-repeat-1/[A-Za-z0-9._-]+\.md|"
    r"repeat-1/[A-Za-z0-9._-]+/vlm/[A-Za-z0-9._-]+_model\.json))$"
)


def _validate_archive(archive: Path, required_suites: tuple[str, ...]) -> tuple[str, ...]:
    observed: list[str] = []
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            name = member.name.replace("\\", "/").removeprefix("./")
            if member.isdir():
                continue
            if not member.isfile() or not _SAFE_MEMBER.fullmatch(name):
                raise ValueError(f"unexpected operational retry evidence member: {member.name}")
            observed.append(name)
    required = {"worker-state.jsonl", *(f"{suite}/run-summary.json" for suite in required_suites)}
    missing = sorted(required - set(observed))
    if missing:
        raise ValueError(f"operational retry evidence is incomplete: {missing}")
    if len(observed) != len(set(observed)):
        raise ValueError("operational retry evidence contains duplicate members")
    return tuple(sorted(observed))


def collect_retry_worker(
    *,
    worker_index: int,
    host: str,
    port: int,
    key: Path,
    known_hosts: Path,
    required_suites: tuple[str, ...],
    output_root: Path,
) -> dict[str, Any]:
    suites = tuple(dict.fromkeys(required_suites))
    if not 0 <= worker_index <= 99 or not suites or any(suite not in SUITES for suite in suites):
        raise ValueError("retry worker index or required suites are invalid")
    worker_name = f"worker-{worker_index:02d}"
    target = output_root / worker_name
    archive = output_root / f"{worker_name}-operational-retry-evidence.tar.gz"
    receipt = output_root / f"{worker_name}-operational-retry-collection.json"
    for path in (target, archive, receipt):
        if path.exists():
            raise FileExistsError(f"retry collection target already exists: {path}")
    output_root.mkdir(parents=True, exist_ok=True)
    remote_root = "/workspace/folynta/results/operational-retry"
    remote_archive = f"/workspace/folynta/results/{worker_name}-operational-retry.tar.gz"
    suite_checks = "\n".join(f'test -f "$root/{suite}/run-summary.json"' for suite in suites)
    remote_script = f"""set -euo pipefail
root={remote_root}
test -f "$root/worker-state.jsonl"
{suite_checks}
rm -f {remote_archive}
cd "$root"
find . -type f \\
  \\( -path './worker-state.jsonl' \\
     -o -path './stall-watchdog.jsonl' \\
     -o -path './*.runner.log' \\
     -o -path './*/run-summary.json' \\
     -o -path './*/repeat-1.stdout.log' \\
     -o -path './*/repeat-1.stderr.log' \\
     -o -path './*/markdown-repeat-1/*.md' \\
     -o -path './*/repeat-1/*/vlm/*_model.json' \\) \\
  -print0 | sort -z | tar --null --files-from=- -czf {remote_archive}
sha256sum {remote_archive}
"""
    ssh = _ssh_base(key=key, known_hosts=known_hosts, port=port)
    remote = subprocess.run(
        [*ssh, f"root@{host}", "bash", "-s"],
        input=remote_script.encode("utf-8"),
        check=True,
        capture_output=True,
    )
    remote_hash = remote.stdout.decode("utf-8", errors="replace").strip().split()[0]
    if not re.fullmatch(r"[0-9a-f]{64}", remote_hash):
        raise ValueError("remote retry archive hash is invalid")
    _run(
        [
            *_scp_base(key=key, known_hosts=known_hosts, port=port),
            f"root@{host}:{remote_archive}",
            str(archive),
        ]
    )
    archive_sha256 = sha256_file(archive)
    if archive_sha256 != f"sha256:{remote_hash}":
        raise ValueError("downloaded retry archive differs from the remote hash")
    members = _validate_archive(archive, suites)
    target.mkdir()
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(target, filter="data")
    summaries: list[dict[str, Any]] = []
    for suite in suites:
        path = target / suite / "run-summary.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        run = payload["runs"][0]
        summaries.append(
            {
                "benchmark_id": suite,
                "input_count": int(payload["input_count"]),
                "completed": int(run["completed"]),
                "failed": int(run["failed"]),
                "run_summary_sha256": sha256_file(path),
            }
        )
    result = {
        "schema": "folynta.operational-retry-worker-collection.v1",
        "worker_index": worker_index,
        "archive_sha256": archive_sha256,
        "archive_bytes": archive.stat().st_size,
        "member_count": len(members),
        "summaries": summaries,
    }
    receipt.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return {**result, "receipt_sha256": sha256_file(receipt)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-index", type=int, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--known-hosts", type=Path, required=True)
    parser.add_argument("--suite", action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = collect_retry_worker(
        worker_index=args.worker_index,
        host=args.host,
        port=args.port,
        key=args.key.resolve(),
        known_hosts=args.known_hosts.resolve(),
        required_suites=tuple(args.suite),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["collect_retry_worker"]
