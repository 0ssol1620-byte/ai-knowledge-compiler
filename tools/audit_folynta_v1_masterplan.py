"""Audit repository-bound requirements from the 2026-08-03 FOLYNTA v1 masterplan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTERPLAN = Path(
    r"D:\FOLYNTA_NEAR_PERFECT_BACKEND_AND_CINEMATIC_WORLD_CLASS_FRONTEND_MASTERPLAN_FINAL_v1_KO_2026-08-03.md"
)
EXPECTED_MASTERPLAN_SHA256 = "adc06f84ae9a6d7f455b8fcfec4d7afc8b9f83132b4f5baaaaee87254ae925c7"

REQUIRED_FILES = (
    "packages/quality/src/akc_quality/final_metrics.py",
    "packages/quality/src/akc_quality/conformal_risk.py",
    "packages/quality/src/akc_quality/page_coverage.py",
    "packages/quality/src/akc_quality/table_conservation.py",
    "packages/quality/src/akc_quality/numeric_authority.py",
    "packages/quality/src/akc_quality/knowledge_quality.py",
    "packages/parallel-runtime/src/akc_parallel_runtime/recovery_planner.py",
    "packages/parallel-runtime/src/akc_parallel_runtime/first_verified.py",
    "packages/parallel-runtime/src/akc_parallel_runtime/impact_scope.py",
    "packages/parallel-runtime/src/akc_parallel_runtime/semantic_health.py",
    "packages/parallel-runtime/src/akc_parallel_runtime/drift.py",
    "packages/router/src/akc_router/champion_matrix.py",
    "packages/router/src/akc_router/expected_verified_cost.py",
    "packages/router/src/akc_router/calibration.py",
    "services/api/src/akc_api/trust_api.py",
    "services/api/src/akc_api/quality_summary.py",
    "services/api/src/akc_api/proof_api.py",
    "services/api/src/akc_api/processing_scene.py",
    "services/api/src/akc_api/trust_receipt.py",
    "apps/web/src/components/folynta-v4/product-film-hero.tsx",
    "apps/web/src/components/folynta-v4/intake-cinematic.tsx",
    "apps/web/src/components/folynta-v4/recovery-theater.tsx",
    "apps/web/src/components/folynta-v4/actual-source-proof.tsx",
    "apps/web/src/components/folynta-v4/knowledge-formation.tsx",
    "apps/web/src/lib/trust-client.ts",
    "apps/web/public/proof-sources/dart-jtc-2026-q1.pdf",
    "assets/public-proof/dart/source-evidence/jtc-2026q1-pdf-receipt.json",
)

REQUIRED_ENDPOINTS = (
    "/jobs/{job_id}/scene",
    "/jobs/{job_id}/quality-summary",
    "/proofs/{proof_id}",
    "/recovery/{recovery_id}",
    "/packages/{package_id}/trust-receipt",
)

REQUIRED_EVENTS = (
    "recovery.planned.v1",
    "recovery.started.v1",
    "recovery.validated.v1",
    "region.verified.v1",
    "region.unresolved.v1",
    "worker.semantic.canary_failed.v1",
    "impact.replay.requested.v1",
    "final.accuracy.calculated.v1",
    "trust.receipt.issued.v1",
    "drift.detected.v1",
    "rollback.triggered.v1",
    "quality.finding.created.v1",
    "recovery.plan.created.v1",
    "recovery.attempt.started.v1",
    "recovery.candidate.generated.v1",
    "recovery.validation.completed.v1",
    "recovery.candidate.accepted.v1",
    "recovery.exhausted.v1",
    "knowledge.objects.invalidated.v1",
    "knowledge.objects.regenerated.v1",
    "package.trust_receipt.created.v1",
)

EXTERNAL_EVIDENCE_GATES = (
    "public_core_benchmarks_three_repeats",
    "private_q1_1500_pages_10000_facts",
    "private_q2_5000_pages_30000_facts",
    "field_shadow_100000_pages",
    "production_r2_role_credentials_and_lifecycle",
    "production_postgres_rls_and_restore_drill",
    "production_runpod_invoice_concurrency_and_fault_drill",
    "independent_private_beta_evidence",
    "legal_domain_and_commercial_clearance",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    masterplan_sha = sha256(MASTERPLAN) if MASTERPLAN.exists() else None
    files = {path: (ROOT / path).is_file() for path in REQUIRED_FILES}
    api_source = (ROOT / "services/api/src/akc_api/trust_api.py").read_text(encoding="utf-8")
    event_source = (
        ROOT / "packages/parallel-runtime/src/akc_parallel_runtime/contracts.py"
    ).read_text(encoding="utf-8")
    endpoints = {endpoint: endpoint in api_source for endpoint in REQUIRED_ENDPOINTS}
    events = {event: event in event_source for event in REQUIRED_EVENTS}
    pdf_path = ROOT / "apps/web/public/proof-sources/dart-jtc-2026-q1.pdf"
    pdf = {
        "exists": pdf_path.is_file(),
        "size_bytes": pdf_path.stat().st_size if pdf_path.is_file() else 0,
        "sha256": sha256(pdf_path) if pdf_path.is_file() else None,
        "expected_sha256": "fb998430db82774afc0d69090383650421ab9a14e6e37c7f32821aa1c6a32eee",
    }
    local_pass = (
        masterplan_sha == EXPECTED_MASTERPLAN_SHA256
        and all(files.values())
        and all(endpoints.values())
        and all(events.values())
        and pdf["sha256"] == pdf["expected_sha256"]
    )
    report = {
        "schema_version": "1.0",
        "masterplan": {
            "path": str(MASTERPLAN),
            "sha256": masterplan_sha,
            "expected_sha256": EXPECTED_MASTERPLAN_SHA256,
            "matched": masterplan_sha == EXPECTED_MASTERPLAN_SHA256,
        },
        "repository_bound": {
            "passed": local_pass,
            "files": files,
            "endpoints": endpoints,
            "events": events,
            "actual_source_pdf": pdf,
        },
        "external_evidence": {gate: "required_not_inferred" for gate in EXTERNAL_EVIDENCE_GATES},
        "release_state": "PRODUCTION-REJECT",
        "release_reason": (
            "Repository-bound audit cannot substitute for external empirical "
            "and deployed evidence gates."
        ),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if local_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
