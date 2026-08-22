"""Fail-closed build-integrity receipt for baked benchmark images.

This receipt deliberately stops before GPU runtime qualification.  A clean
image build, SBOM, and vulnerability scan are necessary evidence, but they do
not authorize paid capacity or establish model accuracy.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

from benchmark.v6.contracts import ContractError, canonical_sha256

_SCHEMA: Final = "folynta.baked-image-build-integrity.v1"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_IMAGE_DIGEST = re.compile(
    r"^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$"
)
_IMAGE_TAG = re.compile(r"^ghcr\.io/[a-z0-9._/-]+:[a-z0-9._-]+$")
_EXPECTED_FIELDS = frozenset(
    {
        "schema",
        "generated_at",
        "source_commit",
        "source_tree_sha256",
        "dockerfile_sha256",
        "image_digest",
        "image_tag",
        "model_revision",
        "model_artifact_sha256",
        "sbom_sha256",
        "vulnerability_scan_sha256",
        "critical_vulnerability_count",
        "build_passed",
        "runtime_qualification_required",
        "paid_capacity_ready",
    }
)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


@dataclass(frozen=True, slots=True)
class BakedImageBuildReceipt:
    generated_at: str
    source_commit: str
    source_tree_sha256: str
    dockerfile_sha256: str
    image_digest: str
    image_tag: str
    model_revision: str
    model_artifact_sha256: str
    sbom_sha256: str
    vulnerability_scan_sha256: str
    critical_vulnerability_count: int
    build_passed: bool
    runtime_qualification_required: bool
    paid_capacity_ready: bool
    receipt_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> BakedImageBuildReceipt:
        fields = frozenset(value)
        if fields != _EXPECTED_FIELDS:
            missing = sorted(_EXPECTED_FIELDS - fields)
            extra = sorted(fields - _EXPECTED_FIELDS)
            raise ContractError(
                f"image build receipt fields mismatch: missing={missing}, extra={extra}"
            )
        if value["schema"] != _SCHEMA:
            raise ContractError("image build receipt schema is unsupported")

        generated_at = str(value["generated_at"])
        try:
            parsed_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractError("image build receipt generated_at is invalid") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise ContractError("image build receipt generated_at must be timezone-aware")

        for field in (
            "source_tree_sha256",
            "dockerfile_sha256",
            "model_artifact_sha256",
            "sbom_sha256",
            "vulnerability_scan_sha256",
        ):
            if not _SHA256.fullmatch(str(value[field])):
                raise ContractError(f"image build receipt {field} is invalid")
        if not _COMMIT.fullmatch(str(value["source_commit"])):
            raise ContractError("image build receipt source commit is invalid")
        if not _REVISION.fullmatch(str(value["model_revision"])):
            raise ContractError("image build receipt model revision is invalid")
        if not _IMAGE_DIGEST.fullmatch(str(value["image_digest"])):
            raise ContractError("image build receipt digest is not an immutable GHCR image")
        if not _IMAGE_TAG.fullmatch(str(value["image_tag"])):
            raise ContractError("image build receipt tag is invalid")

        boolean_fields = (
            "build_passed",
            "runtime_qualification_required",
            "paid_capacity_ready",
        )
        if any(not isinstance(value[field], bool) for field in boolean_fields):
            raise ContractError("image build receipt gate fields must be booleans")
        critical_count = int(value["critical_vulnerability_count"])
        if critical_count != 0:
            raise ContractError("image build contains critical vulnerabilities")
        if value["build_passed"] is not True:
            raise ContractError("image build did not pass")
        if value["runtime_qualification_required"] is not True:
            raise ContractError("image build receipt cannot waive GPU qualification")
        if value["paid_capacity_ready"] is not False:
            raise ContractError("build-only receipt cannot authorize paid capacity")

        return cls(
            generated_at=generated_at,
            source_commit=str(value["source_commit"]),
            source_tree_sha256=str(value["source_tree_sha256"]),
            dockerfile_sha256=str(value["dockerfile_sha256"]),
            image_digest=str(value["image_digest"]),
            image_tag=str(value["image_tag"]),
            model_revision=str(value["model_revision"]),
            model_artifact_sha256=str(value["model_artifact_sha256"]),
            sbom_sha256=str(value["sbom_sha256"]),
            vulnerability_scan_sha256=str(value["vulnerability_scan_sha256"]),
            critical_vulnerability_count=critical_count,
            build_passed=True,
            runtime_qualification_required=True,
            paid_capacity_ready=False,
            receipt_sha256=canonical_sha256(value),
        )


def build_receipt(
    *,
    source_commit: str,
    source_tree_sha256: str,
    dockerfile: Path,
    image_digest: str,
    image_tag: str,
    model_revision: str,
    model_artifact_sha256: str,
    sbom: Path,
    vulnerability_scan: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    scan = json.loads(vulnerability_scan.read_text(encoding="utf-8"))
    critical_count = sum(
        1
        for result in scan.get("Results") or []
        for finding in result.get("Vulnerabilities") or []
        if finding.get("Severity") == "CRITICAL"
    )
    receipt: dict[str, Any] = {
        "schema": _SCHEMA,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "source_commit": source_commit,
        "source_tree_sha256": source_tree_sha256,
        "dockerfile_sha256": _file_sha256(dockerfile),
        "image_digest": image_digest,
        "image_tag": image_tag,
        "model_revision": model_revision,
        "model_artifact_sha256": model_artifact_sha256,
        "sbom_sha256": _file_sha256(sbom),
        "vulnerability_scan_sha256": _file_sha256(vulnerability_scan),
        "critical_vulnerability_count": critical_count,
        "build_passed": True,
        "runtime_qualification_required": True,
        "paid_capacity_ready": False,
    }
    BakedImageBuildReceipt.from_mapping(receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree-sha256", required=True)
    parser.add_argument("--dockerfile", type=Path, required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--model-artifact-sha256", required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--vulnerability-scan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = build_receipt(
        source_commit=args.source_commit,
        source_tree_sha256=args.source_tree_sha256,
        dockerfile=args.dockerfile,
        image_digest=args.image_digest,
        image_tag=args.image_tag,
        model_revision=args.model_revision,
        model_artifact_sha256=args.model_artifact_sha256,
        sbom=args.sbom,
        vulnerability_scan=args.vulnerability_scan,
    )
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["BakedImageBuildReceipt", "build_receipt", "main"]
