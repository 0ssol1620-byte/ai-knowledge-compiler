"""Tests for akc_cir.runtime_qualification — §14 runtime qualification receipts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from akc_cir.runtime_qualification import (
    DEFAULT_REQUIRED_GATES,
    CudaRuntimeIdentity,
    GateStatus,
    LicenseStatus,
    PromotionStatus,
    QualificationDecision,
    QualificationPolicy,
    QualificationStatus,
    RuntimeGateResult,
    RuntimeQualificationReceipt,
    SmokeResult,
    VulnScanRef,
    VulnSeverityCounts,
    evaluate,
    runtime_qualification_json_schema,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
IMAGE_DIGEST = (
    "ghcr.io/folynta/ovisocr2-m1@sha256:"
    + "a1" * 32
)
MODEL_SHA256 = "sha256:" + "b2" * 32
SBOM_REF = "receipts/sbom/ovisocr2-m1.cyclonedx.json"
COST_REF = "receipts/cost/runpod-allocation-2026-08-23.json"
LATENCY_REF = "receipts/latency/benchmark-p95-2026-08-23.json"


def _vuln_scan(**counts: int) -> VulnScanRef:
    return VulnScanRef(
        report_ref="receipts/vuln/trivy-ovisocr2-m1-2026-08-23.json",
        scanned_at=NOW,
        severity_counts=VulnSeverityCounts(**counts),
    )


def _passing_gates() -> tuple[RuntimeGateResult, ...]:
    return tuple(
        RuntimeGateResult(gate=name, status=GateStatus.PASS, detail="verified")
        for name in DEFAULT_REQUIRED_GATES
    )


def _complete_receipt() -> RuntimeQualificationReceipt:
    """A §14-complete candidate receipt: every mandatory field populated."""
    return RuntimeQualificationReceipt(
        created_at=NOW,
        container_image_digest=IMAGE_DIGEST,
        model_artifact_sha256=MODEL_SHA256,
        model_revision="ovisocr2-m1@2026-08-01",
        license_status=LicenseStatus.COMMERCIAL_USE_OK,
        sbom_ref=SBOM_REF,
        vuln_scan_ref=_vuln_scan(),
        cuda_runtime_identity=CudaRuntimeIdentity(
            driver_version="575.57.08",
            toolkit_version="12.9",
            gpu_name="NVIDIA A40",
        ),
        smoke_suite_id="ovisocr2-smoke-frozen-v1",
        smoke_result=SmokeResult.PASS,
        benchmark_scope=("korean_ocr_frozen_set",),
        known_failure_modes=(),
        cost_receipt_ref=COST_REF,
        latency_receipt_ref=LATENCY_REF,
        rollback_target="registry/folynta/ovisocr2-m0@sha256:" + "c3" * 32,
        promotion_status=PromotionStatus.CANDIDATE,
        gates=_passing_gates(),
    )


# ---------------------------------------------------------------------------
# READY: a complete receipt qualifies
# ---------------------------------------------------------------------------


def test_complete_receipt_is_ready() -> None:
    receipt = _complete_receipt()

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.READY
    assert decision.ready is True
    assert decision.missing_fields == ()
    assert decision.reasons == ()
    assert decision.failed_gates == ()


# ---------------------------------------------------------------------------
# Completeness enforcement (§14 필드 완결성)
# ---------------------------------------------------------------------------


def test_missing_sbom_ref_is_not_ready_with_reason() -> None:
    receipt = _complete_receipt().model_copy(update={"sbom_ref": None})

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY
    assert "sbom_ref" in decision.missing_fields
    assert any("sbom" in reason.lower() for reason in decision.reasons)


@pytest.mark.parametrize(
    "field",
    [
        "vuln_scan_ref",
        "cuda_runtime_identity",
        "smoke_suite_id",
        "smoke_result",
        "cost_receipt_ref",
        "latency_receipt_ref",
        "rollback_target",
    ],
)
def test_each_mandatory_field_missing_is_reported(field: str) -> None:
    receipt = _complete_receipt().model_copy(update={field: None})

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY
    assert field in decision.missing_fields


def test_empty_benchmark_scope_is_incomplete() -> None:
    receipt = _complete_receipt().model_copy(update={"benchmark_scope": ()})

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY
    assert "benchmark_scope" in decision.missing_fields


def test_empty_gate_list_is_incomplete() -> None:
    receipt = _complete_receipt().model_copy(update={"gates": ()})

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY
    assert "gates" in decision.missing_fields


# ---------------------------------------------------------------------------
# Vulnerability gate: zero high (and critical) findings
# ---------------------------------------------------------------------------


def test_single_high_vulnerability_is_not_ready() -> None:
    receipt = _complete_receipt().model_copy(
        update={"vuln_scan_ref": _vuln_scan(high=1)}
    )

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY
    assert any("high" in reason.lower() for reason in decision.reasons)


def test_critical_vulnerability_is_not_ready() -> None:
    receipt = _complete_receipt().model_copy(
        update={"vuln_scan_ref": _vuln_scan(critical=2)}
    )

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY
    assert any("critical" in reason.lower() for reason in decision.reasons)


# ---------------------------------------------------------------------------
# License gate: commercial_use_ok only
# ---------------------------------------------------------------------------


def test_unknown_license_is_not_ready() -> None:
    receipt = _complete_receipt().model_copy(
        update={"license_status": LicenseStatus.UNKNOWN}
    )

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY
    assert any("license" in reason.lower() for reason in decision.reasons)


def test_restricted_license_is_not_ready() -> None:
    receipt = _complete_receipt().model_copy(
        update={"license_status": LicenseStatus.RESTRICTED}
    )

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY


# ---------------------------------------------------------------------------
# Rollback target presence
# ---------------------------------------------------------------------------


def test_absent_rollback_target_is_not_ready() -> None:
    receipt = _complete_receipt().model_copy(update={"rollback_target": None})

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY
    assert "rollback_target" in decision.missing_fields


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------


def test_failed_required_gate_is_not_ready() -> None:
    gates = tuple(
        RuntimeGateResult(gate="smoke", status=GateStatus.FAIL, detail="hash mismatch")
        if name == "smoke"
        else RuntimeGateResult(gate=name, status=GateStatus.PASS, detail="ok")
        for name in DEFAULT_REQUIRED_GATES
    )
    receipt = _complete_receipt().model_copy(update={"gates": gates})

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY
    assert "smoke" in decision.failed_gates


def test_missing_required_gate_entry_is_not_ready() -> None:
    gates = tuple(
        gate for gate in _passing_gates() if gate.gate != "model_artifact"
    )
    receipt = _complete_receipt().model_copy(update={"gates": gates})

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY
    assert "model_artifact" in decision.failed_gates


def test_smoke_failure_blocks_readiness_even_with_passing_gate() -> None:
    receipt = _complete_receipt().model_copy(
        update={"smoke_result": SmokeResult.FAIL}
    )

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY
    assert any("smoke" in reason.lower() for reason in decision.reasons)


def test_retired_receipt_is_never_ready() -> None:
    receipt = _complete_receipt().model_copy(
        update={"promotion_status": PromotionStatus.RETIRED}
    )

    decision = evaluate(receipt, QualificationPolicy())

    assert decision.status is QualificationStatus.NOT_READY


def test_policy_can_require_extra_gate() -> None:
    receipt = _complete_receipt()
    policy = QualificationPolicy(required_gates=(*DEFAULT_REQUIRED_GATES, "drill"))

    decision = evaluate(receipt, policy)

    assert decision.status is QualificationStatus.NOT_READY
    assert "drill" in decision.failed_gates


# ---------------------------------------------------------------------------
# Schema JSON serialization
# ---------------------------------------------------------------------------


def test_receipt_json_round_trip_preserves_everything() -> None:
    receipt = _complete_receipt()

    payload = receipt.model_dump_json(by_alias=True)
    restored = RuntimeQualificationReceipt.model_validate_json(payload)

    assert restored == receipt


def test_decision_serializes_to_json() -> None:
    decision = evaluate(_complete_receipt(), QualificationPolicy())

    payload = decision.model_dump_json(by_alias=True)

    assert '"status":"READY"' in payload.replace(" ", "")
    restored = QualificationDecision.model_validate_json(payload)
    assert restored.status is QualificationStatus.READY


def test_json_schema_exposes_section14_fields() -> None:
    schema = runtime_qualification_json_schema()

    properties = schema["properties"]
    for field in (
        "containerImageDigest",
        "modelArtifactSha256",
        "modelRevision",
        "licenseStatus",
        "sbomRef",
        "vulnScanRef",
        "cudaRuntimeIdentity",
        "smokeSuiteId",
        "smokeResult",
        "benchmarkScope",
        "knownFailureModes",
        "costReceiptRef",
        "latencyReceiptRef",
        "rollbackTarget",
        "promotionStatus",
        "gates",
    ):
        assert field in properties, f"§14 field missing from JSON schema: {field}"


# ---------------------------------------------------------------------------
# Schema-level validation (malformed identities rejected at construction)
# ---------------------------------------------------------------------------


def test_non_immutable_image_digest_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _complete_receipt().model_copy(
            update={"container_image_digest": "registry/folynta/ovisocr2-m1:latest"}
        )


def test_malformed_model_sha256_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _complete_receipt().model_copy(
            update={"model_artifact_sha256": "deadbeef"}
        )


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RuntimeQualificationReceipt(
            **{
                **_complete_receipt().model_dump(mode="python"),
                "created_at": datetime(2026, 8, 23, 12, 0, 0),
            }
        )
