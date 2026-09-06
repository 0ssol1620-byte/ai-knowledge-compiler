"""Content-bound qualification contract for paid benchmark runtime images."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from benchmark.v6.contracts import ContractError, canonical_sha256
from infra.runpod.v6.image_build_receipt import BakedImageBuildReceipt

_SCHEMA: Final = "folynta.baked-runtime-qualification.v1"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")
_EVIDENCE_SCHEMA: Final = "folynta.runtime-verification-evidence.v1"
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

_EVIDENCE_FIELDS = frozenset(
    {
        "schema",
        "generated_at",
        "image_digest",
        "gpu_type",
        "cuda_version",
        "framework_version",
        "model_revision",
        "model_artifact_sha256",
        "baked_runtime_file_sha256",
        "smoke_input_sha256",
        "smoke_prediction_sha256",
        "smoke_expected_sha256",
        "identity_verified",
        "model_artifact_verified",
        "smoke_passed",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeVerificationEvidence:
    generated_at: str
    image_digest: str
    gpu_type: str
    cuda_version: str
    framework_version: str
    model_revision: str
    model_artifact_sha256: str
    baked_runtime_file_sha256: str
    smoke_input_sha256: str
    smoke_prediction_sha256: str
    smoke_expected_sha256: str
    identity_verified: bool
    model_artifact_verified: bool
    smoke_passed: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RuntimeVerificationEvidence:
        fields = frozenset(value)
        if fields != _EVIDENCE_FIELDS:
            missing = sorted(_EVIDENCE_FIELDS - fields)
            extra = sorted(fields - _EVIDENCE_FIELDS)
            raise ContractError(
                f"runtime verification evidence fields mismatch: missing={missing}, extra={extra}"
            )
        if value["schema"] != _EVIDENCE_SCHEMA:
            raise ContractError("runtime verification evidence schema is unsupported")
        generated_at = str(value["generated_at"])
        try:
            parsed_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractError("runtime verification evidence generated_at is invalid") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise ContractError("runtime verification evidence generated_at must be timezone-aware")
        image_digest = str(value["image_digest"])
        if not _IMAGE_DIGEST.fullmatch(image_digest):
            raise ContractError("runtime verification image digest is not immutable")
        if not re.fullmatch(r"1[123]\.\d", str(value["cuda_version"])):
            raise ContractError("runtime verification CUDA version is invalid")
        for field in ("gpu_type", "framework_version", "model_revision"):
            if not str(value[field]).strip():
                raise ContractError(f"runtime verification {field} is required")
        for field in (
            "model_artifact_sha256",
            "baked_runtime_file_sha256",
            "smoke_input_sha256",
            "smoke_prediction_sha256",
            "smoke_expected_sha256",
        ):
            if not _SHA256.fullmatch(str(value[field])):
                raise ContractError(f"runtime verification {field} is invalid")
        for field in ("identity_verified", "model_artifact_verified", "smoke_passed"):
            if not isinstance(value[field], bool):
                raise ContractError("runtime verification gate fields must be booleans")
        return cls(
            generated_at=generated_at,
            image_digest=image_digest,
            gpu_type=str(value["gpu_type"]),
            cuda_version=str(value["cuda_version"]),
            framework_version=str(value["framework_version"]),
            model_revision=str(value["model_revision"]),
            model_artifact_sha256=str(value["model_artifact_sha256"]),
            baked_runtime_file_sha256=str(value["baked_runtime_file_sha256"]),
            smoke_input_sha256=str(value["smoke_input_sha256"]),
            smoke_prediction_sha256=str(value["smoke_prediction_sha256"]),
            smoke_expected_sha256=str(value["smoke_expected_sha256"]),
            identity_verified=bool(value["identity_verified"]),
            model_artifact_verified=bool(value["model_artifact_verified"]),
            smoke_passed=bool(value["smoke_passed"]),
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


def build_runtime_qualification(
    *,
    build_receipt: Mapping[str, Any],
    runtime_evidence: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Bind a clean immutable build to measured qualification-only GPU evidence."""

    build = BakedImageBuildReceipt.from_mapping(build_receipt)
    measured = RuntimeVerificationEvidence.from_mapping(runtime_evidence)
    build_time = datetime.fromisoformat(build.generated_at.replace("Z", "+00:00"))
    evidence_time = datetime.fromisoformat(measured.generated_at.replace("Z", "+00:00"))
    if evidence_time < build_time:
        raise ContractError("runtime verification evidence predates the immutable image build")
    if measured.image_digest != build.image_digest:
        raise ContractError("runtime verification image digest does not match build receipt")
    if measured.model_revision != build.model_revision:
        raise ContractError("runtime verification model revision does not match build receipt")
    if measured.model_artifact_sha256 != build.model_artifact_sha256:
        raise ContractError("runtime verification model artifact does not match build receipt")
    if not (
        measured.identity_verified
        and measured.model_artifact_verified
        and measured.smoke_passed
    ):
        raise ContractError("runtime verification evidence did not pass all qualification gates")

    qualification_generated_at = generated_at or datetime.now(UTC).isoformat()
    qualification_time = datetime.fromisoformat(
        qualification_generated_at.replace("Z", "+00:00")
    )
    if qualification_time < evidence_time:
        raise ContractError("runtime qualification timestamp predates GPU verification evidence")

    qualification: dict[str, Any] = {
        "schema": _SCHEMA,
        "generated_at": qualification_generated_at,
        "source_commit": build.source_commit,
        "source_tree_sha256": build.source_tree_sha256,
        "dockerfile_sha256": build.dockerfile_sha256,
        "image_digest": build.image_digest,
        "gpu_type": measured.gpu_type,
        "cuda_version": measured.cuda_version,
        "framework_version": measured.framework_version,
        "model_revision": build.model_revision,
        "model_artifact_sha256": build.model_artifact_sha256,
        "baked_runtime_file_sha256": measured.baked_runtime_file_sha256,
        "sbom_sha256": build.sbom_sha256,
        "vulnerability_scan_sha256": build.vulnerability_scan_sha256,
        "critical_vulnerability_count": build.critical_vulnerability_count,
        "smoke_input_sha256": measured.smoke_input_sha256,
        "smoke_prediction_sha256": measured.smoke_prediction_sha256,
        "smoke_expected_sha256": measured.smoke_expected_sha256,
        "identity_verified": measured.identity_verified,
        "model_artifact_verified": measured.model_artifact_verified,
        "smoke_passed": measured.smoke_passed,
        "passed": True,
    }
    BakedRuntimeQualification.from_mapping(qualification)
    return qualification


def _read_object(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractError(f"{path} must contain one JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a content-bound runtime qualification from immutable build "
            "and GPU evidence."
        )
    )
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--runtime-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    qualification = build_runtime_qualification(
        build_receipt=_read_object(args.build_receipt),
        runtime_evidence=_read_object(args.runtime_evidence),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(qualification, indent=2, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise ContractError(f"runtime qualification output already exists: {args.output}") from exc
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "BakedRuntimeQualification",
    "RuntimeVerificationEvidence",
    "build_runtime_qualification",
    "main",
]
