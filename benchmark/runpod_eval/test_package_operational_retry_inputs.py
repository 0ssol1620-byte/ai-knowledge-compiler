import json
import tarfile
from pathlib import Path

from package_operational_retry_inputs import package_retry_inputs


def test_retry_packages_contain_only_manifests_and_source_images(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    suite = staging / "worker-01" / "suites" / "parsebench"
    inputs = suite / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "parsebench-a.png").write_bytes(b"image")
    (suite / "parent-input-manifest.json").write_text("{}", encoding="utf-8")
    (suite / "shard-input-manifest.json").write_text("{}", encoding="utf-8")
    (staging / "retry-plan-receipt.json").write_text(
        json.dumps(
            {
                "failed_input_count": 1,
                "staged_input_count": 1,
                "eligible_retry_workers": [0, 1, 2, 3],
                "workers": [{"retry_worker_index": 1, "input_count": 1}],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "packages"
    receipt = package_retry_inputs(staging_root=staging, output_root=output)
    assert receipt["input_count"] == 1
    archive = output / receipt["packages"][0]["archive"]
    with tarfile.open(archive, "r:gz") as bundle:
        names = sorted(member.name for member in bundle.getmembers() if member.isfile())
    assert names == [
        "worker-01/suites/parsebench/inputs/parsebench-a.png",
        "worker-01/suites/parsebench/parent-input-manifest.json",
        "worker-01/suites/parsebench/shard-input-manifest.json",
    ]


def test_retry_package_accepts_an_expansion_worker(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    suite = staging / "worker-04" / "suites" / "parsebench"
    inputs = suite / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "parsebench-expanded.png").write_bytes(b"image")
    (suite / "parent-input-manifest.json").write_text("{}", encoding="utf-8")
    (suite / "shard-input-manifest.json").write_text("{}", encoding="utf-8")
    (staging / "retry-plan-receipt.json").write_text(
        json.dumps(
            {
                "failed_input_count": 1,
                "staged_input_count": 1,
                "eligible_retry_workers": [0, 2, 3, 4],
                "workers": [{"retry_worker_index": 4, "input_count": 1}],
            }
        ),
        encoding="utf-8",
    )
    receipt = package_retry_inputs(
        staging_root=staging, output_root=tmp_path / "packages"
    )
    assert receipt["packages"][0]["retry_worker_index"] == 4
