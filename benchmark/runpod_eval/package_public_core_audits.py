#!/usr/bin/env python3
"""Package the three frozen source-only stratified audits for GPU execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path
from typing import Any

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")
_MEMBER = re.compile(
    r"^(?:parsebench|omnidocbench|olmocr-bench)/(?:"
    r"stratified-audit\.json|parent-input-manifest\.json|"
    r"inputs/[A-Za-z0-9._-]+\.(?:png|jpg|jpeg|webp|bmp|tif|tiff))$",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def package_audits(*, staging_root: Path, output_root: Path) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"audit package output already exists: {output_root}")
    stage_receipt = staging_root / "audit-staging-receipt.json"
    staged = json.loads(stage_receipt.read_text(encoding="utf-8"))
    if (
        staged.get("schema") != "folynta.public-core-stratified-audit-staging.v1"
        or staged.get("ground_truth_mounted") is not False
        or int(staged.get("input_count", -1)) != 384
    ):
        raise ValueError("stratified audit staging receipt is invalid")
    output_root.mkdir(parents=True)
    packages: list[dict[str, Any]] = []
    for suite in SUITES:
        suite_root = staging_root / suite
        inputs = sorted((suite_root / "inputs").iterdir())
        if len(inputs) != 128 or any(not path.is_file() for path in inputs):
            raise ValueError(f"stratified audit input inventory is invalid: {suite}")
        files = [
            suite_root / "stratified-audit.json",
            suite_root / "parent-input-manifest.json",
            *inputs,
        ]
        members = [path.relative_to(staging_root).as_posix() for path in files]
        if any(path.is_symlink() for path in files) or any(
            _MEMBER.fullmatch(member) is None for member in members
        ):
            raise ValueError(f"stratified audit package member is unsafe: {suite}")
        archive = output_root / f"{suite}-stratified-audit-inputs.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for path, member in zip(files, members, strict=True):
                bundle.add(path, arcname=member, recursive=False)
        packages.append(
            {
                "benchmark_id": suite,
                "input_count": len(inputs),
                "member_count": len(members),
                "archive": archive.name,
                "archive_bytes": archive.stat().st_size,
                "archive_sha256": _sha256(archive),
            }
        )
    receipt: dict[str, Any] = {
        "schema": "folynta.public-core-stratified-audit-packages.v1",
        "staging_receipt_sha256": _sha256(stage_receipt),
        "ground_truth_included": False,
        "package_count": len(packages),
        "input_count": sum(int(item["input_count"]) for item in packages),
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
    result = package_audits(
        staging_root=args.staging_root.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["package_audits"]
