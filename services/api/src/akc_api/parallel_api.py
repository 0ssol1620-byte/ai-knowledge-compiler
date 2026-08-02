"""Read-only customer and advanced views over truthful v6 runtime evidence."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.database import get_session, set_rls_context
from akc_api.models import (
    Collection,
    CollectionEvent,
    CreditLedger,
    Document,
    ProcessingJob,
    Project,
    utcnow,
)
from akc_api.parallel_models import (
    AcceptedBlock,
    AcceptedBlockInvalidation,
    ArbitrationDecision,
    AttemptValidation,
    ContinuityEdge,
    ParallelParseAttempt,
    ParallelParseShard,
    RecoveryTask,
    WorkerHealth,
)
from akc_api.project_access import project_access_predicate
from akc_api.security import Principal, require_roles

router = APIRouter(prefix="/v1", tags=["parallel-runtime"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReaderDep = Annotated[
    Principal,
    Depends(require_roles("owner", "admin", "editor", "reviewer", "viewer")),
]


class ParallelShardView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    shard_key: str
    shard_kind: str
    page_start: int
    page_end: int
    route_class: str
    priority: int
    status: str
    attempt_count: int
    retry_count: int
    validator_status: Literal["pending", "passed", "failed"]
    active_worker_id: str | None


class ParallelAttemptView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    shard_id: uuid.UUID
    attempt_number: int
    attempt_kind: str
    state: str
    pool_key: str
    worker_id: str | None
    model_id: str
    model_revision: str
    runtime_identity: str
    billing_disposition: str
    gpu_milliseconds: int
    cost_usd: Decimal
    started_at: datetime | None
    completed_at: datetime | None


class WorkerPoolView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pool_key: str
    worker_count: int
    healthy: int
    degraded: int
    draining: int
    quarantined: int
    inflight: int
    capacity: int
    semantic_score_min: Decimal | None


class ParallelIntegrityView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_state_counts: dict[str, int]
    validation_status_counts: dict[str, int]
    recovery_state_counts: dict[str, int]
    arbitration_state_counts: dict[str, int]
    unresolved_count: int
    quarantined_count: int
    hard_fail_count: int
    active_accepted_block_count: int
    invalidated_block_count: int


class ParallelContinuityView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_type_counts: dict[str, int]
    edge_status_counts: dict[str, int]
    accepted_edge_count: int
    unresolved_edge_count: int


class ParallelUsageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gpu_milliseconds: int
    cost_usd: Decimal
    accepted_billable_attempts: int
    duplicate_billable_attempts: int
    billable_credits: Decimal
    refunded_credits: Decimal
    settlement_mismatch_count: int


class ParallelDocumentSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["6.0"] = "6.0"
    collection_id: uuid.UUID
    document_id: uuid.UUID
    processing_job_id: uuid.UUID
    document_version_id: str
    processing_job_status: str
    generated_at: datetime
    event_stream_url: str
    shards_total: int
    attempts_total: int
    shards_truncated: bool
    attempts_truncated: bool
    shard_state_counts: dict[str, int]
    pages_total: int
    pages_active_parallel: int
    shards: list[ParallelShardView]
    attempts: list[ParallelAttemptView]
    worker_pools: list[WorkerPoolView]
    integrity: ParallelIntegrityView
    continuity: ParallelContinuityView
    usage: ParallelUsageView


@dataclass(frozen=True, slots=True)
class _SnapshotScope:
    processing_job_id: uuid.UUID
    document_version_id: str
    processing_job_status: str


_ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "paused", "waiting_review"})


def _scope_error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


async def _resolve_snapshot_scope(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    processing_job_id: uuid.UUID | None,
    document_version_id: str | None,
) -> _SnapshotScope:
    """Resolve exactly one durable execution lineage or fail closed.

    A document can retain many parallel-runtime generations.  The customer
    snapshot must therefore never infer its scope from a document-wide query.
    Explicit callers may select historical evidence.  Default callers receive
    the sole active execution, or the latest materialized execution only when
    no relevant active job exists.
    """

    if (processing_job_id is None) != (document_version_id is None):
        raise _scope_error(422, "PARALLEL_SNAPSHOT_SCOPE_INCOMPLETE")
    if document_version_id is not None and (
        not document_version_id
        or len(document_version_id) > 160
        or any(character.isspace() for character in document_version_id)
    ):
        raise _scope_error(422, "PARALLEL_SNAPSHOT_VERSION_INVALID")

    shard_identity_scope = (
        ParallelParseShard.tenant_id == tenant_id,
        ParallelParseShard.collection_id == collection_id,
        ParallelParseShard.document_id == document_id,
    )
    if processing_job_id is not None and document_version_id is not None:
        job = await session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.tenant_id == tenant_id,
                ProcessingJob.project_id == project_id,
                ProcessingJob.document_id == document_id,
                ProcessingJob.id == processing_job_id,
            )
        )
        materialized = await session.scalar(
            select(func.count(ParallelParseShard.id)).where(
                *shard_identity_scope,
                ParallelParseShard.processing_job_id == processing_job_id,
                ParallelParseShard.document_version_id == document_version_id,
            )
        )
        if job is None or not materialized:
            raise _scope_error(404, "PARALLEL_SNAPSHOT_SCOPE_NOT_FOUND")
        return _SnapshotScope(
            processing_job_id=job.id,
            document_version_id=document_version_id,
            processing_job_status=job.status,
        )

    scope_rows = (
        await session.execute(
            select(
                ParallelParseShard.processing_job_id,
                ParallelParseShard.document_version_id,
            )
            .where(*shard_identity_scope)
            .group_by(
                ParallelParseShard.processing_job_id,
                ParallelParseShard.document_version_id,
            )
        )
    ).all()
    scopes_by_job: dict[uuid.UUID, set[str]] = defaultdict(set)
    for job_id, version_id in scope_rows:
        scopes_by_job[job_id].add(version_id)

    if not scopes_by_job:
        pending_job = await session.scalar(
            select(ProcessingJob.id).where(
                ProcessingJob.tenant_id == tenant_id,
                ProcessingJob.project_id == project_id,
                ProcessingJob.document_id == document_id,
                ProcessingJob.job_type.in_(("compile", "parallel_v6")),
                ProcessingJob.status.in_(_ACTIVE_JOB_STATUSES),
            )
        )
        if pending_job is not None:
            raise _scope_error(409, "PARALLEL_SNAPSHOT_SCOPE_NOT_READY")
        raise _scope_error(404, "PARALLEL_SNAPSHOT_NOT_FOUND")

    scoped_jobs = list(
        (
            await session.scalars(
                select(ProcessingJob).where(
                    ProcessingJob.tenant_id == tenant_id,
                    ProcessingJob.project_id == project_id,
                    ProcessingJob.document_id == document_id,
                    ProcessingJob.id.in_(tuple(scopes_by_job)),
                )
            )
        ).all()
    )
    if len(scoped_jobs) != len(scopes_by_job):
        raise _scope_error(409, "PARALLEL_SNAPSHOT_SCOPE_CORRUPT")

    relevant_job_types = tuple(sorted({job.job_type for job in scoped_jobs}))
    active_jobs = list(
        (
            await session.scalars(
                select(ProcessingJob).where(
                    ProcessingJob.tenant_id == tenant_id,
                    ProcessingJob.project_id == project_id,
                    ProcessingJob.document_id == document_id,
                    ProcessingJob.job_type.in_(relevant_job_types),
                    ProcessingJob.status.in_(_ACTIVE_JOB_STATUSES),
                )
            )
        ).all()
    )
    if len(active_jobs) > 1:
        raise _scope_error(409, "PARALLEL_SNAPSHOT_SCOPE_AMBIGUOUS")
    if active_jobs:
        selected_job = active_jobs[0]
        versions = scopes_by_job.get(selected_job.id, set())
        if not versions:
            # A newly active execution supersedes finalized history, but has no
            # authoritative materialized plan to expose yet.
            raise _scope_error(409, "PARALLEL_SNAPSHOT_SCOPE_NOT_READY")
    else:
        latest_created_at = max(job.created_at for job in scoped_jobs)
        latest_jobs = [job for job in scoped_jobs if job.created_at == latest_created_at]
        if len(latest_jobs) != 1:
            raise _scope_error(409, "PARALLEL_SNAPSHOT_SCOPE_AMBIGUOUS")
        selected_job = latest_jobs[0]
        versions = scopes_by_job[selected_job.id]

    if len(versions) != 1:
        raise _scope_error(409, "PARALLEL_SNAPSHOT_VERSION_AMBIGUOUS")
    return _SnapshotScope(
        processing_job_id=selected_job.id,
        document_version_id=next(iter(versions)),
        processing_job_status=selected_job.status,
    )


async def _authorized_collection_document(
    session: AsyncSession,
    *,
    principal: Principal,
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
) -> tuple[Collection, Document]:
    collection = await session.scalar(
        select(Collection)
        .join(
            Project,
            (Project.tenant_id == Collection.tenant_id) & (Project.id == Collection.project_id),
        )
        .where(
            Collection.tenant_id == principal.tenant_id,
            Collection.id == collection_id,
            Collection.deletion_requested_at.is_(None),
            Project.deletion_requested_at.is_(None),
            project_access_predicate(principal, Collection.project_id, "read"),
        )
    )
    if collection is None:
        raise HTTPException(status_code=404, detail={"code": "COLLECTION_NOT_FOUND"})
    document = await session.scalar(
        select(Document).where(
            Document.tenant_id == principal.tenant_id,
            Document.id == document_id,
            Document.project_id == collection.project_id,
            Document.deletion_requested_at.is_(None),
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND"})
    return collection, document


@router.get(
    "/collections/{collection_id}/parallel/documents/{document_id}/jobs/"
    "{processing_job_id}/events/stream"
)
async def stream_parallel_document_events(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    processing_job_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    principal: ReaderDep,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Replay events for one unambiguous durable execution lineage only."""

    collection, document = await _authorized_collection_document(
        session,
        principal=principal,
        collection_id=collection_id,
        document_id=document_id,
    )
    versions = list(
        (
            await session.scalars(
                select(ParallelParseShard.document_version_id)
                .where(
                    ParallelParseShard.tenant_id == principal.tenant_id,
                    ParallelParseShard.collection_id == collection.id,
                    ParallelParseShard.document_id == document.id,
                    ParallelParseShard.processing_job_id == processing_job_id,
                )
                .distinct()
            )
        ).all()
    )
    if not versions:
        raise _scope_error(404, "PARALLEL_SNAPSHOT_SCOPE_NOT_FOUND")
    if len(versions) != 1:
        raise _scope_error(409, "PARALLEL_SNAPSHOT_VERSION_AMBIGUOUS")
    snapshot_scope = await _resolve_snapshot_scope(
        session,
        tenant_id=principal.tenant_id,
        project_id=collection.project_id,
        collection_id=collection.id,
        document_id=document.id,
        processing_job_id=processing_job_id,
        document_version_id=versions[0],
    )

    cursor = after_sequence
    if last_event_id is not None:
        try:
            replay_cursor = int(last_event_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "COLLECTION_EVENT_ID_INVALID"},
            ) from exc
        if replay_cursor < 0:
            raise HTTPException(
                status_code=400,
                detail={"code": "COLLECTION_EVENT_ID_INVALID"},
            )
        cursor = max(cursor, replay_cursor)

    tenant_id = principal.tenant_id
    user_id = principal.user_id
    database = request.app.state.database

    async def event_stream() -> AsyncIterator[str]:
        nonlocal cursor
        loop = asyncio.get_running_loop()
        last_keepalive = loop.time()
        yield "retry: 2000\n\n"
        while not await request.is_disconnected():
            async with database.sessions() as event_session:
                await set_rls_context(
                    event_session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
                rows = list(
                    (
                        await event_session.scalars(
                            select(CollectionEvent)
                            .where(
                                CollectionEvent.tenant_id == tenant_id,
                                CollectionEvent.collection_id == collection.id,
                                CollectionEvent.job_id == snapshot_scope.processing_job_id,
                                CollectionEvent.sequence > cursor,
                            )
                            .order_by(CollectionEvent.sequence)
                            .limit(200)
                        )
                    ).all()
                )
            if rows:
                for row in rows:
                    cursor = row.sequence
                    body = json.dumps(
                        {
                            "event_id": str(row.id),
                            "collection_id": str(row.collection_id),
                            "document_id": str(document.id),
                            "processing_job_id": str(snapshot_scope.processing_job_id),
                            "document_version_id": snapshot_scope.document_version_id,
                            "sequence": row.sequence,
                            "event_type": row.event_type,
                            "timestamp": row.occurred_at.isoformat(),
                            "payload": row.payload,
                            "schema_version": row.schema_version,
                        },
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    yield f"id: {row.sequence}\nevent: {row.event_type}\ndata: {body}\n\n"
                last_keepalive = loop.time()
                continue
            if loop.time() - last_keepalive >= 15:
                yield ": keepalive\n\n"
                last_keepalive = loop.time()
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _worker_pool_views(rows: list[WorkerHealth]) -> list[WorkerPoolView]:
    grouped: dict[str, list[WorkerHealth]] = defaultdict(list)
    for row in rows:
        grouped[row.pool_key].append(row)
    output = []
    for pool_key, workers in sorted(grouped.items()):
        states = Counter(worker.state for worker in workers)
        semantic_scores = [worker.semantic_score for worker in workers]
        output.append(
            WorkerPoolView(
                pool_key=pool_key,
                worker_count=len(workers),
                healthy=states["HEALTHY"],
                degraded=states["DEGRADED"],
                draining=states["DRAINING"],
                quarantined=states["QUARANTINED"],
                inflight=sum(worker.inflight for worker in workers),
                capacity=sum(worker.capacity for worker in workers),
                semantic_score_min=min(semantic_scores) if semantic_scores else None,
            )
        )
    return output


@router.get(
    "/collections/{collection_id}/parallel/documents/{document_id}",
    response_model=ParallelDocumentSnapshot,
)
async def get_parallel_document_snapshot(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    principal: ReaderDep,
    processing_job_id: uuid.UUID | None = None,
    document_version_id: str | None = None,
) -> ParallelDocumentSnapshot:
    """Return the durable Processing Theater and optional technical projection."""

    collection, document = await _authorized_collection_document(
        session,
        principal=principal,
        collection_id=collection_id,
        document_id=document_id,
    )
    snapshot_scope = await _resolve_snapshot_scope(
        session,
        tenant_id=principal.tenant_id,
        project_id=collection.project_id,
        collection_id=collection.id,
        document_id=document.id,
        processing_job_id=processing_job_id,
        document_version_id=document_version_id,
    )
    shard_scope = (
        ParallelParseShard.tenant_id == principal.tenant_id,
        ParallelParseShard.collection_id == collection.id,
        ParallelParseShard.document_id == document.id,
        ParallelParseShard.processing_job_id == snapshot_scope.processing_job_id,
        ParallelParseShard.document_version_id == snapshot_scope.document_version_id,
    )
    shards_total = int(
        await session.scalar(select(func.count(ParallelParseShard.id)).where(*shard_scope)) or 0
    )
    shards = list(
        (
            await session.scalars(
                select(ParallelParseShard)
                .where(
                    *shard_scope,
                )
                .order_by(ParallelParseShard.ordinal, ParallelParseShard.id)
                .limit(2_000)
            )
        ).all()
    )
    shard_ids = [row.id for row in shards]
    attempts_total = (
        int(
            await session.scalar(
                select(func.count(ParallelParseAttempt.id)).where(
                    ParallelParseAttempt.tenant_id == principal.tenant_id,
                    ParallelParseAttempt.shard_id.in_(shard_ids),
                )
            )
            or 0
        )
        if shard_ids
        else 0
    )
    attempts = (
        list(
            (
                await session.scalars(
                    select(ParallelParseAttempt)
                    .where(
                        ParallelParseAttempt.tenant_id == principal.tenant_id,
                        ParallelParseAttempt.shard_id.in_(shard_ids),
                    )
                    .order_by(
                        ParallelParseAttempt.created_at,
                        ParallelParseAttempt.attempt_number,
                    )
                    .limit(5_000)
                )
            ).all()
        )
        if shard_ids
        else []
    )
    attempt_ids = [row.id for row in attempts]
    validations = (
        list(
            (
                await session.scalars(
                    select(AttemptValidation).where(
                        AttemptValidation.tenant_id == principal.tenant_id,
                        AttemptValidation.attempt_id.in_(attempt_ids),
                    )
                )
            ).all()
        )
        if attempt_ids
        else []
    )
    accepted_history = (
        list(
            (
                await session.scalars(
                    select(AcceptedBlock).where(
                        AcceptedBlock.tenant_id == principal.tenant_id,
                        AcceptedBlock.document_id == document.id,
                        AcceptedBlock.processing_job_id == snapshot_scope.processing_job_id,
                        AcceptedBlock.document_version_id == snapshot_scope.document_version_id,
                        AcceptedBlock.shard_id.in_(shard_ids),
                    )
                )
            ).all()
        )
        if shard_ids
        else []
    )
    accepted_ids = [block.id for block in accepted_history]
    invalidations = (
        list(
            (
                await session.scalars(
                    select(AcceptedBlockInvalidation).where(
                        AcceptedBlockInvalidation.tenant_id == principal.tenant_id,
                        AcceptedBlockInvalidation.processing_job_id
                        == snapshot_scope.processing_job_id,
                        AcceptedBlockInvalidation.document_version_id
                        == snapshot_scope.document_version_id,
                        AcceptedBlockInvalidation.accepted_block_id.in_(accepted_ids),
                    )
                )
            ).all()
        )
        if accepted_ids
        else []
    )
    invalidated_block_ids = {row.accepted_block_id for row in invalidations}
    accepted = [block for block in accepted_history if block.id not in invalidated_block_ids]
    recoveries = list(
        (
            await session.scalars(
                select(RecoveryTask).where(
                    RecoveryTask.tenant_id == principal.tenant_id,
                    RecoveryTask.document_id == document.id,
                    RecoveryTask.shard_id.in_(shard_ids),
                )
            )
        ).all()
    )
    continuity = list(
        (
            await session.scalars(
                select(ContinuityEdge).where(
                    ContinuityEdge.tenant_id == principal.tenant_id,
                    ContinuityEdge.document_id == document.id,
                    ContinuityEdge.source_shard_id.in_(shard_ids),
                    ContinuityEdge.target_shard_id.in_(shard_ids),
                )
            )
        ).all()
    )
    arbitrations = list(
        (
            await session.scalars(
                select(ArbitrationDecision).where(
                    ArbitrationDecision.tenant_id == principal.tenant_id,
                    ArbitrationDecision.document_id == document.id,
                    ArbitrationDecision.shard_id.in_(shard_ids),
                )
            )
        ).all()
    )
    settlement_keys = {
        row.credit_settlement_key
        for row in accepted
        if row.billable and row.credit_settlement_key is not None
    }
    ledgers = (
        list(
            (
                await session.scalars(
                    select(CreditLedger).where(
                        CreditLedger.tenant_id == principal.tenant_id,
                        CreditLedger.job_id == snapshot_scope.processing_job_id,
                        CreditLedger.operation_key.in_(settlement_keys),
                    )
                )
            ).all()
        )
        if settlement_keys
        else []
    )
    refund_keys = {
        row.refund_settlement_key for row in invalidations if row.refund_settlement_key is not None
    }
    refund_ledgers = (
        list(
            (
                await session.scalars(
                    select(CreditLedger).where(
                        CreditLedger.tenant_id == principal.tenant_id,
                        CreditLedger.job_id == snapshot_scope.processing_job_id,
                        CreditLedger.operation_key.in_(refund_keys),
                    )
                )
            ).all()
        )
        if refund_keys
        else []
    )
    pool_keys = sorted({attempt.pool_key for attempt in attempts})
    workers = (
        list(
            (
                await session.scalars(
                    select(WorkerHealth).where(
                        WorkerHealth.tenant_id == principal.tenant_id,
                        WorkerHealth.pool_key.in_(pool_keys),
                    )
                )
            ).all()
        )
        if pool_keys
        else []
    )
    attempts_by_shard: dict[uuid.UUID, list[ParallelParseAttempt]] = defaultdict(list)
    validations_by_attempt: dict[uuid.UUID, list[AttemptValidation]] = defaultdict(list)
    for attempt in attempts:
        attempts_by_shard[attempt.shard_id].append(attempt)
    for validation in validations:
        validations_by_attempt[validation.attempt_id].append(validation)
    accepted_attempt_ids_by_shard: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for block in accepted:
        accepted_attempt_ids_by_shard[block.shard_id].add(block.attempt_id)
    authoritative_validations: list[AttemptValidation] = []
    shard_views = []
    for shard in shards:
        shard_attempts = attempts_by_shard[shard.id]
        authoritative_attempt_ids = accepted_attempt_ids_by_shard[shard.id]
        if not authoritative_attempt_ids and shard_attempts:
            authoritative_attempt_ids = {
                max(shard_attempts, key=lambda attempt: attempt.attempt_number).id
            }
        shard_validations = [
            validation
            for attempt in shard_attempts
            if attempt.id in authoritative_attempt_ids
            for validation in validations_by_attempt[attempt.id]
        ]
        authoritative_validations.extend(shard_validations)
        validator_status: Literal["pending", "passed", "failed"] = "pending"
        if any(row.hard_fail or row.status == "failed" for row in shard_validations):
            validator_status = "failed"
        elif shard_validations and accepted_attempt_ids_by_shard[shard.id]:
            validator_status = "passed"
        active_worker = next(
            (
                attempt.worker_id
                for attempt in reversed(shard_attempts)
                if attempt.state in {"RUNNING", "OUTPUT_RECEIVED", "VALIDATING"}
            ),
            None,
        )
        shard_views.append(
            ParallelShardView(
                id=shard.id,
                shard_key=shard.shard_key,
                shard_kind=shard.shard_kind,
                page_start=shard.page_start,
                page_end=shard.page_end,
                route_class=shard.route_class,
                priority=shard.priority,
                status=shard.status,
                attempt_count=len(shard_attempts),
                retry_count=sum(
                    attempt.attempt_kind in {"retry", "hedge", "straggler", "recovery"}
                    for attempt in shard_attempts
                ),
                validator_status=validator_status,
                active_worker_id=active_worker,
            )
        )
    validation_states = Counter(row.status for row in validations)
    final_states = Counter(row.final_state for row in accepted)
    recovery_states = Counter(row.state for row in recoveries)
    arbitration_states = Counter(row.decision for row in arbitrations)
    edge_types = Counter(row.edge_type for row in continuity)
    edge_states = Counter(row.status for row in continuity)
    attempt_views = [
        ParallelAttemptView(
            id=row.id,
            shard_id=row.shard_id,
            attempt_number=row.attempt_number,
            attempt_kind=row.attempt_kind,
            state=row.state,
            pool_key=row.pool_key,
            worker_id=row.worker_id,
            model_id=row.model_id,
            model_revision=row.model_revision,
            runtime_identity=row.runtime_identity,
            billing_disposition=row.billing_disposition,
            gpu_milliseconds=row.gpu_milliseconds,
            cost_usd=row.cost_usd,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )
        for row in attempts
    ]
    active_pages: set[int] = set()
    pages_total = document.page_count or 0
    for shard in shards:
        if shard.status not in {
            "DISPATCHED",
            "RUNNING",
            "VALIDATING",
            "RECOVERY_PENDING",
        }:
            continue
        active_pages.update(
            range(
                max(1, shard.page_start),
                min(pages_total, shard.page_end) + 1,
            )
        )
    unresolved_shards = {
        shard.id for shard in shards if shard.status in {"UNRESOLVED", "RECOVERY_PENDING", "FAILED"}
    }
    unresolved_shards.update(
        task.shard_id for task in recoveries if task.state in {"UNRESOLVED", "FAILED"}
    )
    unresolved_shards.update(
        decision.shard_id
        for decision in arbitrations
        if decision.decision in {"unresolved", "recovery_required"}
    )
    quarantined_shards = {shard.id for shard in shards if shard.status == "QUARANTINED"}
    quarantined_shards.update(
        decision.shard_id for decision in arbitrations if decision.decision == "quarantined"
    )
    ledgers_by_key = {row.operation_key: row for row in ledgers}
    settled_blocks = [
        block
        for block in accepted
        if block.billable
        and block.credit_settlement_key is not None
        and (ledger := ledgers_by_key.get(block.credit_settlement_key)) is not None
        and ledger.entry_type == "consume"
        and ledger.credits == block.credit_amount
    ]
    settlement_mismatch_count = sum(row.billable for row in accepted) - len(settled_blocks)
    return ParallelDocumentSnapshot(
        collection_id=collection.id,
        document_id=document.id,
        processing_job_id=snapshot_scope.processing_job_id,
        document_version_id=snapshot_scope.document_version_id,
        processing_job_status=snapshot_scope.processing_job_status,
        generated_at=utcnow(),
        event_stream_url=(
            f"/v1/collections/{collection.id}/parallel/documents/{document.id}/jobs/"
            f"{snapshot_scope.processing_job_id}/events/stream"
        ),
        shards_total=shards_total,
        attempts_total=attempts_total,
        shards_truncated=shards_total > len(shards),
        attempts_truncated=attempts_total > len(attempts),
        shard_state_counts=dict(sorted(Counter(row.status for row in shards).items())),
        pages_total=pages_total,
        pages_active_parallel=len(active_pages),
        shards=shard_views,
        attempts=attempt_views,
        worker_pools=_worker_pool_views(workers),
        integrity=ParallelIntegrityView(
            final_state_counts=dict(sorted(final_states.items())),
            validation_status_counts=dict(sorted(validation_states.items())),
            recovery_state_counts=dict(sorted(recovery_states.items())),
            arbitration_state_counts=dict(sorted(arbitration_states.items())),
            unresolved_count=len(unresolved_shards),
            quarantined_count=len(quarantined_shards),
            hard_fail_count=sum(row.hard_fail for row in authoritative_validations),
            active_accepted_block_count=len(accepted),
            invalidated_block_count=len(invalidations),
        ),
        continuity=ParallelContinuityView(
            edge_type_counts=dict(sorted(edge_types.items())),
            edge_status_counts=dict(sorted(edge_states.items())),
            accepted_edge_count=edge_states["accepted"],
            unresolved_edge_count=edge_states["unresolved"],
        ),
        usage=ParallelUsageView(
            gpu_milliseconds=sum(row.gpu_milliseconds for row in attempts),
            cost_usd=sum((row.cost_usd for row in attempts), Decimal("0")),
            accepted_billable_attempts=len({row.attempt_id for row in settled_blocks}),
            duplicate_billable_attempts=max(
                0,
                len(settled_blocks) - len({row.credit_settlement_key for row in settled_blocks}),
            ),
            billable_credits=sum((row.credit_amount for row in settled_blocks), Decimal("0")),
            refunded_credits=sum(
                (row.credits for row in refund_ledgers if row.entry_type == "refund"),
                Decimal("0"),
            ),
            settlement_mismatch_count=settlement_mismatch_count,
        ),
    )
