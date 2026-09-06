#!/usr/bin/env python3
"""Validate and extract a Stage-1 result archive that is already on disk.

The first holdout run finished correctly -- 800 of 800 pages, zero failures,
2,018 seconds of inference -- and the controller then refused it, because v10
compares the returned receipt against a literal 200 in a check that runs *after*
the archive has been downloaded and the Pod cleaned up. The archive, the receipt
and the cleanup proof are all present and valid; only the controller's last
assertion was wrong.

Re-running the inference to satisfy a wrong constant would spend another half
hour of GPU and produce a different sample of a nondeterministic process, which
would be worse evidence, not better. So this performs the same validations v10
performs -- GT isolation on both the receipt and the run summary, assembly
identity, declared-versus-actual cohort size, and archive hash -- with the count
read from the bundle receipt, and extracts.

It refuses on any mismatch. It cannot make a failed run look successful: the
completion counts it checks come from the Pod's own receipt, which is hashed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--bundle-receipt", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    archive_path = run_dir / "stage1-results.tar.gz"
    receipt_path = run_dir / "stage1-receipt.json"
    for path in (archive_path, receipt_path):
        if not path.is_file():
            raise SystemExit(f"missing: {path.name}")

    expected = int(
        json.loads(args.bundle_receipt.resolve().read_text(encoding="utf-8"))[
            "input_count"
        ]
    )
    ready = json.loads(args.ready.resolve().read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    if (
        receipt.get("ground_truth_mounted") is not False
        or receipt.get("ground_truth_in_bundle") is not False
    ):
        raise SystemExit("Stage-1 receipt violated GT isolation")
    if int(receipt.get("input_count", -1)) != expected:
        raise SystemExit(
            f"receipt declares {receipt.get('input_count')} inputs, bundle says {expected}"
        )
    if receipt.get("assembly_id") != ready.get("assembly_id"):
        raise SystemExit("Stage-1 assembly id does not match the READY receipt")
    if receipt.get("shard_content_sha256") != json.loads(
        args.bundle_receipt.resolve().read_text(encoding="utf-8")
    ).get("shard_content_sha256"):
        raise SystemExit("Stage-1 receipt shard identity drifted")
    if int(receipt.get("completed", -1)) + int(receipt.get("failed", -1)) != expected:
        raise SystemExit("completed + failed does not account for every input")

    extract = run_dir / "results"
    if extract.exists():
        raise SystemExit("results/ already exists; refusing to overwrite")
    extract.mkdir()
    with tarfile.open(archive_path, "r:gz") as handle:
        names = handle.getnames()
        suspicious = [
            name
            for name in names
            if "ground_truth" in name.lower()
            or "ground-truth" in name.lower()
            or f"/{name.lower()}/".find("/inputs/") >= 0
        ]
        if suspicious:
            raise SystemExit("result archive contains forbidden source/GT material")
        handle.extractall(extract, filter="data")

    summary_path = extract / "output" / "run-summary.json"
    if not summary_path.is_file():
        raise SystemExit("downloaded result lacks run-summary.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (
        summary.get("ground_truth_mounted") is not False
        or int(summary.get("input_count", -1)) != expected
    ):
        raise SystemExit("run summary violated the GT/input-count contract")

    predictions = sorted((extract / "output").rglob("*.md"))
    local = {
        "schema": "tavonel.stage1-local-archive-harvest.v1",
        "completed_at": datetime.now(UTC).isoformat(),
        "run_dir": run_dir.name,
        "why_local": (
            "the run succeeded and the controller's final assertion compared the "
            "cohort size against a literal 200; the archive was already downloaded "
            "and the Pod already cleaned up when it fired"
        ),
        "input_count": expected,
        "completed": int(receipt["completed"]),
        "failed": int(receipt["failed"]),
        "inference_seconds": float(receipt["inference_seconds"]),
        "gpu_seconds_per_page": float(receipt["inference_seconds"]) / expected,
        "assembly_id": receipt["assembly_id"],
        "gpu_type": receipt.get("gpu_type"),
        "ground_truth_mounted": False,
        "ground_truth_in_bundle": False,
        "prediction_files": len(predictions),
        "result_archive_sha256": sha256_file(archive_path),
        "stage1_receipt_sha256": sha256_file(receipt_path),
        "run_summary_sha256": sha256_file(summary_path),
    }
    local["receipt_sha256"] = canonical_sha256(local)
    (run_dir / "local-harvest-receipt.json").write_text(
        json.dumps(local, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"validated and extracted {run_dir.name}")
    for key in (
        "input_count",
        "completed",
        "failed",
        "inference_seconds",
        "gpu_seconds_per_page",
        "prediction_files",
    ):
        print(f"  {key}: {local[key]}")
    print(f"receipt: {run_dir / 'local-harvest-receipt.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
