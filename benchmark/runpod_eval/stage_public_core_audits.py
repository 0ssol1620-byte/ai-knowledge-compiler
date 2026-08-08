#!/usr/bin/env python3
"""Materialize the frozen 128-case-per-suite audit without ground truth."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _link(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def stage_audits(
    *,
    audit_manifest_root: Path,
    staged_worker_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"audit staging already exists: {output_root}")
    output_root.mkdir(parents=True)
    suite_receipts: list[dict[str, Any]] = []
    total = 0
    for suite in SUITES:
        audit_path = audit_manifest_root / f"{suite}-stratified-audit.json"
        parent_path = (
            staged_worker_root
            / "worker-00"
            / "suites"
            / suite
            / "parent-input-manifest.json"
        )
        audit = _load(audit_path)
        parent = _load(parent_path)
        if audit.get("schema") != "folynta.public-core-stratified-audit.v1":
            raise ValueError(f"audit schema is invalid for {suite}")
        if audit.get("benchmark_id") != suite or parent.get("benchmark_id") != suite:
            raise ValueError(f"audit benchmark identity is invalid for {suite}")
        if audit.get("parent_input_manifest_sha256") != parent.get("content_sha256"):
            raise ValueError(f"audit parent binding is invalid for {suite}")
        inputs = audit.get("inputs", [])
        if len(inputs) != 128 or int(audit.get("input_count", -1)) != 128:
            raise ValueError(f"audit must contain exactly 128 inputs for {suite}")
        suite_root = output_root / suite
        input_root = suite_root / "inputs"
        input_root.mkdir(parents=True)
        shutil.copy2(audit_path, suite_root / "stratified-audit.json")
        shutil.copy2(parent_path, suite_root / "parent-input-manifest.json")
        source_workers: dict[int, int] = {}
        for item in inputs:
            filename = Path(str(item["input_relative_path"])).name
            expected_hash = str(item["input_sha256"])
            matches = [
                staged_worker_root
                / f"worker-{worker:02d}"
                / "suites"
                / suite
                / "inputs"
                / filename
                for worker in range(4)
            ]
            matches = [path for path in matches if path.is_file()]
            if len(matches) != 1:
                raise ValueError(f"audit input is not uniquely sharded: {suite}/{filename}")
            source = matches[0]
            if _sha256(source) != expected_hash:
                raise ValueError(f"audit input hash is invalid: {suite}/{filename}")
            target = input_root / filename
            _link(source, target)
            if _sha256(target) != expected_hash:
                raise ValueError(f"materialized audit input hash is invalid: {suite}/{filename}")
            worker_index = int(source.parts[-5].removeprefix("worker-"))
            source_workers[worker_index] = source_workers.get(worker_index, 0) + 1
            total += 1
        suite_receipts.append(
            {
                "benchmark_id": suite,
                "input_count": len(inputs),
                "audit_manifest_sha256": _sha256(audit_path),
                "parent_manifest_sha256": _sha256(parent_path),
                "source_worker_distribution": [
                    {"worker_index": worker, "input_count": count}
                    for worker, count in sorted(source_workers.items())
                ],
            }
        )
    if total != 384:
        raise ValueError("stratified audit staging must contain exactly 384 inputs")
    receipt: dict[str, Any] = {
        "schema": "folynta.public-core-stratified-audit-staging.v1",
        "ground_truth_mounted": False,
        "suite_count": len(suite_receipts),
        "input_count": total,
        "repeat_policy": {"repeats": 3, "repeat_start_index": 1},
        "suites": suite_receipts,
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    (output_root / "audit-staging-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-manifest-root", type=Path, required=True)
    parser.add_argument("--staged-worker-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = stage_audits(
        audit_manifest_root=args.audit_manifest_root.resolve(),
        staged_worker_root=args.staged_worker_root.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["stage_audits"]
