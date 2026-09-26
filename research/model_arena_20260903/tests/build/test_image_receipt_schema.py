"""build/image_receipt.schema.json: pass/fail validation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

BUILD_DIR = Path(__file__).resolve().parents[2] / "build"


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return json.loads((BUILD_DIR / "image_receipt.schema.json").read_text(encoding="utf-8"))


@pytest.fixture()
def valid_receipt() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.build.image-receipt.v1",
        "model_key": "paddleocr_vl_1_6",
        "dockerfile_sha256": "sha256:" + "a" * 64,
        "context_tree_sha256": "sha256:" + "b" * 64,
        "base_image_digest": "sha256:" + "c" * 64,
        "image_digest": "sha256:" + "d" * 64,
        "image_tag": "ghcr.io/0ssol1620-byte/tavonel-arena/paddleocr_vl_1_6:20260903",
        "built_at": "2026-09-03T12:00:00Z",
        "builder_pod_id": "abc123",
        "buildah_version": "1.37.0",
        "sbom_sha256": "sha256:" + "e" * 64,
        "sbom_tool": "syft",
        "vulnerability_scan_sha256": "sha256:" + "f" * 64,
        "vulnerability_scan_tool": "trivy",
        "critical_vulnerability_count": 0,
        "runtime_qualification_required": True,
        "paid_capacity_ready": False,
    }


def test_valid_receipt_passes(schema, valid_receipt) -> None:
    jsonschema.validate(valid_receipt, schema)


def test_receipt_with_null_sbom_and_scan_passes(schema, valid_receipt) -> None:
    """SBOM/vuln-scan tools are optional ('syft if available else null' /
    'trivy if available else null' per the lane brief)."""
    receipt = copy.deepcopy(valid_receipt)
    receipt["sbom_sha256"] = None
    receipt["sbom_tool"] = None
    receipt["vulnerability_scan_sha256"] = None
    receipt["vulnerability_scan_tool"] = None
    receipt["critical_vulnerability_count"] = None
    jsonschema.validate(receipt, schema)


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("schema", "wrong.schema.v1"),
        ("model_key", "not_a_real_model_key"),
        ("dockerfile_sha256", "not-a-sha"),
        ("dockerfile_sha256", "a" * 64),  # missing sha256: prefix
        ("context_tree_sha256", "sha256:short"),
        ("base_image_digest", "sha256:" + "g" * 63),  # too short
        ("image_digest", "plain-tag-not-a-digest"),
        ("image_tag", "docker.io/vllm/vllm-openai:v0.21.0"),  # wrong registry
        ("built_at", "2026-09-03"),  # not a full timestamp
        ("runtime_qualification_required", False),  # cannot waive qualification
        ("paid_capacity_ready", True),  # a build receipt can never authorize spend
        ("critical_vulnerability_count", -1),
    ],
)
def test_invalid_field_values_fail(schema, valid_receipt, field: str, bad_value: object) -> None:
    receipt = copy.deepcopy(valid_receipt)
    receipt[field] = bad_value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(receipt, schema)


@pytest.mark.parametrize(
    "missing_field",
    [
        "model_key",
        "image_digest",
        "runtime_qualification_required",
        "paid_capacity_ready",
        "sbom_sha256",
    ],
)
def test_missing_required_field_fails(schema, valid_receipt, missing_field: str) -> None:
    receipt = copy.deepcopy(valid_receipt)
    del receipt[missing_field]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(receipt, schema)


def test_unknown_extra_field_fails(schema, valid_receipt) -> None:
    receipt = copy.deepcopy(valid_receipt)
    receipt["actual_marginal_api_cost"] = "N/A"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(receipt, schema)
