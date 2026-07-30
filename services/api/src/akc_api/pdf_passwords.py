"""HTTP boundary for short-lived encrypted-PDF passwords.

The password crosses the API only as a Pydantic ``SecretStr`` and is written to
the configured ephemeral secret store outside a database transaction.  The
database receives only normal analysis task state; no password, ciphertext, or
secret-store locator is persisted.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal, cast

from akc_security import PdfSecretBinding, PdfSecretError, PdfSecretStore
from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.database import Database, get_session
from akc_api.idempotency import idempotent_mutation
from akc_api.models import (
    AnalysisTask,
    Document,
    OutboxEvent,
    Project,
    SourceFile,
    utcnow,
)
from akc_api.project_access import require_project_access
from akc_api.security import Principal, require_roles
from akc_api.services import audit
from akc_api.settings import Settings
from akc_api.storage import ObjectStore

router = APIRouter(prefix="/v1")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
EditorDep = Annotated[
    Principal,
    Depends(require_roles("owner", "admin", "editor")),
]


class PdfPasswordSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr = Field(min_length=1, max_length=1024)


class PdfPasswordAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    task_id: uuid.UUID
    document_id: uuid.UUID
    status: Literal["queued", "running", "completed", "failed", "dead_letter"]
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    password_expires_in_seconds: int = Field(ge=30, le=900)


async def _run_local_task(app: FastAPI, task_id: uuid.UUID) -> None:
    settings = cast(Settings, app.state.settings)
    if settings.env == "production" or not settings.local_analysis_worker_enabled:
        raise RuntimeError("local_analysis_worker_forbidden")
    from akc_worker_document.worker import run_local_analysis_task

    await run_local_analysis_task(
        database=cast(Database, app.state.database),
        store=cast(ObjectStore, app.state.object_store),
        settings=settings,
        task_id=task_id,
        pdf_secret_store=cast(
            PdfSecretStore,
            app.state.pdf_secret_store,
        ),
    )


async def _source_binding(
    session: AsyncSession,
    *,
    principal: Principal,
    document_id: uuid.UUID,
    lock: bool,
) -> tuple[Document, SourceFile, PdfSecretBinding]:
    statement = (
        select(Document, SourceFile)
        .join(
            Project,
            (Project.tenant_id == Document.tenant_id) & (Project.id == Document.project_id),
        )
        .join(
            SourceFile,
            (SourceFile.tenant_id == Document.tenant_id)
            & (SourceFile.id == Document.source_file_id),
        )
        .where(
            Document.tenant_id == principal.tenant_id,
            Document.id == document_id,
            Document.deletion_requested_at.is_(None),
            Project.deletion_requested_at.is_(None),
        )
    )
    if lock:
        statement = statement.with_for_update(of=(Document, SourceFile))
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND"})
    document, source = row
    await require_project_access(
        session,
        principal=principal,
        project_id=document.project_id,
        capability="write",
    )
    if source.mime_type.split(";", 1)[
        0
    ].casefold() != "application/pdf" or not source.safe_filename.casefold().endswith(".pdf"):
        raise HTTPException(status_code=409, detail={"code": "DOCUMENT_NOT_ENCRYPTED_PDF"})
    return (
        document,
        source,
        PdfSecretBinding(
            tenant_id=principal.tenant_id,
            document_id=document_id,
            source_sha256=source.sha256,
        ),
    )


@router.post(
    "/documents/{document_id}/password",
    response_model=PdfPasswordAccepted,
    status_code=202,
)
@idempotent_mutation
async def submit_pdf_password(
    document_id: uuid.UUID,
    payload: PdfPasswordSubmit,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: EditorDep,
    session: SessionDep,
) -> PdfPasswordAccepted:
    settings = cast(Settings, request.app.state.settings)
    secret_store = cast(PdfSecretStore, request.app.state.pdf_secret_store)

    document, source, binding = await _source_binding(
        session,
        principal=principal,
        document_id=document_id,
        lock=False,
    )
    existing = await session.scalar(
        select(AnalysisTask).where(
            AnalysisTask.tenant_id == principal.tenant_id,
            AnalysisTask.document_id == document.id,
            AnalysisTask.source_file_id == source.id,
        )
    )
    if existing is not None and existing.status == "completed":
        raise HTTPException(status_code=409, detail={"code": "ANALYSIS_ALREADY_COMPLETED"})

    # Do not hold a database transaction while calling the external secret
    # store.  The binding is revalidated under a row lock immediately after.
    await session.rollback()
    try:
        await secret_store.put(
            binding,
            payload.password.get_secret_value(),
            ttl_seconds=settings.pdf_password_ttl_seconds,
            max_attempts=settings.pdf_password_max_attempts,
        )
    except PdfSecretError as exc:
        status = 422 if exc.code == "PDF_PASSWORD_INVALID" else 503
        raise HTTPException(status_code=status, detail={"code": exc.code}) from exc

    try:
        locked_document, locked_source, locked_binding = await _source_binding(
            session,
            principal=principal,
            document_id=document_id,
            lock=True,
        )
        if locked_source.id != source.id or locked_binding != binding:
            raise HTTPException(status_code=409, detail={"code": "SOURCE_VERSION_CHANGED"})
        task = await session.scalar(
            select(AnalysisTask)
            .where(
                AnalysisTask.tenant_id == principal.tenant_id,
                AnalysisTask.document_id == locked_document.id,
                AnalysisTask.source_file_id == locked_source.id,
            )
            .with_for_update()
        )
        now = utcnow()
        if task is None:
            task = AnalysisTask(
                tenant_id=principal.tenant_id,
                project_id=locked_document.project_id,
                document_id=locked_document.id,
                source_file_id=locked_source.id,
                requested_by=principal.user_id,
                status="queued",
                max_attempts=settings.analysis_max_attempts,
            )
            session.add(task)
            await session.flush()
        elif task.status == "completed":
            raise HTTPException(status_code=409, detail={"code": "ANALYSIS_ALREADY_COMPLETED"})
        elif task.status != "running":
            task.status = "queued"
            task.attempt_count = 0
            task.max_attempts = settings.analysis_max_attempts
            task.available_at = now
            task.lease_expires_at = None
            task.lease_token = None
            task.last_error_code = None
            task.page_count = 0
            task.block_count = 0
            task.preview_count = 0
            task.started_at = None
            task.completed_at = None
            task.updated_at = now

        event = await session.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.tenant_id == principal.tenant_id,
                OutboxEvent.aggregate_id == task.id,
                OutboxEvent.event_type == "document.analysis.requested.v1",
            )
            .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
            .with_for_update()
        )
        event_payload = {
            "task_id": str(task.id),
            "tenant_id": str(principal.tenant_id),
            "document_id": str(locked_document.id),
        }
        if event is None:
            event = OutboxEvent(
                tenant_id=principal.tenant_id,
                aggregate_type="analysis_task",
                aggregate_id=task.id,
                event_type="document.analysis.requested.v1",
                payload=event_payload,
            )
            session.add(event)
        elif task.status != "running":
            event.payload = event_payload
            event.available_at = now
            event.published_at = None
            event.dead_lettered_at = None
            event.attempts = 0
            event.last_error = None
        locked_document.status = "PREFLIGHTING" if task.status == "running" else "ANALYSIS_QUEUED"
        locked_document.updated_at = now
        await audit(
            session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action="document.pdf_password_submitted",
            target_type="document",
            target_id=str(locked_document.id),
            metadata={
                "task_id": str(task.id),
                "source_sha256": locked_source.sha256,
                "ttl_seconds": settings.pdf_password_ttl_seconds,
            },
        )
        await session.commit()
    except BaseException:
        await session.rollback()
        await secret_store.delete(binding)
        raise

    if task.status == "queued" and settings.local_analysis_worker_enabled:
        background_tasks.add_task(_run_local_task, request.app, task.id)
    return PdfPasswordAccepted(
        task_id=task.id,
        document_id=task.document_id,
        status=cast(
            Literal["queued", "running", "completed", "failed", "dead_letter"],
            task.status,
        ),
        attempt_count=task.attempt_count,
        max_attempts=task.max_attempts,
        password_expires_in_seconds=settings.pdf_password_ttl_seconds,
    )
