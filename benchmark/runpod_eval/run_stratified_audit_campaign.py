#!/usr/bin/env python3
"""Run the frozen 128-per-suite, three-repeat MinerU audit on healthy Pods."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from collect_public_core_worker import _scp_base, _ssh_base, sha256_file

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")
_SAFE_MEMBER = re.compile(
    r"^(?:run-summary\.json|repeat-[123]\.(?:stdout|stderr)\.log|"
    r"markdown-repeat-[123]/[A-Za-z0-9._-]+\.md|"
    r"repeat-[123]/[A-Za-z0-9._-]+/vlm/[A-Za-z0-9._-]+_model\.json)$"
)


def _load(path: Path) -> dict[str, Any]:
    # The release controllers are Windows PowerShell, whose Set-Content -Encoding
    # utf8 prepends a BOM. Reading those receipts as strict utf-8 makes json
    # reject the very first character, so the pool worker config could never be
    # loaded. utf-8-sig strips a BOM when present and is identical otherwise.
    return json.loads(path.read_text(encoding="utf-8-sig"))


# Bounds for remote calls. The transfers move hundreds of megabytes; the
# probes are one-line shell tests.
POLL_COMMAND_TIMEOUT_SECONDS = 120
REMOTE_COMMAND_TIMEOUT_SECONDS = 900
TRANSFER_TIMEOUT_SECONDS = 3600


def _with_kex(command: list[str]) -> list[str]:
    return [*command[:-2], "-o", "KexAlgorithms=curve25519-sha256", *command[-2:]]


def _event(path: Path, event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        **fields,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _validate_archive(path: Path) -> tuple[str, ...]:
    members: list[str] = []
    with tarfile.open(path, "r:gz") as bundle:
        for member in bundle.getmembers():
            name = member.name.replace("\\", "/").removeprefix("./")
            if member.isdir():
                continue
            if not member.isfile() or _SAFE_MEMBER.fullmatch(name) is None:
                raise ValueError(f"unsafe stratified audit evidence member: {member.name}")
            members.append(name)
    if "run-summary.json" not in members or len(members) != len(set(members)):
        raise ValueError("stratified audit archive coverage is invalid")
    return tuple(sorted(members))


def _eligible_audit_workers(
    config: dict[str, Any], health: dict[str, Any]
) -> tuple[int, ...]:
    endpoints = {int(item["worker_index"]) for item in config.get("workers", [])}
    eligible_primary = {
        int(value) for value in health.get("eligible_retry_workers", [])
    }
    quarantined = {
        int(value) for value in health.get("quarantined_worker_indices", [])
    }
    if (
        eligible_primary | quarantined != set(range(4))
        or eligible_primary & quarantined
    ):
        raise ValueError("stratified audit worker health does not partition primaries")
    # Primary Pods may already have been collected and deleted by the live
    # monitor. Only endpoints in the current revalidated pool are eligible;
    # the health receipt still has to partition all four primaries.
    available_primary = eligible_primary & endpoints
    expansion = {worker for worker in endpoints if worker >= 4}
    eligible = tuple(sorted(available_primary | expansion))
    if len(eligible) < 3:
        raise ValueError("stratified audit requires three eligible MinerU Pods")
    return eligible


def run_audit_campaign(
    *,
    repository_root: Path,
    config_path: Path,
    worker_health: Path,
    package_receipt: Path,
    package_root: Path,
    mineru_runner: Path,
    audit_runner: Path,
    input_contract: Path,
    output_root: Path,
    deadline_unix: float,
    poll_seconds: int,
    resume: bool = False,
) -> dict[str, Any]:
    # The remote runners are detached, so they survive a coordinator that dies
    # or is restarted. Resuming rebuilds the launch state from the progress log
    # instead of re-uploading and re-running suites that are already inferring.
    resuming = resume and output_root.exists()
    if output_root.exists() and not resuming:
        raise FileExistsError(f"stratified audit output exists: {output_root}")
    output_root.mkdir(parents=True, exist_ok=resuming)
    progress = output_root / "progress.jsonl"
    config = _load(config_path)
    health = _load(worker_health)
    packages = _load(package_receipt)
    if (
        health.get("schema") != "folynta.public-core-operational-worker-health.v1"
        or packages.get("schema") != "folynta.public-core-stratified-audit-packages.v1"
        or int(packages.get("input_count", -1)) != 384
        or int(packages.get("package_count", -1)) != 3
    ):
        raise ValueError("stratified audit campaign input identity is invalid")
    eligible = _eligible_audit_workers(config, health)
    endpoints = {int(item["worker_index"]): item for item in config["workers"]}
    key = (repository_root / str(config["key"])).resolve()
    known_hosts = (repository_root / str(config["known_hosts"])).resolve()
    for path in (key, known_hosts, mineru_runner, audit_runner, input_contract):
        if not path.is_file():
            raise FileNotFoundError(path)
    package_by_suite = {str(item["benchmark_id"]): item for item in packages["packages"]}
    if set(package_by_suite) != set(SUITES):
        raise ValueError("stratified audit package suite coverage is invalid")

    launches: list[dict[str, Any]] = []
    if resuming:
        for line in progress.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("event") == "audit_suite_launched":
                launches = [
                    item for item in launches
                    if item["benchmark_id"] != record["benchmark_id"]
                ]
                launches.append(
                    {key: value for key, value in record.items()
                     if key not in {"event", "observed_at_utc"}}
                )
        if {str(item["benchmark_id"]) for item in launches} != set(SUITES):
            raise ValueError("resume cannot rebuild every launched suite")
        _event(progress, "audit_campaign_resumed", suite_count=len(launches))
    for suite, worker in ([] if resuming else zip(SUITES, sorted(eligible)[:3], strict=True)):
        endpoint = endpoints[worker]
        item = package_by_suite[suite]
        archive = package_root / str(item["archive"])
        if (
            not archive.is_file()
            or archive.stat().st_size != int(item["archive_bytes"])
            or sha256_file(archive) != str(item["archive_sha256"])
        ):
            raise ValueError(f"stratified audit package binding mismatch: {suite}")
        host = str(endpoint["host"])
        port = int(endpoint["port"])
        target = f"root@{host}"
        scp = _with_kex(_scp_base(key=key, known_hosts=known_hosts, port=port))
        for source, destination in (
            (archive, "/workspace/folynta/"),
            (mineru_runner, "/workspace/folynta/runner/mineru_stage2.py"),
            (audit_runner, "/workspace/folynta/runner/remote_run_stratified_audit.sh"),
            (input_contract, "/workspace/folynta/runner/input_contract.py"),
        ):
            subprocess.run(
                [*scp, str(source), f"{target}:{destination}"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        raw_hash = str(item["archive_sha256"]).removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
            raise ValueError("stratified audit package hash is invalid")
        input_root = "/workspace/folynta/stratified-audit-r1"
        result_root = f"/workspace/folynta/results/stratified-audit-r1/{suite}"
        remote = f"""set -euo pipefail
if pgrep -f '/workspace/folynta/runner/remote_run_.*retry' >/dev/null; then
  echo 'another MinerU recovery runner is active' >&2
  exit 30
fi
if pgrep -f '/workspace/folynta/runner/mineru_stage2.py' >/dev/null; then
  echo 'another MinerU inference runner is active' >&2
  exit 30
fi
test ! -e '{input_root}/{suite}'
test ! -e '{result_root}'
mkdir -p '{input_root}' /workspace/folynta/results/stratified-audit-r1
printf '%s  %s\n' '{raw_hash}' '/workspace/folynta/{archive.name}' | sha256sum -c - >/dev/null
tar --no-same-owner -xzf '/workspace/folynta/{archive.name}' -C '{input_root}'
chmod 700 /workspace/folynta/runner/remote_run_stratified_audit.sh
nohup bash /workspace/folynta/runner/remote_run_stratified_audit.sh \
  '{suite}' '{input_root}' '{result_root}' \
  >'{result_root}.launcher.stdout.log' \
  2>'{result_root}.launcher.stderr.log' < /dev/null &
printf '%s\n' "$!"
"""
        ssh = _with_kex(_ssh_base(key=key, known_hosts=known_hosts, port=port))
        launched = subprocess.run(
            [*ssh, target, "bash", "-s"],
            input=remote.encode("utf-8"),
            check=True,
            capture_output=True,
        )
        pid = launched.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]
        if not re.fullmatch(r"[1-9][0-9]*", pid):
            raise ValueError(f"stratified audit launch did not return a PID: {suite}")
        launches.append(
            {
                "benchmark_id": suite,
                "worker_index": worker,
                "host": host,
                "port": port,
                "runner_pid": int(pid),
                "archive_sha256": str(item["archive_sha256"]),
            }
        )
        _event(progress, "audit_suite_launched", **launches[-1])

    pending = {str(item["benchmark_id"]): item for item in launches}
    while pending:
        if time.time() >= deadline_unix:
            raise TimeoutError("stratified audit campaign deadline reached")
        for suite, item in list(pending.items()):
            ssh = _with_kex(
                _ssh_base(key=key, known_hosts=known_hosts, port=int(item["port"]))
            )
            result_root = f"/workspace/folynta/results/stratified-audit-r1/{suite}"
            command = (
                f"if test -f '{result_root}/run-summary.json'; then echo COMPLETE; "
                f"elif kill -0 {int(item['runner_pid'])} 2>/dev/null; then echo RUNNING; "
                "else echo FAILED; fi"
            )
            # SSH keepalives end a session whose peer has died, but a session
            # that wedges while the peer still answers leaves subprocess.run
            # waiting forever. A trivial status probe once blocked for fifty-one
            # minutes while all three Pods were healthily inferring, so the poll
            # is bounded and a miss is survivable: the remote runners are
            # detached and keep working, and the next cycle re-reads their state.
            try:
                status = subprocess.run(
                    [*ssh, f"root@{item['host']}", command],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=POLL_COMMAND_TIMEOUT_SECONDS,
                ).stdout.strip()
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                _event(
                    progress,
                    "audit_suite_poll_unavailable",
                    benchmark_id=suite,
                    error_type=type(exc).__name__,
                )
                continue
            _event(progress, "audit_suite_poll", benchmark_id=suite, status=status)
            if status == "COMPLETE":
                del pending[suite]
            elif status == "FAILED":
                raise RuntimeError(f"stratified audit suite failed: {suite}")
        if pending:
            time.sleep(poll_seconds)

    collections: list[dict[str, Any]] = []
    for item in launches:
        suite = str(item["benchmark_id"])
        host = str(item["host"])
        port = int(item["port"])
        root = f"/workspace/folynta/results/stratified-audit-r1/{suite}"
        remote_archive = f"{root}-evidence.tar.gz"
        remote = rf"""set -euo pipefail
cd '{root}'
find . -type f \( \
  -path './run-summary.json' -o \
  -path './repeat-[123].stdout.log' -o \
  -path './repeat-[123].stderr.log' -o \
  -path './markdown-repeat-[123]/*.md' -o \
  -path './repeat-[123]/*/vlm/*_model.json' \
\) -print0 | sort -z | tar --null --files-from=- -czf '{remote_archive}'
sha256sum '{remote_archive}'
"""
        ssh = _with_kex(_ssh_base(key=key, known_hosts=known_hosts, port=port))
        result = subprocess.run(
            [*ssh, f"root@{host}", "bash", "-s"],
            input=remote.encode("utf-8"),
            check=True,
            capture_output=True,
        )
        remote_hash = result.stdout.decode("utf-8", errors="replace").strip().split()[0]
        if not re.fullmatch(r"[0-9a-f]{64}", remote_hash):
            raise ValueError("stratified audit remote archive hash is invalid")
        archive = output_root / f"{suite}-evidence.tar.gz"
        scp = _with_kex(_scp_base(key=key, known_hosts=known_hosts, port=port))
        subprocess.run(
            [*scp, f"root@{host}:{remote_archive}", str(archive)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if sha256_file(archive) != f"sha256:{remote_hash}":
            raise ValueError("stratified audit archive changed during download")
        members = _validate_archive(archive)
        suite_root = output_root / suite
        suite_root.mkdir()
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(suite_root, filter="data")
        summary = _load(suite_root / "run-summary.json")
        runs = summary.get("runs", [])
        if (
            summary.get("candidate_id") != "mineru-3.4.4-vlm"
            or summary.get("evidence_class") != "stratified-audit"
            or summary.get("ground_truth_mounted") is not False
            or int(summary.get("input_count", -1)) != 128
            or [int(run["repeat_index"]) for run in runs] != [1, 2, 3]
        ):
            raise ValueError(f"stratified audit summary identity mismatch: {suite}")
        collections.append(
            {
                **item,
                "archive_sha256": sha256_file(archive),
                "member_count": len(members),
                "completed_by_repeat": [int(run["completed"]) for run in runs],
                "failed_by_repeat": [int(run["failed"]) for run in runs],
                "run_summary_sha256": sha256_file(suite_root / "run-summary.json"),
            }
        )
        _event(progress, "audit_suite_collected", benchmark_id=suite)
    receipt = {
        "schema": "folynta.public-core-stratified-audit-campaign.v1",
        "suite_count": 3,
        "input_count_per_repeat": 384,
        "repeat_count": 3,
        "inference_count": 1152,
        "different_pods_by_suite": len({item["worker_index"] for item in launches}) == 3,
        "collections": collections,
    }
    receipt_path = output_root / "terminal-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    _event(progress, "stratified_audit_collected")
    return {**receipt, "receipt_sha256": sha256_file(receipt_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--worker-health", type=Path, required=True)
    parser.add_argument("--package-receipt", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--mineru-runner", type=Path, required=True)
    parser.add_argument("--audit-runner", type=Path, required=True)
    parser.add_argument("--input-contract", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--deadline-unix", type=float, required=True)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="rebuild launch state from an existing progress log instead of relaunching",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_audit_campaign(
        repository_root=args.repository_root.resolve(),
        config_path=args.config.resolve(),
        worker_health=args.worker_health.resolve(),
        package_receipt=args.package_receipt.resolve(),
        package_root=args.package_root.resolve(),
        mineru_runner=args.mineru_runner.resolve(),
        audit_runner=args.audit_runner.resolve(),
        input_contract=args.input_contract.resolve(),
        output_root=args.output_root.resolve(),
        deadline_unix=args.deadline_unix,
        poll_seconds=args.poll_seconds,
        resume=args.resume,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["_eligible_audit_workers", "run_audit_campaign"]
