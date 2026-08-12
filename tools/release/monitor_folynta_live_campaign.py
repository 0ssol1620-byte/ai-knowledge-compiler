#!/usr/bin/env python3
"""Collect and delete each live RunPod worker as soon as its evidence is complete."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def read_runpod_key(path: Path) -> str:
    pattern = re.compile(r"^\s*Runpod\s*[:=]\s*(.+?)\s*$", re.IGNORECASE)
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.match(line)
        if match and len(match.group(1).strip()) >= 20:
            return match.group(1).strip()
    raise RuntimeError("RunPod credential is missing or malformed")


def provider_delete(pod_id: str, api_key: str) -> None:
    response = httpx.delete(
        f"https://rest.runpod.io/v1/pods/{pod_id}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=30,
    )
    if response.status_code not in {200, 202, 204, 404}:
        raise RuntimeError(f"RunPod delete failed with status {response.status_code}")


def ssh_complete(worker: dict[str, Any], *, key: Path, known_hosts: Path) -> bool:
    root = str(worker["remote_result_root"])
    suites = tuple(worker["suites"])
    checks = "\n".join(f'test -s "$root/{suite}/run-summary.json"' for suite in suites)
    if worker["mode"] == "full":
        checks += '\ntest -f "$root/WORKER_COMPLETE"'
    script = f"""set -euo pipefail
root={root}
{checks}
printf complete
"""
    command = [
        "ssh",
        "-i",
        str(key),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-p",
        str(worker["port"]),
        f"root@{worker['host']}",
        "bash",
        "-s",
    ]
    completed = subprocess.run(  # noqa: S603 - fixed ssh executable and validated config
        command,
        input=script.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    return completed.returncode == 0 and stdout.strip() == "complete"


def ssh_cuda_health(
    worker: dict[str, Any], *, key: Path, known_hosts: Path
) -> tuple[bool, str]:
    """Prove that PyTorch can use the GPU, not merely that nvidia-smi can see it."""
    script = """set -euo pipefail
nvidia-smi --query-gpu=name --format=csv,noheader | head -1
/usr/bin/python3.11 - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("torch-cuda-unavailable")
print(torch.cuda.get_device_name(0))
PY
"""
    command = [
        "ssh",
        "-i",
        str(key),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-p",
        str(worker["port"]),
        f"root@{worker['host']}",
        "bash",
        "-s",
    ]
    completed = subprocess.run(  # noqa: S603 - fixed ssh executable and validated config
        command,
        input=script.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    detail = (stdout + "\n" + stderr).strip()[-1000:]
    return completed.returncode == 0, detail


def validate_receipt(receipt: Path, worker: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(receipt.read_text(encoding="utf-8"))
    if int(value["worker_index"]) != int(worker["worker_index"]):
        raise RuntimeError("collection receipt worker index differs")
    expected = {str(key): int(count) for key, count in worker["suites"].items()}
    raw_summaries = value["summaries"]
    if isinstance(raw_summaries, dict):
        summaries = {str(suite): summary for suite, summary in raw_summaries.items()}
    else:
        summaries = {
            str(item["benchmark_id"]): item for item in raw_summaries
        }
    if set(summaries) != set(expected):
        raise RuntimeError("collection receipt suite coverage differs")
    for suite, count in expected.items():
        summary = summaries[suite]
        if int(summary["input_count"]) != count:
            raise RuntimeError(f"{suite} input count differs")
        if int(summary["completed"]) + int(summary["failed"]) != count:
            raise RuntimeError(f"{suite} terminal accounting differs")
    return value


def read_deleted_workers(progress: Path) -> set[tuple[int, str]]:
    """Recover durable completion state after a controller restart."""
    deleted: set[tuple[int, str]] = set()
    if not progress.exists():
        return deleted
    for line in progress.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if event.get("event") != "worker_pod_deleted":
            continue
        deleted.add((int(event["worker_index"]), str(event["pod_id"])))
    return deleted


def collect_worker(
    worker: dict[str, Any],
    *,
    repository: Path,
    key: Path,
    known_hosts: Path,
) -> tuple[Path, dict[str, Any]]:
    index = int(worker["worker_index"])
    output_root = repository / str(worker["collection_root"])
    output_root.mkdir(parents=True, exist_ok=True)
    if worker["mode"] == "full":
        receipt = output_root / f"worker-{index:02d}-collection-receipt.json"
        collector = repository / "benchmark/runpod_eval/collect_public_core_worker.py"
        args = [
            sys.executable,
            str(collector),
            "--worker-index",
            str(index),
            "--host",
            str(worker["host"]),
            "--port",
            str(worker["port"]),
            "--key",
            str(key),
            "--known-hosts",
            str(known_hosts),
            "--output-root",
            str(output_root),
        ]
    else:
        receipt = output_root / f"worker-{index:02d}-operational-retry-collection.json"
        collector = repository / "benchmark/runpod_eval/collect_operational_retry_worker.py"
        args = [
            sys.executable,
            str(collector),
            "--worker-index",
            str(index),
            "--host",
            str(worker["host"]),
            "--port",
            str(worker["port"]),
            "--key",
            str(key),
            "--known-hosts",
            str(known_hosts),
            "--output-root",
            str(output_root),
        ]
        for suite in worker["suites"]:
            args.extend(("--suite", suite))
    if not receipt.exists():
        subprocess.run(  # noqa: S603 - fixed Python executable and repository collectors
            args, cwd=repository, check=True
        )
    return receipt, validate_receipt(receipt, worker)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=int, default=60)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 30 <= args.poll_seconds <= 300:
        raise ValueError("poll-seconds must be between 30 and 300")
    repository = args.repository_root.resolve()
    config = json.loads(args.config.resolve().read_text(encoding="utf-8"))
    key = (repository / config["key"]).resolve()
    known_hosts = (repository / config["known_hosts"]).resolve()
    progress = (repository / config["progress_log"]).resolve()
    terminal = (repository / config["terminal_receipt"]).resolve()
    api_key = read_runpod_key(args.credential_file.resolve())
    deleted_workers = read_deleted_workers(progress)
    pending = {
        int(worker["worker_index"]): worker
        for worker in config["workers"]
        if (int(worker["worker_index"]), str(worker["pod_id"]))
        not in deleted_workers
    }
    append_jsonl(progress, {"event": "monitor_started", "observed_at_utc": utc_now()})
    for index, worker in sorted(pending.items()):
        healthy, detail = ssh_cuda_health(worker, key=key, known_hosts=known_hosts)
        append_jsonl(
            progress,
            {
                "event": (
                    "worker_cuda_health_verified"
                    if healthy
                    else "worker_cuda_health_fault"
                ),
                "worker_index": index,
                "pod_id": worker["pod_id"],
                "detail": detail,
                "observed_at_utc": utc_now(),
            },
        )
    while pending:
        for index, worker in tuple(pending.items()):
            try:
                if not ssh_complete(worker, key=key, known_hosts=known_hosts):
                    continue
                append_jsonl(
                    progress,
                    {
                        "event": "worker_terminal_observed",
                        "worker_index": index,
                        "observed_at_utc": utc_now(),
                    },
                )
                receipt_path, receipt = collect_worker(
                    worker, repository=repository, key=key, known_hosts=known_hosts
                )
                append_jsonl(
                    progress,
                    {
                        "event": "worker_collection_verified",
                        "worker_index": index,
                        "collection_receipt": str(receipt_path),
                        "archive_sha256": receipt["archive_sha256"],
                        "observed_at_utc": utc_now(),
                    },
                )
                provider_delete(str(worker["pod_id"]), api_key)
                append_jsonl(
                    progress,
                    {
                        "event": "worker_pod_deleted",
                        "worker_index": index,
                        "pod_id": worker["pod_id"],
                        "observed_at_utc": utc_now(),
                    },
                )
                del pending[index]
            except Exception as exc:  # keep monitoring other workers; record bounded error text
                append_jsonl(
                    progress,
                    {
                        "event": "worker_monitor_error",
                        "worker_index": index,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                        "observed_at_utc": utc_now(),
                    },
                )
        if pending:
            append_jsonl(
                progress,
                {
                    "event": "poll",
                    "pending_worker_indices": sorted(pending),
                    "observed_at_utc": utc_now(),
                },
            )
            time.sleep(args.poll_seconds)
    result = {
        "schema": "folynta.live-campaign-monitor-terminal.v1",
        "status": "all_workers_collected_and_deleted",
        "worker_indices": sorted(int(worker["worker_index"]) for worker in config["workers"]),
        "completed_at_utc": utc_now(),
    }
    terminal.parent.mkdir(parents=True, exist_ok=True)
    terminal.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    append_jsonl(progress, {"event": "monitor_completed", "observed_at_utc": utc_now()})
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
