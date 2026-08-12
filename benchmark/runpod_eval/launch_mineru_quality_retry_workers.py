#!/usr/bin/env python3
"""Upload and launch health-routed MinerU official-quality retries."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from collect_public_core_worker import _scp_base, _ssh_base, sha256_file
from launch_operational_retry_workers import _worker_lookup, _write_json_atomic

MODEL = "mineru-3.4.4-vlm-quality-retry"
_PACKAGE_NAME = re.compile(
    rf"^worker-([0-9]{{2}})-{re.escape(MODEL)}-inputs\.tar\.gz$"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_packages(
    *, package_receipt: Path, package_root: Path
) -> tuple[dict[str, Any], ...]:
    receipt = _load(package_receipt)
    if (
        receipt.get("schema")
        != "folynta.public-core-selective-recovery-packages.v1"
        or receipt.get("recovery_model") != MODEL
    ):
        raise ValueError("MinerU quality retry package identity is invalid")
    packages = receipt.get("packages", [])
    if int(receipt.get("package_count", -1)) != len(packages):
        raise ValueError("MinerU quality retry package count is invalid")
    observed: set[int] = set()
    total = 0
    validated: list[dict[str, Any]] = []
    for package in packages:
        index = int(package["recovery_worker_index"])
        name = str(package["archive"])
        match = _PACKAGE_NAME.fullmatch(name)
        if (
            index in observed
            or not 0 <= index <= 99
            or match is None
            or int(match.group(1)) != index
        ):
            raise ValueError("MinerU quality retry package route is invalid")
        archive = package_root / name
        if not archive.is_file() or archive.stat().st_size != int(package["archive_bytes"]):
            raise ValueError(f"MinerU quality retry archive size is invalid: {archive}")
        if sha256_file(archive) != str(package["archive_sha256"]):
            raise ValueError(f"MinerU quality retry archive hash is invalid: {archive}")
        count = int(package["input_count"])
        suites = tuple(str(value) for value in package.get("suites", []))
        if count < 1 or not suites:
            raise ValueError("MinerU quality retry package cannot be empty")
        observed.add(index)
        total += count
        validated.append(
            {
                "worker_index": index,
                "archive": archive,
                "archive_sha256": str(package["archive_sha256"]),
                "input_count": count,
                "suites": suites,
            }
        )
    if total != int(receipt.get("input_count", -1)):
        raise ValueError("MinerU quality retry package input coverage is invalid")
    return tuple(sorted(validated, key=lambda item: int(item["worker_index"])))


def _remote_launch_script(*, worker_index: int, archive: Path, sha256: str) -> str:
    raw_hash = sha256.removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
        raise ValueError("MinerU quality retry archive SHA-256 is invalid")
    worker_name = f"worker-{worker_index:02d}"
    remote_archive = f"/workspace/folynta/{archive.name}"
    input_root = f"/workspace/folynta/selective-recovery/mineru-quality-r1/{worker_name}"
    result_root = "/workspace/folynta/results/mineru-quality-r1"
    return f"""set -euo pipefail
if pgrep -f '/workspace/folynta/runner/run-mineru-' >/dev/null || \
   pgrep -f '/workspace/folynta/runner/remote_run_operational_retry.sh' >/dev/null || \
   pgrep -f '/workspace/folynta/runner/remote_run_mineru_quality_retry.sh' >/dev/null; then
  echo 'another MinerU campaign runner is still active' >&2
  exit 30
fi
test ! -e {result_root}
printf '%s  %s\n' '{raw_hash}' '{remote_archive}' | sha256sum -c - >/dev/null
mkdir -p /workspace/folynta/selective-recovery/mineru-quality-r1
input_marker={input_root}/.source-archive-sha256
if [[ ! -f "$input_marker" ]] || [[ "$(cat "$input_marker")" != '{raw_hash}' ]]; then
  if [[ -e {input_root} ]]; then
    superseded={input_root}.superseded-$(date -u +%s)
    test ! -e "$superseded"
    mv {input_root} "$superseded"
  fi
  tar --no-same-owner -xzf {remote_archive} \
    -C /workspace/folynta/selective-recovery/mineru-quality-r1
  printf '%s\n' '{raw_hash}' >"$input_marker"
fi
test -f /workspace/folynta/runner/input_contract.py
mkdir -p /workspace/folynta/results
chmod 700 \
  /workspace/folynta/runner/remote_run_mineru_quality_retry.sh \
  /workspace/folynta/runner/remote_stall_watchdog.sh
nohup bash /workspace/folynta/runner/remote_run_mineru_quality_retry.sh \
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
  tail -80 {result_root}.launcher.stderr.log 2>/dev/null >&2 || true
  echo 'MinerU quality retry runner failed before readiness evidence' >&2
  exit 31
fi
sleep 2
if ! kill -0 "$runner_pid" 2>/dev/null && \
   ! find {result_root} -name run-summary.json -type f -print -quit | grep -q .; then
  tail -80 {result_root}.launcher.stderr.log 2>/dev/null >&2 || true
  echo 'MinerU quality retry runner exited immediately after readiness' >&2
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
  echo 'MinerU quality retry stall watchdog failed startup readiness' >&2
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
    quality_runner: Path,
    stall_watchdog: Path,
    output_receipt: Path,
) -> dict[str, Any]:
    if output_receipt.exists():
        raise FileExistsError(f"quality retry launch receipt exists: {output_receipt}")
    config = _load(config_path)
    workers = _worker_lookup(config)
    key = (repository_root / str(config["key"])).resolve()
    known_hosts = (repository_root / str(config["known_hosts"])).resolve()
    if not key.is_file() or not known_hosts.is_file():
        raise FileNotFoundError("SSH identity or known-hosts file is missing")
    input_contract = mineru_runner.parent / "input_contract.py"
    scripts = (mineru_runner, input_contract, quality_runner, stall_watchdog)
    if any(not script.is_file() for script in scripts):
        raise FileNotFoundError("MinerU quality retry runtime script is missing")
    packages = validate_packages(
        package_receipt=package_receipt, package_root=package_root
    )
    inflight_receipt = output_receipt.with_name(f".{output_receipt.name}.inflight")
    package_by_worker = {int(item["worker_index"]): item for item in packages}
    launches: list[dict[str, Any]] = []
    if inflight_receipt.is_file():
        inflight = _load(inflight_receipt)
        if inflight.get("schema") != "folynta.mineru-quality-retry-launch-inflight.v1":
            raise ValueError("MinerU quality retry inflight journal schema is invalid")
        for item in inflight.get("launches", []):
            worker = int(item["worker_index"])
            package = package_by_worker.get(worker)
            if (
                package is None
                or any(int(existing["worker_index"]) == worker for existing in launches)
                or int(item.get("input_count", -1)) != int(package["input_count"])
                or str(item.get("archive_sha256")) != str(package["archive_sha256"])
            ):
                raise ValueError("MinerU quality retry inflight journal is inconsistent")
            launches.append(item)

    def write_inflight() -> None:
        _write_json_atomic(
            inflight_receipt,
            {
                "schema": "folynta.mineru-quality-retry-launch-inflight.v1",
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
            raise ValueError(f"RunPod config has no quality retry worker {index}")
        endpoint = workers[index]
        scp = _scp_base(
            key=key, known_hosts=known_hosts, port=int(endpoint["port"])
        )
        target = f"root@{endpoint['host']}"
        uploads = (
            (Path(package["archive"]), "/workspace/folynta/"),
            (mineru_runner, "/workspace/folynta/runner/mineru_stage2.py"),
            (input_contract, "/workspace/folynta/runner/input_contract.py"),
            (
                quality_runner,
                "/workspace/folynta/runner/remote_run_mineru_quality_retry.sh",
            ),
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
            key=key, known_hosts=known_hosts, port=int(endpoint["port"])
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
                f"remote MinerU quality retry launch failed for worker {index}; "
                f"stdout={stdout!r}; stderr={stderr!r}"
            ) from exc
        pid_line = (
            remote.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]
        )
        if not re.fullmatch(r"[1-9][0-9]*,[1-9][0-9]*", pid_line):
            raise ValueError(f"quality retry launch did not return two PIDs: {index}")
        runner_pid, watchdog_pid = (int(value) for value in pid_line.split(","))
        launches.append(
            {
                "worker_index": index,
                "host": str(endpoint["host"]),
                "port": int(endpoint["port"]),
                "input_count": int(package["input_count"]),
                "suites": list(package["suites"]),
                "archive_sha256": str(package["archive_sha256"]),
                "runner_pid": runner_pid,
                "stall_watchdog_pid": watchdog_pid,
            }
        )
        launched_workers.add(index)
        write_inflight()
    receipt: dict[str, Any] = {
        "schema": "folynta.mineru-quality-retry-launch.v1",
        "recovery_model": MODEL,
        "worker_count": len(launches),
        "input_count": sum(int(item["input_count"]) for item in launches),
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
    parser.add_argument("--quality-runner", type=Path, required=True)
    parser.add_argument("--stall-watchdog", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = launch_workers(
        repository_root=args.repository_root.resolve(),
        config_path=args.config.resolve(),
        package_receipt=args.package_receipt.resolve(),
        package_root=args.package_root.resolve(),
        mineru_runner=args.mineru_runner.resolve(),
        quality_runner=args.quality_runner.resolve(),
        stall_watchdog=args.stall_watchdog.resolve(),
        output_receipt=args.output_receipt.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["MODEL", "launch_workers", "validate_packages"]
