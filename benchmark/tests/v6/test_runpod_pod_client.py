from __future__ import annotations

import json

import httpx
import pytest

from benchmark.v6.contracts import ContractError, canonical_sha256
from infra.runpod.v6.pod_client import PodClientError, PodCreateSpec, RunPodPodClient


def spec() -> PodCreateSpec:
    image = "runpod/pytorch@sha256:" + "a" * 64
    qualification = qualification_receipt(image=image)
    return PodCreateSpec.from_mapping(
        {
            "name": "folynta-m1-test",
            "image_name": image,
            "gpu_type": "NVIDIA GeForce RTX 4090",
            "public_key": "ssh-ed25519 AAAATEST test",
            "docker_entrypoint": ["/bin/bash", "-lc"],
            "docker_start_cmd": ["exec /usr/sbin/sshd -D -e"],
            "vllm_cuda_compatibility": True,
            "qualification_state": "READY",
            "baked_runtime_receipt_sha256": canonical_sha256(qualification),
            "baked_runtime_qualification": qualification,
        }
    )


def qualification_receipt(
    *, image: str, gpu_type: str = "NVIDIA GeForce RTX 4090"
) -> dict[str, object]:
    digest = "sha256:" + "b" * 64
    return {
        "schema": "folynta.baked-runtime-qualification.v1",
        "generated_at": "2026-08-03T12:00:00Z",
        "source_commit": "c" * 40,
        "source_tree_sha256": digest,
        "dockerfile_sha256": digest,
        "image_digest": image,
        "gpu_type": gpu_type,
        "cuda_version": "12.9",
        "framework_version": "vllm-0.22.1",
        "model_revision": "model-revision-1",
        "model_artifact_sha256": digest,
        "baked_runtime_file_sha256": digest,
        "sbom_sha256": digest,
        "vulnerability_scan_sha256": digest,
        "critical_vulnerability_count": 0,
        "smoke_input_sha256": digest,
        "smoke_prediction_sha256": digest,
        "smoke_expected_sha256": digest,
        "identity_verified": True,
        "model_artifact_verified": True,
        "smoke_passed": True,
        "passed": True,
    }


def test_create_receipt_redacts_public_key_and_account_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert b"AAAATEST" in request.content
        payload = json.loads(request.content)
        assert payload["dockerEntrypoint"] == ["/bin/bash", "-lc"]
        assert payload["dockerStartCmd"] == ["exec /usr/sbin/sshd -D -e"]
        assert payload["env"]["VLLM_ENABLE_CUDA_COMPATIBILITY"] == "1"
        return httpx.Response(
            201,
            headers={"content-type": "application/json"},
            json={
                "id": "pod123",
                "name": "folynta-m1-test",
                "desiredStatus": "RUNNING",
                "image": "runpod/pytorch@sha256:" + "a" * 64,
                "consumerUserId": "private-account",
                "env": {"PUBLIC_KEY": "ssh-ed25519 AAAATEST test"},
                "gpu": {"displayName": "NVIDIA GeForce RTX 4090"},
                "costPerHr": 0.69,
            },
        )

    client = RunPodPodClient(api_key="secret", transport=httpx.MockTransport(handler))
    receipt = client.create_pod(spec())
    client.close()
    assert receipt["pod_id"] == "pod123"
    assert "consumerUserId" not in receipt
    assert "env" not in receipt
    assert "AAAATEST" not in str(receipt)


def test_compatibility_flag_is_strict_boolean() -> None:
    with pytest.raises(ContractError, match="must be a boolean"):
        PodCreateSpec.from_mapping(
            {
                "name": "folynta-m1-test",
                "image_name": "runpod/pytorch@sha256:" + "a" * 64,
                "gpu_type": "NVIDIA A40",
                "public_key": "ssh-ed25519 AAAATEST test",
                "vllm_cuda_compatibility": "true",
            }
        )


def test_runtime_install_commands_are_rejected() -> None:
    with pytest.raises(ContractError, match="may not install"):
        PodCreateSpec.from_mapping(
            {
                "name": "folynta-m1-test",
                "image_name": "runpod/pytorch@sha256:" + "a" * 64,
                "gpu_type": "NVIDIA A40",
                "public_key": "ssh-ed25519 AAAATEST test",
                "docker_start_cmd": ["python -m pip install vllm"],
            }
        )


def test_build_required_spec_cannot_create_paid_capacity() -> None:
    blocked = PodCreateSpec.from_mapping(
        {
            "name": "folynta-m1-test",
            "image_name": "runpod/pytorch@sha256:" + "a" * 64,
            "gpu_type": "NVIDIA A40",
            "public_key": "ssh-ed25519 AAAATEST test",
            "qualification_state": "BUILD_REQUIRED",
        }
    )
    client = RunPodPodClient(api_key="secret", transport=httpx.MockTransport(lambda r: None))
    with pytest.raises(ContractError, match="cannot create paid capacity"):
        client.create_pod(blocked)
    client.close()


def test_ready_spec_rejects_fabricated_receipt_hash_without_qualification() -> None:
    with pytest.raises(ContractError, match="content-bound"):
        PodCreateSpec.from_mapping(
            {
                "name": "folynta-m1-test",
                "image_name": "runpod/pytorch@sha256:" + "a" * 64,
                "gpu_type": "NVIDIA A40",
                "public_key": "ssh-ed25519 AAAATEST test",
                "qualification_state": "READY",
                "baked_runtime_receipt_sha256": "sha256:" + "b" * 64,
            }
        )


def test_ready_spec_rejects_qualification_for_another_image() -> None:
    image = "runpod/pytorch@sha256:" + "a" * 64
    qualification = qualification_receipt(
        image="runpod/pytorch@sha256:" + "d" * 64,
        gpu_type="NVIDIA A40",
    )
    with pytest.raises(ContractError, match="image digest"):
        PodCreateSpec.from_mapping(
            {
                "name": "folynta-m1-test",
                "image_name": image,
                "gpu_type": "NVIDIA A40",
                "public_key": "ssh-ed25519 AAAATEST test",
                "qualification_state": "READY",
                "baked_runtime_receipt_sha256": canonical_sha256(qualification),
                "baked_runtime_qualification": qualification,
            }
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("critical_vulnerability_count", 1, "critical vulnerabilities"),
        ("smoke_prediction_sha256", "sha256:" + "e" * 64, "smoke prediction"),
        ("identity_verified", False, "gate did not pass"),
        ("model_artifact_verified", False, "gate did not pass"),
        ("smoke_passed", False, "gate did not pass"),
        ("passed", False, "gate did not pass"),
    ),
)
def test_runtime_qualification_gates_fail_closed(
    field: str, value: object, message: str
) -> None:
    image = "runpod/pytorch@sha256:" + "a" * 64
    qualification = qualification_receipt(image=image, gpu_type="NVIDIA A40")
    qualification[field] = value

    with pytest.raises(ContractError, match=message):
        PodCreateSpec.from_mapping(
            {
                "name": "folynta-m1-test",
                "image_name": image,
                "gpu_type": "NVIDIA A40",
                "public_key": "ssh-ed25519 AAAATEST test",
                "qualification_state": "READY",
                "baked_runtime_receipt_sha256": canonical_sha256(qualification),
                "baked_runtime_qualification": qualification,
            }
        )


def test_unknown_status_fails_closed() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"id": "pod123", "desiredStatus": "MYSTERY"},
        )
    )
    client = RunPodPodClient(api_key="secret", transport=transport)
    with pytest.raises(PodClientError, match="unknown pod status"):
        client.get_pod("pod123")
    client.close()


def test_delete_requires_strict_pod_id() -> None:
    client = RunPodPodClient(api_key="secret", transport=httpx.MockTransport(lambda r: None))
    with pytest.raises(ContractError, match="invalid pod_id"):
        client.delete_pod("../all")
    client.close()
