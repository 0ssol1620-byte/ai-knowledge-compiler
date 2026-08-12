from __future__ import annotations

import json
from pathlib import Path

import pytest
from public_core_sources import EXPECTED_SOURCE_COUNTS, content_sha256, sha256_file
from verify_staged_public_core_inputs import verify_staged_inputs


def _fixture_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    stage_root = tmp_path / "stage"
    sources = tmp_path / "sources"
    sources.mkdir()
    for benchmark_id in tuple(EXPECTED_SOURCE_COUNTS):
        monkeypatch.setitem(EXPECTED_SOURCE_COUNTS, benchmark_id, 1)
        revision = f"{benchmark_id}-revision"
        source_manifest = {
            "schema": "folynta.public-core-source-manifest.v1",
            "benchmark_id": benchmark_id,
            "dataset_revision": revision,
            "ground_truth_mounted": False,
            "source_count": 1,
            "complete_source_coverage": True,
            "sources": [],
        }
        source_manifest["content_sha256"] = content_sha256(source_manifest)
        (sources / f"{benchmark_id}-source-manifest.json").write_text(
            json.dumps(source_manifest), encoding="utf-8"
        )
        dataset_stage = stage_root / benchmark_id
        inputs = dataset_stage / "inputs"
        inputs.mkdir(parents=True)
        image = inputs / "case.png"
        image.write_bytes(f"{benchmark_id}-input".encode())
        input_manifest = {
            "schema": "folynta.public-core-inference-inputs.v1",
            "benchmark_id": benchmark_id,
            "dataset_revision": revision,
            "source_manifest_sha256": source_manifest["content_sha256"],
            "ground_truth_mounted": False,
            "source_count": 1,
            "input_count": 1,
            "complete_source_coverage": True,
            "complete_input_coverage": True,
            "inputs": [
                {
                    "case_id": f"{benchmark_id}-case",
                    "input_relative_path": "inputs/case.png",
                    "input_sha256": sha256_file(image),
                }
            ],
        }
        input_manifest["content_sha256"] = content_sha256(input_manifest)
        (dataset_stage / "inference-input-manifest.json").write_text(
            json.dumps(input_manifest), encoding="utf-8"
        )
    return stage_root, sources


def test_verifier_rehashes_every_staged_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stages, sources = _fixture_stages(tmp_path, monkeypatch)

    receipt = verify_staged_inputs(stage_root=stages, source_manifest_dir=sources)

    assert receipt["gate"] == "PASS"
    assert receipt["total_source_count"] == 3
    assert receipt["total_input_count"] == 3
    assert receipt["receipt_sha256"] == content_sha256(receipt)


def test_verifier_rejects_a_mutated_staged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stages, sources = _fixture_stages(tmp_path, monkeypatch)
    (stages / "parsebench/inputs/case.png").write_bytes(b"mutated")

    with pytest.raises(ValueError, match="hash does not match"):
        verify_staged_inputs(stage_root=stages, source_manifest_dir=sources)
