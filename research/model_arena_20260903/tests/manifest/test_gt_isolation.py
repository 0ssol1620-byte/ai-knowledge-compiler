from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arena.manifest.build import BuildConfig, build_campaign
from arena.manifest.gt_isolation import GtIsolationError, run_gt_isolation_audit


def _roots_from_config(config: BuildConfig) -> dict[str, Path]:
    return {source.key: source.inputs_root for source in config.benchmarks}


def _staged_manifests_from_config(config: BuildConfig) -> dict[str, dict[str, Any]]:
    return {
        source.key: json.loads(
            (source.inputs_root / "inference-input-manifest.json").read_text(encoding="utf-8")
        )
        for source in config.benchmarks
    }


def test_clean_tree_passes_every_check(config_factory: Any) -> None:
    config = config_factory()
    build_campaign(config, force=True)

    receipt = run_gt_isolation_audit(
        campaign_id=config.campaign_id,
        inputs_roots=_roots_from_config(config),
        acquired_root=config.acquired_root,
        evaluator_cache_root=config.evaluator_cache_root,
        source_manifest_path=config.output_source_manifest,
        staged_manifests=_staged_manifests_from_config(config),
    )

    assert receipt["passed"] is True
    assert all(check["passed"] for check in receipt["checks"])
    assert receipt["gt_roots"] == [str(config.acquired_root), str(config.evaluator_cache_root)]


def test_gt_root_inside_inputs_root_fails_overlap_check(config_factory: Any) -> None:
    config = config_factory()
    build_campaign(config, force=True)

    poisoned_acquired_root = next(iter(_roots_from_config(config).values())) / "inputs"

    receipt = run_gt_isolation_audit(
        campaign_id=config.campaign_id,
        inputs_roots=_roots_from_config(config),
        acquired_root=poisoned_acquired_root,
        evaluator_cache_root=config.evaluator_cache_root,
        source_manifest_path=config.output_source_manifest,
        staged_manifests=_staged_manifests_from_config(config),
    )

    assert receipt["passed"] is False
    overlap_check = next(c for c in receipt["checks"] if c["name"] == "gt-inputs-path-overlap")
    assert overlap_check["passed"] is False


def test_planted_non_png_file_inside_inputs_root_fails(
    tmp_path: Path,
    staged_tree_builder: Any,
    fake_lock_writer: Any,
    default_items_factory: Any,
    staged_ids: dict[str, str],
) -> None:
    revisions = {"parsebench": "r1", "omnidoc": "r2", "olmocr": "r3"}
    items = {b: default_items_factory(b, 3) for b in ("parsebench", "omnidoc", "olmocr")}
    stage_root = tmp_path / "staged-public-core"
    staged_tree_builder(
        stage_root,
        items_by_benchmark=items,
        revisions=revisions,
        extra_files={"omnidoc": ["inputs/leaked_ground_truth.jsonl"]},
    )
    fake_lock_writer(tmp_path / "benchmark-registry.lock.yaml", revisions)

    inputs_roots = {b: stage_root / staged_ids[b] for b in items}
    staged_manifests = {
        b: json.loads((root / "inference-input-manifest.json").read_text(encoding="utf-8"))
        for b, root in inputs_roots.items()
    }
    source_manifest_path = tmp_path / "source_manifest.jsonl"
    source_manifest_path.write_text("", encoding="utf-8")

    receipt = run_gt_isolation_audit(
        campaign_id="C",
        inputs_roots=inputs_roots,
        acquired_root=tmp_path / "acquired",
        evaluator_cache_root=tmp_path / "evaluator-cache",
        source_manifest_path=source_manifest_path,
        staged_manifests=staged_manifests,
    )

    assert receipt["passed"] is False
    whitelist_check = next(
        c for c in receipt["checks"] if c["name"] == "inputs-root-whitelist:omnidoc"
    )
    assert whitelist_check["passed"] is False
    assert "leaked_ground_truth" in whitelist_check["detail"]


def test_forbidden_field_in_source_manifest_row_fails(config_factory: Any) -> None:
    config = config_factory()
    build_campaign(config, force=True)

    rows = [
        json.loads(line)
        for line in config.output_source_manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows[0]["expected_text"] = "this must never appear"
    config.output_source_manifest.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    receipt = run_gt_isolation_audit(
        campaign_id=config.campaign_id,
        inputs_roots=_roots_from_config(config),
        acquired_root=config.acquired_root,
        evaluator_cache_root=config.evaluator_cache_root,
        source_manifest_path=config.output_source_manifest,
        staged_manifests=_staged_manifests_from_config(config),
    )

    assert receipt["passed"] is False
    field_check = next(
        c for c in receipt["checks"] if c["name"] == "source-manifest-fields-and-uniqueness"
    )
    assert field_check["passed"] is False
    assert "extra=" in field_check["detail"]


def test_duplicate_sample_id_in_manifest_file_fails(config_factory: Any) -> None:
    config = config_factory()
    build_campaign(config, force=True)

    lines = [
        line
        for line in config.output_source_manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    first_row = json.loads(lines[0])
    duplicate_row = dict(first_row)
    duplicate_row["case_key"] = duplicate_row["case_key"] + "-dup"
    lines.append(json.dumps(duplicate_row, ensure_ascii=False))
    config.output_source_manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    receipt = run_gt_isolation_audit(
        campaign_id=config.campaign_id,
        inputs_roots=_roots_from_config(config),
        acquired_root=config.acquired_root,
        evaluator_cache_root=config.evaluator_cache_root,
        source_manifest_path=config.output_source_manifest,
        staged_manifests=_staged_manifests_from_config(config),
    )

    assert receipt["passed"] is False
    field_check = next(
        c for c in receipt["checks"] if c["name"] == "source-manifest-fields-and-uniqueness"
    )
    assert "duplicate sample_id" in field_check["detail"]


def test_staged_manifest_with_gt_mounted_true_fails(config_factory: Any) -> None:
    config = config_factory()
    build_campaign(config, force=True)

    staged_manifests = _staged_manifests_from_config(config)
    poisoned_key = next(iter(staged_manifests))
    staged_manifests[poisoned_key]["ground_truth_mounted"] = True

    receipt = run_gt_isolation_audit(
        campaign_id=config.campaign_id,
        inputs_roots=_roots_from_config(config),
        acquired_root=config.acquired_root,
        evaluator_cache_root=config.evaluator_cache_root,
        source_manifest_path=config.output_source_manifest,
        staged_manifests=staged_manifests,
    )

    assert receipt["passed"] is False
    gt_check = next(c for c in receipt["checks"] if c["name"] == "staged-manifest-gt-free")
    assert gt_check["passed"] is False


def test_missing_source_manifest_raises(config_factory: Any) -> None:
    config = config_factory()
    build_campaign(config, force=True)
    config.output_source_manifest.unlink()

    with pytest.raises(GtIsolationError):
        run_gt_isolation_audit(
            campaign_id=config.campaign_id,
            inputs_roots=_roots_from_config(config),
            acquired_root=config.acquired_root,
            evaluator_cache_root=config.evaluator_cache_root,
            source_manifest_path=config.output_source_manifest,
            staged_manifests=_staged_manifests_from_config(config),
        )
