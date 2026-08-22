from __future__ import annotations

import json
import tarfile
from pathlib import Path

from package_selective_recovery_inputs import package_selective_inputs


def test_selective_packages_contain_only_source_inputs_and_manifests(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    suite = staging / "worker-02" / "suites" / "parsebench"
    inputs = suite / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "parsebench-a.png").write_bytes(b"image")
    (suite / "parent-input-manifest.json").write_text("{}", encoding="utf-8")
    (suite / "shard-input-manifest.json").write_text("{}", encoding="utf-8")
    (staging / "selective-recovery-receipt.json").write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-selective-recovery-staging.v1",
                "recovery_model": "mineru-3.4.4-vlm-quality-retry",
                "input_count": 1,
                "eligible_recovery_workers": [0, 1, 2, 3],
                "workers": [
                    {
                        "recovery_worker_index": 2,
                        "input_count": 1,
                        "suites": [{"benchmark_id": "parsebench"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "packages"
    receipt = package_selective_inputs(staging_root=staging, output_root=output)

    assert receipt["input_count"] == 1
    assert receipt["recovery_model"] == "mineru-3.4.4-vlm-quality-retry"
    archive = output / receipt["packages"][0]["archive"]
    with tarfile.open(archive, "r:gz") as bundle:
        names = sorted(member.name for member in bundle.getmembers() if member.isfile())
    assert names == [
        "worker-02/suites/parsebench/inputs/parsebench-a.png",
        "worker-02/suites/parsebench/parent-input-manifest.json",
        "worker-02/suites/parsebench/shard-input-manifest.json",
    ]


def test_selective_package_accepts_an_expansion_worker(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    suite = staging / "worker-05" / "suites" / "parsebench"
    inputs = suite / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "parsebench-expanded.png").write_bytes(b"image")
    (suite / "parent-input-manifest.json").write_text("{}", encoding="utf-8")
    (suite / "shard-input-manifest.json").write_text("{}", encoding="utf-8")
    (staging / "selective-recovery-receipt.json").write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-selective-recovery-staging.v1",
                "recovery_model": "mineru-3.4.4-vlm-quality-retry",
                "input_count": 1,
                "eligible_recovery_workers": [0, 2, 3, 4, 5, 6],
                "workers": [
                    {
                        "recovery_worker_index": 5,
                        "input_count": 1,
                        "suites": [{"benchmark_id": "parsebench"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    receipt = package_selective_inputs(
        staging_root=staging, output_root=tmp_path / "packages"
    )
    assert receipt["packages"][0]["recovery_worker_index"] == 5
