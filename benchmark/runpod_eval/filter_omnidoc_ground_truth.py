#!/usr/bin/env python3
"""Create an evaluator-only OmniDocBench ground-truth subset.

The inference manifest contains filenames and source hashes only.  This tool
joins those filenames to the official annotation locally, refuses missing or
duplicate rows, and emits both the evaluator input and a hash receipt.  The
result must never be copied into an inference bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_subset(annotation: object, manifest: object) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(annotation, list) or not all(isinstance(row, dict) for row in annotation):
        raise ValueError("OmniDocBench annotation must be a list of objects")
    if not isinstance(manifest, dict) or manifest.get("ground_truth_mounted") is not False:
        raise ValueError("inference manifest must explicitly record absent ground truth")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or int(manifest.get("case_count", -1)) != len(cases):
        raise ValueError("inference manifest case count is invalid")

    requested: list[str] = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("filename"), str):
            raise ValueError("every inference case requires a filename")
        filename = Path(case["filename"]).name
        if filename != case["filename"]:
            raise ValueError("inference filenames must be basenames")
        requested.append(filename)
    if len(set(requested)) != len(requested):
        raise ValueError("duplicate inference filenames are forbidden")

    indexed: dict[str, dict[str, Any]] = {}
    for row in annotation:
        page_info = row.get("page_info")
        image_path = page_info.get("image_path") if isinstance(page_info, dict) else None
        if not isinstance(image_path, str):
            raise ValueError("annotation row is missing page_info.image_path")
        filename = Path(image_path).name
        if filename in indexed:
            raise ValueError(f"duplicate annotation image_path: {filename}")
        indexed[filename] = row

    missing = [filename for filename in requested if filename not in indexed]
    if missing:
        raise ValueError(f"annotation is missing inference cases: {missing}")
    return [indexed[filename] for filename in requested], requested


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotation", type=Path, required=True)
    parser.add_argument("--inference-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.receipt_out.exists():
        raise SystemExit("output paths must not already exist")

    annotation_bytes = args.annotation.read_bytes()
    manifest_bytes = args.inference_manifest.read_bytes()
    subset, filenames = build_subset(
        json.loads(annotation_bytes),
        json.loads(manifest_bytes),
    )
    output_bytes = (
        json.dumps(subset, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output_bytes)
    receipt = {
        "schema_version": "1.0.0",
        "role": "evaluator_only_ground_truth",
        "ground_truth_mounted_on_inference_worker": False,
        "case_count": len(subset),
        "filenames": filenames,
        "source_annotation_sha256": sha256_bytes(annotation_bytes),
        "inference_manifest_sha256": sha256_bytes(manifest_bytes),
        "subset_sha256": sha256_bytes(output_bytes),
    }
    args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_out.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
