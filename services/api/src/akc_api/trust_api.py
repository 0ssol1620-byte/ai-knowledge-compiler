"""Customer-facing scene, proof, recovery, quality, and trust receipt APIs."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime
from typing import Annotated, Any, Literal

from akc_quality.final_metrics import (
    FinalDisposition,
    FinalMetricInput,
    calculate_final_metrics,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.database import get_session
from akc_api.models import (
    Collection,
    Document,
    PackageFile,
    PackageManifest,
    PackageValidation,
    Page,
    ProcessingJob,
    VerificationRecord,
)
from akc_api.parallel_models import AcceptedBlock, RecoveryTask
from akc_api.project_access import project_access_predicate
from akc_api.security import Principal, require_roles

router = APIRouter(prefix="/v1", tags=["trust"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReaderDep = Annotated[
    Principal,
    Depends(require_roles("owner", "admin", "editor", "reviewer", "viewer")),
]


class TrustModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SceneResponse(TrustModel):
    schema_version: Literal["1.0"] = "1.0"
    job_id: uuid.UUID
    status: str
    terminal: bool
    pages_total: int
    page_state_counts: dict[str, int]
    accepted_blocks: int
    unresolved_recoveries: int
    progress: dict[str, Any]
    generated_at: datetime


class QualitySummaryResponse(TrustModel):
    schema_version: Literal["1.0"] = "1.0"
    job_id: uuid.UUID
    verified_count: int
    recovered_verified_count: int
    unresolved_count: int
    excluded_count: int
    critical_false_verified_count: int
    silent_omission_count: int
    verified_coverage: float
    accepted_precision: float | None
    publishable: bool
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...]


class ProofResponse(TrustModel):
    schema_version: Literal["1.0"] = "1.0"
    proof_id: uuid.UUID
    collection_id: uuid.UUID
    status: str
    validator_revision: str
    target: dict[str, str | None]
    evidence: dict[str, Any]
    crop_url: str
    created_at: datetime


class RecoveryResponse(TrustModel):
    schema_version: Literal["1.0"] = "1.0"
    recovery_id: uuid.UUID
    document_id: uuid.UUID
    state: str
    recovery_level: str
    reason_code: str
    target: dict[str, Any]
    preprocessing_variants: list[str]
    route_candidates: list[str]
    source_attempt_id: uuid.UUID
    result_attempt_id: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None


class TrustReceiptResponse(TrustModel):
    schema_version: Literal["1.0"] = "1.0"
    package_id: uuid.UUID
    collection_id: uuid.UUID
    status: str
    signature_status: str
    manifest_sha256: str | None
    package_sha256: str | None
    file_count: int
    validation_status: str
    validation_evidence_sha256: str | None
    warnings: list[str]
    issued_at: datetime
    receipt_sha256: str


def _receipt_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def build_trust_receipt(
    package: PackageManifest,
    *,
    file_count: int,
    validation: PackageValidation | None,
) -> TrustReceiptResponse:
    payload = {
        "schema_version": "1.0",
        "package_id": package.id,
        "collection_id": package.collection_id,
        "status": package.status,
        "signature_status": package.signature_status,
        "manifest_sha256": package.manifest_sha256,
        "package_sha256": package.package_sha256,
        "file_count": file_count,
        "validation_status": validation.status if validation else "missing",
        "validation_evidence_sha256": validation.evidence_sha256 if validation else None,
        "warnings": list(package.warnings),
        "issued_at": package.completed_at or package.created_at,
    }
    return TrustReceiptResponse(**payload, receipt_sha256=_receipt_sha256(payload))


async def _job_or_404(
    job_id: uuid.UUID, principal: Principal, session: AsyncSession
) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.tenant_id == principal.tenant_id,
            project_access_predicate(principal, ProcessingJob.project_id),
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND"})
    return job


@router.get("/jobs/{job_id}/scene", response_model=SceneResponse)
async def job_scene(job_id: uuid.UUID, principal: ReaderDep, session: SessionDep) -> SceneResponse:
    job = await _job_or_404(job_id, principal, session)
    pages = (
        (
            await session.execute(
                select(Page.status, func.count(Page.id))
                .where(
                    Page.tenant_id == principal.tenant_id,
                    Page.document_id == job.document_id,
                )
                .group_by(Page.status)
            )
        ).all()
        if job.document_id is not None
        else []
    )
    states = {str(status): int(count) for status, count in pages}
    accepted = await session.scalar(
        select(func.count(AcceptedBlock.id)).where(
            AcceptedBlock.tenant_id == principal.tenant_id,
            AcceptedBlock.processing_job_id == job.id,
        )
    )
    unresolved = (
        await session.scalar(
            select(func.count(RecoveryTask.id)).where(
                RecoveryTask.tenant_id == principal.tenant_id,
                RecoveryTask.document_id == job.document_id,
                RecoveryTask.state.in_(("UNRESOLVED", "FAILED")),
            )
        )
        if job.document_id is not None
        else 0
    )
    return SceneResponse(
        job_id=job.id,
        status=job.status,
        terminal=job.status in {"completed", "failed", "cancelled"},
        pages_total=sum(states.values()),
        page_state_counts=states,
        accepted_blocks=int(accepted or 0),
        unresolved_recoveries=int(unresolved or 0),
        progress=dict(job.progress),
        generated_at=datetime.now().astimezone(),
    )


@router.get("/jobs/{job_id}/quality-summary", response_model=QualitySummaryResponse)
async def quality_summary(
    job_id: uuid.UUID, principal: ReaderDep, session: SessionDep
) -> QualitySummaryResponse:
    job = await _job_or_404(job_id, principal, session)
    states = Counter(
        (
            await session.scalars(
                select(AcceptedBlock.final_state).where(
                    AcceptedBlock.tenant_id == principal.tenant_id,
                    AcceptedBlock.processing_job_id == job.id,
                )
            )
        ).all()
    )
    unresolved = (
        int(
            await session.scalar(
                select(func.count(RecoveryTask.id)).where(
                    RecoveryTask.tenant_id == principal.tenant_id,
                    RecoveryTask.document_id == job.document_id,
                    RecoveryTask.state.in_(("UNRESOLVED", "FAILED")),
                )
            )
            or 0
        )
        if job.document_id is not None
        else 0
    )
    items = tuple(
        FinalMetricInput(
            FinalDisposition.RECOVERED_VERIFIED
            if state == "auto_repaired"
            else FinalDisposition.VERIFIED
        )
        for state, count in sorted(states.items())
        for _ in range(count)
        if state in {"verified", "authority_verified", "cross_model_verified", "auto_repaired"}
    ) + tuple(FinalMetricInput(FinalDisposition.UNRESOLVED) for _ in range(unresolved))
    metrics = calculate_final_metrics(items)
    return QualitySummaryResponse(
        job_id=job.id,
        verified_count=metrics.verified_count,
        recovered_verified_count=metrics.recovered_verified_count,
        unresolved_count=metrics.unresolved_count,
        excluded_count=metrics.excluded_count,
        critical_false_verified_count=metrics.critical_false_verified_count,
        silent_omission_count=metrics.silent_omission_count,
        verified_coverage=metrics.verified_coverage,
        accepted_precision=metrics.accepted_precision,
        publishable=job.status == "completed" and metrics.publishable,
        reason_codes=(
            metrics.reason_codes
            if job.status == "completed"
            else tuple(sorted(set(metrics.reason_codes) | {"job_not_completed"}))
        ),
        limitations=("block-level projection; public benchmark promotion is independent",),
    )


@router.get("/proofs/{proof_id}", response_model=ProofResponse)
async def proof(proof_id: uuid.UUID, principal: ReaderDep, session: SessionDep) -> ProofResponse:
    row = await session.scalar(
        select(VerificationRecord)
        .join(Collection, Collection.id == VerificationRecord.collection_id)
        .where(
            VerificationRecord.id == proof_id,
            VerificationRecord.tenant_id == principal.tenant_id,
            project_access_predicate(principal, Collection.project_id),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "PROOF_NOT_FOUND"})
    return ProofResponse(
        proof_id=row.id,
        collection_id=row.collection_id,
        status=row.status,
        validator_revision=row.validator_revision,
        target={
            "collection_file_id": str(row.collection_file_id) if row.collection_file_id else None,
            "region_id": str(row.region_id) if row.region_id else None,
        },
        evidence=dict(row.evidence),
        crop_url=f"/v1/proofs/{row.id}/crop",
        created_at=row.created_at,
    )


@router.get("/recovery/{recovery_id}", response_model=RecoveryResponse)
async def recovery(
    recovery_id: uuid.UUID, principal: ReaderDep, session: SessionDep
) -> RecoveryResponse:
    row = await session.scalar(
        select(RecoveryTask)
        .join(Document, Document.id == RecoveryTask.document_id)
        .where(
            RecoveryTask.id == recovery_id,
            RecoveryTask.tenant_id == principal.tenant_id,
            project_access_predicate(principal, Document.project_id),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "RECOVERY_NOT_FOUND"})
    return RecoveryResponse(
        recovery_id=row.id,
        document_id=row.document_id,
        state=row.state,
        recovery_level=row.recovery_level,
        reason_code=row.reason_code,
        target=dict(row.target),
        preprocessing_variants=list(row.preprocessing_variants),
        route_candidates=list(row.route_candidates),
        source_attempt_id=row.source_attempt_id,
        result_attempt_id=row.result_attempt_id,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


@router.get("/packages/{package_id}/trust-receipt", response_model=TrustReceiptResponse)
async def trust_receipt(
    package_id: uuid.UUID, principal: ReaderDep, session: SessionDep
) -> TrustReceiptResponse:
    package = await session.scalar(
        select(PackageManifest)
        .join(Collection, Collection.id == PackageManifest.collection_id)
        .where(
            PackageManifest.id == package_id,
            PackageManifest.tenant_id == principal.tenant_id,
            project_access_predicate(principal, Collection.project_id),
        )
    )
    if package is None:
        raise HTTPException(status_code=404, detail={"code": "PACKAGE_NOT_FOUND"})
    file_count = int(
        await session.scalar(
            select(func.count(PackageFile.id)).where(
                PackageFile.tenant_id == principal.tenant_id,
                PackageFile.package_manifest_id == package.id,
            )
        )
        or 0
    )
    validation = await session.scalar(
        select(PackageValidation)
        .where(
            PackageValidation.tenant_id == principal.tenant_id,
            PackageValidation.export_package_id == package.id,
        )
        .order_by(PackageValidation.created_at.desc())
    )
    return build_trust_receipt(package, file_count=file_count, validation=validation)


__all__ = ["build_trust_receipt", "router"]
