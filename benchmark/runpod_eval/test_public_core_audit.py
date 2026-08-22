from __future__ import annotations

import json
from pathlib import Path

import pytest
from input_contract import select_inference_inputs
from public_core_audit import build_stratified_audit_manifest
from public_core_sources import content_sha256, sha256_file


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    stage = tmp_path / "stage"
    inputs = stage / "inputs"
    inputs.mkdir(parents=True)
    rows = []
    for index in range(8):
        image = inputs / f"case-{index}.png"
        image.write_bytes(f"image-{index}".encode())
        category = "chart" if index % 2 == 0 else "table"
        rows.append(
            {
                "case_id": f"case-{index}",
                "source_relative_path": f"docs/{category}/source-{index}.pdf",
                "source_sha256": "sha256:" + f"{index + 1:x}" * 64,
                "media_type": "pdf",
                "page_index": 0,
                "input_relative_path": f"inputs/{image.name}",
                "input_sha256": sha256_file(image),
            }
        )
    parent = {
        "schema": "folynta.public-core-inference-inputs.v1",
        "benchmark_id": "parsebench",
        "dataset_revision": "revision-1",
        "ground_truth_mounted": False,
        "source_count": len(rows),
        "input_count": len(rows),
        "complete_source_coverage": True,
        "complete_input_coverage": True,
        "inputs": rows,
    }
    parent["content_sha256"] = content_sha256(parent)
    parent_path = stage / "inference-input-manifest.json"
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    return stage, parent_path, tmp_path / "dataset"


def test_audit_selection_is_stratified_deterministic_and_runtime_bound(
    tmp_path: Path,
) -> None:
    stage, parent, dataset = _fixture(tmp_path)

    first = build_stratified_audit_manifest(
        full_input_manifest=parent,
        benchmark_id="parsebench",
        dataset_root=dataset,
        target_count=4,
        seed="audit-seed",
    )
    second = build_stratified_audit_manifest(
        full_input_manifest=parent,
        benchmark_id="parsebench",
        dataset_root=dataset,
        target_count=4,
        seed="audit-seed",
    )
    audit_path = stage / "audit.json"
    audit_path.write_text(json.dumps(first), encoding="utf-8")
    selection = select_inference_inputs(
        input_dir=stage,
        supported_extensions={".png"},
        limit=0,
        evidence_class="stratified-audit",
        expected_input_count=4,
        input_manifest=audit_path,
        parent_input_manifest=parent,
    )

    assert first == second
    assert first["stratum_count"] == 2
    assert [item["selected_count"] for item in first["stratum_summary"]] == [2, 2]
    assert len(selection.selected) == 4
    assert selection.complete_input_coverage is True


def test_audit_target_must_cover_every_stratum(tmp_path: Path) -> None:
    _stage, parent, dataset = _fixture(tmp_path)

    with pytest.raises(ValueError, match="cover every observed stratum"):
        build_stratified_audit_manifest(
            full_input_manifest=parent,
            benchmark_id="parsebench",
            dataset_root=dataset,
            target_count=1,
            seed="audit-seed",
        )


def test_audit_parent_content_tampering_fails_closed(tmp_path: Path) -> None:
    _stage, parent, dataset = _fixture(tmp_path)
    payload = json.loads(parent.read_text(encoding="utf-8"))
    payload["dataset_revision"] = "tampered"
    parent.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="content hash"):
        build_stratified_audit_manifest(
            full_input_manifest=parent,
            benchmark_id="parsebench",
            dataset_root=dataset,
            target_count=4,
            seed="audit-seed",
        )
