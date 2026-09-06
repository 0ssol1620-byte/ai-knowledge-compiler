"""Fail-closed promotion from BUILD_REQUIRED to a content-bound READY Pod spec.

Runtime qualification is deliberately separate from image construction and from
normal benchmark capacity.  This module is the only offline bridge between a
passed ``BakedRuntimeQualification`` receipt and a normal ``PodCreateSpec``.
It never contacts RunPod and never accepts an operator-authored READY claim.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from benchmark.v6.contracts import ContractError, canonical_sha256
from infra.runpod.v6.pod_client import PodCreateSpec
from infra.runpod.v6.runtime_qualification import BakedRuntimeQualification


def _qualification_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()}


def promote_build_required_spec(
    base_spec: Mapping[str, Any],
    qualification_receipt: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(ready_spec, secret_free_promotion_receipt)``.

    The source spec must still be explicitly ``BUILD_REQUIRED`` and must not
    contain any pre-existing qualification material.  The passed qualification
    supplies the immutable image digest; GPU and CUDA compatibility remain
    properties of the original Pod spec and are rechecked here and again by
    ``PodCreateSpec.from_mapping``.
    """

    state = str(base_spec.get("qualification_state", "BUILD_REQUIRED")).strip()
    if state != "BUILD_REQUIRED":
        raise ContractError("only a BUILD_REQUIRED pod spec may be promoted")
    if base_spec.get("baked_runtime_receipt_sha256") is not None:
        raise ContractError("BUILD_REQUIRED source spec already contains a runtime receipt")
    if base_spec.get("baked_runtime_qualification") is not None:
        raise ContractError("BUILD_REQUIRED source spec already contains qualification material")

    source = PodCreateSpec.from_mapping(base_spec)
    qualification_raw = _qualification_mapping(qualification_receipt)
    qualification = BakedRuntimeQualification.from_mapping(qualification_raw)
    qualification.assert_matches(
        image_digest=qualification.image_digest,
        gpu_type=source.gpu_type,
        allowed_cuda_versions=source.allowed_cuda_versions,
    )

    ready_mapping: dict[str, Any] = {
        "name": source.name,
        "image_name": qualification.image_digest,
        "gpu_type": source.gpu_type,
        "public_key": source.public_key,
        "container_disk_gb": source.container_disk_gb,
        "volume_gb": source.volume_gb,
        "allowed_cuda_versions": list(source.allowed_cuda_versions),
        "docker_entrypoint": list(source.docker_entrypoint),
        "docker_start_cmd": list(source.docker_start_cmd),
        "vllm_cuda_compatibility": source.vllm_cuda_compatibility,
        "qualification_state": "READY",
        "baked_runtime_receipt_sha256": qualification.receipt_sha256,
        "baked_runtime_qualification": qualification_raw,
    }
    promoted = PodCreateSpec.from_mapping(ready_mapping)
    promoted.require_ready()

    promotion_receipt: dict[str, Any] = {
        "schema": "folynta.runtime-promotion.v1",
        "source_qualification_state": "BUILD_REQUIRED",
        "result_qualification_state": "READY",
        "qualified_image_digest": qualification.image_digest,
        "gpu_type": qualification.gpu_type,
        "cuda_version": qualification.cuda_version,
        "runtime_qualification_receipt_sha256": qualification.receipt_sha256,
        "ready_spec_request_sha256": canonical_sha256(promoted.redacted_identity()),
        "manual_ready_override_allowed": False,
    }
    promotion_receipt["receipt_sha256"] = canonical_sha256(promotion_receipt)
    return ready_mapping, promotion_receipt


__all__ = ["promote_build_required_spec"]