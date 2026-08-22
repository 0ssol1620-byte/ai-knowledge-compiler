#!/usr/bin/env python3
"""Package source-only selective-recovery inputs for exact worker routes."""

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
_MODEL_SLUG = re.compile(r"^[a-z0-9][a-z0-9.-]{2,63}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def package_selective_inputs(
    *, staging_root: Path, output_root: Path
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"selective package output already exists: {output_root}")
    staging_receipt = staging_root / "selective-recovery-receipt.json"
    payload = json.loads(staging_receipt.read_text(encoding="utf-8"))
    if payload.get("schema") != "folynta.public-core-selective-recovery-staging.v1":
        raise ValueError("selective recovery staging receipt schema is invalid")
    model = str(payload.get("recovery_model", ""))
    if not _MODEL_SLUG.fullmatch(model):
        raise ValueError("selective recovery model id is unsafe")
    workers = payload.get("workers", [])
    eligible_workers = {
        int(value) for value in payload.get("eligible_recovery_workers", [])
    }
    if int(payload.get("input_count", -1)) != sum(
        int(worker["input_count"]) for worker in workers
    ):
        raise ValueError("selective recovery worker coverage is invalid")

    output_root.mkdir(parents=True)
    packages: list[dict[str, Any]] = []
    observed_workers: set[int] = set()
    for worker in workers:
        index = int(worker["recovery_worker_index"])
        if (
            index not in eligible_workers
            or not 0 <= index <= 99
            or index in observed_workers
        ):
            raise ValueError("selective recovery worker route is invalid")
        observed_workers.add(index)
        worker_root = staging_root / f"worker-{index:02d}"
        files = sorted(path for path in worker_root.rglob("*") if path.is_file())
        input_files = [path for path in files if path.parent.name == "inputs"]
        if len(input_files) != int(worker["input_count"]):
            raise ValueError(f"selective worker input count is invalid: {index}")
        members: list[str] = []
        for path in files:
            if path.is_symlink():
                raise ValueError(f"selective package cannot contain links: {path}")
            relative = path.relative_to(staging_root).as_posix()
            if not _ALLOWED.fullmatch(relative):
                raise ValueError(f"unexpected selective package member: {relative}")
            members.append(relative)
        archive = output_root / f"worker-{index:02d}-{model}-inputs.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for path, relative in zip(files, members, strict=True):
                bundle.add(path, arcname=relative, recursive=False)
        packages.append(
            {
                "recovery_worker_index": index,
                "input_count": len(input_files),
                "member_count": len(members),
                "suites": [str(item["benchmark_id"]) for item in worker["suites"]],
                "archive": archive.name,
                "archive_bytes": archive.stat().st_size,
                "archive_sha256": _sha256(archive),
            }
        )
    receipt = {
        "schema": "folynta.public-core-selective-recovery-packages.v1",
        "recovery_model": model,
        "staging_receipt_sha256": _sha256(staging_receipt),
        "package_count": len(packages),
        "input_count": sum(int(package["input_count"]) for package in packages),
        "packages": packages,
    }
    receipt_path = output_root / "package-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
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
    result = package_selective_inputs(
        staging_root=args.staging_root.resolve(), output_root=args.output_root.resolve()
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["package_selective_inputs"]
