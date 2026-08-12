#!/usr/bin/env python3
"""Package source-only operational retry shards for their different RunPod workers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path
from typing import Any

_ALLOWED = re.compile(
    r"^worker-[0-9]{2}/suites/(?:parsebench|omnidocbench|olmocr-bench)/(?:"
    r"parent-input-manifest\.json|shard-input-manifest\.json|"
    r"inputs/[A-Za-z0-9._-]+\.(?:png|jpg|jpeg|webp|bmp|tif|tiff))$",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def package_retry_inputs(
    *, staging_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"retry package output already exists: {output_root}")
    plan_path = staging_root / "retry-plan-receipt.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    workers = plan.get("workers", [])
    eligible_workers = {int(value) for value in plan.get("eligible_retry_workers", [])}
    if int(plan.get("staged_input_count", -1)) != int(plan.get("failed_input_count", -2)):
        raise ValueError("retry input plan does not exactly cover operational failures")
    output_root.mkdir(parents=True)
    packages: list[dict[str, Any]] = []
    for worker in workers:
        index = int(worker["retry_worker_index"])
        if index not in eligible_workers or not 0 <= index <= 99:
            raise ValueError("retry worker index is invalid")
        worker_root = staging_root / f"worker-{index:02d}"
        files = sorted(path for path in worker_root.rglob("*") if path.is_file())
        input_files = [path for path in files if path.parent.name == "inputs"]
        if len(input_files) != int(worker["input_count"]):
            raise ValueError(f"retry worker input count is invalid: {index}")
        members: list[str] = []
        for path in files:
            if path.is_symlink():
                raise ValueError(f"retry package cannot contain links: {path}")
            relative = path.relative_to(staging_root).as_posix()
            if not _ALLOWED.fullmatch(relative):
                raise ValueError(f"unexpected retry package member: {relative}")
            members.append(relative)
        archive = output_root / f"worker-{index:02d}-operational-retry-inputs.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for path, relative in zip(files, members, strict=True):
                bundle.add(path, arcname=relative, recursive=False)
        packages.append(
            {
                "retry_worker_index": index,
                "input_count": len(input_files),
                "member_count": len(members),
                "archive": archive.name,
                "archive_bytes": archive.stat().st_size,
                "archive_sha256": _sha256(archive),
            }
        )
    receipt = {
        "schema": "folynta.public-core-operational-retry-packages.v1",
        "retry_plan_sha256": _sha256(plan_path),
        "package_count": len(packages),
        "input_count": sum(int(package["input_count"]) for package in packages),
        "packages": packages,
    }
    receipt_path = output_root / "package-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return {**receipt, "receipt_sha256": _sha256(receipt_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = package_retry_inputs(
        staging_root=args.staging_root.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["package_retry_inputs"]
