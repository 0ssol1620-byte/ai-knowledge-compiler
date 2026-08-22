from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.runpod_eval.public_core_sources import content_sha256, sha256_file
from tools.release.verify_folynta_public_audits import BENCHMARK_IDS, verify_public_audits


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    stage_root = tmp_path / "stage"
    audits = tmp_path / "audits"
    audits.mkdir()
    for benchmark_id in BENCHMARK_IDS:
        stage = stage_root / benchmark_id
        inputs = stage / "inputs"
        inputs.mkdir(parents=True)
        rows = []
        for index in range(3):
            image = inputs / f"case-{index}.png"
            image.write_bytes(f"{benchmark_id}-{index}".encode())
            rows.append(
                {
                    "case_id": f"{benchmark_id}-case-{index}",
                    "source_relative_path": f"source-{index}.pdf",
                    "source_sha256": "sha256:" + str(index + 1) * 64,
                    "media_type": "pdf",
                    "page_index": 0,
                    "input_relative_path": f"inputs/{image.name}",
                    "input_sha256": sha256_file(image),
                }
            )
        full = {
            "schema": "folynta.public-core-inference-inputs.v1",
            "benchmark_id": benchmark_id,
            "dataset_revision": f"{benchmark_id}-revision",
            "ground_truth_mounted": False,
            "source_count": 3,
            "input_count": 3,
            "complete_source_coverage": True,
            "complete_input_coverage": True,
            "inputs": rows,
        }
        full["content_sha256"] = content_sha256(full)
        (stage / "inference-input-manifest.json").write_text(
            json.dumps(full), encoding="utf-8"
        )
        audit = {
            "schema": "folynta.public-core-stratified-audit.v1",
            "benchmark_id": benchmark_id,
            "dataset_revision": full["dataset_revision"],
            "parent_input_manifest_sha256": full["content_sha256"],
            "ground_truth_mounted": False,
            "source_count": 3,
            "input_count": 1,
            "complete_source_coverage": False,
            "complete_input_coverage": True,
            "stratified": True,
            "audit_seed": "seed-1",
            "stratum_count": 1,
            "selection_sha256": "sha256:" + "a" * 64,
            "inputs": rows[:1],
        }
        audit["content_sha256"] = content_sha256(audit)
        (audits / f"{benchmark_id}-stratified-audit.json").write_text(
            json.dumps(audit), encoding="utf-8"
        )
    return stage_root, audits


def test_verifier_rehashes_all_audits_and_quantifies_saved_work(tmp_path: Path) -> None:
    stages, audits = _fixture(tmp_path)

    receipt = verify_public_audits(stage_root=stages, audit_manifest_dir=audits)

    assert receipt["gate"] == "PASS"
    assert receipt["total_source_count"] == 9
    assert receipt["total_audit_input_count"] == 3
    assert receipt["blind_three_full_page_inferences"] == 27
    assert receipt["adaptive_stable_page_inferences"] == 18
    assert receipt["saved_page_inferences"] == 9


def test_verifier_rejects_an_audit_bound_to_a_different_parent(tmp_path: Path) -> None:
    stages, audits = _fixture(tmp_path)
    path = audits / "parsebench-stratified-audit.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    audit["parent_input_manifest_sha256"] = "sha256:" + "f" * 64
    audit["content_sha256"] = content_sha256(audit)
    path.write_text(json.dumps(audit), encoding="utf-8")

    with pytest.raises(ValueError, match="parent manifest hash does not match"):
        verify_public_audits(stage_root=stages, audit_manifest_dir=audits)
