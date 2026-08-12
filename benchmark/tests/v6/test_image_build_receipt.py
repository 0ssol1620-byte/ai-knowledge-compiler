from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6.image_build_receipt import (
    BakedImageBuildReceipt,
    build_receipt,
)


def _receipt() -> dict[str, object]:
    digest = "sha256:" + "a" * 64
    return {
        "schema": "folynta.baked-image-build-integrity.v1",
        "generated_at": "2026-08-03T12:00:00+00:00",
        "source_commit": "b" * 40,
        "source_tree_sha256": digest,
        "dockerfile_sha256": digest,
        "image_digest": f"ghcr.io/owner/repo/ovisocr2-m1@{digest}",
        "image_tag": f"ghcr.io/owner/repo/ovisocr2-m1:{'b' * 40}",
        "model_revision": "c" * 40,
        "model_artifact_sha256": digest,
        "sbom_sha256": digest,
        "vulnerability_scan_sha256": digest,
        "critical_vulnerability_count": 0,
        "build_passed": True,
        "runtime_qualification_required": True,
        "paid_capacity_ready": False,
    }


def test_build_receipt_is_explicitly_not_runtime_qualification() -> None:
    parsed = BakedImageBuildReceipt.from_mapping(_receipt())
    assert parsed.build_passed is True
    assert parsed.runtime_qualification_required is True
    assert parsed.paid_capacity_ready is False
    assert parsed.receipt_sha256.startswith("sha256:")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("critical_vulnerability_count", 1, "critical vulnerabilities"),
        ("build_passed", False, "did not pass"),
        ("runtime_qualification_required", False, "cannot waive"),
        ("paid_capacity_ready", True, "cannot authorize paid capacity"),
    ],
)
def test_build_receipt_fails_closed(
    field: str, value: object, message: str
) -> None:
    receipt = _receipt()
    receipt[field] = value
    with pytest.raises(ContractError, match=message):
        BakedImageBuildReceipt.from_mapping(receipt)


def test_builder_counts_critical_findings(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    sbom = tmp_path / "sbom.json"
    scan = tmp_path / "scan.json"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    sbom.write_text("{}\n", encoding="utf-8")
    scan.write_text(
        json.dumps(
            {
                "Results": [
                    {
                        "Vulnerabilities": [
                            {"Severity": "HIGH"},
                            {"Severity": "CRITICAL"},
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="critical vulnerabilities"):
        build_receipt(
            source_commit="b" * 40,
            source_tree_sha256="sha256:" + "a" * 64,
            dockerfile=dockerfile,
            image_digest="ghcr.io/owner/repo/image@sha256:" + "d" * 64,
            image_tag="ghcr.io/owner/repo/image:" + "b" * 40,
            model_revision="c" * 40,
            model_artifact_sha256="sha256:" + "e" * 64,
            sbom=sbom,
            vulnerability_scan=scan,
        )
