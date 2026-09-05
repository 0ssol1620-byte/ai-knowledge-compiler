from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
from arena.manifest.build import ManifestBuildError, build_campaign, load_source_rows


def test_happy_path_builds_all_three_benchmarks(config_factory: Any) -> None:
    config = config_factory(per_benchmark=3)

    result = build_campaign(config, force=True)

    assert result.unchanged is False
    assert result.gt_isolation_passed is True
    assert result.total_samples == 9
    assert result.per_benchmark_counts == {"parsebench": 3, "omnidoc": 3, "olmocr": 3}
    assert result.source_manifest_path.is_file()
    assert result.campaign_manifest_path.is_file()
    assert result.canary_selection_path.is_file()
    assert result.gt_isolation_receipt_path.is_file()

    rows = load_source_rows(result.source_manifest_path)
    assert len(rows) == 9
    sample_ids = {row["sample_id"] for row in rows}
    assert len(sample_ids) == 9  # all unique
    for row in rows:
        assert row["schema"] == "tavonel.arena.source-row.v1"
        assert row["campaign_id"] == config.campaign_id
        assert set(row["preflight"]) == {
            "near_white_ratio",
            "render_entropy",
            "mean_intensity",
            "edge_density",
            "is_probably_blank",
        }

    campaign_manifest = json.loads(result.campaign_manifest_path.read_text(encoding="utf-8"))
    assert campaign_manifest["schema"] == "tavonel.arena.campaign-manifest.v1"
    assert campaign_manifest["total_samples"] == 9
    assert campaign_manifest["campaign_id"] == config.campaign_id
    for benchmark in ("parsebench", "omnidoc", "olmocr"):
        assert campaign_manifest["benchmarks"][benchmark]["sample_count"] == 3
    assert campaign_manifest["canary"]["salt"] == config.canary_salt
    assert campaign_manifest["gt_isolation_receipt_sha256"].startswith("sha256:")

    canary_selection = json.loads(result.canary_selection_path.read_text(encoding="utf-8"))
    assert canary_selection["schema"] == "tavonel.arena.canary-selection.v1"
    assert canary_selection["gpu_canary"]["per_benchmark_selected"] == {
        "parsebench": 2,
        "omnidoc": 2,
        "olmocr": 2,
    }


def test_sample_count_mismatch_raises(config_factory: Any) -> None:
    config = config_factory(
        per_benchmark=3, expected_counts={"parsebench": 4, "omnidoc": 3, "olmocr": 3}
    )

    with pytest.raises(ManifestBuildError, match="sample count"):
        build_campaign(config, force=True)


def test_dataset_revision_drift_raises(config_factory: Any) -> None:
    # The staged manifests are written with revisions {b: f"rev-{b}"}, but the
    # BenchmarkSource records (fed from the "lock file") disagree with one.
    config = config_factory()
    poisoned_benchmarks = tuple(
        dataclasses.replace(source, dataset_revision="a-different-revision")
        if source.key == "omnidoc"
        else source
        for source in config.benchmarks
    )
    poisoned_config = dataclasses.replace(config, benchmarks=poisoned_benchmarks)

    with pytest.raises(ManifestBuildError, match="dataset_revision"):
        build_campaign(poisoned_config, force=True)


def test_duplicate_sample_id_within_staged_manifest_raises(
    config_factory: Any, default_items_factory: Any
) -> None:
    items = {b: default_items_factory(b, 3) for b in ("parsebench", "omnidoc", "olmocr")}
    # Same source document + page referenced under two different staged case
    # ids -> identical sample_id, distinct case_key. This is exactly the bug
    # class inference_job_id de-duplication depends on catching.
    duplicate = dict(items["omnidoc"][0])
    duplicate["case_id"] = duplicate["case_id"] + "-relabelled"
    items["omnidoc"].append(duplicate)

    config = config_factory(
        items_by_benchmark=items,
        expected_counts={"parsebench": 3, "omnidoc": 4, "olmocr": 3},
    )

    with pytest.raises(ManifestBuildError, match="duplicate sample_id"):
        build_campaign(config, force=True)


def test_duplicate_case_key_within_staged_manifest_raises(
    config_factory: Any, default_items_factory: Any
) -> None:
    items = {b: default_items_factory(b, 3) for b in ("parsebench", "omnidoc", "olmocr")}
    # Two entries sharing a case_id but pointing at different source pages.
    duplicate = dict(items["olmocr"][0])
    duplicate["source_relative_path"] = "bench_data/pdfs/some_other_doc.pdf"
    items["olmocr"].append(duplicate)

    config = config_factory(
        items_by_benchmark=items,
        expected_counts={"parsebench": 3, "omnidoc": 3, "olmocr": 4},
    )

    with pytest.raises(ManifestBuildError, match="duplicate case_key"):
        build_campaign(config, force=True)


def test_zero_byte_png_is_rejected(config_factory: Any) -> None:
    config = config_factory(per_benchmark=2)
    zero_png = config.benchmarks[0].inputs_root / "inputs" / "parsebench-case000.png"
    zero_png.write_bytes(b"")

    with pytest.raises(ManifestBuildError, match="zero bytes"):
        build_campaign(config, force=True)


def test_staged_manifest_content_hash_tamper_is_rejected(config_factory: Any) -> None:
    config = config_factory(per_benchmark=2)
    staged_path = config.benchmarks[0].inputs_root / "inference-input-manifest.json"
    manifest = json.loads(staged_path.read_text(encoding="utf-8"))
    manifest["source_count"] = manifest["source_count"] + 100  # tamper without rehashing
    staged_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ManifestBuildError, match="content hash"):
        build_campaign(config, force=True)


def test_rebuild_without_force_is_a_fast_noop_when_nothing_changed(config_factory: Any) -> None:
    config = config_factory(per_benchmark=2)

    first = build_campaign(config, force=True)
    assert first.unchanged is False

    second = build_campaign(config, force=False)
    assert second.unchanged is True
    assert second.total_samples == first.total_samples
    assert second.per_benchmark_counts == first.per_benchmark_counts


def test_force_rebuild_after_a_staged_input_changes_picks_up_new_hash(
    config_factory: Any,
) -> None:
    config = config_factory(per_benchmark=2)
    build_campaign(config, force=True)

    staged_path = config.benchmarks[0].inputs_root / "inference-input-manifest.json"
    manifest = json.loads(staged_path.read_text(encoding="utf-8"))
    assert manifest["input_count"] == 2

    # Without --force, a change to a staged manifest that build() doesn't
    # re-inspect (because the shortcut thinks it's current) must not be
    # silently accepted forever: verify the shortcut path actually compares
    # staged_manifest_content_sha256, by tampering the recorded campaign
    # manifest's hash for this benchmark and confirming build() then treats
    # the campaign as no longer current.
    campaign_manifest_path = config.output_campaign_manifest
    campaign_manifest = json.loads(campaign_manifest_path.read_text(encoding="utf-8"))
    campaign_manifest["benchmarks"]["parsebench"]["staged_manifest_content_sha256"] = (
        "sha256:" + "0" * 64
    )
    campaign_manifest_path.write_text(json.dumps(campaign_manifest), encoding="utf-8")

    result = build_campaign(config, force=False)
    assert result.unchanged is False


def test_gt_isolation_failure_surfaces_as_manifest_build_error(config_factory: Any) -> None:
    # A planted non-.png file inside an inputs root must fail the build's own
    # internal isolation audit, not just a standalone `audit` re-run.
    config = config_factory(per_benchmark=2)
    leaked = config.benchmarks[1].inputs_root / "inputs" / "leaked.jsonl"
    leaked.write_text("{}", encoding="utf-8")

    with pytest.raises(ManifestBuildError, match="GT isolation audit FAILED"):
        build_campaign(config, force=True)
