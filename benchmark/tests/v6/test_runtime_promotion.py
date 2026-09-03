from __future__ import annotations

from copy import deepcopy

import pytest

from benchmark.v6.contracts import ContractError, canonical_sha256
from infra.runpod.v6.pod_client import PodCreateSpec
from infra.runpod.v6.runtime_promotion import promote_build_required_spec


def _base_spec() -> dict[str, object]:
    return {
        "name": "folynta-ovis-qualified-test",
        "image_name": "vllm/vllm-openai@sha256:" + "a" * 64,
        "gpu_type": "NVIDIA A40",
        "public_key": "ssh-ed25519 AAAATEST test",
        "container_disk_gb": 80,
        "volume_gb": 20,
        "allowed_cuda_versions": ["12.8", "12.9"],
        "qualification_state": "BUILD_REQUIRED",
    }


def _qualification(*, gpu: str = "NVIDIA A40") -> dict[str, object]:
    digest = "sha256:" + "b" * 64
    value: dict[str, object] = {
        "schema": "folynta.baked-runtime-qualification.v1",
        "generated_at": "2026-08-15T09:00:00+00:00",
        "source_commit": "c" * 40,
        "source_tree_sha256": "sha256:" + "d" * 64,
        "dockerfile_sha256": "sha256:" + "e" * 64,
        "image_digest": "ghcr.io/example/ovis@sha256:" + "f" * 64,
        "gpu_type": gpu,
        "cuda_version": "12.9",
        "framework_version": "vllm-0.22.1",
        "model_revision": "ovis-rev",
        "model_artifact_sha256": "sha256:" + "1" * 64,
        "baked_runtime_file_sha256": "sha256:" + "2" * 64,
        "sbom_sha256": "sha256:" + "3" * 64,
        "vulnerability_scan_sha256": "sha256:" + "4" * 64,
        "critical_vulnerability_count": 0,
        "smoke_input_sha256": "sha256:" + "5" * 64,
        "smoke_prediction_sha256": digest,
        "smoke_expected_sha256": digest,
        "identity_verified": True,
        "model_artifact_verified": True,
        "smoke_passed": True,
        "passed": True,
    }
    return value


def test_passed_qualification_promotes_only_to_its_immutable_digest() -> None:
    qualification = _qualification()
    ready, receipt = promote_build_required_spec(_base_spec(), qualification)

    assert ready["qualification_state"] == "READY"
    assert ready["image_name"] == qualification["image_digest"]
    assert ready["baked_runtime_receipt_sha256"] == canonical_sha256(qualification)
    assert receipt["manual_ready_override_allowed"] is False
    PodCreateSpec.from_mapping(ready).require_ready()


def test_gpu_mismatch_refuses_promotion() -> None:
    with pytest.raises(ContractError, match="qualified GPU"):
        promote_build_required_spec(_base_spec(), _qualification(gpu="NVIDIA L40S"))


def test_failed_smoke_cannot_be_promoted() -> None:
    qualification = _qualification()
    qualification["smoke_passed"] = False
    qualification["passed"] = False
    with pytest.raises(ContractError, match="gate did not pass"):
        promote_build_required_spec(_base_spec(), qualification)


def test_existing_ready_or_embedded_receipt_cannot_be_rewritten() -> None:
    ready_source = _base_spec()
    ready_source["qualification_state"] = "READY"
    with pytest.raises(ContractError, match="only a BUILD_REQUIRED"):
        promote_build_required_spec(ready_source, _qualification())

    embedded = deepcopy(_base_spec())
    embedded["baked_runtime_receipt_sha256"] = "sha256:" + "9" * 64
    with pytest.raises(ContractError, match="already contains a runtime receipt"):
        promote_build_required_spec(embedded, _qualification())