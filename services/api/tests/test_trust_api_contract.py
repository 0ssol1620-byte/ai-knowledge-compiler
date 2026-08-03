from datetime import UTC, datetime
from uuid import uuid4

from akc_api.models import PackageManifest, PackageValidation
from akc_api.trust_api import build_trust_receipt, router


def test_masterplan_trust_routes_are_registered() -> None:
    methods_by_path = {
        route.path: getattr(route, "methods", set())
        for route in router.routes
        if hasattr(route, "path")
    }
    for path in (
        "/v1/jobs/{job_id}/scene",
        "/v1/jobs/{job_id}/quality-summary",
        "/v1/proofs/{proof_id}",
        "/v1/recovery/{recovery_id}",
        "/v1/packages/{package_id}/trust-receipt",
    ):
        assert "GET" in methods_by_path[path]


def test_trust_receipt_is_deterministic_and_validation_bound() -> None:
    now = datetime(2026, 8, 3, tzinfo=UTC)
    tenant_id = uuid4()
    collection_id = uuid4()
    package_id = uuid4()
    package = PackageManifest(
        id=package_id,
        tenant_id=tenant_id,
        collection_id=collection_id,
        profile="knowledge-package",
        status="completed",
        manifest_sha256="a" * 64,
        package_sha256="b" * 64,
        signature_status="verified",
        warnings=[],
        created_by=uuid4(),
        created_at=now,
        completed_at=now,
    )
    validation = PackageValidation(
        tenant_id=tenant_id,
        collection_id=collection_id,
        export_package_id=package_id,
        validator_version="final-v1",
        status="passed",
        checks={"hashes": True},
        evidence_sha256="c" * 64,
        created_at=now,
    )
    first = build_trust_receipt(package, file_count=8, validation=validation)
    second = build_trust_receipt(package, file_count=8, validation=validation)
    assert first.receipt_sha256 == second.receipt_sha256
    assert first.validation_status == "passed"
    assert first.validation_evidence_sha256 == "c" * 64
