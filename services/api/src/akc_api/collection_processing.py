"""Collection processing settlement bound to durable shared analysis tasks."""

from __future__ import annotations

from decimal import ROUND_UP, Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.collection_integrity_runtime import reconcile_integrity_analysis_task
from akc_api.models import (
    AnalysisTask,
    ArchitecturePlan,
    AuditEvent,
    Collection,
    CollectionFile,
    CollectionProcessingTaskBinding,
    OutboxEvent,
    Page,
    ProcessingJob,
    RouteAttempt,
    utcnow,
)
from akc_api.services import credit_entry

_TERMINAL_TASK_STATES = frozenset({"completed", "failed", "dead_letter"})
_UNBILLABLE_PAGE_STATES = frozenset({"UNRESOLVED", "QUARANTINED", "FAILED"})
_ROUTE_CREDITS = {
    "native": Decimal("0.750000"),
    "paddle_fast": Decimal("1.500000"),
    "paddle_vl": Decimal("2.000000"),
    "mineru": Decimal("2.500000"),
    "mineru_vlm": Decimal("3.000000"),
}


def _money(value: Any) -> Decimal:
    return Decimal(str(value or "0")).quantize(Decimal("0.000001"))


def _actual_page_credits(page: Page) -> Decimal:
    metrics = page.preflight_metrics if isinstance(page.preflight_metrics, dict) else {}
    value = metrics.get("actual_credits", metrics.get("expected_credits"))
    try:
        parsed = (
            Decimal(str(value))
            if value is not None
            else _ROUTE_CREDITS.get(str(page.route or "native"), Decimal("1.000000"))
        )
    except Exception:  # pragma: no cover - legacy JSON corruption safety net
        parsed = Decimal("1.000000")
    return max(Decimal("0.000001"), parsed).quantize(Decimal("0.000001"), rounding=ROUND_UP)


async def _processing_event(
    session: AsyncSession,
    *,
    collection: Collection,
    job: ProcessingJob,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    from akc_api.collection_api import _emit_collection_event

    await _emit_collection_event(
        session,
        collection=collection,
        event_type=event_type,
        payload=payload,
        job_id=job.id,
    )
    session.add(
        OutboxEvent(
            tenant_id=collection.tenant_id,
            aggregate_type="collection_processing",
            aggregate_id=job.id,
            event_type=event_type,
            payload={**payload, "job_id": str(job.id)},
        )
    )


async def _job_bindings(
    session: AsyncSession,
    *,
    job: ProcessingJob,
) -> list[CollectionProcessingTaskBinding]:
    return list(
        await session.scalars(
            select(CollectionProcessingTaskBinding).where(
                CollectionProcessingTaskBinding.tenant_id == job.tenant_id,
                CollectionProcessingTaskBinding.processing_job_id == job.id,
                CollectionProcessingTaskBinding.status != "detached",
            )
        )
    )


async def _defer_unclaimed_tasks(
    session: AsyncSession,
    *,
    job: ProcessingJob,
) -> None:
    """Detach only this collection job; shared analysis tasks remain runnable."""

    bindings = await _job_bindings(session, job=job)
    for binding in bindings:
        if binding.status in {"active", "paused"}:
            binding.status = "detached"
            binding.settled_at = utcnow()


async def _extend_reservation(
    session: AsyncSession,
    *,
    collection: Collection,
    job: ProcessingJob,
    page: Page,
    charge: Decimal,
    total_reserved: Decimal,
    consumed: Decimal,
    released: Decimal,
) -> tuple[Decimal, str | None]:
    available_reserved = total_reserved - consumed - released
    if charge <= available_reserved:
        return total_reserved, None
    incremental = (charge - available_reserved).quantize(Decimal("0.000001"))
    hard_cap = _money(job.cost_estimate.get("hard_cap"))
    if consumed + charge > hard_cap:
        return total_reserved, "CREDIT_HARD_CAP_REACHED"
    try:
        await credit_entry(
            session,
            tenant_id=job.tenant_id,
            operation_key=f"collection:{job.id}:page:{page.id}:incremental-reserve",
            entry_type="reserve",
            credits=incremental,
            job_id=job.id,
            metadata={
                "collection_id": str(collection.id),
                "page_id": str(page.id),
                "reason": "actual_exceeds_reserved_remaining",
                "overage_policy": job.cost_estimate.get("overage_policy"),
                "hard_cap": str(hard_cap),
            },
        )
    except HTTPException as exc:
        if exc.status_code == 402:
            return total_reserved, "INSUFFICIENT_CREDITS_FOR_OVERAGE"
        raise
    total_reserved += incremental
    await _processing_event(
        session,
        collection=collection,
        job=job,
        event_type="credits.reserved.v1",
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(job.id),
            "credits": str(incremental),
            "reason": "incremental_overage_reserve",
        },
    )
    return total_reserved, None


async def _reconcile_binding(
    session: AsyncSession,
    *,
    task: AnalysisTask,
    binding: CollectionProcessingTaskBinding,
) -> None:
    job = await session.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.tenant_id == task.tenant_id,
            ProcessingJob.id == binding.processing_job_id,
            ProcessingJob.job_type == "collection_processing",
        )
        .with_for_update()
    )
    if job is None or job.status in {"completed", "failed", "cancelled"}:
        return
    collection = await session.scalar(
        select(Collection)
        .where(
            Collection.tenant_id == task.tenant_id,
            Collection.id == binding.collection_id,
        )
        .with_for_update()
    )
    collection_file = await session.scalar(
        select(CollectionFile).where(
            CollectionFile.tenant_id == task.tenant_id,
            CollectionFile.collection_id == binding.collection_id,
            CollectionFile.id == binding.collection_file_id,
        )
    )
    if collection is None or collection_file is None:
        raise RuntimeError("collection_processing_scope_missing")

    actual = dict(job.cost_actual or {})
    total_reserved = _money(actual.get("reserved"))
    consumed = _money(actual.get("consumed"))
    refunded = _money(actual.get("refunded"))
    released = _money(actual.get("released"))
    billable_pages = int(actual.get("billable_pages", 0))
    unbillable_pages = int(actual.get("unbillable_pages", 0))
    terminal_result_ids = set(str(item) for item in job.progress.get("terminal_result_ids", []))
    pages = list(
        await session.scalars(
            select(Page)
            .where(
                Page.tenant_id == task.tenant_id,
                Page.document_id == task.document_id,
            )
            .order_by(Page.page_number)
        )
    )
    existing_route_pages = set(
        await session.scalars(
            select(RouteAttempt.page_id).where(
                RouteAttempt.tenant_id == task.tenant_id,
                RouteAttempt.collection_id == binding.collection_id,
                RouteAttempt.collection_file_id == binding.collection_file_id,
            )
        )
    )
    collection_failure: str | None = None
    reuse_unbillable = binding.billing_disposition == "reuse_unbillable"
    reused_pages = 0
    for page in pages:
        if page.id in existing_route_pages:
            terminal_result_ids.add(str(page.id))
            continue
        estimated = _actual_page_credits(page)
        unbillable = reuse_unbillable or page.status in _UNBILLABLE_PAGE_STATES
        charge = Decimal("0") if unbillable else estimated
        if charge > 0:
            total_reserved, collection_failure = await _extend_reservation(
                session,
                collection=collection,
                job=job,
                page=page,
                charge=charge,
                total_reserved=total_reserved,
                consumed=consumed,
                released=released,
            )
            if collection_failure is not None:
                charge = Decimal("0")
                unbillable = True
        route_status = (
            "quarantined"
            if page.status == "QUARANTINED"
            else "unresolved"
            if page.status in {"UNRESOLVED", "FAILED"} or collection_failure
            else "verified"
        )
        session.add(
            RouteAttempt(
                tenant_id=task.tenant_id,
                collection_id=binding.collection_id,
                collection_file_id=binding.collection_file_id,
                page_id=page.id,
                attempt_number=1,
                route=str(page.route or "native"),
                status=route_status,
                reason_codes=(
                    [collection_failure]
                    if collection_failure is not None
                    else ["SHARED_RESULT_REUSE_UNBILLABLE"]
                    if reuse_unbillable
                    else [f"PAGE_TERMINAL_{page.status}"]
                ),
                estimated_credits=estimated,
                actual_credits=charge,
                completed_at=utcnow(),
            )
        )
        if charge > 0:
            await credit_entry(
                session,
                tenant_id=task.tenant_id,
                operation_key=f"collection:{job.id}:page:{page.id}:consume",
                entry_type="consume",
                credits=charge,
                job_id=job.id,
                metadata={
                    "from_reserved": True,
                    "collection_id": str(binding.collection_id),
                    "page_id": str(page.id),
                    "analysis_task_id": str(task.id),
                    "route": str(page.route or "native"),
                },
            )
            consumed += charge
            billable_pages += 1
        else:
            unbillable_pages += 1
            if reuse_unbillable:
                reused_pages += 1
        terminal_result_ids.add(str(page.id))
        if collection_failure is not None:
            break

    binding.status = "settled"
    binding.settled_at = utcnow()
    bindings = await _job_bindings(session, job=job)
    task_ids = {row.analysis_task_id for row in bindings}
    tasks = list(
        await session.scalars(
            select(AnalysisTask).where(
                AnalysisTask.tenant_id == task.tenant_id,
                AnalysisTask.id.in_(task_ids),
            )
        )
    )
    completed_tasks = sum(row.status == "completed" for row in tasks)
    failed_tasks = sum(row.status in {"failed", "dead_letter"} for row in tasks)
    all_terminal = len(tasks) == len(task_ids) and all(
        row.status in _TERMINAL_TASK_STATES for row in tasks
    )
    all_bindings_settled = all(row.status == "settled" for row in bindings)
    job.progress = {
        **job.progress,
        "stage": "failed" if collection_failure else "processing",
        "completed_tasks": completed_tasks,
        "failed_tasks": failed_tasks,
        "terminal_result_ids": sorted(terminal_result_ids),
    }
    job.cost_actual = {
        **actual,
        "reserved": str(total_reserved),
        "consumed": str(consumed),
        "refunded": str(refunded),
        "released": str(released),
        "billable_pages": billable_pages,
        "unbillable_pages": unbillable_pages,
    }
    if reused_pages:
        await _processing_event(
            session,
            collection=collection,
            job=job,
            event_type="processing.result.reused.v1",
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(job.id),
                "analysis_task_id": str(task.id),
                "billing_owner_job_id": (
                    str(binding.billing_owner_job_id)
                    if binding.billing_owner_job_id is not None
                    else None
                ),
                "billing_basis_sha256": binding.billing_basis_sha256,
                "reused_pages": reused_pages,
                "credits": "0.000000",
            },
        )
    if collection_failure is not None:
        job.status = "failed"
        job.error = {"code": collection_failure}
        await _defer_unclaimed_tasks(session, job=job)
    if (not all_terminal or not all_bindings_settled) and collection_failure is None:
        return

    remaining = max(Decimal("0"), total_reserved - consumed - released)
    if remaining > 0:
        await credit_entry(
            session,
            tenant_id=task.tenant_id,
            operation_key=f"collection:{job.id}:release",
            entry_type="release",
            credits=remaining,
            job_id=job.id,
            metadata={
                "collection_id": str(collection.id),
                "reason": "terminal_settlement",
            },
        )
        released += remaining
        await _processing_event(
            session,
            collection=collection,
            job=job,
            event_type="credits.released.v1",
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(job.id),
                "credits": str(remaining),
                "reason": "terminal_settlement",
            },
        )
    job.cost_actual = {**job.cost_actual, "released": str(released)}
    terminal_failure = collection_failure is not None
    job.status = "failed" if terminal_failure else "running"
    job.completed_at = utcnow() if terminal_failure else None
    job.progress = {
        **job.progress,
        "stage": "failed" if terminal_failure else "semantic_compile_queued",
        "partial": failed_tasks > 0 or unbillable_pages > 0,
    }
    if not terminal_failure:
        initiating_user_id = job.requested_options.get("initiating_user_id")
        if initiating_user_id is None:
            initiating_user_id = await session.scalar(
                select(ArchitecturePlan.created_by).where(
                    ArchitecturePlan.tenant_id == job.tenant_id,
                    ArchitecturePlan.collection_id == collection.id,
                    ArchitecturePlan.processing_job_id == job.id,
                )
            )
        if initiating_user_id is None:
            raise RuntimeError("collection_processing_initiating_actor_missing")
        existing_compile_request = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.tenant_id == job.tenant_id,
                OutboxEvent.aggregate_id == job.id,
                OutboxEvent.event_type == "collection.semantic.compile.requested.v1",
            )
        )
        if existing_compile_request is None:
            session.add(
                OutboxEvent(
                    tenant_id=job.tenant_id,
                    aggregate_type="collection_processing",
                    aggregate_id=job.id,
                    event_type="collection.semantic.compile.requested.v1",
                    payload={
                        "tenant_id": str(job.tenant_id),
                        "collection_id": str(collection.id),
                        "processing_job_id": str(job.id),
                        "architecture_plan_id": str(job.requested_options["architecture_plan_id"]),
                        "actor_user_id": str(initiating_user_id),
                        "immutable_plan_sha256": str(
                            job.requested_options["immutable_plan_sha256"]
                        ),
                        "approved_preflight_sha256": str(
                            job.requested_options["approved_preflight_sha256"]
                        ),
                        "approved_estimate_sha256": str(
                            job.requested_options["approved_estimate_sha256"]
                        ),
                    },
                )
            )
    if collection.status == "PAUSED" and collection.paused_from == "PROCESSING":
        collection.status = "PROCESSING"
        collection.paused_from = None
    collection.status = "FAILED_RETRYABLE" if terminal_failure else "VERIFYING_OUTPUT"
    collection.status_reason = (
        collection_failure
        if terminal_failure
        else "PROCESSING_PARTIAL_ISOLATED"
        if failed_tasks > 0 or unbillable_pages > 0
        else "SEMANTIC_COMPILE_QUEUED"
    )
    collection.updated_at = utcnow()
    if consumed > 0:
        await _processing_event(
            session,
            collection=collection,
            job=job,
            event_type="credits.consumed.v1",
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(job.id),
                "credits": str(consumed),
                "billable_pages": billable_pages,
            },
        )
    if terminal_failure:
        await _processing_event(
            session,
            collection=collection,
            job=job,
            event_type="processing.failed.v1",
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(job.id),
                "error_code": collection_failure,
                "completed_tasks": completed_tasks,
                "failed_tasks": failed_tasks,
                "billable_pages": billable_pages,
                "unbillable_pages": unbillable_pages,
                "partial": failed_tasks > 0 or unbillable_pages > 0,
            },
        )
    session.add(
        AuditEvent(
            tenant_id=task.tenant_id,
            actor_id=task.requested_by,
            action=(
                "collection.processing_failed"
                if terminal_failure
                else "collection.processing_extraction_completed"
            ),
            target_type="processing_job",
            target_id=str(job.id),
            metadata_json={
                "collection_id": str(collection.id),
                "consumed": str(consumed),
                "refunded": str(refunded),
                "released": str(released),
                "partial": failed_tasks > 0 or unbillable_pages > 0,
            },
        )
    )


async def reconcile_collection_analysis_task(
    session: AsyncSession,
    *,
    task: AnalysisTask,
) -> None:
    """Settle every collection bound to a shared terminal task exactly once."""

    await reconcile_integrity_analysis_task(session, task=task)
    if task.status not in _TERMINAL_TASK_STATES:
        return
    bindings = list(
        await session.scalars(
            select(CollectionProcessingTaskBinding)
            .where(
                CollectionProcessingTaskBinding.tenant_id == task.tenant_id,
                CollectionProcessingTaskBinding.analysis_task_id == task.id,
                CollectionProcessingTaskBinding.status == "active",
            )
            .order_by(CollectionProcessingTaskBinding.processing_job_id)
        )
    )
    for binding in bindings:
        await _reconcile_binding(session, task=task, binding=binding)


__all__ = ["reconcile_collection_analysis_task"]
