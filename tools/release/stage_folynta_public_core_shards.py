"""Materialize source-only worker directories from a frozen shard plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


def _canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def stage_worker_inputs(
    *,
    plan_path: Path,
    manifest_paths: tuple[Path, ...],
    output_root: Path,
) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    manifests = {
        str(value["benchmark_id"]): (path, value)
        for path in manifest_paths
        for value in (json.loads(path.read_text(encoding="utf-8")),)
    }
    if set(manifests) != {str(suite["benchmark_id"]) for suite in plan["suites"]}:
        raise ValueError("plan and parent manifests cover different suites")
    if output_root.exists():
        raise FileExistsError(f"staging output already exists: {output_root}")

    worker_count = int(plan["worker_count"])
    staged_count = 0
    for worker_index in range(worker_count):
        worker_root = output_root / f"worker-{worker_index:02d}"
        worker_receipt: dict[str, Any] = {
            "schema": "folynta.public-core-worker-inputs.v1",
            "worker_index": worker_index,
            "worker_count": worker_count,
            "campaign_plan_sha256": plan["plan_sha256"],
            "ground_truth_mounted": False,
            "suites": [],
        }
        for suite in plan["suites"]:
            benchmark_id = str(suite["benchmark_id"])
            parent_path, parent = manifests[benchmark_id]
            shard = suite["shards"][worker_index]
            suite_root = worker_root / "suites" / benchmark_id
            input_root = suite_root / "inputs"
            input_root.mkdir(parents=True)
            parent_copy = suite_root / "parent-input-manifest.json"
            shutil.copy2(parent_path, parent_copy)

            parent_by_case = {str(item["case_id"]): item for item in parent["inputs"]}
            shard_inputs: list[dict[str, Any]] = []
            for planned in shard["inputs"]:
                case_id = str(planned["case_id"])
                item = parent_by_case[case_id]
                source = parent_path.parent / str(item["input_relative_path"])
                target = input_root / Path(str(item["input_relative_path"])).name
                if not source.is_file():
                    raise FileNotFoundError(source)
                os.link(source, target)
                shard_item = dict(item)
                shard_item["input_relative_path"] = f"inputs/{target.name}"
                shard_inputs.append(shard_item)
                staged_count += 1

            shard_manifest: dict[str, Any] = {
                "schema": "folynta.public-core-inference-shard.v1",
                "benchmark_id": benchmark_id,
                "dataset_revision": parent["dataset_revision"],
                "ground_truth_mounted": False,
                "source_count": parent["source_count"],
                "input_count": len(shard_inputs),
                "complete_source_coverage": False,
                "complete_input_coverage": True,
                "parent_input_manifest_sha256": parent["content_sha256"],
                "campaign_plan_sha256": plan["plan_sha256"],
                "shard_manifest_sha256": shard["manifest_sha256"],
                "shard_index": worker_index,
                "shard_count": worker_count,
                "inputs": shard_inputs,
            }
            shard_manifest["content_sha256"] = _canonical_sha256(shard_manifest)
            shard_path = suite_root / "shard-input-manifest.json"
            shard_path.write_text(
                json.dumps(shard_manifest, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            worker_receipt["suites"].append(
                {
                    "benchmark_id": benchmark_id,
                    "input_count": len(shard_inputs),
                    "shard_input_manifest_sha256": shard_manifest["content_sha256"],
                }
            )
        worker_receipt["input_count"] = sum(
            int(suite["input_count"]) for suite in worker_receipt["suites"]
        )
        worker_receipt["receipt_sha256"] = _canonical_sha256(worker_receipt)
        (worker_root / "worker-input-receipt.json").write_text(
            json.dumps(worker_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if staged_count != int(plan["total_input_count"]):
        raise ValueError("staged worker inputs do not cover the complete campaign")
    return {
        "schema": "folynta.public-core-worker-staging.v1",
        "worker_count": worker_count,
        "input_count": staged_count,
        "campaign_plan_sha256": plan["plan_sha256"],
        "ground_truth_mounted": False,
        "output_root": str(output_root),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--manifest", action="append", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = stage_worker_inputs(
        plan_path=args.plan,
        manifest_paths=tuple(args.manifest),
        output_root=args.output_root,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
