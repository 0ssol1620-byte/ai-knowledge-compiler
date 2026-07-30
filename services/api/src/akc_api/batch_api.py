"""Atomic, idempotent batch compilation for the developer API."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.abuse_repository import reserve_free_usage
from akc_api.database import Database, get_session, set_rls_context
from akc_api.free_tier import (
    FreeTierCapExceeded,
    FreeTierCaps,
    FreeUsageDelta,
    estimate_gpu_cost,
    queue_priority_for_plan,
)
from akc_api.idempotency import idempotent_mutation
from akc_api.models import (
    Document,
    OutboxEvent,
    ProcessingJob,
    Project,
    Tenant,
    User,
)
from akc_api.project_access import project_access_predicate
from akc_api.security import Principal, require_roles
from akc_api.services import (
    credit_entry,
    emit_event,
    estimate_document,
    run_compile_job,
)
from akc_api.settings import Settings

router = APIRouter(prefix="/v1")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
EditorDep = Annotated[
    Principal,
    Depends(require_roles("owner", "admin", "editor")),
]

RouteProfile = Literal[
    "parse_fast_v1",
    "parse_balanced_v1",
    "parse_precision_v1",
    "parse_private_v1",
    "parse_long_v1",
]
OutputProfile = Literal[
    "portable_markdown_v1",
    "obsidian_vault_v1",
    "rag_jsonl_v1",
    "jsonld_v1",
]


def _default_output_profiles() -> list[OutputProfile]:
    return [
        "portable_markdown_v1",
        "obsidian_vault_v1",
        "rag_jsonl_v1",
        "jsonld_v1",
    ]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchCompileRequest(WireModel):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    route_profile: RouteProfile = "parse_balanced_v1"
    output_profiles: list[OutputProfile] = Field(
        default_factory=_default_output_profiles,
        min_length=1,
        max_length=4,
    )
    external_processing_consent: bool = False
    max_total_credits: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def unique_members(self) -> BatchCompileRequest:
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("document_ids must be unique")
        if len(self.output_profiles) != len(set(self.output_profiles)):
            raise ValueError("output_profiles must be unique")
        return self


class BatchJobResponse(WireModel):
    job_id: uuid.UUID
    document_id: uuid.UUID
    status: str
    reserved_credits: Decimal


class BatchCompileResponse(WireModel):
    batch_id: uuid.UUID
    status: Literal["queued", "running", "completed", "partial", "failed"]
    total_reserved_credits: Decimal
    jobs: list[BatchJobResponse]


def _free_caps(settings: Settings) -> FreeTierCaps:
    return FreeTierCaps(
        files=settings.free_daily_file_cap,
        pages=settings.free_daily_page_cap,
        gpu_cost_usd=settings.free_daily_gpu_cost_usd_cap,
    )


async def _execute_local_batch(
    app: Any,
    *,
    tenant_id: uuid.UUID,
    job_ids: tuple[uuid.UUID, ...],
) -> None:
    settings = cast(Settings, app.state.settings)
    database = cast(Database, app.state.database)
    for job_id in job_ids:
        async with database.sessions() as session:
            await set_rls_context(session, tenant_id=tenant_id)
            await run_compile_job(
                session=session,
                job_id=job_id,
                settings=settings,
                object_store=app.state.object_store,
            )


@router.post(
    "/batches/compile",
    response_model=BatchCompileResponse,
    status_code=202,
)
@idempotent_mutation
async def compile_batch(
    payload: BatchCompileRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: EditorDep,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BatchCompileResponse:
    settings = cast(Settings, request.app.state.settings)
    user = await session.get(User, principal.user_id)
    if user is None or user.email_verified_at is None:
        raise HTTPException(status_code=403, detail={"code": "EMAIL_VERIFICATION_REQUIRED"})
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})
    if payload.external_processing_consent and (
        tenant.private_mode or not tenant.external_transfer_allowed
    ):
        raise HTTPException(status_code=403, detail={"code": "EXTERNAL_TRANSFER_DENIED"})

    requested_ids = list(payload.document_ids)
    documents = list(
        await session.scalars(
            select(Document)
            .join(
                Project,
                (Project.tenant_id == Document.tenant_id) & (Project.id == Document.project_id),
            )
            .where(
                Document.tenant_id == principal.tenant_id,
                Document.id.in_(sorted(requested_ids, key=str)),
                Document.deletion_requested_at.is_(None),
                Project.deletion_requested_at.is_(None),
                project_access_predicate(principal, Document.project_id, "write"),
            )
            .order_by(Document.id)
            .with_for_update()
        )
    )
    by_id = {document.id: document for document in documents}
    missing = [str(document_id) for document_id in requested_ids if document_id not in by_id]
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"code": "BATCH_DOCUMENT_NOT_FOUND", "document_ids": missing},
        )
    not_ready = [
        str(document_id)
        for document_id in requested_ids
        if by_id[document_id].status != "COMPLETED"
    ]
    if not_ready:
        raise HTTPException(
            status_code=409,
            detail={"code": "BATCH_ANALYSIS_REQUIRED", "document_ids": not_ready},
        )

    estimates: dict[uuid.UUID, dict[str, Any]] = {}
    total_reserved = Decimal("0")
    total_gpu_cost = Decimal("0")
    for document_id in requested_ids:
        estimate = await estimate_document(session, by_id[document_id])
        if int(estimate["total_pages"]) <= 0:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DOCUMENT_HAS_NO_PAGES",
                    "document_id": str(document_id),
                },
            )
        estimates[document_id] = estimate
        total_reserved += Decimal(str(estimate["reserved"]))
        total_gpu_cost += estimate_gpu_cost(
            visual_pages=int(estimate["visual_pages"]),
            per_visual_page_usd=settings.free_gpu_cost_per_visual_page_usd,
        )
    if payload.max_total_credits is not None and payload.max_total_credits < total_reserved:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BATCH_CREDIT_CAP_BELOW_ESTIMATE",
                "required": str(total_reserved),
                "maximum": str(payload.max_total_credits),
            },
        )

    batch_id = uuid.uuid4()
    try:
        if total_gpu_cost > 0:
            await reserve_free_usage(
                session,
                tenant_id=principal.tenant_id,
                plan_code=tenant.plan_code,
                operation_key=f"batch:{batch_id}:gpu",
                delta=FreeUsageDelta(gpu_cost_usd=total_gpu_cost),
                caps=_free_caps(settings),
            )
    except FreeTierCapExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "FREE_DAILY_CAP_EXCEEDED",
                "dimension": exc.dimension.value,
                "limit": str(exc.limit),
                "current": str(exc.current),
                "requested": str(exc.requested),
                "retry_after_seconds": exc.retry_after_seconds,
            },
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    jobs: list[ProcessingJob] = []
    for index, document_id in enumerate(requested_ids):
        document = by_id[document_id]
        estimate = estimates[document_id]
        job_id = uuid.uuid4()
        dispatch_key = (
            f"{idempotency_key}:document:{document_id}"
            if idempotency_key
            else f"batch:{batch_id}:document:{document_id}"
        )
        priority = queue_priority_for_plan(tenant.plan_code)
        job = ProcessingJob(
            id=job_id,
            tenant_id=principal.tenant_id,
            project_id=document.project_id,
            document_id=document.id,
            job_type="compile",
            priority=priority,
            requested_options={
                "batch_id": str(batch_id),
                "batch_index": index,
                "route_profile": payload.route_profile,
                "output_profiles": payload.output_profiles,
                "external_processing_consent": payload.external_processing_consent,
                "idempotency_key": dispatch_key,
                "queue_class": "free_low" if priority == 1 else "standard",
            },
            cost_estimate={key: str(value) for key, value in estimate.items()},
            progress={"done": 0, "total": int(estimate["total_pages"])},
        )
        session.add(job)
        await session.flush()
        await credit_entry(
            session,
            tenant_id=principal.tenant_id,
            operation_key=f"job:{job.id}:attempt:0:reserve",
            entry_type="reserve",
            credits=Decimal(str(estimate["reserved"])),
            job_id=job.id,
        )
        await emit_event(
            session,
            job=job,
            event_type="job.created.v1",
            payload={
                "status": "queued",
                "job_type": "compile",
                "batch_id": str(batch_id),
                "batch_index": index,
            },
        )
        await emit_event(
            session,
            job=job,
            event_type="credit.reserved.v1",
            payload={"credits": str(estimate["reserved"])},
        )
        session.add(
            OutboxEvent(
                tenant_id=principal.tenant_id,
                aggregate_type="job",
                aggregate_id=job.id,
                event_type="job.dispatch.requested.v1",
                payload={
                    "job_id": str(job.id),
                    "tenant_id": str(principal.tenant_id),
                    "idempotency_key": dispatch_key,
                    "batch_id": str(batch_id),
                },
            )
        )
        jobs.append(job)
    await session.commit()
    if settings.local_background_tasks:
        background_tasks.add_task(
            _execute_local_batch,
            request.app,
            tenant_id=principal.tenant_id,
            job_ids=tuple(job.id for job in jobs),
        )
    return BatchCompileResponse(
        batch_id=batch_id,
        status="queued",
        total_reserved_credits=total_reserved,
        jobs=[
            BatchJobResponse(
                job_id=job.id,
                document_id=cast(uuid.UUID, job.document_id),
                status=job.status,
                reserved_credits=Decimal(str(job.cost_estimate["reserved"])),
            )
            for job in jobs
        ],
    )


@router.get(
    "/batches/{batch_id}",
    response_model=BatchCompileResponse,
)
async def get_batch(
    batch_id: uuid.UUID,
    principal: Annotated[
        Principal,
        Depends(require_roles("owner", "admin", "editor", "reviewer", "viewer")),
    ],
    session: SessionDep,
) -> BatchCompileResponse:
    jobs = list(
        await session.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.tenant_id == principal.tenant_id,
                ProcessingJob.requested_options["batch_id"].as_string() == str(batch_id),
                project_access_predicate(principal, ProcessingJob.project_id, "read"),
            )
            .order_by(
                ProcessingJob.requested_options["batch_index"].as_integer(),
                ProcessingJob.id,
            )
            .limit(50)
        )
    )
    if not jobs:
        raise HTTPException(status_code=404, detail={"code": "BATCH_NOT_FOUND"})
    statuses = {job.status for job in jobs}
    if statuses == {"completed"}:
        batch_status: Literal["queued", "running", "completed", "partial", "failed"] = "completed"
    elif statuses <= {"failed", "cancelled"}:
        batch_status = "failed"
    elif statuses & {"completed", "failed", "cancelled"}:
        batch_status = "partial"
    elif "running" in statuses:
        batch_status = "running"
    else:
        batch_status = "queued"
    return BatchCompileResponse(
        batch_id=batch_id,
        status=batch_status,
        total_reserved_credits=sum(
            (Decimal(str(job.cost_estimate.get("reserved", "0"))) for job in jobs),
            Decimal("0"),
        ),
        jobs=[
            BatchJobResponse(
                job_id=job.id,
                document_id=cast(uuid.UUID, job.document_id),
                status=job.status,
                reserved_credits=Decimal(str(job.cost_estimate.get("reserved", "0"))),
            )
            for job in jobs
        ],
    )
