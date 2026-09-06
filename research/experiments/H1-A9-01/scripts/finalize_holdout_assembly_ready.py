#!/usr/bin/env python3
"""Derive a READY receipt for the A9 confirmatory-holdout bundle.

This is the sealed v29 READY generator with its bundle paths turned into
arguments and the hardcoded 200 replaced by the bundle receipt's own count.
Nothing about the runtime changes: the same GPU qualification receipt supplies
the assembly id, base image digest, model identity, security receipt and
CRITICAL=0 binding, because the runtime being qualified is the same runtime.
What changes is only which sealed input bundle the READY authorises.

Two things this deliberately is not:

  * It is **not** an edit of the existing READY. That file is untouched and
    still binds the hard-200 bundle that produced the discovery evidence; this
    writes a separate receipt to a separate path.
  * It is **not** a manual override. `manual_ready_override_allowed` stays
    false, every check the original performs still runs, and the bundle hash is
    recomputed from the tar rather than trusted from its receipt.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
QUAL = (
    ROOT
    / "research"
    / "experiments"
    / "ASSURANCE-A-01"
    / "receipts"
    / "ovisocr2-m1-verified-assembly-v29.runtime-qualification.json"
)
BUNDLE = ROOT / ".chatgpt2codex" / "formal-runtime-v28" / "stage1-hard-200-source-only-v2.tar"
BUNDLE_RECEIPT = (
    ROOT / ".chatgpt2codex" / "formal-runtime-v28" / "stage1-hard-200-source-only-v2.receipt.json"
)
OUT = ROOT / ".chatgpt2codex" / "formal-runtime-v29" / "ovisocr2-v29-assembly-ready.json"


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def main() -> int:
    import argparse

    global BUNDLE, BUNDLE_RECEIPT, OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bundle-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    BUNDLE = args.bundle.resolve()
    BUNDLE_RECEIPT = args.bundle_receipt.resolve()
    OUT = args.out.resolve()

    if OUT.exists():
        raise RuntimeError("READY receipt already exists at that path")
    qualification = read_object(QUAL)
    bundle = read_object(BUNDLE_RECEIPT)
    if qualification.get("schema") != "tavonel.verified-runtime-assembly-qualification.v1":
        raise RuntimeError("v29 qualification schema drifted")
    if qualification.get("passed") is not True:
        raise RuntimeError("v29 qualification is not PASS")
    if qualification.get("provider_cleanup_verified") is not True:
        raise RuntimeError("v29 qualification provider cleanup is not verified")
    if int(qualification.get("critical_vulnerability_count", -1)) != 0:
        raise RuntimeError("v29 qualification does not bind CRITICAL=0")
    if qualification.get("gpu_type") != "NVIDIA GeForce RTX 4090":
        raise RuntimeError("v29 qualification GPU is not RTX 4090")
    expected_count = int(bundle.get("input_count", -1))
    if expected_count < 1 or bundle.get("evidence_class") != "public-core-shard":
        raise RuntimeError("Stage-1 bundle identity drifted")
    if (
        bundle.get("ground_truth_mounted") is not False
        or bundle.get("ground_truth_in_bundle") is not False
    ):
        raise RuntimeError("Stage-1 bundle is not GT-free")
    if bundle.get("shard_parent_binding_verified") is not True:
        raise RuntimeError("Stage-1 shard/parent binding is not verified")
    if sha_file(BUNDLE) != bundle.get("tar_sha256"):
        raise RuntimeError("Stage-1 bundle hash drifted")

    ready = {
        "schema": "tavonel.verified-runtime-assembly-ready.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "qualification_state": "READY",
        "manual_ready_override_allowed": False,
        "assembly_id": qualification["assembly_id"],
        "base_image_digest": qualification["base_image_digest"],
        "bootstrap_sha256": qualification["bootstrap_sha256"],
        "security_receipt_sha256": qualification["security_receipt_sha256"],
        "security_package_sha256": qualification["security_package_sha256"],
        "critical_vulnerability_count": 0,
        "model_receipt_sha256": qualification["model_receipt_sha256"],
        "model_revision": qualification["model_revision"],
        "model_artifact_sha256": qualification["model_artifact_sha256"],
        "gpu_type": qualification["gpu_type"],
        "cuda_version": qualification["cuda_version"],
        "framework_version": qualification["framework_version"],
        "persistent_volume_gb": 0,
        "container_disk_gb": 80,
        "maximum_hourly_rate_usd": "0.80",
        "fresh_pod_must_reverify_assembly_before_public_benchmark": True,
        "stage1": {
            "benchmark_id": bundle["benchmark_id"],
            "evidence_class": bundle["evidence_class"],
            "input_count": expected_count,
            "bundle_sha256": bundle["tar_sha256"],
            "shard_content_sha256": bundle["shard_content_sha256"],
            "parent_content_sha256": bundle["parent_content_sha256"],
            "ground_truth_mounted": False,
            "ground_truth_in_bundle": False,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(ready, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "qualification_state": "READY",
                "input_count": expected_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
