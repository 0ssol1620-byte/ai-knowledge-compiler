from __future__ import annotations

import json
from pathlib import Path

from infra.runpod.v6.cli import main


def _base_spec() -> dict[str, object]:
    return {
        "name": "folynta-ovis-qualified-cli",
        "image_name": "vllm/vllm-openai@sha256:" + "a" * 64,
        "gpu_type": "NVIDIA A40",
        "public_key": "ssh-ed25519 AAAATEST test",
        "container_disk_gb": 80,
        "volume_gb": 20,
        "allowed_cuda_versions": ["12.8", "12.9"],
        "qualification_state": "BUILD_REQUIRED",
    }


def _qualification() -> dict[str, object]:
    smoke = "sha256:" + "9" * 64
    return {
        "schema": "folynta.baked-runtime-qualification.v1",
        "generated_at": "2026-08-15T09:00:00+00:00",
        "source_commit": "c" * 40,
        "source_tree_sha256": "sha256:" + "1" * 64,
        "dockerfile_sha256": "sha256:" + "2" * 64,
        "image_digest": "ghcr.io/example/ovis@sha256:" + "3" * 64,
        "gpu_type": "NVIDIA A40",
        "cuda_version": "12.9",
        "framework_version": "vllm-0.22.1",
        "model_revision": "ovis-rev",
        "model_artifact_sha256": "sha256:" + "4" * 64,
        "baked_runtime_file_sha256": "sha256:" + "5" * 64,
        "sbom_sha256": "sha256:" + "6" * 64,
        "vulnerability_scan_sha256": "sha256:" + "7" * 64,
        "critical_vulnerability_count": 0,
        "smoke_input_sha256": "sha256:" + "8" * 64,
        "smoke_prediction_sha256": smoke,
        "smoke_expected_sha256": smoke,
        "identity_verified": True,
        "model_artifact_verified": True,
        "smoke_passed": True,
        "passed": True,
    }


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_promote_runtime_cli_writes_ready_spec_and_secret_free_receipt(
    tmp_path: Path, capsys: object
) -> None:
    spec = tmp_path / "spec.json"
    qualification = tmp_path / "qualification.json"
    ready = tmp_path / "ready.json"
    receipt = tmp_path / "receipt.json"
    _write(spec, _base_spec())
    _write(qualification, _qualification())

    assert (
        main(
            [
                "--receipt-out",
                str(receipt),
                "promote-runtime",
                "--spec",
                str(spec),
                "--qualification",
                str(qualification),
                "--ready-spec-out",
                str(ready),
            ]
        )
        == 0
    )
    ready_payload = json.loads(ready.read_text(encoding="utf-8"))
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert ready_payload["qualification_state"] == "READY"
    assert ready_payload["image_name"] == _qualification()["image_digest"]
    assert "public_key" not in receipt_payload
    assert receipt_payload["manual_ready_override_allowed"] is False


def test_promote_runtime_cli_rejects_execute(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    qualification = tmp_path / "qualification.json"
    ready = tmp_path / "ready.json"
    _write(spec, _base_spec())
    _write(qualification, _qualification())

    assert (
        main(
            [
                "--execute",
                "promote-runtime",
                "--spec",
                str(spec),
                "--qualification",
                str(qualification),
                "--ready-spec-out",
                str(ready),
            ]
        )
        == 2
    )
    assert not ready.exists()