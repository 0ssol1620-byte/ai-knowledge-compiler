from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6.runtime_qualification import (
    BakedRuntimeQualification,
    build_runtime_qualification,
    main,
)


def _build_receipt() -> dict[str, object]:
    return {
        "schema": "folynta.baked-image-build-integrity.v1",
        "generated_at": "2026-08-15T09:00:00+00:00",
        "source_commit": "a" * 40,
        "source_tree_sha256": "sha256:" + "1" * 64,
        "dockerfile_sha256": "sha256:" + "2" * 64,
        "image_digest": "ghcr.io/example/ovis@sha256:" + "3" * 64,
        "image_tag": "ghcr.io/example/ovis:test",
        "model_revision": "b" * 40,
        "model_artifact_sha256": "sha256:" + "4" * 64,
        "sbom_sha256": "sha256:" + "5" * 64,
        "vulnerability_scan_sha256": "sha256:" + "6" * 64,
        "critical_vulnerability_count": 0,
        "build_passed": True,
        "runtime_qualification_required": True,
        "paid_capacity_ready": False,
    }


def _runtime_evidence() -> dict[str, object]:
    smoke = "sha256:" + "9" * 64
    return {
        "schema": "folynta.runtime-verification-evidence.v1",
        "generated_at": "2026-08-15T09:10:00+00:00",
        "image_digest": _build_receipt()["image_digest"],
        "gpu_type": "NVIDIA A40",
        "cuda_version": "12.9",
        "framework_version": "vllm-0.22.1",
        "model_revision": _build_receipt()["model_revision"],
        "model_artifact_sha256": _build_receipt()["model_artifact_sha256"],
        "baked_runtime_file_sha256": "sha256:" + "7" * 64,
        "smoke_input_sha256": "sha256:" + "8" * 64,
        "smoke_prediction_sha256": smoke,
        "smoke_expected_sha256": smoke,
        "identity_verified": True,
        "model_artifact_verified": True,
        "smoke_passed": True,
    }


def test_builder_binds_build_integrity_and_measured_gpu_evidence() -> None:
    qualification = build_runtime_qualification(
        build_receipt=_build_receipt(),
        runtime_evidence=_runtime_evidence(),
        generated_at="2026-08-15T09:20:00+00:00",
    )
    parsed = BakedRuntimeQualification.from_mapping(qualification)
    assert parsed.image_digest == _build_receipt()["image_digest"]
    assert parsed.gpu_type == "NVIDIA A40"
    assert parsed.passed


@pytest.mark.parametrize("field", ["image_digest", "model_revision", "model_artifact_sha256"])
def test_builder_refuses_runtime_evidence_that_drifted_from_the_build(field: str) -> None:
    evidence = deepcopy(_runtime_evidence())
    if field == "image_digest":
        evidence[field] = "ghcr.io/example/ovis@sha256:" + "f" * 64
    elif field == "model_revision":
        evidence[field] = "c" * 40
    else:
        evidence[field] = "sha256:" + "f" * 64
    with pytest.raises(ContractError, match="does not match build receipt"):
        build_runtime_qualification(build_receipt=_build_receipt(), runtime_evidence=evidence)


def test_builder_refuses_failed_measured_gate() -> None:
    evidence = deepcopy(_runtime_evidence())
    evidence["smoke_passed"] = False
    with pytest.raises(ContractError, match="did not pass all qualification gates"):
        build_runtime_qualification(build_receipt=_build_receipt(), runtime_evidence=evidence)


def test_builder_refuses_temporally_impossible_evidence() -> None:
    evidence = deepcopy(_runtime_evidence())
    evidence["generated_at"] = "2026-08-15T08:59:59+00:00"
    with pytest.raises(ContractError, match="predates the immutable image build"):
        build_runtime_qualification(build_receipt=_build_receipt(), runtime_evidence=evidence)

    with pytest.raises(ContractError, match="predates GPU verification evidence"):
        build_runtime_qualification(
            build_receipt=_build_receipt(),
            runtime_evidence=_runtime_evidence(),
            generated_at="2026-08-15T09:09:59+00:00",
        )


def test_builder_refuses_smoke_hash_disagreement() -> None:
    evidence = deepcopy(_runtime_evidence())
    evidence["smoke_prediction_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ContractError, match="smoke prediction does not match expected"):
        build_runtime_qualification(build_receipt=_build_receipt(), runtime_evidence=evidence)


def test_cli_exclusive_creates_qualification_receipt(tmp_path: Path) -> None:
    build = tmp_path / "build.json"
    evidence = tmp_path / "evidence.json"
    output = tmp_path / "qualification.json"
    build.write_text(json.dumps(_build_receipt()), encoding="utf-8")
    evidence.write_text(json.dumps(_runtime_evidence()), encoding="utf-8")

    assert main(["--build-receipt", str(build), "--runtime-evidence", str(evidence), "--output", str(output)]) == 0
    BakedRuntimeQualification.from_mapping(json.loads(output.read_text(encoding="utf-8")))
    with pytest.raises(ContractError, match="already exists"):
        main(["--build-receipt", str(build), "--runtime-evidence", str(evidence), "--output", str(output)])