"""Tenant-safe v4 Collection ingestion and repository-local completion API.

This module deliberately does not accept bytes, trust client upload receipts,
invoke an external parser, or claim a full deployable knowledge package. It
binds collection manifests only to source rows already verified by the legacy
upload path and exposes an explicit metadata-only export until the full package
pipeline is connected.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import inspect
import io
import json
import re
import secrets
import unicodedata
import uuid
import zipfile
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import timedelta
from decimal import ROUND_UP, Decimal
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, cast

from akc_cir import (
    COLLECTION_EVENT_TYPES,
    validate_collection_event_payload,
)
from akc_domain_packs import builtin_blueprint_modules
from akc_exporters import (
    build_knowledge_package,
    canonical_knowledge_model_bytes,
    deterministic_zip,
    import_knowledge_package,
)
from akc_retrieval import (
    PostgresHybridIndexer,
    ProviderAttestationError,
    RetrievalIndexBatch,
    RetrievalUnavailable,
)
from akc_router import (
    CollectionEstimate,
    CollectionEstimateInput,
    DimensionUnit,
    GpuClass,
    GpuThermalState,
    PreflightObservation,
    Route,
    RoutePopulation,
    StaticDocumentFeatures,
    build_cluster_identity,
    build_zero_authority_learned_router_shadow,
    estimate_collection,
    select_adaptive_samples,
)
from akc_security import ALLOWED_EXTENSIONS, PLAN_LIMITS, PlanTier, safe_relative_path
from akc_telemetry import (
    observe_collection_estimate_calibration,
    observe_collection_export,
    observe_collection_retry_ratio,
    record_collection_credits_refunded,
    record_collection_knowledge_tokens,
)
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from akc_api.collection_integrity_runtime import load_integrity_decision_projection
from akc_api.collection_metadata import (
    CollectionMetadataCodec,
    CollectionMetadataIntegrityError,
    normalize_collection_relative_path,
)
from akc_api.collection_probe import (
    CollectionProbeReceipt,
    CollectionProbeRequest,
    source_page_input_sha256,
)
from akc_api.collection_probe import (
    canonical_json as probe_canonical_json,
)
from akc_api.collection_schemas import (
    ArchitecturePlanResponse,
    BlueprintModuleResponse,
    ClusterResponse,
    CollectionCompileRequest,
    CollectionCreate,
    CollectionDeleteResponse,
    CollectionEstimateResponse,
    CollectionEventResponse,
    CollectionEventSnapshot,
    CollectionEventsResponse,
    CollectionExportRequest,
    CollectionExportResponse,
    CollectionFileResponse,
    CollectionFilesPlan,
    CollectionFilesPlanResponse,
    CollectionFinalizerRequest,
    CollectionIntegrityResponse,
    CollectionKnowledgeResponse,
    CollectionPreflightResponse,
    CollectionProcessingControlRequest,
    CollectionProcessingResponse,
    CollectionProcessingRetryRequest,
    CollectionResponse,
    CollectionSceneResponse,
    CollectionUploadComplete,
    CollectionUploadCompleteResponse,
    CollectionUploadControlRequest,
    CollectionUploadControlResponse,
    CollectionUploadStatusResponse,
    CollectionUploadSummary,
    EntityProjection,
    KnowledgeNoteProjection,
    LocalSourceCreate,
    PackageFileResponse,
    RelationProjection,
    SceneClusterProjection,
    SceneIntegrityProjection,
    SceneKnowledgeProjection,
    ScenePageProjection,
    SourceRootResponse,
)
from akc_api.collection_semantic_runtime import (
    load_collection_semantic_compile_input,
    prepare_collection_semantic_runtime,
    run_collection_semantic_runtime,
    semantic_blueprint_registry_sha256,
)
from akc_api.database import get_session, set_rls_context
from akc_api.idempotency import idempotent_mutation
from akc_api.models import (
    AnalysisTask,
    ArchitecturePlan,
    AssetRegistry,
    AuthorityMapping,
    Block,
    BlueprintModule,
    Collection,
    CollectionEvent,
    CollectionFile,
    CollectionPreflight,
    CollectionProcessingTaskBinding,
    CollectionRegion,
    CollectionRegionAttempt,
    CollectionSourceRoot,
    CollectionUploadSession,
    CostPredictionModel,
    Document,
    DocumentCluster,
    DocumentVersion,
    Entity,
    EstimateRun,
    EstimateSample,
    Export,
    FileContentHash,
    FileVersion,
    GpuProviderInvocation,
    JobEvent,
    KnowledgeCompileRun,
    KnowledgeNote,
    Membership,
    OutboxEvent,
    PackageFile,
    PackageManifest,
    PackageValidation,
    Page,
    PageAsset,
    PageAttempt,
    PageFingerprint,
    PreflightFeatureRecord,
    ProcessingJob,
    Project,
    QuarantineItem,
    Relation,
    ReviewItem,
    RouteAttempt,
    SourceFile,
    Tenant,
    UploadFileSession,
    User,
    VerificationRecord,
    utcnow,
)
from akc_api.project_access import project_access_predicate
from akc_api.security import Principal, get_principal, require_roles
from akc_api.services import audit, credit_entry, estimate_document

router = APIRouter(prefix="/v1", tags=["collections"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
EditorDep = Annotated[Principal, Depends(require_roles("owner", "admin", "editor"))]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]

_SUCCESS_FILE_STATES = frozenset({"verified", "duplicate"})
_ACTIVE_FILE_STATES = frozenset({"planned", "uploading", "duplicate_pending", "uploaded"})
_FAILED_FILE_STATES = frozenset(
    {
        "password_required",
        "unsupported",
        "corrupted",
        "failed",
        "unresolved",
        "quarantined",
        "rejected",
    }
)
_TERMINAL_FILE_STATES = _SUCCESS_FILE_STATES | _FAILED_FILE_STATES | {"purged"}

_DEFAULT_BLUEPRINTS = (
    "source_index",
    "document_catalog",
    "knowledge_notes",
    "entities",
    "relations",
    "integrity",
    "export_manifest",
)

_EVENT_TYPES = frozenset(COLLECTION_EVENT_TYPES)

_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"DISCOVERING", "CANCEL_REQUESTED"}),
    "DISCOVERING": frozenset({"HASHING", "CANCEL_REQUESTED"}),
    "HASHING": frozenset({"UPLOADING", "PARTIAL", "UNRESOLVED", "CANCEL_REQUESTED"}),
    "UPLOADING": frozenset({"VERIFYING", "PAUSED", "PARTIAL", "UNRESOLVED", "CANCEL_REQUESTED"}),
    "VERIFYING": frozenset({"SECURITY_SCAN", "PARTIAL", "UNRESOLVED", "QUARANTINED"}),
    "SECURITY_SCAN": frozenset({"DEDUPLICATING", "UNRESOLVED", "QUARANTINED"}),
    "DEDUPLICATING": frozenset({"INGESTED", "PARTIAL", "UNRESOLVED", "QUARANTINED"}),
    "INGESTED": frozenset({"PREFLIGHTING", "CANCEL_REQUESTED"}),
    "PARTIAL": frozenset({"PREFLIGHTING", "PACKAGING", "CANCEL_REQUESTED"}),
    "UNRESOLVED": frozenset({"CANCEL_REQUESTED"}),
    "PREFLIGHTING": frozenset({"ESTIMATED", "PARTIAL", "FAILED_RETRYABLE"}),
    "ESTIMATED": frozenset({"AWAITING_APPROVAL", "PROCESSING", "CANCEL_REQUESTED"}),
    "AWAITING_APPROVAL": frozenset({"PROCESSING", "CANCEL_REQUESTED"}),
    "PROCESSING": frozenset({"VERIFYING_OUTPUT", "PAUSED", "FAILED_RETRYABLE", "UNRESOLVED"}),
    "VERIFYING_OUTPUT": frozenset(
        {"KNOWLEDGE_COMPILING", "UNRESOLVED", "QUARANTINED", "CANCEL_REQUESTED"}
    ),
    "KNOWLEDGE_COMPILING": frozenset({"PACKAGING", "PARTIAL", "CANCEL_REQUESTED"}),
    "PACKAGING": frozenset({"COMPLETED", "PARTIAL", "FAILED_RETRYABLE", "CANCEL_REQUESTED"}),
    "COMPLETED": frozenset({"CANCEL_REQUESTED"}),
    "FAILED_RETRYABLE": frozenset({"PREFLIGHTING", "PROCESSING", "PACKAGING"}),
    "QUARANTINED": frozenset({"CANCEL_REQUESTED"}),
    "PAUSED": frozenset({"UPLOADING", "PROCESSING", "CANCEL_REQUESTED"}),
    "CANCEL_REQUESTED": frozenset({"CANCELED", "PURGED"}),
    "CANCELED": frozenset({"PURGED"}),
    "PURGED": frozenset(),
}


def _source_antivirus_verified(source: SourceFile, request: Request) -> bool:
    """Accept the explicit test/development bypass only where it can be emitted."""

    if source.antivirus_status == "clean":
        return True
    settings = request.app.state.settings
    return bool(
        source.antivirus_status == "development_static_only"
        and settings.env in {"development", "test"}
        and settings.allow_development_antivirus_bypass
    )


def _canonical_json(value: Any) -> bytes:
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


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _billing_advisory_key(
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    billing_basis_sha256: str,
) -> int:
    digest = hashlib.sha256(
        b"akc-collection-billing-owner-v1\0"
        + tenant_id.bytes
        + task_id.bytes
        + billing_basis_sha256.encode("ascii")
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def _lock_billing_owner_claim(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    billing_basis_sha256: str,
) -> None:
    """Serialize the production owner decision; the partial unique is the backstop."""

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:claim_key)"),
            {
                "claim_key": _billing_advisory_key(
                    tenant_id,
                    task_id,
                    billing_basis_sha256,
                )
            },
        )


def _money(value: Any) -> Decimal:
    return Decimal(str(value or "0")).quantize(Decimal("0.000001"))


def _knowledge_blueprint_receipt(profile: dict[str, Any]) -> dict[str, Any]:
    modules = sorted(builtin_blueprint_modules(), key=lambda module: module.blueprint.id)
    registry = {module.blueprint.id: module.module_sha256 for module in modules}
    export_profiles = {
        module.blueprint.id: list(module.blueprint.export_profiles) for module in modules
    }
    requested = profile.get("knowledge_blueprint_id")
    selected = requested if isinstance(requested, str) and requested in registry else None
    rationale = ["COLLECTION_PROFILE_EXACT_MATCH"] if selected else []
    if selected is None:
        selected = "generic-mixed-corpus"
        rationale.append("SAFE_GENERIC_MIXED_CORPUS_DEFAULT")
    return {
        "knowledge_blueprint_id": selected,
        "knowledge_blueprint_registry_sha256": semantic_blueprint_registry_sha256(),
        "knowledge_blueprint_module_sha256": registry[selected],
        "knowledge_blueprint_candidates": [
            {"id": module_id, "module_sha256": module_sha}
            for module_id, module_sha in registry.items()
        ],
        "knowledge_blueprint_rationale_codes": rationale,
        "output_modules": list(_DEFAULT_BLUEPRINTS),
        "export_profiles": export_profiles[selected],
    }


def _require_idempotency_key(value: str | None) -> str:
    if value is None:
        raise HTTPException(
            status_code=428,
            detail={"code": "IDEMPOTENCY_KEY_REQUIRED"},
        )
    return value


async def _require_verified_user(
    session: AsyncSession,
    principal: Principal,
) -> User:
    user = await session.scalar(
        select(User).where(
            User.id == principal.user_id,
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "SESSION_REVOKED"})
    if user.email_verified_at is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "EMAIL_VERIFICATION_REQUIRED"},
        )
    return user


async def _project(
    session: AsyncSession,
    *,
    principal: Principal,
    project_id: uuid.UUID,
    capability: Literal["read", "write"],
    lock: bool = False,
) -> Project:
    statement = select(Project).where(
        Project.tenant_id == principal.tenant_id,
        Project.id == project_id,
        Project.deletion_requested_at.is_(None),
        project_access_predicate(principal, Project.id, capability),
    )
    if lock:
        statement = statement.with_for_update()
    project = await session.scalar(statement)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
    return project


async def _collection(
    session: AsyncSession,
    *,
    principal: Principal,
    collection_id: uuid.UUID,
    capability: Literal["read", "write"],
    lock: bool = False,
    include_deleted: bool = False,
) -> Collection:
    statement = (
        select(Collection)
        .join(
            Project,
            (Project.tenant_id == Collection.tenant_id) & (Project.id == Collection.project_id),
        )
        .where(
            Collection.tenant_id == principal.tenant_id,
            Collection.id == collection_id,
            Project.deletion_requested_at.is_(None),
            project_access_predicate(principal, Collection.project_id, capability),
        )
    )
    if not include_deleted:
        statement = statement.where(Collection.deletion_requested_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "COLLECTION_NOT_FOUND"})
    return row


def _transition(
    collection: Collection,
    target: str,
    *,
    reason: str | None = None,
) -> None:
    if collection.status == target:
        collection.status_reason = reason
        return
    if target not in _TRANSITIONS.get(collection.status, frozenset()):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COLLECTION_STATE_CONFLICT",
                "current": collection.status,
                "requested": target,
            },
        )
    if target == "PAUSED":
        collection.paused_from = collection.status
    elif collection.status == "PAUSED":
        if target != "CANCEL_REQUESTED" and target != collection.paused_from:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COLLECTION_RESUME_TARGET_CONFLICT",
                    "recorded": collection.paused_from,
                    "requested": target,
                },
            )
        collection.paused_from = None
    collection.status = target
    collection.status_reason = reason
    collection.updated_at = utcnow()


async def _emit_collection_event(
    session: AsyncSession,
    *,
    collection: Collection,
    event_type: str,
    payload: dict[str, Any],
    job_id: uuid.UUID | None = None,
    schema_version: str = "1.0",
) -> CollectionEvent:
    if event_type not in _EVENT_TYPES:
        raise ValueError(f"unregistered collection event type: {event_type}")
    if schema_version != "1.0":
        raise ValueError(f"unsupported collection event schema version: {schema_version}")
    payload = validate_collection_event_payload(
        event_type,
        payload,
        collection_id=collection.id,
        job_id=job_id,
    )
    collection.event_sequence += 1
    row = CollectionEvent(
        tenant_id=collection.tenant_id,
        collection_id=collection.id,
        job_id=job_id,
        sequence=collection.event_sequence,
        event_type=event_type,
        schema_version=schema_version,
        payload=payload,
    )
    session.add(row)
    await session.flush()
    return row


def _collection_response(row: Collection) -> CollectionResponse:
    return CollectionResponse.model_validate(row)


def _collection_metadata_codec(request: Request) -> CollectionMetadataCodec:
    codec = getattr(request.app.state, "collection_metadata_codec", None)
    if not isinstance(codec, CollectionMetadataCodec):
        raise HTTPException(
            status_code=503,
            detail={"code": "COLLECTION_METADATA_ENCRYPTION_REQUIRED"},
        )
    return codec


CollectionMetadataDep = Annotated[
    CollectionMetadataCodec,
    Depends(_collection_metadata_codec),
]


def _source_root_display_name(
    row: CollectionSourceRoot,
    codec: CollectionMetadataCodec,
) -> str:
    try:
        return codec.decrypt_source_root_display_name(
            row.display_name_ciphertext,
            key_id=row.metadata_key_id,
            tenant_id=row.tenant_id,
            collection_id=row.collection_id,
            source_root_id=row.id,
        )
    except CollectionMetadataIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_METADATA_INTEGRITY_FAILED"},
        ) from exc


def _file_relative_path(row: CollectionFile, codec: CollectionMetadataCodec) -> str:
    try:
        return codec.decrypt_file_relative_path(
            row.relative_path_ciphertext,
            key_id=row.metadata_key_id,
            tenant_id=row.tenant_id,
            collection_id=row.collection_id,
            source_root_id=row.source_root_id,
            file_id=row.id,
        )
    except CollectionMetadataIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_METADATA_INTEGRITY_FAILED"},
        ) from exc


def _file_display_name(row: CollectionFile, codec: CollectionMetadataCodec) -> str:
    try:
        return codec.decrypt_file_display_name(
            row.display_name_ciphertext,
            key_id=row.metadata_key_id,
            tenant_id=row.tenant_id,
            collection_id=row.collection_id,
            source_root_id=row.source_root_id,
            file_id=row.id,
        )
    except CollectionMetadataIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_METADATA_INTEGRITY_FAILED"},
        ) from exc


def _source_root_response(
    row: CollectionSourceRoot,
    codec: CollectionMetadataCodec,
) -> SourceRootResponse:
    return SourceRootResponse(
        id=row.id,
        collection_id=row.collection_id,
        source_type=cast(Any, row.source_type),
        display_name=_source_root_display_name(row, codec),
        source_fingerprint=row.source_fingerprint,
        status=cast(Any, row.status),
        created_at=row.created_at,
    )


def _file_response(
    row: CollectionFile,
    codec: CollectionMetadataCodec,
) -> CollectionFileResponse:
    upload_required = row.status in {"planned", "uploading"}
    return CollectionFileResponse(
        id=row.id,
        source_root_id=row.source_root_id,
        source_file_id=row.source_file_id,
        relative_path=_file_relative_path(row, codec),
        display_name=_file_display_name(row, codec),
        size_bytes=row.size_bytes,
        last_modified_ms=row.last_modified_ms,
        expected_mime=row.expected_mime,
        detected_mime=row.detected_mime,
        sha256=row.sha256,
        quick_fingerprint=row.quick_fingerprint,
        status=cast(Any, row.status),
        error_code=row.error_code,
        upload_required=upload_required,
        upload_endpoint="/v1/uploads/initiate" if upload_required else None,
    )


def _upload_summary(row: CollectionUploadSession) -> CollectionUploadSummary:
    return CollectionUploadSummary(
        upload_session_id=row.id,
        manifest_revision=row.manifest_revision,
        resume_version=row.resume_version,
        status=cast(Any, row.status),
        total_files=row.total_files,
        total_bytes=row.total_bytes,
        completed_files=row.completed_files,
        active_files=row.active_files,
        failed_files=row.failed_files,
        duplicate_files=row.duplicate_files,
        source_manifest_hash=row.source_manifest_hash,
        expires_at=row.expires_at,
    )


def _plan_tier(plan_code: str) -> PlanTier:
    if plan_code.casefold() in {"team", "enterprise"}:
        return PlanTier.TEAM
    if plan_code.casefold() in {"personal", "pro"}:
        return PlanTier.PRO
    return PlanTier.FREE


def _manifest_record(
    row: CollectionFile,
    codec: CollectionMetadataCodec,
) -> dict[str, Any]:
    return {
        "file_id": str(row.id),
        "source_root_id": str(row.source_root_id),
        "relative_path": _file_relative_path(row, codec),
        "display_name": _file_display_name(row, codec),
        "size_bytes": row.size_bytes,
        "last_modified_ms": row.last_modified_ms,
        "expected_mime": row.expected_mime,
        "sha256": row.sha256,
        "quick_fingerprint": row.quick_fingerprint,
    }


async def _manifest_hash(
    session: AsyncSession,
    *,
    collection: Collection,
    codec: CollectionMetadataCodec,
) -> str:
    rows = list(
        await session.scalars(
            select(CollectionFile)
            .where(
                CollectionFile.tenant_id == collection.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status != "purged",
            )
            .order_by(CollectionFile.source_root_id, CollectionFile.id)
        )
    )
    rows.sort(
        key=lambda row: (
            str(row.source_root_id),
            normalize_collection_relative_path(_file_relative_path(row, codec)),
            str(row.id),
        )
    )
    return _sha256(_canonical_json([_manifest_record(row, codec) for row in rows]))


async def _latest_upload(
    session: AsyncSession,
    *,
    collection: Collection,
    lock: bool = False,
) -> CollectionUploadSession | None:
    statement = (
        select(CollectionUploadSession)
        .where(
            CollectionUploadSession.tenant_id == collection.tenant_id,
            CollectionUploadSession.collection_id == collection.id,
        )
        .order_by(CollectionUploadSession.manifest_revision.desc())
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    return cast(CollectionUploadSession | None, await session.scalar(statement))


async def _refresh_upload_aggregate(
    session: AsyncSession,
    *,
    collection: Collection,
    upload: CollectionUploadSession,
    codec: CollectionMetadataCodec,
) -> tuple[int, int, int]:
    rows = list(
        await session.scalars(
            select(CollectionFile).where(
                CollectionFile.tenant_id == collection.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status != "purged",
            )
        )
    )
    statuses = Counter(row.status for row in rows)
    completed = sum(statuses[state] for state in _SUCCESS_FILE_STATES)
    failed = sum(statuses[state] for state in _FAILED_FILE_STATES)
    active = len(rows) - completed - failed
    upload.total_files = len(rows)
    upload.total_bytes = sum(row.size_bytes for row in rows)
    upload.completed_files = completed
    upload.active_files = active
    upload.failed_files = failed
    upload.duplicate_files = statuses["duplicate"]
    upload.source_manifest_hash = await _manifest_hash(
        session,
        collection=collection,
        codec=codec,
    )
    upload.updated_at = utcnow()

    if active:
        upload.status = "uploading"
        if collection.status == "HASHING":
            _transition(collection, "UPLOADING")
    elif completed and not failed:
        upload.status = "completed"
        upload.completed_at = utcnow()
        if collection.status in {"HASHING", "UPLOADING", "VERIFYING"}:
            if collection.status == "HASHING":
                _transition(collection, "UPLOADING")
            if collection.status == "UPLOADING":
                _transition(collection, "VERIFYING")
            source_ids = {
                row.source_file_id
                for row in rows
                if row.status in _SUCCESS_FILE_STATES and row.source_file_id is not None
            }
            sources = await _source_files_by_id(
                session,
                tenant_id=collection.tenant_id,
                identifiers=source_ids,
            )
            if len(sources) != len(source_ids):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "COLLECTION_SECURITY_EVIDENCE_MISSING"},
                )
            _transition(collection, "SECURITY_SCAN")
            await _emit_collection_event(
                session,
                collection=collection,
                event_type="file.security.passed.v1",
                payload={
                    "collection_id": str(collection.id),
                    "verified_files": completed,
                    "source_files": len(source_ids),
                    "antivirus_status_counts": dict(
                        sorted(
                            Counter(source.antivirus_status for source in sources.values()).items()
                        )
                    ),
                    "cdr_status_counts": dict(
                        sorted(Counter(source.cdr_status for source in sources.values()).items())
                    ),
                },
            )
            _transition(collection, "DEDUPLICATING")
            if upload.duplicate_files:
                await _emit_collection_event(
                    session,
                    collection=collection,
                    event_type="file.duplicate.detected.v1",
                    payload={
                        "collection_id": str(collection.id),
                        "duplicate_files": upload.duplicate_files,
                        "processing_credits": 0,
                    },
                )
            _transition(collection, "INGESTED")
            await _emit_collection_event(
                session,
                collection=collection,
                event_type="collection.ingested.v1",
                payload={
                    "collection_id": str(collection.id),
                    "verified_files": completed,
                    "unavailable_files": 0,
                    "manifest_sha256": upload.source_manifest_hash,
                    "status": collection.status,
                },
            )
    elif completed:
        upload.status = "partial"
        upload.completed_at = utcnow()
        if collection.status in {"HASHING", "UPLOADING", "VERIFYING"}:
            if collection.status == "HASHING":
                _transition(collection, "UPLOADING")
            if collection.status == "UPLOADING":
                _transition(collection, "VERIFYING")
            _transition(collection, "SECURITY_SCAN")
            await _emit_collection_event(
                session,
                collection=collection,
                event_type="file.security.passed.v1",
                payload={
                    "collection_id": str(collection.id),
                    "verified_files": completed,
                    "unavailable_files": failed,
                },
            )
            _transition(collection, "DEDUPLICATING")
            if upload.duplicate_files:
                await _emit_collection_event(
                    session,
                    collection=collection,
                    event_type="file.duplicate.detected.v1",
                    payload={
                        "collection_id": str(collection.id),
                        "duplicate_files": upload.duplicate_files,
                        "processing_credits": 0,
                    },
                )
            _transition(collection, "PARTIAL", reason="SOME_FILES_UNAVAILABLE")
            await _emit_collection_event(
                session,
                collection=collection,
                event_type="collection.ingested.v1",
                payload={
                    "collection_id": str(collection.id),
                    "verified_files": completed,
                    "unavailable_files": failed,
                    "manifest_sha256": upload.source_manifest_hash,
                    "status": collection.status,
                },
            )
    else:
        upload.status = "partial"
        upload.completed_at = utcnow()
        if collection.status in {"HASHING", "UPLOADING", "VERIFYING"}:
            _transition(collection, "UNRESOLVED", reason="NO_VERIFIED_FILES")
    return completed, active, failed


@router.post("/collections", response_model=CollectionResponse, status_code=201)
@idempotent_mutation
async def create_collection(
    payload: CollectionCreate,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey = None,
) -> CollectionResponse:
    del request
    _require_idempotency_key(idempotency_key)
    await _require_verified_user(session, principal)
    await _project(
        session,
        principal=principal,
        project_id=payload.project_id,
        capability="write",
        lock=True,
    )
    row = Collection(
        tenant_id=principal.tenant_id,
        project_id=payload.project_id,
        name=payload.name,
        description=payload.description,
        profile=payload.profile,
        created_by=principal.user_id,
        status="CREATED",
    )
    session.add(row)
    await session.flush()
    await _emit_collection_event(
        session,
        collection=row,
        event_type="collection.created.v1",
        payload={
            "collection_id": str(row.id),
            "project_id": str(row.project_id),
            "status": row.status,
        },
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.created",
        target_type="collection",
        target_id=str(row.id),
        metadata={"project_id": str(row.project_id)},
    )
    await session.commit()
    return _collection_response(row)


@router.post(
    "/collections/{collection_id}/sources/local",
    response_model=SourceRootResponse,
    status_code=201,
)
@idempotent_mutation
async def create_local_source(
    collection_id: uuid.UUID,
    payload: LocalSourceCreate,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
    codec: CollectionMetadataDep,
    idempotency_key: IdempotencyKey = None,
) -> SourceRootResponse:
    _require_idempotency_key(idempotency_key)
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="write",
        lock=True,
    )
    if collection.status not in {"CREATED", "DISCOVERING"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_SOURCE_WINDOW_CLOSED"},
        )
    existing = await session.scalar(
        select(CollectionSourceRoot).where(
            CollectionSourceRoot.tenant_id == principal.tenant_id,
            CollectionSourceRoot.collection_id == collection.id,
            CollectionSourceRoot.source_fingerprint == payload.source_fingerprint,
            CollectionSourceRoot.status == "active",
        )
    )
    if existing is not None:
        return _source_root_response(existing, codec)
    if collection.status == "CREATED":
        _transition(collection, "DISCOVERING")
    root_id = uuid.uuid4()
    protected_name = codec.encrypt_source_root_display_name(
        payload.display_name,
        tenant_id=principal.tenant_id,
        collection_id=collection.id,
        source_root_id=root_id,
    )
    row = CollectionSourceRoot(
        id=root_id,
        tenant_id=principal.tenant_id,
        collection_id=collection.id,
        source_type="local",
        display_name_ciphertext=protected_name.ciphertext,
        metadata_key_id=protected_name.key_id,
        source_fingerprint=payload.source_fingerprint,
        created_by=principal.user_id,
    )
    session.add(row)
    await session.flush()
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="collection.source.created.v1",
        payload={
            "collection_id": str(collection.id),
            "source_root_id": str(row.id),
            "source_type": row.source_type,
            "status": collection.status,
        },
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.source_created",
        target_type="collection_source_root",
        target_id=str(row.id),
        metadata={"collection_id": str(collection.id), "source_type": "local"},
    )
    await session.commit()
    return _source_root_response(row, codec)


async def _source_files_by_sha(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    sha256_values: set[str],
) -> dict[str, SourceFile]:
    rows: list[SourceFile] = []
    ordered = sorted(sha256_values)
    for offset in range(0, len(ordered), 400):
        rows.extend(
            await session.scalars(
                select(SourceFile).where(
                    SourceFile.tenant_id == tenant_id,
                    SourceFile.project_id == project_id,
                    SourceFile.sha256.in_(ordered[offset : offset + 400]),
                )
            )
        )
    return {row.sha256: row for row in rows}


@router.post(
    "/collections/{collection_id}/files/plan",
    response_model=CollectionFilesPlanResponse,
    status_code=201,
)
@idempotent_mutation
async def plan_collection_files(
    collection_id: uuid.UUID,
    payload: CollectionFilesPlan,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
    codec: CollectionMetadataDep,
    idempotency_key: IdempotencyKey = None,
) -> CollectionFilesPlanResponse:
    _require_idempotency_key(idempotency_key)
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="write",
        lock=True,
    )
    if collection.status not in {"DISCOVERING", "HASHING", "UPLOADING"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_MANIFEST_WINDOW_CLOSED"},
        )
    root = await session.scalar(
        select(CollectionSourceRoot).where(
            CollectionSourceRoot.tenant_id == principal.tenant_id,
            CollectionSourceRoot.collection_id == collection.id,
            CollectionSourceRoot.id == payload.source_root_id,
            CollectionSourceRoot.status == "active",
        )
    )
    if root is None:
        raise HTTPException(status_code=404, detail={"code": "SOURCE_ROOT_NOT_FOUND"})
    already_planned = await session.scalar(
        select(func.count(CollectionFile.id)).where(
            CollectionFile.tenant_id == principal.tenant_id,
            CollectionFile.collection_id == collection.id,
            CollectionFile.source_root_id == root.id,
        )
    )
    if int(already_planned or 0) > 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "SOURCE_ROOT_MANIFEST_IMMUTABLE"},
        )

    existing_count, existing_bytes = (
        await session.execute(
            select(
                func.count(CollectionFile.id),
                func.coalesce(func.sum(CollectionFile.size_bytes), 0),
            ).where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status != "purged",
            )
        )
    ).one()
    combined_count = int(existing_count) + len(payload.files)
    combined_bytes = int(existing_bytes) + sum(item.size_bytes for item in payload.files)
    if combined_count > 5_000:
        raise HTTPException(
            status_code=413,
            detail={"code": "COLLECTION_FILE_LIMIT_EXCEEDED", "maximum": 5_000},
        )
    if combined_bytes > 10 * 1024 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "COLLECTION_BYTE_LIMIT_EXCEEDED",
                "maximum": 10 * 1024 * 1024 * 1024,
            },
        )

    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})
    maximum_file_bytes = min(
        int(request.app.state.settings.max_upload_bytes),
        PLAN_LIMITS[_plan_tier(tenant.plan_code)].max_file_bytes,
    )
    reusable = await _source_files_by_sha(
        session,
        tenant_id=principal.tenant_id,
        project_id=collection.project_id,
        sha256_values={item.sha256 for item in payload.files},
    )
    seen_new_hashes: set[str] = set()
    created: list[CollectionFile] = []
    if collection.status == "DISCOVERING":
        _transition(collection, "HASHING")
    for item in payload.files:
        extension = PurePosixPath(item.relative_path).suffix.casefold()
        status = "planned"
        error_code: str | None = None
        source_file_id: uuid.UUID | None = None
        detected_mime: str | None = None
        existing = reusable.get(item.sha256)
        if extension not in ALLOWED_EXTENSIONS:
            status = "unsupported"
            error_code = "UNSUPPORTED_EXTENSION"
        elif item.size_bytes > maximum_file_bytes:
            status = "rejected"
            error_code = "PLAN_FILE_SIZE_LIMIT_EXCEEDED"
        elif existing is not None:
            if (
                existing.size_bytes != item.size_bytes
                or not _source_antivirus_verified(existing, request)
                or existing.cdr_status in {"unavailable", "rejected"}
            ):
                status = "quarantined"
                error_code = "EXISTING_SOURCE_NOT_REUSABLE"
            else:
                status = "duplicate"
                source_file_id = existing.id
                detected_mime = existing.mime_type
        elif item.sha256 in seen_new_hashes:
            status = "duplicate_pending"
        seen_new_hashes.add(item.sha256)
        file_id = uuid.uuid4()
        protected_path = codec.encrypt_file_relative_path(
            item.relative_path,
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            source_root_id=root.id,
            file_id=file_id,
        )
        protected_name = codec.encrypt_file_display_name(
            item.display_name,
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            source_root_id=root.id,
            file_id=file_id,
        )
        blind_index = codec.relative_path_blind_index(
            item.relative_path,
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            source_root_id=root.id,
        )
        row = CollectionFile(
            id=file_id,
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            source_root_id=root.id,
            source_file_id=source_file_id,
            relative_path_ciphertext=protected_path.ciphertext,
            display_name_ciphertext=protected_name.ciphertext,
            metadata_key_id=protected_path.key_id,
            relative_path_blind_index=blind_index.digest,
            relative_path_blind_index_key_id=blind_index.key_id,
            size_bytes=item.size_bytes,
            last_modified_ms=item.last_modified_ms,
            expected_mime=item.expected_mime,
            detected_mime=detected_mime,
            sha256=item.sha256,
            quick_fingerprint=item.quick_fingerprint,
            status=status,
            error_code=error_code,
        )
        session.add(row)
        created.append(row)

    collection.manifest_revision += 1
    resume_token = secrets.token_urlsafe(32)
    resume_hash = _sha256(resume_token.encode("utf-8"))
    upload = await _latest_upload(session, collection=collection, lock=True)
    if upload is None:
        upload = CollectionUploadSession(
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            manifest_revision=collection.manifest_revision,
            total_files=0,
            total_bytes=0,
            completed_files=0,
            active_files=0,
            failed_files=0,
            duplicate_files=0,
            source_manifest_hash="0" * 64,
            browser_resume_token_hash=resume_hash,
            status="planned",
            expires_at=utcnow() + timedelta(hours=24),
        )
        session.add(upload)
    else:
        upload.manifest_revision = collection.manifest_revision
        upload.resume_version += 1
        upload.browser_resume_token_hash = resume_hash
        upload.expires_at = utcnow() + timedelta(hours=24)
        upload.completed_at = None
    await session.flush()
    collection_rows = list(
        await session.scalars(
            select(CollectionFile)
            .where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status != "purged",
            )
            .order_by(CollectionFile.created_at, CollectionFile.id)
        )
    )
    hash_rows = {
        row.sha256: row
        for row in await session.scalars(
            select(FileContentHash).where(
                FileContentHash.tenant_id == principal.tenant_id,
                FileContentHash.collection_id == collection.id,
            )
        )
    }
    files_by_hash: dict[str, list[CollectionFile]] = defaultdict(list)
    for row in collection_rows:
        files_by_hash[row.sha256].append(row)
    for digest, members in sorted(files_by_hash.items()):
        hash_row = hash_rows.get(digest)
        if hash_row is None:
            hash_row = FileContentHash(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                canonical_file_id=members[0].id,
                sha256=digest,
                quick_fingerprint=members[0].quick_fingerprint,
                reference_count=len(members),
                status=(
                    "verified"
                    if any(member.status in _SUCCESS_FILE_STATES for member in members)
                    else "computed"
                ),
            )
            session.add(hash_row)
        else:
            hash_row.reference_count = len(members)
            if any(member.status in _SUCCESS_FILE_STATES for member in members):
                hash_row.status = "verified"
    for row in created:
        session.add(
            FileVersion(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                collection_file_id=row.id,
                parent_file_id=row.version_candidate_of,
                version_number=1,
                source_sha256=row.sha256,
                status="active" if row.status in _SUCCESS_FILE_STATES else "candidate",
                evidence={"manifest_revision": collection.manifest_revision},
            )
        )
        session.add(
            UploadFileSession(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                collection_file_id=row.id,
                upload_session_id=(
                    reusable[row.sha256].upload_id
                    if row.status == "duplicate" and row.sha256 in reusable
                    else None
                ),
                status=(
                    "completed"
                    if row.status == "duplicate"
                    else "failed"
                    if row.status in _FAILED_FILE_STATES
                    else "planned"
                ),
                completed_at=utcnow() if row.status == "duplicate" else None,
            )
        )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="file.discovered.v1",
        payload={
            "collection_id": str(collection.id),
            "source_root_id": str(root.id),
            "discovered_files": len(created),
            "discovered_bytes": sum(row.size_bytes for row in created),
            "manifest_revision": collection.manifest_revision,
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="file.hash.progress.v1",
        payload={
            "collection_id": str(collection.id),
            "hashed_files": len(created),
            "hash_algorithm": "sha256",
            "quick_fingerprint_files": sum(
                1 for row in created if row.quick_fingerprint is not None
            ),
            "manifest_revision": collection.manifest_revision,
        },
    )
    completed, active, failed = await _refresh_upload_aggregate(
        session,
        collection=collection,
        upload=upload,
        codec=codec,
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="collection.files.planned.v1",
        payload={
            "collection_id": str(collection.id),
            "source_root_id": str(root.id),
            "manifest_revision": collection.manifest_revision,
            "manifest_sha256": upload.source_manifest_hash,
            "total_files": upload.total_files,
            "total_bytes": upload.total_bytes,
            "completed_files": completed,
            "active_files": active,
            "failed_files": failed,
            "duplicate_files": upload.duplicate_files,
            "status": collection.status,
        },
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.files_planned",
        target_type="collection",
        target_id=str(collection.id),
        metadata={
            "source_root_id": str(root.id),
            "manifest_revision": collection.manifest_revision,
            "manifest_sha256": upload.source_manifest_hash,
            "file_count": len(created),
        },
    )
    await session.commit()
    return CollectionFilesPlanResponse(
        collection=_collection_response(collection),
        upload=_upload_summary(upload),
        browser_resume_token=resume_token,
        files=[_file_response(row, codec) for row in created],
        limitations=[
            "Upload bytes remain authoritative only through /v1/uploads/initiate and complete.",
            "Collection completion binds each file to a server-verified source_file_id.",
        ],
    )


@router.get(
    "/collections/{collection_id}/upload",
    response_model=CollectionUploadStatusResponse,
)
async def get_collection_upload(
    collection_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    codec: CollectionMetadataDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CollectionUploadStatusResponse:
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="read",
    )
    upload = await _latest_upload(session, collection=collection)
    if upload is None:
        raise HTTPException(status_code=404, detail={"code": "COLLECTION_UPLOAD_NOT_FOUND"})
    rows = list(
        await session.scalars(
            select(CollectionFile)
            .where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status != "purged",
            )
            .order_by(CollectionFile.created_at, CollectionFile.id)
            .offset(offset)
            .limit(limit)
        )
    )
    next_offset = offset + len(rows) if offset + len(rows) < upload.total_files else None
    return CollectionUploadStatusResponse(
        collection=_collection_response(collection),
        upload=_upload_summary(upload),
        files=[_file_response(row, codec) for row in rows],
        offset=offset,
        limit=limit,
        next_offset=next_offset,
    )


@router.post(
    "/collections/{collection_id}/upload/control",
    response_model=CollectionUploadControlResponse,
)
@idempotent_mutation
async def control_collection_upload(
    collection_id: uuid.UUID,
    payload: CollectionUploadControlRequest,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
    codec: CollectionMetadataDep,
    idempotency_key: IdempotencyKey = None,
) -> CollectionUploadControlResponse:
    _require_idempotency_key(idempotency_key)
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="write",
        lock=True,
    )
    upload = await _latest_upload(session, collection=collection, lock=True)
    if upload is None:
        raise HTTPException(status_code=404, detail={"code": "COLLECTION_UPLOAD_NOT_FOUND"})
    rotated_token: str | None = None
    if payload.action == "pause":
        if collection.status == "PAUSED":
            return CollectionUploadControlResponse(
                collection=_collection_response(collection),
                upload=_upload_summary(upload),
                browser_resume_token=None,
            )
        if collection.status not in {"UPLOADING", "PROCESSING"}:
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_NOT_PAUSABLE", "status": collection.status},
            )
        paused_from = collection.status
        _transition(collection, "PAUSED", reason="USER_PAUSED")
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="collection.paused.v1",
            payload={
                "collection_id": str(collection.id),
                "paused_from": paused_from,
                "upload_session_id": str(upload.id),
                "resume_version": upload.resume_version,
                "status": collection.status,
            },
        )
    else:
        if collection.status != "PAUSED" or collection.paused_from is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_NOT_PAUSED", "status": collection.status},
            )
        assert payload.browser_resume_token is not None
        submitted_hash = _sha256(payload.browser_resume_token.encode("utf-8"))
        if not secrets.compare_digest(submitted_hash, upload.browser_resume_token_hash):
            raise HTTPException(
                status_code=403,
                detail={"code": "COLLECTION_RESUME_TOKEN_INVALID"},
            )
        resume_target = collection.paused_from
        _transition(collection, resume_target, reason="USER_RESUMED")
        rotated_token = secrets.token_urlsafe(32)
        upload.browser_resume_token_hash = _sha256(rotated_token.encode("utf-8"))
        upload.expires_at = utcnow() + timedelta(hours=24)
        upload.resume_version += 1
        if resume_target == "UPLOADING":
            await _refresh_upload_aggregate(
                session,
                collection=collection,
                upload=upload,
                codec=codec,
            )
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="collection.resumed.v1",
            payload={
                "collection_id": str(collection.id),
                "resumed_to": resume_target,
                "upload_session_id": str(upload.id),
                "resume_version": upload.resume_version,
                "status": collection.status,
            },
        )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action=f"collection.{payload.action}d",
        target_type="collection",
        target_id=str(collection.id),
        metadata={"upload_session_id": str(upload.id), "status": collection.status},
    )
    await session.commit()
    return CollectionUploadControlResponse(
        collection=_collection_response(collection),
        upload=_upload_summary(upload),
        browser_resume_token=rotated_token,
    )


def _processing_control_response(
    *,
    collection: Collection,
    plan: ArchitecturePlan,
    job: ProcessingJob,
    processing_resume_token: str | None = None,
) -> CollectionProcessingResponse:
    progress = job.progress or {}
    estimate = job.cost_estimate or {}
    actual = job.cost_actual or {}
    return CollectionProcessingResponse(
        collection_id=collection.id,
        architecture_plan_id=plan.id,
        processing_job_id=job.id,
        collection_status=cast(Any, collection.status),
        processing_status=cast(Any, job.status),
        immutable_plan_sha256=str(job.requested_options["immutable_plan_sha256"]),
        approved_preflight_sha256=str(job.requested_options["approved_preflight_sha256"]),
        approved_estimate_sha256=str(job.requested_options["approved_estimate_sha256"]),
        credit_hard_cap=Decimal(str(estimate.get("hard_cap", "0"))),
        overage_policy=cast(Any, estimate.get("overage_policy", "stop_at_cap")),
        total_tasks=int(progress.get("total_tasks", 0)),
        completed_tasks=int(progress.get("completed_tasks", 0)),
        failed_tasks=int(progress.get("failed_tasks", 0)),
        billable_pages=int(actual.get("billable_pages", 0)),
        unbillable_pages=int(actual.get("unbillable_pages", 0)),
        credits_reserved=Decimal(str(actual.get("reserved", "0"))),
        credits_consumed=Decimal(str(actual.get("consumed", "0"))),
        credits_refunded=Decimal(str(actual.get("refunded", "0"))),
        credits_released=Decimal(str(actual.get("released", "0"))),
        processing_resume_token=processing_resume_token,
    )


@router.post(
    "/collections/{collection_id}/processing/control",
    response_model=CollectionProcessingResponse,
)
@idempotent_mutation
async def control_collection_processing(
    collection_id: uuid.UUID,
    payload: CollectionProcessingControlRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: EditorDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey = None,
) -> CollectionProcessingResponse:
    _require_idempotency_key(idempotency_key)
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="write",
        lock=True,
    )
    plan = await session.scalar(
        select(ArchitecturePlan)
        .where(
            ArchitecturePlan.tenant_id == principal.tenant_id,
            ArchitecturePlan.collection_id == collection.id,
            ArchitecturePlan.processing_job_id.is_not(None),
        )
        .order_by(ArchitecturePlan.plan_version.desc())
        .limit(1)
    )
    job = (
        await session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.tenant_id == principal.tenant_id,
                ProcessingJob.id == plan.processing_job_id,
                ProcessingJob.job_type == "collection_processing",
            )
            .with_for_update()
        )
        if plan is not None and plan.processing_job_id is not None
        else None
    )
    if plan is None or job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "COLLECTION_PROCESSING_JOB_NOT_FOUND"},
        )
    processing_bindings = list(
        await session.scalars(
            select(CollectionProcessingTaskBinding).where(
                CollectionProcessingTaskBinding.tenant_id == principal.tenant_id,
                CollectionProcessingTaskBinding.collection_id == collection.id,
                CollectionProcessingTaskBinding.processing_job_id == job.id,
                CollectionProcessingTaskBinding.status.in_(("active", "paused")),
            )
        )
    )
    task_ids = [binding.analysis_task_id for binding in processing_bindings]
    tasks = list(
        await session.scalars(
            select(AnalysisTask).where(
                AnalysisTask.tenant_id == principal.tenant_id,
                AnalysisTask.id.in_(task_ids),
            )
        )
    )
    rotated_token: str | None = None
    if payload.action == "pause":
        if collection.status == "PAUSED" and collection.paused_from == "PROCESSING":
            return _processing_control_response(
                collection=collection,
                plan=plan,
                job=job,
            )
        if collection.status != "PROCESSING" or job.status != "running":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COLLECTION_PROCESSING_NOT_PAUSABLE",
                    "collection_status": collection.status,
                    "processing_status": job.status,
                },
            )
        for binding in processing_bindings:
            if binding.status == "active":
                binding.status = "paused"
        _transition(collection, "PAUSED", reason="PROCESSING_USER_PAUSED")
        job.status = "paused"
        job.progress = {**job.progress, "stage": "paused"}
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="collection.paused.v1",
            job_id=job.id,
            payload={
                "collection_id": str(collection.id),
                "paused_from": "PROCESSING",
                "processing_job_id": str(job.id),
                "status": collection.status,
            },
        )
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="processing.paused.v1",
            job_id=job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(job.id),
                "queued_tasks_deferred": sum(task.status == "queued" for task in tasks),
            },
        )
    else:
        if (
            collection.status != "PAUSED"
            or collection.paused_from != "PROCESSING"
            or job.status != "paused"
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_PROCESSING_NOT_PAUSED"},
            )
        assert payload.processing_resume_token is not None
        submitted_hash = _sha256(payload.processing_resume_token.encode("utf-8"))
        expected_hash = str(job.requested_options.get("resume_token_hash", ""))
        if not secrets.compare_digest(submitted_hash, expected_hash):
            raise HTTPException(
                status_code=403,
                detail={"code": "COLLECTION_PROCESSING_RESUME_TOKEN_INVALID"},
            )
        rotated_token = secrets.token_urlsafe(32)
        job.requested_options = {
            **job.requested_options,
            "resume_token_hash": _sha256(rotated_token.encode("utf-8")),
            "resume_version": int(job.requested_options.get("resume_version", 1)) + 1,
        }
        for binding in processing_bindings:
            if binding.status == "paused":
                binding.status = "active"
        _transition(collection, "PROCESSING", reason="PROCESSING_USER_RESUMED")
        job.status = "running"
        job.progress = {**job.progress, "stage": "processing"}
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="collection.resumed.v1",
            job_id=job.id,
            payload={
                "collection_id": str(collection.id),
                "resumed_to": "PROCESSING",
                "processing_job_id": str(job.id),
                "resume_version": job.requested_options["resume_version"],
                "status": collection.status,
            },
        )
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="processing.resumed.v1",
            job_id=job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(job.id),
                "resume_version": job.requested_options["resume_version"],
            },
        )
        from akc_api.collection_processing import reconcile_collection_analysis_task

        for task in tasks:
            if task.status in {"completed", "failed", "dead_letter"}:
                await reconcile_collection_analysis_task(session, task=task)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action=f"collection.processing_{payload.action}d",
        target_type="processing_job",
        target_id=str(job.id),
        metadata={"collection_id": str(collection.id), "status": job.status},
    )
    await session.commit()
    if rotated_token is not None and request.app.state.settings.local_analysis_worker_enabled:
        from akc_api.main import _execute_local_analysis_task

        for task in tasks:
            if task.status == "queued":
                background_tasks.add_task(_execute_local_analysis_task, request.app, task.id)
    return _processing_control_response(
        collection=collection,
        plan=plan,
        job=job,
        processing_resume_token=rotated_token,
    )


async def _source_files_by_id(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    identifiers: set[uuid.UUID],
) -> dict[uuid.UUID, SourceFile]:
    rows: list[SourceFile] = []
    ordered = sorted(identifiers, key=str)
    for offset in range(0, len(ordered), 400):
        rows.extend(
            await session.scalars(
                select(SourceFile).where(
                    SourceFile.tenant_id == tenant_id,
                    SourceFile.id.in_(ordered[offset : offset + 400]),
                )
            )
        )
    return {row.id: row for row in rows}


@router.post(
    "/collections/{collection_id}/upload/complete",
    response_model=CollectionUploadCompleteResponse,
)
@idempotent_mutation
async def complete_collection_upload(
    collection_id: uuid.UUID,
    payload: CollectionUploadComplete,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
    codec: CollectionMetadataDep,
    idempotency_key: IdempotencyKey = None,
) -> CollectionUploadCompleteResponse:
    _require_idempotency_key(idempotency_key)
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="write",
        lock=True,
    )
    if collection.status not in {"UPLOADING", "INGESTED", "PARTIAL"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_UPLOAD_NOT_COMPLETABLE"},
        )
    upload = await _latest_upload(session, collection=collection, lock=True)
    if upload is None:
        raise HTTPException(status_code=404, detail={"code": "COLLECTION_UPLOAD_NOT_FOUND"})

    requested_file_ids = {receipt.file_id for receipt in payload.receipts}
    files = list(
        await session.scalars(
            select(CollectionFile)
            .where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.id.in_(requested_file_ids),
            )
            .with_for_update()
        )
    )
    by_id = {row.id: row for row in files}
    missing = sorted(str(item) for item in requested_file_ids - set(by_id))
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"code": "COLLECTION_FILE_NOT_FOUND", "file_ids": missing},
        )
    source_ids = {
        receipt.source_file_id for receipt in payload.receipts if receipt.source_file_id is not None
    }
    sources = await _source_files_by_id(
        session,
        tenant_id=principal.tenant_id,
        identifiers=source_ids,
    )
    outcome_status = {
        "failed": "failed",
        # Public protocol state, never a credential.
        "password_required": "password_required",  # nosec B105
        "corrupted": "corrupted",
        "quarantined": "quarantined",
        "unsupported": "unsupported",
    }
    default_errors = {
        "failed": "CLIENT_UPLOAD_FAILED",
        # Public protocol error code, never a credential.
        "password_required": "PASSWORD_REQUIRED",  # nosec B105
        "corrupted": "CORRUPTED_SOURCE",
        "quarantined": "SOURCE_QUARANTINED",
        "unsupported": "UNSUPPORTED_SOURCE",
    }
    for receipt in payload.receipts:
        row = by_id[receipt.file_id]
        if row.status in _TERMINAL_FILE_STATES:
            same_completed = (
                receipt.outcome == "completed"
                and row.status in _SUCCESS_FILE_STATES
                and row.source_file_id == receipt.source_file_id
            )
            same_failed = (
                receipt.outcome != "completed" and row.status == outcome_status[receipt.outcome]
            )
            if same_completed or same_failed:
                continue
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COLLECTION_FILE_TERMINAL",
                    "file_id": str(row.id),
                    "status": row.status,
                },
            )
        if receipt.outcome == "completed":
            assert receipt.source_file_id is not None
            source = sources.get(receipt.source_file_id)
            if source is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "SOURCE_FILE_NOT_FOUND",
                        "file_id": str(row.id),
                    },
                )
            if source.project_id != collection.project_id:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "SOURCE_FILE_PROJECT_MISMATCH"},
                )
            if source.sha256 != row.sha256 or source.size_bytes != row.size_bytes:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "SOURCE_FILE_MANIFEST_MISMATCH"},
                )
            if not _source_antivirus_verified(source, request) or source.cdr_status in {
                "unavailable",
                "rejected",
            }:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "SOURCE_FILE_NOT_VERIFIED"},
                )
            row.source_file_id = source.id
            row.detected_mime = source.mime_type
            row.status = "verified"
            row.error_code = None
        else:
            row.source_file_id = None
            row.status = outcome_status[receipt.outcome]
            row.error_code = receipt.error_code or default_errors[receipt.outcome]

    await session.flush()
    verified_by_sha = {
        row.sha256: row.source_file_id
        for row in await session.scalars(
            select(CollectionFile).where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status.in_(_SUCCESS_FILE_STATES),
                CollectionFile.source_file_id.is_not(None),
            )
        )
        if row.source_file_id is not None
    }
    duplicate_reuses = 0
    pending_duplicates = list(
        await session.scalars(
            select(CollectionFile)
            .where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status == "duplicate_pending",
            )
            .with_for_update()
        )
    )
    for row in pending_duplicates:
        source_id = verified_by_sha.get(row.sha256)
        if source_id is None:
            continue
        source = sources.get(source_id)
        if source is None:
            source = await session.get(SourceFile, source_id)
        if source is None or source.tenant_id != principal.tenant_id:
            raise HTTPException(status_code=409, detail={"code": "SOURCE_REUSE_LOST"})
        row.source_file_id = source.id
        row.detected_mime = source.mime_type
        row.status = "duplicate"
        row.error_code = None
        duplicate_reuses += 1
    await session.flush()
    terminal_file_ids = requested_file_ids | {row.id for row in pending_duplicates}
    file_upload_bindings = {
        row.collection_file_id: row
        for row in await session.scalars(
            select(UploadFileSession)
            .where(
                UploadFileSession.tenant_id == principal.tenant_id,
                UploadFileSession.collection_id == collection.id,
                UploadFileSession.collection_file_id.in_(terminal_file_ids),
            )
            .with_for_update()
        )
    }
    terminal_rows = list(
        await session.scalars(
            select(CollectionFile).where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.id.in_(terminal_file_ids),
            )
        )
    )
    versions = {
        row.collection_file_id: row
        for row in await session.scalars(
            select(FileVersion).where(
                FileVersion.tenant_id == principal.tenant_id,
                FileVersion.collection_id == collection.id,
                FileVersion.collection_file_id.in_(terminal_file_ids),
            )
        )
    }
    hashes = {
        row.sha256: row
        for row in await session.scalars(
            select(FileContentHash).where(
                FileContentHash.tenant_id == principal.tenant_id,
                FileContentHash.collection_id == collection.id,
                FileContentHash.sha256.in_({row.sha256 for row in terminal_rows}),
            )
        )
    }
    for row in terminal_rows:
        binding = file_upload_bindings.get(row.id)
        version = versions.get(row.id)
        if row.status in _SUCCESS_FILE_STATES and row.source_file_id is not None:
            source = sources.get(row.source_file_id) or await session.get(
                SourceFile, row.source_file_id
            )
            if source is None or source.tenant_id != principal.tenant_id:
                raise HTTPException(status_code=409, detail={"code": "SOURCE_REUSE_LOST"})
            if binding is not None:
                binding.upload_session_id = source.upload_id
                binding.status = "completed"
                binding.completed_at = utcnow()
            if version is not None:
                version.status = "active"
            if row.sha256 in hashes:
                hashes[row.sha256].status = "verified"
        else:
            if binding is not None:
                binding.status = "failed"
                binding.completed_at = utcnow()
            if version is not None:
                version.status = "rejected"
            if row.status == "quarantined":
                session.add(
                    QuarantineItem(
                        tenant_id=principal.tenant_id,
                        collection_id=collection.id,
                        collection_file_id=row.id,
                        reason_code=row.error_code or "COLLECTION_FILE_QUARANTINED",
                        status="open",
                        evidence={"manifest_revision": collection.manifest_revision},
                    )
                )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="file.upload.completed.v1",
        payload={
            "collection_id": str(collection.id),
            "accepted_receipts": len(payload.receipts),
            "verified_receipts": sum(
                1 for receipt in payload.receipts if receipt.outcome == "completed"
            ),
            "failed_receipts": sum(
                1 for receipt in payload.receipts if receipt.outcome != "completed"
            ),
            "duplicate_reuses": duplicate_reuses,
            "manifest_revision": collection.manifest_revision,
        },
    )
    completed, active, failed = await _refresh_upload_aggregate(
        session,
        collection=collection,
        upload=upload,
        codec=codec,
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="collection.upload.completed.v1",
        payload={
            "collection_id": str(collection.id),
            "upload_session_id": str(upload.id),
            "manifest_revision": collection.manifest_revision,
            "manifest_sha256": upload.source_manifest_hash,
            "accepted_receipts": len(payload.receipts),
            "completed_files": completed,
            "active_files": active,
            "failed_files": failed,
            "duplicate_files": upload.duplicate_files,
            "status": collection.status,
        },
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.upload_receipts_completed",
        target_type="collection",
        target_id=str(collection.id),
        metadata={
            "upload_session_id": str(upload.id),
            "manifest_revision": collection.manifest_revision,
            "receipt_count": len(payload.receipts),
        },
    )
    await session.commit()
    return CollectionUploadCompleteResponse(
        collection=_collection_response(collection),
        upload=_upload_summary(upload),
        accepted_receipts=len(payload.receipts),
        duplicate_reuses=duplicate_reuses,
        unresolved_files=failed,
    )


def _size_bucket(size_bytes: int) -> str:
    if size_bytes < 1 * 1024 * 1024:
        return "lt_1_mib"
    if size_bytes < 10 * 1024 * 1024:
        return "1_to_10_mib"
    if size_bytes < 100 * 1024 * 1024:
        return "10_to_100_mib"
    return "gte_100_mib"


def _cluster_descriptor(
    row: CollectionFile,
    codec: CollectionMetadataCodec,
) -> dict[str, Any]:
    relative_path = _file_relative_path(row, codec)
    suffix = PurePosixPath(relative_path).suffix.casefold() or "none"
    depth = len(PurePosixPath(relative_path).parts)
    return {
        "extension": suffix,
        "path_depth_bucket": str(min(depth, 6)),
        "size_bucket": _size_bucket(row.size_bytes),
        "status_class": (
            "verified"
            if row.status in _SUCCESS_FILE_STATES
            else "unavailable"
            if row.status in _FAILED_FILE_STATES
            else "active"
        ),
    }


_PREFLIGHT_SAMPLE_KEYS = frozenset(
    {
        "difficulty",
        "difficulty_score",
        "preflight_difficulty",
        "native_quality",
        "native_text_ratio",
        "table_density",
        "image_density",
        "numeric_density",
        "blur_score",
        "recovery_probability",
        "runtime_seconds",
        "runtime_ms",
        "output_tokens",
        "probe_artifact_sha256",
        "probe_attestation_sha256",
    }
)

_PROBE_REVISION = "collection-parser-model-probe-v1"


def _page_metric_map(page: Page) -> dict[str, Any] | None:
    raw = page.preflight_metrics if isinstance(page.preflight_metrics, dict) else {}
    nested = raw.get("router_metrics")
    metrics = {**nested, **raw} if isinstance(nested, dict) else dict(raw)
    if not _PREFLIGHT_SAMPLE_KEYS.intersection(metrics):
        return None
    return metrics


def _bounded_float(value: Any, *, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:  # NaN
        return default
    return min(high, max(low, parsed))


def _bounded_optional_float(value: Any, *, low: float, high: float) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN
        return None
    return min(high, max(low, parsed))


def _route_for_page(page: Page) -> Route:
    if page.status == "UNRESOLVED":
        return Route.UNRESOLVED
    if page.status == "QUARANTINED":
        return Route.QUARANTINE
    raw = str(page.route or "native").casefold()
    aliases = {
        "native_text": Route.NATIVE,
        "native": Route.NATIVE,
        "paddle": Route.PADDLE_FAST,
        "paddle_fast": Route.PADDLE_FAST,
        "hpd": Route.HPD_FAST,
        "hpd_fast": Route.HPD_FAST,
        "paddle_vl": Route.PADDLE_VL,
        "unlimited": Route.UNLIMITED_LONG,
        "unlimited_long": Route.UNLIMITED_LONG,
        "mistral": Route.MISTRAL_FALLBACK,
        "mistral_fallback": Route.MISTRAL_FALLBACK,
        "region_recovery": Route.REGION_RECOVERY,
        "authority_reconstruction": Route.AUTHORITY_RECONSTRUCTION,
        "unresolved": Route.UNRESOLVED,
        "quarantine": Route.QUARANTINE,
        "quarantined": Route.QUARANTINE,
    }
    return aliases.get(raw, Route.PADDLE_VL)


def _sample_observation(
    *,
    collection_file: CollectionFile,
    page: Page,
    cluster_key: str,
    metrics: dict[str, Any],
) -> PreflightObservation:
    difficulty = _bounded_float(
        metrics.get(
            "difficulty",
            metrics.get("difficulty_score", metrics.get("preflight_difficulty", 50.0)),
        ),
        default=50.0,
        low=0.0,
        high=100.0,
    )
    native_quality = _bounded_optional_float(
        metrics.get("native_quality", metrics.get("native_text_ratio")),
        low=0.0,
        high=1.0,
    )
    width = metrics.get("page_width", page.width_pt)
    height = metrics.get("page_height", page.height_pt)
    return PreflightObservation(
        page_id=f"{collection_file.id}:{page.id}",
        cluster_id=cluster_key,
        page_index0=max(0, page.page_number - 1),
        difficulty=difficulty,
        native_quality=native_quality,
        table_density=_bounded_optional_float(
            metrics.get("table_density"), low=0.0, high=1.0
        ),
        image_density=_bounded_optional_float(
            metrics.get("image_density"), low=0.0, high=1.0
        ),
        numeric_density=_bounded_optional_float(
            metrics.get("numeric_density"), low=0.0, high=1.0
        ),
        width=max(1, int(float(width))) if width is not None else None,
        height=max(1, int(float(height))) if height is not None else None,
    )


def _expanded_sample_ids(
    observations: list[PreflightObservation],
    *,
    selected: tuple[str, ...],
    expansion_limit: int,
) -> list[str]:
    """Fill the estimator seed to the exact adaptive 3/5/10/20 tier."""

    target = min(len(observations), expansion_limit)
    result = list(selected)
    remaining = sorted(
        (row for row in observations if row.page_id not in result),
        key=lambda row: (row.difficulty, row.page_index0, row.page_id),
    )
    while remaining and len(result) < target:
        result.append(remaining.pop(0 if len(result) % 2 == 0 else -1).page_id)
    return result


def _runtime_seconds(metrics: dict[str, Any]) -> float | None:
    if metrics.get("runtime_seconds") is not None:
        return _bounded_float(metrics["runtime_seconds"], default=0.0, low=0.0, high=86_400.0)
    if metrics.get("runtime_ms") is not None:
        milliseconds = _bounded_float(
            metrics["runtime_ms"], default=0.0, low=0.0, high=86_400_000.0
        )
        return milliseconds / 1000
    return None


def _validated_probe_receipt(metrics: dict[str, Any]) -> dict[str, Any] | None:
    artifact = metrics.get("probe_artifact")
    attestation = metrics.get("probe_attestation")
    artifact_sha = metrics.get("probe_artifact_sha256")
    attestation_sha = metrics.get("probe_attestation_sha256")
    runtime = _runtime_seconds(metrics)
    if (
        metrics.get("static_only") is not False
        or not isinstance(artifact, dict)
        or not isinstance(attestation, dict)
        or not isinstance(artifact_sha, str)
        or not isinstance(attestation_sha, str)
        or runtime is None
        or runtime <= 0
        or len(artifact_sha) != 64
        or len(attestation_sha) != 64
        or _sha256(_canonical_json(artifact)) != artifact_sha
        or _sha256(_canonical_json(attestation)) != attestation_sha
        or attestation.get("schema_version") != "1.0"
        or attestation.get("probe_revision") != _PROBE_REVISION
        or attestation.get("probe_kind") == "static"
        or not isinstance(attestation.get("execution_receipt_id"), str)
        or not isinstance(attestation.get("source_page_input_sha256"), str)
        or not isinstance(attestation.get("parser_revision"), str)
        or not isinstance(attestation.get("model_revision"), str)
        or not isinstance(attestation.get("provider_revision"), str)
        or not isinstance(attestation.get("runtime_image_digest"), str)
        or not isinstance(attestation.get("output_sha256"), str)
        or not isinstance(attestation.get("output_length"), int)
        or not isinstance(attestation.get("started_monotonic_ns"), int)
        or not isinstance(attestation.get("completed_monotonic_ns"), int)
        or attestation["completed_monotonic_ns"] <= attestation["started_monotonic_ns"]
        or attestation.get("artifact_sha256") != artifact_sha
        or attestation.get("runtime_seconds") != metrics.get("runtime_seconds")
        or attestation.get("output_tokens") != metrics.get("output_tokens")
        or artifact.get("recovery_probability") != metrics.get("recovery_probability")
        or metrics.get("probe_attestation_verified") is not True
        or not isinstance(metrics.get("probe_attestation_key_id"), str)
        or not isinstance(metrics.get("probe_attestation_signature"), str)
    ):
        return None
    return {
        "probe_revision": _PROBE_REVISION,
        "artifact_sha256": artifact_sha,
        "attestation_sha256": attestation_sha,
        "attestation": attestation,
        "attestation_key_id": metrics["probe_attestation_key_id"],
        "attestation_signature": metrics["probe_attestation_signature"],
        "runtime_seconds": runtime,
        "output_tokens": max(0, int(metrics.get("output_tokens") or 0)),
        "recovery_probability": _bounded_float(
            metrics.get("recovery_probability"),
            default=0.0,
            low=0.0,
            high=1.0,
        ),
    }


async def _execute_real_sample_probes(
    request: Request,
    *,
    session: AsyncSession,
    observation_meta: dict[str, tuple[CollectionFile, Document, Page, dict[str, Any], Route]],
    selected_observation_ids: set[str],
) -> dict[str, dict[str, Any]]:
    executor = getattr(request.app.state, "collection_probe_executor", None)
    verifier = getattr(request.app.state, "collection_probe_attestation_verifier", None)
    if executor is None or verifier is None or not selected_observation_ids:
        return {}
    source_cache: dict[uuid.UUID, tuple[SourceFile, bytes]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    try:
        for observation_id in sorted(selected_observation_ids):
            collection_file, _, page, metrics, predicted_route = observation_meta[observation_id]
            source_id = collection_file.source_file_id
            if source_id is None:
                return {}
            source_and_raw = source_cache.get(source_id)
            if source_and_raw is None:
                source = await session.get(SourceFile, source_id)
                if source is None or source.tenant_id != collection_file.tenant_id:
                    return {}
                raw = await request.app.state.object_store.read_source(source.storage_key)
                if len(raw) != source.size_bytes or _sha256(raw) != source.sha256:
                    return {}
                source_and_raw = (source, raw)
                source_cache[source_id] = source_and_raw
            source, raw = source_and_raw
            input_sha = source_page_input_sha256(raw, page.page_number - 1)
            raw_receipt = await executor.execute(
                CollectionProbeRequest(
                    tenant_id=collection_file.tenant_id,
                    collection_id=collection_file.collection_id,
                    source_file_id=source.id,
                    source_sha256=source.sha256,
                    source_filename=source.safe_filename,
                    source_bytes=raw,
                    page_index=page.page_number - 1,
                    source_page_input_sha256=input_sha,
                    predicted_route=predicted_route.value,
                )
            )
            receipt = CollectionProbeReceipt.model_validate(raw_receipt)
            if (
                receipt.source_sha256 != source.sha256
                or receipt.source_page_input_sha256 != input_sha
                or receipt.page_index != page.page_number - 1
            ):
                return {}
            verified = await verifier.verify(
                key_id=receipt.attestation_key_id,
                attestation=probe_canonical_json(receipt.attestation),
                signature=receipt.attestation_signature,
            )
            if not verified:
                return {}
            page.preflight_metrics = {
                **metrics,
                "static_only": False,
                "probe_kind": receipt.probe_kind,
                "probe_revision": receipt.probe_revision,
                "runtime_seconds": receipt.runtime_seconds,
                "output_tokens": receipt.output_tokens,
                "recovery_probability": receipt.recovery_probability,
                "probe_artifact": receipt.artifact,
                "probe_artifact_sha256": receipt.artifact_sha256,
                "probe_attestation": receipt.attestation,
                "probe_attestation_sha256": receipt.attestation_sha256,
                "probe_attestation_key_id": receipt.attestation_key_id,
                "probe_attestation_signature": receipt.attestation_signature,
                "probe_attestation_verified": True,
            }
            validated = _validated_probe_receipt(page.preflight_metrics)
            if validated is None:
                return {}
            receipts[observation_id] = validated
    except (OSError, RuntimeError, TypeError, ValueError):
        return {}
    return receipts


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile + 0.999999)))
    return ordered[index]


async def _documents_by_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    source_ids: set[uuid.UUID],
) -> dict[uuid.UUID, Document]:
    rows: list[Document] = []
    ordered = sorted(source_ids, key=str)
    for offset in range(0, len(ordered), 400):
        rows.extend(
            await session.scalars(
                select(Document)
                .where(
                    Document.tenant_id == tenant_id,
                    Document.project_id == project_id,
                    Document.source_file_id.in_(ordered[offset : offset + 400]),
                    Document.deletion_requested_at.is_(None),
                )
                .order_by(Document.source_file_id, Document.created_at.desc())
            )
        )
    result: dict[uuid.UUID, Document] = {}
    for row in rows:
        if row.source_file_id is not None:
            result.setdefault(row.source_file_id, row)
    return result


def _gpu_class(value: Any) -> GpuClass:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    aliases = {
        "cpu": GpuClass.CPU_ONLY,
        "cpu_only": GpuClass.CPU_ONLY,
        "t4": GpuClass.T4,
        "l4": GpuClass.L4,
        "a10": GpuClass.A10,
        "a10g": GpuClass.A10,
        "a100": GpuClass.A100,
        "h100": GpuClass.H100,
    }
    return aliases.get(normalized, GpuClass.UNKNOWN)


def _gpu_thermal_state(value: Any) -> GpuThermalState:
    normalized = str(value or "").strip().casefold()
    return {
        "warm": GpuThermalState.WARM,
        "cold": GpuThermalState.COLD,
    }.get(normalized, GpuThermalState.UNKNOWN)


async def _stored_predictor_context(
    session: AsyncSession,
    *,
    collection: Collection,
    document_ids: set[uuid.UUID],
) -> dict[str, Any]:
    note_count = 0
    relation_count = 0
    entity_count = 0
    block_ids: set[str] = set()
    if document_ids:
        note_count = int(
            await session.scalar(
                select(func.count(KnowledgeNote.id)).where(
                    KnowledgeNote.tenant_id == collection.tenant_id,
                    KnowledgeNote.project_id == collection.project_id,
                    KnowledgeNote.document_id.in_(document_ids),
                    KnowledgeNote.is_active.is_(True),
                )
            )
            or 0
        )
        relation_count = int(
            await session.scalar(
                select(func.count(Relation.id)).where(
                    Relation.tenant_id == collection.tenant_id,
                    Relation.project_id == collection.project_id,
                    Relation.document_id.in_(document_ids),
                    Relation.is_active.is_(True),
                )
            )
            or 0
        )
        block_ids = {
            str(block_id)
            for block_id in await session.scalars(
                select(Block.id).where(
                    Block.tenant_id == collection.tenant_id,
                    Block.document_id.in_(document_ids),
                )
            )
        }
        if block_ids:
            entity_evidence = await session.scalars(
                select(Entity.evidence_block_ids).where(
                    Entity.tenant_id == collection.tenant_id,
                    Entity.project_id == collection.project_id,
                )
            )
            entity_count = sum(
                1
                for evidence_ids in entity_evidence
                if any(str(evidence_id) in block_ids for evidence_id in (evidence_ids or []))
            )

    queue_rows = (
        await session.execute(
            select(AnalysisTask.created_at, AnalysisTask.started_at)
            .where(
                AnalysisTask.tenant_id == collection.tenant_id,
                AnalysisTask.project_id == collection.project_id,
                AnalysisTask.started_at.is_not(None),
            )
            .order_by(AnalysisTask.created_at.desc())
            .limit(256)
        )
    ).all()
    queue_delays = [
        max(0.0, (started_at - created_at).total_seconds())
        for created_at, started_at in queue_rows
        if started_at is not None
    ]
    queue_p50 = _percentile(queue_delays, 0.50)
    queue_p95 = _percentile(queue_delays, 0.95)

    gpu_class = GpuClass.UNKNOWN
    gpu_state = GpuThermalState.UNKNOWN
    if document_ids:
        gpu_rows = list(
            await session.scalars(
                select(GpuProviderInvocation)
                .where(
                    GpuProviderInvocation.tenant_id == collection.tenant_id,
                    GpuProviderInvocation.project_id == collection.project_id,
                    GpuProviderInvocation.document_id.in_(document_ids),
                )
                .order_by(GpuProviderInvocation.created_at.desc())
                .limit(64)
            )
        )
        for invocation in gpu_rows:
            result = (
                invocation.result_manifest
                if isinstance(invocation.result_manifest, dict)
                else {}
            )
            options = invocation.options if isinstance(invocation.options, dict) else {}
            measured_class = _gpu_class(result.get("gpu_class", options.get("gpu_class")))
            measured_state = _gpu_thermal_state(result.get("gpu_state", options.get("gpu_state")))
            if gpu_class == GpuClass.UNKNOWN and measured_class != GpuClass.UNKNOWN:
                gpu_class = measured_class
            if gpu_state == GpuThermalState.UNKNOWN and measured_state != GpuThermalState.UNKNOWN:
                gpu_state = measured_state
            if gpu_class != GpuClass.UNKNOWN and gpu_state != GpuThermalState.UNKNOWN:
                break

    warnings: list[str] = []
    if queue_p50 is None:
        warnings.append("QUEUE_DELAY_UNMEASURED")
    if gpu_class == GpuClass.UNKNOWN:
        warnings.append("GPU_CLASS_UNMEASURED")
    if gpu_state == GpuThermalState.UNKNOWN:
        warnings.append("GPU_THERMAL_STATE_UNMEASURED")
    return {
        "knowledge_note_count": note_count,
        "entity_count": entity_count,
        "relation_count": relation_count,
        "entity_relation_candidates": entity_count + relation_count,
        "queue_delay_p50_seconds": queue_p50,
        "queue_delay_p95_seconds": queue_p95,
        "queue_observations": len(queue_delays),
        "gpu_class": gpu_class,
        "gpu_state": gpu_state,
        "bound_block_count": len(block_ids),
        "warnings": warnings,
    }


_STATIC_FEATURE_REVISION = "collection-verified-static-signals-v2"
_STATIC_TEXT_LIMIT = 2_000_000
_STATIC_XML_MEMBER_LIMIT = 2_000_000
_STATIC_XML_TOTAL_LIMIT = 16_000_000
_STATIC_SIGNAL_FIELDS = frozenset(
    {
        "page_count",
        "native_text_presence",
        "producer",
        "font_profile",
        "image_coverage",
        "page_width",
        "page_height",
        "resolution_dpi",
        "table_line_candidates",
        "column_count",
        "numeric_density",
        "language_script",
        "rotation_degrees",
        "skew_degrees",
        "blur_score",
        "compression_artifacts",
        "archive_expansion_ratio",
        "layout_fingerprint",
        "document_style_signature",
        "theme_master_signature",
        "scan_device_signature",
        "folder_context_hash",
    }
)


def _hashed_signal(*values: str | bytes) -> str:
    digest = hashlib.sha256()
    accepted = False
    for value in values:
        payload = value if isinstance(value, bytes) else value.encode("utf-8", errors="replace")
        if not payload:
            continue
        accepted = True
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest() if accepted else ""


def _language_script(text: str) -> str | None:
    counts: Counter[str] = Counter()
    for character in text:
        if character.isspace() or character.isdigit() or unicodedata.category(character)[0] in {
            "P",
            "S",
        }:
            continue
        point = ord(character)
        if 0xAC00 <= point <= 0xD7AF or 0x1100 <= point <= 0x11FF:
            counts["Kore"] += 1
        elif 0x4E00 <= point <= 0x9FFF:
            counts["Hani"] += 1
        elif 0x3040 <= point <= 0x30FF:
            counts["Jpan"] += 1
        elif 0x0400 <= point <= 0x04FF:
            counts["Cyrl"] += 1
        elif 0x0600 <= point <= 0x06FF:
            counts["Arab"] += 1
        elif "LATIN" in unicodedata.name(character, ""):
            counts["Latn"] += 1
        else:
            counts["Other"] += 1
    if not counts:
        return None
    return "+".join(
        name
        for name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def _text_feature_metrics(text: str, *, source_bytes: int) -> dict[str, Any]:
    """Return bounded, content-free text signals; source text is never persisted."""

    visible = [character for character in text if not character.isspace()]
    visible_count = len(visible)
    numeric_count = sum(character.isdigit() for character in visible)
    lines = text.splitlines() or [""]
    table_lines = [line for line in lines if "\t" in line or line.count("|") >= 2]
    column_candidates = [
        max(line.count("\t") + 1, line.count("|") - 1)
        for line in table_lines
    ]
    native_quality = min(1.0, visible_count / max(1, len(text)))
    numeric_density = numeric_count / max(1, visible_count)
    table_density = min(1.0, len(table_lines) / max(1, len(lines)))
    structural_rows = [
        (
            min(40, len(line) // 20),
            min(12, len(line) - len(line.lstrip())),
            int("\t" in line),
            min(12, line.count("|")),
        )
        for line in lines[:10_000]
    ]
    difficulty = min(
        100.0,
        max(0.0, 55.0 * (1.0 - native_quality) + 15.0 * table_density),
    )
    return {
        "difficulty": round(difficulty, 6),
        "native_quality": round(native_quality, 6),
        "native_text_ratio": 1.0 if visible_count else 0.0,
        "table_density": round(table_density, 6),
        "image_density": None,
        "numeric_density": round(numeric_density, 6),
        "native_text_char_count": visible_count,
        "line_count": len(lines),
        "table_line_candidates": len(table_lines),
        "column_count": min(100, max(column_candidates, default=0)),
        "language_script": _language_script(text),
        "layout_fingerprint": _sha256(_canonical_json(structural_rows)),
        "bounded_source_bytes": min(source_bytes, _STATIC_TEXT_LIMIT),
    }


def _aggregate_text_signals(descriptors: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [cast(dict[str, Any], descriptor["metrics"]) for descriptor in descriptors]
    native_presence = [float(metric["native_text_ratio"]) for metric in metrics]
    numeric = [float(metric["numeric_density"]) for metric in metrics]
    scripts = Counter(
        part
        for metric in metrics
        for part in str(metric.get("language_script") or "").split("+")
        if part
    )
    rotations = Counter(int(descriptor["rotation"]) for descriptor in descriptors)
    return {
        "page_count": len(descriptors),
        "native_text_presence": round(sum(native_presence) / len(native_presence), 6),
        "table_line_candidates": sum(int(metric["table_line_candidates"]) for metric in metrics),
        "column_count": max(int(metric["column_count"]) for metric in metrics),
        "numeric_density": round(sum(numeric) / len(numeric), 6),
        "language_script": (
            "+".join(
                name
                for name, _ in sorted(
                    scripts.items(), key=lambda item: (-item[1], item[0])
                )
            )
            if scripts
            else None
        ),
        "rotation_degrees": sorted(rotations.items(), key=lambda item: (-item[1], item[0]))[0][0],
        "layout_fingerprint": _hashed_signal(
            *(str(metric["layout_fingerprint"]) for metric in metrics)
        ),
    }


def _pdf_static_extraction(raw: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
    except (OSError, ValueError, PdfReadError) as exc:
        raise ValueError("STATIC_PREFLIGHT_PDF_INVALID") from exc
    if reader.is_encrypted:
        raise ValueError("STATIC_PREFLIGHT_PASSWORD_REQUIRED")
    if not reader.pages:
        raise ValueError("STATIC_PREFLIGHT_PDF_EMPTY")
    if len(reader.pages) > 100_000:
        raise ValueError("STATIC_PREFLIGHT_PAGE_LIMIT_EXCEEDED")

    per_page_bytes = max(1, len(raw) // len(reader.pages))
    descriptors: list[dict[str, Any]] = []
    font_names: set[str] = set()
    for page_number, source_page in enumerate(reader.pages, start=1):
        try:
            extracted_text = source_page.extract_text() or ""
        except (KeyError, TypeError, ValueError, PdfReadError):
            extracted_text = ""
        metrics = _text_feature_metrics(
            extracted_text[:_STATIC_TEXT_LIMIT],
            source_bytes=per_page_bytes,
        )
        try:
            resources = source_page.get("/Resources") or {}
            if hasattr(resources, "get_object"):
                resources = resources.get_object()
            xobjects = resources.get("/XObject") or {}
            if hasattr(xobjects, "get_object"):
                xobjects = xobjects.get_object()
            image_candidates = len(xobjects)
            fonts = resources.get("/Font") or {}
            if hasattr(fonts, "get_object"):
                fonts = fonts.get_object()
            for key, font in list(fonts.items())[:512]:
                if hasattr(font, "get_object"):
                    font = font.get_object()
                font_names.add(f"{key}:{font.get('/BaseFont', '')}:{font.get('/Subtype', '')}")
        except (AttributeError, KeyError, TypeError, ValueError, PdfReadError):
            image_candidates = 0
        metrics["image_candidate_count"] = image_candidates
        metrics["page_width"] = round(max(1.0, float(source_page.mediabox.width)), 6)
        metrics["page_height"] = round(max(1.0, float(source_page.mediabox.height)), 6)
        metrics["dimension_unit"] = DimensionUnit.POINTS.value
        native_quality = float(metrics["native_quality"])
        descriptors.append(
            {
                "page_number": page_number,
                "width_pt": metrics["page_width"],
                "height_pt": metrics["page_height"],
                "rotation": int(source_page.get("/Rotate") or 0) % 360,
                "route": "native" if native_quality >= 0.2 else "paddle_vl",
                "metrics": metrics,
            }
        )
    widths = sorted(round(float(row["metrics"]["page_width"])) for row in descriptors)
    heights = sorted(round(float(row["metrics"]["page_height"])) for row in descriptors)
    metadata = reader.metadata
    producer_values = []
    if metadata is not None:
        producer_values = [str(metadata.producer or ""), str(metadata.creator or "")]
    signals = {
        **_aggregate_text_signals(descriptors),
        "producer": _hashed_signal(*producer_values),
        "font_profile": _hashed_signal(*sorted(font_names)),
        "page_width": widths[len(widths) // 2],
        "page_height": heights[len(heights) // 2],
        "dimension_unit": DimensionUnit.POINTS.value,
    }
    return descriptors, signals


def _natural_archive_key(value: str) -> tuple[tuple[int, str], ...]:
    return tuple(
        (0, f"{int(part):012d}") if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
    )


def _bounded_archive_member(archive: zipfile.ZipFile, name: str) -> tuple[bytes, bool]:
    with archive.open(name, "r") as member:
        payload = member.read(_STATIC_XML_MEMBER_LIMIT + 1)
    return payload[:_STATIC_XML_MEMBER_LIMIT], len(payload) > _STATIC_XML_MEMBER_LIMIT


def _office_static_extraction(
    raw: bytes,
    *,
    suffix: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), "r")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ValueError("STATIC_PREFLIGHT_OFFICE_ARCHIVE_INVALID") from exc
    with archive:
        infos = archive.infolist()
        if any(info.flag_bits & 0x1 for info in infos):
            raise ValueError("STATIC_PREFLIGHT_PASSWORD_REQUIRED")
        by_lower = {info.filename.casefold(): info.filename for info in infos}
        if suffix == ".pptx":
            page_names = [
                info.filename
                for info in infos
                if info.filename.casefold().startswith("ppt/slides/slide")
                and info.filename.casefold().endswith(".xml")
                and "/_rels/" not in info.filename.casefold()
            ]
        elif suffix == ".xlsx":
            page_names = [
                info.filename
                for info in infos
                if info.filename.casefold().startswith("xl/worksheets/sheet")
                and info.filename.casefold().endswith(".xml")
                and "/_rels/" not in info.filename.casefold()
            ]
        else:
            document_name = by_lower.get("word/document.xml")
            page_names = [document_name] if document_name is not None else []
        page_names.sort(key=_natural_archive_key)
        if not page_names:
            raise ValueError("STATIC_PREFLIGHT_OFFICE_STRUCTURE_INVALID")
        if len(page_names) > 100_000:
            raise ValueError("STATIC_PREFLIGHT_PAGE_LIMIT_EXCEEDED")

        presentation_size: tuple[float, float] | None = None
        presentation_name = by_lower.get("ppt/presentation.xml")
        if presentation_name is not None:
            presentation_xml, _ = _bounded_archive_member(archive, presentation_name)
            size_tag = re.search(rb"<[^>]*sldSz\b[^>]*>", presentation_xml)
            if size_tag is not None:
                cx = re.search(rb'\bcx="(\d+)"', size_tag.group(0))
                cy = re.search(rb'\bcy="(\d+)"', size_tag.group(0))
                if cx is not None and cy is not None:
                    presentation_size = (int(cx.group(1)) / 12_700, int(cy.group(1)) / 12_700)

        descriptors: list[dict[str, Any]] = []
        consumed = 0
        any_truncated = False
        for page_number, page_name in enumerate(page_names, start=1):
            if consumed >= _STATIC_XML_TOTAL_LIMIT:
                page_xml = b""
                truncated = True
            else:
                page_xml, truncated = _bounded_archive_member(archive, page_name)
                permitted = min(len(page_xml), _STATIC_XML_TOTAL_LIMIT - consumed)
                page_xml = page_xml[:permitted]
                consumed += permitted
                truncated = truncated or permitted == 0
            any_truncated = any_truncated or truncated
            text_payload = re.sub(rb"<[^>]{0,4096}>", b" ", page_xml)
            decoded = text_payload.decode("utf-8", errors="replace")
            metrics = _text_feature_metrics(decoded, source_bytes=len(page_xml))
            metrics["archive_entry_count"] = len(infos)
            metrics["bounded_xml_truncated"] = truncated
            if presentation_size is not None:
                metrics["page_width"] = round(presentation_size[0], 6)
                metrics["page_height"] = round(presentation_size[1], 6)
                metrics["dimension_unit"] = DimensionUnit.POINTS.value
            descriptors.append(
                {
                    "page_number": page_number,
                    "width_pt": presentation_size[0] if presentation_size is not None else None,
                    "height_pt": presentation_size[1] if presentation_size is not None else None,
                    "rotation": 0,
                    "route": "native" if metrics["native_text_ratio"] else "paddle_vl",
                    "metrics": metrics,
                }
            )

        def signature_for(prefixes: tuple[str, ...]) -> str:
            payloads: list[bytes] = []
            for lower_name, original_name in sorted(by_lower.items()):
                if any(lower_name.startswith(prefix) for prefix in prefixes):
                    payload, _ = _bounded_archive_member(archive, original_name)
                    payloads.append(payload)
            return _hashed_signal(*payloads)

        uncompressed_bytes = sum(max(0, info.file_size) for info in infos)
        signals = {
            **_aggregate_text_signals(descriptors),
            "producer": signature_for(("docprops/app.xml",)),
            "font_profile": signature_for(("word/fonttable.xml", "xl/styles.xml")),
            "archive_expansion_ratio": round(uncompressed_bytes / max(1, len(raw)), 6),
            "document_style_signature": signature_for(
                ("word/styles.xml", "xl/styles.xml", "ppt/slidemasters/")
            ),
            "theme_master_signature": signature_for(("ppt/theme/", "ppt/slidemasters/")),
            "bounded_xml_truncated": any_truncated,
        }
        if presentation_size is not None:
            signals.update(
                {
                    "page_width": max(1, round(presentation_size[0])),
                    "page_height": max(1, round(presentation_size[1])),
                    "dimension_unit": DimensionUnit.POINTS.value,
                }
            )
        return descriptors, signals


def _image_static_extraction(raw: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            image_format = str(image.format or "")
            raw_dpi = image.info.get("dpi")
            dpi_values = (
                [float(value) for value in raw_dpi if float(value) > 0]
                if isinstance(raw_dpi, tuple)
                else [float(raw_dpi)]
                if isinstance(raw_dpi, (int, float)) and float(raw_dpi) > 0
                else []
            )
            dpi = sum(dpi_values) / len(dpi_values) if dpi_values else None
            exif = image.getexif()
            scan_parts = [str(exif.get(tag, "")) for tag in (271, 272, 305)] if exif else []
            orientation = int(exif.get(274, 1)) if exif else 1
            image.verify()
    except (OSError, ValueError, TypeError, UnidentifiedImageError) as exc:
        raise ValueError("STATIC_PREFLIGHT_IMAGE_INVALID") from exc
    rotation = {3: 180, 6: 90, 8: 270}.get(orientation, 0)
    width_pt = width * 72 / dpi if dpi is not None else None
    height_pt = height * 72 / dpi if dpi is not None else None
    metrics = {
        "difficulty": 70.0,
        "native_quality": 0.0,
        "native_text_ratio": 0.0,
        "table_density": None,
        "image_density": 1.0,
        "numeric_density": None,
        "page_width": width,
        "page_height": height,
        "dimension_unit": DimensionUnit.PIXELS.value,
        "resolution_dpi": round(dpi, 6) if dpi is not None else None,
    }
    descriptors = [
        {
            "page_number": 1,
            "width_pt": width_pt,
            "height_pt": height_pt,
            "rotation": rotation,
            "route": "paddle_fast",
            "metrics": metrics,
        }
    ]
    return descriptors, {
        "page_count": 1,
        "native_text_presence": 0.0,
        "producer": _hashed_signal(image_format),
        "image_coverage": 1.0,
        "page_width": width,
        "page_height": height,
        "dimension_unit": DimensionUnit.PIXELS.value,
        "resolution_dpi": round(dpi, 6) if dpi is not None else None,
        "rotation_degrees": rotation,
        "scan_device_signature": _hashed_signal(*scan_parts),
    }


def _static_page_descriptors(
    raw: bytes,
    *,
    filename: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    suffix = PurePosixPath(filename).suffix.casefold()
    if suffix == ".pdf":
        return _pdf_static_extraction(raw)
    if suffix in {".docx", ".pptx", ".xlsx"}:
        return _office_static_extraction(raw, suffix=suffix)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return _image_static_extraction(raw)
    if suffix not in {".txt", ".md", ".csv", ".html", ".htm", ".vtt", ".srt"}:
        raise ValueError("STATIC_PREFLIGHT_UNSUPPORTED_TYPE")
    decoded = raw[:_STATIC_TEXT_LIMIT].decode("utf-8", errors="replace")
    metrics = _text_feature_metrics(decoded, source_bytes=len(raw))
    descriptors = [
        {
            "page_number": 1,
            "width_pt": None,
            "height_pt": None,
            "rotation": 0,
            "route": "native",
            "metrics": metrics,
        }
    ]
    signals = {
        **_aggregate_text_signals(descriptors),
        "bounded_text_truncated": len(raw) > _STATIC_TEXT_LIMIT,
    }
    return descriptors, signals


def _folder_context_hash(
    collection_file: CollectionFile,
    codec: CollectionMetadataCodec,
) -> str:
    relative_path = PurePosixPath(_file_relative_path(collection_file, codec))
    parent = relative_path.parent.as_posix()
    normalized_parent = "__root__" if parent in {"", "."} else parent
    return codec.relative_path_blind_index(
        normalized_parent,
        tenant_id=collection_file.tenant_id,
        collection_id=collection_file.collection_id,
        source_root_id=collection_file.source_root_id,
    ).digest.hex()


def _static_feature_receipt(
    collection_file: CollectionFile,
    codec: CollectionMetadataCodec,
    *,
    signals: dict[str, Any] | None,
    verified_source_sha256: str | None,
) -> dict[str, Any]:
    suffix = PurePosixPath(_file_relative_path(collection_file, codec)).suffix.casefold() or "none"
    values = {
        key: value
        for key, value in (signals or {}).items()
        if key in StaticDocumentFeatures.model_fields
    }
    values.update(
        {
            "file_type": suffix,
            "folder_context_hash": _folder_context_hash(collection_file, codec),
        }
    )
    features = StaticDocumentFeatures.model_validate(values)
    feature_payload = features.model_dump(mode="json", by_alias=False)
    measured = sorted(
        key
        for key in _STATIC_SIGNAL_FIELDS
        if (
            feature_payload.get(key) is not None
            and (not isinstance(feature_payload.get(key), str) or bool(feature_payload.get(key)))
        )
    )
    unmeasured = sorted(_STATIC_SIGNAL_FIELDS - set(measured))
    measurement_warnings: list[str] = []
    if verified_source_sha256 is None:
        measurement_warnings.append("VERIFIED_SOURCE_BYTES_UNAVAILABLE")
    if bool((signals or {}).get("bounded_text_truncated")):
        measurement_warnings.append("BOUNDED_TEXT_EXTRACTION_TRUNCATED")
    if bool((signals or {}).get("bounded_xml_truncated")):
        measurement_warnings.append("BOUNDED_XML_EXTRACTION_TRUNCATED")
    evidence_basis = {
        "revision": _STATIC_FEATURE_REVISION,
        "verified_source_sha256": verified_source_sha256,
        "features": feature_payload,
        "measured_signals": measured,
        "unmeasured_signals": unmeasured,
        "warnings": measurement_warnings,
    }
    return {
        "features": feature_payload,
        "cluster_key": build_cluster_identity(features).removeprefix("cluster_"),
        "measurement_coverage": {
            "measured_signals": measured,
            "unmeasured_signals": unmeasured,
            "verified_source_bytes": verified_source_sha256 is not None,
            "warnings": measurement_warnings,
        },
        "evidence_revision": _STATIC_FEATURE_REVISION,
        "evidence_sha256": _sha256(_canonical_json(evidence_basis)),
    }


async def _ensure_static_preflight_pages(
    request: Request,
    session: AsyncSession,
    *,
    collection: Collection,
    documents: dict[uuid.UUID, Document],
    collection_files: list[CollectionFile],
    codec: CollectionMetadataCodec,
) -> dict[str, Any]:
    """Materialize free static descriptors; these can never attest a sampled run."""

    if not documents:
        return {
            "created_pages": 0,
            "inspected_sources": 0,
            "failures": {},
            "document_features": {},
        }
    sources = await _source_files_by_id(
        session,
        tenant_id=collection.tenant_id,
        identifiers=set(documents),
    )
    existing_pages = list(
        await session.scalars(
            select(Page).where(
                Page.tenant_id == collection.tenant_id,
                Page.document_id.in_({row.id for row in documents.values()}),
            )
        )
    )
    pages_by_document_number = {
        (page.document_id, page.page_number): page for page in existing_pages
    }
    files_by_source: dict[uuid.UUID, list[CollectionFile]] = defaultdict(list)
    for collection_file in collection_files:
        if collection_file.source_file_id is not None:
            files_by_source[collection_file.source_file_id].append(collection_file)

    created_pages = 0
    failures: Counter[str] = Counter()
    document_features: dict[str, dict[str, Any]] = {}
    for source_id in sorted(documents, key=str):
        source = sources.get(source_id)
        document = documents[source_id]
        if source is None:
            failure_code = "STATIC_PREFLIGHT_SOURCE_MISSING"
        else:
            try:
                raw = await request.app.state.object_store.read_source(source.storage_key)
                if len(raw) != source.size_bytes or _sha256(raw) != source.sha256:
                    raise ValueError("STATIC_PREFLIGHT_SOURCE_INTEGRITY_MISMATCH")
                descriptors, signals = _static_page_descriptors(
                    raw,
                    filename=source.safe_filename,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                failure_code = str(exc) or "STATIC_PREFLIGHT_FAILED"
            else:
                for descriptor in descriptors:
                    page_number = int(descriptor["page_number"])
                    metrics = {
                        **descriptor["metrics"],
                        "feature_origin": "verified_source_bytes",
                        "static_only": True,
                        "classifier_revision": "collection-native-static-v1",
                    }
                    page = pages_by_document_number.get((document.id, page_number))
                    if page is None:
                        page = Page(
                            tenant_id=collection.tenant_id,
                            document_id=document.id,
                            page_number=page_number,
                            width_pt=(
                                float(descriptor["width_pt"])
                                if descriptor["width_pt"] is not None
                                else None
                            ),
                            height_pt=(
                                float(descriptor["height_pt"])
                                if descriptor["height_pt"] is not None
                                else None
                            ),
                            rotation=int(descriptor["rotation"]),
                            status="PREFLIGHTED",
                            route=str(descriptor["route"]),
                            route_policy_version="collection-native-static-v1",
                            preflight_metrics=metrics,
                            quality_metrics={},
                        )
                        session.add(page)
                        pages_by_document_number[(document.id, page_number)] = page
                        created_pages += 1
                    else:
                        page.preflight_metrics = {**page.preflight_metrics, **metrics}
                document.page_count = len(descriptors)
                if document.status != "COMPLETED":
                    document.status = "PREFLIGHTED"
                for collection_file in files_by_source.get(source_id, []):
                    document_features[str(collection_file.id)] = _static_feature_receipt(
                        collection_file,
                        codec,
                        signals=signals,
                        verified_source_sha256=source.sha256,
                    )
                continue

        failures[failure_code] += 1
        document.status = "PREFLIGHT_FAILED"
        for collection_file in files_by_source.get(source_id, []):
            session.add(
                QuarantineItem(
                    tenant_id=collection.tenant_id,
                    collection_id=collection.id,
                    collection_file_id=collection_file.id,
                    reason_code=failure_code[:120],
                    status="open",
                    evidence={"stage": "static_preflight", "billing": "unbillable"},
                )
            )
    await session.flush()
    return {
        "created_pages": created_pages,
        "inspected_sources": len(documents),
        "failures": dict(sorted(failures.items())),
        "document_features": document_features,
    }


def _estimate_response(
    preflight: CollectionPreflight,
) -> CollectionEstimateResponse:
    estimate = preflight.estimate
    return CollectionEstimateResponse(
        collection_id=preflight.collection_id,
        preflight_id=preflight.id,
        manifest_revision=preflight.manifest_revision,
        status=cast(Any, estimate["status"]),
        basis=cast(Any, estimate["basis"]),
        p50_credits=(
            Decimal(str(estimate["p50_credits"]))
            if estimate.get("p50_credits") is not None
            else None
        ),
        p95_credits=(
            Decimal(str(estimate["p95_credits"]))
            if estimate.get("p95_credits") is not None
            else None
        ),
        reserve_ceiling=(
            Decimal(str(estimate["reserve_ceiling"]))
            if estimate.get("reserve_ceiling") is not None
            else None
        ),
        duration_p50_seconds=estimate.get("duration_p50_seconds"),
        duration_p95_seconds=estimate.get("duration_p95_seconds"),
        confidence=Decimal(str(estimate["confidence"])),
        confidence_band=cast(Any, estimate["confidence_band"]),
        route_mix={str(key): float(value) for key, value in estimate["route_mix"].items()},
        known_pages=int(estimate["known_pages"]),
        unestimated_files=int(estimate["unestimated_files"]),
        sampled_pages=int(estimate["sampled_pages"]),
        billable_pages=int(estimate["billable_pages"]),
        duplicate_pages=int(estimate["duplicate_pages"]),
        unbillable_pages=int(estimate["unbillable_pages"]),
        predictor_revision=str(estimate["predictor_revision"]),
        predictor_evidence_revision=str(estimate["predictor_evidence_revision"]),
        predictor_evidence_sha256=str(estimate["predictor_evidence_sha256"]),
        measured_signal_fields=[str(item) for item in estimate["measured_signal_fields"]],
        predictor_input=cast(dict[str, Any], estimate["predictor_input"]),
        estimate_sha256=str(estimate["estimate_sha256"]),
        knowledge_blueprint_id=str(estimate["knowledge_blueprint_id"]),
        knowledge_blueprint_registry_sha256=str(estimate["knowledge_blueprint_registry_sha256"]),
        knowledge_blueprint_module_sha256=str(estimate["knowledge_blueprint_module_sha256"]),
        knowledge_blueprint_candidates=estimate["knowledge_blueprint_candidates"],
        knowledge_blueprint_rationale_codes=[
            str(item) for item in estimate["knowledge_blueprint_rationale_codes"]
        ],
        output_modules=[cast(Any, item) for item in estimate["output_modules"]],
        export_profiles=[str(item) for item in estimate["export_profiles"]],
        learned_router_shadow=cast(dict[str, Any], estimate["learned_router_shadow"]),
        calibration_required=bool(estimate["calibration_required"]),
        warnings=[str(item) for item in estimate["warnings"]],
    )


async def _preflight_response(
    session: AsyncSession,
    preflight: CollectionPreflight,
) -> CollectionPreflightResponse:
    clusters = list(
        await session.scalars(
            select(DocumentCluster)
            .where(
                DocumentCluster.tenant_id == preflight.tenant_id,
                DocumentCluster.collection_id == preflight.collection_id,
                DocumentCluster.preflight_id == preflight.id,
            )
            .order_by(DocumentCluster.cluster_key)
        )
    )
    return CollectionPreflightResponse(
        id=preflight.id,
        collection_id=preflight.collection_id,
        manifest_revision=preflight.manifest_revision,
        status=cast(Any, preflight.status),
        coverage_ratio=Decimal(preflight.coverage_ratio),
        total_files=preflight.total_files,
        bound_files=preflight.bound_files,
        known_pages=preflight.known_pages,
        input_manifest_hash=preflight.input_manifest_hash,
        output_sha256=preflight.output_sha256,
        features=preflight.features,
        limitations=preflight.limitations,
        clusters=[
            ClusterResponse(
                id=row.id,
                cluster_key=row.cluster_key,
                strategy=row.strategy,
                member_count=row.member_count,
                representative_file_ids=[
                    uuid.UUID(str(item)) for item in row.representative_file_ids
                ],
                outlier_file_ids=[uuid.UUID(str(item)) for item in row.outlier_file_ids],
                feature_summary=row.feature_summary,
            )
            for row in clusters
        ],
        estimate=_estimate_response(preflight),
        created_at=preflight.created_at,
    )


@router.post(
    "/collections/{collection_id}/preflight",
    response_model=CollectionPreflightResponse,
    status_code=201,
)
@idempotent_mutation
async def preflight_collection(
    collection_id: uuid.UUID,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
    codec: CollectionMetadataDep,
    idempotency_key: IdempotencyKey = None,
) -> CollectionPreflightResponse:
    _require_idempotency_key(idempotency_key)
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="write",
        lock=True,
    )
    existing = await session.scalar(
        select(CollectionPreflight).where(
            CollectionPreflight.tenant_id == principal.tenant_id,
            CollectionPreflight.collection_id == collection.id,
            CollectionPreflight.manifest_revision == collection.manifest_revision,
            CollectionPreflight.status != "stale",
        )
    )
    if existing is not None:
        return await _preflight_response(session, existing)
    if collection.status not in {"INGESTED", "PARTIAL"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_NOT_READY_FOR_PREFLIGHT"},
        )
    upload = await _latest_upload(session, collection=collection)
    if upload is None or upload.active_files:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_UPLOAD_INCOMPLETE"},
        )
    _transition(collection, "PREFLIGHTING")
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="preflight.started.v1",
        payload={
            "collection_id": str(collection.id),
            "manifest_revision": collection.manifest_revision,
            "manifest_sha256": upload.source_manifest_hash,
            "status": collection.status,
        },
    )
    files = list(
        await session.scalars(
            select(CollectionFile)
            .where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status != "purged",
            )
            .order_by(CollectionFile.source_root_id, CollectionFile.id)
        )
    )
    files.sort(
        key=lambda row: (
            str(row.source_root_id),
            normalize_collection_relative_path(_file_relative_path(row, codec)),
            str(row.id),
        )
    )
    successful = [row for row in files if row.status in _SUCCESS_FILE_STATES]
    if not successful:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_HAS_NO_VERIFIED_FILES"},
        )
    source_ids = {row.source_file_id for row in successful if row.source_file_id is not None}
    documents = await _documents_by_source(
        session,
        tenant_id=principal.tenant_id,
        project_id=collection.project_id,
        source_ids=source_ids,
    )
    static_preflight = await _ensure_static_preflight_pages(
        request,
        session,
        collection=collection,
        documents=documents,
        collection_files=successful,
        codec=codec,
    )
    static_document_feature_receipts = cast(
        dict[str, dict[str, Any]],
        static_preflight.pop("document_features", {}),
    )
    document_ids = {document.id for document in documents.values()}
    predictor_context = await _stored_predictor_context(
        session,
        collection=collection,
        document_ids=document_ids,
    )

    p50 = Decimal("0")
    p95 = Decimal("0")
    duration_p50_seconds = 0
    duration_p95_seconds = 0
    known_pages = 0
    route_mix = {"native_pages": 0, "visual_pages": 0, "precision_candidates": 0}
    estimated_sources: set[uuid.UUID] = set()
    for source_id, bound_document in documents.items():
        document_estimate = await estimate_document(session, bound_document)
        document_page_count = int(document_estimate["total_pages"])
        if document_page_count <= 0:
            continue
        estimated_sources.add(source_id)
        known_pages += document_page_count
        p50 += Decimal(str(document_estimate["expected"]))
        p95 += Decimal(str(document_estimate["reserved"]))
        duration_p50_seconds += int(document_estimate["expected_duration_min"]) * 60
        duration_p95_seconds += int(document_estimate["expected_duration_max"]) * 60
        route_mix["native_pages"] += int(document_estimate["native_pages"])
        route_mix["visual_pages"] += int(document_estimate["visual_pages"])
        route_mix["precision_candidates"] += int(document_estimate["precision_candidate_pages"])
    unestimated_sources = source_ids - estimated_sources
    warnings: list[str] = [
        "Repository-rule estimate is not a calibrated production quantile model."
    ]
    if unestimated_sources:
        warnings.append("Some unique verified sources do not yet have measurable pages.")
    if upload.failed_files:
        warnings.append("Unavailable files are excluded from processing estimates.")
    estimate_status = "fast_ready" if not unestimated_sources else "incomplete"
    duplicate_pages = 0
    for duplicate_file in successful:
        if duplicate_file.status != "duplicate" or duplicate_file.source_file_id is None:
            continue
        duplicate_document = documents.get(duplicate_file.source_file_id)
        if duplicate_document is not None:
            duplicate_pages += int(duplicate_document.page_count or 0)
    fast_predictor_revision = "repository-rule-2026-07-31.1"
    fast_reserve = (p95 * Decimal("1.025")).quantize(Decimal("0.000001"))
    blueprint_receipt = _knowledge_blueprint_receipt(collection.profile)
    estimate_payload: dict[str, Any] = {
        "status": estimate_status,
        "basis": "repository_rule_v1",
        "p50_credits": str(p50.quantize(Decimal("0.000001"))),
        "p95_credits": str(p95.quantize(Decimal("0.000001"))),
        "reserve_ceiling": str(fast_reserve),
        "duration_p50_seconds": duration_p50_seconds,
        "duration_p95_seconds": duration_p95_seconds,
        "confidence": "0.450000" if estimate_status == "fast_ready" else "0.200000",
        "confidence_band": "low",
        "route_mix": route_mix,
        "known_pages": known_pages,
        "unestimated_files": len(unestimated_sources),
        "sampled_pages": 0,
        "billable_pages": known_pages,
        "duplicate_pages": duplicate_pages,
        "unbillable_pages": 0,
        "predictor_revision": fast_predictor_revision,
        **blueprint_receipt,
        "calibration_required": True,
        "warnings": warnings,
    }
    fast_estimate_payload = dict(estimate_payload)
    status_counts = Counter(row.status for row in files)
    relative_paths = {row.id: _file_relative_path(row, codec) for row in files}
    extension_counts = Counter(
        PurePosixPath(relative_paths[row.id]).suffix.casefold() or "none" for row in files
    )
    depth_counts = Counter(
        str(min(len(PurePosixPath(relative_paths[row.id]).parts), 6)) for row in files
    )
    features: dict[str, Any] = {
        "feature_scope": "manifest_plus_verified_byte_static_preflight",
        "total_files": len(files),
        "total_bytes": sum(row.size_bytes for row in files),
        "source_roots": len({row.source_root_id for row in files}),
        "unique_content_hashes": len({row.sha256 for row in files}),
        "status_counts": dict(sorted(status_counts.items())),
        "extension_counts": dict(sorted(extension_counts.items())),
        "path_depth_buckets": dict(sorted(depth_counts.items())),
        "bound_documents": len(documents),
        "known_pages": known_pages,
        "static_preflight": static_preflight,
    }
    grouped: dict[str, list[CollectionFile]] = defaultdict(list)
    descriptors: dict[str, dict[str, Any]] = {}
    file_feature_receipts: dict[uuid.UUID, dict[str, Any]] = {}
    extracted_feature_receipts = static_document_feature_receipts
    for row in files:
        feature_receipt = extracted_feature_receipts.get(str(row.id))
        if feature_receipt is None:
            feature_receipt = _static_feature_receipt(
                row,
                codec,
                signals=None,
                verified_source_sha256=None,
            )
        cluster_key = str(feature_receipt["cluster_key"])
        descriptor = {
            "features": feature_receipt["features"],
            "measurement_coverage": feature_receipt["measurement_coverage"],
            "evidence_revision": feature_receipt["evidence_revision"],
            "evidence_sha256": feature_receipt["evidence_sha256"],
        }
        grouped[cluster_key].append(row)
        descriptors[cluster_key] = descriptor
        file_feature_receipts[row.id] = feature_receipt

    measured_static_signals = sorted(
        {
            signal
            for receipt in file_feature_receipts.values()
            for signal in receipt["measurement_coverage"]["measured_signals"]
        }
    )
    unmeasured_static_signals = sorted(_STATIC_SIGNAL_FIELDS - set(measured_static_signals))
    features["static_signal_coverage"] = {
        "evidence_revision": _STATIC_FEATURE_REVISION,
        "measured_signals": measured_static_signals,
        "unmeasured_signals": unmeasured_static_signals,
        "verified_byte_feature_files": sum(
            bool(receipt["measurement_coverage"]["verified_source_bytes"])
            for receipt in file_feature_receipts.values()
        ),
    }
    configured_parallelism = collection.profile.get("max_parallel_pages")
    max_parallel_pages = (
        int(configured_parallelism)
        if isinstance(configured_parallelism, int) and 1 <= configured_parallelism <= 64
        else 8
    )
    predictor_warnings = list(cast(list[str], predictor_context["warnings"]))
    if max_parallel_pages == 8 and configured_parallelism != 8:
        predictor_warnings.append("MAX_PARALLEL_PAGES_POLICY_DEFAULT")
    export_profile_count = len(cast(list[str], blueprint_receipt["export_profiles"]))
    base_measured_predictor_fields = {
        *measured_static_signals,
        "knowledge_note_count",
        "entity_relation_candidates",
        "export_profile_count",
        "max_parallel_pages",
    }
    if predictor_context["queue_delay_p50_seconds"] is not None:
        base_measured_predictor_fields.add("queue_delay_seconds")
    if predictor_context["gpu_class"] != GpuClass.UNKNOWN:
        base_measured_predictor_fields.add("gpu_class")
    if predictor_context["gpu_state"] != GpuThermalState.UNKNOWN:
        base_measured_predictor_fields.add("gpu_state")
    predictor_evidence_revision = "collection-predictor-evidence-v2"
    predictor_base_evidence = {
        "evidence_revision": predictor_evidence_revision,
        "manifest_sha256": upload.source_manifest_hash,
        "static_feature_evidence_sha256": sorted(
            str(receipt["evidence_sha256"]) for receipt in file_feature_receipts.values()
        ),
        "knowledge_note_count": predictor_context["knowledge_note_count"],
        "entity_count": predictor_context["entity_count"],
        "relation_count": predictor_context["relation_count"],
        "entity_relation_candidates": predictor_context["entity_relation_candidates"],
        "bound_block_count": predictor_context["bound_block_count"],
        "export_profiles": blueprint_receipt["export_profiles"],
        "queue_delay_p50_seconds": predictor_context["queue_delay_p50_seconds"],
        "queue_delay_p95_seconds": predictor_context["queue_delay_p95_seconds"],
        "queue_observations": predictor_context["queue_observations"],
        "gpu_class": predictor_context["gpu_class"].value,
        "gpu_state": predictor_context["gpu_state"].value,
        "max_parallel_pages": max_parallel_pages,
        "measured_signal_fields": sorted(base_measured_predictor_fields),
        "warnings": sorted(set(predictor_warnings)),
    }
    fast_predictor_evidence_sha256 = _sha256(_canonical_json(predictor_base_evidence))
    for payload in (fast_estimate_payload, estimate_payload):
        payload.update(
            {
                "predictor_evidence_revision": predictor_evidence_revision,
                "predictor_evidence_sha256": fast_predictor_evidence_sha256,
                "measured_signal_fields": sorted(base_measured_predictor_fields),
                "predictor_input": predictor_base_evidence,
            }
        )
        payload["warnings"] = [
            *payload["warnings"],
            *sorted(set(predictor_warnings)),
        ]
        if unmeasured_static_signals:
            payload["warnings"].append(
                "STATIC_SIGNALS_UNMEASURED:" + ",".join(unmeasured_static_signals)
            )

    file_cluster_key = {row.id: key for key, members in grouped.items() for row in members}
    page_rows = (
        list(
            await session.scalars(
                select(Page)
                .where(
                    Page.tenant_id == principal.tenant_id,
                    Page.document_id.in_(document_ids),
                )
                .order_by(Page.document_id, Page.page_number)
            )
        )
        if document_ids
        else []
    )
    pages_by_document: dict[uuid.UUID, list[Page]] = defaultdict(list)
    for page in page_rows:
        pages_by_document[page.document_id].append(page)
    open_reviews = (
        list(
            await session.scalars(
                select(ReviewItem).where(
                    ReviewItem.tenant_id == principal.tenant_id,
                    ReviewItem.document_id.in_(document_ids),
                    ReviewItem.status == "open",
                )
            )
        )
        if document_ids
        else []
    )
    review_routes_by_page: dict[uuid.UUID, Route] = {}
    review_routes_by_document: dict[uuid.UUID, Route] = {}
    for review in open_reviews:
        terminal_route = (
            Route.QUARANTINE
            if review.severity.casefold() in {"critical", "high"}
            or "security" in review.category.casefold()
            else Route.UNRESOLVED
        )
        target = review_routes_by_page if review.page_id is not None else review_routes_by_document
        review_scope_id = review.page_id if review.page_id is not None else review.document_id
        target[review_scope_id] = terminal_route

    observation_meta: dict[str, tuple[CollectionFile, Document, Page, dict[str, Any], Route]] = {}
    all_page_refs: list[tuple[CollectionFile, Document, Page, Route]] = []
    for collection_file in successful:
        if collection_file.source_file_id is None:
            continue
        referenced_document = documents.get(collection_file.source_file_id)
        if referenced_document is None:
            continue
        for page in pages_by_document.get(referenced_document.id, []):
            predicted_route = review_routes_by_page.get(
                page.id,
                review_routes_by_document.get(referenced_document.id, _route_for_page(page)),
            )
            all_page_refs.append((collection_file, referenced_document, page, predicted_route))
            page_metrics = _page_metric_map(page)
            if page_metrics is None:
                continue
            observation = _sample_observation(
                collection_file=collection_file,
                page=page,
                cluster_key=file_cluster_key[collection_file.id],
                metrics=page_metrics,
            )
            observation_meta[observation.page_id] = (
                collection_file,
                referenced_document,
                page,
                page_metrics,
                predicted_route,
            )

    selected_stage_by_observation: dict[str, int] = {}
    sample_selection_reasons: dict[str, tuple[str, ...]] = {}
    sample_plan_by_cluster: dict[str, Any] = {}
    probe_receipts_by_observation: dict[str, dict[str, Any]] = {}
    sample_evidence_ready = False
    sampled_estimate: CollectionEstimate | None = None
    if all_page_refs and len(observation_meta) == len(all_page_refs):
        observations = [
            _sample_observation(
                collection_file=meta[0],
                page=meta[2],
                cluster_key=file_cluster_key[meta[0].id],
                metrics=meta[3],
            )
            for meta in observation_meta.values()
        ]
        sample_plans = select_adaptive_samples(observations)
        sample_plan_by_cluster = {plan.cluster_id: plan for plan in sample_plans}
        observations_by_cluster: dict[str, list[PreflightObservation]] = defaultdict(list)
        for observation in observations:
            observations_by_cluster[observation.cluster_id].append(observation)
        for sample_plan in sample_plans:
            for observation_id in _expanded_sample_ids(
                observations_by_cluster[sample_plan.cluster_id],
                selected=sample_plan.selected_page_ids,
                expansion_limit=sample_plan.expansion_limit,
            ):
                selected_stage_by_observation[observation_id] = sample_plan.expansion_limit
                sample_selection_reasons[observation_id] = sample_plan.selection_reasons.get(
                    observation_id,
                    ("DISPERSION_EXPANSION",),
                )

        executed_receipts = await _execute_real_sample_probes(
            request,
            session=session,
            observation_meta=observation_meta,
            selected_observation_ids=set(selected_stage_by_observation),
        )
        selected_receipts: dict[str, dict[str, Any] | None] = {
            observation_id: executed_receipts.get(observation_id)
            for observation_id in selected_stage_by_observation
        }
        sample_evidence_ready = bool(selected_receipts) and all(
            receipt is not None for receipt in selected_receipts.values()
        )
        if sample_evidence_ready:
            probe_receipts_by_observation = {
                observation_id: cast(dict[str, Any], receipt)
                for observation_id, receipt in selected_receipts.items()
            }
        else:
            selected_stage_by_observation.clear()
            sample_selection_reasons.clear()

        route_counts: Counter[Route] = Counter(route for *_, route in all_page_refs)
        duplicate_sample_pages = sum(
            1
            for collection_file, _, _, route in all_page_refs
            if collection_file.status == "duplicate"
            and route not in {Route.UNRESOLVED, Route.QUARANTINE}
        )
        selected_by_route: Counter[Route] = Counter()
        runtimes_by_route: dict[Route, list[float]] = defaultdict(list)
        recovery_by_route: dict[Route, list[float]] = defaultdict(list)
        sample_output_tokens = 0
        for observation_id in selected_stage_by_observation:
            _, _, _, _metrics, route = observation_meta[observation_id]
            selected_by_route[route] += 1
            receipt = probe_receipts_by_observation[observation_id]
            runtimes_by_route[route].append(float(receipt["runtime_seconds"]))
            recovery_by_route[route].append(float(receipt["recovery_probability"]))
            sample_output_tokens += int(receipt["output_tokens"])
        route_populations = tuple(
            RoutePopulation(
                route=route,
                pages=count,
                sampled_pages=selected_by_route[route],
                sample_runtime_seconds_p50=_percentile(runtimes_by_route[route], 0.50),
                sample_runtime_seconds_p95=_percentile(runtimes_by_route[route], 0.95),
                recovery_probability=(
                    sum(recovery_by_route[route]) / len(recovery_by_route[route])
                    if recovery_by_route[route]
                    else 0.0
                ),
            )
            for route, count in sorted(route_counts.items(), key=lambda item: item[0].value)
        )
        difficulty_values = [
            _bounded_float(
                meta[3].get(
                    "difficulty",
                    meta[3].get("difficulty_score", meta[3].get("preflight_difficulty", 50.0)),
                ),
                default=50.0,
                low=0.0,
                high=100.0,
            )
            for meta in observation_meta.values()
        ]
        measured_predictor_fields = set(base_measured_predictor_fields)
        if sample_evidence_ready:
            measured_predictor_fields.update(
                {
                    "sample_output_tokens",
                    "sample_recovery_probability",
                    "sample_runtime_seconds",
                }
            )
        sample_predictor_evidence = {
            **predictor_base_evidence,
            "route_populations": [
                population.model_dump(mode="json", by_alias=False)
                for population in route_populations
            ],
            "sample_output_tokens": sample_output_tokens,
            "sample_probe_receipts": [
                {
                    "artifact_sha256": receipt["artifact_sha256"],
                    "attestation_sha256": receipt["attestation_sha256"],
                    "probe_revision": receipt["probe_revision"],
                    "runtime_seconds": receipt["runtime_seconds"],
                    "output_tokens": receipt["output_tokens"],
                    "recovery_probability": receipt["recovery_probability"],
                }
                for _, receipt in sorted(probe_receipts_by_observation.items())
            ],
            "static_complexity": (
                sum(difficulty_values) / (100 * len(difficulty_values))
                if difficulty_values
                else 0.0
            ),
            "measured_signal_fields": sorted(measured_predictor_fields),
        }
        sample_predictor_evidence_sha256 = _sha256(
            _canonical_json(sample_predictor_evidence)
        )
        sampled_estimate = estimate_collection(
            CollectionEstimateInput(
                route_populations=route_populations,
                duplicate_pages=duplicate_sample_pages,
                knowledge_note_count=int(predictor_context["knowledge_note_count"]),
                entity_relation_candidates=int(
                    predictor_context["entity_relation_candidates"]
                ),
                export_profile_count=export_profile_count,
                queue_delay_p50_seconds=cast(
                    float | None,
                    predictor_context["queue_delay_p50_seconds"],
                ),
                queue_delay_p95_seconds=cast(
                    float | None,
                    predictor_context["queue_delay_p95_seconds"],
                ),
                gpu_state=cast(GpuThermalState, predictor_context["gpu_state"]),
                gpu_class=cast(GpuClass, predictor_context["gpu_class"]),
                sample_output_tokens=sample_output_tokens,
                static_complexity=(
                    sum(difficulty_values) / (100 * len(difficulty_values))
                    if difficulty_values
                    else 0.0
                ),
                max_parallel_pages=max_parallel_pages,
                predictor_revision="rules-quantile-2026-07-31.1",
                evidence_revision=predictor_evidence_revision,
                evidence_sha256=sample_predictor_evidence_sha256,
                measured_signal_fields=tuple(sorted(measured_predictor_fields)),
            )
        )
        sampled_warnings = [
            (
                "Adaptive estimate uses signed real parser/model probe receipts, "
                "measured runtimes, and persisted technical features."
                if sample_evidence_ready
                else "Adaptive estimate lacks complete signed real probe evidence."
            )
        ]
        if upload.failed_files:
            sampled_warnings.append("Unavailable files are excluded and remain unbillable.")
        sampled_warnings.extend(sorted(set(predictor_warnings)))
        if unmeasured_static_signals:
            sampled_warnings.append(
                "STATIC_SIGNALS_UNMEASURED:" + ",".join(unmeasured_static_signals)
            )
        if sample_evidence_ready:
            estimate_status = "sampled_ready" if not unestimated_sources else "incomplete"
            estimate_payload = {
                "status": estimate_status,
                "basis": "adaptive_sample_rules_quantile_v1",
                "p50_credits": str(
                    Decimal(str(sampled_estimate.credit_p50)).quantize(Decimal("0.000001"))
                ),
                "p95_credits": str(
                    Decimal(str(sampled_estimate.credit_p95)).quantize(Decimal("0.000001"))
                ),
                "reserve_ceiling": str(
                    Decimal(str(sampled_estimate.reserve_ceiling)).quantize(Decimal("0.000001"))
                ),
                "duration_p50_seconds": int(sampled_estimate.duration_p50_seconds + 0.999999),
                "duration_p95_seconds": int(sampled_estimate.duration_p95_seconds + 0.999999),
                "confidence": str(
                    Decimal(str(sampled_estimate.confidence)).quantize(Decimal("0.000001"))
                ),
                "confidence_band": sampled_estimate.confidence_band.value,
                "route_mix": sampled_estimate.route_mix,
                "known_pages": len(page_rows),
                "unestimated_files": len(unestimated_sources),
                "sampled_pages": sampled_estimate.sampled_pages,
                "billable_pages": sampled_estimate.billable_pages,
                "duplicate_pages": sampled_estimate.duplicate_pages,
                "unbillable_pages": sampled_estimate.unbillable_pages,
                "predictor_revision": sampled_estimate.predictor_revision,
                "predictor_evidence_revision": sampled_estimate.evidence_revision,
                "predictor_evidence_sha256": sampled_estimate.evidence_sha256,
                "measured_signal_fields": list(sampled_estimate.measured_signal_fields),
                "predictor_input": sample_predictor_evidence,
                **blueprint_receipt,
                "calibration_required": sampled_estimate.calibration_required,
                "warnings": sampled_warnings,
            }
        else:
            sampled_estimate = None
            estimate_payload["warnings"] = [
                *estimate_payload["warnings"],
                "Adaptive sampling was not claimed because a real probe receipt or "
                "attestation is missing or invalid.",
            ]
    elif all_page_refs:
        estimate_payload["warnings"] = [
            *estimate_payload["warnings"],
            "Adaptive sampling was not claimed because persisted page feature "
            "coverage is incomplete.",
        ]

    features["page_feature_records"] = len(observation_meta)
    features["page_feature_coverage"] = (
        round(len(observation_meta) / len(all_page_refs), 6) if all_page_refs else 0.0
    )
    features["adaptive_sample_tiers"] = [3, 5, 10, 20]
    features["selected_sample_pages"] = len(selected_stage_by_observation)
    features["valid_probe_receipts"] = len(probe_receipts_by_observation)

    limitations = [
        "Verified source bytes are read only for bounded native/static feature extraction.",
        "Missing page-level features remain on the fast static estimate path.",
    ]
    if sample_evidence_ready:
        limitations.append(
            "Only the selected 3/5/10/20 adaptive pages invoke the attested parser/model "
            "executor; every sampled measurement is signature verified."
        )
    else:
        limitations.append(
            "No verified external parser/model execution receipt was accepted; the result "
            "remains a fast static estimate."
        )
    if static_preflight["failures"]:
        limitations.append(
            "Static preflight failures are isolated into quarantine and remain unbillable."
        )
    if upload.failed_files:
        limitations.append(
            "Preflight covers verified files and records unavailable files separately."
        )
    learned_router_shadow = build_zero_authority_learned_router_shadow(
        champion_revision=str(estimate_payload["predictor_revision"]),
        challenger_revision="learned-quantile-shadow-untrained-v1",
        evidence_sha256=str(estimate_payload["predictor_evidence_sha256"]),
        champion_route_mix=(
            cast(dict[str, float], estimate_payload["route_mix"])
            if sampled_estimate is not None
            else {}
        ),
        challenger_route_mix=None,
        calibration_observations=0,
    )
    estimate_payload["learned_router_shadow"] = learned_router_shadow.model_dump(
        mode="json",
        by_alias=False,
    )
    fast_estimate_payload["estimate_sha256"] = _sha256(_canonical_json(fast_estimate_payload))
    estimate_payload["estimate_sha256"] = _sha256(_canonical_json(estimate_payload))
    output_basis = {
        "features": features,
        "estimate": estimate_payload,
        "limitations": limitations,
        "clusters": [
            {
                "cluster_key": key,
                "descriptor": descriptors[key],
                "member_ids": sorted(str(row.id) for row in members),
            }
            for key, members in sorted(grouped.items())
        ],
    }
    preflight = CollectionPreflight(
        tenant_id=principal.tenant_id,
        collection_id=collection.id,
        manifest_revision=collection.manifest_revision,
        status="complete" if not upload.failed_files and not unestimated_sources else "partial",
        coverage_ratio=(
            Decimal(len(successful)) / Decimal(len(files)) if files else Decimal("0")
        ).quantize(Decimal("0.000001")),
        total_files=len(files),
        bound_files=len(successful),
        known_pages=known_pages,
        input_manifest_hash=upload.source_manifest_hash,
        output_sha256=_sha256(_canonical_json(output_basis)),
        features=features,
        estimate=estimate_payload,
        limitations=limitations,
    )
    session.add(preflight)
    await session.flush()

    fast_run = EstimateRun(
        tenant_id=principal.tenant_id,
        collection_id=collection.id,
        preflight_id=preflight.id,
        run_kind="fast",
        status=fast_estimate_payload["status"],
        basis="repository_rule_v1",
        predictor_version=fast_predictor_revision,
        estimate_sha256=str(fast_estimate_payload["estimate_sha256"]),
        credit_p50=Decimal(str(fast_estimate_payload["p50_credits"])),
        credit_p95=Decimal(str(fast_estimate_payload["p95_credits"])),
        reserve_ceiling=Decimal(str(fast_estimate_payload["reserve_ceiling"])),
        duration_p50_seconds=int(fast_estimate_payload["duration_p50_seconds"]),
        duration_p95_seconds=int(fast_estimate_payload["duration_p95_seconds"]),
        confidence=Decimal(str(fast_estimate_payload["confidence"])),
        confidence_band=str(fast_estimate_payload["confidence_band"]),
        route_mix=fast_estimate_payload["route_mix"],
        sampled_pages=0,
        billable_pages=int(fast_estimate_payload["billable_pages"]),
        duplicate_pages=int(fast_estimate_payload["duplicate_pages"]),
        unbillable_pages=int(fast_estimate_payload["unbillable_pages"]),
        warnings=fast_estimate_payload["warnings"],
    )
    session.add(fast_run)
    final_estimate_run = fast_run
    if sampled_estimate is not None:
        final_estimate_run = EstimateRun(
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            preflight_id=preflight.id,
            run_kind="sampled",
            status=estimate_payload["status"],
            basis="adaptive_sample_rules_quantile_v1",
            predictor_version=str(estimate_payload["predictor_revision"]),
            estimate_sha256=str(estimate_payload["estimate_sha256"]),
            credit_p50=Decimal(str(estimate_payload["p50_credits"])),
            credit_p95=Decimal(str(estimate_payload["p95_credits"])),
            reserve_ceiling=Decimal(str(estimate_payload["reserve_ceiling"])),
            duration_p50_seconds=int(estimate_payload["duration_p50_seconds"]),
            duration_p95_seconds=int(estimate_payload["duration_p95_seconds"]),
            confidence=Decimal(str(estimate_payload["confidence"])),
            confidence_band=str(estimate_payload["confidence_band"]),
            route_mix=estimate_payload["route_mix"],
            sampled_pages=int(estimate_payload["sampled_pages"]),
            billable_pages=int(estimate_payload["billable_pages"]),
            duplicate_pages=int(estimate_payload["duplicate_pages"]),
            unbillable_pages=int(estimate_payload["unbillable_pages"]),
            warnings=estimate_payload["warnings"],
        )
        session.add(final_estimate_run)
    await session.flush()

    predictor_revision = str(estimate_payload["predictor_revision"])
    existing_predictor = await session.scalar(
        select(CostPredictionModel).where(
            CostPredictionModel.tenant_id == principal.tenant_id,
            CostPredictionModel.collection_id == collection.id,
            CostPredictionModel.predictor_version == predictor_revision,
        )
    )
    if existing_predictor is None:
        predictor_parameters = {
            "basis": estimate_payload["basis"],
            "adaptive_sample_tiers": [3, 5, 10, 20],
            "duplicate_unbillable": True,
            "terminal_unbillable_routes": ["unresolved", "quarantine"],
            "calibration_required": bool(estimate_payload["calibration_required"]),
            "predictor_evidence_revision": estimate_payload[
                "predictor_evidence_revision"
            ],
            "predictor_evidence_sha256": estimate_payload["predictor_evidence_sha256"],
            "production_authority": "deterministic_fallback",
        }
        session.add(
            CostPredictionModel(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                model_key="collection_credit_time_predictor",
                predictor_version=predictor_revision,
                model_type="rules_quantile",
                status="active_snapshot",
                parameters=predictor_parameters,
                artifact_sha256=_sha256(_canonical_json(predictor_parameters)),
            )
        )
    shadow_parameters = learned_router_shadow.model_dump(mode="json", by_alias=False)
    existing_shadow = await session.scalar(
        select(CostPredictionModel).where(
            CostPredictionModel.tenant_id == principal.tenant_id,
            CostPredictionModel.collection_id == collection.id,
            CostPredictionModel.predictor_version
            == learned_router_shadow.challenger_revision,
        )
    )
    if existing_shadow is None:
        session.add(
            CostPredictionModel(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                model_key="collection_learned_router_challenger",
                predictor_version=learned_router_shadow.challenger_revision,
                model_type="learned_quantile",
                status="shadow_snapshot",
                parameters=shadow_parameters,
                artifact_sha256=_sha256(_canonical_json(shadow_parameters)),
            )
        )

    feature_records: dict[str, PreflightFeatureRecord] = {}
    for observation_id, meta in sorted(observation_meta.items()):
        collection_file, document, page, page_metrics, predicted_route = meta
        observation = _sample_observation(
            collection_file=collection_file,
            page=page,
            cluster_key=file_cluster_key[collection_file.id],
            metrics=page_metrics,
        )
        technical_features = {
            "difficulty": observation.difficulty,
            "native_quality": observation.native_quality,
            "table_density": observation.table_density,
            "image_density": observation.image_density,
            "numeric_density": observation.numeric_density,
            "width": observation.width,
            "height": observation.height,
            "dimension_unit": page_metrics.get("dimension_unit", DimensionUnit.UNKNOWN.value),
            "rotation_degrees": page.rotation,
            "predicted_route": predicted_route.value,
            "selection_reasons": list(sample_selection_reasons.get(observation_id, ())),
            "document_static_features": file_feature_receipts[collection_file.id]["features"],
            "measurement_coverage": file_feature_receipts[collection_file.id][
                "measurement_coverage"
            ],
            "evidence_revision": file_feature_receipts[collection_file.id][
                "evidence_revision"
            ],
            "evidence_sha256": file_feature_receipts[collection_file.id]["evidence_sha256"],
        }
        feature_record = PreflightFeatureRecord(
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            preflight_id=preflight.id,
            collection_file_id=collection_file.id,
            document_id=document.id,
            page_id=page.id,
            page_index=observation.page_index0,
            cluster_key=file_cluster_key[collection_file.id],
            features=technical_features,
            classifier_version=_STATIC_FEATURE_REVISION,
        )
        session.add(feature_record)
        feature_records[observation_id] = feature_record
        fingerprint_basis = {
            "page_number": page.page_number,
            "width": observation.width,
            "height": observation.height,
            "rotation": page.rotation,
            "features": technical_features,
        }
        session.add(
            PageFingerprint(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                collection_file_id=collection_file.id,
                document_id=document.id,
                page_id=page.id,
                page_index=observation.page_index0,
                fingerprint_sha256=_sha256(_canonical_json(fingerprint_basis)),
                algorithm_version="technical-metadata-v2",
            )
        )
    await session.flush()
    for observation_id, stage in sorted(selected_stage_by_observation.items()):
        collection_file, _, page, page_metrics, predicted_route = observation_meta[observation_id]
        receipt = probe_receipts_by_observation[observation_id]
        session.add(
            EstimateSample(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                estimate_run_id=final_estimate_run.id,
                preflight_feature_record_id=feature_records[observation_id].id,
                page_id=page.id,
                cluster_key=file_cluster_key[collection_file.id],
                sample_stage=stage,
                predicted_route=predicted_route.value,
                runtime_seconds=Decimal(str(receipt["runtime_seconds"])),
                output_tokens=int(receipt["output_tokens"]),
                probe_revision=str(receipt["probe_revision"]),
                probe_artifact_sha256=str(receipt["artifact_sha256"]),
                attestation_sha256=str(receipt["attestation_sha256"]),
                attestation=cast(dict[str, Any], receipt["attestation"]),
                attestation_key_id=str(receipt["attestation_key_id"]),
                attestation_signature=str(receipt["attestation_signature"]),
                recovery_probability=Decimal(
                    str(receipt["recovery_probability"])
                ),
                billable=(
                    collection_file.status != "duplicate"
                    and predicted_route not in {Route.UNRESOLVED, Route.QUARANTINE}
                ),
            )
        )
    for row in files:
        if row.status != "quarantined":
            continue
        session.add(
            QuarantineItem(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                collection_file_id=row.id,
                reason_code=row.error_code or "COLLECTION_FILE_QUARANTINED",
                status="open",
                evidence={"manifest_revision": collection.manifest_revision},
            )
        )
    for key, members in sorted(grouped.items()):
        ordered_members = sorted(members, key=lambda item: str(item.id))
        member_ids = {member.id for member in ordered_members}
        representative_ids: list[str] = []
        outlier_ids: list[str] = []
        role_receipt: dict[str, list[str]] = {}
        representative_roles = {"MEDIAN_DIFFICULTY", "FIRST_PAGE", "LAST_PAGE"}
        outlier_roles = {
            "HIGHEST_TABLE",
            "HIGHEST_IMAGE",
            "HIGHEST_NUMERIC",
            "LOWEST_NATIVE_QUALITY",
            "UNUSUAL_DIMENSION",
        }
        for observation_id, reasons in sorted(sample_selection_reasons.items()):
            collection_file = observation_meta[observation_id][0]
            if collection_file.id not in member_ids:
                continue
            file_id = str(collection_file.id)
            role_receipt.setdefault(file_id, []).extend(reasons)
            if representative_roles.intersection(reasons) and file_id not in representative_ids:
                representative_ids.append(file_id)
            if outlier_roles.intersection(reasons) and file_id not in outlier_ids:
                outlier_ids.append(file_id)
        if not representative_ids:
            representative_candidates = [
                ordered_members[0],
                ordered_members[len(ordered_members) // 2],
                ordered_members[-1],
            ]
            representative_ids = list(
                dict.fromkeys(str(item.id) for item in representative_candidates)
            )
        session.add(
            DocumentCluster(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                preflight_id=preflight.id,
                cluster_key=key,
                strategy="verified_static_identity_v2",
                member_count=len(members),
                representative_file_ids=representative_ids,
                outlier_file_ids=outlier_ids,
                feature_summary={
                    **descriptors[key],
                    "selection_roles": {
                        file_id: sorted(set(reasons))
                        for file_id, reasons in sorted(role_receipt.items())
                    },
                    "selection_strategy": (
                        "measured_page_roles_v2"
                        if key in sample_plan_by_cluster
                        else "stable_member_order_fallback_v1"
                    ),
                    "member_evidence_sha256": sorted(
                        str(file_feature_receipts[member.id]["evidence_sha256"])
                        for member in members
                    ),
                },
            )
        )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="preflight.cluster.created.v1",
        payload={
            "collection_id": str(collection.id),
            "preflight_id": str(preflight.id),
            "cluster_count": len(grouped),
            "member_files": len(files),
            "feature_records": len(feature_records),
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="estimate.fast.ready.v1",
        payload={
            "collection_id": str(collection.id),
            "preflight_id": str(preflight.id),
            "estimate_run_id": str(fast_run.id),
            "basis": fast_run.basis,
            "predictor_revision": fast_run.predictor_version,
            "credit_p50": str(fast_run.credit_p50),
            "credit_p95": str(fast_run.credit_p95),
            "reserve_ceiling": str(fast_run.reserve_ceiling),
            "confidence": str(fast_run.confidence),
        },
    )
    if sampled_estimate is not None:
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="estimate.sample.updated.v1",
            payload={
                "collection_id": str(collection.id),
                "preflight_id": str(preflight.id),
                "estimate_run_id": str(final_estimate_run.id),
                "sampled_pages": int(estimate_payload["sampled_pages"]),
                "sample_tiers": sorted(set(selected_stage_by_observation.values())),
                "predictor_revision": str(estimate_payload["predictor_revision"]),
                "predictor_evidence_revision": str(
                    estimate_payload["predictor_evidence_revision"]
                ),
                "predictor_evidence_sha256": str(
                    estimate_payload["predictor_evidence_sha256"]
                ),
            },
        )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="estimate.final.ready.v1",
        payload={
            "collection_id": str(collection.id),
            "preflight_id": str(preflight.id),
            "estimate_run_id": str(final_estimate_run.id),
            "basis": str(estimate_payload["basis"]),
            "estimate_status": str(estimate_payload["status"]),
            "credit_p50": str(estimate_payload["p50_credits"]),
            "credit_p95": str(estimate_payload["p95_credits"]),
            "reserve_ceiling": str(estimate_payload["reserve_ceiling"]),
            "confidence": str(estimate_payload["confidence"]),
            "predictor_revision": str(estimate_payload["predictor_revision"]),
            "predictor_evidence_revision": str(
                estimate_payload["predictor_evidence_revision"]
            ),
            "predictor_evidence_sha256": str(
                estimate_payload["predictor_evidence_sha256"]
            ),
            "production_route_source": learned_router_shadow.production_route_source,
            "learned_router_authority": learned_router_shadow.authority,
            "learned_router_promotion_eligible": learned_router_shadow.promotion_eligible,
        },
    )
    _transition(collection, "ESTIMATED")
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="collection.preflight.completed.v1",
        payload={
            "collection_id": str(collection.id),
            "preflight_id": str(preflight.id),
            "manifest_revision": collection.manifest_revision,
            "manifest_sha256": upload.source_manifest_hash,
            "preflight_sha256": preflight.output_sha256,
            "cluster_count": len(grouped),
            "verified_files": len(successful),
            "unavailable_files": upload.failed_files,
            "known_pages": known_pages,
            "estimate_status": estimate_status,
            "status": collection.status,
        },
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.preflight_completed",
        target_type="collection_preflight",
        target_id=str(preflight.id),
        metadata={
            "collection_id": str(collection.id),
            "manifest_revision": collection.manifest_revision,
            "preflight_sha256": preflight.output_sha256,
        },
    )
    await session.commit()
    if sampled_estimate is not None:
        record_collection_knowledge_tokens(
            stage="probe",
            tokens=sum(
                int(receipt["output_tokens"])
                for receipt in probe_receipts_by_observation.values()
            ),
        )
    return await _preflight_response(session, preflight)


@router.get(
    "/collections/{collection_id}/estimate",
    response_model=CollectionEstimateResponse,
)
async def get_collection_estimate(
    collection_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> CollectionEstimateResponse:
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="read",
    )
    preflight = await session.scalar(
        select(CollectionPreflight)
        .where(
            CollectionPreflight.tenant_id == principal.tenant_id,
            CollectionPreflight.collection_id == collection.id,
            CollectionPreflight.manifest_revision == collection.manifest_revision,
            CollectionPreflight.status != "stale",
        )
        .order_by(CollectionPreflight.created_at.desc())
        .limit(1)
    )
    if preflight is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_PREFLIGHT_REQUIRED"},
        )
    return _estimate_response(preflight)


async def _status_counts(
    session: AsyncSession,
    model: Any,
    status_column: Any,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
) -> dict[str, int]:
    rows = (
        await session.execute(
            select(status_column, func.count())
            .where(
                model.tenant_id == tenant_id,
                model.collection_id == collection_id,
            )
            .group_by(status_column)
        )
    ).all()
    return {str(status): int(count) for status, count in rows}


async def _integrity_projection(
    session: AsyncSession,
    *,
    collection: Collection,
) -> dict[str, Any]:
    upload = await _latest_upload(session, collection=collection)
    file_counts = await _status_counts(
        session,
        CollectionFile,
        CollectionFile.status,
        tenant_id=collection.tenant_id,
        collection_id=collection.id,
    )
    verification_counts = await _status_counts(
        session,
        VerificationRecord,
        VerificationRecord.status,
        tenant_id=collection.tenant_id,
        collection_id=collection.id,
    )
    authority_counts = await _status_counts(
        session,
        AuthorityMapping,
        AuthorityMapping.mapping_status,
        tenant_id=collection.tenant_id,
        collection_id=collection.id,
    )
    package_counts = await _status_counts(
        session,
        PackageManifest,
        PackageManifest.status,
        tenant_id=collection.tenant_id,
        collection_id=collection.id,
    )
    success_rows = list(
        await session.scalars(
            select(CollectionFile).where(
                CollectionFile.tenant_id == collection.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status.in_(_SUCCESS_FILE_STATES),
            )
        )
    )
    source_ids = {row.source_file_id for row in success_rows if row.source_file_id is not None}
    documents = await _documents_by_source(
        session,
        tenant_id=collection.tenant_id,
        project_id=collection.project_id,
        source_ids=source_ids,
    )
    blockers: list[str] = []
    if upload is None:
        blockers.append("UPLOAD_SESSION_MISSING")
    elif upload.active_files:
        blockers.append("UPLOAD_ACTIVE_FILES_REMAIN")
    if not success_rows:
        blockers.append("NO_VERIFIED_FILES")
    if len(documents) != len(source_ids):
        blockers.append("VERIFIED_SOURCE_DOCUMENT_PROJECTION_MISSING")
    if any(document.status != "COMPLETED" for document in documents.values()):
        blockers.append("DOCUMENT_PROCESSING_INCOMPLETE")
    isolated_verifications = sum(
        verification_counts.get(status, 0) for status in ("unresolved", "quarantined", "rejected")
    )
    preflight = await session.scalar(
        select(CollectionPreflight)
        .where(
            CollectionPreflight.tenant_id == collection.tenant_id,
            CollectionPreflight.collection_id == collection.id,
            CollectionPreflight.manifest_revision == collection.manifest_revision,
            CollectionPreflight.status != "stale",
        )
        .order_by(CollectionPreflight.created_at.desc())
        .limit(1)
    )
    if preflight is None:
        blockers.append("PREFLIGHT_MISSING")
    elif preflight.estimate.get("status") not in {"fast_ready", "sampled_ready"}:
        blockers.append("ESTIMATE_INCOMPLETE")
    compiled_plan = await session.scalar(
        select(ArchitecturePlan.id)
        .where(
            ArchitecturePlan.tenant_id == collection.tenant_id,
            ArchitecturePlan.collection_id == collection.id,
            ArchitecturePlan.status == "compiled",
        )
        .order_by(ArchitecturePlan.plan_version.desc())
        .limit(1)
    )
    basis = {
        "collection_id": str(collection.id),
        "collection_status": collection.status,
        "manifest_revision": collection.manifest_revision,
        "manifest_hash": upload.source_manifest_hash if upload else None,
        "file_status_counts": dict(sorted(file_counts.items())),
        "verification_status_counts": dict(sorted(verification_counts.items())),
        "authority_mapping_status_counts": dict(sorted(authority_counts.items())),
        "package_status_counts": dict(sorted(package_counts.items())),
        "isolated_unbillable_verification_records": isolated_verifications,
        "source_ids": sorted(str(item) for item in source_ids),
        "document_states": {
            str(source_id): {
                "document_id": str(document.id),
                "status": document.status,
                "active_version": document.active_version,
            }
            for source_id, document in sorted(documents.items(), key=lambda item: str(item[0]))
        },
        "blockers": sorted(set(blockers)),
    }
    return {
        **basis,
        "integrity_sha256": _sha256(_canonical_json(basis)),
        "ready_for_compile": not blockers and collection.status == "ESTIMATED",
        "ready_for_full_package": (
            not blockers
            and compiled_plan is not None
            and collection.status in {"KNOWLEDGE_COMPILING", "PACKAGING", "COMPLETED"}
        ),
    }


@router.get(
    "/collections/{collection_id}/integrity",
    response_model=CollectionIntegrityResponse,
)
async def get_collection_integrity(
    collection_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> CollectionIntegrityResponse:
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="read",
    )
    projection = await _integrity_projection(session, collection=collection)
    return CollectionIntegrityResponse(
        collection_id=collection.id,
        collection_status=cast(Any, collection.status),
        manifest_hash=projection["manifest_hash"],
        integrity_sha256=projection["integrity_sha256"],
        file_status_counts=projection["file_status_counts"],
        verification_status_counts=projection["verification_status_counts"],
        authority_mapping_status_counts=projection["authority_mapping_status_counts"],
        package_status_counts=projection["package_status_counts"],
        ready_for_compile=projection["ready_for_compile"],
        ready_for_full_package=projection["ready_for_full_package"],
        blockers=projection["blockers"],
    )


@router.get(
    "/collections/{collection_id}/events",
    response_model=CollectionEventsResponse,
)
async def get_collection_events(
    collection_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CollectionEventsResponse:
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="read",
    )
    upload = await _latest_upload(session, collection=collection)
    latest_plan = await session.scalar(
        select(ArchitecturePlan)
        .where(
            ArchitecturePlan.tenant_id == principal.tenant_id,
            ArchitecturePlan.collection_id == collection.id,
        )
        .order_by(ArchitecturePlan.plan_version.desc())
        .limit(1)
    )
    processing_job = (
        await session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.tenant_id == principal.tenant_id,
                ProcessingJob.id == latest_plan.processing_job_id,
            )
        )
        if latest_plan is not None and latest_plan.processing_job_id is not None
        else None
    )
    cost_estimate = processing_job.cost_estimate if processing_job is not None else {}
    cost_actual = processing_job.cost_actual if processing_job is not None else {}
    progress = processing_job.progress if processing_job is not None else {}
    rows = list(
        await session.scalars(
            select(CollectionEvent)
            .where(
                CollectionEvent.tenant_id == principal.tenant_id,
                CollectionEvent.collection_id == collection.id,
                CollectionEvent.sequence > after_sequence,
            )
            .order_by(CollectionEvent.sequence)
            .limit(limit)
        )
    )
    events = [
        CollectionEventResponse(
            event_id=row.id,
            collection_id=row.collection_id,
            job_id=row.job_id,
            sequence=row.sequence,
            event_type=row.event_type,
            timestamp=row.occurred_at,
            payload=row.payload,
            schema_version="1.0",
        )
        for row in rows
    ]
    return CollectionEventsResponse(
        snapshot=CollectionEventSnapshot(
            collection_id=collection.id,
            status=cast(Any, collection.status),
            manifest_revision=collection.manifest_revision,
            latest_sequence=collection.event_sequence,
            upload=_upload_summary(upload) if upload is not None else None,
            processing_job_id=processing_job.id if processing_job is not None else None,
            processing_status=(cast(Any, processing_job.status) if processing_job else None),
            processing_stage=(str(progress.get("stage")) if progress.get("stage") else None),
            total_tasks=int(progress.get("total_tasks", 0)),
            completed_tasks=int(progress.get("completed_tasks", 0)),
            failed_tasks=int(progress.get("failed_tasks", 0)),
            credits_reserved=Decimal(str(cost_actual.get("reserved", "0"))),
            credits_consumed=Decimal(str(cost_actual.get("consumed", "0"))),
            credit_hard_cap=Decimal(str(cost_estimate.get("hard_cap", "0"))),
            terminal_result_ids=[
                uuid.UUID(str(item)) for item in progress.get("terminal_result_ids", [])
            ],
        ),
        events=events,
        next_sequence=events[-1].sequence if events else after_sequence,
    )


@router.get(
    "/collections/{collection_id}/scene",
    response_model=CollectionSceneResponse,
)
async def get_collection_scene(
    collection_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> CollectionSceneResponse:
    """Return a bounded, deterministic, identifier-only visual projection."""

    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="read",
    )
    latest_preflight = await session.scalar(
        select(CollectionPreflight)
        .where(
            CollectionPreflight.tenant_id == principal.tenant_id,
            CollectionPreflight.collection_id == collection.id,
            CollectionPreflight.status != "stale",
        )
        .order_by(CollectionPreflight.manifest_revision.desc())
        .limit(1)
    )
    clusters = (
        list(
            await session.scalars(
                select(DocumentCluster)
                .where(
                    DocumentCluster.tenant_id == principal.tenant_id,
                    DocumentCluster.collection_id == collection.id,
                    DocumentCluster.preflight_id == latest_preflight.id,
                )
                .order_by(DocumentCluster.cluster_key, DocumentCluster.id)
            )
        )
        if latest_preflight is not None
        else []
    )
    source_ids = list(
        await session.scalars(
            select(CollectionFile.source_file_id)
            .where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.source_file_id.is_not(None),
            )
            .order_by(CollectionFile.id)
        )
    )
    documents = await _documents_by_source(
        session,
        tenant_id=principal.tenant_id,
        project_id=collection.project_id,
        source_ids=[source_id for source_id in source_ids if source_id is not None],
    )
    document_ids = sorted((document.id for document in documents.values()), key=str)
    versions = list(
        await session.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.tenant_id == principal.tenant_id,
                DocumentVersion.document_id.in_(document_ids),
            )
            .order_by(DocumentVersion.document_id, DocumentVersion.version.desc())
        )
    ) if document_ids else []
    active_version_ids: dict[uuid.UUID, uuid.UUID] = {}
    active_versions = {document.id: document.active_version for document in documents.values()}
    for version in versions:
        if (
            version.document_id not in active_version_ids
            and version.version == active_versions.get(version.document_id)
        ):
            active_version_ids[version.document_id] = version.id

    total_pages = int(
        await session.scalar(
            select(func.count(Page.id)).where(
                Page.tenant_id == principal.tenant_id,
                Page.document_id.in_(document_ids),
            )
        )
        or 0
    ) if document_ids else 0
    page_rows = list(
        await session.scalars(
            select(Page)
            .where(
                Page.tenant_id == principal.tenant_id,
                Page.document_id.in_(document_ids),
            )
            .order_by(Page.document_id, Page.page_number)
            .limit(200)
        )
    ) if document_ids else []
    page_ids = [page.id for page in page_rows]
    preview_page_ids = set(
        await session.scalars(
            select(PageAsset.page_id)
            .where(
                PageAsset.tenant_id == principal.tenant_id,
                PageAsset.page_id.in_(page_ids),
                PageAsset.asset_type.in_(("preview", "thumbnail")),
            )
            .distinct()
        )
    ) if page_ids else set()
    finding_counts = dict(
        (
            await session.execute(
                select(CollectionRegion.page_id, func.count(VerificationRecord.id))
                .join(
                    VerificationRecord,
                    (
                        (VerificationRecord.tenant_id == CollectionRegion.tenant_id)
                        & (VerificationRecord.collection_id == CollectionRegion.collection_id)
                        & (VerificationRecord.region_id == CollectionRegion.id)
                    ),
                )
                .where(
                    CollectionRegion.tenant_id == principal.tenant_id,
                    CollectionRegion.collection_id == collection.id,
                    CollectionRegion.page_id.in_(page_ids),
                )
                .group_by(CollectionRegion.page_id)
            )
        ).all()
    ) if page_ids else {}
    knowledge = await _collection_knowledge_projection(session, collection=collection)
    package_ids = list(
        await session.scalars(
            select(PackageManifest.id)
            .where(
                PackageManifest.tenant_id == principal.tenant_id,
                PackageManifest.collection_id == collection.id,
            )
            .order_by(PackageManifest.id)
        )
    )
    integrity = await _integrity_projection(session, collection=collection)
    page_projections = [
        ScenePageProjection(
            page_id=page.id,
            document_id=page.document_id,
            document_version_id=active_version_ids.get(page.document_id),
            page_number=page.page_number,
            status=page.status,
            route=page.route,
            preview_ref=(f"/v1/pages/{page.id}/preview" if page.id in preview_page_ids else None),
            finding_count=int(finding_counts.get(page.id, 0)),
        )
        for page in page_rows
    ]
    route_state_counts = dict(
        sorted(Counter(f"{page.route or 'unrouted'}:{page.status}" for page in page_rows).items())
    )
    unresolved_count = sum(
        count
        for status, count in integrity["verification_status_counts"].items()
        if status in {"unresolved", "rejected", "failed"}
    )
    quarantined_count = int(integrity["verification_status_counts"].get("quarantined", 0))
    response_basis = {
        "collection_id": str(collection.id),
        "collection_status": collection.status,
        "manifest_revision": collection.manifest_revision,
        "sequence": collection.event_sequence,
        "total_pages": total_pages,
        "route_state_counts": route_state_counts,
        "clusters": [
            {
                "cluster_id": str(cluster.id),
                "strategy": cluster.strategy,
                "member_count": cluster.member_count,
                "representative_file_ids": sorted(cluster.representative_file_ids),
                "outlier_count": len(cluster.outlier_file_ids),
            }
            for cluster in clusters
        ],
        "pages": [projection.model_dump(mode="json") for projection in page_projections],
        "knowledge": {
            "note_ids": sorted(str(note.id) for note in knowledge.notes),
            "entity_ids": sorted(str(entity.id) for entity in knowledge.entities),
            "relation_ids": sorted(str(relation.id) for relation in knowledge.relations),
            "package_ids": sorted(str(package_id) for package_id in package_ids),
        },
        "integrity": {
            "file_status_counts": dict(sorted(integrity["file_status_counts"].items())),
            "verification_status_counts": dict(
                sorted(integrity["verification_status_counts"].items())
            ),
            "authority_mapping_status_counts": dict(
                sorted(integrity["authority_mapping_status_counts"].items())
            ),
            "package_status_counts": dict(sorted(integrity["package_status_counts"].items())),
            "unresolved_count": unresolved_count,
            "quarantined_count": quarantined_count,
            "blocker_codes": sorted(integrity["blockers"]),
        },
    }
    return CollectionSceneResponse(
        collection_id=collection.id,
        collection_status=cast(Any, collection.status),
        manifest_revision=collection.manifest_revision,
        sequence=collection.event_sequence,
        total_pages=total_pages,
        projected_page_count=len(page_projections),
        route_state_counts=route_state_counts,
        clusters=[
            SceneClusterProjection(
                cluster_id=cluster.id,
                strategy=cluster.strategy,
                member_count=cluster.member_count,
                representative_file_ids=[
                    uuid.UUID(str(item)) for item in sorted(cluster.representative_file_ids)
                ],
                outlier_count=len(cluster.outlier_file_ids),
            )
            for cluster in clusters
        ],
        pages=page_projections,
        knowledge=SceneKnowledgeProjection(
            note_ids=[note.id for note in knowledge.notes],
            entity_ids=[entity.id for entity in knowledge.entities],
            relation_ids=[relation.id for relation in knowledge.relations],
            package_ids=package_ids,
            note_count=knowledge.note_count,
            entity_count=knowledge.entity_count,
            relation_count=knowledge.relation_count,
            package_count=len(package_ids),
        ),
        integrity=SceneIntegrityProjection(**response_basis["integrity"]),
        scene_hash=_sha256(_canonical_json(response_basis)),
    )


@router.get("/collections/{collection_id}/events/stream")
async def stream_collection_events(
    collection_id: uuid.UUID,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Replay tenant-scoped collection events, then tail them with SSE keepalives."""

    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="read",
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

    async def event_stream() -> Any:
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
                    await event_session.scalars(
                        select(CollectionEvent)
                        .where(
                            CollectionEvent.tenant_id == tenant_id,
                            CollectionEvent.collection_id == collection.id,
                            CollectionEvent.sequence > cursor,
                        )
                        .order_by(CollectionEvent.sequence)
                        .limit(200)
                    )
                )
            if rows:
                for row in rows:
                    cursor = row.sequence
                    body = json.dumps(
                        {
                            "event_id": str(row.id),
                            "collection_id": str(row.collection_id),
                            "job_id": str(row.job_id) if row.job_id is not None else None,
                            "sequence": row.sequence,
                            "event_type": row.event_type,
                            "timestamp": row.occurred_at.isoformat(),
                            "payload": row.payload,
                            "schema_version": "1.0",
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


async def _architecture_response(
    session: AsyncSession,
    plan: ArchitecturePlan,
    *,
    processing_resume_token: str | None = None,
) -> ArchitecturePlanResponse:
    modules = list(
        await session.scalars(
            select(BlueprintModule)
            .where(
                BlueprintModule.tenant_id == plan.tenant_id,
                BlueprintModule.collection_id == plan.collection_id,
                BlueprintModule.architecture_plan_id == plan.id,
            )
            .order_by(BlueprintModule.module_key)
        )
    )
    processing_job = (
        await session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.tenant_id == plan.tenant_id,
                ProcessingJob.id == plan.processing_job_id,
            )
        )
        if plan.processing_job_id is not None
        else None
    )
    cost_actual = processing_job.cost_actual if processing_job is not None else {}
    return ArchitecturePlanResponse(
        id=plan.id,
        collection_id=plan.collection_id,
        plan_version=plan.plan_version,
        status=cast(Any, plan.status),
        input_integrity_sha256=plan.input_integrity_sha256,
        plan=plan.plan,
        modules=[
            BlueprintModuleResponse(
                id=row.id,
                module_key=cast(Any, row.module_key),
                module_version=row.module_version,
                status=cast(Any, row.status),
                config=row.config_json,
                output_summary=row.output_summary,
            )
            for row in modules
        ],
        processing_job_id=processing_job.id if processing_job is not None else None,
        processing_status=(cast(Any, processing_job.status) if processing_job else None),
        processing_resume_token=processing_resume_token,
        credits_reserved=Decimal(str(cost_actual.get("reserved", "0"))),
        credits_consumed=Decimal(str(cost_actual.get("consumed", "0"))),
        credits_refunded=Decimal(str(cost_actual.get("refunded", "0"))),
        credits_released=Decimal(str(cost_actual.get("released", "0"))),
        execution_scope=cast(
            Any, plan.plan.get("execution_scope", "existing_verified_artifacts_only")
        ),
        created_at=plan.created_at,
    )


def _estimate_sample_attested(sample: EstimateSample) -> bool:
    attestation = sample.attestation
    required_string_fields = (
        "execution_receipt_id",
        "source_page_input_sha256",
        "parser_revision",
        "model_revision",
        "provider_revision",
        "runtime_image_digest",
        "output_sha256",
    )
    return bool(
        isinstance(attestation, dict)
        and sample.runtime_seconds > 0
        and len(sample.probe_artifact_sha256) == 64
        and len(sample.attestation_sha256) == 64
        and _sha256(_canonical_json(attestation)) == sample.attestation_sha256
        and attestation.get("schema_version") == "1.0"
        and attestation.get("probe_revision") == sample.probe_revision
        and attestation.get("probe_kind") in {"native_parser", "ocr_model", "vlm_model"}
        and all(isinstance(attestation.get(key), str) for key in required_string_fields)
        and isinstance(attestation.get("output_length"), int)
        and int(attestation["output_length"]) > 0
        and isinstance(attestation.get("started_monotonic_ns"), int)
        and isinstance(attestation.get("completed_monotonic_ns"), int)
        and int(attestation["completed_monotonic_ns"])
        > int(attestation["started_monotonic_ns"])
        and attestation.get("artifact_sha256") == sample.probe_artifact_sha256
        and Decimal(str(attestation.get("runtime_seconds"))) == Decimal(sample.runtime_seconds)
        and int(attestation.get("output_tokens", -1)) == sample.output_tokens
        and bool(sample.attestation_key_id)
        and len(sample.attestation_signature) >= 16
    )


def _route_mix_error_ratio(
    predicted: dict[str, Any],
    actual: dict[str, float],
) -> float | None:
    try:
        predicted_mix = {str(key): float(value) for key, value in predicted.items()}
    except (TypeError, ValueError):
        return None
    if not predicted_mix or abs(sum(predicted_mix.values()) - 1.0) > 1e-6:
        return None
    keys = set(predicted_mix) | set(actual)
    return 0.5 * sum(abs(predicted_mix.get(key, 0.0) - actual.get(key, 0.0)) for key in keys)


async def _completion_calibration_receipt(
    session: AsyncSession,
    *,
    collection: Collection,
    processing_job: ProcessingJob,
    collection_files: list[CollectionFile],
    package_size_bytes: int,
) -> dict[str, Any]:
    preflight = await session.scalar(
        select(CollectionPreflight)
        .where(
            CollectionPreflight.tenant_id == collection.tenant_id,
            CollectionPreflight.collection_id == collection.id,
            CollectionPreflight.status != "stale",
        )
        .order_by(CollectionPreflight.created_at.desc())
        .limit(1)
    )
    estimate = preflight.estimate if preflight is not None else {}
    source_sizes = {
        row.source_file_id: row.size_bytes
        for row in collection_files
        if row.status in _SUCCESS_FILE_STATES and row.source_file_id is not None
    }
    documents = await _documents_by_source(
        session,
        tenant_id=collection.tenant_id,
        project_id=collection.project_id,
        source_ids=set(source_sizes),
    )
    document_ids = {document.id for document in documents.values()}
    pages = (
        list(
            await session.scalars(
                select(Page).where(
                    Page.tenant_id == collection.tenant_id,
                    Page.document_id.in_(document_ids),
                )
            )
        )
        if document_ids
        else []
    )
    actual_route_counts: Counter[str] = Counter()
    for page in pages:
        route = _route_for_page(page)
        if route not in {Route.UNRESOLVED, Route.QUARANTINE}:
            actual_route_counts[route.value] += 1
    actual_route_total = sum(actual_route_counts.values())
    actual_route_mix = (
        {
            route: count / actual_route_total
            for route, count in sorted(actual_route_counts.items())
        }
        if actual_route_total
        else {}
    )
    route_mix_error = _route_mix_error_ratio(
        cast(dict[str, Any], estimate.get("route_mix", {})),
        actual_route_mix,
    )

    attempt_numbers = list(
        await session.scalars(
            select(RouteAttempt.attempt_number).where(
                RouteAttempt.tenant_id == collection.tenant_id,
                RouteAttempt.collection_id == collection.id,
            )
        )
    )
    retry_attempts = sum(max(0, int(attempt) - 1) for attempt in attempt_numbers)
    retry_ratio = retry_attempts / actual_route_total if actual_route_total else None

    actual = processing_job.cost_actual if isinstance(processing_job.cost_actual, dict) else {}
    actual_credits = float(actual["consumed"]) if "consumed" in actual else None
    actual_duration = (
        max(0.0, (processing_job.completed_at - processing_job.started_at).total_seconds())
        if processing_job.completed_at is not None and processing_job.started_at is not None
        else None
    )
    credit_p50 = (
        float(estimate["p50_credits"])
        if estimate.get("p50_credits") is not None
        else None
    )
    duration_p50 = (
        float(estimate["duration_p50_seconds"])
        if estimate.get("duration_p50_seconds") is not None
        else None
    )
    credit_error = (
        abs(credit_p50 - actual_credits) / max(1.0, actual_credits)
        if credit_p50 is not None and actual_credits is not None
        else None
    )
    duration_error = (
        abs(duration_p50 - actual_duration) / max(1.0, actual_duration)
        if duration_p50 is not None and actual_duration is not None
        else None
    )
    input_bytes = sum(source_sizes.values())
    storage_amplification = package_size_bytes / input_bytes if input_bytes > 0 else None
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "calibration_revision": "collection-outcome-calibration-v1",
        "estimate_sha256": estimate.get("estimate_sha256"),
        "predictor_revision": estimate.get("predictor_revision"),
        "predictor_evidence_sha256": estimate.get("predictor_evidence_sha256"),
        "actual_credits": actual_credits,
        "actual_duration_seconds": actual_duration,
        "actual_route_mix": actual_route_mix,
        "credit_error_ratio": credit_error,
        "duration_error_ratio": duration_error,
        "route_mix_error_ratio": route_mix_error,
        "retry_attempts": retry_attempts,
        "retry_ratio": retry_ratio,
        "storage_amplification_ratio": storage_amplification,
        "credits_refunded": actual.get("refunded") if "refunded" in actual else None,
        "learned_router_authority": "zero",
        "production_route_source": "deterministic_fallback",
    }
    receipt["evidence_sha256"] = _sha256(_canonical_json(receipt))
    return receipt


def _approved_blueprint(
    payload: CollectionCompileRequest,
    estimate: dict[str, Any],
) -> dict[str, Any]:
    expected = {
        "knowledge_blueprint_id": str(estimate["knowledge_blueprint_id"]),
        "knowledge_blueprint_registry_sha256": str(estimate["knowledge_blueprint_registry_sha256"]),
        "knowledge_blueprint_module_sha256": str(estimate["knowledge_blueprint_module_sha256"]),
    }
    submitted = {
        "knowledge_blueprint_id": payload.knowledge_blueprint_id,
        "knowledge_blueprint_registry_sha256": (
            payload.knowledge_blueprint_registry_sha256
            or expected["knowledge_blueprint_registry_sha256"]
        ),
        "knowledge_blueprint_module_sha256": (
            payload.knowledge_blueprint_module_sha256
            or expected["knowledge_blueprint_module_sha256"]
        ),
    }
    if submitted != expected:
        raise HTTPException(
            status_code=409,
            detail={"code": "KNOWLEDGE_BLUEPRINT_APPROVAL_MISMATCH"},
        )
    if list(payload.output_modules) != list(estimate["output_modules"]):
        raise HTTPException(
            status_code=409,
            detail={"code": "OUTPUT_MODULE_APPROVAL_MISMATCH"},
        )
    return expected


async def _start_collection_processing(
    *,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession,
    principal: Principal,
    collection: Collection,
    preflight: CollectionPreflight,
    estimate_run: EstimateRun,
    payload: CollectionCompileRequest,
    successful: list[CollectionFile],
    documents: dict[uuid.UUID, Document],
) -> ArchitecturePlanResponse:
    samples = list(
        await session.scalars(
            select(EstimateSample).where(
                EstimateSample.tenant_id == principal.tenant_id,
                EstimateSample.collection_id == collection.id,
                EstimateSample.estimate_run_id == estimate_run.id,
            )
        )
    )
    verifier = getattr(request.app.state, "collection_probe_attestation_verifier", None)
    if (
        estimate_run.run_kind != "sampled"
        or estimate_run.status != "sampled_ready"
        or not samples
        or len(samples) != estimate_run.sampled_pages
        or not all(_estimate_sample_attested(sample) for sample in samples)
        or verifier is None
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_PROBE_ATTESTATION_INCOMPLETE"},
        )
    signature_results = [
        await verifier.verify(
            key_id=sample.attestation_key_id,
            attestation=probe_canonical_json(sample.attestation),
            signature=sample.attestation_signature,
        )
        for sample in samples
    ]
    if not all(signature_results):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_PROBE_SIGNATURE_INVALID"},
        )
    estimate_sha = str(preflight.estimate.get("estimate_sha256", ""))
    if estimate_run.estimate_sha256 != estimate_sha:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_ESTIMATE_HASH_MISMATCH"},
        )
    approved_preflight = payload.approved_preflight_sha256 or preflight.output_sha256
    approved_estimate = payload.approved_estimate_sha256 or estimate_sha
    if approved_preflight != preflight.output_sha256 or approved_estimate != estimate_sha:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_APPROVAL_HASH_MISMATCH"},
        )
    blueprint = _approved_blueprint(payload, preflight.estimate)
    approved_collection_reserve_ceiling = _money(estimate_run.reserve_ceiling)
    default_cap = (
        approved_collection_reserve_ceiling * Decimal("1.10")
        if payload.overage_policy == "allow_10_percent"
        else approved_collection_reserve_ceiling
    ).quantize(Decimal("0.000001"))
    submitted_hard_cap = _money(payload.credit_hard_cap or default_cap)
    if payload.overage_policy == "allow_10_percent" and submitted_hard_cap > (
        approved_collection_reserve_ceiling * Decimal("1.10")
    ).quantize(Decimal("0.000001")):
        raise HTTPException(
            status_code=409,
            detail={"code": "CREDIT_HARD_CAP_EXCEEDS_APPROVED_OVERAGE_POLICY"},
        )

    source_file_by_id = {
        source_id: row
        for source_id, row in (
            (
                collection_file.source_file_id,
                collection_file,
            )
            for collection_file in successful
            if collection_file.source_file_id is not None
        )
        if row.status == "verified"
    }
    for collection_file in successful:
        if collection_file.source_file_id is not None:
            source_file_by_id.setdefault(collection_file.source_file_id, collection_file)

    plan_id = uuid.uuid4()
    job_id = uuid.uuid4()
    module_ids = {module: uuid.uuid4() for module in payload.output_modules}
    resume_token = secrets.token_urlsafe(32)
    task_bindings: list[dict[str, str | None]] = []
    task_source_weights: dict[str, int] = {}
    analysis_tasks: list[AnalysisTask] = []
    seen_task_ids: set[uuid.UUID] = set()
    for source_id, document in sorted(documents.items(), key=lambda item: str(item[0])):
        if document.status == "COMPLETED":
            continue
        task = await session.scalar(
            select(AnalysisTask).where(
                AnalysisTask.tenant_id == principal.tenant_id,
                AnalysisTask.document_id == document.id,
                AnalysisTask.document_version == document.active_version,
            )
        )
        if task is None:
            task = AnalysisTask(
                tenant_id=principal.tenant_id,
                project_id=collection.project_id,
                document_id=document.id,
                document_version=document.active_version,
                source_file_id=source_id,
                requested_by=principal.user_id,
                status="queued",
                max_attempts=request.app.state.settings.analysis_max_attempts,
            )
            session.add(task)
            await session.flush()
        if task.status not in {"queued", "running"}:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COLLECTION_ANALYSIS_TASK_NOT_REUSABLE",
                    "task_id": str(task.id),
                    "status": task.status,
                },
            )
        if task.id in seen_task_ids:
            continue
        seen_task_ids.add(task.id)
        binding_file = source_file_by_id[source_id]
        billing_basis_sha256 = _sha256(
            _canonical_json(
                {
                    "analysis_task_id": str(task.id),
                    "document_id": str(task.document_id),
                    "document_version": task.document_version,
                    "source_sha256": binding_file.sha256,
                }
            )
        )
        await _lock_billing_owner_claim(
            session,
            tenant_id=principal.tenant_id,
            task_id=task.id,
            billing_basis_sha256=billing_basis_sha256,
        )
        previous_owner = await session.scalar(
            select(CollectionProcessingTaskBinding)
            .where(
                CollectionProcessingTaskBinding.tenant_id == principal.tenant_id,
                CollectionProcessingTaskBinding.analysis_task_id == task.id,
                CollectionProcessingTaskBinding.billing_disposition == "new_billable",
                CollectionProcessingTaskBinding.billing_basis_sha256 == billing_basis_sha256,
            )
            .order_by(
                CollectionProcessingTaskBinding.created_at, CollectionProcessingTaskBinding.id
            )
            .limit(1)
        )
        reuse_unbillable = binding_file.status == "duplicate" or previous_owner is not None
        owner_job_id = (
            previous_owner.billing_owner_job_id or previous_owner.processing_job_id
            if previous_owner is not None
            else None
            if reuse_unbillable
            else job_id
        )
        task_bindings.append(
            {
                "task_id": str(task.id),
                "document_id": str(document.id),
                "collection_file_id": str(binding_file.id),
                "billing_disposition": ("reuse_unbillable" if reuse_unbillable else "new_billable"),
                "billing_owner_job_id": (str(owner_job_id) if owner_job_id is not None else None),
                "billing_basis_sha256": billing_basis_sha256,
            }
        )
        task_source_weights[str(task.id)] = max(1, int(binding_file.size_bytes))
        analysis_tasks.append(task)

    total_scope_weight = sum(max(1, int(row.size_bytes)) for row in source_file_by_id.values())
    billable_scope_weight = sum(
        task_source_weights[str(binding["task_id"])]
        for binding in task_bindings
        if binding["billing_disposition"] == "new_billable"
    )
    reserve_ceiling = (
        (
            approved_collection_reserve_ceiling
            * Decimal(billable_scope_weight)
            / Decimal(total_scope_weight)
        ).quantize(Decimal("0.000001"), rounding=ROUND_UP)
        if total_scope_weight > 0 and billable_scope_weight > 0
        else Decimal("0.000000")
    )
    hard_cap = submitted_hard_cap
    if hard_cap < reserve_ceiling:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CREDIT_HARD_CAP_BELOW_RESERVE_CEILING",
                "minimum": str(reserve_ceiling),
            },
        )

    current_version = await session.scalar(
        select(func.max(ArchitecturePlan.plan_version)).where(
            ArchitecturePlan.tenant_id == principal.tenant_id,
            ArchitecturePlan.collection_id == collection.id,
        )
    )
    immutable_basis = {
        "schema_version": "1.0",
        "execution_scope": "collection_processing_runtime",
        "collection_id": str(collection.id),
        "project_id": str(collection.project_id),
        "manifest_revision": collection.manifest_revision,
        "manifest_sha256": preflight.input_manifest_hash,
        "preflight_id": str(preflight.id),
        "approved_preflight_sha256": approved_preflight,
        "estimate_run_id": str(estimate_run.id),
        "approved_estimate_sha256": approved_estimate,
        **blueprint,
        "output_modules": [
            {"id": str(module_ids[key]), "module_key": key, "module_version": "1.0"}
            for key in payload.output_modules
        ],
        "credit_hard_cap": str(hard_cap),
        "reserve_ceiling": str(reserve_ceiling),
        "approved_collection_reserve_ceiling": str(approved_collection_reserve_ceiling),
        "billing_scope_weight": billable_scope_weight,
        "collection_scope_weight": total_scope_weight,
        "overage_policy": payload.overage_policy,
        "processing_job_id": str(job_id),
        "analysis_task_ids": [str(task.id) for task in analysis_tasks],
    }
    plan_sha = _sha256(_canonical_json(immutable_basis))
    plan_payload = {**immutable_basis, "immutable_plan_sha256": plan_sha}
    job = ProcessingJob(
        id=job_id,
        tenant_id=principal.tenant_id,
        project_id=collection.project_id,
        document_id=None,
        job_type="collection_processing",
        status="running",
        requested_options={
            **plan_payload,
            "architecture_plan_id": str(plan_id),
            "task_bindings": task_bindings,
            "initiating_user_id": str(principal.user_id),
            "resume_token_hash": _sha256(resume_token.encode("utf-8")),
            "resume_version": 1,
        },
        progress={
            "stage": "processing",
            "total_tasks": len(analysis_tasks),
            "completed_tasks": 0,
            "failed_tasks": 0,
            "terminal_result_ids": [],
        },
        cost_estimate={
            "p50": str(estimate_run.credit_p50),
            "p95": str(estimate_run.credit_p95),
            "reserve_ceiling": str(reserve_ceiling),
            "approved_collection_reserve_ceiling": str(approved_collection_reserve_ceiling),
            "billing_scope_weight": billable_scope_weight,
            "collection_scope_weight": total_scope_weight,
            "hard_cap": str(hard_cap),
            "overage_policy": payload.overage_policy,
        },
        cost_actual={
            "reserved": str(reserve_ceiling),
            "consumed": "0.000000",
            "refunded": "0.000000",
            "released": "0.000000",
            "billable_pages": 0,
            "unbillable_pages": 0,
        },
        started_at=utcnow(),
    )
    session.add(job)
    await session.flush()
    if reserve_ceiling > 0:
        await credit_entry(
            session,
            tenant_id=principal.tenant_id,
            operation_key=f"collection:{job.id}:reserve",
            entry_type="reserve",
            credits=reserve_ceiling,
            job_id=job.id,
            metadata={
                "collection_id": str(collection.id),
                "estimate_sha256": approved_estimate,
                "hard_cap": str(hard_cap),
                "reserve_ceiling": str(reserve_ceiling),
                "approved_collection_reserve_ceiling": str(approved_collection_reserve_ceiling),
                "billing_scope_weight": billable_scope_weight,
                "collection_scope_weight": total_scope_weight,
                "overage_policy": payload.overage_policy,
            },
        )
    plan = ArchitecturePlan(
        id=plan_id,
        tenant_id=principal.tenant_id,
        collection_id=collection.id,
        processing_job_id=job.id,
        plan_version=int(current_version or 0) + 1,
        status="planned",
        input_integrity_sha256=plan_sha,
        plan=plan_payload,
        created_by=principal.user_id,
    )
    session.add(plan)
    for module_key in payload.output_modules:
        session.add(
            BlueprintModule(
                id=module_ids[module_key],
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                architecture_plan_id=plan.id,
                module_key=module_key,
                module_version="1.0",
                status="planned",
                config_json={"knowledge_blueprint_id": blueprint["knowledge_blueprint_id"]},
                output_summary={},
            )
        )
    for task in analysis_tasks:
        binding = next(item for item in task_bindings if item["task_id"] == str(task.id))
        session.add(
            CollectionProcessingTaskBinding(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                processing_job_id=job.id,
                analysis_task_id=task.id,
                collection_file_id=uuid.UUID(binding["collection_file_id"]),
                document_id=task.document_id,
                billing_disposition=str(binding["billing_disposition"]),
                billing_owner_job_id=(
                    uuid.UUID(str(binding["billing_owner_job_id"]))
                    if binding["billing_owner_job_id"] is not None
                    else None
                ),
                billing_basis_sha256=str(binding["billing_basis_sha256"]),
                status="active",
            )
        )
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.tenant_id == principal.tenant_id,
                OutboxEvent.aggregate_id == task.id,
                OutboxEvent.event_type == "document.analysis.requested.v1",
                OutboxEvent.published_at.is_(None),
            )
        )
        event_payload = {
            "task_id": str(task.id),
            "tenant_id": str(principal.tenant_id),
            "document_id": str(task.document_id),
        }
        if event is None:
            session.add(
                OutboxEvent(
                    tenant_id=principal.tenant_id,
                    aggregate_type="analysis_task",
                    aggregate_id=task.id,
                    event_type="document.analysis.requested.v1",
                    payload=event_payload,
                )
            )
        session.add(
            OutboxEvent(
                tenant_id=principal.tenant_id,
                aggregate_type="collection_processing_task_binding",
                aggregate_id=job.id,
                event_type="collection.processing.task.bound.v1",
                payload={
                    "collection_id": str(collection.id),
                    "processing_job_id": str(job.id),
                    "analysis_task_id": str(task.id),
                    "architecture_plan_id": str(plan.id),
                    "immutable_plan_sha256": plan_sha,
                    "billing_disposition": binding["billing_disposition"],
                    "billing_owner_job_id": binding["billing_owner_job_id"],
                    "billing_basis_sha256": binding["billing_basis_sha256"],
                },
            )
        )
        task.available_at = utcnow()
        document = next(item for item in documents.values() if item.id == task.document_id)
        document.status = "ANALYSIS_QUEUED"
    _transition(collection, "PROCESSING", reason="APPROVED_IMMUTABLE_PLAN")
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="architecture.plan.created.v1",
        job_id=job.id,
        payload={
            "collection_id": str(collection.id),
            "architecture_plan_id": str(plan.id),
            "processing_job_id": str(job.id),
            "plan_version": plan.plan_version,
            "integrity_sha256": plan_sha,
            "module_count": len(payload.output_modules),
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="credits.reserved.v1",
        job_id=job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(job.id),
            "credits": str(reserve_ceiling),
            "hard_cap": str(hard_cap),
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="processing.started.v1",
        job_id=job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(job.id),
            "architecture_plan_id": str(plan.id),
            "task_count": len(analysis_tasks),
            "immutable_plan_sha256": plan_sha,
        },
    )
    if not analysis_tasks:
        job.progress = {
            **job.progress,
            "stage": "semantic_compile_queued",
            "partial": False,
        }
        _transition(collection, "VERIFYING_OUTPUT", reason="ZERO_TASK_REUSE_READY")
        session.add(
            OutboxEvent(
                tenant_id=principal.tenant_id,
                aggregate_type="collection_processing",
                aggregate_id=job.id,
                event_type="collection.semantic.compile.requested.v1",
                payload={
                    "tenant_id": str(principal.tenant_id),
                    "collection_id": str(collection.id),
                    "processing_job_id": str(job.id),
                    "architecture_plan_id": str(plan.id),
                    "actor_user_id": str(principal.user_id),
                    "immutable_plan_sha256": plan_sha,
                    "approved_preflight_sha256": approved_preflight,
                    "approved_estimate_sha256": approved_estimate,
                },
            )
        )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.processing_started",
        target_type="processing_job",
        target_id=str(job.id),
        metadata={
            "collection_id": str(collection.id),
            "architecture_plan_id": str(plan.id),
            "immutable_plan_sha256": plan_sha,
            "hard_cap": str(hard_cap),
        },
    )
    await session.commit()
    if request.app.state.settings.local_analysis_worker_enabled:
        from akc_api.main import _execute_local_analysis_task

        for task in analysis_tasks:
            background_tasks.add_task(_execute_local_analysis_task, request.app, task.id)
    return await _architecture_response(session, plan, processing_resume_token=resume_token)


@router.post(
    "/collections/{collection_id}/compile",
    response_model=ArchitecturePlanResponse,
    status_code=201,
)
@idempotent_mutation
async def compile_collection(
    collection_id: uuid.UUID,
    payload: CollectionCompileRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: EditorDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey = None,
) -> ArchitecturePlanResponse:
    _require_idempotency_key(idempotency_key)
    await _require_verified_user(session, principal)
    if (
        payload.mode == "deterministic_existing_artifacts"
        and request.app.state.settings.env == "production"
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "COMPATIBILITY_COMPILE_MODE_FORBIDDEN_IN_PRODUCTION"},
        )
    semantic_indexer: PostgresHybridIndexer | None = None
    semantic_batch_factory: Any = None
    if payload.mode == "collection_processing_runtime":
        candidate_indexer = getattr(
            request.app.state, "collection_semantic_retrieval_indexer", None
        )
        semantic_batch_factory = getattr(
            request.app.state, "collection_semantic_retrieval_batch_factory", None
        )
        if not isinstance(candidate_indexer, PostgresHybridIndexer) or not callable(
            semantic_batch_factory
        ):
            raise HTTPException(
                status_code=503,
                detail={"code": "COLLECTION_SEMANTIC_RUNTIME_UNAVAILABLE"},
            )
        semantic_indexer = candidate_indexer
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="write",
        lock=True,
    )
    existing_plan = await session.scalar(
        select(ArchitecturePlan)
        .where(
            ArchitecturePlan.tenant_id == principal.tenant_id,
            ArchitecturePlan.collection_id == collection.id,
            ArchitecturePlan.status == "compiled",
        )
        .order_by(ArchitecturePlan.plan_version.desc())
        .limit(1)
    )
    if existing_plan is not None:
        existing_modules = set(
            await session.scalars(
                select(BlueprintModule.module_key).where(
                    BlueprintModule.tenant_id == principal.tenant_id,
                    BlueprintModule.architecture_plan_id == existing_plan.id,
                )
            )
        )
        if existing_modules != set(payload.output_modules):
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_COMPILE_PLAN_IMMUTABLE"},
            )
        return await _architecture_response(session, existing_plan)
    planned_plan = await session.scalar(
        select(ArchitecturePlan)
        .where(
            ArchitecturePlan.tenant_id == principal.tenant_id,
            ArchitecturePlan.collection_id == collection.id,
            ArchitecturePlan.status == "planned",
        )
        .order_by(ArchitecturePlan.plan_version.desc())
        .limit(1)
    )
    if planned_plan is not None and collection.status in {"PROCESSING", "PAUSED"}:
        return await _architecture_response(session, planned_plan)
    if collection.status not in {"ESTIMATED", "VERIFYING_OUTPUT"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_NOT_READY_FOR_COMPILE"},
        )
    preflight = await session.scalar(
        select(CollectionPreflight).where(
            CollectionPreflight.tenant_id == principal.tenant_id,
            CollectionPreflight.collection_id == collection.id,
            CollectionPreflight.manifest_revision == collection.manifest_revision,
            CollectionPreflight.status != "stale",
        )
    )
    if preflight is None or preflight.estimate.get("status") != "sampled_ready":
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_ESTIMATE_INCOMPLETE"},
        )
    estimate_run: EstimateRun | None = None
    if payload.mode == "collection_processing_runtime":
        estimate_run = await session.scalar(
            select(EstimateRun)
            .where(
                EstimateRun.tenant_id == principal.tenant_id,
                EstimateRun.collection_id == collection.id,
                EstimateRun.preflight_id == preflight.id,
                EstimateRun.run_kind == "sampled",
                EstimateRun.status == "sampled_ready",
            )
            .order_by(EstimateRun.created_at.desc())
            .limit(1)
        )
        samples = (
            list(
                await session.scalars(
                    select(EstimateSample).where(
                        EstimateSample.tenant_id == principal.tenant_id,
                        EstimateSample.collection_id == collection.id,
                        EstimateSample.estimate_run_id == estimate_run.id,
                    )
                )
            )
            if estimate_run is not None
            else []
        )
        verifier = getattr(request.app.state, "collection_probe_attestation_verifier", None)
        if (
            estimate_run is None
            or not samples
            or len(samples) != estimate_run.sampled_pages
            or not all(_estimate_sample_attested(sample) for sample in samples)
            or verifier is None
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_PROBE_ATTESTATION_INCOMPLETE"},
            )
        signature_results = [
            await verifier.verify(
                key_id=sample.attestation_key_id,
                attestation=probe_canonical_json(sample.attestation),
                signature=sample.attestation_signature,
            )
            for sample in samples
        ]
        if not all(signature_results):
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_PROBE_SIGNATURE_INVALID"},
            )
        estimate_sha = str(preflight.estimate.get("estimate_sha256", ""))
        if estimate_run.estimate_sha256 != estimate_sha:
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_ESTIMATE_HASH_MISMATCH"},
            )
        if (
            payload.approved_preflight_sha256 or preflight.output_sha256
        ) != preflight.output_sha256 or (
            payload.approved_estimate_sha256 or estimate_sha
        ) != estimate_sha:
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_APPROVAL_HASH_MISMATCH"},
            )
    successful = list(
        await session.scalars(
            select(CollectionFile).where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status.in_(_SUCCESS_FILE_STATES),
            )
        )
    )
    source_ids = {row.source_file_id for row in successful if row.source_file_id is not None}
    documents = await _documents_by_source(
        session,
        tenant_id=principal.tenant_id,
        project_id=collection.project_id,
        source_ids=source_ids,
    )
    if len(documents) != len(source_ids):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_DOCUMENT_PROJECTION_MISSING"},
        )
    processing_incomplete = any(document.status != "COMPLETED" for document in documents.values())
    if payload.mode == "collection_processing_runtime" and planned_plan is None:
        assert estimate_run is not None
        if estimate_run is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_SAMPLED_ESTIMATE_REQUIRED"},
            )
        return await _start_collection_processing(
            request=request,
            background_tasks=background_tasks,
            session=session,
            principal=principal,
            collection=collection,
            preflight=preflight,
            estimate_run=estimate_run,
            payload=payload,
            successful=successful,
            documents=documents,
        )
    if processing_incomplete and payload.mode == "collection_processing_runtime":
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_PROCESSING_RESULT_INCOMPLETE"},
        )
    if len(documents) != len(source_ids) or any(
        document.status != "COMPLETED" for document in documents.values()
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_DOCUMENTS_NOT_COMPLETED"},
        )
    document_ids = {document.id for document in documents.values()}
    pages = list(
        await session.scalars(
            select(Page).where(
                Page.tenant_id == principal.tenant_id,
                Page.document_id.in_(document_ids),
            )
        )
    )
    if not pages:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_PAGE_EVIDENCE_MISSING"},
        )
    page_ids = {page.id for page in pages}
    later_attempt = aliased(PageAttempt)
    latest_attempts = list(
        await session.scalars(
            select(PageAttempt).where(
                PageAttempt.tenant_id == principal.tenant_id,
                PageAttempt.page_id.in_(page_ids),
                ~exists(
                    select(1).where(
                        later_attempt.tenant_id == PageAttempt.tenant_id,
                        later_attempt.page_id == PageAttempt.page_id,
                        later_attempt.attempt_number > PageAttempt.attempt_number,
                    )
                ),
            )
        )
    )
    if len(latest_attempts) != len(page_ids) or any(
        attempt.status not in {"COMPLETED", "UNRESOLVED", "QUARANTINED"}
        for attempt in latest_attempts
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_PAGE_VERIFICATION_INCOMPLETE"},
        )
    open_reviews = list(
        await session.scalars(
            select(ReviewItem).where(
                ReviewItem.tenant_id == principal.tenant_id,
                ReviewItem.document_id.in_(document_ids),
                ReviewItem.status == "open",
            )
        )
    )
    files_by_document: dict[uuid.UUID, list[CollectionFile]] = defaultdict(list)
    for collection_file in successful:
        if collection_file.source_file_id is None:
            continue
        document = documents.get(collection_file.source_file_id)
        if document is not None:
            files_by_document[document.id].append(collection_file)
    for review in open_reviews:
        autonomous_status = (
            "quarantined"
            if review.severity.casefold() in {"critical", "high"}
            or "security" in review.category.casefold()
            else "unresolved"
        )
        for collection_file in files_by_document.get(review.document_id, []):
            session.add(
                VerificationRecord(
                    tenant_id=principal.tenant_id,
                    collection_id=collection.id,
                    collection_file_id=collection_file.id,
                    status=autonomous_status,
                    validator_revision="legacy-review-autonomous-isolation-v1",
                    evidence={
                        "review_item_id": str(review.id),
                        "document_id": str(review.document_id),
                        "page_id": str(review.page_id) if review.page_id else None,
                        "scope_status": autonomous_status,
                        "billing": "unbillable",
                    },
                )
            )
            if autonomous_status == "quarantined":
                session.add(
                    QuarantineItem(
                        tenant_id=principal.tenant_id,
                        collection_id=collection.id,
                        collection_file_id=collection_file.id,
                        page_id=review.page_id,
                        reason_code="LEGACY_OPEN_REVIEW_AUTONOMOUSLY_ISOLATED",
                        status="open",
                        evidence={"review_item_id": str(review.id)},
                    )
                )
        review.status = "resolved"
        review.resolution = {
            "strategy": "autonomous_isolation",
            "result": autonomous_status,
            "human_action_required": False,
        }
        review.resolved_by = None
        review.resolved_at = utcnow()

    notes = list(
        await session.scalars(
            select(KnowledgeNote).where(
                KnowledgeNote.tenant_id == principal.tenant_id,
                KnowledgeNote.document_id.in_(document_ids),
                KnowledgeNote.is_active.is_(True),
            )
        )
    )
    note_documents = {
        note.document_id
        for note in notes
        if note.document_id is not None and note.evidence_block_ids
    }
    if note_documents != document_ids:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_EVIDENCE_BOUND_KNOWLEDGE_MISSING"},
        )
    relations = list(
        await session.scalars(
            select(Relation).where(
                Relation.tenant_id == principal.tenant_id,
                Relation.document_id.in_(document_ids),
                Relation.is_active.is_(True),
            )
        )
    )
    relation_count = len(relations)
    invalid_relations = sum(1 for relation in relations if not relation.evidence_block_ids)
    if invalid_relations:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_RELATION_EVIDENCE_MISSING"},
        )
    blocks = list(
        await session.scalars(
            select(Block).where(
                Block.tenant_id == principal.tenant_id,
                Block.document_id.in_(document_ids),
            )
        )
    )
    evidence_block_ids = {str(item.id) for item in blocks}
    project_entities = list(
        await session.scalars(
            select(Entity).where(
                Entity.tenant_id == principal.tenant_id,
                Entity.project_id == collection.project_id,
            )
        )
    )
    entities = [
        entity
        for entity in project_entities
        if evidence_block_ids.intersection(str(item) for item in entity.evidence_block_ids)
    ]
    processing_jobs = list(
        await session.scalars(
            select(ProcessingJob).where(
                ProcessingJob.tenant_id == principal.tenant_id,
                ProcessingJob.document_id.in_(document_ids),
            )
        )
    )
    processing_job_ids = {row.id for row in processing_jobs}
    source_job_events = (
        list(
            await session.scalars(
                select(JobEvent).where(
                    JobEvent.tenant_id == principal.tenant_id,
                    JobEvent.job_id.in_(processing_job_ids),
                )
            )
        )
        if processing_job_ids
        else []
    )
    final_plan_id = planned_plan.id if planned_plan is not None else uuid.uuid4()
    parent_job = (
        await session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.tenant_id == principal.tenant_id,
                ProcessingJob.id == planned_plan.processing_job_id,
            )
        )
        if planned_plan is not None and planned_plan.processing_job_id is not None
        else None
    )
    approved_blueprint = _approved_blueprint(payload, preflight.estimate)
    execution_scope = (
        "collection_processing_runtime"
        if payload.mode == "collection_processing_runtime"
        else "existing_verified_artifacts_only"
    )
    if parent_job is None:
        if payload.mode == "collection_processing_runtime":
            assert estimate_run is not None
            reserve_ceiling = _money(estimate_run.reserve_ceiling)
            default_cap = (
                reserve_ceiling * Decimal("1.10")
                if payload.overage_policy == "allow_10_percent"
                else reserve_ceiling
            ).quantize(Decimal("0.000001"))
            hard_cap = _money(payload.credit_hard_cap or default_cap)
            if hard_cap < reserve_ceiling:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "CREDIT_HARD_CAP_BELOW_RESERVE_CEILING"},
                )
            if payload.overage_policy == "allow_10_percent" and hard_cap > (
                reserve_ceiling * Decimal("1.10")
            ).quantize(Decimal("0.000001")):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "CREDIT_HARD_CAP_EXCEEDS_APPROVED_OVERAGE_POLICY"},
                )
        else:
            reserve_ceiling = Decimal("0.000000")
            hard_cap = Decimal("0.000000")
        parent_job = ProcessingJob(
            tenant_id=principal.tenant_id,
            project_id=collection.project_id,
            document_id=None,
            job_type="collection_processing",
            status=("running" if payload.mode == "collection_processing_runtime" else "completed"),
            requested_options={
                "execution_scope": execution_scope,
                "collection_id": str(collection.id),
                "preflight_id": str(preflight.id),
                "approved_preflight_sha256": preflight.output_sha256,
                "approved_estimate_sha256": str(preflight.estimate["estimate_sha256"]),
                **approved_blueprint,
                "output_modules": list(payload.output_modules),
                "compatibility_reuse": (payload.mode == "deterministic_existing_artifacts"),
                "existing_result_reuse_unbillable": True,
                "overage_policy": payload.overage_policy,
            },
            progress={
                "stage": "verifying_output",
                "total_tasks": 0,
                "completed_tasks": 0,
                "failed_tasks": 0,
                "terminal_result_ids": sorted(str(item) for item in page_ids),
            },
            cost_estimate={
                "reserve_ceiling": str(reserve_ceiling),
                "hard_cap": str(hard_cap),
                "overage_policy": payload.overage_policy,
            },
            cost_actual={
                "reserved": "0.000000",
                "consumed": "0.000000",
                "refunded": "0.000000",
                "released": "0.000000",
                "billable_pages": 0,
                "unbillable_pages": 0,
            },
            started_at=utcnow(),
            completed_at=(utcnow() if payload.mode == "deterministic_existing_artifacts" else None),
        )
        session.add(parent_job)
        await session.flush()

    integrity_basis = {
        "collection_id": str(collection.id),
        "manifest_sha256": preflight.input_manifest_hash,
        "preflight_sha256": preflight.output_sha256,
        "documents": [
            {
                "document_id": str(document.id),
                "active_version": document.active_version,
                "status": document.status,
            }
            for document in sorted(documents.values(), key=lambda item: str(item.id))
        ],
        "page_attempts": [
            {
                "page_id": str(attempt.page_id),
                "attempt_id": str(attempt.id),
                "status": attempt.status,
            }
            for attempt in sorted(latest_attempts, key=lambda item: str(item.page_id))
        ],
        "note_ids": sorted(str(note.id) for note in notes),
        "entity_ids": sorted(str(entity.id) for entity in entities),
        "relation_ids": sorted(str(relation.id) for relation in relations),
        "autonomous_isolation_review_ids": sorted(str(review.id) for review in open_reviews),
    }
    integrity_sha = _sha256(_canonical_json(integrity_basis))
    existing_verifications = {
        row.collection_file_id
        for row in await session.scalars(
            select(VerificationRecord).where(
                VerificationRecord.tenant_id == principal.tenant_id,
                VerificationRecord.collection_id == collection.id,
                VerificationRecord.collection_file_id.is_not(None),
            )
        )
    }
    for row in successful:
        if row.id in existing_verifications:
            continue
        document = documents[cast(uuid.UUID, row.source_file_id)]
        session.add(
            VerificationRecord(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                collection_file_id=row.id,
                status="verified",
                validator_revision="collection-existing-artifacts-v1",
                evidence={
                    "source_file_id": str(row.source_file_id),
                    "source_sha256": row.sha256,
                    "document_id": str(document.id),
                    "document_version": document.active_version,
                    "document_status": document.status,
                    "integrity_sha256": integrity_sha,
                },
            )
        )

    latest_attempt_by_page = {attempt.page_id: attempt for attempt in latest_attempts}
    existing_regions = list(
        await session.scalars(
            select(CollectionRegion).where(
                CollectionRegion.tenant_id == principal.tenant_id,
                CollectionRegion.collection_id == collection.id,
            )
        )
    )
    regions_by_key = {region.stable_key: region for region in existing_regions}
    projected_regions: list[CollectionRegion] = []
    projected_region_attempts: list[CollectionRegionAttempt] = []
    for block in sorted(blocks, key=lambda item: (str(item.document_id), item.block_order)):
        if block.page_id is None or block.page_id not in latest_attempt_by_page:
            continue
        stable_key = f"block:{block.id}"
        if stable_key in regions_by_key:
            continue
        collection_file = min(files_by_document[block.document_id], key=lambda item: str(item.id))
        page_attempt = latest_attempt_by_page[block.page_id]
        region_status = {
            "COMPLETED": "verified",
            "UNRESOLVED": "unresolved",
            "QUARANTINED": "quarantined",
        }[page_attempt.status]
        region = CollectionRegion(
            id=uuid.uuid4(),
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            collection_file_id=collection_file.id,
            document_id=block.document_id,
            page_id=block.page_id,
            stable_key=stable_key,
            region_type=block.block_type,
            bbox1000=block.bbox1000,
            status=region_status,
        )
        session.add(region)
        regions_by_key[stable_key] = region
        projected_regions.append(region)
        region_attempt = CollectionRegionAttempt(
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            region_id=region.id,
            attempt_number=1,
            route=str(next(page.route for page in pages if page.id == block.page_id) or "native"),
            status=region_status,
            validator_summary={
                "source_page_attempt_id": str(page_attempt.id),
                "evidence_block_id": str(block.id),
                "content_hash": block.content_hash,
                "engine": block.engine,
                "engine_revision": block.engine_revision,
                "quality_findings": page_attempt.quality_findings,
            },
            completed_at=page_attempt.completed_at or utcnow(),
        )
        session.add(region_attempt)
        projected_region_attempts.append(region_attempt)
    await session.flush()

    rendered_assets = list(
        await session.scalars(
            select(PageAsset).where(
                PageAsset.tenant_id == principal.tenant_id,
                PageAsset.page_id.in_(page_ids),
                PageAsset.asset_type.in_(("preview", "thumbnail", "inference_raster")),
            )
        )
    )
    authority_mapping_count = int(
        await session.scalar(
            select(func.count(AuthorityMapping.id)).where(
                AuthorityMapping.tenant_id == principal.tenant_id,
                AuthorityMapping.collection_id == collection.id,
                AuthorityMapping.mapping_status == "matched",
            )
        )
        or 0
    )

    if collection.status == "ESTIMATED":
        _transition(collection, "PROCESSING")
    if collection.status == "PROCESSING":
        _transition(collection, "VERIFYING_OUTPUT")
    route_counts = Counter(str(page.route or "unassigned") for page in pages)
    block_type_counts = Counter(block.block_type for block in blocks)
    if planned_plan is None:
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="processing.started.v1",
            job_id=parent_job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(parent_job.id),
                "architecture_plan_id": str(final_plan_id),
                "task_count": 0,
                "documents": len(document_ids),
                "pages": len(pages),
                "processing_jobs": len(processing_jobs),
                "execution_scope": execution_scope,
                "credits_consumed": 0,
                "status": collection.status,
            },
        )
    if source_job_events:
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="processing.source_events.bridged.v1",
            job_id=parent_job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(parent_job.id),
                "processing_jobs": len(processing_jobs),
                "source_event_count": len(source_job_events),
                "source_event_type_counts": dict(
                    sorted(Counter(row.event_type for row in source_job_events).items())
                ),
            },
        )
    if rendered_assets:
        rendered_asset_set_sha256 = _sha256(
            _canonical_json(sorted({asset.sha256 for asset in rendered_assets}))
        )
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="page.rendered.v1",
            job_id=parent_job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(parent_job.id),
                "rendered_page_count": len({asset.page_id for asset in rendered_assets}),
                "rendered_asset_count": len(rendered_assets),
                "asset_type_counts": dict(
                    sorted(Counter(asset.asset_type for asset in rendered_assets).items())
                ),
                "asset_set_sha256": rendered_asset_set_sha256,
            },
        )
    if projected_regions:
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="region.detected.v1",
            job_id=parent_job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(parent_job.id),
                "region_count": len(projected_regions),
                "region_type_counts": dict(
                    sorted(Counter(region.region_type for region in projected_regions).items())
                ),
                "evidence": "persisted_block_projection",
            },
        )
    if projected_region_attempts:
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="region.route.selected.v1",
            job_id=parent_job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(parent_job.id),
                "region_attempt_count": len(projected_region_attempts),
                "route_counts": dict(
                    sorted(Counter(attempt.route for attempt in projected_region_attempts).items())
                ),
            },
        )
    if authority_mapping_count:
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="numeric.authority.verified.v1",
            job_id=parent_job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(parent_job.id),
                "matched_authority_mapping_count": authority_mapping_count,
            },
        )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="page.route.selected.v1",
        job_id=parent_job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(parent_job.id),
            "page_count": len(pages),
            "route_counts": dict(sorted(route_counts.items())),
            "route_policy_versions": sorted(
                {page.route_policy_version for page in pages if page.route_policy_version}
            ),
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="block.completed.v1",
        job_id=parent_job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(parent_job.id),
            "block_count": len(blocks),
            "block_type_counts": dict(sorted(block_type_counts.items())),
            "evidence_bound": len(blocks) > 0,
        },
    )
    if block_type_counts.get("table", 0):
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="table.reconstructed.v1",
            job_id=parent_job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(parent_job.id),
                "table_count": block_type_counts["table"],
                "source": "persisted_verified_blocks",
            },
        )
    if open_reviews:
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="output.quarantined.v1",
            job_id=parent_job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(parent_job.id),
                "isolated_review_count": len(open_reviews),
                "isolation_status_counts": dict(
                    sorted(
                        Counter(
                            "quarantined"
                            if review.severity.casefold() in {"critical", "high"}
                            or "security" in review.category.casefold()
                            else "unresolved"
                            for review in open_reviews
                        ).items()
                    )
                ),
                "billing": "unbillable",
            },
        )
    current_version = await session.scalar(
        select(func.max(ArchitecturePlan.plan_version)).where(
            ArchitecturePlan.tenant_id == principal.tenant_id,
            ArchitecturePlan.collection_id == collection.id,
        )
    )
    plan_directories = [
        "source/",
        "canonical/",
        "architecture/",
        "knowledge/",
        "integrity/",
        "provenance/",
        "validation/",
    ]
    existing_module_rows = (
        list(
            await session.scalars(
                select(BlueprintModule).where(
                    BlueprintModule.tenant_id == principal.tenant_id,
                    BlueprintModule.architecture_plan_id == planned_plan.id,
                )
            )
        )
        if planned_plan is not None
        else []
    )
    direct_module_ids = {module_key: uuid.uuid4() for module_key in payload.output_modules}
    output_module_bindings = [
        {
            "id": str(
                next(
                    (row.id for row in existing_module_rows if row.module_key == module_key),
                    direct_module_ids[module_key],
                )
            ),
            "module_key": module_key,
            "module_version": "1.0",
        }
        for module_key in payload.output_modules
    ]
    compile_projection = {
        "document_ids": sorted(str(item) for item in document_ids),
        "directories": plan_directories,
        "counts": {
            "verified_collection_files": len(successful),
            "unique_source_files": len(source_ids),
            "documents": len(document_ids),
            "pages": len(pages),
            "knowledge_notes": len(notes),
            "entities": len(entities),
            "relations": relation_count,
            "autonomously_isolated_legacy_reviews": len(open_reviews),
        },
        "output_integrity_sha256": integrity_sha,
    }
    output_counts: dict[str, dict[str, Any]] = {
        "source_index": {"verified_files": len(successful)},
        "document_catalog": {"documents": len(document_ids), "pages": len(pages)},
        "knowledge_notes": {"notes": len(notes)},
        "entities": {"entities": len(entities), "scope": "collection_evidence_blocks"},
        "relations": {"relations": relation_count},
        "integrity": {"integrity_sha256": integrity_sha},
        "export_manifest": {"status": "ready_for_repository_manifest"},
    }
    if planned_plan is not None:
        plan = planned_plan
    else:
        plan_payload = {
            "schema_version": "1.0",
            "execution_scope": execution_scope,
            "network_access": False,
            "code_execution": False,
            "collection_id": str(collection.id),
            "project_id": str(collection.project_id),
            "manifest_revision": collection.manifest_revision,
            "manifest_sha256": preflight.input_manifest_hash,
            "preflight_id": str(preflight.id),
            "approved_preflight_sha256": preflight.output_sha256,
            "approved_estimate_sha256": str(preflight.estimate["estimate_sha256"]),
            **approved_blueprint,
            "output_modules": output_module_bindings,
            "processing_job_id": str(parent_job.id),
            "compile_output": compile_projection,
            "limitations": (
                [
                    "Compatibility lane reused existing verified artifacts.",
                    "Package signing requires an external approved Ed25519 signer.",
                ]
                if payload.mode == "deterministic_existing_artifacts"
                else []
            ),
        }
        plan_integrity_sha = _sha256(_canonical_json(plan_payload))
        plan = ArchitecturePlan(
            id=final_plan_id,
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            processing_job_id=parent_job.id,
            plan_version=int(current_version or 0) + 1,
            status="planned",
            input_integrity_sha256=plan_integrity_sha,
            plan=plan_payload,
            created_by=principal.user_id,
        )
        session.add(plan)
        await session.flush()
        parent_job.requested_options = {
            **parent_job.requested_options,
            "architecture_plan_id": str(plan.id),
            "immutable_plan_sha256": plan_integrity_sha,
        }
    modules_by_key = {row.module_key: row for row in existing_module_rows}
    for module_key in payload.output_modules:
        if module_key in modules_by_key:
            modules_by_key[module_key].status = "compiled"
            modules_by_key[module_key].output_summary = output_counts[module_key]
            continue
        module = BlueprintModule(
            id=direct_module_ids[module_key],
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            architecture_plan_id=plan.id,
            module_key=module_key,
            module_version="1.0",
            status="compiled",
            config_json={
                "declarative": True,
                "network_access": False,
                "code_execution": False,
                "knowledge_blueprint_id": approved_blueprint["knowledge_blueprint_id"],
            },
            output_summary=output_counts[module_key],
        )
        session.add(module)
        existing_module_rows.append(module)
        modules_by_key[module_key] = module
    await session.flush()

    semantic_result = None
    semantic_exception_reason: str | None = None
    if payload.mode == "collection_processing_runtime":
        assert semantic_indexer is not None
        try:
            compile_input = await load_collection_semantic_compile_input(
                session,
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                project_id=collection.project_id,
                architecture_plan_id=plan.id,
                document_ids=tuple(document_ids),
            )
            prepared = prepare_collection_semantic_runtime(compile_input)
            retrieval_batch: RetrievalIndexBatch | None = None
            if prepared.ready_for_index:
                batch_candidate = cast(Any, semantic_batch_factory)(prepared)
                if inspect.isawaitable(batch_candidate):
                    batch_candidate = await batch_candidate
                if not isinstance(batch_candidate, RetrievalIndexBatch):
                    raise ValueError("collection retrieval batch is invalid")
                retrieval_batch = batch_candidate
            semantic_result = await run_collection_semantic_runtime(
                session,
                compile_input=compile_input,
                retrieval_indexer=semantic_indexer,
                retrieval_batch=retrieval_batch,
                processing_job_id=parent_job.id,
            )
        except ProviderAttestationError:
            semantic_exception_reason = "retrieval_provider_attestation_failed"
        except RetrievalUnavailable:
            semantic_exception_reason = "retrieval_provider_unavailable"
        except ValueError:
            semantic_exception_reason = "semantic_runtime_input_invalid"
        if semantic_exception_reason is not None or not (
            semantic_result is not None
            and semantic_result.accepted
            and semantic_result.retrieval_receipt is not None
            and semantic_result.outbox_event is not None
        ):
            semantic_state = (
                semantic_result.state.value if semantic_result is not None else "unresolved"
            )
            semantic_reason_codes = (
                list(semantic_result.reason_codes)
                if semantic_result is not None
                else [semantic_exception_reason or "semantic_runtime_failed_closed"]
            )
            plan.status = "failed"
            plan.plan = {
                **plan.plan,
                "semantic_runtime_failure": {
                    "state": semantic_state,
                    "reason_codes": semantic_reason_codes,
                },
            }
            for module in existing_module_rows:
                module.status = "failed"
            actual = dict(parent_job.cost_actual or {})
            consumed = _money(actual.get("consumed"))
            refunded = _money(actual.get("refunded"))
            reimbursement = max(Decimal("0"), consumed - refunded)
            if reimbursement > 0:
                await credit_entry(
                    session,
                    tenant_id=principal.tenant_id,
                    operation_key=f"collection:{parent_job.id}:semantic-refund",
                    entry_type="refund",
                    credits=reimbursement,
                    job_id=parent_job.id,
                    metadata={
                        "collection_id": str(collection.id),
                        "reason": "semantic_or_authority_gate_rejected",
                        "reason_codes": semantic_reason_codes,
                    },
                )
                refunded += reimbursement
                actual["refunded"] = str(refunded)
                parent_job.cost_actual = actual
                await _emit_collection_event(
                    session,
                    collection=collection,
                    event_type="credits.refunded.v1",
                    job_id=parent_job.id,
                    payload={
                        "collection_id": str(collection.id),
                        "processing_job_id": str(parent_job.id),
                        "credits": str(reimbursement),
                        "reason": "semantic_or_authority_gate_rejected",
                    },
                )
            parent_job.status = "failed"
            parent_job.completed_at = utcnow()
            parent_job.progress = {
                **parent_job.progress,
                "stage": "semantic_failed",
                "semantic_state": semantic_state,
                "semantic_reason_codes": semantic_reason_codes,
            }
            parent_job.error = {
                "code": "COLLECTION_SEMANTIC_RUNTIME_REJECTED",
                "reason_codes": semantic_reason_codes,
            }
            target_state = (
                "QUARANTINED" if semantic_state in {"quarantined", "rejected"} else "UNRESOLVED"
            )
            _transition(collection, target_state, reason="SEMANTIC_RUNTIME_REJECTED")
            session.add(
                KnowledgeCompileRun(
                    tenant_id=principal.tenant_id,
                    collection_id=collection.id,
                    architecture_plan_id=plan.id,
                    input_integrity_sha256=integrity_sha,
                    compiler_revision="collection-semantic-runtime-v1",
                    mode=payload.mode,
                    status="failed",
                    note_count=len(notes),
                    relation_count=relation_count,
                    output_sha256=None,
                    limitations=semantic_reason_codes,
                    completed_at=utcnow(),
                )
            )
            await _emit_collection_event(
                session,
                collection=collection,
                event_type="verification.failed.v1",
                job_id=parent_job.id,
                payload={
                    "collection_id": str(collection.id),
                    "processing_job_id": str(parent_job.id),
                    "architecture_plan_id": str(plan.id),
                    "state": semantic_state,
                    "reason_codes": semantic_reason_codes,
                },
            )
            await _emit_collection_event(
                session,
                collection=collection,
                event_type="processing.failed.v1",
                job_id=parent_job.id,
                payload={
                    "collection_id": str(collection.id),
                    "processing_job_id": str(parent_job.id),
                    "error_code": "COLLECTION_SEMANTIC_RUNTIME_REJECTED",
                },
            )
            await audit(
                session,
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                action="collection.semantic_runtime_rejected",
                target_type="architecture_plan",
                target_id=str(plan.id),
                metadata={
                    "collection_id": str(collection.id),
                    "state": semantic_state,
                    "reason_codes": semantic_reason_codes,
                    "refunded": str(reimbursement),
                },
            )
            await session.commit()
            return await _architecture_response(session, plan)
        plan.plan = semantic_result.architecture_plan
        compile_output_sha = semantic_result.canonical_model_sha256.removeprefix("sha256:")
    else:
        plan.plan = {**plan.plan, "compile_output": compile_projection}
        compile_output_sha = _sha256(
            _canonical_json(
                {
                    "architecture_plan_id": str(plan.id),
                    "integrity_sha256": integrity_sha,
                    "note_ids": sorted(str(note.id) for note in notes),
                    "entity_ids": sorted(str(entity.id) for entity in entities),
                    "relation_ids": sorted(str(relation.id) for relation in relations),
                }
            )
        )
    plan.status = "compiled"
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="note.created.v1",
        job_id=parent_job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(parent_job.id),
            "note_count": len(notes),
            "evidence_bound": all(bool(note.evidence_block_ids) for note in notes),
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="entity.resolved.v1",
        job_id=parent_job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(parent_job.id),
            "entity_count": len(entities),
            "scope": "collection_evidence_blocks",
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="relation.created.v1",
        job_id=parent_job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(parent_job.id),
            "relation_count": relation_count,
            "evidence_bound": invalid_relations == 0,
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="architecture.plan.created.v1",
        job_id=parent_job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(parent_job.id),
            "architecture_plan_id": str(plan.id),
            "plan_version": plan.plan_version,
            "integrity_sha256": integrity_sha,
            "module_count": len(payload.output_modules),
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="architecture.folder.created.v1",
        job_id=parent_job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(parent_job.id),
            "architecture_plan_id": str(plan.id),
            "folder_count": len(plan_directories),
            "declarative": True,
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="architecture.moc.created.v1",
        job_id=parent_job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(parent_job.id),
            "architecture_plan_id": str(plan.id),
            "moc_count": 1,
            "linked_note_count": len(notes),
        },
    )
    for module_key in payload.output_modules:
        compiled_module = modules_by_key.get(module_key)
        assert compiled_module is not None
        compiled_module.status = "compiled"
        compiled_module.output_summary = output_counts[module_key]
    session.add(
        KnowledgeCompileRun(
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            architecture_plan_id=plan.id,
            input_integrity_sha256=integrity_sha,
            compiler_revision=(
                "collection-semantic-runtime-v1"
                if payload.mode == "collection_processing_runtime"
                else "existing-evidence-compiler-v1"
            ),
            mode=payload.mode,
            status=(
                "completed"
                if payload.mode == "collection_processing_runtime" or not open_reviews
                else "partial"
            ),
            note_count=len(notes),
            relation_count=relation_count,
            output_sha256=compile_output_sha,
            limitations=(
                list(semantic_result.reason_codes)
                if semantic_result is not None
                else ["Legacy review evidence was autonomously isolated as unbillable scope."]
                if open_reviews
                else []
            ),
            completed_at=utcnow(),
        )
    )
    _transition(collection, "VERIFYING_OUTPUT")
    _transition(collection, "KNOWLEDGE_COMPILING")
    if payload.mode == "collection_processing_runtime":
        parent_job.status = "running"
        parent_job.completed_at = None
        parent_job.progress = {
            **parent_job.progress,
            "stage": "ready_for_packaging",
            "semantic_state": semantic_result.state.value if semantic_result else None,
            "canonical_model_sha256": (
                semantic_result.canonical_model_sha256 if semantic_result else None
            ),
        }
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="architecture.plan.compiled.v1",
        job_id=parent_job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(parent_job.id),
            "architecture_plan_id": str(plan.id),
            "plan_version": plan.plan_version,
            "integrity_sha256": integrity_sha,
            "verified_files": len(successful),
            "documents": len(document_ids),
            "pages": len(pages),
            "knowledge_notes": len(notes),
            "entities": len(entities),
            "relations": relation_count,
            "autonomously_isolated_legacy_reviews": len(open_reviews),
            "credits_consumed": str(parent_job.cost_actual.get("consumed", "0")),
            "status": collection.status,
        },
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.architecture_compiled",
        target_type="architecture_plan",
        target_id=str(plan.id),
        metadata={
            "collection_id": str(collection.id),
            "integrity_sha256": integrity_sha,
            "execution_scope": "existing_verified_artifacts_only",
        },
    )
    await session.commit()
    return await _architecture_response(session, plan)


async def _collection_knowledge_projection(
    session: AsyncSession,
    *,
    collection: Collection,
) -> CollectionKnowledgeResponse:
    successful = list(
        await session.scalars(
            select(CollectionFile).where(
                CollectionFile.tenant_id == collection.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status.in_(_SUCCESS_FILE_STATES),
                CollectionFile.source_file_id.is_not(None),
            )
        )
    )
    source_ids = {cast(uuid.UUID, row.source_file_id) for row in successful}
    documents = await _documents_by_source(
        session,
        tenant_id=collection.tenant_id,
        project_id=collection.project_id,
        source_ids=source_ids,
    )
    document_ids = {document.id for document in documents.values()}
    plan = await session.scalar(
        select(ArchitecturePlan)
        .where(
            ArchitecturePlan.tenant_id == collection.tenant_id,
            ArchitecturePlan.collection_id == collection.id,
            ArchitecturePlan.status == "compiled",
        )
        .order_by(ArchitecturePlan.plan_version.desc())
        .limit(1)
    )
    if not document_ids:
        return CollectionKnowledgeResponse(
            collection_id=collection.id,
            architecture_plan_id=plan.id if plan else None,
            document_ids=[],
            notes=[],
            entities=[],
            relations=[],
            note_count=0,
            entity_count=0,
            relation_count=0,
            ready_for_package=False,
            limitations=["No verified document projection is available."],
        )
    note_count = int(
        await session.scalar(
            select(func.count(KnowledgeNote.id)).where(
                KnowledgeNote.tenant_id == collection.tenant_id,
                KnowledgeNote.document_id.in_(document_ids),
                KnowledgeNote.is_active.is_(True),
            )
        )
        or 0
    )
    relation_count = int(
        await session.scalar(
            select(func.count(Relation.id)).where(
                Relation.tenant_id == collection.tenant_id,
                Relation.document_id.in_(document_ids),
                Relation.is_active.is_(True),
            )
        )
        or 0
    )
    notes = list(
        await session.scalars(
            select(KnowledgeNote)
            .where(
                KnowledgeNote.tenant_id == collection.tenant_id,
                KnowledgeNote.document_id.in_(document_ids),
                KnowledgeNote.is_active.is_(True),
            )
            .order_by(KnowledgeNote.document_id, KnowledgeNote.stable_key)
            .limit(1_000)
        )
    )
    relations = list(
        await session.scalars(
            select(Relation)
            .where(
                Relation.tenant_id == collection.tenant_id,
                Relation.document_id.in_(document_ids),
                Relation.is_active.is_(True),
            )
            .order_by(Relation.document_id, Relation.id)
            .limit(1_000)
        )
    )
    evidence_block_ids = {
        str(item)
        for item in await session.scalars(
            select(Block.id).where(
                Block.tenant_id == collection.tenant_id,
                Block.document_id.in_(document_ids),
            )
        )
    }
    project_entities = list(
        await session.scalars(
            select(Entity).where(
                Entity.tenant_id == collection.tenant_id,
                Entity.project_id == collection.project_id,
            )
        )
    )
    entities = [
        entity
        for entity in project_entities
        if evidence_block_ids.intersection(str(item) for item in entity.evidence_block_ids)
    ]
    entity_count = len(entities)
    limitations = [
        "Projection includes document-bound active notes and relations only.",
        "Project-scoped entities are filtered through collection-owned evidence block IDs.",
    ]
    if note_count > len(notes) or relation_count > len(relations):
        limitations.append("Projection items are capped at 1,000 per record type.")
    evidence_complete = all(note.evidence_block_ids for note in notes) and all(
        relation.evidence_block_ids for relation in relations
    )
    return CollectionKnowledgeResponse(
        collection_id=collection.id,
        architecture_plan_id=plan.id if plan else None,
        document_ids=sorted(document_ids, key=str),
        notes=[
            KnowledgeNoteProjection(
                id=row.id,
                document_id=cast(uuid.UUID, row.document_id),
                stable_key=row.stable_key,
                title=row.title,
                note_type=row.note_type,
                content_origin=row.content_origin,
                review_status=row.review_status,
                evidence_block_ids=row.evidence_block_ids,
            )
            for row in notes
        ],
        entities=[
            EntityProjection(
                id=row.id,
                stable_key=row.stable_key,
                entity_type=row.entity_type,
                label=row.label,
                evidence_block_ids=row.evidence_block_ids,
            )
            for row in entities
        ],
        relations=[
            RelationProjection(
                id=row.id,
                document_id=cast(uuid.UUID, row.document_id),
                subject_id=row.subject_id,
                predicate=row.predicate,
                object_id=row.object_id,
                assertion_status=row.assertion_status,
                review_status=row.review_status,
                evidence_block_ids=row.evidence_block_ids,
            )
            for row in relations
        ],
        note_count=note_count,
        entity_count=entity_count,
        relation_count=relation_count,
        ready_for_package=(
            plan is not None
            and evidence_complete
            and note_count == len(notes)
            and relation_count == len(relations)
        ),
        limitations=limitations,
    )


@router.get(
    "/collections/{collection_id}/knowledge",
    response_model=CollectionKnowledgeResponse,
)
async def get_collection_knowledge(
    collection_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> CollectionKnowledgeResponse:
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="read",
    )
    return await _collection_knowledge_projection(session, collection=collection)


def _package_file_response(row: PackageFile) -> PackageFileResponse:
    return PackageFileResponse(
        path=row.path,
        role=row.role,
        media_type=row.media_type,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
    )


async def _existing_package_response(
    session: AsyncSession,
    package: PackageManifest,
) -> CollectionExportResponse:
    if package.export_id is None or package.package_sha256 is None or package.size_bytes is None:
        raise HTTPException(status_code=409, detail={"code": "COLLECTION_PACKAGE_CORRUPT"})
    export = await session.get(Export, package.export_id)
    if (
        export is None
        or export.tenant_id != package.tenant_id
        or export.status != "completed"
        or export.storage_key is None
    ):
        raise HTTPException(status_code=409, detail={"code": "COLLECTION_PACKAGE_CORRUPT"})
    files = list(
        await session.scalars(
            select(PackageFile)
            .where(
                PackageFile.tenant_id == package.tenant_id,
                PackageFile.collection_id == package.collection_id,
                PackageFile.package_manifest_id == package.id,
            )
            .order_by(PackageFile.path)
        )
    )
    return CollectionExportResponse(
        export_id=export.id,
        package_manifest_id=package.id,
        collection_id=package.collection_id,
        status="completed",
        profile=cast(Any, package.profile),
        download_url=f"/v1/exports/{export.id}/download",
        sha256=package.package_sha256,
        size_bytes=package.size_bytes,
        signature_status=cast(Any, package.signature_status),
        completion_scope=(
            "complete_knowledge_package"
            if package.profile == "complete_knowledge_v1"
            else "repository_manifest_only"
        ),
        files=[_package_file_response(row) for row in files],
        warnings=package.warnings,
    )


def _package_readme(collection: Collection) -> bytes:
    return (
        "# FOLYNTA Collection Repository Manifest\n\n"
        "This package is a deterministic repository-local manifest over existing "
        "server-verified document and knowledge artifacts.\n\n"
        "It does not claim a complete signed ontology, Neo4j import, or production "
        "retrieval package. See `validation/limitations.json` before use.\n\n"
        f"Collection ID: `{collection.id}`\n"
        f"Manifest revision: `{collection.manifest_revision}`\n"
    ).encode()


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(_canonical_json(row) for row in rows)


def _csv_bytes(header: list[str], rows: list[list[Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _turtle_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


async def _complete_knowledge_groups(
    session: AsyncSession,
    *,
    codec: CollectionMetadataCodec,
    collection: Collection,
    plan: ArchitecturePlan,
    collection_files: list[CollectionFile],
    event_rows: list[CollectionEvent],
    integrity: dict[str, Any],
) -> tuple[dict[str, dict[str, bytes]], dict[str, int]]:
    decision_projection = await load_integrity_decision_projection(
        session,
        tenant_id=collection.tenant_id,
        collection_id=collection.id,
    )
    collection_files = [
        row
        for row in collection_files
        if row.id not in decision_projection.excluded_collection_file_ids
    ]
    source_ids = {
        row.source_file_id
        for row in collection_files
        if row.status in _SUCCESS_FILE_STATES and row.source_file_id is not None
    }
    documents_by_source = await _documents_by_source(
        session,
        tenant_id=collection.tenant_id,
        project_id=collection.project_id,
        source_ids=source_ids,
    )
    documents = sorted(
        (
            row
            for row in documents_by_source.values()
            if row.id not in decision_projection.excluded_document_ids
        ),
        key=lambda row: str(row.id),
    )
    document_ids = {row.id for row in documents}
    pages = list(
        await session.scalars(
            select(Page)
            .where(
                Page.tenant_id == collection.tenant_id,
                Page.document_id.in_(document_ids),
            )
            .order_by(Page.document_id, Page.page_number)
        )
    )
    pages = [row for row in pages if row.id not in decision_projection.excluded_page_ids]
    page_ids = {row.id for row in pages}
    blocks = list(
        await session.scalars(
            select(Block)
            .where(
                Block.tenant_id == collection.tenant_id,
                Block.document_id.in_(document_ids),
            )
            .order_by(Block.document_id, Block.block_order, Block.id)
        )
    )
    blocks = [
        row
        for row in blocks
        if row.id not in decision_projection.excluded_block_ids and row.page_id in page_ids
    ]
    if decision_projection.excluded_region_ids:
        excluded_regions = list(
            await session.scalars(
                select(CollectionRegion).where(
                    CollectionRegion.tenant_id == collection.tenant_id,
                    CollectionRegion.collection_id == collection.id,
                    CollectionRegion.id.in_(decision_projection.excluded_region_ids),
                )
            )
        )

        def intersects(left: object, right: object) -> bool:
            if (
                not isinstance(left, (list, tuple))
                or not isinstance(right, (list, tuple))
                or len(left) != 4
                or len(right) != 4
                or any(
                    not isinstance(value, (int, float)) or isinstance(value, bool)
                    for value in (*left, *right)
                )
            ):
                return False
            lx0, ly0, lx1, ly1 = (float(value) for value in left)
            rx0, ry0, rx1, ry1 = (float(value) for value in right)
            return lx0 < rx1 and lx1 > rx0 and ly0 < ry1 and ly1 > ry0

        blocks = [
            row
            for row in blocks
            if not any(
                region.page_id == row.page_id and intersects(row.bbox1000, region.bbox1000)
                for region in excluded_regions
            )
        ]
    collection_block_ids = {str(row.id) for row in blocks}
    notes = list(
        await session.scalars(
            select(KnowledgeNote)
            .where(
                KnowledgeNote.tenant_id == collection.tenant_id,
                KnowledgeNote.document_id.in_(document_ids),
                KnowledgeNote.is_active.is_(True),
            )
            .order_by(KnowledgeNote.document_id, KnowledgeNote.stable_key)
        )
    )
    relations = list(
        await session.scalars(
            select(Relation)
            .where(
                Relation.tenant_id == collection.tenant_id,
                Relation.document_id.in_(document_ids),
                Relation.is_active.is_(True),
            )
            .order_by(Relation.document_id, Relation.id)
        )
    )
    notes = [
        row
        for row in notes
        if collection_block_ids.intersection(str(item) for item in row.evidence_block_ids)
    ]
    relations = [
        row
        for row in relations
        if collection_block_ids.intersection(str(item) for item in row.evidence_block_ids)
    ]
    project_entities = list(
        await session.scalars(
            select(Entity)
            .where(
                Entity.tenant_id == collection.tenant_id,
                Entity.project_id == collection.project_id,
            )
            .order_by(Entity.stable_key)
        )
    )
    entities = [
        row
        for row in project_entities
        if collection_block_ids.intersection(str(item) for item in row.evidence_block_ids)
    ]
    page_number_by_id = {row.id: row.page_number for row in pages}
    overridden_block_ids = {
        str(row.id)
        for row in blocks
        if row.id in decision_projection.overridden_block_ids
        or row.page_id in decision_projection.overridden_page_ids
        or row.document_id in decision_projection.overridden_document_ids
    }
    decision_receipts = list(decision_projection.receipts)
    decision_set_sha256 = _sha256(_canonical_json(decision_receipts))

    def projected_evidence(values: Sequence[str]) -> list[str]:
        return sorted(
            {str(item) for item in values if str(item) in collection_block_ids}
        )

    def projected_review_status(status: str, values: Sequence[str]) -> str:
        return (
            "verified_with_warning"
            if overridden_block_ids.intersection(projected_evidence(values))
            else status
        )

    canonical_model = {
        "schema_version": "1.0",
        "collection_id": str(collection.id),
        "project_id": str(collection.project_id),
        "manifest_revision": collection.manifest_revision,
        "integrity_decisions": decision_receipts,
        "integrity_decision_set_sha256": decision_set_sha256,
        "architecture_plan": {
            "id": str(plan.id),
            "version": plan.plan_version,
            "input_integrity_sha256": plan.input_integrity_sha256,
            "plan": plan.plan,
        },
        "documents": [
            {
                "id": str(row.id),
                "source_file_id": str(row.source_file_id) if row.source_file_id else None,
                "title": row.title,
                "document_type": row.document_type,
                "page_count": row.page_count,
                "active_version": row.active_version,
                "status": row.status,
            }
            for row in documents
        ],
        "blocks": [
            {
                "id": str(row.id),
                "document_id": str(row.document_id),
                "page_id": str(row.page_id) if row.page_id else None,
                "block_order": row.block_order,
                "block_type": row.block_type,
                "origin": row.origin,
                "text": row.normalized_text or row.markdown or row.source_text or "",
                "structured_content": row.structured_content,
                "content_hash": row.content_hash,
                "verification_state": (
                    "verified_with_warning"
                    if str(row.id) in overridden_block_ids
                    else "source_verified"
                ),
            }
            for row in blocks
        ],
        "notes": [
            {
                "id": str(row.id),
                "document_id": str(row.document_id),
                "stable_key": row.stable_key,
                "title": row.title,
                "note_type": row.note_type,
                "content_markdown": row.content_markdown,
                "content_origin": row.content_origin,
                "review_status": projected_review_status(
                    row.review_status,
                    row.evidence_block_ids,
                ),
                "evidence_block_ids": projected_evidence(row.evidence_block_ids),
            }
            for row in notes
        ],
        "entities": [
            {
                "id": str(row.id),
                "stable_key": row.stable_key,
                "entity_type": row.entity_type,
                "label": row.label,
                "evidence_block_ids": projected_evidence(row.evidence_block_ids),
            }
            for row in entities
        ],
        "relations": [
            {
                "id": str(row.id),
                "document_id": str(row.document_id) if row.document_id else None,
                "subject_id": row.subject_id,
                "predicate": row.predicate,
                "object_id": row.object_id,
                "assertion_status": row.assertion_status,
                "review_status": projected_review_status(
                    row.review_status,
                    row.evidence_block_ids,
                ),
                "evidence_block_ids": projected_evidence(row.evidence_block_ids),
            }
            for row in relations
        ],
    }

    obsidian: dict[str, bytes] = {
        "Home.md": (
            "# FOLYNTA Knowledge Package\n\n"
            f"Collection `{collection.id}`\n\n"
            "## Notes\n\n" + "".join(f"- [[notes/{row.id}|{row.title}]]\n" for row in notes)
        ).encode("utf-8")
    }
    for note_row in notes:
        obsidian[f"notes/{note_row.id}.md"] = (
            f"---\nakc_id: {note_row.id}\ndocument_id: {note_row.document_id}\n"
            f"note_type: {note_row.note_type}\n---\n\n# {note_row.title}\n\n"
            f"{note_row.content_markdown}\n"
        ).encode()

    ttl_lines = [
        "@prefix sk: <urn:akc:> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix prov: <http://www.w3.org/ns/prov#> .",
        "",
    ]
    for entity_row in entities:
        ttl_lines.append(
            f"<urn:akc:entity:{entity_row.id}> a sk:Entity ; "
            f"rdfs:label {_turtle_literal(entity_row.label)} ."
        )
    for note_row in notes:
        ttl_lines.append(
            f"<urn:akc:note:{note_row.id}> a sk:KnowledgeNote ; "
            f"rdfs:label {_turtle_literal(note_row.title)} ."
        )
    for relation_row in relations:
        ttl_lines.append(
            f"<urn:akc:relation:{relation_row.id}> a sk:Relation ; "
            f"sk:predicate {_turtle_literal(relation_row.predicate)} ."
        )
    knowledge_ttl = ("\n".join(ttl_lines) + "\n").encode("utf-8")
    jsonld_graph = [
        {
            "@id": f"urn:akc:entity:{row.id}",
            "@type": "Entity",
            "label": row.label,
            "evidence": projected_evidence(row.evidence_block_ids),
        }
        for row in entities
    ] + [
        {
            "@id": f"urn:akc:note:{row.id}",
            "@type": "KnowledgeNote",
            "label": row.title,
            "evidence": projected_evidence(row.evidence_block_ids),
        }
        for row in notes
    ]

    graph_nodes = (
        [[str(row.id), "Document", row.title, str(row.id)] for row in documents]
        + [[str(row.id), "KnowledgeNote", row.title, str(row.document_id)] for row in notes]
        + [[str(row.id), "Entity", row.label, ""] for row in entities]
    )
    graph_relationships = [
        [str(row.id), row.subject_id, row.predicate, row.object_id, str(row.document_id or "")]
        for row in relations
    ]

    rag_documents = [
        {
            "document_id": str(row.id),
            "title": row.title,
            "document_type": row.document_type,
            "active_version": row.active_version,
        }
        for row in documents
    ]
    rag_chunks = [
        {
            "chunk_id": str(row.id),
            "document_id": str(row.document_id),
            "page_number": page_number_by_id.get(row.page_id) if row.page_id else None,
            "block_type": row.block_type,
            "text": row.normalized_text or row.markdown or row.source_text or "",
        }
        for row in blocks
    ]
    rag_metadata = [
        {
            "chunk_id": str(row.id),
            "origin": row.origin,
            "engine": row.engine,
            "engine_revision": row.engine_revision,
            "confidence": row.confidence,
        }
        for row in blocks
    ]
    rag_evidence = [
        {
            "chunk_id": str(row.id),
            "evidence_block_id": str(row.id),
            "content_hash": row.content_hash,
            "document_id": str(row.document_id),
        }
        for row in blocks
    ]
    provenance_activities = [
        {
            "activity_id": str(row.id),
            "sequence": row.sequence,
            "type": row.event_type,
            "occurred_at": row.occurred_at.isoformat(),
            "payload": row.payload,
        }
        for row in event_rows
    ]
    counts = {
        "documents": len(documents),
        "pages": len(pages),
        "blocks": len(blocks),
        "notes": len(notes),
        "entities": len(entities),
        "relations": len(relations),
    }
    validation_report = {
        "schema_version": "1.0",
        "status": "passed_with_disclosed_isolation"
        if integrity["verification_status_counts"].get("unresolved", 0)
        or integrity["verification_status_counts"].get("quarantined", 0)
        else "passed",
        "counts": counts,
        "integrity_sha256": integrity["integrity_sha256"],
        "integrity_decision_set_sha256": decision_set_sha256,
        "integrity_decision_count": len(decision_receipts),
        "verification_status_counts": integrity["verification_status_counts"],
        "signature_status": "external_signer_required",
        "checks": {
            "collection_evidence_scope": True,
            "entity_evidence_scope": True,
            "deterministic_materialization": True,
            "integrity_decisions_applied": True,
            "external_signer_required": True,
        },
    }

    groups: dict[str, dict[str, bytes]] = {
        "source": {
            "collection-files.json": _canonical_json(
                {
                    "schema_version": "1.0",
                    "collection_id": str(collection.id),
                    "manifest_revision": collection.manifest_revision,
                    "files": [
                        {
                            **_manifest_record(row, codec),
                            "source_file_id": str(row.source_file_id)
                            if row.source_file_id
                            else None,
                            "detected_mime": row.detected_mime,
                            "status": row.status,
                            "error_code": row.error_code,
                        }
                        for row in collection_files
                    ],
                }
            )
        },
        "canonical": {"model.json": _canonical_json(canonical_model)},
        "obsidian": obsidian,
        "ontology": {
            "knowledge.ttl": knowledge_ttl,
            "knowledge.owl": (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                'xmlns:owl="http://www.w3.org/2002/07/owl#">'
                f'<owl:Ontology rdf:about="urn:akc:collection:{collection.id}"/>'
                "</rdf:RDF>\n"
            ).encode(),
            "knowledge.jsonld": _canonical_json(
                {
                    "@context": {"label": "http://www.w3.org/2000/01/rdf-schema#label"},
                    "@graph": jsonld_graph,
                }
            ),
            "knowledge.skos.ttl": (
                "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
                + "".join(
                    f"<urn:akc:entity:{row.id}> skos:prefLabel "
                    f"{_turtle_literal(row.label)} .\n"
                    for row in entities
                )
            ).encode("utf-8"),
            "shapes.shacl.ttl": (
                b"@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
                b"@prefix sk: <urn:akc:> .\n"
                b"sk:KnowledgeNodeShape a sh:NodeShape ; sh:targetClass sk:KnowledgeNote .\n"
            ),
            "vocabulary.md": (
                b"# FOLYNTA Vocabulary\n\n"
                b"- `KnowledgeNote`: evidence-bound knowledge note.\n"
                b"- `Entity`: project entity scoped by collection evidence.\n"
                b"- `Relation`: evidence-bound assertion.\n"
            ),
            "provenance.jsonld": _canonical_json(
                {
                    "@context": {"prov": "http://www.w3.org/ns/prov#"},
                    "@id": f"urn:akc:collection:{collection.id}",
                    "prov:wasGeneratedBy": f"urn:akc:architecture-plan:{plan.id}",
                }
            ),
        },
        "graph": {
            "nodes.csv": _csv_bytes(["id", "label", "name", "document_id"], graph_nodes),
            "relationships.csv": _csv_bytes(
                ["id", "subject_id", "predicate", "object_id", "document_id"],
                graph_relationships,
            ),
            "constraints.cypher": (
                b"CREATE CONSTRAINT akc_knowledge_id IF NOT EXISTS "
                b"FOR (n:KnowledgeNode) REQUIRE n.id IS UNIQUE;\n"
            ),
            "indexes.cypher": (
                b"CREATE INDEX akc_knowledge_name IF NOT EXISTS "
                b"FOR (n:KnowledgeNode) ON (n.name);\n"
            ),
            "import.cypher": (
                b"// Import nodes.csv and relationships.csv with the approved deployment loader.\n"
            ),
        },
        "rag": {
            "documents.jsonl": _jsonl_bytes(rag_documents),
            "chunks.jsonl": _jsonl_bytes(rag_chunks),
            "metadata.jsonl": _jsonl_bytes(rag_metadata),
            "evidence.jsonl": _jsonl_bytes(rag_evidence),
            "retrieval-profile.json": _canonical_json(
                {
                    "schema_version": "1.0",
                    "chunk_identity": "block_id",
                    "evidence_required": True,
                    "tenant_filter_required": True,
                    "collection_filter": str(collection.id),
                }
            ),
        },
        "provenance": {
            "activities.jsonl": _jsonl_bytes(provenance_activities),
            "integrity-decisions.json": _canonical_json(
                {
                    "schema_version": "1.0",
                    "collection_id": str(collection.id),
                    "decision_set_sha256": decision_set_sha256,
                    "decisions": decision_receipts,
                }
            ),
        },
        "validation": {
            "report.json": _canonical_json(validation_report),
            "round-trip.json": _canonical_json(
                {
                    "schema_version": "1.0",
                    "validator": "akc_exporters.import_knowledge_package",
                    "expected_counts": counts,
                    "require_signature": False,
                    "external_signer_required": True,
                }
            ),
        },
    }
    return groups, counts


def _package_role(path: str) -> str:
    if path == "README.md":
        return "readme"
    if path == "manifest.json":
        return "manifest"
    if path == "checksums.sha256":
        return "checksum"
    root = path.partition("/")[0]
    return {
        "source": "source",
        "canonical": "canonical",
        "obsidian": "knowledge",
        "ontology": "knowledge",
        "graph": "knowledge",
        "rag": "knowledge",
        "provenance": "provenance",
        "validation": "validation",
    }.get(root, "document_package")


def _package_media_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix.casefold()
    return {
        ".md": "text/markdown; charset=utf-8",
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
        ".jsonld": "application/ld+json",
        ".ttl": "text/turtle; charset=utf-8",
        ".owl": "application/rdf+xml",
        ".csv": "text/csv; charset=utf-8",
        ".cypher": "text/plain; charset=utf-8",
        ".sha256": "text/plain; charset=utf-8",
    }.get(suffix, "application/octet-stream")


async def _export_complete_knowledge_package(
    request: Request,
    session: AsyncSession,
    *,
    collection: Collection,
    plan: ArchitecturePlan,
    collection_files: list[CollectionFile],
    event_rows: list[CollectionEvent],
    integrity: dict[str, Any],
    principal: Principal,
    requested_profiles: list[str],
) -> CollectionExportResponse:
    codec = _collection_metadata_codec(request)
    groups, counts = await _complete_knowledge_groups(
        session,
        codec=codec,
        collection=collection,
        plan=plan,
        collection_files=collection_files,
        event_rows=event_rows,
        integrity=integrity,
    )
    semantic_model: Any = None
    semantic_blueprints: tuple[Any, ...] = ()
    semantic_architecture_plan_sha256: str | None = None
    require_semantic_profile = plan.plan.get("execution_scope") == "collection_processing_runtime"
    if require_semantic_profile:
        source_ids = {
            row.source_file_id
            for row in collection_files
            if row.status in _SUCCESS_FILE_STATES and row.source_file_id is not None
        }
        documents_by_source = await _documents_by_source(
            session,
            tenant_id=collection.tenant_id,
            project_id=collection.project_id,
            source_ids=source_ids,
        )
        compile_input = await load_collection_semantic_compile_input(
            session,
            tenant_id=collection.tenant_id,
            collection_id=collection.id,
            project_id=collection.project_id,
            architecture_plan_id=plan.id,
            document_ids=tuple(document.id for document in documents_by_source.values()),
        )
        prepared = prepare_collection_semantic_runtime(compile_input)
        if not prepared.ready_for_index:
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_SEMANTIC_PACKAGE_GATE_FAILED"},
            )
        compile_run = await session.scalar(
            select(KnowledgeCompileRun)
            .where(
                KnowledgeCompileRun.tenant_id == collection.tenant_id,
                KnowledgeCompileRun.collection_id == collection.id,
                KnowledgeCompileRun.architecture_plan_id == plan.id,
                KnowledgeCompileRun.compiler_revision == "collection-semantic-runtime-v1",
                KnowledgeCompileRun.status == "completed",
            )
            .order_by(KnowledgeCompileRun.started_at.desc())
            .limit(1)
        )
        if (
            compile_run is None
            or compile_run.output_sha256 != prepared.canonical_model_sha256.removeprefix("sha256:")
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_SEMANTIC_PACKAGE_DIGEST_MISMATCH"},
            )
        semantic_model = prepared.canonical_model
        semantic_blueprints = prepared.blueprint_modules
        semantic_architecture_plan_sha256 = prepared.architecture_plan_sha256
        groups["canonical"]["model.json"] = canonical_knowledge_model_bytes(
            prepared.canonical_model
        )
    architecture_plan_sha256 = semantic_architecture_plan_sha256 or (
        "sha256:" + _sha256(_canonical_json(plan.plan))
    )
    package_payload, receipt = build_knowledge_package(
        groups,
        collection_id=str(collection.id),
        architecture_plan_sha256=architecture_plan_sha256,
        signer=None,
        semantic_model=semantic_model,
        blueprint_modules=semantic_blueprints,
    )
    imported = import_knowledge_package(
        package_payload,
        require_signature=False,
        require_semantic_profile=require_semantic_profile,
    )
    if imported.receipt != receipt or (
        require_semantic_profile
        and (
            imported.semantic_model is None
            or canonical_knowledge_model_bytes(imported.semantic_model)
            != groups["canonical"]["model.json"]
        )
    ):
        raise HTTPException(
            status_code=500,
            detail={"code": "COLLECTION_PACKAGE_ROUND_TRIP_MISMATCH"},
        )
    package_sha = receipt.package_sha256.removeprefix("sha256:")
    manifest_sha = receipt.manifest_sha256.removeprefix("sha256:")
    with zipfile.ZipFile(io.BytesIO(package_payload), "r") as archive:
        packaged_files = {
            safe_relative_path(name): archive.read(name) for name in sorted(archive.namelist())
        }

    unresolved_scope = sum(
        int(integrity["verification_status_counts"].get(status, 0))
        for status in ("unresolved", "quarantined", "rejected")
    )
    warnings = [
        "Package is deterministic and round-trip validated.",
        "Production trust requires an approved external Ed25519 signer.",
    ]
    if unresolved_scope:
        warnings.append(
            "Unresolved or quarantined evidence is disclosed and excluded from billable scope."
        )
    export = Export(
        tenant_id=principal.tenant_id,
        project_id=collection.project_id,
        document_id=None,
        export_type="complete_knowledge",
        status="running",
        options={
            "collection_id": str(collection.id),
            "profiles": requested_profiles,
            "completion_scope": "complete_knowledge_package",
            "signature_status": receipt.signature_status,
        },
        created_by=principal.user_id,
    )
    session.add(export)
    await session.flush()
    package_attempt_scope = plan.processing_job_id or plan.id
    storage_key = (
        f"tenants/{principal.tenant_id}/projects/{collection.project_id}/"
        f"collections/{collection.id}/exports/processing/{package_attempt_scope}/"
        "complete-knowledge.zip"
    )
    package = PackageManifest(
        tenant_id=principal.tenant_id,
        collection_id=collection.id,
        export_id=export.id,
        profile="complete_knowledge_v1",
        status="building",
        manifest_sha256=manifest_sha,
        package_sha256=package_sha,
        size_bytes=len(package_payload),
        storage_key=storage_key,
        signature_status="external_signer_required",
        warnings=warnings,
        created_by=principal.user_id,
    )
    session.add(package)
    await session.flush()
    package_rows: list[PackageFile] = []
    for path, content in packaged_files.items():
        package_row = PackageFile(
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            package_manifest_id=package.id,
            path=path,
            role=_package_role(path),
            media_type=_package_media_type(path),
            sha256=_sha256(content),
            size_bytes=len(content),
        )
        session.add(package_row)
        package_rows.append(package_row)
        session.add(
            AssetRegistry(
                tenant_id=principal.tenant_id,
                collection_id=collection.id,
                export_package_id=package.id,
                asset_key=f"complete:{_sha256(path.encode('utf-8'))}",
                package_path=path,
                role=_package_role(path),
                media_type=_package_media_type(path),
                sha256=_sha256(content),
                size_bytes=len(content),
                license_id="tenant-content-derived",
                qa_status="verified",
            )
        )

    validation_checks = {
        "deterministic_zip": True,
        "manifest_hash_verified": True,
        "all_file_hashes_verified": True,
        "required_profile_roots_present": True,
        "round_trip_import_passed": True,
        "external_signer_required": True,
        "signed": False,
        "counts": counts,
    }
    validation = PackageValidation(
        tenant_id=principal.tenant_id,
        collection_id=collection.id,
        export_package_id=package.id,
        validator_version="akc-exporters-round-trip-v1",
        status="passed",
        checks=validation_checks,
        evidence_sha256=_sha256(_canonical_json(validation_checks)),
    )
    session.add(validation)
    package_processing_job_id = plan.processing_job_id
    package_processing_job_id_wire = (
        str(package_processing_job_id) if package_processing_job_id is not None else None
    )
    if collection.status != "PACKAGING":
        _transition(collection, "PACKAGING")
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="export.started.v1",
        job_id=package_processing_job_id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": package_processing_job_id_wire,
            "export_id": str(export.id),
            "package_manifest_id": str(package.id),
            "profile": "complete_knowledge_v1",
            "completion_scope": "complete_knowledge_package",
            "status": collection.status,
        },
    )
    await request.app.state.object_store.put_export(storage_key, package_payload)
    export.storage_key = storage_key
    export.sha256 = package_sha
    export.size_bytes = len(package_payload)
    export.status = "completed"
    export.completed_at = utcnow()
    package.status = "completed"
    package.completed_at = utcnow()
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="export.ready.v1",
        job_id=package_processing_job_id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": package_processing_job_id_wire,
            "export_id": str(export.id),
            "package_manifest_id": str(package.id),
            "package_sha256": package_sha,
            "manifest_sha256": manifest_sha,
            "size_bytes": len(package_payload),
            "file_count": len(package_rows),
            "signature_status": package.signature_status,
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="package.validated.v1",
        job_id=package_processing_job_id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": package_processing_job_id_wire,
            "export_id": str(export.id),
            "package_manifest_id": str(package.id),
            "package_validation_id": str(validation.id),
            "validator_version": validation.validator_version,
            "validation_status": validation.status,
            "evidence_sha256": validation.evidence_sha256,
            "external_signer_required": True,
        },
    )
    _transition(collection, "COMPLETED")
    completion_calibration: dict[str, Any] | None = None
    if require_semantic_profile and plan.processing_job_id is not None:
        processing_job = await session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.tenant_id == collection.tenant_id,
                ProcessingJob.id == plan.processing_job_id,
                ProcessingJob.job_type == "collection_processing",
            )
            .with_for_update()
        )
        if processing_job is None or processing_job.status != "running":
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_PROCESSING_JOB_FINALIZATION_INVALID"},
            )
        processing_job.status = "completed"
        processing_job.completed_at = utcnow()
        completion_calibration = await _completion_calibration_receipt(
            session,
            collection=collection,
            processing_job=processing_job,
            collection_files=collection_files,
            package_size_bytes=len(package_payload),
        )
        processing_job.progress = {
            **processing_job.progress,
            "stage": "completed",
            "package_manifest_id": str(package.id),
            "export_id": str(export.id),
            "package_sha256": package_sha,
            "estimate_calibration": completion_calibration,
        }
        await _emit_collection_event(
            session,
            collection=collection,
            event_type="processing.completed.v1",
            job_id=processing_job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(processing_job.id),
                "architecture_plan_id": str(plan.id),
                "package_manifest_id": str(package.id),
                "export_id": str(export.id),
                "package_sha256": package_sha,
                "estimate_calibration_evidence_sha256": str(
                    completion_calibration["evidence_sha256"]
                ),
            },
        )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="collection.completed.v1",
        job_id=package_processing_job_id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": package_processing_job_id_wire,
            "export_id": str(export.id),
            "package_manifest_id": str(package.id),
            "profile": "complete_knowledge_v1",
            "signature_status": package.signature_status,
            "status": collection.status,
        },
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="collection.export.completed.v1",
        job_id=package_processing_job_id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": package_processing_job_id_wire,
            "export_id": str(export.id),
            "package_manifest_id": str(package.id),
            "profile": "complete_knowledge_v1",
            "package_sha256": package_sha,
            "manifest_sha256": manifest_sha,
            "size_bytes": len(package_payload),
            "file_count": len(package_rows),
            "signature_status": package.signature_status,
            "completion_scope": "complete_knowledge_package",
            "status": collection.status,
        },
    )
    session.add(
        OutboxEvent(
            tenant_id=principal.tenant_id,
            aggregate_type="export",
            aggregate_id=export.id,
            event_type="export.completed.v1",
            payload={
                "export_id": str(export.id),
                "collection_id": str(collection.id),
                "processing_job_id": package_processing_job_id_wire,
                "profiles": requested_profiles,
                "signature_status": package.signature_status,
            },
        )
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.complete_knowledge_export_completed",
        target_type="package_manifest",
        target_id=str(package.id),
        metadata={
            "collection_id": str(collection.id),
            "export_id": str(export.id),
            "package_sha256": package_sha,
            "manifest_sha256": manifest_sha,
            "signature_status": package.signature_status,
            "round_trip_validated": True,
        },
    )
    export_duration_seconds = (
        max(0.0, (export.completed_at - export.created_at).total_seconds())
        if export.completed_at is not None
        else 0.0
    )
    unique_source_bytes = sum(
        {
            row.source_file_id: row.size_bytes
            for row in collection_files
            if row.status in _SUCCESS_FILE_STATES and row.source_file_id is not None
        }.values()
    )
    storage_amplification_ratio = (
        len(package_payload) / unique_source_bytes if unique_source_bytes > 0 else None
    )
    await session.commit()
    observe_collection_export(
        profile="complete_knowledge",
        duration_seconds=export_duration_seconds,
        storage_amplification_ratio=storage_amplification_ratio,
    )
    if completion_calibration is not None:
        observe_collection_estimate_calibration(
            credit_error_ratio=completion_calibration["credit_error_ratio"],
            duration_error_ratio=completion_calibration["duration_error_ratio"],
            route_mix_error_ratio=completion_calibration["route_mix_error_ratio"],
        )
        if completion_calibration["retry_ratio"] is not None:
            observe_collection_retry_ratio(completion_calibration["retry_ratio"])
        if completion_calibration["credits_refunded"] is not None:
            record_collection_credits_refunded(
                completion_calibration["credits_refunded"]
            )
    return CollectionExportResponse(
        export_id=export.id,
        package_manifest_id=package.id,
        collection_id=collection.id,
        status="completed",
        profile="complete_knowledge_v1",
        download_url=f"/v1/exports/{export.id}/download",
        sha256=package_sha,
        size_bytes=len(package_payload),
        signature_status="external_signer_required",
        completion_scope="complete_knowledge_package",
        files=[_package_file_response(row) for row in package_rows],
        warnings=warnings,
    )


async def _record_collection_package_failure(
    request: Request,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    collection_id: uuid.UUID,
    plan_id: uuid.UUID,
    error_code: str,
) -> None:
    """Persist a fail-closed terminal and idempotent reimbursement separately."""

    async with request.app.state.database.sessions() as failure_session:
        await set_rls_context(
            failure_session,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        collection = await failure_session.scalar(
            select(Collection)
            .where(
                Collection.tenant_id == tenant_id,
                Collection.id == collection_id,
            )
            .with_for_update()
        )
        plan = await failure_session.scalar(
            select(ArchitecturePlan).where(
                ArchitecturePlan.tenant_id == tenant_id,
                ArchitecturePlan.collection_id == collection_id,
                ArchitecturePlan.id == plan_id,
            )
        )
        job = (
            await failure_session.scalar(
                select(ProcessingJob)
                .where(
                    ProcessingJob.tenant_id == tenant_id,
                    ProcessingJob.id == plan.processing_job_id,
                    ProcessingJob.job_type == "collection_processing",
                )
                .with_for_update()
            )
            if plan is not None and plan.processing_job_id is not None
            else None
        )
        if (
            collection is None
            or plan is None
            or job is None
            or plan.plan.get("execution_scope") != "collection_processing_runtime"
            or job.status != "running"
        ):
            return
        actual = dict(job.cost_actual or {})
        consumed = _money(actual.get("consumed"))
        refunded = _money(actual.get("refunded"))
        package_attempt = int(job.progress.get("package_attempt", 0))
        reimbursement = max(Decimal("0"), consumed - refunded)
        if reimbursement > 0:
            refund_operation_key = (
                f"collection:{job.id}:package-refund"
                if package_attempt == 0
                else f"collection:{job.id}:package-refund:{package_attempt}"
            )
            await credit_entry(
                failure_session,
                tenant_id=tenant_id,
                operation_key=refund_operation_key,
                entry_type="refund",
                credits=reimbursement,
                job_id=job.id,
                metadata={
                    "collection_id": str(collection.id),
                    "reason": "package_gate_failed",
                    "error_code": error_code,
                    "package_attempt": package_attempt,
                },
            )
            refunded += reimbursement
            actual["refunded"] = str(refunded)
            job.cost_actual = actual
            await _emit_collection_event(
                failure_session,
                collection=collection,
                event_type="credits.refunded.v1",
                job_id=job.id,
                payload={
                    "collection_id": str(collection.id),
                    "processing_job_id": str(job.id),
                    "credits": str(reimbursement),
                    "reason": "package_gate_failed",
                },
            )
        job.status = "failed"
        job.completed_at = utcnow()
        job.error = {"code": error_code}
        job.progress = {**job.progress, "stage": "package_failed"}
        if collection.status in {"KNOWLEDGE_COMPILING", "PARTIAL"}:
            _transition(collection, "PACKAGING", reason="PACKAGE_GATE_STARTED")
        if collection.status == "PACKAGING":
            _transition(collection, "FAILED_RETRYABLE", reason=error_code)
        await _emit_collection_event(
            failure_session,
            collection=collection,
            event_type="processing.failed.v1",
            job_id=job.id,
            payload={
                "collection_id": str(collection.id),
                "processing_job_id": str(job.id),
                "error_code": error_code,
            },
        )
        await audit(
            failure_session,
            tenant_id=tenant_id,
            actor_id=user_id,
            action="collection.package_runtime_failed",
            target_type="processing_job",
            target_id=str(job.id),
            metadata={
                "collection_id": str(collection.id),
                "architecture_plan_id": str(plan.id),
                "error_code": error_code,
                "refunded": str(reimbursement),
            },
        )
        await failure_session.commit()


@router.post(
    "/collections/{collection_id}/exports",
    response_model=CollectionExportResponse,
    status_code=201,
)
@idempotent_mutation
async def export_collection(
    collection_id: uuid.UUID,
    payload: CollectionExportRequest,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
    codec: CollectionMetadataDep,
    idempotency_key: IdempotencyKey = None,
) -> CollectionExportResponse:
    _require_idempotency_key(idempotency_key)
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="write",
        lock=True,
    )
    supported_profiles = {"collection_manifest_v1", "complete_knowledge_v1"}
    unknown_profiles = sorted(set(payload.profiles) - supported_profiles)
    if unknown_profiles:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COLLECTION_EXPORT_PROFILE_UNAVAILABLE",
                "available_profiles": sorted(supported_profiles),
                "requested_profiles": payload.profiles,
                "unknown_profiles": unknown_profiles,
            },
        )
    target_profile = (
        "complete_knowledge_v1"
        if "complete_knowledge_v1" in payload.profiles
        else "collection_manifest_v1"
    )
    existing = await session.scalar(
        select(PackageManifest)
        .where(
            PackageManifest.tenant_id == principal.tenant_id,
            PackageManifest.collection_id == collection.id,
            PackageManifest.profile == target_profile,
            PackageManifest.status == "completed",
        )
        .order_by(PackageManifest.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        return await _existing_package_response(session, existing)
    if collection.status not in {"KNOWLEDGE_COMPILING", "PACKAGING", "PARTIAL"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_NOT_READY_FOR_EXPORT"},
        )
    plan = await session.scalar(
        select(ArchitecturePlan)
        .where(
            ArchitecturePlan.tenant_id == principal.tenant_id,
            ArchitecturePlan.collection_id == collection.id,
            ArchitecturePlan.status == "compiled",
        )
        .order_by(ArchitecturePlan.plan_version.desc())
        .limit(1)
    )
    if plan is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_ARCHITECTURE_PLAN_REQUIRED"},
        )
    knowledge = await _collection_knowledge_projection(session, collection=collection)
    if not knowledge.ready_for_package:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_KNOWLEDGE_PROJECTION_INCOMPLETE"},
        )
    integrity = await _integrity_projection(session, collection=collection)
    collection_files = list(
        await session.scalars(
            select(CollectionFile)
            .where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
                CollectionFile.status != "purged",
            )
            .order_by(CollectionFile.source_root_id, CollectionFile.id)
        )
    )
    collection_files.sort(
        key=lambda row: (
            str(row.source_root_id),
            normalize_collection_relative_path(_file_relative_path(row, codec)),
            str(row.id),
        )
    )
    event_rows = list(
        await session.scalars(
            select(CollectionEvent)
            .where(
                CollectionEvent.tenant_id == principal.tenant_id,
                CollectionEvent.collection_id == collection.id,
            )
            .order_by(CollectionEvent.sequence)
        )
    )
    if target_profile == "complete_knowledge_v1":
        runtime_plan_id = plan.id
        try:
            return await _export_complete_knowledge_package(
                request,
                session,
                collection=collection,
                plan=plan,
                collection_files=collection_files,
                event_rows=event_rows,
                integrity=integrity,
                principal=principal,
                requested_profiles=payload.profiles,
            )
        except Exception as exc:
            error_code = "COLLECTION_PACKAGE_RUNTIME_FAILED"
            if isinstance(exc, HTTPException):
                error_detail = cast(Any, exc.detail)
                if isinstance(error_detail, dict):
                    candidate = error_detail.get("code")
                    if isinstance(candidate, str) and candidate:
                        error_code = candidate
            await session.rollback()
            await _record_collection_package_failure(
                request,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                collection_id=collection_id,
                plan_id=runtime_plan_id,
                error_code=error_code,
            )
            raise
    limitations = [
        "profile_scope:repository_manifest_only",
        "full_ontology:not_materialized",
        "neo4j_import:not_materialized",
        "production_retrieval_bundle:not_materialized",
        "signature:external_key_required",
    ]
    files: dict[str, bytes] = {
        "README.md": _package_readme(collection),
        "source/collection-files.json": _canonical_json(
            {
                "schema_version": "1.0",
                "collection_id": str(collection.id),
                "manifest_revision": collection.manifest_revision,
                "files": [
                    {
                        **_manifest_record(row, codec),
                        "source_file_id": (str(row.source_file_id) if row.source_file_id else None),
                        "detected_mime": row.detected_mime,
                        "status": row.status,
                        "error_code": row.error_code,
                    }
                    for row in collection_files
                ],
            }
        ),
        "architecture/plan.json": _canonical_json(
            {
                "id": str(plan.id),
                "version": plan.plan_version,
                "status": plan.status,
                "input_integrity_sha256": plan.input_integrity_sha256,
                "plan": plan.plan,
            }
        ),
        "knowledge/index.json": _canonical_json(
            knowledge.model_dump(mode="json", exclude_none=True)
        ),
        "integrity/summary.json": _canonical_json(integrity),
        "provenance/collection-events.jsonl": b"".join(
            _canonical_json(
                CollectionEventResponse(
                    event_id=row.id,
                    collection_id=row.collection_id,
                    job_id=row.job_id,
                    sequence=row.sequence,
                    event_type=row.event_type,
                    timestamp=row.occurred_at,
                    payload=row.payload,
                    schema_version="1.0",
                ).model_dump(mode="json")
            )
            for row in event_rows
        ),
        "validation/limitations.json": _canonical_json(
            {
                "schema_version": "1.0",
                "completion_scope": "repository_manifest_only",
                "limitations": limitations,
                "signature_status": "unsigned_external_key_required",
            }
        ),
    }
    checksum_lines = [f"{_sha256(content)}  {path}\n" for path, content in sorted(files.items())]
    files["checksums.sha256"] = "".join(checksum_lines).encode("utf-8")
    internal_manifest = {
        "schema_version": "1.0",
        "profile": "collection_manifest_v1",
        "completion_scope": "repository_manifest_only",
        "collection_id": str(collection.id),
        "project_id": str(collection.project_id),
        "manifest_revision": collection.manifest_revision,
        "integrity_sha256": integrity["integrity_sha256"],
        "architecture_plan_id": str(plan.id),
        "files": [
            {
                "path": path,
                "sha256": _sha256(content),
                "size_bytes": len(content),
            }
            for path, content in sorted(files.items())
        ],
        "signature_status": "unsigned_external_key_required",
        "warnings": limitations,
    }
    files["manifest.json"] = _canonical_json(internal_manifest)
    package_payload = deterministic_zip(files)
    package_sha = _sha256(package_payload)
    manifest_sha = _sha256(files["manifest.json"])

    export = Export(
        tenant_id=principal.tenant_id,
        project_id=collection.project_id,
        document_id=None,
        export_type="collection_manifest",
        status="running",
        options={
            "collection_id": str(collection.id),
            "profiles": ["collection_manifest_v1"],
            "completion_scope": "repository_manifest_only",
        },
        created_by=principal.user_id,
    )
    session.add(export)
    await session.flush()
    storage_key = (
        f"tenants/{principal.tenant_id}/projects/{collection.project_id}/"
        f"collections/{collection.id}/exports/{export.id}/collection-manifest.zip"
    )
    package = PackageManifest(
        tenant_id=principal.tenant_id,
        collection_id=collection.id,
        export_id=export.id,
        profile="collection_manifest_v1",
        status="building",
        manifest_sha256=manifest_sha,
        package_sha256=package_sha,
        size_bytes=len(package_payload),
        storage_key=storage_key,
        signature_status="unsigned_external_key_required",
        warnings=limitations,
        created_by=principal.user_id,
    )
    session.add(package)
    await session.flush()
    role_by_path = {
        "README.md": "readme",
        "manifest.json": "manifest",
        "source/collection-files.json": "source",
        "architecture/plan.json": "architecture",
        "knowledge/index.json": "knowledge",
        "integrity/summary.json": "integrity",
        "provenance/collection-events.jsonl": "provenance",
        "validation/limitations.json": "validation",
        "checksums.sha256": "checksum",
    }
    media_by_suffix = {
        ".md": "text/markdown; charset=utf-8",
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
        ".sha256": "text/plain; charset=utf-8",
    }
    package_files: list[PackageFile] = []
    for path, content in sorted(files.items()):
        package_file = PackageFile(
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            package_manifest_id=package.id,
            path=safe_relative_path(path),
            role=role_by_path[path],
            media_type=media_by_suffix.get(PurePosixPath(path).suffix, "application/octet-stream"),
            sha256=_sha256(content),
            size_bytes=len(content),
        )
        session.add(package_file)
        package_files.append(package_file)
    _transition(collection, "PACKAGING")
    await request.app.state.object_store.put_export(storage_key, package_payload)
    export.storage_key = storage_key
    export.sha256 = package_sha
    export.size_bytes = len(package_payload)
    export.status = "completed"
    export.completed_at = utcnow()
    package.status = "completed"
    package.completed_at = utcnow()
    _transition(
        collection,
        "PARTIAL",
        reason="FULL_KNOWLEDGE_PACKAGE_NOT_MATERIALIZED",
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="collection.export.completed.v1",
        payload={
            "collection_id": str(collection.id),
            "export_id": str(export.id),
            "package_manifest_id": str(package.id),
            "profile": "collection_manifest_v1",
            "package_sha256": package_sha,
            "manifest_sha256": manifest_sha,
            "size_bytes": len(package_payload),
            "file_count": len(package_files),
            "signature_status": package.signature_status,
            "completion_scope": "repository_manifest_only",
            "status": collection.status,
        },
    )
    session.add(
        OutboxEvent(
            tenant_id=principal.tenant_id,
            aggregate_type="export",
            aggregate_id=export.id,
            event_type="export.completed.v1",
            payload={
                "export_id": str(export.id),
                "collection_id": str(collection.id),
                "profiles": ["collection_manifest_v1"],
            },
        )
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.export_completed",
        target_type="package_manifest",
        target_id=str(package.id),
        metadata={
            "collection_id": str(collection.id),
            "export_id": str(export.id),
            "package_sha256": package_sha,
            "completion_scope": "repository_manifest_only",
        },
    )
    await session.commit()
    return CollectionExportResponse(
        export_id=export.id,
        package_manifest_id=package.id,
        collection_id=collection.id,
        status="completed",
        profile="collection_manifest_v1",
        download_url=f"/v1/exports/{export.id}/download",
        sha256=package_sha,
        size_bytes=len(package_payload),
        signature_status="unsigned_external_key_required",
        completion_scope="repository_manifest_only",
        files=[_package_file_response(row) for row in package_files],
        warnings=limitations,
    )


async def _prepare_collection_package_retry(
    session: AsyncSession,
    *,
    collection: Collection,
    job: ProcessingJob,
    plan: ArchitecturePlan,
    actor_user_id: uuid.UUID,
    enqueue_finalizer: bool,
) -> None:
    if (
        collection.status != "FAILED_RETRYABLE"
        or job.status != "failed"
        or str(job.progress.get("stage", "")) != "package_failed"
        or plan.status != "compiled"
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_PACKAGE_RETRY_UNSAFE"},
        )
    package_attempt = int(job.progress.get("package_attempt", 0)) + 1
    actual = dict(job.cost_actual or {})
    consumed = _money(actual.get("consumed"))
    refunded = _money(actual.get("refunded"))
    retry_reconsumed = _money(actual.get("retry_reconsumed"))
    reconsume = max(Decimal("0"), refunded - retry_reconsumed)
    if reconsume > 0:
        await credit_entry(
            session,
            tenant_id=job.tenant_id,
            operation_key=f"collection:{job.id}:package-retry:{package_attempt}:reserve",
            entry_type="reserve",
            credits=reconsume,
            job_id=job.id,
            metadata={
                "collection_id": str(collection.id),
                "reason": "package_retry_reconsume",
                "package_attempt": package_attempt,
            },
        )
        await credit_entry(
            session,
            tenant_id=job.tenant_id,
            operation_key=f"collection:{job.id}:package-retry:{package_attempt}:consume",
            entry_type="consume",
            credits=reconsume,
            job_id=job.id,
            metadata={
                "from_reserved": True,
                "collection_id": str(collection.id),
                "reason": "package_retry_reconsume",
                "package_attempt": package_attempt,
            },
        )
        actual["reserved"] = str(_money(actual.get("reserved")) + reconsume)
        actual["consumed"] = str(consumed + reconsume)
        actual["retry_reconsumed"] = str(retry_reconsumed + reconsume)
        job.cost_actual = actual
    job.status = "running"
    job.completed_at = None
    job.error = None
    job.requested_options = {
        **job.requested_options,
        "initiating_user_id": str(actor_user_id),
    }
    job.progress = {
        **job.progress,
        "stage": "ready_for_packaging",
        "package_attempt": package_attempt,
    }
    _transition(collection, "PACKAGING", reason="PACKAGE_RETRY_APPROVED")
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="processing.resumed.v1",
        job_id=job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(job.id),
            "stage": "ready_for_packaging",
            "package_attempt": package_attempt,
        },
    )
    if enqueue_finalizer:
        pending = await session.scalar(
            select(OutboxEvent.id).where(
                OutboxEvent.tenant_id == job.tenant_id,
                OutboxEvent.aggregate_type == "collection_processing",
                OutboxEvent.aggregate_id == job.id,
                OutboxEvent.event_type == "collection.semantic.compile.requested.v1",
                OutboxEvent.published_at.is_(None),
                OutboxEvent.dead_lettered_at.is_(None),
            )
        )
        if pending is None:
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
                        "architecture_plan_id": str(plan.id),
                        "actor_user_id": str(actor_user_id),
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


async def _prepare_collection_finalizer_retry(
    session: AsyncSession,
    *,
    collection: Collection,
    job: ProcessingJob,
    plan: ArchitecturePlan,
    actor_user_id: uuid.UUID,
) -> None:
    if (
        collection.status not in {"FAILED_RETRYABLE", "UNRESOLVED"}
        or job.status != "failed"
        or str(job.progress.get("stage", "")) != "semantic_finalizer_failed"
        or plan.status not in {"planned", "compiled"}
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_FINALIZER_RETRY_UNSAFE"},
        )
    if collection.status == "UNRESOLVED":
        # Rolling upgrades may retain the pre-redrive terminal emitted by an
        # older scheduler. The exact durable job stage is the migration guard;
        # no other unresolved collection is made retryable here.
        collection.status = "FAILED_RETRYABLE"
        collection.status_reason = "LEGACY_FINALIZER_TERMINAL_RECOVERED"
        collection.updated_at = utcnow()
    retry_attempt = int(job.progress.get("finalizer_retry_attempt", 0)) + 1
    actual = dict(job.cost_actual or {})
    consumed = _money(actual.get("consumed"))
    refunded = _money(actual.get("refunded"))
    retry_reconsumed = _money(actual.get("retry_reconsumed"))
    reconsume = max(Decimal("0"), refunded - retry_reconsumed)
    if reconsume > 0:
        await credit_entry(
            session,
            tenant_id=job.tenant_id,
            operation_key=f"collection:{job.id}:finalizer-retry:{retry_attempt}:reserve",
            entry_type="reserve",
            credits=reconsume,
            job_id=job.id,
            metadata={
                "collection_id": str(collection.id),
                "reason": "semantic_finalizer_retry_reconsume",
                "finalizer_retry_attempt": retry_attempt,
            },
        )
        await credit_entry(
            session,
            tenant_id=job.tenant_id,
            operation_key=f"collection:{job.id}:finalizer-retry:{retry_attempt}:consume",
            entry_type="consume",
            credits=reconsume,
            job_id=job.id,
            metadata={
                "from_reserved": True,
                "collection_id": str(collection.id),
                "reason": "semantic_finalizer_retry_reconsume",
                "finalizer_retry_attempt": retry_attempt,
            },
        )
        actual["reserved"] = str(_money(actual.get("reserved")) + reconsume)
        actual["consumed"] = str(consumed + reconsume)
        actual["retry_reconsumed"] = str(retry_reconsumed + reconsume)
        job.cost_actual = actual
    stage = "semantic_compile_queued" if plan.status == "planned" else "ready_for_packaging"
    job.status = "running"
    job.completed_at = None
    job.error = None
    job.requested_options = {
        **job.requested_options,
        "initiating_user_id": str(actor_user_id),
    }
    job.progress = {
        **job.progress,
        "stage": stage,
        "finalizer_retry_attempt": retry_attempt,
    }
    if plan.status == "planned":
        _transition(collection, "PROCESSING", reason="FINALIZER_RETRY_APPROVED")
        _transition(collection, "VERIFYING_OUTPUT", reason="SEMANTIC_COMPILE_REQUEUED")
    else:
        _transition(collection, "PACKAGING", reason="FINALIZER_PACKAGE_REQUEUED")
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
                "architecture_plan_id": str(plan.id),
                "actor_user_id": str(actor_user_id),
                "immutable_plan_sha256": str(job.requested_options["immutable_plan_sha256"]),
                "approved_preflight_sha256": str(
                    job.requested_options["approved_preflight_sha256"]
                ),
                "approved_estimate_sha256": str(job.requested_options["approved_estimate_sha256"]),
            },
        )
    )
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="processing.resumed.v1",
        job_id=job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(job.id),
            "architecture_plan_id": str(plan.id),
            "stage": stage,
            "finalizer_retry_attempt": retry_attempt,
        },
    )


async def _prepare_collection_analysis_retry(
    session: AsyncSession,
    *,
    collection: Collection,
    job: ProcessingJob,
    plan: ArchitecturePlan,
    actor_user_id: uuid.UUID,
    requested_hard_cap: Decimal | None,
) -> tuple[ArchitecturePlan, list[AnalysisTask], str]:
    """Re-arm only collection bindings after a credit-policy terminal.

    The shared analysis task and its global outbox ownership are never reset.
    A new immutable plan version records any approved hard-cap change, while
    cumulative ledger totals remain on the original billing-owner job.
    """

    retryable_codes = frozenset(
        {
            "CREDIT_HARD_CAP_REACHED",
            "INSUFFICIENT_CREDITS_FOR_OVERAGE",
        }
    )
    error_code = str((job.error or {}).get("code", ""))
    if (
        collection.status != "FAILED_RETRYABLE"
        or job.status != "failed"
        or str(job.progress.get("stage", "")) != "failed"
        or plan.status != "planned"
        or error_code not in retryable_codes
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_ANALYSIS_RETRY_UNSAFE"},
        )

    old_hard_cap = _money(job.cost_estimate.get("hard_cap"))
    new_hard_cap = _money(requested_hard_cap or old_hard_cap)
    approved_ceiling = _money(
        job.cost_estimate.get(
            "approved_collection_reserve_ceiling",
            job.cost_estimate.get("reserve_ceiling"),
        )
    )
    overage_policy = str(job.cost_estimate.get("overage_policy", "stop_at_cap"))
    policy_maximum = (
        (approved_ceiling * Decimal("1.10")).quantize(Decimal("0.000001"))
        if overage_policy == "allow_10_percent"
        else approved_ceiling
        if overage_policy == "stop_at_cap"
        else None
    )
    if new_hard_cap <= 0 or (policy_maximum is not None and new_hard_cap > policy_maximum):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CREDIT_HARD_CAP_EXCEEDS_APPROVED_OVERAGE_POLICY",
                "maximum": str(policy_maximum) if policy_maximum is not None else None,
            },
        )
    if error_code == "CREDIT_HARD_CAP_REACHED" and new_hard_cap <= old_hard_cap:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COLLECTION_RETRY_REQUIRES_HIGHER_HARD_CAP",
                "current": str(old_hard_cap),
            },
        )

    bindings = list(
        await session.scalars(
            select(CollectionProcessingTaskBinding).where(
                CollectionProcessingTaskBinding.tenant_id == job.tenant_id,
                CollectionProcessingTaskBinding.collection_id == collection.id,
                CollectionProcessingTaskBinding.processing_job_id == job.id,
            )
        )
    )
    if not bindings:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_ANALYSIS_RETRY_BINDINGS_MISSING"},
        )
    collection_file_ids = {binding.collection_file_id for binding in bindings}
    retry_attempt_rows = list(
        await session.scalars(
            select(RouteAttempt).where(
                RouteAttempt.tenant_id == job.tenant_id,
                RouteAttempt.collection_id == collection.id,
                RouteAttempt.collection_file_id.in_(collection_file_ids),
            )
        )
    )
    failed_page_ids: set[uuid.UUID] = set()
    affected_file_ids: set[uuid.UUID] = set()
    for attempt in retry_attempt_rows:
        reason_codes = set(str(code) for code in (attempt.reason_codes or []))
        if reason_codes.isdisjoint(retryable_codes):
            continue
        failed_page_ids.add(attempt.page_id)
        affected_file_ids.add(attempt.collection_file_id)
        await session.delete(attempt)

    for binding in bindings:
        if binding.status == "detached" or binding.collection_file_id in affected_file_ids:
            binding.status = "active"
            binding.settled_at = None
    if not any(binding.status == "active" for binding in bindings):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_ANALYSIS_RETRY_SCOPE_EMPTY"},
        )

    task_ids = {binding.analysis_task_id for binding in bindings}
    tasks = list(
        await session.scalars(
            select(AnalysisTask).where(
                AnalysisTask.tenant_id == job.tenant_id,
                AnalysisTask.id.in_(task_ids),
            )
        )
    )
    if len(tasks) != len(task_ids):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_ANALYSIS_RETRY_TASKS_MISSING"},
        )

    old_modules = list(
        await session.scalars(
            select(BlueprintModule)
            .where(
                BlueprintModule.tenant_id == job.tenant_id,
                BlueprintModule.architecture_plan_id == plan.id,
            )
            .order_by(BlueprintModule.module_key)
        )
    )
    module_ids = {module.module_key: uuid.uuid4() for module in old_modules}
    retry_attempt = int(job.progress.get("retry_attempt", 0)) + 1
    new_plan_id = uuid.uuid4()
    retry_basis = dict(plan.plan)
    retry_basis.pop("immutable_plan_sha256", None)
    retry_basis.update(
        {
            "credit_hard_cap": str(new_hard_cap),
            "processing_job_id": str(job.id),
            "retry_of_architecture_plan_id": str(plan.id),
            "retry_attempt": retry_attempt,
            "output_modules": [
                {
                    "id": str(module_ids[module.module_key]),
                    "module_key": module.module_key,
                    "module_version": module.module_version,
                }
                for module in old_modules
            ],
        }
    )
    immutable_plan_sha256 = _sha256(_canonical_json(retry_basis))
    retry_plan_payload = {
        **retry_basis,
        "immutable_plan_sha256": immutable_plan_sha256,
    }
    current_version = await session.scalar(
        select(func.max(ArchitecturePlan.plan_version)).where(
            ArchitecturePlan.tenant_id == job.tenant_id,
            ArchitecturePlan.collection_id == collection.id,
        )
    )
    plan.status = "stale"
    retry_plan = ArchitecturePlan(
        id=new_plan_id,
        tenant_id=job.tenant_id,
        collection_id=collection.id,
        processing_job_id=job.id,
        plan_version=int(current_version or plan.plan_version) + 1,
        status="planned",
        input_integrity_sha256=immutable_plan_sha256,
        plan=retry_plan_payload,
        created_by=actor_user_id,
    )
    session.add(retry_plan)
    for module in old_modules:
        session.add(
            BlueprintModule(
                id=module_ids[module.module_key],
                tenant_id=job.tenant_id,
                collection_id=collection.id,
                architecture_plan_id=retry_plan.id,
                module_key=module.module_key,
                module_version=module.module_version,
                status="planned",
                config_json=dict(module.config_json or {}),
                output_summary={},
            )
        )

    actual = dict(job.cost_actual or {})
    total_reserved = _money(actual.get("reserved"))
    consumed = _money(actual.get("consumed"))
    released = _money(actual.get("released"))
    available_reserved = max(Decimal("0"), total_reserved - consumed - released)
    initial_reserve_ceiling = _money(job.cost_estimate.get("reserve_ceiling"))
    target_available = max(
        Decimal("0"),
        min(initial_reserve_ceiling, new_hard_cap) - consumed,
    )
    retry_reserve = max(Decimal("0"), target_available - available_reserved)
    if retry_reserve > 0:
        await credit_entry(
            session,
            tenant_id=job.tenant_id,
            operation_key=f"collection:{job.id}:analysis-retry:{retry_attempt}:reserve",
            entry_type="reserve",
            credits=retry_reserve,
            job_id=job.id,
            metadata={
                "collection_id": str(collection.id),
                "reason": "analysis_credit_retry",
                "retry_attempt": retry_attempt,
                "hard_cap": str(new_hard_cap),
            },
        )
        total_reserved += retry_reserve
        actual["reserved"] = str(total_reserved)
        job.cost_actual = actual

    resume_token = secrets.token_urlsafe(32)
    terminal_result_ids = {str(item) for item in job.progress.get("terminal_result_ids", [])} - {
        str(page_id) for page_id in failed_page_ids
    }
    job.status = "running"
    job.completed_at = None
    job.error = None
    job.cost_estimate = {
        **job.cost_estimate,
        "hard_cap": str(new_hard_cap),
    }
    job.requested_options = {
        **job.requested_options,
        "architecture_plan_id": str(retry_plan.id),
        "immutable_plan_sha256": immutable_plan_sha256,
        "credit_hard_cap": str(new_hard_cap),
        "output_modules": retry_basis["output_modules"],
        "resume_token_hash": _sha256(resume_token.encode("utf-8")),
        "resume_version": int(job.requested_options.get("resume_version", 1)) + 1,
        "retry_attempt": retry_attempt,
        "initiating_user_id": str(actor_user_id),
    }
    job.progress = {
        **job.progress,
        "stage": "processing",
        "retry_attempt": retry_attempt,
        "terminal_result_ids": sorted(terminal_result_ids),
    }
    _transition(collection, "PROCESSING", reason="ANALYSIS_RETRY_APPROVED")
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="processing.resumed.v1",
        job_id=job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(job.id),
            "architecture_plan_id": str(retry_plan.id),
            "retry_attempt": retry_attempt,
            "hard_cap": str(new_hard_cap),
        },
    )

    from akc_api.collection_processing import reconcile_collection_analysis_task

    for task in tasks:
        if task.status in {"completed", "failed", "dead_letter"}:
            await reconcile_collection_analysis_task(session, task=task)
        elif task.status == "queued":
            pending = await session.scalar(
                select(OutboxEvent.id).where(
                    OutboxEvent.tenant_id == task.tenant_id,
                    OutboxEvent.aggregate_type == "analysis_task",
                    OutboxEvent.aggregate_id == task.id,
                    OutboxEvent.event_type == "document.analysis.requested.v1",
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.dead_lettered_at.is_(None),
                )
            )
            if pending is None:
                session.add(
                    OutboxEvent(
                        tenant_id=task.tenant_id,
                        aggregate_type="analysis_task",
                        aggregate_id=task.id,
                        event_type="document.analysis.requested.v1",
                        payload={
                            "task_id": str(task.id),
                            "tenant_id": str(task.tenant_id),
                            "document_id": str(task.document_id),
                            "collection_retry_attempt": retry_attempt,
                        },
                    )
                )
    return retry_plan, tasks, resume_token


@router.post(
    "/collections/{collection_id}/processing/retry",
    response_model=CollectionProcessingResponse,
)
@idempotent_mutation
async def retry_collection_processing(
    collection_id: uuid.UUID,
    payload: CollectionProcessingRetryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: EditorDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey = None,
) -> CollectionProcessingResponse:
    _require_idempotency_key(idempotency_key)
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="write",
        lock=True,
    )
    plan = await session.scalar(
        select(ArchitecturePlan)
        .where(
            ArchitecturePlan.tenant_id == principal.tenant_id,
            ArchitecturePlan.collection_id == collection.id,
            ArchitecturePlan.processing_job_id.is_not(None),
        )
        .order_by(ArchitecturePlan.plan_version.desc())
        .limit(1)
    )
    job = (
        await session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.tenant_id == principal.tenant_id,
                ProcessingJob.id == plan.processing_job_id,
                ProcessingJob.job_type == "collection_processing",
            )
            .with_for_update()
        )
        if plan is not None and plan.processing_job_id is not None
        else None
    )
    if plan is None or job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "COLLECTION_PROCESSING_JOB_NOT_FOUND"},
        )

    resumed_plan = plan
    resume_token: str | None = None
    tasks: list[AnalysisTask] = []
    retry_stage = str(job.progress.get("stage", ""))
    if retry_stage == "package_failed":
        await _prepare_collection_package_retry(
            session,
            collection=collection,
            job=job,
            plan=plan,
            actor_user_id=principal.user_id,
            enqueue_finalizer=True,
        )
    elif retry_stage == "semantic_finalizer_failed":
        await _prepare_collection_finalizer_retry(
            session,
            collection=collection,
            job=job,
            plan=plan,
            actor_user_id=principal.user_id,
        )
    else:
        resumed_plan, tasks, resume_token = await _prepare_collection_analysis_retry(
            session,
            collection=collection,
            job=job,
            plan=plan,
            actor_user_id=principal.user_id,
            requested_hard_cap=payload.credit_hard_cap,
        )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.processing_retried",
        target_type="processing_job",
        target_id=str(job.id),
        metadata={
            "collection_id": str(collection.id),
            "architecture_plan_id": str(resumed_plan.id),
            "retry_stage": retry_stage,
            "hard_cap": str(job.cost_estimate.get("hard_cap", "0")),
        },
    )
    await session.commit()
    if request.app.state.settings.local_analysis_worker_enabled:
        from akc_api.main import _execute_local_analysis_task

        for task in tasks:
            if task.status == "queued":
                background_tasks.add_task(_execute_local_analysis_task, request.app, task.id)
    return _processing_control_response(
        collection=collection,
        plan=resumed_plan,
        job=job,
        processing_resume_token=resume_token,
    )


@router.post("/internal/collections/finalize", include_in_schema=False)
async def finalize_collection_processing(
    payload: CollectionFinalizerRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    signature: Annotated[
        str | None,
        Header(alias="X-AKC-Collection-Finalizer-Signature"),
    ] = None,
) -> dict[str, Any]:
    """Consume one scheduler-claimed extraction terminal through public gates."""

    expected_signature = (
        "sha256="
        + hmac.new(
            request.app.state.settings.effective_collection_finalizer_hmac_secret,
            _canonical_json(payload.model_dump(mode="json")),
            hashlib.sha256,
        ).hexdigest()
    )
    if signature is None or not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(
            status_code=401,
            detail={"code": "COLLECTION_FINALIZER_SIGNATURE_INVALID"},
        )
    await set_rls_context(
        session,
        tenant_id=payload.tenant_id,
        user_id=payload.actor_user_id,
    )
    event = await session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.id == payload.event_id,
            OutboxEvent.tenant_id == payload.tenant_id,
            OutboxEvent.aggregate_type == "collection_processing",
            OutboxEvent.aggregate_id == payload.processing_job_id,
            OutboxEvent.event_type == "collection.semantic.compile.requested.v1",
            OutboxEvent.dead_lettered_at.is_(None),
        )
    )
    job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.tenant_id == payload.tenant_id,
            ProcessingJob.id == payload.processing_job_id,
            ProcessingJob.job_type == "collection_processing",
        )
    )
    plan = await session.scalar(
        select(ArchitecturePlan).where(
            ArchitecturePlan.tenant_id == payload.tenant_id,
            ArchitecturePlan.collection_id == payload.collection_id,
            ArchitecturePlan.id == payload.architecture_plan_id,
            ArchitecturePlan.processing_job_id == payload.processing_job_id,
        )
    )
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == payload.tenant_id,
            Membership.user_id == payload.actor_user_id,
            Membership.role.in_(("owner", "admin", "editor")),
        )
    )
    expected_event_payload = {
        "collection_id": str(payload.collection_id),
        "processing_job_id": str(payload.processing_job_id),
        "architecture_plan_id": str(payload.architecture_plan_id),
        "actor_user_id": str(payload.actor_user_id),
        "tenant_id": str(payload.tenant_id),
    }
    if (
        event is None
        or job is None
        or plan is None
        or membership is None
        or any(event.payload.get(key) != value for key, value in expected_event_payload.items())
        or str(job.requested_options.get("initiating_user_id", plan.created_by))
        != str(payload.actor_user_id)
        or str(job.requested_options.get("architecture_plan_id")) != str(plan.id)
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_FINALIZER_SCOPE_INVALID"},
        )
    if job.status == "failed" and str(job.progress.get("stage", "")) == "package_failed":
        retry_collection = await session.get(Collection, payload.collection_id)
        if retry_collection is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_FINALIZER_SCOPE_INVALID"},
            )
        await _prepare_collection_package_retry(
            session,
            collection=retry_collection,
            job=job,
            plan=plan,
            actor_user_id=payload.actor_user_id,
            enqueue_finalizer=False,
        )
        await session.commit()
        await set_rls_context(
            session,
            tenant_id=payload.tenant_id,
            user_id=payload.actor_user_id,
        )
    if job.status in {"completed", "failed", "cancelled"}:
        return {
            "collection_id": str(payload.collection_id),
            "processing_job_id": str(job.id),
            "status": job.status,
            "stage": str(job.progress.get("stage", "")),
        }
    processing_stage = str(job.progress.get("stage", ""))
    if job.status != "running" or processing_stage not in {
        "semantic_compile_queued",
        "ready_for_packaging",
    }:
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_FINALIZER_NOT_READY"},
        )
    principal = Principal(
        user_id=payload.actor_user_id,
        tenant_id=payload.tenant_id,
        roles=frozenset({membership.role}),
        scopes=frozenset({"api:read", "api:write", "exports:read"}),
        auth_type="collection_finalizer",
    )
    module_rows = job.requested_options.get("output_modules", [])
    module_keys = [
        str(row["module_key"])
        for row in module_rows
        if isinstance(row, dict) and isinstance(row.get("module_key"), str)
    ]
    if processing_stage == "semantic_compile_queued":
        compile_payload = CollectionCompileRequest(
            approve_estimate=True,
            mode="collection_processing_runtime",
            approved_preflight_sha256=str(job.requested_options["approved_preflight_sha256"]),
            approved_estimate_sha256=str(job.requested_options["approved_estimate_sha256"]),
            credit_hard_cap=Decimal(str(job.cost_estimate["hard_cap"])),
            overage_policy=cast(Any, job.cost_estimate["overage_policy"]),
            knowledge_blueprint_id=str(job.requested_options["knowledge_blueprint_id"]),
            knowledge_blueprint_registry_sha256=str(
                job.requested_options["knowledge_blueprint_registry_sha256"]
            ),
            knowledge_blueprint_module_sha256=str(
                job.requested_options["knowledge_blueprint_module_sha256"]
            ),
            output_modules=cast(Any, module_keys),
        )
        compile_handler = cast(Any, inspect.unwrap(compile_collection))
        compiled = await compile_handler(
            payload.collection_id,
            compile_payload,
            request,
            background_tasks,
            principal,
            session,
            f"collection-finalizer:{event.id}:compile",
        )
        if compiled.status == "failed":
            return {
                "collection_id": str(payload.collection_id),
                "processing_job_id": str(job.id),
                "status": "failed",
                "stage": "semantic_failed",
            }
    await set_rls_context(
        session,
        tenant_id=payload.tenant_id,
        user_id=payload.actor_user_id,
    )
    export_handler = cast(Any, inspect.unwrap(export_collection))
    exported = await export_handler(
        payload.collection_id,
        CollectionExportRequest(profiles=["complete_knowledge_v1"]),
        request,
        principal,
        session,
        f"collection-finalizer:{event.id}:package",
    )
    return {
        "collection_id": str(payload.collection_id),
        "processing_job_id": str(job.id),
        "status": "completed",
        "stage": "completed",
        "export_id": str(exported.export_id),
        "package_manifest_id": str(exported.package_manifest_id),
    }


@router.delete(
    "/collections/{collection_id}",
    response_model=CollectionDeleteResponse,
)
@idempotent_mutation
async def delete_collection(
    collection_id: uuid.UUID,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
    codec: CollectionMetadataDep,
    idempotency_key: IdempotencyKey = None,
) -> CollectionDeleteResponse:
    _require_idempotency_key(idempotency_key)
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="write",
        lock=True,
        include_deleted=True,
    )
    if collection.status == "PURGED":
        return CollectionDeleteResponse(
            collection_id=collection.id,
            status="PURGED",
            purged_package_objects=0,
            message="Collection metadata was already purged; shared project sources were retained.",
        )
    if collection.status == "PROCESSING":
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_ACTIVE_PROCESSING_CANCEL_REQUIRED"},
        )
    cancel_runtime = (
        collection.status == "PAUSED" and collection.paused_from == "PROCESSING"
    ) or collection.status in {"VERIFYING_OUTPUT", "KNOWLEDGE_COMPILING", "PACKAGING"}
    if cancel_runtime:
        cancelled_from = collection.status
        processing_job = await session.scalar(
            select(ProcessingJob)
            .join(
                ArchitecturePlan,
                ArchitecturePlan.processing_job_id == ProcessingJob.id,
            )
            .where(
                ProcessingJob.tenant_id == principal.tenant_id,
                ProcessingJob.job_type == "collection_processing",
                ProcessingJob.status.in_(("running", "paused")),
                ArchitecturePlan.tenant_id == principal.tenant_id,
                ArchitecturePlan.collection_id == collection.id,
            )
            .order_by(ArchitecturePlan.plan_version.desc())
            .with_for_update()
            .limit(1)
        )
        if processing_job is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "COLLECTION_ACTIVE_FINALIZATION_JOB_MISSING"},
            )
        bindings = list(
            await session.scalars(
                select(CollectionProcessingTaskBinding)
                .where(
                    CollectionProcessingTaskBinding.tenant_id == principal.tenant_id,
                    CollectionProcessingTaskBinding.collection_id == collection.id,
                    CollectionProcessingTaskBinding.processing_job_id == processing_job.id,
                    CollectionProcessingTaskBinding.status.in_(("active", "paused")),
                )
                .with_for_update()
            )
        )
        for binding in bindings:
            binding.status = "detached"
            binding.settled_at = utcnow()
        actual = dict(processing_job.cost_actual or {})
        reserved = _money(actual.get("reserved"))
        consumed = _money(actual.get("consumed"))
        released = _money(actual.get("released"))
        remaining = max(Decimal("0"), reserved - consumed - released)
        if remaining > 0:
            await credit_entry(
                session,
                tenant_id=principal.tenant_id,
                operation_key=f"collection:{processing_job.id}:cancel-release",
                entry_type="release",
                credits=remaining,
                job_id=processing_job.id,
                metadata={
                    "collection_id": str(collection.id),
                    "reason": "active_collection_deleted",
                    "cancelled_from": cancelled_from,
                },
            )
            released += remaining
            actual["released"] = str(released)
            processing_job.cost_actual = actual
            await _emit_collection_event(
                session,
                collection=collection,
                event_type="credits.released.v1",
                job_id=processing_job.id,
                payload={
                    "collection_id": str(collection.id),
                    "processing_job_id": str(processing_job.id),
                    "credits": str(remaining),
                    "reason": "active_collection_deleted",
                    "cancelled_from": cancelled_from,
                },
            )
        pending_finalizers = list(
            await session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.tenant_id == principal.tenant_id,
                    OutboxEvent.aggregate_type == "collection_processing",
                    OutboxEvent.aggregate_id == processing_job.id,
                    OutboxEvent.event_type == "collection.semantic.compile.requested.v1",
                    OutboxEvent.published_at.is_(None),
                )
                .with_for_update()
            )
        )
        cancelled_at = utcnow()
        for event in pending_finalizers:
            event.published_at = cancelled_at
            event.dead_lettered_at = cancelled_at
            event.last_error = "collection_deleted_during_finalization"
        processing_job.status = "cancelled"
        processing_job.completed_at = cancelled_at
        processing_job.progress = {
            **processing_job.progress,
            "stage": "cancelled",
            "detached_bindings": len(bindings),
            "cancelled_finalizer_events": len(pending_finalizers),
        }
        processing_job.error = {
            "code": "COLLECTION_DELETED_DURING_ACTIVE_RUNTIME",
            "cancelled_from": cancelled_from,
        }
    _transition(collection, "CANCEL_REQUESTED", reason="USER_REQUESTED_DELETION")
    collection.deletion_requested_at = utcnow()
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="collection.deletion.requested.v1",
        payload={
            "collection_id": str(collection.id),
            "status": collection.status,
        },
    )
    packages = list(
        await session.scalars(
            select(PackageManifest)
            .where(
                PackageManifest.tenant_id == principal.tenant_id,
                PackageManifest.collection_id == collection.id,
            )
            .with_for_update()
        )
    )
    package_objects = sorted(
        {package.storage_key for package in packages if package.storage_key is not None}
    )
    package_plan_scopes = list(
        await session.execute(
            select(ArchitecturePlan.processing_job_id, ArchitecturePlan.id).where(
                ArchitecturePlan.tenant_id == principal.tenant_id,
                ArchitecturePlan.collection_id == collection.id,
            )
        )
    )
    package_objects = sorted(
        set(package_objects)
        | {
            (
                f"tenants/{principal.tenant_id}/projects/{collection.project_id}/"
                f"collections/{collection.id}/exports/processing/"
                f"{processing_job_id or plan_id}/complete-knowledge.zip"
            )
            for processing_job_id, plan_id in package_plan_scopes
        }
    )
    purged_objects = 0
    try:
        for storage_key in package_objects:
            purged_objects += int(
                await request.app.state.object_store.delete("exports", storage_key)
            )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "COLLECTION_PACKAGE_PURGE_UNAVAILABLE"},
        ) from exc

    export_ids = {package.export_id for package in packages if package.export_id is not None}
    exports = (
        list(
            await session.scalars(
                select(Export)
                .where(
                    Export.tenant_id == principal.tenant_id,
                    Export.id.in_(export_ids),
                )
                .with_for_update()
            )
        )
        if export_ids
        else []
    )
    for export_row in exports:
        export_row.status = "deleted"
        export_row.storage_key = None
        export_row.sha256 = None
        export_row.size_bytes = None
        export_row.completed_at = None
    for package_row in packages:
        package_row.status = "invalidated"
        package_row.storage_key = None
        package_row.package_sha256 = None
        package_row.size_bytes = None
        package_row.completed_at = None
        package_row.warnings = [*package_row.warnings, "collection_purged"]

    roots = list(
        await session.scalars(
            select(CollectionSourceRoot)
            .where(
                CollectionSourceRoot.tenant_id == principal.tenant_id,
                CollectionSourceRoot.collection_id == collection.id,
            )
            .with_for_update()
        )
    )
    files = list(
        await session.scalars(
            select(CollectionFile)
            .where(
                CollectionFile.tenant_id == principal.tenant_id,
                CollectionFile.collection_id == collection.id,
            )
            .with_for_update()
        )
    )
    for file_row in files:
        file_row.version_candidate_of = None
    await session.flush()
    for root_row in roots:
        protected_name = codec.encrypt_source_root_display_name(
            "purged",
            tenant_id=root_row.tenant_id,
            collection_id=root_row.collection_id,
            source_root_id=root_row.id,
        )
        root_row.display_name_ciphertext = protected_name.ciphertext
        root_row.metadata_key_id = protected_name.key_id
        root_row.source_fingerprint = _sha256(f"purged-root:{root_row.id}".encode("ascii"))
        root_row.status = "purged"
    for file_row in files:
        tombstone_path = f"purged/{file_row.id.hex}"
        protected_path = codec.encrypt_file_relative_path(
            tombstone_path,
            tenant_id=file_row.tenant_id,
            collection_id=file_row.collection_id,
            source_root_id=file_row.source_root_id,
            file_id=file_row.id,
        )
        protected_name = codec.encrypt_file_display_name(
            "purged",
            tenant_id=file_row.tenant_id,
            collection_id=file_row.collection_id,
            source_root_id=file_row.source_root_id,
            file_id=file_row.id,
        )
        blind_index = codec.relative_path_blind_index(
            tombstone_path,
            tenant_id=file_row.tenant_id,
            collection_id=file_row.collection_id,
            source_root_id=file_row.source_root_id,
        )
        file_row.source_file_id = None
        file_row.relative_path_ciphertext = protected_path.ciphertext
        file_row.display_name_ciphertext = protected_name.ciphertext
        file_row.metadata_key_id = protected_path.key_id
        file_row.relative_path_blind_index = blind_index.digest
        file_row.relative_path_blind_index_key_id = blind_index.key_id
        file_row.size_bytes = 0
        file_row.last_modified_ms = None
        file_row.expected_mime = "application/octet-stream"
        file_row.detected_mime = None
        file_row.sha256 = _sha256(f"purged-file:{file_row.id}".encode("ascii"))
        file_row.quick_fingerprint = None
        file_row.status = "purged"
        file_row.error_code = "COLLECTION_PURGED"
    uploads = list(
        await session.scalars(
            select(CollectionUploadSession)
            .where(
                CollectionUploadSession.tenant_id == principal.tenant_id,
                CollectionUploadSession.collection_id == collection.id,
            )
            .with_for_update()
        )
    )
    for upload in uploads:
        upload.total_bytes = 0
        upload.completed_files = 0
        upload.active_files = 0
        upload.failed_files = upload.total_files
        upload.duplicate_files = 0
        upload.browser_resume_token_hash = _sha256(f"purged-upload:{upload.id}".encode("ascii"))
        upload.status = "aborted"
        upload.expires_at = utcnow()
        upload.completed_at = utcnow()
    collection.name = "purged"
    collection.description = None
    collection.profile = {}
    _transition(collection, "PURGED", reason="COLLECTION_METADATA_PURGED")
    collection.purged_at = utcnow()
    await _emit_collection_event(
        session,
        collection=collection,
        event_type="collection.purged.v1",
        payload={
            "collection_id": str(collection.id),
            "purged_package_objects": purged_objects,
            "shared_source_objects_retained": True,
            "status": collection.status,
        },
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.purged",
        target_type="collection",
        target_id=str(collection.id),
        metadata={
            "purged_package_objects": purged_objects,
            "shared_source_objects_retained": True,
        },
    )
    await session.commit()
    return CollectionDeleteResponse(
        collection_id=collection.id,
        status="PURGED",
        purged_package_objects=purged_objects,
        message=(
            "Collection metadata and collection-owned packages were purged; "
            "shared project sources were retained."
        ),
    )
