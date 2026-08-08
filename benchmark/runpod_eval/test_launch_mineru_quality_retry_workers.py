from __future__ import annotations

import json
from pathlib import Path

import pytest
from collect_public_core_worker import sha256_file
from launch_mineru_quality_retry_workers import (
    MODEL,
    _remote_launch_script,
    validate_packages,
)


def test_quality_retry_package_validation_binds_worker_and_hash(tmp_path: Path) -> None:
    archive = tmp_path / f"worker-02-{MODEL}-inputs.tar.gz"
    archive.write_bytes(b"archive")
    receipt = tmp_path / "package-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-selective-recovery-packages.v1",
                "recovery_model": MODEL,
                "package_count": 1,
                "input_count": 3,
                "packages": [
                    {
                        "recovery_worker_index": 2,
                        "input_count": 3,
                        "suites": ["parsebench"],
                        "archive": archive.name,
                        "archive_bytes": archive.stat().st_size,
                        "archive_sha256": sha256_file(archive),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    packages = validate_packages(package_receipt=receipt, package_root=tmp_path)

    assert packages[0]["worker_index"] == 2
    assert packages[0]["input_count"] == 3

    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError, match=r"size|hash"):
        validate_packages(package_receipt=receipt, package_root=tmp_path)


def test_quality_retry_package_accepts_expansion_worker(tmp_path: Path) -> None:
    archive = tmp_path / f"worker-06-{MODEL}-inputs.tar.gz"
    archive.write_bytes(b"expanded-archive")
    receipt = tmp_path / "package-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-selective-recovery-packages.v1",
                "recovery_model": MODEL,
                "package_count": 1,
                "input_count": 2,
                "packages": [
                    {
                        "recovery_worker_index": 6,
                        "input_count": 2,
                        "suites": ["parsebench"],
                        "archive": archive.name,
                        "archive_bytes": archive.stat().st_size,
                        "archive_sha256": sha256_file(archive),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    packages = validate_packages(package_receipt=receipt, package_root=tmp_path)
    assert packages[0]["worker_index"] == 6


def test_quality_remote_launch_is_dependency_complete_and_readiness_gated() -> None:
    script = _remote_launch_script(
        worker_index=6,
        archive=Path(f"worker-06-{MODEL}-inputs.tar.gz"),
        sha256="sha256:" + "a" * 64,
    )

    assert "mkdir -p /workspace/folynta/results" in script
    assert "runner/input_contract.py" in script
    assert ".source-archive-sha256" in script
    assert "worker-state.jsonl" in script
    assert "failed before readiness evidence" in script
    assert "stall watchdog failed startup readiness" in script
    assert 'kill -0 "$watchdog_pid"' in script
