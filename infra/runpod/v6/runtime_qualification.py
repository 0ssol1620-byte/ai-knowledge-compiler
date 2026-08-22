"""Content-bound qualification contract for paid benchmark runtime images."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from benchmark.v6.contracts import ContractError, canonical_sha256

_SCHEMA: Final = "folynta.baked-runtime-qualification.v1"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")
_EXPECTED_FIELDS = frozenset(
    {
        "schema",
        "generated_at",
        "source_commit",
        "source_tree_sha256",
        "dockerfile_sha256",
        "image_digest",
        "gpu_type",
        "cuda_version",
        "framework_version",
        "model_revision",
        "model_artifact_sha256",
        "baked_runtime_file_sha256",
        "sbom_sha256",
        "vulnerability_scan_sha256",
        "critical_vulnerability_count",
        "smoke_input_sha256",
        "smoke_prediction_sha256",
        "smoke_expected_sha256",
        "identity_verified",
        "model_artifact_verified",
        "smoke_passed",
        "passed",
    }
)


@dataclass(frozen=True, slots=True)
class BakedRuntimeQualification:
    generated_at: str
    source_commit: str
    source_tree_sha256: str
    dockerfile_sha256: str
    image_digest: str
    gpu_type: str
    cuda_version: str
    framework_version: str
    model_revision: str
    model_artifact_sha256: str
    baked_runtime_file_sha256: str
    sbom_sha256: str
    vulnerability_scan_sha256: str
    critical_vulnerability_count: int
    smoke_input_sha256: str
    smoke_prediction_sha256: str
    smoke_expected_sha256: str
    identity_verified: bool
    model_artifact_verified: bool
    smoke_passed: bool
    passed: bool
    receipt_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> BakedRuntimeQualification:
        fields = frozenset(value)
        if fields != _EXPECTED_FIELDS:
            missing = sorted(_EXPECTED_FIELDS - fields)
            extra = sorted(fields - _EXPECTED_FIELDS)
            raise ContractError(
                f"runtime qualification fields mismatch: missing={missing}, extra={extra}"
            )
        if value["schema"] != _SCHEMA:
            raise ContractError("runtime qualification schema is unsupported")
        generated_at = str(value["generated_at"])
        try:
            parsed_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractError("runtime qualification generated_at is invalid") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise ContractError("runtime qualification generated_at must be timezone-aware")

        sha_fields = (
            "source_tree_sha256",
            "dockerfile_sha256",
            "model_artifact_sha256",
            "baked_runtime_file_sha256",
            "sbom_sha256",
            "vulnerability_scan_sha256",
            "smoke_input_sha256",
            "smoke_prediction_sha256",
            "smoke_expected_sha256",
        )
        if any(not _SHA256.fullmatch(str(value[field])) for field in sha_fields):
            raise ContractError("runtime qualification contains an invalid sha256")
        image_digest = str(value["image_digest"])
        if not _IMAGE_DIGEST.fullmatch(image_digest):
            raise ContractError("runtime qualification image digest is not immutable")
        source_commit = str(value["source_commit"])
        if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
            raise ContractError("runtime qualification source commit is invalid")
        if not re.fullmatch(r"1[123]\.\d", str(value["cuda_version"])):
            raise ContractError("runtime qualification CUDA version is invalid")
        for field in ("gpu_type", "framework_version", "model_revision"):
            if not str(value[field]).strip():
                raise ContractError(f"runtime qualification {field} is required")
        critical_count = int(value["critical_vulnerability_count"])
        boolean_fields = (
            "identity_verified",
            "model_artifact_verified",
            "smoke_passed",
            "passed",
        )
        if any(not isinstance(value[field], bool) for field in boolean_fields):
            raise ContractError("runtime qualification gate fields must be booleans")
        if critical_count != 0:
            raise ContractError("runtime qualification has critical vulnerabilities")
        if value["smoke_prediction_sha256"] != value["smoke_expected_sha256"]:
            raise ContractError("runtime qualification smoke prediction does not match expected")
        if not all(bool(value[field]) for field in boolean_fields):
            raise ContractError("runtime qualification gate did not pass")

        return cls(
            generated_at=generated_at,
            source_commit=source_commit,
            source_tree_sha256=str(value["source_tree_sha256"]),
            dockerfile_sha256=str(value["dockerfile_sha256"]),
            image_digest=image_digest,
            gpu_type=str(value["gpu_type"]),
            cuda_version=str(value["cuda_version"]),
            framework_version=str(value["framework_version"]),
            model_revision=str(value["model_revision"]),
            model_artifact_sha256=str(value["model_artifact_sha256"]),
            baked_runtime_file_sha256=str(value["baked_runtime_file_sha256"]),
            sbom_sha256=str(value["sbom_sha256"]),
            vulnerability_scan_sha256=str(value["vulnerability_scan_sha256"]),
            critical_vulnerability_count=critical_count,
            smoke_input_sha256=str(value["smoke_input_sha256"]),
            smoke_prediction_sha256=str(value["smoke_prediction_sha256"]),
            smoke_expected_sha256=str(value["smoke_expected_sha256"]),
            identity_verified=bool(value["identity_verified"]),
            model_artifact_verified=bool(value["model_artifact_verified"]),
            smoke_passed=bool(value["smoke_passed"]),
            passed=bool(value["passed"]),
            receipt_sha256=canonical_sha256(value),
        )

    def assert_matches(
        self,
        *,
        image_digest: str,
        gpu_type: str,
        allowed_cuda_versions: tuple[str, ...],
    ) -> None:
        if self.image_digest != image_digest:
            raise ContractError("qualified image digest does not match the pod image")
        if self.gpu_type != gpu_type:
            raise ContractError("qualified GPU does not match the pod GPU")
        if self.cuda_version not in allowed_cuda_versions:
            raise ContractError("qualified CUDA version is not allowed by the pod spec")


__all__ = ["BakedRuntimeQualification"]
