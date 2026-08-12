import json
import os
from pathlib import Path

import pytest
from evaluate_omnidoc_repeats import (
    count_frozen_markdown_pages,
    extract_official_failures,
    render_config,
    require_exact_page_count,
    strip_element_suffix,
)


def test_render_config_is_partial_and_keeps_paths_explicit(tmp_path: Path) -> None:
    ground_truth = tmp_path / "gt.json"
    prediction = tmp_path / "markdown-repeat-1"

    rendered = render_config(
        ground_truth=ground_truth,
        prediction=prediction,
        workers=3,
    )

    assert "metric: [Edit_dist, CDM]" not in rendered
    assert "display_formula:\n      metric: [Edit_dist]" in rendered
    assert "metric: [TEDS, Edit_dist]" in rendered
    assert "match_workers: 3" in rendered
    assert "quick_match_truncated_timeout_sec: 60" in rendered
    assert "match_timeout_sec: 90" in rendered
    assert ground_truth.resolve().as_posix() in rendered
    assert prediction.resolve().as_posix() in rendered


def test_render_config_accepts_bounded_stall_recovery_timeouts(tmp_path: Path) -> None:
    rendered = render_config(
        ground_truth=tmp_path / "gt.json",
        prediction=tmp_path / "predictions",
        workers=2,
        quick_match_timeout_seconds=30,
        page_match_timeout_seconds=45,
    )

    assert "quick_match_truncated_timeout_sec: 30" in rendered
    assert "match_timeout_sec: 45" in rendered


def test_page_count_must_match_frozen_prediction_directory(tmp_path: Path) -> None:
    prediction = tmp_path / "markdown-repeat-1"
    prediction.mkdir()
    (prediction / "a.md").write_text("a", encoding="utf-8")
    (prediction / "b.md").write_text("b", encoding="utf-8")
    assert require_exact_page_count({"match_debug": {"page_count": 2}}, prediction) == 2
    with pytest.raises(ValueError, match="expected 2, received 3"):
        require_exact_page_count({"match_debug": {"page_count": 3}}, prediction)


def test_page_count_includes_pages_beyond_the_windows_max_path_limit(
    tmp_path: Path,
) -> None:
    prediction = tmp_path
    while len(str(prediction.resolve())) < 150:
        prediction = prediction / "nested-evidence-segment"
    prediction = prediction / "markdown-repeat-1"
    prediction.mkdir(parents=True)
    (prediction / "short.md").write_text("short", encoding="utf-8")

    # OmniDocBench ships CJK source names; the longest frozen page in the public
    # core run resolves to 291 characters, past the Windows MAX_PATH limit of 260.
    long_name = "book_en_国外数学教材-" + ("漫游" * 60) + "_0035.md"
    long_page = prediction / long_name
    target = str(long_page.resolve())
    assert len(long_name) < 255, "NTFS caps a single path component at 255"
    assert len(target) > 260
    if os.name == "nt":
        target = "\\\\?\\" + target
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("long")

    assert count_frozen_markdown_pages(prediction) == 2
    assert require_exact_page_count({"match_debug": {"page_count": 2}}, prediction) == 2


def test_official_detail_artifacts_bind_exact_nonperfect_elements_to_cases(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "source-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "input_count": 1,
                "inputs": [
                    {
                        "case_id": "omnidocbench-a",
                        "source_relative_path": "images/doc.png",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    artifacts = tmp_path / "official"
    artifacts.mkdir()
    values = {
        "text_block_per_page_edit.json": {"doc.jpg": 0.2},
        "display_formula_per_page_edit.json": {"doc.jpg": 0.0},
        "table_per_page_edit.json": {"doc.jpg": 0.0},
        "reading_order_per_page_edit.json": {"doc.jpg": 0.0},
        "table_per_table_TEDS.json": {
            "doc.jpg_[0]": {"TEDS": 0.9, "TEDS_structure_only": 1.0}
        },
    }
    for name, payload in values.items():
        (artifacts / name).write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "failures.json"
    evidence = extract_official_failures(
        official_artifact_dir=artifacts,
        source_manifest=manifest,
        output_path=output,
    )
    assert evidence["failure_count"] == 2
    assert {item["evaluator_type"] for item in evidence["failures"]} == {
        "text_block",
        "table",
    }
    assert all(item["case_id"] == "omnidocbench-a" for item in evidence["failures"])
    assert all("[" not in item["location_id"] for item in evidence["failures"])


def test_official_detail_keys_keep_bracketed_source_names_intact(
    tmp_path: Path,
) -> None:
    # Four OmniDocBench sources carry a bracketed scan-library prefix inside the
    # page name itself, so only a trailing per-table suffix may be stripped.
    page = "book_en_[搬书匠#893][Pyomo—Optimization Modeling in Python].2012.英文版_page_188.png"
    assert strip_element_suffix(page) == page
    assert strip_element_suffix(f"{page}_[0]") == page

    manifest = tmp_path / "source-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-source-manifest.v1",
                "source_count": 1,
                "sources": [
                    {
                        "case_id": "omnidocbench-bracketed",
                        "source_relative_path": f"images/{page}",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    artifacts = tmp_path / "official"
    artifacts.mkdir()
    values = {
        "text_block_per_page_edit.json": {page: 0.25},
        "display_formula_per_page_edit.json": {page: 0.0},
        "table_per_page_edit.json": {page: 0.0},
        "reading_order_per_page_edit.json": {page: 0.0},
        "table_per_table_TEDS.json": {
            f"{page}_[0]": {"TEDS": 0.8, "TEDS_structure_only": 1.0}
        },
    }
    for name, payload in values.items():
        (artifacts / name).write_text(json.dumps(payload), encoding="utf-8")

    evidence = extract_official_failures(
        official_artifact_dir=artifacts,
        source_manifest=manifest,
        output_path=tmp_path / "failures.json",
    )

    assert evidence["failure_count"] == 2
    assert all(
        item["case_id"] == "omnidocbench-bracketed" for item in evidence["failures"]
    )
    assert {item["source_name"] for item in evidence["failures"]} == {page}


def test_frozen_source_manifest_schema_is_supported(tmp_path: Path) -> None:
    manifest = tmp_path / "source-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-source-manifest.v1",
                "source_count": 1,
                "sources": [
                    {
                        "case_id": "omnidocbench-a",
                        "source_relative_path": "images/doc.png",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    artifacts = tmp_path / "official"
    artifacts.mkdir()
    values = {
        "text_block_per_page_edit.json": {"doc.jpg": 0.0},
        "display_formula_per_page_edit.json": {"doc.jpg": 0.0},
        "table_per_page_edit.json": {"doc.jpg": 0.0},
        "reading_order_per_page_edit.json": {"doc.jpg": 0.0},
        "table_per_table_TEDS.json": {"doc.jpg_[0]": {"TEDS": 1.0}},
    }
    for name, payload in values.items():
        (artifacts / name).write_text(json.dumps(payload), encoding="utf-8")

    evidence = extract_official_failures(
        official_artifact_dir=artifacts,
        source_manifest=manifest,
        output_path=tmp_path / "failures.json",
    )

    assert evidence["source_count"] == 1
    assert evidence["failure_count"] == 0
