"""Re-hash every staged public-core inference input and emit a gate receipt."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from input_contract import select_inference_inputs
from public_core_sources import EXPECTED_SOURCE_COUNTS, content_sha256, write_manifest

SUPPORTED_INPUTS = {".png"}


def verify_staged_inputs(
    *, stage_root: Path, source_manifest_dir: Path
) -> dict[str, Any]:
    datasets: list[dict[str, Any]] = []
    for benchmark_id, expected_count in EXPECTED_SOURCE_COUNTS.items():
        dataset_stage = stage_root / benchmark_id
        input_manifest = dataset_stage / "inference-input-manifest.json"
        source_manifest_path = source_manifest_dir / f"{benchmark_id}-source-manifest.json"
        source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
        selection = select_inference_inputs(
            input_dir=dataset_stage,
            supported_extensions=SUPPORTED_INPUTS,
            limit=0,
            evidence_class="public-core",
            expected_input_count=expected_count,
            input_manifest=input_manifest,
        )
        if selection.benchmark_id != benchmark_id:
            raise ValueError(f"{benchmark_id} staged benchmark identity is invalid")
        if selection.dataset_revision != source_manifest.get("dataset_revision"):
            raise ValueError(f"{benchmark_id} staged revision does not match source manifest")
        staged_manifest = json.loads(input_manifest.read_text(encoding="utf-8"))
        if staged_manifest.get("source_manifest_sha256") != source_manifest.get(
            "content_sha256"
        ):
            raise ValueError(f"{benchmark_id} staged inputs are not bound to source manifest")
        datasets.append(
            {
                "benchmark_id": benchmark_id,
                "dataset_revision": selection.dataset_revision,
                "source_count": expected_count,
                "input_count": len(selection.selected),
                "input_bytes": sum(path.stat().st_size for path in selection.selected),
                "source_manifest_sha256": source_manifest["content_sha256"],
                "input_manifest_sha256": selection.input_manifest_sha256,
                "complete_input_coverage": selection.complete_input_coverage,
                "ground_truth_mounted": False,
                "passed": True,
            }
        )
    receipt: dict[str, Any] = {
        "schema": "folynta.public-core-staged-input-verification.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "ground_truth_mount_policy": "evaluator-only",
        "inference_ground_truth_access": "forbidden",
        "total_source_count": sum(item["source_count"] for item in datasets),
        "total_input_count": sum(item["input_count"] for item in datasets),
        "total_input_bytes": sum(item["input_bytes"] for item in datasets),
        "datasets": datasets,
        "gate": "PASS",
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--source-manifest-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = verify_staged_inputs(
        stage_root=args.stage_root,
        source_manifest_dir=args.source_manifest_dir,
    )
    write_manifest(args.output, receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["verify_staged_inputs"]
