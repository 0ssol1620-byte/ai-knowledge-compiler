#!/usr/bin/env python3
"""Upload all logical-worker recovery packages to one dedicated physical Pod."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from collect_public_core_worker import _scp_base, _ssh_base, sha256_file

MODELS = ("paddleocr-vl-1.6", "deepseek-ocr-2")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_packages(
    *, model: str, package_receipt: Path, package_root: Path
) -> tuple[dict[str, Any], ...]:
    receipt = _load(package_receipt)
    if (
        model not in MODELS
        or receipt.get("schema") != "folynta.public-core-selective-recovery-packages.v1"
        or receipt.get("recovery_model") != model
    ):
        raise ValueError("dedicated recovery package identity is invalid")
    packages = receipt.get("packages", [])
    if int(receipt.get("package_count", -1)) != len(packages) or not packages:
        raise ValueError("dedicated recovery package count is invalid")
    observed: set[int] = set()
    validated: list[dict[str, Any]] = []
    total = 0
    pattern = re.compile(rf"^worker-(0[0-3])-{re.escape(model)}-inputs\.tar\.gz$")
    for item in packages:
        index = int(item["recovery_worker_index"])
        name = str(item["archive"])
        match = pattern.fullmatch(name)
        if index in observed or match is None or int(match.group(1)) != index:
            raise ValueError("dedicated recovery package route is invalid")
        archive = package_root / name
        if not archive.is_file() or archive.stat().st_size != int(item["archive_bytes"]):
            raise ValueError(f"dedicated recovery archive size mismatch: {archive}")
        if sha256_file(archive) != str(item["archive_sha256"]):
            raise ValueError(f"dedicated recovery archive hash mismatch: {archive}")
        count = int(item["input_count"])
        if count < 1:
            raise ValueError("dedicated recovery package cannot be empty")
        observed.add(index)
        total += count
        validated.append({**item, "archive_path": archive})
    if total != int(receipt.get("input_count", -1)):
        raise ValueError("dedicated recovery package coverage is incomplete")
    return tuple(sorted(validated, key=lambda item: int(item["recovery_worker_index"])))


def _with_frozen_kex(command: list[str]) -> list[str]:
    return [*command[:-2], "-o", "KexAlgorithms=curve25519-sha256", *command[-2:]]


def launch_dedicated_recovery(
    *,
    repository_root: Path,
    model: str,
    host: str,
    port: int,
    pod_id: str,
    forbidden_pod_ids: tuple[str, ...],
    key: Path,
    known_hosts: Path,
    package_receipt: Path,
    package_root: Path,
    model_runner: Path,
    campaign_runner: Path,
    input_contract: Path,
    isolated_process: Path,
    output_receipt: Path,
) -> dict[str, Any]:
    del repository_root
    if output_receipt.exists():
        raise FileExistsError(f"dedicated recovery launch receipt exists: {output_receipt}")
    if pod_id in forbidden_pod_ids or len(set(forbidden_pod_ids)) != len(forbidden_pod_ids):
        raise ValueError("dedicated recovery Pod must differ from every baseline Pod")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}", pod_id):
        raise ValueError("dedicated recovery Pod id is invalid")
    for path in (key, known_hosts, model_runner, campaign_runner, input_contract, isolated_process):
        if not path.is_file():
            raise FileNotFoundError(path)
    packages = validate_packages(
        model=model, package_receipt=package_receipt, package_root=package_root
    )
    slug = "paddle" if model == "paddleocr-vl-1.6" else "deepseek"
    target = f"root@{host}"
    scp = _with_frozen_kex(_scp_base(key=key, known_hosts=known_hosts, port=port))
    ssh = _with_frozen_kex(_ssh_base(key=key, known_hosts=known_hosts, port=port))
    uploads = [
        *((Path(item["archive_path"]), "/workspace/folynta/") for item in packages),
        (model_runner, f"/workspace/folynta/runner/{model_runner.name}"),
        (campaign_runner, "/workspace/folynta/runner/remote_run_dedicated_recovery.sh"),
        (input_contract, "/workspace/folynta/runner/input_contract.py"),
        (isolated_process, "/workspace/folynta/runner/isolated_case_process.py"),
    ]
    for source, destination in uploads:
        subprocess.run(
            [*scp, str(source), f"{target}:{destination}"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    input_root = f"/workspace/folynta/selective-recovery/{slug}-r1"
    output_root = f"/workspace/folynta/results/{slug}-r1"
    archive_checks = []
    for item in packages:
        archive = Path(item["archive_path"])
        raw_hash = str(item["archive_sha256"]).removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
            raise ValueError("dedicated recovery archive SHA-256 is invalid")
        archive_checks.append(
            f"printf '%s  %s\\n' '{raw_hash}' "
            f"'/workspace/folynta/{archive.name}' | sha256sum -c - >/dev/null"
        )
        archive_checks.append(
            f"tar --no-same-owner -xzf '/workspace/folynta/{archive.name}' -C '{input_root}'"
        )
    remote_script = "\n".join(
        [
            "set -euo pipefail",
            f"test -f /workspace/folynta/bootstrap/{slug}-r1/runtime-identity.json",
            f"test ! -e '{input_root}'",
            f"test ! -e '{output_root}'",
            f"mkdir -p '{input_root}' /workspace/folynta/results",
            *archive_checks,
            "chmod 700 /workspace/folynta/runner/remote_run_dedicated_recovery.sh",
            "nohup bash /workspace/folynta/runner/remote_run_dedicated_recovery.sh "
            f"'{model}' '{input_root}' '{output_root}' "
            f">'{output_root}.launcher.stdout.log' "
            f"2>'{output_root}.launcher.stderr.log' < /dev/null &",
            "printf '%s\\n' \"$!\"",
        ]
    )
    launched = subprocess.run(
        [*ssh, target, "bash", "-s"],
        input=remote_script.encode("utf-8"),
        check=True,
        capture_output=True,
    )
    pid = launched.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]
    if not re.fullmatch(r"[1-9][0-9]*", pid):
        raise ValueError("dedicated recovery launch did not return a PID")
    receipt: dict[str, Any] = {
        "schema": "folynta.dedicated-recovery-launch.v1",
        "model": model,
        "dedicated_pod_id": pod_id,
        "forbidden_baseline_pod_ids": sorted(forbidden_pod_ids),
        "different_physical_pod_verified": True,
        "host": host,
        "port": port,
        "logical_worker_count": len(packages),
        "input_count": sum(int(item["input_count"]) for item in packages),
        "runner_pid": int(pid),
        "packages": [
            {
                "recovery_worker_index": int(item["recovery_worker_index"]),
                "archive": str(item["archive"]),
                "archive_sha256": str(item["archive_sha256"]),
                "input_count": int(item["input_count"]),
                "suites": list(item["suites"]),
            }
            for item in packages
        ],
    }
    output_receipt.parent.mkdir(parents=True, exist_ok=True)
    output_receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return {**receipt, "receipt_sha256": sha256_file(output_receipt)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--forbid-pod-id", action="append", default=[])
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--known-hosts", type=Path, required=True)
    parser.add_argument("--package-receipt", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--model-runner", type=Path, required=True)
    parser.add_argument("--campaign-runner", type=Path, required=True)
    parser.add_argument("--input-contract", type=Path, required=True)
    parser.add_argument("--isolated-process", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = launch_dedicated_recovery(
        repository_root=args.repository_root.resolve(),
        model=args.model,
        host=args.host,
        port=args.port,
        pod_id=args.pod_id,
        forbidden_pod_ids=tuple(args.forbid_pod_id),
        key=args.key.resolve(),
        known_hosts=args.known_hosts.resolve(),
        package_receipt=args.package_receipt.resolve(),
        package_root=args.package_root.resolve(),
        model_runner=args.model_runner.resolve(),
        campaign_runner=args.campaign_runner.resolve(),
        input_contract=args.input_contract.resolve(),
        isolated_process=args.isolated_process.resolve(),
        output_receipt=args.output_receipt.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["MODELS", "launch_dedicated_recovery", "validate_packages"]
