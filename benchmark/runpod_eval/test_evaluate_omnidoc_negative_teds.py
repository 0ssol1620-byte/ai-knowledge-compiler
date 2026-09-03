"""OmniDocBench's own TEDS can fall below zero, and the value must survive intact.

`src/metrics/table_metric.py` computes TEDS as `1.0 - APTED_distance / n_nodes`
with `n_nodes = max(n_nodes_pred, n_nodes_true)`. APTED's cost model charges node
*content* substitution on top of structural insert and delete, so the distance is
not bounded by the node count and the published metric is not bounded below by 0.

Measured 2026-08-18 on the Stage-1 hard-200 run: one table in
`newspaper_TheBostonGlobe-2025-1-8@magazinesclubnew_page_025` scored -0.1086
while its structure-only score was 0.333 -- a table whose shape was roughly right
and whose cell contents were massively over-generated.

The harness used to refuse the whole run over that value. Refusing is wrong (the
evaluator is behaving as implemented) and so is clamping it to 0 (that silently
improves a published number). It is reported as produced, and flagged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evaluate_omnidoc_repeats import extract_official_failures

ARTIFACTS = (
    "text_block_per_page_edit.json",
    "display_formula_per_page_edit.json",
    "table_per_page_edit.json",
    "reading_order_per_page_edit.json",
    "table_per_table_TEDS.json",
)


def _manifest(tmp_path: Path, page: str) -> Path:
    path = tmp_path / "source-manifest.json"
    path.write_text(
        json.dumps(
            {
                "input_count": 1,
                "inputs": [
                    {"case_id": "omnidocbench-a", "source_relative_path": f"images/{page}"}
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _artifacts(tmp_path: Path, overrides: dict[str, dict]) -> Path:
    directory = tmp_path / "official"
    directory.mkdir()
    for name in ARTIFACTS:
        (directory / name).write_text(
            json.dumps(overrides.get(name, {})), encoding="utf-8"
        )
    return directory


def test_a_negative_official_teds_is_reported_not_clamped(tmp_path: Path) -> None:
    page = "doc.png"
    artifacts = _artifacts(
        tmp_path,
        {
            "table_per_table_TEDS.json": {
                f"{page}_[20]": {
                    "TEDS": -0.10857142857142854,
                    "TEDS_structure_only": 0.33333333333333337,
                }
            }
        },
    )
    evidence = extract_official_failures(
        official_artifact_dir=artifacts,
        source_manifest=_manifest(tmp_path, page),
        output_path=tmp_path / "failures.json",
    )
    records = [item for item in evidence["failures"] if item["metric"] == "teds"]
    assert len(records) == 1, evidence
    assert records[0]["official_value"] == -0.10857142857142854
    assert records[0]["score"] == -0.10857142857142854
    assert records[0]["below_official_floor"] is True


def test_a_negative_teds_is_still_counted_as_a_failure(tmp_path: Path) -> None:
    """It is the worst possible table result, not an excluded one."""
    page = "doc.png"
    artifacts = _artifacts(
        tmp_path, {"table_per_table_TEDS.json": {f"{page}_[0]": {"TEDS": -0.5}}}
    )
    evidence = extract_official_failures(
        official_artifact_dir=artifacts,
        source_manifest=_manifest(tmp_path, page),
        output_path=tmp_path / "failures.json",
    )
    assert evidence["failure_count"] == 1


def test_an_ordinary_teds_is_not_flagged(tmp_path: Path) -> None:
    page = "doc.png"
    artifacts = _artifacts(
        tmp_path, {"table_per_table_TEDS.json": {f"{page}_[0]": {"TEDS": 0.9}}}
    )
    evidence = extract_official_failures(
        official_artifact_dir=artifacts,
        source_manifest=_manifest(tmp_path, page),
        output_path=tmp_path / "failures.json",
    )
    assert evidence["failures"][0]["below_official_floor"] is False


def test_a_teds_above_one_is_still_refused(tmp_path: Path) -> None:
    """The relaxation is one-sided. Nothing in the implementation can produce a
    TEDS above 1, so a value above 1 is corruption, not a metric property."""
    page = "doc.png"
    artifacts = _artifacts(
        tmp_path, {"table_per_table_TEDS.json": {f"{page}_[0]": {"TEDS": 1.5}}}
    )
    with pytest.raises(ValueError, match=r"outside \[0,1\]"):
        extract_official_failures(
            official_artifact_dir=artifacts,
            source_manifest=_manifest(tmp_path, page),
            output_path=tmp_path / "failures.json",
        )


def test_an_edit_distance_above_one_is_still_refused(tmp_path: Path) -> None:
    """Edit-distance metrics are normalized and keep the original guard."""
    page = "doc.png"
    artifacts = _artifacts(tmp_path, {"text_block_per_page_edit.json": {page: 1.5}})
    with pytest.raises(ValueError, match=r"outside \[0,1\]"):
        extract_official_failures(
            official_artifact_dir=artifacts,
            source_manifest=_manifest(tmp_path, page),
            output_path=tmp_path / "failures.json",
        )
