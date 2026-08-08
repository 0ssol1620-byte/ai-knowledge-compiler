"""Verify frozen, ground-truth-free public-core source manifests and emit a receipt."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from public_core_sources import EXPECTED_SOURCE_COUNTS, content_sha256, write_manifest

ALLOWED_SOURCE_FIELDS = {
    "case_id",
    "source_relative_path",
    "source_sha256",
    "media_type",
    "page_index",
}


def verify_source_manifests(
    *, acquisition_receipt: Path, manifest_dir: Path
) -> dict[str, Any]:
    acquisition = json.loads(acquisition_receipt.read_text(encoding="utf-8"))
    if acquisition.get("gate") != "PASS":
        raise ValueError("public-core acquisition gate is not PASS")
    acquired = {item["benchmark_id"]: item for item in acquisition["datasets"]}
    datasets: list[dict[str, Any]] = []
    for benchmark_id, expected_count in EXPECTED_SOURCE_COUNTS.items():
        manifest_path = manifest_dir / f"{benchmark_id}-source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != "folynta.public-core-source-manifest.v1":
            raise ValueError(f"{benchmark_id} source manifest schema is invalid")
        if manifest.get("content_sha256") != content_sha256(manifest):
            raise ValueError(f"{benchmark_id} source manifest hash is invalid")
        if manifest.get("ground_truth_mounted") is not False:
            raise ValueError(f"{benchmark_id} source manifest is not ground-truth-free")
        sources = manifest.get("sources")
        if not isinstance(sources, list) or len(sources) != expected_count:
            raise ValueError(f"{benchmark_id} source manifest count is invalid")
        if (
            manifest.get("source_count") != expected_count
            or manifest.get("complete_source_coverage") is not True
        ):
            raise ValueError(f"{benchmark_id} source coverage is incomplete")
        if any(set(source) != ALLOWED_SOURCE_FIELDS for source in sources):
            raise ValueError(f"{benchmark_id} source manifest exposes forbidden fields")
        case_ids = [source["case_id"] for source in sources]
        paths = [source["source_relative_path"] for source in sources]
        if len(set(case_ids)) != expected_count or len(set(paths)) != expected_count:
            raise ValueError(f"{benchmark_id} source identities are not unique")
        acquisition_item = acquired.get(benchmark_id)
        if acquisition_item is None or acquisition_item.get("passed") is not True:
            raise ValueError(f"{benchmark_id} acquisition evidence is missing")
        if manifest.get("dataset_revision") != acquisition_item.get("dataset_revision"):
            raise ValueError(f"{benchmark_id} revision does not match acquisition")
        datasets.append(
            {
                "benchmark_id": benchmark_id,
                "dataset_revision": manifest["dataset_revision"],
                "source_count": expected_count,
                "source_manifest_sha256": manifest["content_sha256"],
                "ground_truth_mounted": False,
                "complete_source_coverage": True,
                "passed": True,
            }
        )
    receipt: dict[str, Any] = {
        "schema": "folynta.public-core-source-manifest-verification.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "acquisition_receipt_sha256": acquisition["receipt_sha256"],
        "ground_truth_mount_policy": "evaluator-only",
        "inference_ground_truth_access": "forbidden",
        "total_source_count": sum(item["source_count"] for item in datasets),
        "datasets": datasets,
        "gate": "PASS",
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-receipt", type=Path, required=True)
    parser.add_argument("--manifest-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = verify_source_manifests(
        acquisition_receipt=args.acquisition_receipt,
        manifest_dir=args.manifest_dir,
    )
    write_manifest(args.output, receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["verify_source_manifests"]
