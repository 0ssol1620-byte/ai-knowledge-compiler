from __future__ import annotations

from publish_omnidoc_demo_snapshot import DEFAULT_REGISTRY, build, load


def test_registry_builds_only_formal_ground_truth_isolated_candidates() -> None:
    bundle, snapshot = build(load(DEFAULT_REGISTRY))

    assert len(snapshot["datasets"]) >= 3
    assert len(bundle["candidates"]) == len(snapshot["datasets"])
    assert bundle["ground_truth_mounted_on_inference_workers"] is False
    assert all(row["evidence"]["repeat_count"] == 3 for row in snapshot["datasets"])
    assert all(row["evidence"]["hard_failure_count"] == 0 for row in snapshot["datasets"])
    assert all(row["metrics"]["exact_repeat_ratio"] is not None for row in snapshot["datasets"])
