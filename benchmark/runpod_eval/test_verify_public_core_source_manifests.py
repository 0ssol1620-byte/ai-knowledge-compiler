from __future__ import annotations

import json
from pathlib import Path

import pytest
from public_core_sources import EXPECTED_SOURCE_COUNTS, content_sha256
from verify_public_core_source_manifests import verify_source_manifests


def _fixture_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    datasets = []
    for benchmark_id in tuple(EXPECTED_SOURCE_COUNTS):
        monkeypatch.setitem(EXPECTED_SOURCE_COUNTS, benchmark_id, 1)
        revision = f"{benchmark_id}-revision"
        manifest = {
            "schema": "folynta.public-core-source-manifest.v1",
            "benchmark_id": benchmark_id,
            "dataset_revision": revision,
            "ground_truth_mounted": False,
            "source_count": 1,
            "complete_source_coverage": True,
            "sources": [
                {
                    "case_id": f"{benchmark_id}-case",
                    "source_relative_path": "source.pdf",
                    "source_sha256": "sha256:" + "1" * 64,
                    "media_type": "pdf",
                    "page_index": 0,
                }
            ],
        }
        manifest["content_sha256"] = content_sha256(manifest)
        (manifests / f"{benchmark_id}-source-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        datasets.append(
            {
                "benchmark_id": benchmark_id,
                "dataset_revision": revision,
                "passed": True,
            }
        )
    acquisition = {
        "gate": "PASS",
        "receipt_sha256": "sha256:" + "2" * 64,
        "datasets": datasets,
    }
    acquisition_path = tmp_path / "acquisition.json"
    acquisition_path.write_text(json.dumps(acquisition), encoding="utf-8")
    return acquisition_path, manifests


def test_verifier_accepts_exact_source_only_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acquisition, manifests = _fixture_files(tmp_path, monkeypatch)

    receipt = verify_source_manifests(
        acquisition_receipt=acquisition,
        manifest_dir=manifests,
    )

    assert receipt["gate"] == "PASS"
    assert receipt["total_source_count"] == 3
    assert receipt["receipt_sha256"] == content_sha256(receipt)


def test_verifier_rejects_a_forbidden_ground_truth_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acquisition, manifests = _fixture_files(tmp_path, monkeypatch)
    path = manifests / "parsebench-source-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["sources"][0]["expected_markdown"] = "forbidden"
    manifest["content_sha256"] = content_sha256(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden fields"):
        verify_source_manifests(
            acquisition_receipt=acquisition,
            manifest_dir=manifests,
        )
