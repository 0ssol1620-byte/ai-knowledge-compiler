#!/usr/bin/env python3
"""Collect one dedicated PaddleOCR-VL or DeepSeek-OCR-2 recovery campaign."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from collect_public_core_worker import _scp_base, _ssh_base, sha256_file
from launch_dedicated_recovery import MODELS

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")
_SAFE_MEMBER = re.compile(
    r"^(?:campaign-state\.jsonl|worker-0[0-3]/(?:"
    r"(?:parsebench|omnidocbench|olmocr-bench)\.runner\.(?:stdout|stderr)\.log|"
    r"(?:parsebench|omnidocbench|olmocr-bench)/(?:"
    r"run-summary\.json|markdown-repeat-1/[A-Za-z0-9._-]+\.md|"
    r"repeat-1/[A-Za-z0-9._-]+\.json|"
    r"repeat-1/[A-Za-z0-9._-]+/(?:isolated-case-(?:spec|response)\.json|"
    r"child\.(?:stdout|stderr)\.log)"
    r")"
    r"))$"
)


def _with_frozen_kex(command: list[str]) -> list[str]:
    return [*command[:-2], "-o", "KexAlgorithms=curve25519-sha256", *command[-2:]]


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
                raise ValueError(f"unsafe dedicated recovery member: {member.name}")
            observed.append(normalized)
    if "campaign-state.jsonl" not in observed or len(observed) != len(set(observed)):
        raise ValueError("dedicated recovery archive coverage is invalid")
    return tuple(sorted(observed))


def collect_dedicated_recovery(
    *,
    model: str,
    host: str,
    port: int,
    key: Path,
    known_hosts: Path,
    launch_receipt: Path,
    output_root: Path,
) -> dict[str, Any]:
    if model not in MODELS:
        raise ValueError("unsupported dedicated recovery model")
    launch = json.loads(launch_receipt.read_text(encoding="utf-8"))
    if (
        launch.get("schema") != "folynta.dedicated-recovery-launch.v1"
        or launch.get("model") != model
        or launch.get("different_physical_pod_verified") is not True
    ):
        raise ValueError("dedicated recovery launch identity is invalid")
    if output_root.exists():
        raise FileExistsError(f"dedicated recovery collection exists: {output_root}")
    slug = "paddle" if model == "paddleocr-vl-1.6" else "deepseek"
    remote_root = f"/workspace/folynta/results/{slug}-r1"
    remote_archive = f"/workspace/folynta/results/{slug}-r1-evidence.tar.gz"
    required = []
    for package in launch.get("packages", []):
        worker = int(package["recovery_worker_index"])
        for suite in package.get("suites", []):
            if worker not in range(4) or suite not in SUITES:
                raise ValueError("dedicated recovery launch route is invalid")
            required.append((worker, str(suite)))
    if not required:
        raise ValueError("dedicated recovery launch has no routed suites")
    checks = "\n".join(
        f'test -f "$root/worker-{worker:02d}/{suite}/run-summary.json"'
        for worker, suite in required
    )
    remote_script = rf"""set -euo pipefail
root='{remote_root}'
test -f "$root/campaign-state.jsonl"
tail -1 "$root/campaign-state.jsonl" | grep -F '"event":"dedicated_recovery_completed"' >/dev/null
{checks}
rm -f '{remote_archive}'
cd "$root"
find . -type f \( \
  -path './campaign-state.jsonl' -o \
  -path './worker-??/*.runner.stdout.log' -o \
  -path './worker-??/*.runner.stderr.log' -o \
  -path './worker-??/*/run-summary.json' -o \
  -path './worker-??/*/markdown-repeat-1/*.md' -o \
  -path './worker-??/*/repeat-1/*.json' -o \
  -path './worker-??/*/repeat-1/*/isolated-case-spec.json' -o \
  -path './worker-??/*/repeat-1/*/isolated-case-response.json' -o \
  -path './worker-??/*/repeat-1/*/child.stdout.log' -o \
  -path './worker-??/*/repeat-1/*/child.stderr.log' \
\) -print0 | sort -z | tar --null --files-from=- -czf '{remote_archive}'
sha256sum '{remote_archive}'
"""
    ssh = _with_frozen_kex(_ssh_base(key=key, known_hosts=known_hosts, port=port))
    remote = subprocess.run(
        [*ssh, f"root@{host}", "bash", "-s"],
        input=remote_script.encode("utf-8"),
        check=False,
        capture_output=True,
    )
    if remote.returncode != 0:
        stdout = remote.stdout.decode("utf-8", errors="replace").strip()
        stderr = remote.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "dedicated recovery remote archive failed "
            f"(exit={remote.returncode}, stdout={stdout!r}, stderr={stderr!r})"
        )
    remote_hash = remote.stdout.decode("utf-8", errors="replace").strip().split()[0]
    if not re.fullmatch(r"[0-9a-f]{64}", remote_hash):
        raise ValueError("dedicated recovery remote archive hash is invalid")
    output_root.mkdir(parents=True)
    archive = output_root / f"{slug}-r1-evidence.tar.gz"
    scp = _with_frozen_kex(_scp_base(key=key, known_hosts=known_hosts, port=port))
    subprocess.run(
        [*scp, f"root@{host}:{remote_archive}", str(archive)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if sha256_file(archive) != f"sha256:{remote_hash}":
        raise ValueError("dedicated recovery archive changed during download")
    members = validate_archive(archive)
    evidence_root = output_root / "evidence"
    evidence_root.mkdir()
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(evidence_root, filter="data")
    expected_candidate = (
        "paddleocr-vl-1.6" if model == "paddleocr-vl-1.6" else "deepseek-ocr-2-3b-transformers"
    )
    summaries: list[dict[str, Any]] = []
    total_inputs = 0
    for worker, suite in sorted(set(required)):
        path = evidence_root / f"worker-{worker:02d}" / suite / "run-summary.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        runs = payload.get("runs", [])
        if (
            payload.get("candidate_id") != expected_candidate
            or payload.get("ground_truth_mounted") is not False
            or payload.get("evidence_class") != "public-core-shard"
            or len(runs) != 1
            or int(runs[0].get("repeat_index", -1)) != 1
        ):
            raise ValueError(f"dedicated recovery summary identity mismatch: {path}")
        total_inputs += int(payload["input_count"])
        summaries.append(
            {
                "recovery_worker_index": worker,
                "benchmark_id": suite,
                "input_count": int(payload["input_count"]),
                "completed": int(runs[0]["completed"]),
                "failed": int(runs[0]["failed"]),
                "run_summary_sha256": sha256_file(path),
            }
        )
    if total_inputs != int(launch["input_count"]):
        raise ValueError("dedicated recovery collected input coverage is incomplete")
    receipt: dict[str, Any] = {
        "schema": "folynta.dedicated-recovery-collection.v1",
        "model": model,
        "dedicated_pod_id": str(launch["dedicated_pod_id"]),
        "different_physical_pod_verified": True,
        "launch_receipt_sha256": sha256_file(launch_receipt),
        "archive_sha256": sha256_file(archive),
        "archive_bytes": archive.stat().st_size,
        "member_count": len(members),
        "input_count": total_inputs,
        "summaries": summaries,
    }
    receipt_path = output_root / "collection-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return {**receipt, "receipt_sha256": sha256_file(receipt_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--known-hosts", type=Path, required=True)
    parser.add_argument("--launch-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = collect_dedicated_recovery(
        model=args.model,
        host=args.host,
        port=args.port,
        key=args.key.resolve(),
        known_hosts=args.known_hosts.resolve(),
        launch_receipt=args.launch_receipt.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["collect_dedicated_recovery", "validate_archive"]
