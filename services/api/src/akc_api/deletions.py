"""Durable, tenant-safe deletion lifecycle shared by the API and worker.

Deletion is deliberately split into three durable phases:

1. A short database transaction tombstones the target, cancels work, releases
   outstanding reservations, and writes an immutable manifest plus outbox row.
2. A lease-protected worker purges every object independently and records each
   retry without logging keys or document content.
3. Only after every object is terminally absent does one transaction remove
   domain rows and append the immutable receipt and audit evidence.

Every function here that a worker calls receives an ``async_sessionmaker`` and
opens its *own* session, so the tenant context a caller set on some other
session does not reach it. Each one therefore binds its own transaction with
``enter_tenant_context`` before it touches tenant data — this is the most
destructive path in the repository, and an unbound transaction here would let a
``tenant_id = NULL`` comparison evaluate silently false and record a purge that
deleted nothing.

**One read is deliberately unbound.** The ``deletion_requests`` row is fetched by
primary key before its tenant is known — the same shape as a queue claim, which
has no tenant until a row is read. Binding happens immediately after that read
and before any tenant table is touched. Scoping the claim read itself is the
open problem recorded in ``docs/audit/V5_WORKER_PRIVILEGE_BOUNDARY.md`` §2.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast

from akc_security.tenant_context import enter_tenant_context
from akc_telemetry import record_deletion_attempt, record_deletion_object_result
from akc_url_fetcher.models import UrlFetchTask
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from akc_api.models import (
    AnalysisTask,
    AuditEvent,
    Block,
    BlockRevision,
    CreditLedger,
    DeletionAttempt,
    DeletionObject,
    DeletionReceipt,
    DeletionRequest,
    Document,
    DocumentVersion,
    Entity,
    Export,
    GpuInvocationEvent,
    GpuProviderAttempt,
    GpuProviderInvocation,
    JobEvent,
    KnowledgeNote,
    OutboxEvent,
    Page,
    PageAsset,
    PageAttempt,
    PageAttemptTransitionEvent,
    ProcessingJob,
    Project,
    Relation,
    ReviewItem,
    SourceFile,
    UploadSession,
    utcnow,
)
from akc_api.services import audit, credit_entry
from akc_api.storage import MultipartUploadNotFoundError, ObjectStore

DeletionTargetType = Literal["document", "project"]
_ACTIVE_JOB_STATES = frozenset({"queued", "running", "paused", "waiting_review"})
_DELETION_EVENT_TYPES = (
    "deletion.purge.requested.v1",
    "deletion.retry.requested.v1",
)


@dataclass(frozen=True, slots=True)
class DeletionProcessResult:
    request_id: uuid.UUID
    state: Literal["busy", "retry", "purged", "dead_letter"]
    receipt: DeletionReceipt | None = None


@dataclass(frozen=True, slots=True)
class _ObjectTarget:
    operation: Literal["delete", "abort_multipart"]
    bucket: str
    object_key: str
    provider_upload_id: str | None = None

    @property
    def identity_hash(self) -> str:
        value = f"{self.operation}:{self.bucket}:{self.object_key}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def manifest_value(self) -> dict[str, str]:
        result = {
            "operation": self.operation,
            "bucket": self.bucket,
            "object_key": self.object_key,
            "object_key_hash": self.identity_hash,
        }
        if self.provider_upload_id is not None:
            result["provider_upload_id"] = self.provider_upload_id
        return result


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _target_hash(target_id: uuid.UUID) -> str:
    return hashlib.sha256(str(target_id).encode("ascii")).hexdigest()


async def _ids(
    session: AsyncSession,
    model: type[Any],
    *conditions: Any,
) -> list[uuid.UUID]:
    return list((await session.scalars(select(model.id).where(*conditions))).all())


async def _manifest_for_documents(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    documents: list[Document],
    target_type: DeletionTargetType,
    target_id: uuid.UUID,
) -> tuple[dict[str, Any], list[_ObjectTarget]]:
    document_ids = [document.id for document in documents]
    project_ids = (
        [target_id]
        if target_type == "project"
        else sorted({document.project_id for document in documents}, key=str)
    )

    pages = list(
        (
            await session.scalars(
                select(Page).where(
                    Page.tenant_id == tenant_id,
                    Page.document_id.in_(document_ids),
                )
            )
        ).all()
    )
    page_ids = [page.id for page in pages]
    page_attempts = (
        list(
            (
                await session.scalars(
                    select(PageAttempt).where(
                        PageAttempt.tenant_id == tenant_id,
                        PageAttempt.page_id.in_(page_ids),
                    )
                )
            ).all()
        )
        if page_ids
        else []
    )
    page_attempt_ids = [attempt.id for attempt in page_attempts]
    blocks = list(
        (
            await session.scalars(
                select(Block).where(
                    Block.tenant_id == tenant_id,
                    Block.document_id.in_(document_ids),
                )
            )
        ).all()
    )
    block_ids = [block.id for block in blocks]
    versions = list(
        (
            await session.scalars(
                select(DocumentVersion).where(
                    DocumentVersion.tenant_id == tenant_id,
                    DocumentVersion.document_id.in_(document_ids),
                )
            )
        ).all()
    )
    assets = (
        list(
            (
                await session.scalars(
                    select(PageAsset).where(
                        PageAsset.tenant_id == tenant_id,
                        PageAsset.page_id.in_(page_ids),
                    )
                )
            ).all()
        )
        if page_ids
        else []
    )
    jobs = list(
        (
            await session.scalars(
                select(ProcessingJob).where(
                    ProcessingJob.tenant_id == tenant_id,
                    (
                        ProcessingJob.project_id == target_id
                        if target_type == "project"
                        else ProcessingJob.document_id.in_(document_ids)
                    ),
                )
            )
        ).all()
    )
    job_ids = [job.id for job in jobs]
    analysis_tasks = list(
        (
            await session.scalars(
                select(AnalysisTask).where(
                    AnalysisTask.tenant_id == tenant_id,
                    (
                        AnalysisTask.project_id == target_id
                        if target_type == "project"
                        else AnalysisTask.document_id.in_(document_ids)
                    ),
                )
            )
        ).all()
    )
    url_fetch_tasks = list(
        (
            await session.scalars(
                select(UrlFetchTask).where(
                    UrlFetchTask.tenant_id == tenant_id,
                    (
                        UrlFetchTask.project_id == target_id
                        if target_type == "project"
                        else UrlFetchTask.document_id.in_(document_ids)
                    ),
                )
            )
        ).all()
    )
    gpu_invocations = list(
        (
            await session.scalars(
                select(GpuProviderInvocation).where(
                    GpuProviderInvocation.tenant_id == tenant_id,
                    (
                        GpuProviderInvocation.project_id == target_id
                        if target_type == "project"
                        else GpuProviderInvocation.document_id.in_(document_ids)
                    ),
                )
            )
        ).all()
    )
    gpu_invocation_ids = [invocation.id for invocation in gpu_invocations]
    exports = list(
        (
            await session.scalars(
                select(Export).where(
                    Export.tenant_id == tenant_id,
                    (
                        Export.project_id == target_id
                        if target_type == "project"
                        else Export.document_id.in_(document_ids)
                    ),
                )
            )
        ).all()
    )

    purge_sources: list[SourceFile] = []
    if target_type == "project":
        purge_sources = list(
            (
                await session.scalars(
                    select(SourceFile).where(
                        SourceFile.tenant_id == tenant_id,
                        SourceFile.project_id == target_id,
                    )
                )
            ).all()
        )
    else:
        source_ids = {
            document.source_file_id for document in documents if document.source_file_id is not None
        }
        source_ids.update(
            version.source_file_id for version in versions if version.source_file_id is not None
        )
        sources = list(
            (
                await session.scalars(
                    select(SourceFile).where(
                        SourceFile.tenant_id == tenant_id,
                        SourceFile.id.in_(source_ids),
                    )
                )
            ).all()
        )
        for source in sources:
            active_reference_count = await session.scalar(
                select(func.count(Document.id)).where(
                    Document.tenant_id == tenant_id,
                    Document.source_file_id == source.id,
                    Document.id.not_in(document_ids),
                    Document.deletion_requested_at.is_(None),
                )
            )
            version_reference_count = await session.scalar(
                select(func.count(DocumentVersion.id)).where(
                    DocumentVersion.tenant_id == tenant_id,
                    DocumentVersion.source_file_id == source.id,
                    DocumentVersion.document_id.not_in(document_ids),
                )
            )
            if not active_reference_count and not version_reference_count:
                purge_sources.append(source)

    purge_source_ids = [source.id for source in purge_sources]
    if target_type == "project":
        upload_condition = UploadSession.project_id == target_id
    else:
        upload_condition = UploadSession.document_id.in_(document_ids) | UploadSession.id.in_(
            [source.upload_id for source in purge_sources]
        )
    uploads = list(
        (
            await session.scalars(
                select(UploadSession).where(
                    UploadSession.tenant_id == tenant_id,
                    upload_condition,
                )
            )
        ).all()
    )

    notes: list[KnowledgeNote] = []
    if project_ids:
        candidate_notes = list(
            (
                await session.scalars(
                    select(KnowledgeNote).where(
                        KnowledgeNote.tenant_id == tenant_id,
                        KnowledgeNote.project_id.in_(project_ids),
                    )
                )
            ).all()
        )
        block_id_strings = {str(value) for value in block_ids}
        notes = [
            note
            for note in candidate_notes
            if target_type == "project"
            or bool(block_id_strings.intersection(note.evidence_block_ids))
        ]

    objects: dict[tuple[str, str, str], _ObjectTarget] = {}

    def add_object(target: _ObjectTarget) -> None:
        objects[(target.operation, target.bucket, target.object_key)] = target

    for page in pages:
        if page.render_key:
            add_object(_ObjectTarget("delete", "working", page.render_key))
        if page.thumbnail_key:
            add_object(_ObjectTarget("delete", "derived", page.thumbnail_key))
    for asset in assets:
        bucket = str(asset.metadata_json.get("bucket", "derived"))
        if bucket not in {"working", "derived"}:
            bucket = "derived"
        add_object(_ObjectTarget("delete", bucket, asset.storage_key))
    for version in versions:
        if version.cir_object_key:
            add_object(_ObjectTarget("delete", "derived", version.cir_object_key))
        for archived_object in version.archived_objects:
            archived_bucket = archived_object.get("bucket")
            object_key = archived_object.get("object_key")
            if (
                not isinstance(archived_bucket, str)
                or archived_bucket not in {"working", "derived"}
                or not isinstance(object_key, str)
                or not object_key
            ):
                raise RuntimeError("invalid archived document object manifest")
            add_object(_ObjectTarget("delete", archived_bucket, object_key))
    for export in exports:
        if export.storage_key:
            add_object(_ObjectTarget("delete", "exports", export.storage_key))
    for invocation in gpu_invocations:
        if invocation.input_bucket == "derived":
            add_object(
                _ObjectTarget(
                    "delete",
                    "derived",
                    invocation.input_object_key,
                )
            )
        add_object(
            _ObjectTarget(
                "delete",
                "derived",
                invocation.output_object_key,
            )
        )
    for source in purge_sources:
        add_object(_ObjectTarget("delete", "source", source.storage_key))
    for upload in uploads:
        if (
            upload.upload_mode == "multipart"
            and upload.provider_upload_id
            and upload.status in {"initiated", "uploaded"}
        ):
            add_object(
                _ObjectTarget(
                    "abort_multipart",
                    "quarantine",
                    upload.object_key,
                    upload.provider_upload_id,
                )
            )
        add_object(_ObjectTarget("delete", "quarantine", upload.object_key))

    db_targets: dict[str, list[str]] = {
        "documents": sorted(str(value) for value in document_ids),
        "document_versions": sorted(str(value.id) for value in versions),
        "pages": sorted(str(value) for value in page_ids),
        "page_assets": sorted(str(value.id) for value in assets),
        "page_attempts": sorted(str(value) for value in page_attempt_ids),
        "page_attempt_transition_events": sorted(
            str(value)
            for value in (
                await session.scalars(
                    select(PageAttemptTransitionEvent.id).where(
                        PageAttemptTransitionEvent.tenant_id == tenant_id,
                        PageAttemptTransitionEvent.attempt_id.in_(page_attempt_ids),
                    )
                )
            ).all()
        )
        if page_attempt_ids
        else [],
        "blocks": sorted(str(value) for value in block_ids),
        "block_revisions": sorted(
            str(value)
            for value in (
                await session.scalars(
                    select(BlockRevision.id).where(
                        BlockRevision.tenant_id == tenant_id,
                        BlockRevision.block_id.in_(block_ids),
                    )
                )
            ).all()
        )
        if block_ids
        else [],
        "processing_jobs": sorted(str(value) for value in job_ids),
        "analysis_tasks": sorted(str(value.id) for value in analysis_tasks),
        "url_fetch_tasks": sorted(str(value.id) for value in url_fetch_tasks),
        "gpu_provider_invocations": sorted(str(value) for value in gpu_invocation_ids),
        "gpu_provider_attempts": sorted(
            str(value)
            for value in (
                await session.scalars(
                    select(GpuProviderAttempt.id).where(
                        GpuProviderAttempt.tenant_id == tenant_id,
                        GpuProviderAttempt.invocation_id.in_(gpu_invocation_ids),
                    )
                )
            ).all()
        )
        if gpu_invocation_ids
        else [],
        "gpu_invocation_events": sorted(
            str(value)
            for value in (
                await session.scalars(
                    select(GpuInvocationEvent.id).where(
                        GpuInvocationEvent.tenant_id == tenant_id,
                        GpuInvocationEvent.invocation_id.in_(gpu_invocation_ids),
                    )
                )
            ).all()
        )
        if gpu_invocation_ids
        else [],
        "job_events": sorted(
            str(value)
            for value in (
                await session.scalars(
                    select(JobEvent.id).where(
                        JobEvent.tenant_id == tenant_id,
                        JobEvent.job_id.in_(job_ids),
                    )
                )
            ).all()
        )
        if job_ids
        else [],
        "review_items": sorted(
            str(value)
            for value in (
                await session.scalars(
                    select(ReviewItem.id).where(
                        ReviewItem.tenant_id == tenant_id,
                        (
                            ReviewItem.project_id == target_id
                            if target_type == "project"
                            else ReviewItem.document_id.in_(document_ids)
                        ),
                    )
                )
            ).all()
        ),
        "knowledge_notes": sorted(str(value.id) for value in notes),
        "exports": sorted(str(value.id) for value in exports),
        "source_files": sorted(str(value) for value in purge_source_ids),
        "upload_sessions": sorted(str(value.id) for value in uploads),
    }
    if target_type == "project":
        db_targets["projects"] = [str(target_id)]
        db_targets["entities"] = sorted(
            str(value)
            for value in await _ids(
                session,
                Entity,
                Entity.tenant_id == tenant_id,
                Entity.project_id == target_id,
            )
        )
        db_targets["relations"] = sorted(
            str(value)
            for value in await _ids(
                session,
                Relation,
                Relation.tenant_id == tenant_id,
                Relation.project_id == target_id,
            )
        )

    sorted_objects = sorted(
        objects.values(),
        key=lambda value: (
            0 if value.operation == "abort_multipart" else 1,
            value.bucket,
            value.object_key,
        ),
    )
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "target": {
            "type": target_type,
            "id": str(target_id),
            "id_hash": _target_hash(target_id),
        },
        "database_targets": db_targets,
        "object_targets": [target.manifest_value() for target in sorted_objects],
    }
    return manifest, sorted_objects


async def _outstanding_reservation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
) -> Decimal:
    rows = list(
        (
            await session.execute(
                select(CreditLedger.entry_type, func.sum(CreditLedger.credits))
                .where(
                    CreditLedger.tenant_id == tenant_id,
                    CreditLedger.job_id == job_id,
                    CreditLedger.entry_type.in_(("reserve", "consume", "release")),
                )
                .group_by(CreditLedger.entry_type)
            )
        ).all()
    )
    totals = {str(entry_type): Decimal(total or 0) for entry_type, total in rows}
    return max(
        Decimal("0"),
        totals.get("reserve", Decimal("0"))
        - totals.get("consume", Decimal("0"))
        - totals.get("release", Decimal("0")),
    )


async def _cancel_jobs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    jobs: Iterable[ProcessingJob],
    now: datetime,
) -> None:
    for job in jobs:
        if job.status not in _ACTIVE_JOB_STATES:
            continue
        outstanding = await _outstanding_reservation(
            session,
            tenant_id=tenant_id,
            job_id=job.id,
        )
        job.status = "cancelled"
        job.completed_at = now
        job.error = {
            "code": "TARGET_DELETION_REQUESTED",
            "retryable": False,
        }
        job.event_sequence += 1
        session.add(
            JobEvent(
                tenant_id=tenant_id,
                job_id=job.id,
                sequence=job.event_sequence,
                event_type="job.cancelled.v1",
                payload={
                    "status": "cancelled",
                    "reason": "target_deletion_requested",
                },
            )
        )
        if outstanding > 0:
            await credit_entry(
                session,
                tenant_id=tenant_id,
                operation_key=f"job:{job.id}:deletion-release",
                entry_type="release",
                credits=outstanding,
                job_id=job.id,
                metadata={"reason": "target_deletion_requested"},
            )
            job.event_sequence += 1
            session.add(
                JobEvent(
                    tenant_id=tenant_id,
                    job_id=job.id,
                    sequence=job.event_sequence,
                    event_type="credit.released.v1",
                    payload={
                        "credits": str(outstanding),
                        "reason": "target_deletion_requested",
                    },
                )
            )


def _cancel_analysis_tasks(
    tasks: Iterable[AnalysisTask],
    *,
    now: datetime,
) -> None:
    for task in tasks:
        if task.status not in {"queued", "running"}:
            continue
        task.status = "dead_letter"
        task.last_error_code = "TARGET_DELETION_REQUESTED"
        task.lease_token = None
        task.lease_expires_at = None
        task.completed_at = now


def _cancel_url_fetch_tasks(
    tasks: Iterable[UrlFetchTask],
    *,
    now: datetime,
) -> None:
    for task in tasks:
        if task.status not in {"queued", "retry", "running"}:
            continue
        task.status = "cancelled"
        task.last_error_code = "URL_FETCH_TARGET_DELETED"
        task.available_at = now
        task.lease_token = None
        task.lease_expires_at = None
        task.completed_at = None
        task.cancelled_at = now
        task.updated_at = now


def _cancel_gpu_invocations(
    invocations: Iterable[GpuProviderInvocation],
    *,
    now: datetime,
) -> None:
    for invocation in invocations:
        if invocation.status in {"completed", "failed", "dead_letter", "cancelled"}:
            continue
        invocation.cancellation_reason = "tombstone"
        invocation.available_at = now
        invocation.lease_token = None
        invocation.lease_expires_at = None
        invocation.updated_at = now
        if invocation.provider_job_id is None:
            invocation.status = "cancelled"
            invocation.last_error_code = "GPU_INVOCATION_TOMBSTONE"
            invocation.completed_at = now
        else:
            invocation.status = "cancel_requested"
            invocation.last_error_code = "GPU_INVOCATION_CANCEL_PENDING"


async def create_deletion_request(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    target_type: DeletionTargetType,
    target_id: uuid.UUID,
    emit_outbox: bool = True,
) -> tuple[DeletionRequest, bool]:
    """Atomically tombstone a target and persist its immutable purge plan."""

    existing = await session.scalar(
        select(DeletionRequest).where(
            DeletionRequest.tenant_id == tenant_id,
            DeletionRequest.target_type == target_type,
            DeletionRequest.target_id == target_id,
        )
    )
    if existing is not None:
        return existing, False

    if target_type == "project":
        project_statement = select(Project).where(
            Project.tenant_id == tenant_id,
            Project.id == target_id,
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            project_statement = project_statement.with_for_update()
        project = await session.scalar(project_statement)
        if project is None:
            raise LookupError("project_not_found")
        documents = list(
            (
                await session.scalars(
                    select(Document).where(
                        Document.tenant_id == tenant_id,
                        Document.project_id == project.id,
                    )
                )
            ).all()
        )
    else:
        document_statement = select(Document).where(
            Document.tenant_id == tenant_id,
            Document.id == target_id,
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            document_statement = document_statement.with_for_update()
        document = await session.scalar(document_statement)
        if document is None:
            raise LookupError("document_not_found")
        project = await session.scalar(
            select(Project).where(
                Project.tenant_id == tenant_id,
                Project.id == document.project_id,
            )
        )
        if project is None:
            raise LookupError("project_not_found")
        documents = [document]

    # A concurrent requester can win while this transaction waits for the
    # target row lock. Re-read after admission so the unique target key is a
    # backstop rather than the normal concurrency path.
    existing = await session.scalar(
        select(DeletionRequest).where(
            DeletionRequest.tenant_id == tenant_id,
            DeletionRequest.target_type == target_type,
            DeletionRequest.target_id == target_id,
        )
    )
    if existing is not None:
        return existing, False

    manifest, object_targets = await _manifest_for_documents(
        session,
        tenant_id=tenant_id,
        documents=documents,
        target_type=target_type,
        target_id=target_id,
    )
    manifest_hash = _canonical_hash(manifest)
    now = utcnow()
    deletion_request = DeletionRequest(
        tenant_id=tenant_id,
        target_type=target_type,
        target_id=target_id,
        target_id_hash=_target_hash(target_id),
        requested_by=actor_id,
        state="requested",
        manifest=manifest,
        manifest_hash=manifest_hash,
        object_count=len(object_targets),
        requested_at=now,
    )
    session.add(deletion_request)
    await session.flush()
    for target in object_targets:
        session.add(
            DeletionObject(
                tenant_id=tenant_id,
                deletion_request_id=deletion_request.id,
                operation=target.operation,
                bucket=target.bucket,
                object_key=target.object_key,
                object_key_hash=target.identity_hash,
                provider_upload_id=target.provider_upload_id,
            )
        )

    if target_type == "project":
        project.deletion_requested_at = now
    for document in documents:
        document.deletion_requested_at = now
        document.status = "DELETE_REQUESTED"

    jobs = list(
        (
            await session.scalars(
                select(ProcessingJob).where(
                    ProcessingJob.tenant_id == tenant_id,
                    (
                        ProcessingJob.project_id == target_id
                        if target_type == "project"
                        else ProcessingJob.document_id.in_([document.id for document in documents])
                    ),
                )
            )
        ).all()
    )
    analysis_tasks = list(
        (
            await session.scalars(
                select(AnalysisTask).where(
                    AnalysisTask.tenant_id == tenant_id,
                    (
                        AnalysisTask.project_id == target_id
                        if target_type == "project"
                        else AnalysisTask.document_id.in_([document.id for document in documents])
                    ),
                )
            )
        ).all()
    )
    url_fetch_tasks = list(
        (
            await session.scalars(
                select(UrlFetchTask).where(
                    UrlFetchTask.tenant_id == tenant_id,
                    (
                        UrlFetchTask.project_id == target_id
                        if target_type == "project"
                        else UrlFetchTask.document_id.in_([document.id for document in documents])
                    ),
                )
            )
        ).all()
    )
    gpu_invocation_ids = [
        uuid.UUID(value)
        for value in manifest["database_targets"].get(
            "gpu_provider_invocations",
            [],
        )
    ]
    gpu_invocations = (
        list(
            (
                await session.scalars(
                    select(GpuProviderInvocation).where(
                        GpuProviderInvocation.tenant_id == tenant_id,
                        GpuProviderInvocation.id.in_(gpu_invocation_ids),
                    )
                )
            ).all()
        )
        if gpu_invocation_ids
        else []
    )
    await _cancel_jobs(
        session,
        tenant_id=tenant_id,
        jobs=jobs,
        now=now,
    )
    _cancel_analysis_tasks(analysis_tasks, now=now)
    _cancel_url_fetch_tasks(url_fetch_tasks, now=now)
    _cancel_gpu_invocations(gpu_invocations, now=now)

    aggregate_ids = {
        target_id,
        *(document.id for document in documents),
        *(job.id for job in jobs),
        *(task.id for task in analysis_tasks),
        *(task.id for task in url_fetch_tasks),
        *(invocation.id for invocation in gpu_invocations),
        *(uuid.UUID(value) for value in manifest["database_targets"].get("exports", [])),
    }
    outbox_rows = list(
        (
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.tenant_id == tenant_id,
                    OutboxEvent.aggregate_id.in_(aggregate_ids),
                    OutboxEvent.published_at.is_(None),
                )
            )
        ).all()
    )
    for row in outbox_rows:
        row.published_at = now
        row.last_error = "target_deletion_requested"

    if emit_outbox:
        session.add(
            OutboxEvent(
                tenant_id=tenant_id,
                aggregate_type="deletion_request",
                aggregate_id=deletion_request.id,
                event_type="deletion.purge.requested.v1",
                payload={
                    "deletion_request_id": str(deletion_request.id),
                    "target_type": target_type,
                    "target_id": str(target_id),
                    "manifest_hash": manifest_hash,
                },
            )
        )
    await audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=f"{target_type}.deletion_requested",
        target_type=target_type,
        target_id=deletion_request.target_id_hash,
        metadata={
            "deletion_request_id": str(deletion_request.id),
            "manifest_hash": manifest_hash,
            "object_count": len(object_targets),
            "cancellation_candidates": (
                sum(job.status in _ACTIVE_JOB_STATES for job in jobs)
                + sum(task.status in {"queued", "running"} for task in analysis_tasks)
                + sum(task.status in {"queued", "retry", "running"} for task in url_fetch_tasks)
                + sum(
                    invocation.status
                    in {
                        "queued",
                        "submitting",
                        "submitted",
                        "running",
                        "retry",
                        "cancel_requested",
                        "cancelling",
                    }
                    for invocation in gpu_invocations
                )
            ),
        },
    )
    return deletion_request, True


async def cancel_deletion_work(
    sessions: async_sessionmaker[AsyncSession],
    *,
    request_id: uuid.UUID,
    tenant_id: uuid.UUID,
    clock: Callable[[], datetime] = utcnow,
) -> None:
    """Idempotently fence active analysis/compile work and release reserves.

    ``tenant_id`` is the tenant established when the request was claimed. It is
    checked against the row read here, so a request that changed tenants between
    claim and cancellation refuses rather than fencing the wrong tenant's work.
    """

    async with sessions() as session, session.begin():
        request = await session.get(DeletionRequest, request_id)
        if request is None:
            raise RuntimeError("deletion_request_missing")
        await enter_tenant_context(
            session, tenant_id=tenant_id, expected_tenant_id=request.tenant_id
        )
        job_ids = _manifest_ids(request, "processing_jobs")
        jobs: list[ProcessingJob] = []
        if job_ids:
            statement = select(ProcessingJob).where(
                ProcessingJob.tenant_id == request.tenant_id,
                ProcessingJob.id.in_(job_ids),
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                statement = statement.with_for_update()
            jobs = list((await session.scalars(statement)).all())
        now = clock()
        await _cancel_jobs(
            session,
            tenant_id=request.tenant_id,
            jobs=jobs,
            now=now,
        )
        task_ids = _manifest_ids(request, "analysis_tasks")
        if task_ids:
            task_statement = select(AnalysisTask).where(
                AnalysisTask.tenant_id == request.tenant_id,
                AnalysisTask.id.in_(task_ids),
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                task_statement = task_statement.with_for_update()
            tasks = list((await session.scalars(task_statement)).all())
            _cancel_analysis_tasks(tasks, now=now)
        url_task_ids = _manifest_ids(request, "url_fetch_tasks")
        if url_task_ids:
            url_task_statement = select(UrlFetchTask).where(
                UrlFetchTask.tenant_id == request.tenant_id,
                UrlFetchTask.id.in_(url_task_ids),
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                url_task_statement = url_task_statement.with_for_update()
            url_tasks = list((await session.scalars(url_task_statement)).all())
            _cancel_url_fetch_tasks(url_tasks, now=now)
        gpu_invocation_ids = _manifest_ids(request, "gpu_provider_invocations")
        if gpu_invocation_ids:
            gpu_statement = select(GpuProviderInvocation).where(
                GpuProviderInvocation.tenant_id == request.tenant_id,
                GpuProviderInvocation.id.in_(gpu_invocation_ids),
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                gpu_statement = gpu_statement.with_for_update()
            gpu_invocations = list((await session.scalars(gpu_statement)).all())
            _cancel_gpu_invocations(gpu_invocations, now=now)


async def _gpu_cancellation_pending(
    sessions: async_sessionmaker[AsyncSession],
    *,
    request_id: uuid.UUID,
    tenant_id: uuid.UUID,
    now: datetime,
) -> bool:
    """Keep storage intact while a provider can still write through a grant."""

    async with sessions() as session:
        request = await session.get(DeletionRequest, request_id)
        if request is None:
            raise RuntimeError("deletion_request_missing")
        await enter_tenant_context(
            session, tenant_id=tenant_id, expected_tenant_id=request.tenant_id
        )
        invocation_ids = _manifest_ids(request, "gpu_provider_invocations")
        if not invocation_ids:
            return False
        invocations = list(
            (
                await session.scalars(
                    select(GpuProviderInvocation).where(
                        GpuProviderInvocation.tenant_id == request.tenant_id,
                        GpuProviderInvocation.id.in_(invocation_ids),
                    )
                )
            ).all()
        )
    for invocation in invocations:
        if invocation.provider_job_id is None:
            continue
        if invocation.status in {"completed", "failed", "cancelled"}:
            continue
        grant_expiry = _aware(invocation.object_grant_expires_at)
        if invocation.status == "dead_letter" and grant_expiry is not None and grant_expiry <= now:
            continue
        return True
    return False


async def get_deletion_receipt(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
) -> DeletionReceipt | None:
    return cast(
        DeletionReceipt | None,
        await session.scalar(
            select(DeletionReceipt).where(
                DeletionReceipt.tenant_id == tenant_id,
                DeletionReceipt.id == request_id,
            )
        ),
    )


async def _claim_request(
    sessions: async_sessionmaker[AsyncSession],
    *,
    request_id: uuid.UUID,
    lease_seconds: float,
    now: datetime,
) -> tuple[uuid.UUID, int, uuid.UUID] | None:
    async with sessions() as session, session.begin():
        statement = select(DeletionRequest).where(DeletionRequest.id == request_id)
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        request = await session.scalar(statement)
        if request is None or request.state == "purged":
            return None
        # First read of the request row is unbound by necessity (see module
        # docstring); every write below belongs to exactly one tenant.
        await enter_tenant_context(session, tenant_id=request.tenant_id)
        lease_expires_at = _aware(request.lease_expires_at)
        if request.lease_token is not None and lease_expires_at and lease_expires_at > now:
            return None
        if request.state == "purging" and request.attempts > 0:
            interrupted = await session.scalar(
                select(DeletionAttempt).where(
                    DeletionAttempt.deletion_request_id == request.id,
                    DeletionAttempt.attempt_number == request.attempts,
                    DeletionAttempt.outcome == "started",
                )
            )
            if interrupted is not None:
                interrupted.outcome = "retry"
                interrupted.error_code = "deletion_lease_expired"
                interrupted.completed_at = now
        token = uuid.uuid4()
        request.attempts += 1
        request.state = "purging"
        request.lease_token = token
        request.lease_expires_at = now + timedelta(seconds=lease_seconds)
        request.last_error_code = None
        attempt = DeletionAttempt(
            tenant_id=request.tenant_id,
            deletion_request_id=request.id,
            attempt_number=request.attempts,
            outcome="started",
            started_at=now,
        )
        session.add(attempt)
        return token, request.attempts, request.tenant_id


async def _record_object_result(
    sessions: async_sessionmaker[AsyncSession],
    *,
    request_id: uuid.UUID,
    object_id: uuid.UUID,
    tenant_id: uuid.UUID,
    lease_token: uuid.UUID,
    lease_seconds: float,
    error_code: str | None,
    now: datetime,
) -> bool:
    async with sessions() as session, session.begin():
        request_statement = select(DeletionRequest).where(DeletionRequest.id == request_id)
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            request_statement = request_statement.with_for_update()
        request = await session.scalar(request_statement)
        if request is None or request.lease_token != lease_token:
            return False
        await enter_tenant_context(
            session, tenant_id=tenant_id, expected_tenant_id=request.tenant_id
        )
        row_statement = select(DeletionObject).where(
            DeletionObject.id == object_id,
            DeletionObject.deletion_request_id == request_id,
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            row_statement = row_statement.with_for_update()
        row = await session.scalar(row_statement)
        if row is None:
            return False
        row.attempts += 1
        if error_code is None:
            row.state = "purged"
            row.last_error_code = None
            row.purged_at = now
        else:
            row.last_error_code = error_code
        request.lease_expires_at = now + timedelta(seconds=lease_seconds)
        return error_code is None


def _manifest_ids(request: DeletionRequest, table: str) -> list[uuid.UUID]:
    raw = request.manifest.get("database_targets", {}).get(table, [])
    return [uuid.UUID(str(value)) for value in raw]


async def _finalize_database_purge(
    sessions: async_sessionmaker[AsyncSession],
    *,
    request_id: uuid.UUID,
    tenant_id: uuid.UUID,
    lease_token: uuid.UUID,
    attempt_number: int,
    now: datetime,
) -> DeletionReceipt:
    async with sessions() as session, session.begin():
        statement = select(DeletionRequest).where(DeletionRequest.id == request_id)
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            statement = statement.with_for_update()
        request = await session.scalar(statement)
        if request is None:
            raise RuntimeError("deletion_request_missing")
        # Everything below this line is an irreversible DELETE. Bind before the
        # first one, and refuse outright if the row's tenant is not the tenant
        # this attempt was claimed for.
        await enter_tenant_context(
            session, tenant_id=tenant_id, expected_tenant_id=request.tenant_id
        )
        existing = await get_deletion_receipt(
            session,
            tenant_id=request.tenant_id,
            request_id=request.id,
        )
        if request.state == "purged" and existing is not None:
            return existing
        if request.lease_token != lease_token:
            raise RuntimeError("deletion_lease_lost")
        remaining = await session.scalar(
            select(func.count(DeletionObject.id)).where(
                DeletionObject.deletion_request_id == request.id,
                DeletionObject.state != "purged",
            )
        )
        if remaining:
            raise RuntimeError("deletion_objects_pending")

        note_ids = _manifest_ids(request, "knowledge_notes")
        if note_ids:
            notes = list(
                (
                    await session.scalars(
                        select(KnowledgeNote).where(
                            KnowledgeNote.tenant_id == request.tenant_id,
                            KnowledgeNote.id.in_(note_ids),
                        )
                    )
                ).all()
            )
            for note in notes:
                await session.delete(note)
            # Flush document-scoped notes before deleting their parent. The
            # database FK cascade would otherwise win the unit-of-work race
            # and make the later ORM DELETE report a false zero-row warning.
            await session.flush()

        document_ids = _manifest_ids(request, "documents")
        if document_ids:
            documents = list(
                (
                    await session.scalars(
                        select(Document).where(
                            Document.tenant_id == request.tenant_id,
                            Document.id.in_(document_ids),
                        )
                    )
                ).all()
            )
            for document in documents:
                await session.delete(document)
            await session.flush()

        source_ids = _manifest_ids(request, "source_files")
        if source_ids:
            sources = list(
                (
                    await session.scalars(
                        select(SourceFile).where(
                            SourceFile.tenant_id == request.tenant_id,
                            SourceFile.id.in_(source_ids),
                        )
                    )
                ).all()
            )
            for source in sources:
                reference_count = await session.scalar(
                    select(func.count(Document.id)).where(
                        Document.tenant_id == request.tenant_id,
                        Document.source_file_id == source.id,
                    )
                )
                if not reference_count:
                    await session.delete(source)
            await session.flush()

        upload_ids = _manifest_ids(request, "upload_sessions")
        if upload_ids:
            uploads = list(
                (
                    await session.scalars(
                        select(UploadSession).where(
                            UploadSession.tenant_id == request.tenant_id,
                            UploadSession.id.in_(upload_ids),
                        )
                    )
                ).all()
            )
            for upload in uploads:
                reference_count = await session.scalar(
                    select(func.count(SourceFile.id)).where(
                        SourceFile.tenant_id == request.tenant_id,
                        SourceFile.upload_id == upload.id,
                    )
                )
                if not reference_count:
                    await session.delete(upload)
            await session.flush()

        if request.target_type == "project":
            project = await session.scalar(
                select(Project).where(
                    Project.tenant_id == request.tenant_id,
                    Project.id == request.target_id,
                )
            )
            if project is not None:
                await session.delete(project)
                await session.flush()

        aggregate_ids = {
            request.target_id,
            *document_ids,
            *_manifest_ids(request, "processing_jobs"),
            *_manifest_ids(request, "exports"),
            request.id,
        }
        pending_outbox = list(
            (
                await session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.tenant_id == request.tenant_id,
                        OutboxEvent.published_at.is_(None),
                        (
                            OutboxEvent.aggregate_id.in_(aggregate_ids)
                            | (
                                OutboxEvent.event_type.in_(_DELETION_EVENT_TYPES)
                                & (
                                    OutboxEvent.payload["target_id"].as_string()
                                    == str(request.target_id)
                                )
                            )
                        ),
                    )
                )
            ).all()
        )
        for event in pending_outbox:
            event.published_at = now
            event.dead_lettered_at = None
            event.last_error = None

        receipt = existing or DeletionReceipt(
            id=request.id,
            tenant_id=request.tenant_id,
            target_type=request.target_type,
            target_id_hash=request.target_id_hash,
            manifest_hash=request.manifest_hash,
            deleted_count=request.object_count,
            requested_at=request.requested_at,
            completed_at=now,
        )
        if existing is None:
            session.add(receipt)
        request.state = "purged"
        request.deleted_count = request.object_count
        request.last_error_code = None
        request.lease_token = None
        request.lease_expires_at = None
        request.completed_at = now
        attempt = await session.scalar(
            select(DeletionAttempt).where(
                DeletionAttempt.deletion_request_id == request.id,
                DeletionAttempt.attempt_number == attempt_number,
            )
        )
        if attempt is not None:
            attempt.outcome = "purged"
            attempt.completed_at = now
        session.add(
            AuditEvent(
                tenant_id=request.tenant_id,
                actor_id=request.requested_by,
                action=f"{request.target_type}.purged",
                target_type=request.target_type,
                target_id=request.target_id_hash,
                metadata_json={
                    "deletion_request_id": str(request.id),
                    "manifest_hash": request.manifest_hash,
                    "deleted_objects": request.object_count,
                },
            )
        )
        return receipt


async def _record_attempt_failure(
    sessions: async_sessionmaker[AsyncSession],
    *,
    request_id: uuid.UUID,
    tenant_id: uuid.UUID,
    lease_token: uuid.UUID,
    attempt_number: int,
    failure_hashes: list[str],
    error_code: str,
    max_attempts: int,
    now: datetime,
) -> Literal["retry", "dead_letter"]:
    async with sessions() as session, session.begin():
        statement = select(DeletionRequest).where(DeletionRequest.id == request_id)
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            statement = statement.with_for_update()
        request = await session.scalar(statement)
        if request is None:
            raise RuntimeError("deletion_request_missing")
        if request.lease_token != lease_token:
            return "retry"
        await enter_tenant_context(
            session, tenant_id=tenant_id, expected_tenant_id=request.tenant_id
        )
        terminal = request.attempts >= max_attempts
        state: Literal["retry", "dead_letter"] = "dead_letter" if terminal else "retry"
        request.state = state
        request.last_error_code = error_code
        request.lease_token = None
        request.lease_expires_at = None
        attempt = await session.scalar(
            select(DeletionAttempt).where(
                DeletionAttempt.deletion_request_id == request.id,
                DeletionAttempt.attempt_number == attempt_number,
            )
        )
        if attempt is not None:
            attempt.outcome = state
            attempt.failure_hashes = sorted(set(failure_hashes))
            attempt.error_code = error_code
            attempt.completed_at = now
        if terminal:
            events = list(
                (
                    await session.scalars(
                        select(OutboxEvent).where(
                            OutboxEvent.tenant_id == request.tenant_id,
                            OutboxEvent.published_at.is_(None),
                            OutboxEvent.event_type.in_(_DELETION_EVENT_TYPES),
                            (
                                (OutboxEvent.aggregate_id == request.id)
                                | (
                                    OutboxEvent.payload["target_id"].as_string()
                                    == str(request.target_id)
                                )
                            ),
                        )
                    )
                ).all()
            )
            for event in events:
                event.dead_lettered_at = now
                event.last_error = error_code
        return state


async def process_deletion_request(
    sessions: async_sessionmaker[AsyncSession],
    *,
    object_store: ObjectStore,
    request_id: uuid.UUID,
    lease_seconds: float = 300.0,
    max_attempts: int = 20,
    clock: Callable[[], datetime] = utcnow,
) -> DeletionProcessResult:
    """Run one idempotent purge attempt without holding DB locks over I/O."""

    now = clock()
    claimed = await _claim_request(
        sessions,
        request_id=request_id,
        lease_seconds=lease_seconds,
        now=now,
    )
    if claimed is None:
        async with sessions() as session:
            request = await session.get(DeletionRequest, request_id)
            if request is not None and request.state == "purged":
                # No claim, so no tenant was established earlier; the row's own
                # tenant is all there is to bind to before reading its receipt.
                await enter_tenant_context(session, tenant_id=request.tenant_id)
                receipt = await get_deletion_receipt(
                    session,
                    tenant_id=request.tenant_id,
                    request_id=request.id,
                )
                return DeletionProcessResult(
                    request_id=request_id,
                    state="purged",
                    receipt=receipt,
                )
        record_deletion_attempt("busy")
        return DeletionProcessResult(request_id=request_id, state="busy")

    lease_token, attempt_number, tenant_id = claimed
    try:
        await cancel_deletion_work(
            sessions,
            request_id=request_id,
            tenant_id=tenant_id,
            clock=clock,
        )
    except Exception as exc:
        state = await _record_attempt_failure(
            sessions,
            request_id=request_id,
            tenant_id=tenant_id,
            lease_token=lease_token,
            attempt_number=attempt_number,
            failure_hashes=[],
            error_code=f"cancellation_{type(exc).__name__}"[:120],
            max_attempts=max_attempts,
            now=clock(),
        )
        record_deletion_attempt(state)
        return DeletionProcessResult(request_id=request_id, state=state)
    if await _gpu_cancellation_pending(
        sessions,
        request_id=request_id,
        tenant_id=tenant_id,
        now=clock(),
    ):
        state = await _record_attempt_failure(
            sessions,
            request_id=request_id,
            tenant_id=tenant_id,
            lease_token=lease_token,
            attempt_number=attempt_number,
            failure_hashes=[],
            error_code="gpu_cancellation_pending",
            max_attempts=max_attempts,
            now=clock(),
        )
        record_deletion_attempt(state)
        return DeletionProcessResult(request_id=request_id, state=state)
    failures: list[str] = []
    error_codes: list[str] = []
    async with sessions() as session:
        await enter_tenant_context(session, tenant_id=tenant_id)
        objects = list(
            (
                await session.scalars(
                    select(DeletionObject)
                    .where(
                        DeletionObject.deletion_request_id == request_id,
                        DeletionObject.state == "pending",
                    )
                    .order_by(
                        DeletionObject.operation.asc(),
                        DeletionObject.bucket,
                        DeletionObject.id,
                    )
                )
            ).all()
        )

    for row in objects:
        error_code: str | None = None
        try:
            if row.operation == "abort_multipart":
                if not row.provider_upload_id:
                    raise RuntimeError("multipart_upload_identifier_missing")
                await object_store.abort_multipart_upload(
                    object_key=row.object_key,
                    provider_upload_id=row.provider_upload_id,
                )
            else:
                await object_store.delete(row.bucket, row.object_key)
        except MultipartUploadNotFoundError:
            error_code = None
        except Exception as exc:
            error_code = f"object_store_{type(exc).__name__}"[:120]
        recorded = await _record_object_result(
            sessions,
            request_id=request_id,
            object_id=row.id,
            tenant_id=tenant_id,
            lease_token=lease_token,
            lease_seconds=lease_seconds,
            error_code=error_code,
            now=clock(),
        )
        if error_code is not None:
            record_deletion_object_result("retry")
            failures.append(row.object_key_hash)
            error_codes.append(error_code)
        elif not recorded:
            record_deletion_object_result("retry")
            failures.append(row.object_key_hash)
            error_codes.append("deletion_lease_lost")
            break
        else:
            record_deletion_object_result("purged")

    if failures:
        dominant_error = sorted(error_codes)[0]
        state = await _record_attempt_failure(
            sessions,
            request_id=request_id,
            tenant_id=tenant_id,
            lease_token=lease_token,
            attempt_number=attempt_number,
            failure_hashes=failures,
            error_code=dominant_error,
            max_attempts=max_attempts,
            now=clock(),
        )
        record_deletion_attempt(state)
        return DeletionProcessResult(request_id=request_id, state=state)

    try:
        receipt = await _finalize_database_purge(
            sessions,
            request_id=request_id,
            tenant_id=tenant_id,
            lease_token=lease_token,
            attempt_number=attempt_number,
            now=clock(),
        )
    except Exception as exc:
        state = await _record_attempt_failure(
            sessions,
            request_id=request_id,
            tenant_id=tenant_id,
            lease_token=lease_token,
            attempt_number=attempt_number,
            failure_hashes=[],
            error_code=f"database_{type(exc).__name__}"[:120],
            max_attempts=max_attempts,
            now=clock(),
        )
        record_deletion_attempt(state)
        return DeletionProcessResult(request_id=request_id, state=state)
    record_deletion_attempt("purged")
    return DeletionProcessResult(
        request_id=request_id,
        state="purged",
        receipt=receipt,
    )
