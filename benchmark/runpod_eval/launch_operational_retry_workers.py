#!/usr/bin/env python3
"""Upload and launch provenance-bound different-Pod operational retries."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from collect_public_core_worker import _scp_base, _ssh_base, sha256_file

_PACKAGE_NAME = re.compile(r"^worker-([0-9]{2})-operational-retry-inputs\.tar\.gz$")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _worker_lookup(config: dict[str, Any]) -> dict[int, dict[str, Any]]:
    workers: dict[int, dict[str, Any]] = {}
    for worker in config.get("workers", []):
        index = int(worker["worker_index"])
        if index in workers or not 0 <= index <= 99:
            raise ValueError("RunPod worker config contains an invalid or duplicate index")
        host = str(worker["host"])
        port = int(worker["port"])
        if not host or not 0 < port < 65536:
            raise ValueError("RunPod worker config contains an invalid endpoint")
        workers[index] = {"host": host, "port": port}
    if not {0, 1, 2, 3}.issubset(workers):
        raise ValueError("RunPod worker config must include primary indices 0 through 3")
    return workers


def validate_packages(
    *,
    package_receipt: Path,
    package_root: Path,
) -> tuple[dict[str, Any], ...]:
    receipt = _load(package_receipt)
    if receipt.get("schema") != "folynta.public-core-operational-retry-packages.v1":
        raise ValueError("operational retry package receipt schema is invalid")
    packages = receipt.get("packages", [])
    if int(receipt.get("package_count", -1)) != len(packages):
        raise ValueError("operational retry package receipt count is invalid")
    observed_indices: set[int] = set()
    observed_inputs = 0
    validated: list[dict[str, Any]] = []
    for package in packages:
        index = int(package["retry_worker_index"])
        name = str(package["archive"])
        match = _PACKAGE_NAME.fullmatch(name)
        if (
            index in observed_indices
            or not 0 <= index <= 99
            or match is None
            or int(match.group(1)) != index
        ):
            raise ValueError("operational retry package route is invalid")
        archive = package_root / name
        if not archive.is_file() or archive.stat().st_size != int(package["archive_bytes"]):
            raise ValueError(f"operational retry archive size is invalid: {archive}")
        if sha256_file(archive) != str(package["archive_sha256"]):
            raise ValueError(f"operational retry archive hash is invalid: {archive}")
        input_count = int(package["input_count"])
        if input_count < 1:
            raise ValueError("operational retry package cannot be empty")
        observed_indices.add(index)
        observed_inputs += input_count
        validated.append(
            {
                "worker_index": index,
                "archive": archive,
                "archive_sha256": str(package["archive_sha256"]),
                "input_count": input_count,
            }
        )
    if observed_inputs != int(receipt.get("input_count", -1)):
        raise ValueError("operational retry package input coverage is invalid")
    return tuple(sorted(validated, key=lambda item: int(item["worker_index"])))


def validate_preexisting_launch(
    *,
    preexisting_launch_receipt: Path,
    preexisting_retry_plan: Path,
    final_retry_plan: Path,
    packages: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    launch = _load(preexisting_launch_receipt)
    early_plan = _load(preexisting_retry_plan)
    final_plan = _load(final_retry_plan)
    if launch.get("schema") != "folynta.operational-retry-launch.v1":
        raise ValueError("preexisting retry launch schema is invalid")
    if early_plan.get("schema") != "folynta.public-core-operational-retry-plan.v1":
        raise ValueError("preexisting retry plan schema is invalid")
    if final_plan.get("schema") != "folynta.public-core-operational-retry-plan.v1":
        raise ValueError("final retry plan schema is invalid")

    launches = launch.get("launches", [])
    launch_by_worker: dict[int, dict[str, Any]] = {}
    for item in launches:
        worker = int(item["worker_index"])
        if worker in launch_by_worker:
            raise ValueError("preexisting retry launch has duplicate workers")
        launch_by_worker[worker] = item
    if int(launch.get("worker_count", -1)) != len(launch_by_worker):
        raise ValueError("preexisting retry launch worker count is invalid")

    def case_key(item: dict[str, Any]) -> tuple[str, str, int, int]:
        return (
            str(item["benchmark_id"]),
            str(item["case_id"]),
            int(item["primary_worker_index"]),
            int(item["retry_worker_index"]),
        )

    early_cases = {case_key(item) for item in early_plan.get("failures", [])}
    early_workers = {key[3] for key in early_cases}
    if early_workers != set(launch_by_worker):
        raise ValueError("preexisting launch does not exactly cover its retry plan")
    final_cases = {
        case_key(item)
        for item in final_plan.get("failures", [])
        if int(item["retry_worker_index"]) in early_workers
    }
    if early_cases != final_cases:
        raise ValueError("preexisting retry routes differ from the final frozen plan")

    package_by_worker = {int(item["worker_index"]): item for item in packages}
    reused: list[dict[str, Any]] = []
    for worker, item in sorted(launch_by_worker.items()):
        planned_count = sum(key[3] == worker for key in early_cases)
        package = package_by_worker.get(worker)
        if (
            package is None
            or int(item.get("input_count", -1)) != planned_count
            or int(package["input_count"]) != planned_count
        ):
            raise ValueError("preexisting retry launch input coverage is invalid")
        reused.append(
            {
                **item,
                "prefetch_reused": True,
                "prefetch_launch_receipt_sha256": sha256_file(
                    preexisting_launch_receipt
                ),
                "prefetch_retry_plan_sha256": sha256_file(preexisting_retry_plan),
                "final_planned_archive_sha256": str(package["archive_sha256"]),
            }
        )
    if sum(int(item["input_count"]) for item in reused) != int(
        launch.get("input_count", -1)
    ):
        raise ValueError("preexisting retry launch total input count is invalid")
    return tuple(reused)


def _remote_launch_script(*, worker_index: int, archive: Path, sha256: str) -> str:
    raw_hash = sha256.removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
        raise ValueError("operational retry archive SHA-256 is invalid")
    worker_name = f"worker-{worker_index:02d}"
    remote_archive = f"/workspace/folynta/{archive.name}"
    input_root = f"/workspace/folynta/operational-retry/{worker_name}"
    result_root = "/workspace/folynta/results/operational-retry"
    return f"""set -euo pipefail
if pgrep -f '/workspace/folynta/runner/run-mineru-' >/dev/null; then
  echo 'full baseline runner is still active' >&2
  exit 30
fi
test ! -e {result_root}
printf '%s  %s\n' '{raw_hash}' '{remote_archive}' | sha256sum -c - >/dev/null
mkdir -p /workspace/folynta/operational-retry
input_marker={input_root}/.source-archive-sha256
if [[ ! -f "$input_marker" ]] || [[ "$(cat "$input_marker")" != '{raw_hash}' ]]; then
  if [[ -e {input_root} ]]; then
    superseded={input_root}.superseded-$(date -u +%s)
    test ! -e "$superseded"
    mv {input_root} "$superseded"
  fi
  tar --no-same-owner -xzf {remote_archive} -C /workspace/folynta/operational-retry
  printf '%s\n' '{raw_hash}' >"$input_marker"
fi
test -f {input_root}/suites/parsebench/shard-input-manifest.json || \
  test -f {input_root}/suites/omnidocbench/shard-input-manifest.json || \
  test -f {input_root}/suites/olmocr-bench/shard-input-manifest.json
test -f /workspace/folynta/runner/input_contract.py
mkdir -p /workspace/folynta/results
chmod 700 \
  /workspace/folynta/runner/remote_run_operational_retry.sh \
  /workspace/folynta/runner/remote_stall_watchdog.sh
nohup bash /workspace/folynta/runner/remote_run_operational_retry.sh \
  {worker_index} {input_root} {result_root} \
  >{result_root}.launcher.stdout.log \
  2>{result_root}.launcher.stderr.log < /dev/null &
runner_pid=$!
runner_ready=0
for _ in $(seq 1 30); do
  if test -f {result_root}/worker-state.jsonl; then
    runner_ready=1
    break
  fi
  if ! kill -0 "$runner_pid" 2>/dev/null; then
    break
  fi
  sleep 1
done
if [[ "$runner_ready" != 1 ]]; then
  wait "$runner_pid" 2>/dev/null || true
  tail -80 {result_root}.launcher.stderr.log >&2 2>/dev/null || true
  echo 'operational retry runner failed before readiness evidence' >&2
  exit 31
fi
sleep 2
if ! kill -0 "$runner_pid" 2>/dev/null && \
   ! find {result_root} -name run-summary.json -type f -print -quit | grep -q .; then
  tail -80 {result_root}.launcher.stderr.log 2>/dev/null >&2 || true
  echo 'operational retry runner exited immediately after readiness' >&2
  exit 32
fi
nohup bash /workspace/folynta/runner/remote_stall_watchdog.sh \
  2100 60 {result_root} \
  >{result_root}.stall-watchdog.stdout.log \
  2>{result_root}.stall-watchdog.stderr.log < /dev/null &
watchdog_pid=$!
sleep 2
if ! kill -0 "$watchdog_pid" 2>/dev/null; then
  tail -80 {result_root}.stall-watchdog.stderr.log 2>/dev/null >&2 || true
  echo 'operational retry stall watchdog failed startup readiness' >&2
  exit 33
fi
printf '%s,%s\n' "$runner_pid" "$watchdog_pid"
"""


def launch_workers(
    *,
    repository_root: Path,
    config_path: Path,
    package_receipt: Path,
    package_root: Path,
    mineru_runner: Path,
    retry_runner: Path,
    stall_watchdog: Path,
    output_receipt: Path,
    retry_plan: Path | None = None,
    preexisting_launch_receipt: Path | None = None,
    preexisting_retry_plan: Path | None = None,
) -> dict[str, Any]:
    if output_receipt.exists():
        raise FileExistsError(f"launch receipt already exists: {output_receipt}")
    config = _load(config_path)
    workers = _worker_lookup(config)
    key = (repository_root / str(config["key"])).resolve()
    known_hosts = (repository_root / str(config["known_hosts"])).resolve()
    if not key.is_file() or not known_hosts.is_file():
        raise FileNotFoundError("RunPod SSH identity or known-hosts file is missing")
    input_contract = mineru_runner.parent / "input_contract.py"
    scripts = (mineru_runner, input_contract, retry_runner, stall_watchdog)
    if any(not script.is_file() for script in scripts):
        raise FileNotFoundError("operational retry runtime script is missing")
    packages = validate_packages(
        package_receipt=package_receipt,
        package_root=package_root,
    )
    if (preexisting_launch_receipt is None) != (preexisting_retry_plan is None):
        raise ValueError("preexisting launch and retry plan must be supplied together")
    inflight_receipt = output_receipt.with_name(f".{output_receipt.name}.inflight")
    package_by_worker = {int(item["worker_index"]): item for item in packages}
    launches: list[dict[str, Any]] = []
    reused_workers: set[int] = set()
    if preexisting_launch_receipt is not None:
        if retry_plan is None:
            raise ValueError("final retry plan is required for preexisting launch reuse")
        reused = validate_preexisting_launch(
            preexisting_launch_receipt=preexisting_launch_receipt,
            preexisting_retry_plan=preexisting_retry_plan,
            final_retry_plan=retry_plan,
            packages=packages,
        )
        launches.extend(reused)
        reused_workers = {int(item["worker_index"]) for item in reused}
    if inflight_receipt.is_file():
        inflight = _load(inflight_receipt)
        if inflight.get("schema") != "folynta.operational-retry-launch-inflight.v1":
            raise ValueError("operational retry inflight journal schema is invalid")
        journal_launches = inflight.get("launches", [])
        journal_workers: set[int] = set()
        for item in journal_launches:
            worker = int(item["worker_index"])
            package = package_by_worker.get(worker)
            if (
                package is None
                or worker in journal_workers
                or int(item.get("input_count", -1)) != int(package["input_count"])
                or (
                    item.get("prefetch_reused") is not True
                    and str(item.get("archive_sha256"))
                    != str(package["archive_sha256"])
                )
            ):
                raise ValueError("operational retry inflight journal is inconsistent")
            journal_workers.add(worker)
        launches = list(journal_launches)
        reused_workers = {
            int(item["worker_index"])
            for item in launches
            if item.get("prefetch_reused") is True
        }

    def write_inflight() -> None:
        _write_json_atomic(
            inflight_receipt,
            {
                "schema": "folynta.operational-retry-launch-inflight.v1",
                "launches": launches,
            },
        )

    write_inflight()
    launched_workers = {int(item["worker_index"]) for item in launches}
    for package in packages:
        index = int(package["worker_index"])
        if index in launched_workers:
            continue
        if index not in workers:
            raise ValueError(f"RunPod worker config has no endpoint for retry worker {index}")
        endpoint = workers[index]
        scp = _scp_base(
            key=key,
            known_hosts=known_hosts,
            port=int(endpoint["port"]),
        )
        target = f"root@{endpoint['host']}"
        uploads = (
            (Path(package["archive"]), "/workspace/folynta/"),
            (mineru_runner, "/workspace/folynta/runner/mineru_stage2.py"),
            (input_contract, "/workspace/folynta/runner/input_contract.py"),
            (retry_runner, "/workspace/folynta/runner/remote_run_operational_retry.sh"),
            (stall_watchdog, "/workspace/folynta/runner/remote_stall_watchdog.sh"),
        )
        for source, destination in uploads:
            remote_path = (
                f"{destination}{source.name}"
                if destination.endswith("/")
                else destination
            )
            expected_hash = sha256_file(source).removeprefix("sha256:")
            remote_hash = subprocess.run(
                [
                    *_ssh_base(
                        key=key,
                        known_hosts=known_hosts,
                        port=int(endpoint["port"]),
                    ),
                    target,
                    f"sha256sum '{remote_path}' 2>/dev/null | cut -d' ' -f1",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout.strip()
            if remote_hash == expected_hash:
                continue
            subprocess.run(
                [*scp, str(source), f"{target}:{destination}"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        ssh = _ssh_base(
            key=key,
            known_hosts=known_hosts,
            port=int(endpoint["port"]),
        )
        try:
            remote = subprocess.run(
                [*ssh, target, "bash", "-s"],
                input=_remote_launch_script(
                    worker_index=index,
                    archive=Path(package["archive"]),
                    sha256=str(package["archive_sha256"]),
                ).encode("utf-8"),
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            stdout = (exc.stdout or b"").decode("utf-8", errors="replace")[-4000:]
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")[-4000:]
            raise RuntimeError(
                f"remote operational retry launch failed for worker {index}; "
                f"stdout={stdout!r}; stderr={stderr!r}"
            ) from exc
        pid_line = (
            remote.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]
        )
        if not re.fullmatch(r"[1-9][0-9]*,[1-9][0-9]*", pid_line):
            raise ValueError(f"remote retry launch did not return two PIDs: {index}")
        runner_pid, watchdog_pid = (int(value) for value in pid_line.split(","))
        launches.append(
            {
                "worker_index": index,
                "host": str(endpoint["host"]),
                "port": int(endpoint["port"]),
                "input_count": int(package["input_count"]),
                "archive_sha256": str(package["archive_sha256"]),
                "runner_pid": runner_pid,
                "stall_watchdog_pid": watchdog_pid,
            }
        )
        launched_workers.add(index)
        write_inflight()
    receipt: dict[str, Any] = {
        "schema": "folynta.operational-retry-launch.v1",
        "different_worker_routes_frozen": True,
        "worker_count": len(launches),
        "input_count": sum(int(item["input_count"]) for item in launches),
        "prefetch_reused_worker_count": len(reused_workers),
        "prefetch_reused_input_count": sum(
            int(item["input_count"])
            for item in launches
            if item.get("prefetch_reused") is True
        ),
        "launches": launches,
    }
    output_receipt.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(output_receipt, receipt)
    inflight_receipt.unlink(missing_ok=True)
    return {**receipt, "receipt_sha256": sha256_file(output_receipt)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--package-receipt", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--mineru-runner", type=Path, required=True)
    parser.add_argument("--retry-runner", type=Path, required=True)
    parser.add_argument("--stall-watchdog", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--retry-plan", type=Path)
    parser.add_argument("--preexisting-launch-receipt", type=Path)
    parser.add_argument("--preexisting-retry-plan", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = launch_workers(
        repository_root=args.repository_root.resolve(),
        config_path=args.config.resolve(),
        package_receipt=args.package_receipt.resolve(),
        package_root=args.package_root.resolve(),
        mineru_runner=args.mineru_runner.resolve(),
        retry_runner=args.retry_runner.resolve(),
        stall_watchdog=args.stall_watchdog.resolve(),
        output_receipt=args.output_receipt.resolve(),
        retry_plan=(args.retry_plan.resolve() if args.retry_plan else None),
        preexisting_launch_receipt=(
            args.preexisting_launch_receipt.resolve()
            if args.preexisting_launch_receipt
            else None
        ),
        preexisting_retry_plan=(
            args.preexisting_retry_plan.resolve()
            if args.preexisting_retry_plan
            else None
        ),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["launch_workers", "validate_packages", "validate_preexisting_launch"]
