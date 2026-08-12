import json
from pathlib import Path

import pytest
from launch_operational_retry_workers import (
    _remote_launch_script,
    validate_packages,
    validate_preexisting_launch,
)


def _sha256(path: Path) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def test_validate_packages_binds_worker_route_size_and_hash(tmp_path: Path) -> None:
    archive = tmp_path / "worker-02-operational-retry-inputs.tar.gz"
    archive.write_bytes(b"source-only-retry")
    receipt = tmp_path / "package-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-operational-retry-packages.v1",
                "package_count": 1,
                "input_count": 7,
                "packages": [
                    {
                        "retry_worker_index": 2,
                        "input_count": 7,
                        "archive": archive.name,
                        "archive_bytes": archive.stat().st_size,
                        "archive_sha256": _sha256(archive),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    packages = validate_packages(package_receipt=receipt, package_root=tmp_path)

    assert packages[0]["worker_index"] == 2
    assert packages[0]["input_count"] == 7


def test_validate_packages_rejects_tampered_archive(tmp_path: Path) -> None:
    archive = tmp_path / "worker-00-operational-retry-inputs.tar.gz"
    archive.write_bytes(b"tampered")
    receipt = tmp_path / "package-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-operational-retry-packages.v1",
                "package_count": 1,
                "input_count": 1,
                "packages": [
                    {
                        "retry_worker_index": 0,
                        "input_count": 1,
                        "archive": archive.name,
                        "archive_bytes": archive.stat().st_size,
                        "archive_sha256": "sha256:" + "0" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="hash"):
        validate_packages(package_receipt=receipt, package_root=tmp_path)


def test_validate_packages_accepts_expansion_worker_route(tmp_path: Path) -> None:
    archive = tmp_path / "worker-06-operational-retry-inputs.tar.gz"
    archive.write_bytes(b"expanded-source-only-retry")
    receipt = tmp_path / "package-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-operational-retry-packages.v1",
                "package_count": 1,
                "input_count": 3,
                "packages": [
                    {
                        "retry_worker_index": 6,
                        "input_count": 3,
                        "archive": archive.name,
                        "archive_bytes": archive.stat().st_size,
                        "archive_sha256": _sha256(archive),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    packages = validate_packages(package_receipt=receipt, package_root=tmp_path)
    assert packages[0]["worker_index"] == 6


def test_preexisting_prefetch_is_reused_only_when_final_routes_match(
    tmp_path: Path,
) -> None:
    case = {
        "benchmark_id": "parsebench",
        "case_id": "parsebench-a",
        "primary_worker_index": 1,
        "retry_worker_index": 4,
    }
    early_plan = tmp_path / "early-plan.json"
    final_plan = tmp_path / "final-plan.json"
    for path, failures in ((early_plan, [case]), (final_plan, [case])):
        path.write_text(
            json.dumps(
                {
                    "schema": "folynta.public-core-operational-retry-plan.v1",
                    "failures": failures,
                }
            ),
            encoding="utf-8",
        )
    launch = tmp_path / "early-launch.json"
    launch.write_text(
        json.dumps(
            {
                "schema": "folynta.operational-retry-launch.v1",
                "worker_count": 1,
                "input_count": 1,
                "launches": [
                    {
                        "worker_index": 4,
                        "input_count": 1,
                        "archive_sha256": "sha256:" + "a" * 64,
                        "runner_pid": 10,
                        "stall_watchdog_pid": 11,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    packages = (
        {
            "worker_index": 4,
            "input_count": 1,
            "archive_sha256": "sha256:" + "b" * 64,
        },
    )

    reused = validate_preexisting_launch(
        preexisting_launch_receipt=launch,
        preexisting_retry_plan=early_plan,
        final_retry_plan=final_plan,
        packages=packages,
    )

    assert reused[0]["prefetch_reused"] is True
    assert reused[0]["final_planned_archive_sha256"] == "sha256:" + "b" * 64


def test_preexisting_prefetch_rejects_final_route_drift(tmp_path: Path) -> None:
    early_plan = tmp_path / "early-plan.json"
    final_plan = tmp_path / "final-plan.json"
    base = {
        "benchmark_id": "parsebench",
        "case_id": "parsebench-a",
        "primary_worker_index": 1,
    }
    early_plan.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-operational-retry-plan.v1",
                "failures": [{**base, "retry_worker_index": 4}],
            }
        ),
        encoding="utf-8",
    )
    final_plan.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-operational-retry-plan.v1",
                "failures": [{**base, "retry_worker_index": 5}],
            }
        ),
        encoding="utf-8",
    )
    launch = tmp_path / "launch.json"
    launch.write_text(
        json.dumps(
            {
                "schema": "folynta.operational-retry-launch.v1",
                "worker_count": 1,
                "input_count": 1,
                "launches": [{"worker_index": 4, "input_count": 1}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="final frozen plan"):
        validate_preexisting_launch(
            preexisting_launch_receipt=launch,
            preexisting_retry_plan=early_plan,
            final_retry_plan=final_plan,
            packages=(
                {
                    "worker_index": 4,
                    "input_count": 1,
                    "archive_sha256": "sha256:" + "a" * 64,
                },
            ),
        )


def test_remote_launch_creates_result_parent_and_requires_readiness() -> None:
    script = _remote_launch_script(
        worker_index=4,
        archive=Path("worker-04-operational-retry-inputs.tar.gz"),
        sha256="sha256:" + "a" * 64,
    )

    assert "mkdir -p /workspace/folynta/results" in script
    assert ".source-archive-sha256" in script
    assert "superseded-$(date -u +%s)" in script
    assert "worker-state.jsonl" in script
    assert "runner/input_contract.py" in script
    assert "failed before readiness evidence" in script
    assert "stall watchdog failed startup readiness" in script
    assert 'kill -0 "$watchdog_pid"' in script
    assert script.index("mkdir -p /workspace/folynta/results") < script.index("nohup bash")
