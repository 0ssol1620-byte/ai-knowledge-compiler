import json
from pathlib import Path

import pytest
from stage_public_core_audits import stage_audits


def test_stage_audits_requires_all_three_exact_128_case_manifests(tmp_path: Path) -> None:
    audit_root = tmp_path / "audits"
    worker_root = tmp_path / "workers"
    audit_root.mkdir()
    worker_root.mkdir()

    with pytest.raises(FileNotFoundError):
        stage_audits(
            audit_manifest_root=audit_root,
            staged_worker_root=worker_root,
            output_root=tmp_path / "output",
        )


def test_stage_audits_rejects_non_128_manifest_before_inputs(tmp_path: Path) -> None:
    audit_root = tmp_path / "audits"
    parent_root = (
        tmp_path / "workers" / "worker-00" / "suites" / "parsebench"
    )
    audit_root.mkdir()
    parent_root.mkdir(parents=True)
    parent = {
        "benchmark_id": "parsebench",
        "content_sha256": "sha256:parent",
    }
    (parent_root / "parent-input-manifest.json").write_text(
        json.dumps(parent), encoding="utf-8"
    )
    (audit_root / "parsebench-stratified-audit.json").write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-stratified-audit.v1",
                "benchmark_id": "parsebench",
                "parent_input_manifest_sha256": "sha256:parent",
                "input_count": 1,
                "inputs": [{}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exactly 128"):
        stage_audits(
            audit_manifest_root=audit_root,
            staged_worker_root=tmp_path / "workers",
            output_root=tmp_path / "output",
        )
