from __future__ import annotations

import json
from pathlib import Path

from tools.release.plan_folynta_public_core_shards import build_campaign_plan


def _manifest(path: Path) -> Path:
    value = {
        "benchmark_id": "omnidocbench",
        "dataset_revision": "revision-1",
        "source_manifest_sha256": "sha256:" + "a" * 64,
        "inputs": [
            {
                "case_id": "case-1",
                "source_relative_path": "docs/report_page_001.png",
                "page_index": 0,
                "input_relative_path": "inputs/case-1.png",
                "input_sha256": "sha256:" + "1" * 64,
            },
            {
                "case_id": "case-2",
                "source_relative_path": "docs/report_page_002.png",
                "page_index": 1,
                "input_relative_path": "inputs/case-2.png",
                "input_sha256": "sha256:" + "2" * 64,
            },
            {
                "case_id": "case-3",
                "source_relative_path": "docs/other_pg7.pdf",
                "page_index": 0,
                "input_relative_path": "inputs/case-3.png",
                "input_sha256": "sha256:" + "3" * 64,
            },
        ],
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_plan_preserves_documents_and_forces_retry_to_another_worker(tmp_path: Path) -> None:
    plan = build_campaign_plan(
        manifests=(_manifest(tmp_path / "manifest.json"),),
        worker_count=4,
        estimated_seconds_per_page=10.0,
    )

    inputs = [item for shard in plan["suites"][0]["shards"] for item in shard["inputs"]]
    report_pages = [item for item in inputs if item["document_id"].endswith("docs/report")]
    assert len({item["primary_worker_index"] for item in report_pages}) == 1
    assert all(item["retry_worker_index"] != item["primary_worker_index"] for item in inputs)
    assert plan["total_input_count"] == 3
    assert plan["ground_truth_mounted_on_workers"] is False


def test_plan_is_deterministic(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    first = build_campaign_plan(
        manifests=(manifest,), worker_count=4, estimated_seconds_per_page=10.0
    )
    second = build_campaign_plan(
        manifests=(manifest,), worker_count=4, estimated_seconds_per_page=10.0
    )
    assert first == second
