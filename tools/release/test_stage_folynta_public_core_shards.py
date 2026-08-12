from __future__ import annotations

import json
from pathlib import Path

from tools.release.plan_folynta_public_core_shards import build_campaign_plan
from tools.release.stage_folynta_public_core_shards import (
    _canonical_sha256,
    stage_worker_inputs,
)


def test_stage_worker_inputs_keeps_ground_truth_out_and_covers_every_input(
    tmp_path: Path,
) -> None:
    suite_root = tmp_path / "suite"
    inputs_root = suite_root / "inputs"
    inputs_root.mkdir(parents=True)
    inputs = []
    for index in range(4):
        image = inputs_root / f"case-{index}.png"
        image.write_bytes(f"image-{index}".encode())
        inputs.append(
            {
                "case_id": f"case-{index}",
                "source_relative_path": f"images/doc-{index}_page_001.png",
                "page_index": 0,
                "input_relative_path": f"inputs/{image.name}",
                "input_sha256": "sha256:"
                + __import__("hashlib").sha256(image.read_bytes()).hexdigest(),
            }
        )
    parent = {
        "schema": "folynta.public-core-inference-inputs.v1",
        "benchmark_id": "omnidocbench",
        "dataset_revision": "revision-1",
        "source_manifest_sha256": "sha256:" + "a" * 64,
        "ground_truth_mounted": False,
        "source_count": 4,
        "input_count": 4,
        "complete_source_coverage": True,
        "complete_input_coverage": True,
        "inputs": inputs,
    }
    parent["content_sha256"] = _canonical_sha256(parent)
    parent_path = suite_root / "inference-input-manifest.json"
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    plan = build_campaign_plan(
        manifests=(parent_path,), worker_count=2, estimated_seconds_per_page=1.0
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    receipt = stage_worker_inputs(
        plan_path=plan_path,
        manifest_paths=(parent_path,),
        output_root=tmp_path / "workers",
    )

    staged = list((tmp_path / "workers").rglob("*.png"))
    assert len(staged) == 4
    assert receipt["input_count"] == 4
    assert receipt["ground_truth_mounted"] is False
    for manifest_path in (tmp_path / "workers").rglob("shard-input-manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["ground_truth_mounted"] is False
        assert "label" not in manifest
