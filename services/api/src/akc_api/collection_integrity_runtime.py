"""Executable, collection-scoped runtime for integrity decisions.

The module accepts only identifiers, hashes, and fixed reason codes.  It never
handles passwords, source text, filenames, object-store credentials, or signed
URLs.  Immutable customer decisions are separated from mutable asynchronous
execution state so retries can be reconciled without rewriting audit history.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal, cast

from akc_cir import PageState, validate_collection_event_payload
from akc_router import Route, RouteProfile
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.feature_flags import cohort_enabled
from akc_api.models import (
    AnalysisTask,
    ArchitecturePlan,
    AssetRegistry,
    AuditEvent,
    Block,
    Collection,
    CollectionEvent,
    CollectionFile,
    CollectionIntegrityActionExecution,
    CollectionIntegrityDecision,
    CollectionPreflight,
    CollectionRegion,
    Document,
    EstimateRun,
    Export,
    FileContentHash,
    FileVersion,
    KnowledgeCompileRun,
    ModelRegistry,
    OutboxEvent,
    PackageManifest,
    PackageValidation,
    Page,
    PageAsset,
    PageAttempt,
    ProcessingJob,
    QuarantineItem,
    ReviewItem,
    SourceFile,
    VerificationRecord,
    utcnow,
)
from akc_api.page_attempts import create_page_attempt, next_attempt_number
from akc_api.routing_runtime import (
    ProviderBinding,
    RoutingRuntime,
    load_routing_runtime,
    validate_registry_binding,
)

ExecutionStatus = Literal["queued", "running", "completed", "failed"]

_INTERNAL_RETRY_ROUTES = frozenset(
    {
        Route.HPD_FAST,
        Route.PADDLE_FAST,
        Route.PADDLE_VL,
        Route.UNLIMITED_LONG,
    }
)
_TERMINAL_TASK_STATES = frozenset({"completed", "failed", "dead_letter"})
_TERMINAL_PAGE_ATTEMPT_STATES = frozenset(
    {"COMPLETED", "NEEDS_REVIEW", "UNRESOLVED", "QUARANTINED", "FAILED"}
)
_SUCCESS_FILE_STATES = frozenset({"verified", "duplicate"})


class IntegrityActionRejected(RuntimeError):
    """A controlled fail-closed rejection suitable for the HTTP boundary."""

    def __init__(self, code: str, *, status_code: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class RetryCandidate:
    registry_model_id: uuid.UUID
    route: Route
    revision: str
    receipt_sha256: str
    receipt: dict[str, Any]

    @property
    def evidence_reference(self) -> dict[str, Any]:
        return {
            "kind": "engine_revision",
            "sha256": self.receipt_sha256,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class IntegrityDecisionProjection:
    receipts: tuple[dict[str, Any], ...]
    excluded_document_ids: frozenset[uuid.UUID]
    excluded_page_ids: frozenset[uuid.UUID]
    excluded_block_ids: frozenset[uuid.UUID]
    excluded_region_ids: frozenset[uuid.UUID]
    excluded_collection_file_ids: frozenset[uuid.UUID]
    overridden_document_ids: frozenset[uuid.UUID]
    overridden_page_ids: frozenset[uuid.UUID]
    overridden_block_ids: frozenset[uuid.UUID]


def registry_receipt(row: ModelRegistry, binding: ProviderBinding) -> tuple[dict[str, Any], str]:
    """Return the exact enabled lifecycle and immutable recipe receipt."""

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "registry_model_id": str(row.id),
        "endpoint": row.endpoint,
        "model_id": row.model_id,
        "route": binding.route.value,
        "revision": binding.model_revision,
        "runtime_image_digest": binding.runtime_image_digest,
        "adapter_version": binding.adapter_version,
        "policy_version": binding.policy_version,
        "lifecycle_state": row.lifecycle_state,
        "generation": row.generation,
        "enabled": row.enabled,
        "benchmark_sha256": row.benchmark_sha256,
        "recipe_sha256": row.recipe_sha256,
    }
    return payload, _sha256(payload)


async def target_scope_for_quarantine(
    session: AsyncSession,
    *,
    collection: Collection,
    target: QuarantineItem,
) -> dict[str, Any]:
    scope: dict[str, Any] = {
        "target_type": "quarantine_item",
        "target_id": str(target.id),
    }
    if target.collection_file_id is not None:
        scope["collection_file_id"] = str(target.collection_file_id)
    if target.page_id is not None:
        scope["page_id"] = str(target.page_id)
    if target.region_id is not None:
        region = await session.scalar(
            select(CollectionRegion).where(
                CollectionRegion.tenant_id == collection.tenant_id,
                CollectionRegion.collection_id == collection.id,
                CollectionRegion.id == target.region_id,
            )
        )
        if region is None:
            raise IntegrityActionRejected("INTEGRITY_TARGET_SCOPE_INVALID")
        scope.update(
            {
                "region_id": str(region.id),
                "collection_file_id": str(region.collection_file_id),
            }
        )
        if region.document_id is not None:
            scope["document_id"] = str(region.document_id)
        if region.page_id is not None:
            scope["page_id"] = str(region.page_id)
        if region.bbox1000 is not None:
            scope["bbox1000"] = list(region.bbox1000)
    if "page_id" in scope:
        page = await session.scalar(
            select(Page).where(
                Page.tenant_id == collection.tenant_id,
                Page.id == uuid.UUID(str(scope["page_id"])),
            )
        )
        if page is None:
            raise IntegrityActionRejected("INTEGRITY_TARGET_SCOPE_INVALID")
        scope["document_id"] = str(page.document_id)
    return scope


def target_scope_for_review(target: ReviewItem) -> dict[str, Any]:
    scope: dict[str, Any] = {
        "target_type": "review_item",
        "target_id": str(target.id),
        "document_id": str(target.document_id),
        "category": target.category,
        "severity": target.severity,
    }
    if target.page_id is not None:
        scope["page_id"] = str(target.page_id)
    if target.block_id is not None:
        scope["block_id"] = str(target.block_id)
    return scope


async def _retry_scope_rows(
    session: AsyncSession,
    *,
    collection: Collection,
    scope: dict[str, Any],
) -> tuple[CollectionFile, Document, Page, PageAsset]:
    try:
        collection_file_id = uuid.UUID(str(scope["collection_file_id"]))
        document_id = uuid.UUID(str(scope["document_id"]))
        page_id = uuid.UUID(str(scope["page_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrityActionRejected("INTEGRITY_RETRY_SCOPE_UNAVAILABLE") from exc
    collection_file = await session.scalar(
        select(CollectionFile).where(
            CollectionFile.tenant_id == collection.tenant_id,
            CollectionFile.collection_id == collection.id,
            CollectionFile.id == collection_file_id,
            CollectionFile.source_file_id.is_not(None),
        )
    )
    document = await session.scalar(
        select(Document).where(
            Document.tenant_id == collection.tenant_id,
            Document.project_id == collection.project_id,
            Document.id == document_id,
            Document.deletion_requested_at.is_(None),
        )
    )
    page = await session.scalar(
        select(Page).where(
            Page.tenant_id == collection.tenant_id,
            Page.id == page_id,
            Page.document_id == document_id,
        )
    )
    page_asset = await session.scalar(
        select(PageAsset)
        .where(
            PageAsset.tenant_id == collection.tenant_id,
            PageAsset.page_id == page_id,
            PageAsset.asset_type == "inference_raster",
        )
        .order_by(PageAsset.created_at.desc(), PageAsset.id.desc())
        .limit(1)
    )
    if (
        collection_file is None
        or document is None
        or page is None
        or page_asset is None
        or document.source_file_id != collection_file.source_file_id
    ):
        raise IntegrityActionRejected("INTEGRITY_RETRY_SCOPE_UNAVAILABLE")
    return collection_file, document, page, page_asset


async def approved_retry_candidates(
    session: AsyncSession,
    *,
    collection: Collection,
    scope: dict[str, Any],
) -> tuple[RetryCandidate, ...]:
    """Return only candidates that can execute now under tenant route policy."""

    _, document, page, _ = await _retry_scope_rows(
        session,
        collection=collection,
        scope=scope,
    )
    active_attempt = await session.scalar(
        select(PageAttempt.id).where(
            PageAttempt.tenant_id == collection.tenant_id,
            PageAttempt.page_id == page.id,
            PageAttempt.status.not_in(_TERMINAL_PAGE_ATTEMPT_STATES),
        )
    )
    if active_attempt is not None:
        return ()
    runtime = await load_routing_runtime(
        session,
        tenant_id=collection.tenant_id,
        project_id=collection.project_id,
        requested_route_profile=RouteProfile.PRECISION.value,
        external_processing_consent=False,
        dominant_language=(document.language_codes[0] if document.language_codes else None),
    )
    current_revisions = set(
        await session.scalars(
            select(Block.engine_revision).where(
                Block.tenant_id == collection.tenant_id,
                Block.page_id == page.id,
                Block.engine_revision.is_not(None),
            )
        )
    )
    rows = list(
        await session.scalars(
            select(ModelRegistry)
            .where(
                ModelRegistry.enabled.is_(True),
                ModelRegistry.lifecycle_state.in_(("champion", "fallback")),
            )
            .order_by(
                ModelRegistry.lifecycle_state.asc(),
                ModelRegistry.generation.desc(),
                ModelRegistry.id.desc(),
            )
        )
    )
    candidates: list[RetryCandidate] = []
    for row in rows:
        try:
            binding = validate_registry_binding(row)
        except ValueError:
            continue
        if (
            binding.route not in _INTERNAL_RETRY_ROUTES
            or binding.route not in runtime.context.ready_routes
            or binding.model_revision in current_revisions
            or not cohort_enabled(
                tenant_id=collection.tenant_id,
                key=f"model:{row.endpoint}:{row.revision}",
                enabled=row.enabled,
                percent=row.canary_percent,
            )
        ):
            continue
        receipt, receipt_sha = registry_receipt(row, binding)
        candidates.append(
            RetryCandidate(
                registry_model_id=row.id,
                route=binding.route,
                revision=binding.model_revision,
                receipt_sha256=receipt_sha,
                receipt=receipt,
            )
        )
    return tuple(candidates[:10])


async def secure_password_tasks(
    session: AsyncSession,
    *,
    collection: Collection,
    target: QuarantineItem,
) -> tuple[AnalysisTask, ...]:
    if target.collection_file_id is None:
        return ()
    collection_file = await session.scalar(
        select(CollectionFile).where(
            CollectionFile.tenant_id == collection.tenant_id,
            CollectionFile.collection_id == collection.id,
            CollectionFile.id == target.collection_file_id,
            CollectionFile.source_file_id.is_not(None),
        )
    )
    if collection_file is None or collection_file.source_file_id is None:
        return ()
    source_file = await session.scalar(
        select(SourceFile).where(
            SourceFile.tenant_id == collection.tenant_id,
            SourceFile.project_id == collection.project_id,
            SourceFile.id == collection_file.source_file_id,
            SourceFile.sha256 == collection_file.sha256,
        )
    )
    if source_file is None:
        return ()
    documents = list(
        await session.scalars(
            select(Document).where(
                Document.tenant_id == collection.tenant_id,
                Document.project_id == collection.project_id,
                Document.source_file_id == collection_file.source_file_id,
                Document.deletion_requested_at.is_(None),
            )
        )
    )
    if not documents:
        return ()
    tasks = list(
        await session.scalars(
            select(AnalysisTask).where(
                AnalysisTask.tenant_id == collection.tenant_id,
                AnalysisTask.project_id == collection.project_id,
                AnalysisTask.document_id.in_(tuple(row.id for row in documents)),
                AnalysisTask.source_file_id == collection_file.source_file_id,
                AnalysisTask.status.in_(("queued", "running", "completed")),
            )
        )
    )
    document_versions = {row.id: row.active_version for row in documents}
    audited: list[AnalysisTask] = []
    for task in tasks:
        if task.document_version != document_versions.get(task.document_id):
            continue
        audit_rows = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == collection.tenant_id,
                    AuditEvent.action == "document.pdf_password_submitted",
                    AuditEvent.target_type == "document",
                    AuditEvent.target_id == str(task.document_id),
                )
            )
        )
        if any(
            isinstance(row.metadata_json, dict)
            and row.metadata_json.get("task_id") == str(task.id)
            and row.metadata_json.get("source_sha256") == source_file.sha256
            for row in audit_rows
        ):
            audited.append(task)
    return tuple(sorted(audited, key=lambda row: (row.created_at, row.id), reverse=True))


async def corrected_source_candidates(
    session: AsyncSession,
    *,
    collection: Collection,
    target: QuarantineItem,
) -> tuple[SourceFile, ...]:
    if target.collection_file_id is None:
        return ()
    collection_file = await session.scalar(
        select(CollectionFile).where(
            CollectionFile.tenant_id == collection.tenant_id,
            CollectionFile.collection_id == collection.id,
            CollectionFile.id == target.collection_file_id,
        )
    )
    if collection_file is None:
        return ()
    rows = list(
        await session.scalars(
            select(SourceFile)
            .where(
                SourceFile.tenant_id == collection.tenant_id,
                SourceFile.project_id == collection.project_id,
                SourceFile.antivirus_status == "clean",
                SourceFile.cdr_status != "rejected",
                SourceFile.id != collection_file.source_file_id,
                SourceFile.sha256 != collection_file.sha256,
            )
            .order_by(SourceFile.created_at.desc(), SourceFile.id.desc())
        )
    )
    document_source_ids = set(
        await session.scalars(
            select(Document.source_file_id).where(
                Document.tenant_id == collection.tenant_id,
                Document.project_id == collection.project_id,
                Document.source_file_id.in_(tuple(row.id for row in rows)),
                Document.deletion_requested_at.is_(None),
            )
        )
    )
    return tuple(row for row in rows if row.id in document_source_ids)[:10]


async def invalidate_collection_derived_state(
    session: AsyncSession,
    *,
    collection: Collection,
) -> dict[str, int]:
    """Fence every collection-derived authority while preserving shared documents."""

    counts: dict[str, int] = {}
    operations = (
        (
            "preflights",
            update(CollectionPreflight)
            .where(
                CollectionPreflight.tenant_id == collection.tenant_id,
                CollectionPreflight.collection_id == collection.id,
                CollectionPreflight.status != "stale",
            )
            .values(status="stale"),
        ),
        (
            "estimates",
            update(EstimateRun)
            .where(
                EstimateRun.tenant_id == collection.tenant_id,
                EstimateRun.collection_id == collection.id,
                EstimateRun.status != "stale",
            )
            .values(status="stale"),
        ),
        (
            "plans",
            update(ArchitecturePlan)
            .where(
                ArchitecturePlan.tenant_id == collection.tenant_id,
                ArchitecturePlan.collection_id == collection.id,
                ArchitecturePlan.status.in_(("planned", "compiled")),
            )
            .values(status="stale"),
        ),
        (
            "knowledge_runs",
            update(KnowledgeCompileRun)
            .where(
                KnowledgeCompileRun.tenant_id == collection.tenant_id,
                KnowledgeCompileRun.collection_id == collection.id,
                KnowledgeCompileRun.status != "invalidated",
            )
            .values(status="invalidated"),
        ),
        (
            "package_validations",
            update(PackageValidation)
            .where(
                PackageValidation.tenant_id == collection.tenant_id,
                PackageValidation.collection_id == collection.id,
                PackageValidation.status != "invalidated",
            )
            .values(status="invalidated"),
        ),
        (
            "assets",
            update(AssetRegistry)
            .where(
                AssetRegistry.tenant_id == collection.tenant_id,
                AssetRegistry.collection_id == collection.id,
                AssetRegistry.qa_status != "invalidated",
            )
            .values(qa_status="invalidated"),
        ),
    )
    for key, statement in operations:
        result = await session.execute(statement)
        counts[key] = int(getattr(result, "rowcount", 0) or 0)
    packages = list(
        await session.scalars(
            select(PackageManifest).where(
                PackageManifest.tenant_id == collection.tenant_id,
                PackageManifest.collection_id == collection.id,
                PackageManifest.status != "invalidated",
            )
        )
    )
    export_ids = tuple(row.export_id for row in packages if row.export_id is not None)
    for package in packages:
        package.status = "invalidated"
    counts["packages"] = len(packages)
    if export_ids:
        result = await session.execute(
            update(Export)
            .where(
                Export.tenant_id == collection.tenant_id,
                Export.id.in_(export_ids),
                Export.status.in_(("running", "completed")),
            )
            .values(status="failed")
        )
        counts["exports"] = int(getattr(result, "rowcount", 0) or 0)
    else:
        counts["exports"] = 0
    return counts


async def replace_collection_source(
    session: AsyncSession,
    *,
    collection: Collection,
    target: QuarantineItem,
    source_file_id: uuid.UUID,
    source_sha256: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    if target.collection_file_id is None:
        raise IntegrityActionRejected("INTEGRITY_SOURCE_TARGET_INVALID")
    collection_file = await session.scalar(
        select(CollectionFile)
        .where(
            CollectionFile.tenant_id == collection.tenant_id,
            CollectionFile.collection_id == collection.id,
            CollectionFile.id == target.collection_file_id,
        )
        .with_for_update()
    )
    source = await session.scalar(
        select(SourceFile).where(
            SourceFile.tenant_id == collection.tenant_id,
            SourceFile.project_id == collection.project_id,
            SourceFile.id == source_file_id,
            SourceFile.sha256 == source_sha256,
            SourceFile.antivirus_status == "clean",
            SourceFile.cdr_status != "rejected",
        )
    )
    matching_document = (
        await session.scalar(
            select(Document.id).where(
                Document.tenant_id == collection.tenant_id,
                Document.project_id == collection.project_id,
                Document.source_file_id == source_file_id,
                Document.deletion_requested_at.is_(None),
            )
        )
        if source is not None
        else None
    )
    if collection_file is None or source is None or matching_document is None:
        raise IntegrityActionRejected("INTEGRITY_CORRECTED_SOURCE_INVALID")
    if collection_file.source_file_id == source.id or collection_file.sha256 == source.sha256:
        raise IntegrityActionRejected("INTEGRITY_CORRECTED_SOURCE_NOT_NEW")
    previous_source_id = collection_file.source_file_id
    previous_sha = collection_file.sha256
    latest_version = int(
        await session.scalar(
            select(func.max(FileVersion.version_number)).where(
                FileVersion.tenant_id == collection.tenant_id,
                FileVersion.collection_id == collection.id,
                FileVersion.collection_file_id == collection_file.id,
            )
        )
        or 0
    )
    await session.execute(
        update(FileVersion)
        .where(
            FileVersion.tenant_id == collection.tenant_id,
            FileVersion.collection_id == collection.id,
            FileVersion.collection_file_id == collection_file.id,
            FileVersion.status == "active",
        )
        .values(status="superseded")
    )
    session.add(
        FileVersion(
            tenant_id=collection.tenant_id,
            collection_id=collection.id,
            collection_file_id=collection_file.id,
            parent_file_id=collection_file.id,
            version_number=latest_version + 1,
            source_sha256=source.sha256,
            status="active",
            evidence={
                "reason_code": "CORRECTED_SOURCE_SUBMITTED",
                "previous_source_sha256": previous_sha,
                "source_file_id": str(source.id),
            },
        )
    )
    collection_file.source_file_id = source.id
    collection_file.sha256 = source.sha256
    collection_file.size_bytes = source.size_bytes
    collection_file.expected_mime = source.mime_type
    collection_file.detected_mime = source.mime_type
    collection_file.status = "verified"
    collection_file.error_code = None
    collection_file.updated_at = utcnow()
    collection.manifest_revision += 1
    await session.execute(
        update(FileContentHash)
        .where(
            FileContentHash.tenant_id == collection.tenant_id,
            FileContentHash.collection_id == collection.id,
            FileContentHash.canonical_file_id == collection_file.id,
            FileContentHash.status != "invalidated",
        )
        .values(status="invalidated")
    )
    await session.execute(
        update(CollectionRegion)
        .where(
            CollectionRegion.tenant_id == collection.tenant_id,
            CollectionRegion.collection_id == collection.id,
            CollectionRegion.collection_file_id == collection_file.id,
            CollectionRegion.status != "rejected",
        )
        .values(status="rejected")
    )
    await session.execute(
        update(VerificationRecord)
        .where(
            VerificationRecord.tenant_id == collection.tenant_id,
            VerificationRecord.collection_id == collection.id,
            VerificationRecord.collection_file_id == collection_file.id,
            VerificationRecord.status != "rejected",
        )
        .values(status="rejected")
    )
    invalidated = await invalidate_collection_derived_state(session, collection=collection)
    return (
        {
            "collection_file_id": str(collection_file.id),
            "previous_source_file_id": (
                str(previous_source_id) if previous_source_id is not None else None
            ),
            "source_file_id": str(source.id),
            "source_sha256": source.sha256,
            "file_version": latest_version + 1,
            "manifest_revision": collection.manifest_revision,
        },
        invalidated,
    )


def _execution_receipt(
    *,
    execution_id: uuid.UUID,
    decision: CollectionIntegrityDecision,
    execution_kind: str,
    target_scope: dict[str, Any],
    binding: dict[str, Any],
) -> str:
    return _sha256(
        {
            "schema_version": "1.0",
            "execution_id": str(execution_id),
            "decision_id": str(decision.id),
            "collection_id": str(decision.collection_id),
            "action": decision.action,
            "execution_kind": execution_kind,
            "target_scope": target_scope,
            "binding": binding,
        }
    )


def synchronous_execution(
    *,
    decision: CollectionIntegrityDecision,
    target_scope: dict[str, Any],
    result_code: str,
    result: dict[str, Any] | None = None,
) -> CollectionIntegrityActionExecution:
    now = utcnow()
    execution_id = uuid.uuid4()
    receipt = _execution_receipt(
        execution_id=execution_id,
        decision=decision,
        execution_kind="synchronous",
        target_scope=target_scope,
        binding={},
    )
    return CollectionIntegrityActionExecution(
        id=execution_id,
        tenant_id=decision.tenant_id,
        collection_id=decision.collection_id,
        decision_id=decision.id,
        execution_kind="synchronous",
        status="completed",
        target_scope=target_scope,
        execution_receipt_sha256=receipt,
        result_code=result_code,
        result=result or {},
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )


async def create_retry_execution(
    session: AsyncSession,
    *,
    collection: Collection,
    decision: CollectionIntegrityDecision,
    target: QuarantineItem,
    evidence_revision: str,
    evidence_sha256: str,
    requested_by: uuid.UUID,
) -> CollectionIntegrityActionExecution:
    scope = await target_scope_for_quarantine(
        session,
        collection=collection,
        target=target,
    )
    collection_file, document, page, _ = await _retry_scope_rows(
        session,
        collection=collection,
        scope=scope,
    )
    candidates = await approved_retry_candidates(
        session,
        collection=collection,
        scope=scope,
    )
    candidate = next(
        (
            item
            for item in candidates
            if item.revision == evidence_revision and item.receipt_sha256 == evidence_sha256
        ),
        None,
    )
    if candidate is None:
        raise IntegrityActionRejected("INTEGRITY_RETRY_REGISTRY_RECEIPT_INVALID")
    execution_id = uuid.uuid4()
    job_id = uuid.uuid4()
    job = ProcessingJob(
        id=job_id,
        tenant_id=collection.tenant_id,
        project_id=collection.project_id,
        document_id=document.id,
        job_type="collection_integrity_retry",
        status="queued",
        priority=4,
        requested_options={
            "document_version": document.active_version,
            "page_ids": [str(page.id)],
            "route_profile": RouteProfile.PRECISION.value,
            "external_processing_consent": False,
            "requested_by": str(requested_by),
            "bounded_retry_only": True,
            "unbillable": True,
            "integrity_action_execution_id": str(execution_id),
            "integrity_registry_receipt": candidate.receipt,
            "integrity_registry_receipt_sha256": candidate.receipt_sha256,
            "integrity_target": scope,
        },
        progress={"stage": "queued", "done": 0, "total": 1},
        cost_estimate={
            "expected": "0.000000",
            "reserved": "0.000000",
            "hard_cap": "0.000000",
            "billing_disposition": "unbillable_integrity_retry",
        },
        cost_actual={"credits": "0.000000"},
    )
    session.add(job)
    await session.flush()
    await session.refresh(page, attribute_names=["id"])
    attempt = await create_page_attempt(
        session,
        tenant_id=collection.tenant_id,
        page_id=page.id,
        attempt_number=await next_attempt_number(
            session,
            tenant_id=collection.tenant_id,
            page_id=page.id,
        ),
        trigger="user_retry",
        initial_state=PageState.PREFLIGHTED,
        route=candidate.route.value,
        route_profile=RouteProfile.PRECISION.value,
        route_policy_version=str(candidate.receipt["policy_version"]),
        max_attempts=1,
        job_id=job.id,
        reason="integrity_retry_pinned",
        payload={
            "collection_id": str(collection.id),
            "collection_file_id": str(collection_file.id),
            "registry_receipt_sha256": candidate.receipt_sha256,
        },
    )
    binding = {
        "processing_job_id": str(job.id),
        "page_attempt_id": str(attempt.id),
        "registry_model_id": str(candidate.registry_model_id),
        "registry_receipt_sha256": candidate.receipt_sha256,
    }
    execution = CollectionIntegrityActionExecution(
        id=execution_id,
        tenant_id=collection.tenant_id,
        collection_id=collection.id,
        decision_id=decision.id,
        execution_kind="compile_retry",
        status="queued",
        processing_job_id=job.id,
        registry_model_id=candidate.registry_model_id,
        target_scope=scope,
        execution_receipt_sha256=_execution_receipt(
            execution_id=execution_id,
            decision=decision,
            execution_kind="compile_retry",
            target_scope=scope,
            binding=binding,
        ),
        result={
            "page_attempt_id": str(attempt.id),
            "registry_receipt_sha256": candidate.receipt_sha256,
        },
    )
    session.add(execution)
    session.add(
        OutboxEvent(
            tenant_id=collection.tenant_id,
            aggregate_type="job",
            aggregate_id=job.id,
            event_type="job.dispatch.requested.v1",
            payload={
                "job_id": str(job.id),
                "tenant_id": str(collection.tenant_id),
                "document_version": document.active_version,
                "document_version_id": f"{document.id}:v{document.active_version}",
                "idempotency_key": f"integrity-retry-{execution.id}",
                "integrity_action_execution_id": str(execution.id),
            },
        )
    )
    target.status = "retrying"
    target.retry_after_revision = candidate.revision
    target.resolved_at = None
    collection.status = "PROCESSING"
    collection.paused_from = None
    collection.status_reason = "INTEGRITY_RETRY_QUEUED"
    collection.updated_at = utcnow()
    return execution


async def create_password_execution(
    session: AsyncSession,
    *,
    collection: Collection,
    decision: CollectionIntegrityDecision,
    target: QuarantineItem,
    analysis_task_id: uuid.UUID,
) -> CollectionIntegrityActionExecution:
    scope = await target_scope_for_quarantine(
        session,
        collection=collection,
        target=target,
    )
    tasks = await secure_password_tasks(
        session,
        collection=collection,
        target=target,
    )
    task = next((item for item in tasks if item.id == analysis_task_id), None)
    if task is None:
        raise IntegrityActionRejected("INTEGRITY_PASSWORD_TASK_BINDING_INVALID")
    # A terminal task is linked as queued and reconciled through the same
    # completion path as a freshly-running secure analysis.  This prevents a
    # pre-completed task from bypassing collection/file reconciliation.
    status: ExecutionStatus = "running" if task.status == "running" else "queued"
    now = utcnow()
    execution_id = uuid.uuid4()
    binding = {
        "analysis_task_id": str(task.id),
        "document_id": str(task.document_id),
        "document_version": task.document_version,
        "source_file_id": str(task.source_file_id),
    }
    execution = CollectionIntegrityActionExecution(
        id=execution_id,
        tenant_id=collection.tenant_id,
        collection_id=collection.id,
        decision_id=decision.id,
        execution_kind="password_analysis",
        status=status,
        analysis_task_id=task.id,
        target_scope=scope,
        execution_receipt_sha256=_execution_receipt(
            execution_id=execution_id,
            decision=decision,
            execution_kind="password_analysis",
            target_scope=scope,
            binding=binding,
        ),
        result={"analysis_task_id": str(task.id)},
        started_at=task.started_at if status == "running" else None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )
    session.add(execution)
    target.status = "retrying"
    target.resolved_at = None
    collection.status = "PROCESSING"
    collection.paused_from = None
    collection.status_reason = "INTEGRITY_PASSWORD_ANALYSIS_LINKED"
    collection.updated_at = now
    return execution


async def _emit_execution_state_event(
    session: AsyncSession,
    *,
    collection: Collection,
    decision: CollectionIntegrityDecision,
    execution: CollectionIntegrityActionExecution,
) -> None:
    event_type = "integrity.action.state_changed.v1"
    payload: dict[str, Any] = {
        "collection_id": str(collection.id),
        "decision_id": str(decision.id),
        "execution_id": str(execution.id),
        "target_type": str(execution.target_scope["target_type"]),
        "target_id": str(execution.target_scope["target_id"]),
        "action": decision.action,
        "status": execution.status,
        "execution_receipt_sha256": execution.execution_receipt_sha256,
    }
    if execution.processing_job_id is not None:
        payload["processing_job_id"] = str(execution.processing_job_id)
    if execution.analysis_task_id is not None:
        payload["analysis_task_id"] = str(execution.analysis_task_id)
    if execution.registry_model_id is not None:
        payload["registry_model_id"] = str(execution.registry_model_id)
    if execution.result_code is not None:
        payload["result_code"] = execution.result_code
    safe = validate_collection_event_payload(
        event_type,
        payload,
        collection_id=collection.id,
        job_id=execution.processing_job_id,
    )
    collection.event_sequence += 1
    session.add(
        CollectionEvent(
            tenant_id=collection.tenant_id,
            collection_id=collection.id,
            job_id=execution.processing_job_id,
            sequence=collection.event_sequence,
            event_type=event_type,
            schema_version="1.0",
            payload=safe,
        )
    )


async def emit_execution_state_event(
    session: AsyncSession,
    *,
    collection: Collection,
    decision: CollectionIntegrityDecision,
    execution: CollectionIntegrityActionExecution,
) -> None:
    await _emit_execution_state_event(
        session,
        collection=collection,
        decision=decision,
        execution=execution,
    )


async def resolve_pinned_retry_binding(
    session: AsyncSession,
    *,
    job: ProcessingJob,
    runtime: RoutingRuntime,
    route: Route,
) -> ProviderBinding:
    """Revalidate the exact registry receipt immediately before GPU enqueue."""

    if job.job_type != "collection_integrity_retry":
        binding = runtime.provider_for(route)
        if binding is None:
            raise IntegrityActionRejected("VISUAL_PROVIDER_NOT_READY")
        return binding
    receipt = job.requested_options.get("integrity_registry_receipt")
    receipt_sha = job.requested_options.get("integrity_registry_receipt_sha256")
    if not isinstance(receipt, dict) or not isinstance(receipt_sha, str):
        raise IntegrityActionRejected("INTEGRITY_RETRY_PIN_MISSING")
    try:
        model_id = uuid.UUID(str(receipt["registry_model_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrityActionRejected("INTEGRITY_RETRY_PIN_INVALID") from exc
    row = await session.scalar(
        select(ModelRegistry)
        .where(
            ModelRegistry.id == model_id,
            ModelRegistry.enabled.is_(True),
            ModelRegistry.lifecycle_state.in_(("champion", "fallback")),
        )
        .with_for_update()
    )
    if row is None:
        raise IntegrityActionRejected("INTEGRITY_RETRY_REGISTRY_DRIFT")
    try:
        binding = validate_registry_binding(row)
    except ValueError as exc:
        raise IntegrityActionRejected("INTEGRITY_RETRY_REGISTRY_DRIFT") from exc
    current_receipt, current_sha = registry_receipt(row, binding)
    if (
        current_sha != receipt_sha
        or current_receipt != receipt
        or binding.route != route
        or binding.route not in _INTERNAL_RETRY_ROUTES
        or binding.route not in runtime.context.ready_routes
        or not cohort_enabled(
            tenant_id=job.tenant_id,
            key=f"model:{row.endpoint}:{row.revision}",
            enabled=row.enabled,
            percent=row.canary_percent,
        )
    ):
        raise IntegrityActionRejected("INTEGRITY_RETRY_REGISTRY_DRIFT")
    execution = await session.scalar(
        select(CollectionIntegrityActionExecution).where(
            CollectionIntegrityActionExecution.tenant_id == job.tenant_id,
            CollectionIntegrityActionExecution.processing_job_id == job.id,
            CollectionIntegrityActionExecution.registry_model_id == row.id,
            CollectionIntegrityActionExecution.status.in_(("queued", "running")),
        )
    )
    attempts = list(
        await session.scalars(
            select(PageAttempt).where(
                PageAttempt.tenant_id == job.tenant_id,
                PageAttempt.job_id == job.id,
            )
        )
    )
    expected_pages = job.requested_options.get("page_ids")
    attempt_shape_valid = (
        len(attempts) == 1
        and expected_pages == [str(attempts[0].page_id)]
        and attempts[0].route == route.value
        and attempts[0].route_policy_version == binding.policy_version
        and attempts[0].max_attempts == 1
    )
    if (
        execution is None
        or execution.execution_kind != "compile_retry"
        or job.cost_estimate.get("reserved") != "0.000000"
        or job.cost_estimate.get("hard_cap") != "0.000000"
        or job.requested_options.get("bounded_retry_only") is not True
        or not attempt_shape_valid
    ):
        raise IntegrityActionRejected("INTEGRITY_RETRY_EXECUTION_FENCE_INVALID")
    return binding


def integrity_region_bbox(job: ProcessingJob) -> list[int] | None:
    if job.job_type != "collection_integrity_retry":
        return None
    target = job.requested_options.get("integrity_target")
    if not isinstance(target, dict):
        return None
    bbox = target.get("bbox1000")
    if (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(item, int) and not isinstance(item, bool) for item in bbox)
        and 0 <= bbox[0] < bbox[2] <= 1000
        and 0 <= bbox[1] < bbox[3] <= 1000
    ):
        return cast(list[int], bbox)
    return None


def _scope_uuid(scope: dict[str, Any], key: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(scope[key])) if key in scope else None
    except (TypeError, ValueError):
        return None


async def reconcile_integrity_retry_job(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> None:
    job = await session.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.job_type == "collection_integrity_retry",
        )
        .with_for_update()
    )
    if job is None:
        return
    execution = await session.scalar(
        select(CollectionIntegrityActionExecution)
        .where(
            CollectionIntegrityActionExecution.tenant_id == job.tenant_id,
            CollectionIntegrityActionExecution.processing_job_id == job.id,
        )
        .with_for_update()
    )
    if execution is None:
        raise RuntimeError("integrity_retry_execution_missing")
    decision = await session.scalar(
        select(CollectionIntegrityDecision).where(
            CollectionIntegrityDecision.tenant_id == execution.tenant_id,
            CollectionIntegrityDecision.id == execution.decision_id,
        )
    )
    collection = await session.scalar(
        select(Collection)
        .where(
            Collection.tenant_id == execution.tenant_id,
            Collection.id == execution.collection_id,
        )
        .with_for_update()
    )
    target = await session.scalar(
        select(QuarantineItem)
        .where(
            QuarantineItem.tenant_id == execution.tenant_id,
            QuarantineItem.collection_id == execution.collection_id,
            QuarantineItem.id == _scope_uuid(execution.target_scope, "target_id"),
        )
        .with_for_update()
    )
    if decision is None or collection is None or target is None:
        raise RuntimeError("integrity_retry_reconciliation_scope_missing")
    desired: ExecutionStatus = (
        "queued"
        if job.status == "queued"
        else "running"
        if job.status in {"running", "paused", "waiting_review"}
        else "completed"
        if job.status == "completed"
        else "failed"
    )
    if execution.status == desired:
        return
    now = utcnow()
    execution.status = desired
    execution.updated_at = now
    if desired == "running":
        execution.started_at = execution.started_at or job.started_at or now
        execution.result_code = "INTEGRITY_RETRY_RUNNING"
    elif desired == "completed":
        execution.started_at = execution.started_at or job.started_at or now
        execution.completed_at = job.completed_at or now
        execution.result_code = "INTEGRITY_RETRY_COMPLETED"
        execution.result = {
            **execution.result,
            "processing_job_id": str(job.id),
            "credits": "0.000000",
        }
        target.status = "resolved"
        target.resolved_at = now
        region_id = _scope_uuid(execution.target_scope, "region_id")
        if region_id is not None:
            region = await session.scalar(
                select(CollectionRegion).where(
                    CollectionRegion.tenant_id == collection.tenant_id,
                    CollectionRegion.collection_id == collection.id,
                    CollectionRegion.id == region_id,
                )
            )
            if region is not None:
                region.status = "verified"
        invalidated = await invalidate_collection_derived_state(session, collection=collection)
        execution.result = {**execution.result, "invalidated": invalidated}
        collection.status = "PARTIAL"
        collection.paused_from = None
        collection.status_reason = "INTEGRITY_RETRY_COMPLETED_RECOMPILE_REQUIRED"
    else:
        execution.started_at = execution.started_at or job.started_at or now
        execution.completed_at = job.completed_at or now
        error_code = (
            str(job.error.get("code"))
            if isinstance(job.error, dict) and isinstance(job.error.get("code"), str)
            else "INTEGRITY_RETRY_FAILED"
        )
        execution.result_code = error_code[:120]
        execution.result = {**execution.result, "processing_job_id": str(job.id)}
        target.status = "open"
        target.resolved_at = None
        collection.status = "QUARANTINED"
        collection.paused_from = None
        collection.status_reason = "INTEGRITY_RETRY_FAILED"
    collection.updated_at = now
    await _emit_execution_state_event(
        session,
        collection=collection,
        decision=decision,
        execution=execution,
    )
    session.add(
        AuditEvent(
            tenant_id=collection.tenant_id,
            actor_id=decision.actor_id,
            action="collection.integrity.action.reconciled",
            target_type="integrity_action_execution",
            target_id=str(execution.id),
            metadata_json={
                "collection_id": str(collection.id),
                "decision_id": str(decision.id),
                "action": decision.action,
                "status": execution.status,
                "result_code": execution.result_code,
            },
        )
    )
    await session.commit()


async def reconcile_integrity_analysis_task(
    session: AsyncSession,
    *,
    task: AnalysisTask,
) -> None:
    executions = list(
        await session.scalars(
            select(CollectionIntegrityActionExecution)
            .where(
                CollectionIntegrityActionExecution.tenant_id == task.tenant_id,
                CollectionIntegrityActionExecution.analysis_task_id == task.id,
                CollectionIntegrityActionExecution.execution_kind == "password_analysis",
                CollectionIntegrityActionExecution.status.in_(("queued", "running")),
            )
            .with_for_update()
        )
    )
    for execution in executions:
        decision = await session.scalar(
            select(CollectionIntegrityDecision).where(
                CollectionIntegrityDecision.tenant_id == execution.tenant_id,
                CollectionIntegrityDecision.id == execution.decision_id,
            )
        )
        collection = await session.scalar(
            select(Collection)
            .where(
                Collection.tenant_id == execution.tenant_id,
                Collection.id == execution.collection_id,
            )
            .with_for_update()
        )
        target = await session.scalar(
            select(QuarantineItem)
            .where(
                QuarantineItem.tenant_id == execution.tenant_id,
                QuarantineItem.collection_id == execution.collection_id,
                QuarantineItem.id == _scope_uuid(execution.target_scope, "target_id"),
            )
            .with_for_update()
        )
        if decision is None or collection is None or target is None:
            raise RuntimeError("integrity_password_reconciliation_scope_missing")
        now = utcnow()
        desired: ExecutionStatus = (
            "completed"
            if task.status == "completed"
            else "failed"
            if task.status in {"failed", "dead_letter"}
            else "running"
            if task.status == "running"
            else "queued"
        )
        if execution.status == desired:
            continue
        execution.status = desired
        execution.updated_at = now
        if desired == "running":
            execution.started_at = execution.started_at or task.started_at or now
            execution.result_code = "INTEGRITY_PASSWORD_ANALYSIS_RUNNING"
        elif desired == "completed":
            execution.started_at = execution.started_at or task.started_at or now
            execution.completed_at = task.completed_at or now
            execution.result_code = "INTEGRITY_PASSWORD_ANALYSIS_COMPLETED"
            target.status = "resolved"
            target.resolved_at = now
            collection_file_id = _scope_uuid(execution.target_scope, "collection_file_id")
            if collection_file_id is not None:
                collection_file = await session.scalar(
                    select(CollectionFile).where(
                        CollectionFile.tenant_id == collection.tenant_id,
                        CollectionFile.collection_id == collection.id,
                        CollectionFile.id == collection_file_id,
                        CollectionFile.source_file_id == task.source_file_id,
                    )
                )
                if collection_file is None:
                    raise RuntimeError("integrity_password_collection_file_drift")
                collection_file.status = "verified"
                collection_file.error_code = None
            invalidated = await invalidate_collection_derived_state(
                session,
                collection=collection,
            )
            execution.result = {
                **execution.result,
                "page_count": task.page_count,
                "block_count": task.block_count,
                "invalidated": invalidated,
            }
            collection.status = "PARTIAL"
            collection.paused_from = None
            collection.status_reason = "PASSWORD_ANALYSIS_COMPLETED_RECOMPILE_REQUIRED"
        elif desired == "failed":
            execution.started_at = execution.started_at or task.started_at or now
            execution.completed_at = task.completed_at or now
            execution.result_code = task.last_error_code or "INTEGRITY_PASSWORD_ANALYSIS_FAILED"
            target.status = "open"
            target.resolved_at = None
            collection.status = "QUARANTINED"
            collection.paused_from = None
            collection.status_reason = "PASSWORD_ANALYSIS_FAILED"
        collection.updated_at = now
        await _emit_execution_state_event(
            session,
            collection=collection,
            decision=decision,
            execution=execution,
        )
        session.add(
            AuditEvent(
                tenant_id=collection.tenant_id,
                actor_id=decision.actor_id,
                action="collection.integrity.action.reconciled",
                target_type="integrity_action_execution",
                target_id=str(execution.id),
                metadata_json={
                    "collection_id": str(collection.id),
                    "decision_id": str(decision.id),
                    "action": decision.action,
                    "status": execution.status,
                    "result_code": execution.result_code,
                },
            )
        )


async def load_integrity_decision_projection(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
) -> IntegrityDecisionProjection:
    rows = list(
        (
            await session.execute(
                select(CollectionIntegrityDecision, CollectionIntegrityActionExecution)
                .join(
                    CollectionIntegrityActionExecution,
                    (
                        CollectionIntegrityActionExecution.tenant_id
                        == CollectionIntegrityDecision.tenant_id
                    )
                    & (
                        CollectionIntegrityActionExecution.decision_id
                        == CollectionIntegrityDecision.id
                    ),
                )
                .where(
                    CollectionIntegrityDecision.tenant_id == tenant_id,
                    CollectionIntegrityDecision.collection_id == collection_id,
                    CollectionIntegrityActionExecution.status == "completed",
                )
                .order_by(
                    CollectionIntegrityDecision.created_at,
                    CollectionIntegrityDecision.id,
                )
            )
        ).all()
    )
    excluded: dict[str, set[uuid.UUID]] = {
        "document_id": set(),
        "page_id": set(),
        "block_id": set(),
        "region_id": set(),
        "collection_file_id": set(),
    }
    overridden: dict[str, set[uuid.UUID]] = {
        "document_id": set(),
        "page_id": set(),
        "block_id": set(),
    }
    receipts: list[dict[str, Any]] = []
    for decision, execution in rows:
        receipts.append(
            {
                "decision_id": str(decision.id),
                "execution_id": str(execution.id),
                "target_type": str(execution.target_scope["target_type"]),
                "target_id": str(execution.target_scope["target_id"]),
                "action": decision.action,
                "reason_code": decision.reason_code,
                "execution_receipt_sha256": execution.execution_receipt_sha256,
                "result_code": execution.result_code,
            }
        )
        target = (
            excluded
            if decision.action in {"exclude", "keep_quarantined"}
            else overridden
            if decision.action == "override"
            else None
        )
        if target is None:
            continue
        # Context IDs in the receipt prove ancestry; only the most granular
        # customer target is authoritative for exclusion/override scope.
        key_order = (
            ("region_id", "block_id", "page_id", "document_id", "collection_file_id")
            if target is excluded
            else ("block_id", "page_id", "document_id")
        )
        for key in key_order:
            if key not in target:
                continue
            value = _scope_uuid(execution.target_scope, key)
            if value is not None:
                target[key].add(value)
                break
    return IntegrityDecisionProjection(
        receipts=tuple(receipts),
        excluded_document_ids=frozenset(excluded["document_id"]),
        excluded_page_ids=frozenset(excluded["page_id"]),
        excluded_block_ids=frozenset(excluded["block_id"]),
        excluded_region_ids=frozenset(excluded["region_id"]),
        excluded_collection_file_ids=frozenset(excluded["collection_file_id"]),
        overridden_document_ids=frozenset(overridden["document_id"]),
        overridden_page_ids=frozenset(overridden["page_id"]),
        overridden_block_ids=frozenset(overridden["block_id"]),
    )


__all__ = [
    "IntegrityActionRejected",
    "IntegrityDecisionProjection",
    "RetryCandidate",
    "approved_retry_candidates",
    "corrected_source_candidates",
    "create_password_execution",
    "create_retry_execution",
    "emit_execution_state_event",
    "integrity_region_bbox",
    "invalidate_collection_derived_state",
    "load_integrity_decision_projection",
    "reconcile_integrity_analysis_task",
    "reconcile_integrity_retry_job",
    "registry_receipt",
    "replace_collection_source",
    "resolve_pinned_retry_binding",
    "secure_password_tasks",
    "synchronous_execution",
    "target_scope_for_quarantine",
    "target_scope_for_review",
]
