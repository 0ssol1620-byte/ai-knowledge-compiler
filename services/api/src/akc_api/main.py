"""FastAPI control plane and runnable local vertical slice."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, BinaryIO, Literal, cast

from akc_cir import DocumentClassification, PageState
from akc_exporters import MergePolicy
from akc_scheduler.webhooks import (
    WebhookDnsError,
    WebhookTargetError,
    encrypt_secret,
    generate_webhook_secret,
    validate_webhook_url,
)
from akc_security import (
    ALLOWED_EXTENSIONS,
    PLAN_LIMITS,
    CdrRequest,
    CdrResult,
    CdrStatus,
    InMemoryPdfSecretStore,
    PlanTier,
    RedisPdfSecretStore,
    UnsafePreviewError,
    detect_sensitive_data,
    ensure_portable_markdown_safe,
    redact_preview_png,
    sanitize_display_filename,
    validate_cdr_result,
    validate_upload_stream,
)
from akc_telemetry import (
    PROMETHEUS_CONTENT_TYPE,
    create_telemetry_runtime,
    install_fastapi_observability,
    record_abuse_control_decision,
    record_product_analytics_snapshot,
    render_prometheus,
)
from akc_url_fetcher.fetcher import UrlFetchError
from akc_url_fetcher.models import UrlFetchTask
from akc_url_fetcher.schemas import UrlFetchTaskResponse, url_fetch_task_response
from akc_url_fetcher.security import UrlSecretCodec
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.abuse import (
    CaptchaProviderUnavailable,
    CaptchaRejectedError,
    CaptchaRequiredError,
    IdentityHasher,
    RateLimitBackendUnavailable,
    RateLimitDecision,
    RateLimitPolicy,
    TrustedProxyIdentityResolver,
    TurnstileCaptchaProvider,
    UnavailableCaptchaProvider,
    build_rate_limiter,
    enforce_captcha,
    rate_limit_http_exception,
)
from akc_api.abuse_repository import (
    DuplicateFreeSource,
    existing_free_source,
    free_source_claim,
    lock_current_free_usage_day,
    reserve_free_usage,
)
from akc_api.auth_api import begin_mfa_login
from akc_api.auth_api import router as advanced_auth_router
from akc_api.auth_security import MfaSecurity, OidcClient, OidcTransactionCipher
from akc_api.batch_api import router as batch_router
from akc_api.block_merge import three_way_merge
from akc_api.cdr import build_cdr_adapter
from akc_api.database import Database, get_session, set_rls_context
from akc_api.deletions import (
    DeletionTargetType,
    create_deletion_request,
    get_deletion_receipt,
    process_deletion_request,
)
from akc_api.document_versions import (
    archive_active_document_version,
    clear_active_document_projection,
    document_version_diff,
    read_public_document_version_snapshot,
)
from akc_api.domain_api import router as domain_api_router
from akc_api.feature_flags import (
    EXISTING_VAULT_MERGE_FLAG,
    ONTOLOGY_EXPORT_FLAG,
    feature_enabled,
)
from akc_api.free_tier import (
    FreeTierCapExceeded,
    FreeTierCaps,
    FreeUsageDelta,
    estimate_gpu_cost,
    queue_priority_for_plan,
)
from akc_api.idempotency import idempotent_mutation
from akc_api.knowledge_api import router as knowledge_api_router
from akc_api.malware import (
    MalwareDetectedError,
    MalwareScanError,
    malware_scanner_ready,
    scan_quarantined_stream,
)
from akc_api.models import (
    AnalysisTask,
    ApiKey,
    Block,
    BlockRevision,
    CreditAccount,
    CreditLedger,
    DeletionReceipt,
    DeletionRequest,
    Document,
    DocumentSemanticClassification,
    DocumentVersion,
    EmailVerificationToken,
    Export,
    FeatureFlag,
    GpuProviderInvocation,
    JobEvent,
    KnowledgeNote,
    Membership,
    ModelRegistry,
    OutboxEvent,
    Page,
    PageAsset,
    PageAttempt,
    ProcessingJob,
    Project,
    ReviewItem,
    SourceFile,
    Tenant,
    UploadSession,
    User,
    WebhookDelivery,
    WebhookEndpoint,
    utcnow,
)
from akc_api.page_attempts import (
    TERMINAL_PAGE_STATES,
    create_page_attempt,
    latest_attempts_for_pages,
    next_attempt_number,
)
from akc_api.payment_routes import router as payment_router
from akc_api.payments import build_payment_provider
from akc_api.pdf_passwords import router as pdf_password_router
from akc_api.product_analytics import (
    ProductAnalyticsSnapshot,
    build_product_analytics_snapshot,
    product_analytics_enabled,
    set_product_analytics_enabled,
)
from akc_api.product_analytics import (
    event_router as product_analytics_event_router,
)
from akc_api.project_access import (
    ProjectCapability,
    project_access_predicate,
    require_project_access,
)
from akc_api.project_access_api import router as project_access_router
from akc_api.project_access_models import ProjectMembership
from akc_api.routing_runtime import validate_registry_binding
from akc_api.schemas import (
    AnalyzeResponse,
    ApiKeyCreate,
    ApiKeyCreated,
    BlockModelMergeRequest,
    BlockModelMergeResponse,
    BlockPatch,
    BlockResponse,
    CompileRequest,
    CreditBalance,
    DeleteReceiptResponse,
    DeletionRequestResponse,
    DispatchDlqClose,
    DispatchDlqFallback,
    DocumentCreate,
    DocumentResponse,
    DocumentVersionDiffResponse,
    DocumentVersionListResponse,
    DocumentVersionSummary,
    EstimateResponse,
    EventWire,
    ExportCreate,
    ExportResponse,
    JobExportCreate,
    JobResponse,
    LoginRequest,
    MfaRequiredResponse,
    ModelPromotionRequest,
    ModelRetireRequest,
    ModelRollbackRequest,
    MultipartUploadPlan,
    PageResponse,
    PrivacyPatch,
    ProjectCreate,
    ProjectPatch,
    ProjectResponse,
    RegisterRequest,
    ReprocessRequest,
    ResendVerificationRequest,
    ReviewResolve,
    ReviewRuleApply,
    SemanticClassificationSummary,
    SessionResponse,
    UploadComplete,
    UploadCompleted,
    UploadedPartResponse,
    UploadedPartsResponse,
    UploadInitiate,
    UploadInitiated,
    UploadPartSignRequest,
    UploadPartTargetResponse,
    UploadPartTargetsResponse,
    UploadSessionResponse,
    VaultMergePreviewResponse,
    VerificationDispatchResponse,
    VerifyEmailRequest,
    WebhookCreate,
    WebhookCreated,
    WebhookPatch,
    WebhookResponse,
)
from akc_api.security import (
    Principal,
    create_session_token,
    generate_api_key,
    get_principal,
    hash_password,
    require_roles,
    verify_password,
)
from akc_api.services import (
    audit,
    build_export_bundle,
    credit_entry,
    emit_event,
    estimate_document,
    run_compile_job,
)
from akc_api.settings import Settings, get_settings
from akc_api.storage import (
    CompletedPart,
    LocalObjectStore,
    MultipartUploadNotFoundError,
    ObjectStore,
    build_object_store,
)
from akc_api.team_api import TeamInvitationTokenCodec
from akc_api.team_api import router as team_router
from akc_api.vault_merge import (
    DEFAULT_VAULT_ZIP_LIMITS,
)
from akc_api.vault_merge import (
    preview_vault_merge as build_vault_merge_preview,
)
from akc_api.verification import (
    DevelopmentCaptureProvider,
    ResendVerificationDeliveryProvider,
    UnavailableVerificationDeliveryProvider,
    VerificationDeliveryProvider,
    VerificationPayloadCipher,
    VerificationTokenCodec,
    VerificationTokenStatus,
    normalize_public_email,
    verification_token_status,
)
from akc_api.verification_repository import (
    deliver_verification,
    enqueue_verification,
)

router = APIRouter(prefix="/v1")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
EditorDep = Annotated[Principal, Depends(require_roles("owner", "admin", "editor"))]
ReviewerDep = Annotated[Principal, Depends(require_roles("owner", "admin", "editor", "reviewer"))]
AdminDep = Annotated[Principal, Depends(require_roles("owner", "admin"))]


def _slug(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{value[:50] or 'workspace'}-{secrets.token_hex(3)}"


def _plan_tier(plan_code: str) -> PlanTier:
    if plan_code.casefold() in {"team", "enterprise"}:
        return PlanTier.TEAM
    if plan_code.casefold() in {"personal", "pro"}:
        return PlanTier.PRO
    return PlanTier.FREE


def _plan_upload_limit(plan_code: str, settings: Settings) -> int:
    return min(
        settings.max_upload_bytes,
        PLAN_LIMITS[_plan_tier(plan_code)].max_file_bytes,
    )


def _multipart_plan(
    upload: UploadSession,
    settings: Settings,
) -> MultipartUploadPlan | None:
    if upload.upload_mode != "multipart":
        return None
    if upload.multipart_part_size is None or upload.multipart_part_count is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "UPLOAD_STATE_CORRUPT"},
        )
    return MultipartUploadPlan(
        part_size=upload.multipart_part_size,
        part_count=upload.multipart_part_count,
        presign_batch_size=settings.multipart_presign_batch_size,
        max_concurrency=settings.multipart_client_concurrency,
        max_retries=settings.multipart_client_max_retries,
        sign_parts_url=f"/v1/uploads/{upload.id}/parts/sign",
        list_parts_url=f"/v1/uploads/{upload.id}/parts",
    )


def _document_version_summary(version: DocumentVersion) -> DocumentVersionSummary:
    return DocumentVersionSummary(
        document_id=version.document_id,
        version=version.version,
        source_file_id=version.source_file_id,
        source_sha256=version.source_sha256,
        source_filename=version.source_filename,
        source_mime_type=version.source_mime_type,
        source_size_bytes=version.source_size_bytes,
        cir_snapshot_sha256=version.cir_snapshot_sha256,
        input_revision_hash=version.input_revision_hash,
        policy_version=version.policy_version,
        model_revision=version.model_revision,
        prompt_revision=version.prompt_revision,
        normalization_revision=version.normalization_revision,
        akmp_schema_version=version.akmp_schema_version,
        status=cast(Any, version.status),
        archived_at=version.archived_at,
        created_at=version.created_at,
    )


async def _supersede_document_work(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    previous_version: int,
    next_version: int,
    now: datetime,
) -> dict[str, int]:
    """Fence old-version work and release only its outstanding reservations."""

    analysis_tasks = list(
        (
            await session.scalars(
                select(AnalysisTask)
                .where(
                    AnalysisTask.tenant_id == tenant_id,
                    AnalysisTask.document_id == document_id,
                    AnalysisTask.status.in_(("queued", "running")),
                )
                .with_for_update()
            )
        ).all()
    )
    for task in analysis_tasks:
        task.status = "dead_letter"
        task.last_error_code = "SOURCE_VERSION_SUPERSEDED"
        task.lease_token = None
        task.lease_expires_at = None
        task.available_at = now
        task.completed_at = now
        task.updated_at = now

    jobs = list(
        (
            await session.scalars(
                select(ProcessingJob)
                .where(
                    ProcessingJob.tenant_id == tenant_id,
                    ProcessingJob.document_id == document_id,
                    ProcessingJob.status.in_(("queued", "running", "waiting_review")),
                )
                .with_for_update()
            )
        ).all()
    )
    for job in jobs:
        totals = {
            str(entry_type): Decimal(total or 0)
            for entry_type, total in (
                await session.execute(
                    select(
                        CreditLedger.entry_type,
                        func.sum(CreditLedger.credits),
                    )
                    .where(
                        CreditLedger.tenant_id == tenant_id,
                        CreditLedger.job_id == job.id,
                        CreditLedger.entry_type.in_(("reserve", "consume", "release")),
                    )
                    .group_by(CreditLedger.entry_type)
                )
            ).all()
        }
        outstanding = max(
            Decimal("0"),
            totals.get("reserve", Decimal("0"))
            - totals.get("consume", Decimal("0"))
            - totals.get("release", Decimal("0")),
        )
        job.status = "cancelled"
        job.completed_at = now
        job.error = {
            "code": "SOURCE_VERSION_SUPERSEDED",
            "retryable": False,
            "previous_version": previous_version,
            "next_version": next_version,
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
                    "reason": "source_version_superseded",
                    "previous_version": previous_version,
                    "next_version": next_version,
                },
            )
        )
        if outstanding > 0:
            await credit_entry(
                session,
                tenant_id=tenant_id,
                operation_key=(f"job:{job.id}:source-version-{next_version}:release"),
                entry_type="release",
                credits=outstanding,
                job_id=job.id,
                metadata={
                    "reason": "source_version_superseded",
                    "previous_version": previous_version,
                    "next_version": next_version,
                },
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
                        "reason": "source_version_superseded",
                    },
                )
            )

    version_id = f"{document_id}:v{previous_version}"
    invocations = list(
        (
            await session.scalars(
                select(GpuProviderInvocation)
                .where(
                    GpuProviderInvocation.tenant_id == tenant_id,
                    GpuProviderInvocation.document_id == document_id,
                    GpuProviderInvocation.document_version_id == version_id,
                )
                .with_for_update()
            )
        ).all()
    )
    terminal = {"completed", "failed", "dead_letter", "cancelled"}
    for invocation in invocations:
        # The immutable invocation remains linked to the archived document
        # version even after its mutable Page row is removed.
        invocation.page_id = None
        if invocation.status in terminal:
            continue
        invocation.cancellation_reason = "source_version_superseded"
        invocation.available_at = now
        invocation.lease_token = None
        invocation.lease_expires_at = None
        invocation.updated_at = now
        if invocation.provider_job_id is None:
            invocation.status = "cancelled"
            invocation.last_error_code = "GPU_SOURCE_VERSION_SUPERSEDED"
            invocation.completed_at = now
        else:
            invocation.status = "cancel_requested"
            invocation.last_error_code = "GPU_CANCEL_PENDING"

    return {
        "analysis_tasks": len(analysis_tasks),
        "processing_jobs": len(jobs),
        "gpu_invocations": len(invocations),
    }


async def _source_object_matches(
    store: Any,
    *,
    object_key: str,
    expected_sha256: str,
    expected_size: int,
) -> bool:
    size = 0
    digest = hashlib.sha256()
    try:
        with tempfile.SpooledTemporaryFile(
            max_size=8 * 1024 * 1024,
            mode="w+b",
        ) as staged:
            await store.download_source(object_key, staged)
            while chunk := staged.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
    except (BotoCoreError, ClientError, FileNotFoundError, OSError, KeyError):
        return False
    return size == expected_size and secrets.compare_digest(
        digest.hexdigest(),
        expected_sha256,
    )


async def _tenant_upload(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    upload_id: uuid.UUID,
    lock: bool = False,
    principal: Principal | None = None,
    capability: ProjectCapability = "read",
) -> UploadSession:
    statement = (
        select(UploadSession)
        .join(
            Project,
            (Project.tenant_id == UploadSession.tenant_id)
            & (Project.id == UploadSession.project_id),
        )
        .join(
            Document,
            (Document.tenant_id == UploadSession.tenant_id)
            & (Document.id == UploadSession.document_id),
        )
        .where(
            UploadSession.tenant_id == tenant_id,
            UploadSession.id == upload_id,
            Project.deletion_requested_at.is_(None),
            Document.deletion_requested_at.is_(None),
        )
    )
    if lock:
        statement = statement.with_for_update()
    upload = await session.scalar(statement)
    if upload is None:
        raise HTTPException(status_code=404, detail={"code": "UPLOAD_NOT_FOUND"})
    if principal is not None:
        await require_project_access(
            session,
            principal=principal,
            project_id=upload.project_id,
            capability=capability,
        )
    return upload


async def _abort_provider_upload(request: Request, upload: UploadSession) -> None:
    if upload.upload_mode != "multipart" or not upload.provider_upload_id:
        return
    try:
        await request.app.state.object_store.abort_multipart_upload(
            object_key=upload.object_key,
            provider_upload_id=upload.provider_upload_id,
        )
    except MultipartUploadNotFoundError:
        # Provider abort is intentionally idempotent. A missing upload is the
        # same terminal state and must not reveal provider details.
        return
    except (BotoCoreError, ClientError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "OBJECT_STORE_UNAVAILABLE"},
        ) from exc


async def _expire_upload(
    request: Request,
    session: AsyncSession,
    upload: UploadSession,
) -> None:
    await _abort_provider_upload(request, upload)
    await request.app.state.object_store.delete("quarantine", upload.object_key)
    upload.status = "expired"
    document = await session.scalar(
        select(Document).where(
            Document.tenant_id == upload.tenant_id,
            Document.id == upload.document_id,
        )
    )
    if (
        document is not None
        and document.source_file_id is None
        and document.status in {"UPLOADING", "QUARANTINED"}
    ):
        document.status = "UPLOAD_EXPIRED"
    await session.commit()


def _session_response(user: User, principal: Principal) -> SessionResponse:
    return SessionResponse(
        user_id=user.id,
        tenant_id=principal.tenant_id,
        email=user.email,
        display_name=user.display_name,
        roles=sorted(principal.roles),
        email_verified=user.email_verified_at is not None,
    )


def _free_caps(settings: Settings) -> FreeTierCaps:
    return FreeTierCaps(
        files=settings.free_daily_file_cap,
        pages=settings.free_daily_page_cap,
        gpu_cost_usd=settings.free_daily_gpu_cost_usd_cap,
    )


def _client_subject(request: Request) -> str:
    resolver = cast(
        TrustedProxyIdentityResolver,
        request.app.state.client_identity_resolver,
    )
    identity = resolver.resolve_request(request)
    return identity.pseudonym


def _account_subject(request: Request, value: str) -> str:
    hasher = cast(IdentityHasher, request.app.state.identity_hasher)
    return hasher.pseudonymize(
        purpose="account",
        value=value.strip().casefold(),
    )


def _tenant_subject(request: Request, tenant_id: uuid.UUID) -> str:
    hasher = cast(IdentityHasher, request.app.state.identity_hasher)
    return hasher.pseudonymize(
        purpose="tenant",
        value=str(tenant_id),
    )


async def _consume_rate_control(
    request: Request,
    *,
    control: str,
    subjects: list[tuple[str, RateLimitPolicy]],
    captcha_action: str | None = None,
) -> None:
    captcha_required = False
    try:
        for subject, policy in subjects:
            decision: RateLimitDecision = await request.app.state.rate_limiter.consume(
                control=control,
                subject=subject,
                policy=policy,
            )
            if not decision.allowed:
                record_abuse_control_decision(control=control, result="limited")
                raise rate_limit_http_exception(decision)
            captcha_required = captcha_required or decision.captcha_required
    except RateLimitBackendUnavailable as exc:
        record_abuse_control_decision(control=control, result="unavailable")
        raise HTTPException(
            status_code=503,
            detail={"code": "ABUSE_CONTROL_UNAVAILABLE"},
        ) from exc
    if captcha_action is not None:
        try:
            await enforce_captcha(
                required=captcha_required,
                token=request.headers.get("X-Captcha-Token"),
                provider=request.app.state.captcha_provider,
                client_identity=_client_subject(request),
                action=captcha_action,
            )
        except CaptchaRequiredError as exc:
            record_abuse_control_decision(control="captcha", result="required")
            raise HTTPException(
                status_code=403,
                detail={"code": "CAPTCHA_REQUIRED"},
            ) from exc
        except CaptchaRejectedError as exc:
            unavailable = isinstance(exc.__cause__, CaptchaProviderUnavailable)
            record_abuse_control_decision(
                control="captcha",
                result="unavailable" if unavailable else "rejected",
            )
            raise HTTPException(
                status_code=503 if unavailable else 403,
                detail={"code": ("CAPTCHA_UNAVAILABLE" if unavailable else "CAPTCHA_REJECTED")},
            ) from exc
    record_abuse_control_decision(control=control, result="allowed")


async def _verified_user(
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


async def _require_verified_for_operation(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    *,
    control: Literal["upload", "analyze", "compile", "export"],
) -> User:
    user = await _verified_user(session, principal)
    settings: Settings = request.app.state.settings
    await _consume_rate_control(
        request,
        control=control,
        subjects=[
            (
                _account_subject(request, str(principal.user_id)),
                RateLimitPolicy(
                    limit=settings.operation_account_limit,
                    window_seconds=settings.operation_window_seconds,
                ),
            ),
            (
                _tenant_subject(request, principal.tenant_id),
                RateLimitPolicy(
                    limit=settings.operation_tenant_limit,
                    window_seconds=settings.operation_window_seconds,
                ),
            ),
        ],
    )
    return user


async def _raise_free_cap(
    request: Request,
    session: AsyncSession,
    *,
    principal: Principal,
    control: str,
    target_type: str,
    target_id: str,
    error: FreeTierCapExceeded,
) -> None:
    await session.rollback()
    async with request.app.state.database.sessions() as audit_session:
        await set_rls_context(
            audit_session,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
        )
        await audit(
            audit_session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action="abuse.free_daily_cap_denied",
            target_type=target_type,
            target_id=target_id,
            metadata={"dimension": error.dimension.value},
        )
        await audit_session.commit()
    record_abuse_control_decision(control=control, result="capped")
    raise HTTPException(
        status_code=429,
        detail={
            "code": "FREE_DAILY_CAP_EXCEEDED",
            "dimension": error.dimension.value,
            "retry_after_seconds": error.retry_after_seconds,
        },
        headers={"Retry-After": str(error.retry_after_seconds)},
    )


async def _dispatch_verification(
    request: Request,
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    delivery_id: uuid.UUID,
) -> None:
    await set_rls_context(session, tenant_id=tenant_id, user_id=user_id)
    delivered = await deliver_verification(
        session,
        delivery_id=delivery_id,
        codec=request.app.state.verification_token_codec,
        cipher=request.app.state.verification_payload_cipher,
        provider=request.app.state.verification_delivery_provider,
        max_attempts=request.app.state.settings.verification_delivery_max_attempts,
        retry_seconds=request.app.state.settings.verification_delivery_retry_seconds,
    )
    await audit(
        session,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="auth.verification_delivery",
        target_type="verification_delivery",
        target_id=str(delivery_id),
        metadata={"result": "delivered" if delivered else "queued_retry"},
    )
    await session.commit()
    record_abuse_control_decision(
        control="email_verify",
        result="delivered" if delivered else "unavailable",
    )


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.effective_cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.access_token_minutes * 60,
        path="/",
    )


async def _tenant_project(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    lock: bool = False,
    principal: Principal | None = None,
    capability: ProjectCapability = "read",
) -> Project:
    statement = select(Project).where(
        Project.tenant_id == tenant_id,
        Project.id == project_id,
        Project.deletion_requested_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    project = await session.scalar(statement)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
    if principal is not None:
        await require_project_access(
            session,
            principal=principal,
            project_id=project.id,
            capability=capability,
        )
    return project


async def _tenant_document(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    lock: bool = False,
    principal: Principal | None = None,
    capability: ProjectCapability = "read",
) -> Document:
    statement = (
        select(Document)
        .join(
            Project,
            (Project.tenant_id == Document.tenant_id) & (Project.id == Document.project_id),
        )
        .where(
            Document.tenant_id == tenant_id,
            Document.id == document_id,
            Document.deletion_requested_at.is_(None),
            Project.deletion_requested_at.is_(None),
        )
    )
    if lock:
        statement = statement.with_for_update()
    document = await session.scalar(statement)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND"})
    if principal is not None:
        await require_project_access(
            session,
            principal=principal,
            project_id=document.project_id,
            capability=capability,
        )
    return document


async def _tenant_url_fetch_task(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    *,
    lock: bool = False,
    principal: Principal | None = None,
    capability: ProjectCapability = "read",
) -> UrlFetchTask:
    statement = (
        select(UrlFetchTask)
        .join(
            Document,
            (Document.tenant_id == UrlFetchTask.tenant_id)
            & (Document.id == UrlFetchTask.document_id),
        )
        .join(
            Project,
            (Project.tenant_id == UrlFetchTask.tenant_id) & (Project.id == UrlFetchTask.project_id),
        )
        .where(
            UrlFetchTask.tenant_id == tenant_id,
            UrlFetchTask.id == task_id,
            Document.deletion_requested_at.is_(None),
            Project.deletion_requested_at.is_(None),
        )
    )
    if lock:
        statement = statement.with_for_update()
    task = await session.scalar(statement)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "URL_FETCH_TASK_NOT_FOUND"},
        )
    if principal is not None:
        await require_project_access(
            session,
            principal=principal,
            project_id=task.project_id,
            capability=capability,
        )
    return task


async def _tenant_job(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    lock: bool = False,
    principal: Principal | None = None,
    capability: ProjectCapability = "read",
) -> ProcessingJob:
    statement = (
        select(ProcessingJob)
        .join(
            Project,
            (Project.tenant_id == ProcessingJob.tenant_id)
            & (Project.id == ProcessingJob.project_id),
        )
        .outerjoin(
            Document,
            (Document.tenant_id == ProcessingJob.tenant_id)
            & (Document.id == ProcessingJob.document_id),
        )
        .where(
            ProcessingJob.tenant_id == tenant_id,
            ProcessingJob.id == job_id,
            Project.deletion_requested_at.is_(None),
            or_(
                ProcessingJob.document_id.is_(None),
                Document.deletion_requested_at.is_(None),
            ),
        )
    )
    if lock:
        statement = statement.with_for_update()
    job = await session.scalar(statement)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND"})
    if principal is not None:
        await require_project_access(
            session,
            principal=principal,
            project_id=job.project_id,
            capability=capability,
        )
    return job


@router.post("/auth/register", response_model=SessionResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    response: Response,
    request: Request,
    session: SessionDep,
) -> SessionResponse:
    settings: Settings = request.app.state.settings
    if not settings.allow_public_registration:
        raise HTTPException(
            status_code=403,
            detail={"code": "PUBLIC_REGISTRATION_DISABLED"},
        )
    if (
        not settings.email_verification_enabled
        or settings.email_verification_provider == "disabled"
    ):
        raise HTTPException(
            status_code=503,
            detail={"code": "EMAIL_VERIFICATION_UNAVAILABLE"},
        )
    email_identity = payload.email.casefold().strip()
    await _consume_rate_control(
        request,
        control="registration",
        subjects=[
            (
                _client_subject(request),
                RateLimitPolicy(
                    limit=settings.register_client_limit,
                    window_seconds=settings.register_window_seconds,
                    captcha_after=settings.register_captcha_after,
                ),
            ),
            (
                _account_subject(request, email_identity),
                RateLimitPolicy(
                    limit=settings.register_account_limit,
                    window_seconds=settings.register_window_seconds,
                    captcha_after=min(
                        settings.register_captcha_after,
                        settings.register_account_limit,
                    ),
                ),
            ),
        ],
        captcha_action="registration",
    )
    try:
        email = normalize_public_email(email_identity)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_EMAIL"},
        ) from exc
    if await session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail={"code": "EMAIL_EXISTS"})
    tenant_id = uuid.uuid4()
    await set_rls_context(session, tenant_id=tenant_id)
    tenant = Tenant(
        id=tenant_id,
        slug=_slug(payload.tenant_name),
        name=payload.tenant_name,
        data_retention_days=settings.default_retention_days,
        private_mode=settings.private_mode,
        training_opt_in=settings.training_opt_in_default,
    )
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
    )
    session.add_all([tenant, user])
    await session.flush()
    membership = Membership(tenant_id=tenant.id, user_id=user.id, role="owner")
    session.add(membership)
    await session.flush()
    enqueued = await enqueue_verification(
        session,
        tenant_id=tenant.id,
        user_id=user.id,
        recipient_email=user.email,
        codec=request.app.state.verification_token_codec,
        cipher=request.app.state.verification_payload_cipher,
        provider_name=settings.email_verification_provider,
        invalidate_existing=False,
    )
    await audit(
        session,
        tenant_id=tenant.id,
        actor_id=user.id,
        action="auth.register",
        target_type="tenant",
        target_id=str(tenant.id),
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail={"code": "REGISTER_CONFLICT"}) from exc
    principal = Principal(
        user_id=user.id,
        tenant_id=tenant.id,
        roles=frozenset({"owner"}),
        scopes=frozenset({"api:read", "api:write"}),
        auth_type="cookie",
    )
    token = create_session_token(
        user_id=user.id,
        tenant_id=tenant.id,
        roles=["owner"],
        settings=settings,
    )
    _set_session_cookie(response, token, settings)
    await _dispatch_verification(
        request,
        session,
        tenant_id=tenant.id,
        user_id=user.id,
        delivery_id=enqueued.delivery_id,
    )
    return _session_response(user, principal)


@router.post(
    "/auth/login",
    response_model=SessionResponse | MfaRequiredResponse,
)
async def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    session: SessionDep,
) -> SessionResponse | MfaRequiredResponse:
    settings: Settings = request.app.state.settings
    email = payload.email.casefold().strip()
    await _consume_rate_control(
        request,
        control="login",
        subjects=[
            (
                _client_subject(request),
                RateLimitPolicy(
                    limit=settings.login_client_limit,
                    window_seconds=settings.login_window_seconds,
                    captcha_after=settings.login_captcha_after,
                ),
            ),
            (
                _account_subject(request, email),
                RateLimitPolicy(
                    limit=settings.login_account_limit,
                    window_seconds=settings.login_window_seconds,
                    captcha_after=settings.login_captcha_after,
                ),
            ),
        ],
        captcha_action="login",
    )
    user = await session.scalar(select(User).where(User.email == email))
    if (
        user is None
        or not user.is_active
        or not verify_password(user.password_hash, payload.password)
    ):
        raise HTTPException(status_code=401, detail={"code": "INVALID_CREDENTIALS"})
    await set_rls_context(session, user_id=user.id)
    memberships = list(
        await session.scalars(
            select(Membership)
            .where(Membership.user_id == user.id)
            .order_by(Membership.created_at.asc(), Membership.tenant_id.asc())
        )
    )
    if not memberships:
        raise HTTPException(status_code=403, detail={"code": "NO_TENANT_MEMBERSHIP"})
    membership: Membership | None = None
    if payload.tenant_slug is None:
        if len(memberships) != 1:
            # Do not choose an arbitrary workspace.  A session and every API
            # key remain bound to one explicit tenant for their entire life.
            raise HTTPException(
                status_code=409,
                detail={"code": "WORKSPACE_SELECTION_REQUIRED"},
            )
        membership = memberships[0]
    else:
        for candidate in memberships:
            # PostgreSQL RLS permits membership discovery by app.user_id but
            # requires the candidate tenant context before reading its slug.
            await set_rls_context(
                session,
                tenant_id=candidate.tenant_id,
                user_id=user.id,
            )
            candidate_tenant = await session.scalar(
                select(Tenant).where(
                    Tenant.id == candidate.tenant_id,
                    Tenant.slug == payload.tenant_slug,
                )
            )
            if candidate_tenant is not None:
                membership = candidate
                break
        if membership is None:
            raise HTTPException(
                status_code=403,
                detail={"code": "WORKSPACE_NOT_AVAILABLE"},
            )
    await set_rls_context(
        session,
        tenant_id=membership.tenant_id,
        user_id=user.id,
    )
    pending_mfa = await begin_mfa_login(
        request=request,
        response=response,
        session=session,
        user=user,
        membership=membership,
        auth_method="password",
    )
    if pending_mfa is not None:
        await audit(
            session,
            tenant_id=membership.tenant_id,
            actor_id=user.id,
            action="auth.primary_login_succeeded",
            target_type="user",
            target_id=str(user.id),
            metadata={"method": "password"},
        )
        await session.commit()
        return pending_mfa
    principal = Principal(
        user_id=user.id,
        tenant_id=membership.tenant_id,
        roles=frozenset({membership.role}),
        scopes=frozenset({"api:read", "api:write"}),
        auth_type="cookie",
    )
    token = create_session_token(
        user_id=user.id,
        tenant_id=membership.tenant_id,
        roles=[membership.role],
        settings=settings,
    )
    _set_session_cookie(response, token, settings)
    await audit(
        session,
        tenant_id=membership.tenant_id,
        actor_id=user.id,
        action="auth.login",
        target_type="user",
        target_id=str(user.id),
    )
    await session.commit()
    return _session_response(user, principal)


def _invalid_verification_token() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "INVALID_OR_EXPIRED_VERIFICATION_TOKEN"},
    )


@router.post("/auth/verify-email", response_model=SessionResponse)
async def verify_email(
    payload: VerifyEmailRequest,
    response: Response,
    request: Request,
    session: SessionDep,
) -> SessionResponse:
    settings: Settings = request.app.state.settings
    await _consume_rate_control(
        request,
        control="email_verify",
        subjects=[
            (
                _client_subject(request),
                RateLimitPolicy(
                    limit=settings.verify_client_limit,
                    window_seconds=settings.verify_window_seconds,
                ),
            )
        ],
    )
    plaintext = payload.token.get_secret_value()
    codec: VerificationTokenCodec = request.app.state.verification_token_codec
    tenant_id = codec.tenant_hint(plaintext)
    if tenant_id is None:
        record_abuse_control_decision(control="email_verify", result="invalid")
        raise _invalid_verification_token()
    await set_rls_context(session, tenant_id=tenant_id)
    token_row = await session.scalar(
        select(EmailVerificationToken)
        .where(
            EmailVerificationToken.tenant_id == tenant_id,
            EmailVerificationToken.token_hash == codec.digest(plaintext),
        )
        .with_for_update()
    )
    if token_row is None or token_row.invalidated_at is not None:
        record_abuse_control_decision(control="email_verify", result="invalid")
        raise _invalid_verification_token()
    token_status = verification_token_status(
        codec=codec,
        plaintext=plaintext,
        expected_digest=token_row.token_hash,
        expires_at=token_row.expires_at,
        consumed_at=token_row.consumed_at,
    )
    if token_status is not VerificationTokenStatus.VALID:
        record_abuse_control_decision(
            control="email_verify",
            result=("expired" if token_status is VerificationTokenStatus.EXPIRED else "invalid"),
        )
        raise _invalid_verification_token()
    user = await session.scalar(select(User).where(User.id == token_row.user_id).with_for_update())
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == token_row.user_id,
        )
    )
    if user is None or membership is None or not user.is_active:
        record_abuse_control_decision(control="email_verify", result="invalid")
        raise _invalid_verification_token()

    now = utcnow()
    consumed_token_id = await session.scalar(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.id == token_row.id,
            EmailVerificationToken.consumed_at.is_(None),
            EmailVerificationToken.invalidated_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(EmailVerificationToken.id)
        .execution_options(synchronize_session=False)
    )
    if consumed_token_id is None:
        record_abuse_control_decision(control="email_verify", result="invalid")
        raise _invalid_verification_token()
    await session.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.tenant_id == tenant_id,
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.id != token_row.id,
            EmailVerificationToken.consumed_at.is_(None),
            EmailVerificationToken.invalidated_at.is_(None),
        )
        .values(invalidated_at=now)
    )
    verified_user_id = await session.scalar(
        update(User)
        .where(
            User.id == user.id,
            User.is_active.is_(True),
            User.email_verified_at.is_(None),
        )
        .values(email_verified_at=now)
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    newly_verified = verified_user_id is not None
    if newly_verified:
        await credit_entry(
            session,
            tenant_id=tenant_id,
            operation_key="bootstrap:verified-free-credit",
            entry_type="grant",
            credits=Decimal("50"),
        )
    await session.refresh(user)
    await audit(
        session,
        tenant_id=tenant_id,
        actor_id=user.id,
        action="auth.email_verified",
        target_type="user",
        target_id=str(user.id),
        metadata={"credit_granted": newly_verified},
    )
    await session.commit()
    principal = Principal(
        user_id=user.id,
        tenant_id=tenant_id,
        roles=frozenset({membership.role}),
        scopes=frozenset({"api:read", "api:write"}),
        auth_type="cookie",
    )
    token = create_session_token(
        user_id=user.id,
        tenant_id=tenant_id,
        roles=[membership.role],
        settings=settings,
    )
    _set_session_cookie(response, token, settings)
    record_abuse_control_decision(control="email_verify", result="verified")
    return _session_response(user, principal)


@router.post(
    "/auth/resend-verification",
    response_model=VerificationDispatchResponse,
    status_code=202,
)
async def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    session: SessionDep,
) -> VerificationDispatchResponse:
    settings: Settings = request.app.state.settings
    email_identity = payload.email.casefold().strip()
    await _consume_rate_control(
        request,
        control="email_resend",
        subjects=[
            (
                _client_subject(request),
                RateLimitPolicy(
                    limit=settings.resend_client_limit,
                    window_seconds=settings.resend_window_seconds,
                    captcha_after=settings.resend_captcha_after,
                ),
            ),
            (
                _account_subject(request, email_identity),
                RateLimitPolicy(
                    limit=settings.resend_account_limit,
                    window_seconds=settings.resend_window_seconds,
                    captcha_after=settings.resend_captcha_after,
                ),
            ),
        ],
        captcha_action="email-resend",
    )
    accepted = VerificationDispatchResponse()
    try:
        email = normalize_public_email(email_identity)
    except ValueError:
        return accepted
    user = await session.scalar(select(User).where(User.email == email))
    if (
        user is None
        or user.email_verified_at is not None
        or not user.is_active
        or not settings.email_verification_enabled
        or settings.email_verification_provider == "disabled"
    ):
        return accepted
    await set_rls_context(session, user_id=user.id)
    membership = await session.scalar(select(Membership).where(Membership.user_id == user.id))
    if membership is None:
        return accepted
    await set_rls_context(
        session,
        tenant_id=membership.tenant_id,
        user_id=user.id,
    )
    enqueued = await enqueue_verification(
        session,
        tenant_id=membership.tenant_id,
        user_id=user.id,
        recipient_email=user.email,
        codec=request.app.state.verification_token_codec,
        cipher=request.app.state.verification_payload_cipher,
        provider_name=settings.email_verification_provider,
        invalidate_existing=True,
    )
    await audit(
        session,
        tenant_id=membership.tenant_id,
        actor_id=user.id,
        action="auth.verification_resent",
        target_type="user",
        target_id=str(user.id),
    )
    await session.commit()
    await _dispatch_verification(
        request,
        session,
        tenant_id=membership.tenant_id,
        user_id=user.id,
        delivery_id=enqueued.delivery_id,
    )
    return accepted


@router.get("/auth/session", response_model=SessionResponse)
@router.get("/auth/me", response_model=SessionResponse, deprecated=True)
async def auth_session(principal: PrincipalDep, session: SessionDep) -> SessionResponse:
    user = await session.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "SESSION_REVOKED"})
    return _session_response(user, principal)


@router.post("/auth/logout", status_code=204)
async def logout(response: Response, request: Request) -> None:
    response.delete_cookie(
        request.app.state.settings.session_cookie_name,
        path="/",
        secure=request.app.state.settings.effective_cookie_secure,
        httponly=True,
        samesite=request.app.state.settings.cookie_samesite,
    )


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
@idempotent_mutation
async def create_api_key(
    payload: ApiKeyCreate, principal: AdminDep, session: SessionDep
) -> ApiKeyCreated:
    await _verified_user(session, principal)
    allowed_scopes = {"api:read", "api:write", "events:read", "exports:read"}
    if not set(payload.scopes).issubset(allowed_scopes):
        raise HTTPException(status_code=422, detail={"code": "INVALID_SCOPE"})
    raw, prefix, digest = generate_api_key(principal.tenant_id)
    row = ApiKey(
        tenant_id=principal.tenant_id,
        created_by=principal.user_id,
        name=payload.name,
        prefix=prefix,
        key_hash=digest,
        scopes=payload.scopes,
    )
    session.add(row)
    await session.flush()
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="api_key.created",
        target_type="api_key",
        target_id=str(row.id),
    )
    await session.commit()
    return ApiKeyCreated(
        id=row.id,
        name=row.name,
        prefix=prefix,
        key=raw,
        scopes=row.scopes,
        created_at=row.created_at,
    )


@router.get("/api-keys")
async def list_api_keys(principal: AdminDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(ApiKey)
                .where(ApiKey.tenant_id == principal.tenant_id)
                .order_by(ApiKey.created_at.desc())
            )
        ).all()
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "prefix": row.prefix,
            "scopes": row.scopes,
            "created_at": row.created_at,
            "last_used_at": row.last_used_at,
            "revoked_at": row.revoked_at,
        }
        for row in rows
    ]


@router.delete("/api-keys/{key_id}", status_code=204)
@idempotent_mutation
async def revoke_api_key(key_id: uuid.UUID, principal: AdminDep, session: SessionDep) -> None:
    row = await session.scalar(
        select(ApiKey).where(ApiKey.tenant_id == principal.tenant_id, ApiKey.id == key_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "API_KEY_NOT_FOUND"})
    row.revoked_at = utcnow()
    await session.commit()


@router.post("/projects", response_model=ProjectResponse, status_code=201)
@idempotent_mutation
async def create_project(
    payload: ProjectCreate, principal: EditorDep, session: SessionDep
) -> Project:
    project = Project(
        tenant_id=principal.tenant_id,
        created_by=principal.user_id,
        **payload.model_dump(),
    )
    session.add(project)
    await session.flush()
    session.add(
        ProjectMembership(
            tenant_id=principal.tenant_id,
            project_id=project.id,
            user_id=principal.user_id,
            role="editor",
            granted_by=principal.user_id,
        )
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="project.created",
        target_type="project",
        target_id=str(project.id),
    )
    await session.commit()
    return project


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(principal: PrincipalDep, session: SessionDep) -> list[Project]:
    return list(
        (
            await session.scalars(
                select(Project)
                .where(
                    Project.tenant_id == principal.tenant_id,
                    Project.deletion_requested_at.is_(None),
                    project_access_predicate(principal, Project.id, "read"),
                )
                .order_by(Project.updated_at.desc())
            )
        ).all()
    )


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> Project:
    return await _tenant_project(
        session,
        principal.tenant_id,
        project_id,
        principal=principal,
        capability="read",
    )


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
@idempotent_mutation
async def patch_project(
    project_id: uuid.UUID,
    payload: ProjectPatch,
    principal: EditorDep,
    session: SessionDep,
) -> Project:
    project = await _tenant_project(
        session,
        principal.tenant_id,
        project_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    project.updated_at = utcnow()
    await session.commit()
    return project


@router.post("/uploads/initiate", response_model=UploadInitiated, status_code=201)
@router.post(
    "/upload-sessions",
    response_model=UploadInitiated,
    status_code=201,
    deprecated=True,
)
@idempotent_mutation
async def initiate_upload(
    payload: UploadInitiate,
    request: Request,
    response: Response,
    principal: EditorDep,
    session: SessionDep,
) -> UploadInitiated:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    settings: Settings = request.app.state.settings
    await _require_verified_for_operation(
        request,
        session,
        principal,
        control="upload",
    )
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})
    plan_limit = _plan_upload_limit(tenant.plan_code, settings)
    limit = min(plan_limit, settings.analysis_max_source_bytes)
    if payload.size <= 0:
        raise HTTPException(status_code=422, detail={"code": "FILE_EMPTY"})
    if payload.size > limit:
        raise HTTPException(
            status_code=413,
            detail={
                "code": (
                    "ANALYSIS_SOURCE_TOO_LARGE"
                    if settings.analysis_max_source_bytes <= plan_limit
                    else "FILE_TOO_LARGE"
                ),
                "max_bytes": limit,
            },
        )
    normalized_filename = sanitize_display_filename(payload.filename)
    extension = "." + normalized_filename.rsplit(".", 1)[-1].casefold()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNSUPPORTED_FILE_TYPE"},
        )
    upload_id = uuid.uuid4()
    document: Document | None = None
    project: Project | None = None
    is_new_document = payload.document_id is None
    if payload.document_id is not None:
        document = await _tenant_document(
            session,
            principal.tenant_id,
            payload.document_id,
            lock=True,
            principal=principal,
            capability="write",
        )
        if payload.project_id is not None and payload.project_id != document.project_id:
            raise HTTPException(
                status_code=422,
                detail={"code": "DOCUMENT_PROJECT_MISMATCH"},
            )
        project = await _tenant_project(
            session,
            principal.tenant_id,
            document.project_id,
            lock=True,
            principal=principal,
            capability="write",
        )
        if document.source_file_id is None:
            existing_version = await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.tenant_id == principal.tenant_id,
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.version == document.active_version,
                )
            )
            if existing_version is not None:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "DOCUMENT_VERSION_STATE_CORRUPT"},
                )
            target_version = document.active_version
        else:
            current_version = await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.tenant_id == principal.tenant_id,
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.version == document.active_version,
                )
            )
            if current_version is None:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "DOCUMENT_VERSION_STATE_CORRUPT"},
                )
            target_version = document.active_version + 1
        active_upload = await session.scalar(
            select(UploadSession.id).where(
                UploadSession.tenant_id == principal.tenant_id,
                UploadSession.document_id == document.id,
                UploadSession.document_version == target_version,
                UploadSession.status.in_(("initiated", "uploaded")),
            )
        )
        if active_upload is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DOCUMENT_VERSION_UPLOAD_ACTIVE",
                    "document_version": target_version,
                },
            )
    elif payload.project_id:
        project = await _tenant_project(
            session,
            principal.tenant_id,
            payload.project_id,
            lock=True,
            principal=principal,
            capability="write",
        )
        target_version = 1
    else:
        project = await session.scalar(
            select(Project)
            .where(
                Project.tenant_id == principal.tenant_id,
                Project.deletion_requested_at.is_(None),
                project_access_predicate(principal, Project.id, "write"),
            )
            .order_by(Project.created_at)
            .with_for_update()
        )
        if project is None:
            project = Project(
                tenant_id=principal.tenant_id,
                name="My Project",
                created_by=principal.user_id,
            )
            session.add(project)
            await session.flush()
            session.add(
                ProjectMembership(
                    tenant_id=principal.tenant_id,
                    project_id=project.id,
                    user_id=principal.user_id,
                    role="editor",
                    granted_by=principal.user_id,
                )
            )
        target_version = 1

    duplicate = await existing_free_source(
        session,
        tenant_id=principal.tenant_id,
        plan_code=tenant.plan_code,
        sha256=payload.sha256,
    )
    duplicate_from_other_document = duplicate is not None and (
        document is None or duplicate.document_id != document.id
    )
    if duplicate_from_other_document:
        await session.rollback()
        async with request.app.state.database.sessions() as audit_session:
            await set_rls_context(
                audit_session,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
            )
            await audit(
                audit_session,
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                action="abuse.duplicate_source_denied",
                target_type="upload",
                target_id=str(upload_id),
            )
            await audit_session.commit()
        record_abuse_control_decision(
            control="duplicate_hash",
            result="duplicate",
        )
        raise HTTPException(
            status_code=409,
            detail={"code": "FREE_DUPLICATE_SOURCE"},
        )
    if document is not None and document.source_file_id:
        current_source = await session.get(SourceFile, document.source_file_id)
        if current_source is not None and secrets.compare_digest(
            current_source.sha256,
            payload.sha256.lower(),
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SOURCE_VERSION_UNCHANGED",
                    "active_version": document.active_version,
                },
            )
    try:
        await reserve_free_usage(
            session,
            tenant_id=principal.tenant_id,
            plan_code=tenant.plan_code,
            operation_key=f"upload:{upload_id}:file",
            delta=FreeUsageDelta(files=1),
            caps=_free_caps(settings),
        )
    except FreeTierCapExceeded as exc:
        await _raise_free_cap(
            request,
            session,
            principal=principal,
            control="free_file_cap",
            target_type="upload",
            target_id=str(upload_id),
            error=exc,
        )
    if project is None:
        raise RuntimeError("upload project resolution failed")
    if document is None:
        document = Document(
            id=uuid.uuid4(),
            tenant_id=principal.tenant_id,
            project_id=project.id,
            source_file_id=None,
            title=normalized_filename,
            document_type=extension.removeprefix("."),
            active_version=1,
            status="UPLOADING",
        )
        session.add(document)
    elif document.source_file_id is None:
        document.status = "UPLOADING"
        document.updated_at = utcnow()
    document_id = document.id
    key = (
        f"tenants/{principal.tenant_id}/projects/{project.id}/"
        f"documents/{document.id}/versions/v{target_version}/"
        f"uploads/{upload_id}/original.bin"
    )
    use_multipart = (
        settings.object_store_driver == "s3"
        and payload.size > settings.multipart_upload_threshold_bytes
    )
    session_ttl = (
        settings.multipart_session_ttl_seconds
        if use_multipart
        else settings.presigned_upload_ttl_seconds
    )
    expires_at = utcnow() + timedelta(seconds=session_ttl)
    part_size: int | None = None
    part_count: int | None = None
    provider_upload_id: str | None = None
    target = None
    if use_multipart:
        part_size = settings.multipart_part_size_bytes
        part_count = (payload.size + part_size - 1) // part_size
        if part_count > settings.multipart_max_parts:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "MULTIPART_PART_LIMIT_EXCEEDED",
                    "max_parts": settings.multipart_max_parts,
                },
            )
        try:
            provider_session = await request.app.state.object_store.create_multipart_upload(
                object_key=key,
                content_type=payload.content_type,
                expected_sha256=payload.sha256.lower(),
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "OBJECT_STORE_UNAVAILABLE"},
            ) from exc
        provider_upload_id = provider_session.provider_upload_id
    else:
        try:
            target = await request.app.state.object_store.create_upload_target(
                upload_id=str(upload_id),
                object_key=key,
                content_type=payload.content_type,
                expected_sha256=payload.sha256.lower(),
                expires=settings.presigned_upload_ttl_seconds,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "OBJECT_STORE_UNAVAILABLE"},
            ) from exc
    upload = UploadSession(
        id=upload_id,
        tenant_id=principal.tenant_id,
        project_id=project.id,
        document_id=document_id,
        document_version=target_version,
        created_by=principal.user_id,
        original_filename=payload.filename,
        safe_filename=normalized_filename,
        expected_mime=payload.content_type,
        expected_size=payload.size,
        expected_sha256=payload.sha256.lower(),
        object_key=key,
        upload_mode="multipart" if use_multipart else "single",
        provider_upload_id=provider_upload_id,
        multipart_part_size=part_size,
        multipart_part_count=part_count,
        expires_at=expires_at,
    )
    session.add(upload)
    try:
        await audit(
            session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action="upload.initiated",
            target_type="upload",
            target_id=str(upload.id),
            metadata={
                "document_id": str(document.id),
                "document_version": target_version,
                "new_document": is_new_document,
                "upload_mode": upload.upload_mode,
                "expected_size": upload.expected_size,
            },
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if provider_upload_id:
            await _abort_provider_upload(request, upload)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOCUMENT_VERSION_UPLOAD_CONFLICT",
                "document_version": target_version,
            },
        ) from exc
    except Exception:
        await session.rollback()
        if provider_upload_id:
            await _abort_provider_upload(request, upload)
        raise
    return UploadInitiated(
        upload_id=upload.id,
        document_id=document.id,
        document_version=upload.document_version,
        method="MULTIPART" if use_multipart else "PUT",
        upload_url=target.url if target else None,
        headers=target.headers if target else {},
        multipart=_multipart_plan(upload, settings),
        expires_at=expires_at,
    )


@router.get("/uploads/{upload_id}", response_model=UploadSessionResponse)
async def get_upload_session(
    upload_id: uuid.UUID,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
) -> UploadSessionResponse:
    upload = await _tenant_upload(
        session,
        tenant_id=principal.tenant_id,
        upload_id=upload_id,
        lock=True,
        principal=principal,
        capability="read",
    )
    if upload.status == "initiated" and _aware(upload.expires_at) <= utcnow():
        await _expire_upload(request, session, upload)
    return UploadSessionResponse(
        upload_id=upload.id,
        document_id=upload.document_id,
        document_version=upload.document_version,
        project_id=upload.project_id,
        method="MULTIPART" if upload.upload_mode == "multipart" else "PUT",
        status=upload.status,
        expected_size=upload.expected_size,
        expected_content_type=upload.expected_mime,
        expected_sha256=upload.expected_sha256,
        expires_at=upload.expires_at,
        multipart=_multipart_plan(upload, request.app.state.settings),
    )


@router.post(
    "/uploads/{upload_id}/parts/sign",
    response_model=UploadPartTargetsResponse,
)
@idempotent_mutation
async def sign_upload_parts(
    upload_id: uuid.UUID,
    payload: UploadPartSignRequest,
    request: Request,
    response: Response,
    principal: EditorDep,
    session: SessionDep,
) -> UploadPartTargetsResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    upload = await _tenant_upload(
        session,
        tenant_id=principal.tenant_id,
        upload_id=upload_id,
        principal=principal,
        capability="write",
    )
    if upload.upload_mode != "multipart" or not upload.provider_upload_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "UPLOAD_NOT_MULTIPART"},
        )
    if upload.status != "initiated":
        raise HTTPException(
            status_code=409,
            detail={"code": "UPLOAD_NOT_ACTIVE"},
        )
    if _aware(upload.expires_at) <= utcnow():
        await _expire_upload(request, session, upload)
        raise HTTPException(status_code=409, detail={"code": "UPLOAD_EXPIRED"})
    settings: Settings = request.app.state.settings
    if len(payload.part_numbers) > settings.multipart_presign_batch_size:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PART_BATCH_TOO_LARGE",
                "max_parts": settings.multipart_presign_batch_size,
            },
        )
    if upload.multipart_part_count is None or any(
        part_number > upload.multipart_part_count for part_number in payload.part_numbers
    ):
        raise HTTPException(
            status_code=422,
            detail={"code": "PART_NUMBER_OUT_OF_RANGE"},
        )
    remaining_ttl = int((_aware(upload.expires_at) - utcnow()).total_seconds())
    expires = min(settings.presigned_upload_ttl_seconds, remaining_ttl)
    if expires < 1:
        await _expire_upload(request, session, upload)
        raise HTTPException(status_code=409, detail={"code": "UPLOAD_EXPIRED"})
    try:
        targets = await asyncio.gather(
            *(
                request.app.state.object_store.create_multipart_part_target(
                    object_key=upload.object_key,
                    provider_upload_id=upload.provider_upload_id,
                    part_number=part_number,
                    expires=expires,
                )
                for part_number in sorted(payload.part_numbers)
            )
        )
    except MultipartUploadNotFoundError as exc:
        await _expire_upload(request, session, upload)
        raise HTTPException(
            status_code=409,
            detail={"code": "UPLOAD_EXPIRED"},
        ) from exc
    except (BotoCoreError, ClientError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "OBJECT_STORE_UNAVAILABLE"},
        ) from exc
    target_expires_at = utcnow() + timedelta(seconds=expires)
    return UploadPartTargetsResponse(
        upload_id=upload.id,
        parts=[
            UploadPartTargetResponse(
                part_number=target.part_number,
                upload_url=target.url,
                headers=target.headers,
                expires_at=target_expires_at,
            )
            for target in targets
        ],
    )


@router.get(
    "/uploads/{upload_id}/parts",
    response_model=UploadedPartsResponse,
)
async def list_upload_parts(
    upload_id: uuid.UUID,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
) -> UploadedPartsResponse:
    upload = await _tenant_upload(
        session,
        tenant_id=principal.tenant_id,
        upload_id=upload_id,
        principal=principal,
        capability="read",
    )
    if upload.upload_mode != "multipart" or not upload.provider_upload_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "UPLOAD_NOT_MULTIPART"},
        )
    if upload.status in {"uploaded", "completed"}:
        return UploadedPartsResponse(
            upload_id=upload.id,
            parts=[],
            assembly_completed=True,
        )
    if upload.status != "initiated":
        raise HTTPException(
            status_code=409,
            detail={"code": "UPLOAD_NOT_ACTIVE"},
        )
    if _aware(upload.expires_at) <= utcnow():
        await _expire_upload(request, session, upload)
        raise HTTPException(status_code=409, detail={"code": "UPLOAD_EXPIRED"})
    try:
        parts = await request.app.state.object_store.list_multipart_parts(
            object_key=upload.object_key,
            provider_upload_id=upload.provider_upload_id,
        )
    except MultipartUploadNotFoundError as exc:
        try:
            metadata = await request.app.state.object_store.head_quarantine(upload.object_key)
        except (FileNotFoundError, OSError, KeyError):
            await _expire_upload(request, session, upload)
            raise HTTPException(
                status_code=409,
                detail={"code": "UPLOAD_EXPIRED"},
            ) from exc
        except (BotoCoreError, ClientError) as store_exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "OBJECT_STORE_UNAVAILABLE"},
            ) from store_exc
        if metadata.size_bytes != upload.expected_size:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "SIZE_MISMATCH",
                    "expected": upload.expected_size,
                    "actual": metadata.size_bytes,
                },
            ) from exc
        upload.status = "uploaded"
        document = await _tenant_document(
            session,
            principal.tenant_id,
            upload.document_id,
            lock=True,
            principal=principal,
            capability="write",
        )
        if document.status == "UPLOADING":
            document.status = "QUARANTINED"
        await session.commit()
        return UploadedPartsResponse(
            upload_id=upload.id,
            parts=[],
            assembly_completed=True,
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "OBJECT_STORE_UNAVAILABLE"},
        ) from exc
    if upload.multipart_part_count is None or any(
        part.part_number > upload.multipart_part_count for part in parts
    ):
        raise HTTPException(
            status_code=502,
            detail={"code": "OBJECT_STORE_INVALID_MULTIPART_STATE"},
        )
    return UploadedPartsResponse(
        upload_id=upload.id,
        parts=[
            UploadedPartResponse(
                part_number=part.part_number,
                etag=part.etag,
                size=part.size_bytes,
            )
            for part in parts
        ],
    )


@router.put("/uploads/{upload_id}/content", status_code=204)
@router.put("/upload-sessions/{upload_id}/content", status_code=204, deprecated=True)
async def put_local_upload(
    upload_id: uuid.UUID,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
) -> None:
    if not isinstance(request.app.state.object_store, LocalObjectStore):
        raise HTTPException(status_code=405, detail={"code": "DIRECT_UPLOAD_REQUIRED"})
    upload = await _tenant_upload(
        session,
        tenant_id=principal.tenant_id,
        upload_id=upload_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    if upload.upload_mode != "single":
        raise HTTPException(status_code=405, detail={"code": "DIRECT_UPLOAD_REQUIRED"})
    if upload.status != "initiated":
        raise HTTPException(status_code=409, detail={"code": "UPLOAD_NOT_ACTIVE"})
    if _aware(upload.expires_at) <= utcnow():
        await _expire_upload(request, session, upload)
        raise HTTPException(status_code=409, detail={"code": "UPLOAD_EXPIRED"})
    content_type = request.headers.get("Content-Type", "").split(";", 1)[0].casefold()
    if content_type != upload.expected_mime.split(";", 1)[0].casefold():
        raise HTTPException(status_code=422, detail={"code": "CONTENT_TYPE_MISMATCH"})
    size = 0
    digest = hashlib.sha256()
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as staged:
        async for chunk in request.stream():
            size += len(chunk)
            if size > upload.expected_size:
                raise HTTPException(status_code=413, detail={"code": "FILE_TOO_LARGE"})
            digest.update(chunk)
            staged.write(chunk)
        if size != upload.expected_size:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "SIZE_MISMATCH",
                    "expected": upload.expected_size,
                    "actual": size,
                },
            )
        if digest.hexdigest() != upload.expected_sha256:
            raise HTTPException(status_code=422, detail={"code": "CHECKSUM_MISMATCH"})
        staged.seek(0)
        await request.app.state.object_store.put_quarantine_stream(
            upload.object_key,
            cast(BinaryIO, staged),
        )
    upload.status = "uploaded"
    document = await _tenant_document(
        session,
        principal.tenant_id,
        upload.document_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    if document.source_file_id is None and upload.document_version == document.active_version:
        document.status = "QUARANTINED"
    await session.commit()


@router.post("/uploads/{upload_id}/complete", response_model=UploadCompleted)
@router.post(
    "/upload-sessions/{upload_id}/finalize",
    response_model=UploadCompleted,
    deprecated=True,
)
@idempotent_mutation
async def complete_upload(
    upload_id: uuid.UUID,
    payload: UploadComplete,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
) -> UploadCompleted:
    await _require_verified_for_operation(
        request,
        session,
        principal,
        control="upload",
    )
    upload = await _tenant_upload(
        session,
        tenant_id=principal.tenant_id,
        upload_id=upload_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    if upload.status == "completed":
        await _tenant_document(
            session,
            principal.tenant_id,
            upload.document_id,
            lock=True,
            principal=principal,
            capability="write",
        )
        completed_version = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.tenant_id == principal.tenant_id,
                DocumentVersion.document_id == upload.document_id,
                DocumentVersion.version == upload.document_version,
            )
        )
        source = (
            await session.get(SourceFile, completed_version.source_file_id)
            if completed_version is not None and completed_version.source_file_id
            else None
        )
        if source is None:
            raise HTTPException(status_code=409, detail={"code": "UPLOAD_STATE_CORRUPT"})
        return UploadCompleted(
            upload_id=upload.id,
            source_file_id=source.id,
            document_id=upload.document_id,
            document_version=upload.document_version,
            status="SECURITY_VERIFIED",
        )
    if upload.status not in {"initiated", "uploaded"}:
        raise HTTPException(status_code=409, detail={"code": "UPLOAD_NOT_COMPLETABLE"})
    if upload.status == "initiated" and _aware(upload.expires_at) <= utcnow():
        await _expire_upload(request, session, upload)
        raise HTTPException(status_code=409, detail={"code": "UPLOAD_EXPIRED"})
    supplied_sha = (payload.sha256 or upload.expected_sha256).lower()
    if not secrets.compare_digest(supplied_sha, upload.expected_sha256):
        raise HTTPException(status_code=422, detail={"code": "CHECKSUM_MISMATCH"})

    if upload.upload_mode == "multipart" and upload.status == "initiated":
        if (
            not upload.provider_upload_id
            or upload.multipart_part_size is None
            or upload.multipart_part_count is None
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "UPLOAD_STATE_CORRUPT"},
            )
        provider_missing = False
        try:
            provider_parts = await request.app.state.object_store.list_multipart_parts(
                object_key=upload.object_key,
                provider_upload_id=upload.provider_upload_id,
            )
        except MultipartUploadNotFoundError:
            provider_parts = []
            provider_missing = True
        except (BotoCoreError, ClientError, OSError) as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "OBJECT_STORE_UNAVAILABLE"},
            ) from exc

        if not provider_missing:
            expected_numbers = list(range(1, upload.multipart_part_count + 1))
            submitted_numbers = [part.part_number for part in payload.parts]
            if submitted_numbers != expected_numbers:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "MULTIPART_PARTS_NOT_CONTIGUOUS",
                        "expected_count": upload.multipart_part_count,
                    },
                )
            provider_numbers = [part.part_number for part in provider_parts]
            if provider_numbers != expected_numbers:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "MULTIPART_PARTS_INCOMPLETE",
                        "expected_count": upload.multipart_part_count,
                        "uploaded_count": len(provider_parts),
                    },
                )
            for submitted, provider in zip(
                payload.parts,
                provider_parts,
                strict=True,
            ):
                expected_part_size = (
                    upload.multipart_part_size
                    if provider.part_number < upload.multipart_part_count
                    else upload.expected_size
                    - (upload.multipart_part_size * (upload.multipart_part_count - 1))
                )
                if provider.size_bytes != expected_part_size:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "MULTIPART_PART_SIZE_MISMATCH",
                            "part_number": provider.part_number,
                            "expected": expected_part_size,
                            "actual": provider.size_bytes,
                        },
                    )
                if not secrets.compare_digest(submitted.etag, provider.etag):
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "MULTIPART_ETAG_MISMATCH",
                            "part_number": provider.part_number,
                        },
                    )
            try:
                await request.app.state.object_store.complete_multipart_upload(
                    object_key=upload.object_key,
                    provider_upload_id=upload.provider_upload_id,
                    parts=[
                        CompletedPart(
                            part_number=part.part_number,
                            etag=part.etag,
                        )
                        for part in payload.parts
                    ],
                )
            except MultipartUploadNotFoundError:
                # A provider can commit the object and lose the opaque upload
                # handle before the client receives the response. HEAD plus the
                # full streamed digest below is the authoritative retry path.
                provider_missing = True
            except (BotoCoreError, ClientError, OSError) as exc:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "OBJECT_STORE_UNAVAILABLE"},
                ) from exc

        if provider_missing:
            try:
                recovered_metadata = await request.app.state.object_store.head_quarantine(
                    upload.object_key
                )
            except (FileNotFoundError, OSError, KeyError) as exc:
                await _expire_upload(request, session, upload)
                raise HTTPException(
                    status_code=409,
                    detail={"code": "UPLOAD_ASSEMBLY_NOT_FOUND"},
                ) from exc
            except (BotoCoreError, ClientError) as exc:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "OBJECT_STORE_UNAVAILABLE"},
                ) from exc
            if recovered_metadata.size_bytes != upload.expected_size:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "SIZE_MISMATCH"},
                )
        upload.status = "uploaded"

    document = await _tenant_document(
        session,
        principal.tenant_id,
        upload.document_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    initial_source_upload = document.source_file_id is None
    expected_version = (
        document.active_version if initial_source_upload else document.active_version + 1
    )
    if upload.document_version != expected_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SOURCE_VERSION_CHANGED",
                "active_version": document.active_version,
                "upload_version": upload.document_version,
            },
        )
    if initial_source_upload:
        document.status = "SECURITY_SCANNING"
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="document.security_scanning",
        target_type="document",
        target_id=str(document.id),
        metadata={
            "document_version": upload.document_version,
            "replacement": not initial_source_upload,
        },
    )
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})
    try:
        metadata = await request.app.state.object_store.head_quarantine(upload.object_key)
    except (FileNotFoundError, OSError, KeyError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "UPLOAD_OBJECT_NOT_FOUND"},
        ) from exc
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "OBJECT_STORE_UNAVAILABLE"},
        ) from exc
    if metadata.size_bytes != upload.expected_size:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SIZE_MISMATCH",
                "expected": upload.expected_size,
                "actual": metadata.size_bytes,
            },
        )
    if metadata.content_type and (
        metadata.content_type.split(";", 1)[0].casefold()
        != upload.expected_mime.split(";", 1)[0].casefold()
    ):
        raise HTTPException(status_code=422, detail={"code": "CONTENT_TYPE_MISMATCH"})
    if metadata.checksum_sha256 and upload.upload_mode == "single":
        expected_b64 = base64.b64encode(bytes.fromhex(upload.expected_sha256)).decode("ascii")
        if not secrets.compare_digest(metadata.checksum_sha256, expected_b64):
            raise HTTPException(status_code=422, detail={"code": "CHECKSUM_MISMATCH"})

    validation_code: str | None = None
    scan_status = ""
    cdr_result: CdrResult | None = None
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as staged:
        await request.app.state.object_store.download_quarantine(
            upload.object_key,
            staged,
        )
        validation = validate_upload_stream(
            upload.safe_filename,
            cast(BinaryIO, staged),
            tier=_plan_tier(tenant.plan_code),
            claimed_content_type=upload.expected_mime,
        )
        digest = (validation.sha256 or "").removeprefix("sha256:")
        if not validation.accepted:
            validation_code = validation.reason_code or "UNSAFE_FILE"
        elif not secrets.compare_digest(digest, upload.expected_sha256):
            validation_code = "CHECKSUM_MISMATCH"
        if validation_code is None:
            await lock_current_free_usage_day(
                session,
                tenant_id=principal.tenant_id,
                plan_code=tenant.plan_code,
            )
            duplicate = await existing_free_source(
                session,
                tenant_id=principal.tenant_id,
                plan_code=tenant.plan_code,
                sha256=digest,
            )
            if duplicate is not None and duplicate.document_id != document.id:
                rejected_upload_id = upload.id
                rejected_document_id = document.id
                rejected_object_key = upload.object_key
                await session.rollback()
                await request.app.state.object_store.delete(
                    "quarantine",
                    rejected_object_key,
                )
                async with request.app.state.database.sessions() as denial_session:
                    await set_rls_context(
                        denial_session,
                        tenant_id=principal.tenant_id,
                        user_id=principal.user_id,
                    )
                    rejected_upload = await denial_session.scalar(
                        select(UploadSession)
                        .where(
                            UploadSession.tenant_id == principal.tenant_id,
                            UploadSession.id == rejected_upload_id,
                        )
                        .with_for_update()
                    )
                    rejected_document = await denial_session.scalar(
                        select(Document)
                        .where(
                            Document.tenant_id == principal.tenant_id,
                            Document.id == rejected_document_id,
                        )
                        .with_for_update()
                    )
                    if rejected_upload is not None:
                        rejected_upload.status = "aborted"
                    if rejected_document is not None and rejected_document.source_file_id is None:
                        rejected_document.status = "SECURITY_REJECTED"
                    await audit(
                        denial_session,
                        tenant_id=principal.tenant_id,
                        actor_id=principal.user_id,
                        action="abuse.duplicate_source_denied",
                        target_type="document",
                        target_id=str(rejected_document_id),
                    )
                    await denial_session.commit()
                record_abuse_control_decision(
                    control="duplicate_hash",
                    result="duplicate",
                )
                raise HTTPException(
                    status_code=409,
                    detail={"code": "FREE_DUPLICATE_SOURCE"},
                )
        if validation_code is None:
            staged.seek(0)
            try:
                scan = await scan_quarantined_stream(
                    cast(BinaryIO, staged),
                    request.app.state.settings,
                )
                scan_status = scan.status
            except MalwareDetectedError:
                validation_code = "MALWARE_DETECTED"
            except MalwareScanError as exc:
                await audit(
                    session,
                    tenant_id=principal.tenant_id,
                    actor_id=principal.user_id,
                    action="document.security_scan_unavailable",
                    target_type="document",
                    target_id=str(document.id),
                )
                await session.commit()
                raise HTTPException(
                    status_code=503,
                    detail={"code": "ANTIVIRUS_UNAVAILABLE"},
                ) from exc
        mime_type = upload.expected_mime.split(";", 1)[0].strip().casefold()
        if (
            validation_code is None
            and request.app.state.settings.cdr_enabled
            and mime_type in request.app.state.settings.cdr_supported_mimes
        ):
            staged.seek(0)
            payload_bytes = staged.read(request.app.state.settings.cdr_max_output_bytes + 1)
            if len(payload_bytes) > request.app.state.settings.cdr_max_output_bytes:
                raise HTTPException(
                    status_code=413,
                    detail={"code": "CDR_SOURCE_TOO_LARGE"},
                )
            try:
                cdr_result = await request.app.state.cdr_adapter.sanitize(
                    CdrRequest(
                        filename=upload.safe_filename,
                        mime_type=mime_type,
                        source_sha256=digest,
                        payload=payload_bytes,
                    )
                )
                cdr_result = validate_cdr_result(
                    cdr_result,
                    source_sha256=digest,
                    max_output_bytes=request.app.state.settings.cdr_max_output_bytes,
                )
            except ValueError as exc:
                await audit(
                    session,
                    tenant_id=principal.tenant_id,
                    actor_id=principal.user_id,
                    action="document.cdr_invalid_response",
                    target_type="document",
                    target_id=str(document.id),
                )
                await session.commit()
                raise HTTPException(
                    status_code=503,
                    detail={"code": "CDR_INVALID_RESPONSE"},
                ) from exc
            if cdr_result.status is CdrStatus.UNAVAILABLE:
                await audit(
                    session,
                    tenant_id=principal.tenant_id,
                    actor_id=principal.user_id,
                    action="document.cdr_unavailable",
                    target_type="document",
                    target_id=str(document.id),
                )
                await session.commit()
                raise HTTPException(
                    status_code=503,
                    detail={"code": "CDR_UNAVAILABLE"},
                )
            if cdr_result.status is CdrStatus.UNSUPPORTED:
                validation_code = "CDR_UNSUPPORTED"
            elif cdr_result.status is CdrStatus.REJECTED:
                validation_code = "CDR_REJECTED"

    if validation_code is not None:
        if initial_source_upload:
            document.status = "SECURITY_REJECTED"
        upload.status = "aborted"
        await request.app.state.object_store.delete("quarantine", upload.object_key)
        await audit(
            session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action="document.security_rejected",
            target_type="document",
            target_id=str(document.id),
            metadata={
                "code": validation_code,
                "document_version": upload.document_version,
                "replacement": not initial_source_upload,
            },
        )
        await session.commit()
        raise HTTPException(status_code=422, detail={"code": validation_code})
    extension = validation.extension
    existing = await session.scalar(
        select(SourceFile).where(
            SourceFile.tenant_id == principal.tenant_id,
            SourceFile.project_id == upload.project_id,
            SourceFile.sha256 == digest,
        )
    )
    if existing is None:
        source_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            (f"akc-source:{principal.tenant_id}:{upload.project_id}:{digest}"),
        )
        source_key = (
            f"tenants/{principal.tenant_id}/projects/{upload.project_id}/"
            f"sources/sha256/{digest}/original.bin"
        )
        await request.app.state.object_store.promote_source(upload.object_key, source_key)
        if not await _source_object_matches(
            request.app.state.object_store,
            object_key=source_key,
            expected_sha256=digest,
            expected_size=metadata.size_bytes,
        ):
            await request.app.state.object_store.delete("source", source_key)
            try:
                await request.app.state.object_store.promote_source(
                    upload.object_key,
                    source_key,
                )
            except (
                BotoCoreError,
                ClientError,
                FileNotFoundError,
                OSError,
                KeyError,
            ) as exc:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "SOURCE_PROMOTION_INTEGRITY_FAILED"},
                ) from exc
            if not await _source_object_matches(
                request.app.state.object_store,
                object_key=source_key,
                expected_sha256=digest,
                expected_size=metadata.size_bytes,
            ):
                raise HTTPException(
                    status_code=503,
                    detail={"code": "SOURCE_PROMOTION_INTEGRITY_FAILED"},
                )
        sanitized_key: str | None = None
        sanitized_sha256: str | None = None
        sanitized_size: int | None = None
        if cdr_result is not None and cdr_result.status is CdrStatus.SANITIZED:
            assert cdr_result.sanitized_payload is not None
            assert cdr_result.sanitized_sha256 is not None
            sanitized_sha256 = cdr_result.sanitized_sha256
            sanitized_size = len(cdr_result.sanitized_payload)
            sanitized_key = (
                f"tenants/{principal.tenant_id}/projects/{upload.project_id}/"
                f"derived/cdr/sha256/{sanitized_sha256}/sanitized.bin"
            )
            await request.app.state.object_store.put_derived(
                sanitized_key,
                cdr_result.sanitized_payload,
            )
        source = SourceFile(
            id=source_id,
            tenant_id=principal.tenant_id,
            project_id=upload.project_id,
            upload_id=upload.id,
            original_filename=upload.original_filename,
            safe_filename=upload.safe_filename,
            mime_type=upload.expected_mime,
            size_bytes=metadata.size_bytes,
            sha256=digest,
            storage_key=source_key,
            antivirus_status=scan_status,
            cdr_status=(cdr_result.status.value if cdr_result is not None else "not_requested"),
            cdr_provider=(cdr_result.provider if cdr_result is not None else None),
            cdr_revision=(cdr_result.revision if cdr_result is not None else None),
            sanitized_storage_key=sanitized_key,
            sanitized_sha256=sanitized_sha256,
            sanitized_size_bytes=sanitized_size,
            uploaded_by=principal.user_id,
        )
        session.add(source)
        # Flush the composite source identity before the existing document row
        # is updated to reference it. This is required by SQLite's immediate
        # foreign-key checks and makes the ordering explicit on PostgreSQL too.
        await session.flush()
    else:
        source = existing
        if cdr_result is not None and cdr_result.status is CdrStatus.SANITIZED:
            assert cdr_result.sanitized_payload is not None
            assert cdr_result.sanitized_sha256 is not None
            sanitized_key = (
                f"tenants/{principal.tenant_id}/projects/{upload.project_id}/"
                f"derived/cdr/sha256/{cdr_result.sanitized_sha256}/sanitized.bin"
            )
            await request.app.state.object_store.put_derived(
                sanitized_key,
                cdr_result.sanitized_payload,
            )
            source.cdr_status = cdr_result.status.value
            source.cdr_provider = cdr_result.provider
            source.cdr_revision = cdr_result.revision
            source.sanitized_storage_key = sanitized_key
            source.sanitized_sha256 = cdr_result.sanitized_sha256
            source.sanitized_size_bytes = len(cdr_result.sanitized_payload)
    try:
        await free_source_claim(
            session,
            tenant_id=principal.tenant_id,
            plan_code=tenant.plan_code,
            sha256=digest,
            document_id=document.id,
            source_file_id=source.id,
        )
    except DuplicateFreeSource as exc:
        # Completion is serialized by the free daily-usage row, so this is an
        # invariant guard rather than the normal duplicate path.
        raise RuntimeError("free source claim serialization failed") from exc
    now = utcnow()
    previous_snapshot_sha256: str | None = None
    superseded_work = {
        "analysis_tasks": 0,
        "processing_jobs": 0,
        "gpu_invocations": 0,
    }
    if initial_source_upload:
        prior_version = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.tenant_id == principal.tenant_id,
                DocumentVersion.document_id == document.id,
                DocumentVersion.version == upload.document_version,
            )
        )
        if prior_version is not None:
            raise HTTPException(
                status_code=409,
                detail={"code": "DOCUMENT_VERSION_STATE_CORRUPT"},
            )
    else:
        archived = await archive_active_document_version(
            session,
            store=request.app.state.object_store,
            document=document,
            now=now,
        )
        previous_snapshot_sha256 = archived.sha256
        superseded_work = await _supersede_document_work(
            session,
            tenant_id=principal.tenant_id,
            document_id=document.id,
            previous_version=document.active_version,
            next_version=upload.document_version,
            now=now,
        )
        await clear_active_document_projection(
            session,
            tenant_id=principal.tenant_id,
            document_id=document.id,
        )
        document.active_version = upload.document_version
    document_version = DocumentVersion(
        tenant_id=principal.tenant_id,
        document_id=document.id,
        version=upload.document_version,
        source_file_id=source.id,
        source_sha256=digest,
        source_filename=upload.safe_filename,
        source_mime_type=upload.expected_mime,
        source_size_bytes=metadata.size_bytes,
        cir_object_key=None,
        cir_snapshot_sha256=None,
        archived_objects=[],
        input_revision_hash=digest,
        policy_version="unprocessed-upload-v1",
        model_revision="unprocessed",
        prompt_revision=None,
        normalization_revision=None,
        akmp_schema_version="1.0",
        status="source_verified",
    )
    session.add(document_version)
    upload.status = "completed"
    upload.completed_at = now
    document.source_file_id = source.id
    document.document_type = extension.removeprefix(".")
    document.language_codes = []
    document.page_count = None
    document.status = "SECURITY_VERIFIED"
    document.updated_at = now
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="document.security_verified",
        target_type="document",
        target_id=str(document.id),
        metadata={
            "source_digest": request.app.state.identity_hasher.pseudonymize(
                purpose="source-digest",
                value=digest,
            ),
            "document_version": upload.document_version,
            "previous_snapshot_sha256": previous_snapshot_sha256,
            "superseded_work": superseded_work,
            "cdr_status": source.cdr_status,
            "cdr_provider": source.cdr_provider,
            "cdr_revision": source.cdr_revision,
            "sanitized_sha256": source.sanitized_sha256,
        },
    )
    await session.commit()
    with suppress(BotoCoreError, ClientError, OSError, KeyError):
        await request.app.state.object_store.delete(
            "quarantine",
            upload.object_key,
        )
    return UploadCompleted(
        upload_id=upload.id,
        source_file_id=source.id,
        document_id=document.id,
        document_version=upload.document_version,
        status=document.status,
    )


@router.post("/uploads/{upload_id}/abort", status_code=204)
@router.post("/upload-sessions/{upload_id}/abort", status_code=204, deprecated=True)
@idempotent_mutation
async def abort_upload(
    upload_id: uuid.UUID,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
) -> None:
    upload = await _tenant_upload(
        session,
        tenant_id=principal.tenant_id,
        upload_id=upload_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    if upload.status == "completed":
        raise HTTPException(status_code=409, detail={"code": "UPLOAD_ALREADY_COMPLETED"})
    if upload.status in {"aborted", "expired"}:
        return
    await _abort_provider_upload(request, upload)
    upload.status = "aborted"
    await request.app.state.object_store.delete("quarantine", upload.object_key)
    document = await _tenant_document(
        session,
        principal.tenant_id,
        upload.document_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    if document.source_file_id is None and document.status in {
        "UPLOADING",
        "QUARANTINED",
        "SECURITY_SCANNING",
    }:
        document.status = "UPLOAD_ABORTED"
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="upload.aborted",
        target_type="upload",
        target_id=str(upload.id),
    )
    await session.commit()


@router.post(
    "/documents",
    response_model=DocumentResponse | UrlFetchTaskResponse,
    status_code=201,
    responses={202: {"model": UrlFetchTaskResponse}},
)
@idempotent_mutation
async def create_document(
    payload: DocumentCreate,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
) -> Document | JSONResponse:
    project = await _tenant_project(
        session,
        principal.tenant_id,
        payload.project_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    if payload.source_url:
        if not request.app.state.settings.url_ingestion_enabled:
            raise HTTPException(
                status_code=403,
                detail={"code": "URL_INGESTION_DISABLED"},
            )
        codec = request.app.state.url_secret_codec
        if not isinstance(codec, UrlSecretCodec):
            raise RuntimeError("URL ingestion codec is unavailable")
        try:
            protected = codec.protect(payload.source_url)
        except UrlFetchError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": exc.code},
            ) from None
        row = Document(
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            source_file_id=None,
            title=payload.title,
            document_type="unknown",
            status="URL_FETCH_QUEUED",
        )
        session.add(row)
        await session.flush()
        task = UrlFetchTask(
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            document_id=row.id,
            requested_by=principal.user_id,
            encrypted_url=protected.ciphertext,
            canonical_url=protected.canonical_url,
            query_hmac=protected.query_hmac,
            status="queued",
            max_attempts=request.app.state.settings.url_fetch_max_attempts,
        )
        session.add(task)
        await session.flush()
        tenant = await session.get(Tenant, principal.tenant_id)
        if tenant is None:
            raise RuntimeError("tenant missing")
        try:
            await reserve_free_usage(
                session,
                tenant_id=principal.tenant_id,
                plan_code=tenant.plan_code,
                operation_key=f"url-fetch:{task.id}:file",
                delta=FreeUsageDelta(files=1),
                caps=_free_caps(request.app.state.settings),
            )
        except FreeTierCapExceeded as exc:
            await _raise_free_cap(
                request,
                session,
                principal=principal,
                control="free_file_cap",
                target_type="url_fetch_task",
                target_id=str(task.id),
                error=exc,
            )
        await audit(
            session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action="document.url_fetch_queued",
            target_type="document",
            target_id=str(row.id),
            metadata={
                "task_id": str(task.id),
                "canonical_url": task.canonical_url,
                "query_hmac": task.query_hmac,
            },
        )
        await session.commit()
        return JSONResponse(
            status_code=202,
            content=url_fetch_task_response(task).model_dump(mode="json"),
        )
    row = Document(
        tenant_id=principal.tenant_id,
        project_id=project.id,
        source_file_id=None,
        title=payload.title,
        document_type="unknown",
        status="DRAFT",
    )
    session.add(row)
    await session.flush()
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="document.created",
        target_type="document",
        target_id=str(row.id),
    )
    await session.commit()
    return row


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> DocumentResponse:
    document = await _tenant_document(
        session,
        principal.tenant_id,
        document_id,
        principal=principal,
        capability="read",
    )
    stored = await session.scalar(
        select(DocumentSemanticClassification).where(
            DocumentSemanticClassification.tenant_id == principal.tenant_id,
            DocumentSemanticClassification.document_id == document.id,
            DocumentSemanticClassification.document_version == document.active_version,
            DocumentSemanticClassification.is_active.is_(True),
        )
    )
    semantic_summary: SemanticClassificationSummary | None = None
    if stored is not None:
        try:
            classification = DocumentClassification.model_validate(stored.classification)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "SEMANTIC_CLASSIFICATION_INVALID"},
            ) from exc
        semantic_summary = SemanticClassificationSummary(
            semantic_type=classification.document_type,
            languages=list(classification.languages or (classification.language,)),
            topics=list(classification.topics),
            domains=list(classification.domain),
            evidence_block_ids=list(classification.evidence_block_ids),
            confidence=classification.confidence,
            model_attestation={
                "provider_key": stored.provider_key,
                "model_revision": stored.model_revision,
                "runtime_image_digest": stored.runtime_image_digest,
                "adapter_version": stored.adapter_version,
                "prompt_revision": stored.prompt_revision,
                "schema_sha256": stored.schema_sha256,
            },
        )
    return DocumentResponse(
        id=document.id,
        project_id=document.project_id,
        title=document.title,
        document_type=document.document_type,
        language_codes=document.language_codes,
        semantic_classification=semantic_summary,
        page_count=document.page_count,
        active_version=document.active_version,
        status=document.status,
        created_at=document.created_at,
    )


@router.get(
    "/documents/{document_id}/versions",
    response_model=DocumentVersionListResponse,
)
async def list_document_versions(
    document_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> DocumentVersionListResponse:
    document = await _tenant_document(
        session,
        principal.tenant_id,
        document_id,
        principal=principal,
        capability="read",
    )
    versions = list(
        (
            await session.scalars(
                select(DocumentVersion)
                .where(
                    DocumentVersion.tenant_id == principal.tenant_id,
                    DocumentVersion.document_id == document.id,
                )
                .order_by(DocumentVersion.version)
            )
        ).all()
    )
    return DocumentVersionListResponse(
        document_id=document.id,
        active_version=document.active_version,
        versions=[_document_version_summary(version) for version in versions],
    )


async def _tenant_document_version(
    session: AsyncSession,
    *,
    principal: Principal,
    document_id: uuid.UUID,
    version_number: int,
) -> tuple[Document, DocumentVersion]:
    document = await _tenant_document(
        session,
        principal.tenant_id,
        document_id,
        principal=principal,
        capability="read",
    )
    version = await session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.tenant_id == principal.tenant_id,
            DocumentVersion.document_id == document.id,
            DocumentVersion.version == version_number,
        )
    )
    if version is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_VERSION_NOT_FOUND"},
        )
    return document, version


@router.get(
    "/documents/{document_id}/versions/{version_number}",
    response_model=DocumentVersionSummary,
)
async def get_document_version(
    document_id: uuid.UUID,
    version_number: int,
    principal: PrincipalDep,
    session: SessionDep,
) -> DocumentVersionSummary:
    _, version = await _tenant_document_version(
        session,
        principal=principal,
        document_id=document_id,
        version_number=version_number,
    )
    return _document_version_summary(version)


@router.get(
    "/documents/{document_id}/versions/{version_number}/diff",
    response_model=DocumentVersionDiffResponse,
)
async def diff_document_versions(
    document_id: uuid.UUID,
    version_number: int,
    principal: PrincipalDep,
    session: SessionDep,
    to_version: int = Query(ge=1),
) -> DocumentVersionDiffResponse:
    _, older = await _tenant_document_version(
        session,
        principal=principal,
        document_id=document_id,
        version_number=version_number,
    )
    if to_version <= version_number:
        raise HTTPException(
            status_code=422,
            detail={"code": "DOCUMENT_VERSION_DIFF_ORDER_INVALID"},
        )
    newer = await session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.tenant_id == principal.tenant_id,
            DocumentVersion.document_id == document_id,
            DocumentVersion.version == to_version,
        )
    )
    if newer is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_VERSION_NOT_FOUND"},
        )
    return DocumentVersionDiffResponse.model_validate(document_version_diff(older, newer))


@router.get(
    "/documents/{document_id}/versions/{version_number}/snapshot",
    response_model=dict[str, Any],
)
async def get_document_version_snapshot(
    document_id: uuid.UUID,
    version_number: int,
    response: Response,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    _, version = await _tenant_document_version(
        session,
        principal=principal,
        document_id=document_id,
        version_number=version_number,
    )
    try:
        return await read_public_document_version_snapshot(
            store=request.app.state.object_store,
            version=version,
        )
    except (FileNotFoundError, OSError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "DOCUMENT_VERSION_SNAPSHOT_UNAVAILABLE"},
        ) from exc


@router.get(
    "/url-fetch-tasks/{task_id}",
    response_model=UrlFetchTaskResponse,
)
async def get_url_fetch_task(
    task_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> UrlFetchTaskResponse:
    task = await _tenant_url_fetch_task(
        session,
        principal.tenant_id,
        task_id,
        principal=principal,
        capability="read",
    )
    return url_fetch_task_response(task)


@router.post(
    "/url-fetch-tasks/{task_id}/cancel",
    response_model=UrlFetchTaskResponse,
)
@idempotent_mutation
async def cancel_url_fetch_task(
    task_id: uuid.UUID,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
) -> UrlFetchTaskResponse:
    del request
    task = await _tenant_url_fetch_task(
        session,
        principal.tenant_id,
        task_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    if task.status == "cancelled":
        return url_fetch_task_response(task)
    if task.status in {"completed", "failed", "dead_letter"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "URL_FETCH_TASK_TERMINAL"},
        )
    now = utcnow()
    task.status = "cancelled"
    task.last_error_code = "URL_FETCH_CANCELLED"
    task.lease_token = None
    task.lease_expires_at = None
    task.available_at = now
    task.cancelled_at = now
    task.updated_at = now
    document = await _tenant_document(
        session,
        principal.tenant_id,
        task.document_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    document.status = "URL_FETCH_CANCELLED"
    document.updated_at = now
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="document.url_fetch_cancelled",
        target_type="document",
        target_id=str(task.document_id),
        metadata={
            "task_id": str(task.id),
            "canonical_url": task.canonical_url,
            "query_hmac": task.query_hmac,
        },
    )
    await session.commit()
    return url_fetch_task_response(task)


def _analysis_response(task: AnalysisTask) -> AnalyzeResponse:
    return AnalyzeResponse(
        task_id=task.id,
        document_id=task.document_id,
        status=cast(
            Any,
            task.status,
        ),
        attempt_count=task.attempt_count,
        max_attempts=task.max_attempts,
        page_count=task.page_count,
        block_count=task.block_count,
        preview_count=task.preview_count,
        error_code=task.last_error_code,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


async def _execute_local_analysis_task(app: FastAPI, task_id: uuid.UUID) -> None:
    """Explicit development/test adapter using the same sandboxed worker."""

    if (
        app.state.settings.env == "production"
        or not app.state.settings.local_analysis_worker_enabled
    ):
        raise RuntimeError("local_analysis_worker_forbidden")
    # Keep parser modules out of the production API import graph.
    from akc_worker_document.worker import run_local_analysis_task

    await run_local_analysis_task(
        database=app.state.database,
        store=app.state.object_store,
        settings=app.state.settings,
        task_id=task_id,
        pdf_secret_store=app.state.pdf_secret_store,
    )


@router.post(
    "/documents/{document_id}/analyze",
    response_model=AnalyzeResponse,
    status_code=202,
)
@idempotent_mutation
async def analyze(
    document_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: EditorDep,
    session: SessionDep,
) -> AnalyzeResponse:
    await _require_verified_for_operation(
        request,
        session,
        principal,
        control="analyze",
    )
    document = await session.scalar(
        select(Document)
        .join(
            Project,
            (Project.tenant_id == Document.tenant_id) & (Project.id == Document.project_id),
        )
        .where(
            Document.tenant_id == principal.tenant_id,
            Document.id == document_id,
            Document.deletion_requested_at.is_(None),
            Project.deletion_requested_at.is_(None),
        )
        .with_for_update()
    )
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND"})
    await require_project_access(
        session,
        principal=principal,
        project_id=document.project_id,
        capability="write",
    )
    if document.status not in {
        "SECURITY_VERIFIED",
        "ANALYSIS_QUEUED",
        "PREFLIGHTING",
        "COMPLETED",
        "PARSE_FAILED",
    }:
        raise HTTPException(
            status_code=409,
            detail={"code": "DOCUMENT_NOT_SECURITY_VERIFIED", "status": document.status},
        )
    if document.source_file_id is None:
        raise HTTPException(status_code=409, detail={"code": "SOURCE_NOT_READY"})
    source = await session.get(SourceFile, document.source_file_id)
    if source is None or source.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=409, detail={"code": "SOURCE_NOT_READY"})
    if source.size_bytes > request.app.state.settings.analysis_max_source_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "ANALYSIS_SOURCE_TOO_LARGE",
                "max_bytes": request.app.state.settings.analysis_max_source_bytes,
            },
        )
    analysis_version = document.active_version
    task = await session.scalar(
        select(AnalysisTask).where(
            AnalysisTask.tenant_id == principal.tenant_id,
            AnalysisTask.document_id == document.id,
            AnalysisTask.document_version == analysis_version,
        )
    )
    created = task is None
    if task is None:
        task = AnalysisTask(
            tenant_id=principal.tenant_id,
            project_id=document.project_id,
            document_id=document.id,
            document_version=analysis_version,
            source_file_id=source.id,
            requested_by=principal.user_id,
            status="queued",
            max_attempts=request.app.state.settings.analysis_max_attempts,
        )
        session.add(task)
        await session.flush()
        session.add(
            OutboxEvent(
                tenant_id=principal.tenant_id,
                aggregate_type="analysis_task",
                aggregate_id=task.id,
                event_type="document.analysis.requested.v1",
                payload={
                    "task_id": str(task.id),
                    "tenant_id": str(principal.tenant_id),
                    "document_id": str(document.id),
                },
            )
        )
        document.status = "ANALYSIS_QUEUED"
        await audit(
            session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action="document.analysis_queued",
            target_type="document",
            target_id=str(document.id),
            metadata={"task_id": str(task.id)},
        )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        task = await session.scalar(
            select(AnalysisTask).where(
                AnalysisTask.tenant_id == principal.tenant_id,
                AnalysisTask.document_id == document_id,
                AnalysisTask.document_version == analysis_version,
            )
        )
        if task is None:
            raise
        created = False
    if created and request.app.state.settings.local_analysis_worker_enabled:
        background_tasks.add_task(
            _execute_local_analysis_task,
            request.app,
            task.id,
        )
    return _analysis_response(task)


@router.post(
    "/documents/{document_id}/reprocess",
    response_model=AnalyzeResponse,
    status_code=202,
)
@idempotent_mutation
async def reprocess_document(
    document_id: uuid.UUID,
    payload: ReprocessRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: EditorDep,
    session: SessionDep,
) -> AnalyzeResponse:
    await _require_verified_for_operation(
        request,
        session,
        principal,
        control="analyze",
    )
    document = await _tenant_document(
        session,
        principal.tenant_id,
        document_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    if document.active_version != payload.expected_active_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SOURCE_VERSION_CHANGED",
                "active_version": document.active_version,
            },
        )
    if document.source_file_id is None:
        raise HTTPException(status_code=409, detail={"code": "SOURCE_NOT_READY"})
    if document.status not in {"COMPLETED", "PARSE_FAILED"}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOCUMENT_REPROCESS_NOT_READY",
                "status": document.status,
            },
        )
    source = await session.scalar(
        select(SourceFile).where(
            SourceFile.tenant_id == principal.tenant_id,
            SourceFile.id == document.source_file_id,
        )
    )
    if source is None:
        raise HTTPException(status_code=409, detail={"code": "SOURCE_NOT_READY"})
    current_version = await session.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.tenant_id == principal.tenant_id,
            DocumentVersion.document_id == document.id,
            DocumentVersion.version == document.active_version,
        )
        .with_for_update()
    )
    if current_version is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "DOCUMENT_VERSION_STATE_CORRUPT"},
        )
    next_version = document.active_version + 1
    active_upload = await session.scalar(
        select(UploadSession.id).where(
            UploadSession.tenant_id == principal.tenant_id,
            UploadSession.document_id == document.id,
            UploadSession.document_version == next_version,
            UploadSession.status.in_(("initiated", "uploaded")),
        )
    )
    if active_upload is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "DOCUMENT_VERSION_UPLOAD_ACTIVE"},
        )
    now = utcnow()
    snapshot = await archive_active_document_version(
        session,
        store=request.app.state.object_store,
        document=document,
        now=now,
    )
    superseded_work = await _supersede_document_work(
        session,
        tenant_id=principal.tenant_id,
        document_id=document.id,
        previous_version=document.active_version,
        next_version=next_version,
        now=now,
    )
    await clear_active_document_projection(
        session,
        tenant_id=principal.tenant_id,
        document_id=document.id,
    )
    session.add(
        DocumentVersion(
            tenant_id=principal.tenant_id,
            document_id=document.id,
            version=next_version,
            source_file_id=source.id,
            source_sha256=source.sha256,
            source_filename=source.safe_filename,
            source_mime_type=source.mime_type,
            source_size_bytes=source.size_bytes,
            cir_object_key=None,
            cir_snapshot_sha256=None,
            archived_objects=[],
            input_revision_hash=source.sha256,
            policy_version="pending-reprocess-v1",
            model_revision="unprocessed",
            prompt_revision=None,
            normalization_revision=None,
            akmp_schema_version="1.0",
            status="source_verified",
        )
    )
    document.active_version = next_version
    document.page_count = None
    document.language_codes = []
    document.status = "ANALYSIS_QUEUED"
    document.updated_at = now
    task = AnalysisTask(
        tenant_id=principal.tenant_id,
        project_id=document.project_id,
        document_id=document.id,
        document_version=next_version,
        source_file_id=source.id,
        requested_by=principal.user_id,
        status="queued",
        max_attempts=request.app.state.settings.analysis_max_attempts,
    )
    session.add(task)
    await session.flush()
    session.add(
        OutboxEvent(
            tenant_id=principal.tenant_id,
            aggregate_type="analysis_task",
            aggregate_id=task.id,
            event_type="document.analysis.requested.v1",
            payload={
                "task_id": str(task.id),
                "tenant_id": str(principal.tenant_id),
                "document_id": str(document.id),
                "document_version": next_version,
            },
        )
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="document.reprocess_queued",
        target_type="document",
        target_id=str(document.id),
        metadata={
            "previous_version": payload.expected_active_version,
            "next_version": next_version,
            "previous_snapshot_sha256": snapshot.sha256,
            "reason": payload.reason,
            "superseded_work": superseded_work,
        },
    )
    await session.commit()
    if request.app.state.settings.local_analysis_worker_enabled:
        background_tasks.add_task(
            _execute_local_analysis_task,
            request.app,
            task.id,
        )
    return _analysis_response(task)


@router.get(
    "/documents/{document_id}/analysis",
    response_model=AnalyzeResponse,
)
async def get_analysis(
    document_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> AnalyzeResponse:
    document = await _tenant_document(
        session,
        principal.tenant_id,
        document_id,
        principal=principal,
        capability="read",
    )
    task = await session.scalar(
        select(AnalysisTask)
        .where(
            AnalysisTask.tenant_id == principal.tenant_id,
            AnalysisTask.document_id == document.id,
            AnalysisTask.document_version == document.active_version,
        )
        .order_by(AnalysisTask.created_at.desc())
    )
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "ANALYSIS_NOT_FOUND"})
    return _analysis_response(task)


@router.get("/documents/{document_id}/estimate", response_model=EstimateResponse)
async def estimate(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> EstimateResponse:
    document = await _tenant_document(
        session,
        principal.tenant_id,
        document_id,
        lock=True,
        principal=principal,
        capability="read",
    )
    values = await estimate_document(session, document)
    return EstimateResponse(
        total_pages=values["total_pages"],
        native_pages=values["native_pages"],
        visual_pages=values["visual_pages"],
        precision_candidate_pages=values["precision_candidate_pages"],
        tables=values["tables"],
        formulas=values["formulas"],
        figures=values["figures"],
        credit_min=values["expected"],
        credit_max=values["upper_bound"],
        third_party_model_api=values["third_party_model_api"],
        expected_duration_min=values["expected_duration_min"],
        expected_duration_max=values["expected_duration_max"],
        expected=values["expected"],
        upper_bound=values["upper_bound"],
        reserved=values["reserved"],
        breakdown={
            "native": values["native"],
            "visual": values["visual"],
            "knowledge": values["knowledge"],
        },
    )


async def _execute_background_job(
    app: FastAPI,
    job_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> None:
    async with app.state.database.sessions() as session:
        await set_rls_context(session, tenant_id=tenant_id)
        await run_compile_job(
            session=session,
            job_id=job_id,
            settings=app.state.settings,
            object_store=app.state.object_store,
        )


@router.post("/documents/{document_id}/compile", response_model=JobResponse, status_code=202)
@idempotent_mutation
async def compile_document(
    document_id: uuid.UUID,
    payload: CompileRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: EditorDep,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProcessingJob:
    await _require_verified_for_operation(
        request,
        session,
        principal,
        control="compile",
    )
    document = await _tenant_document(
        session,
        principal.tenant_id,
        document_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    if document.status != "COMPLETED":
        raise HTTPException(status_code=409, detail={"code": "ANALYSIS_REQUIRED"})
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})
    if "jsonld" in payload.output_profiles and not await feature_enabled(
        session,
        tenant_id=principal.tenant_id,
        key=ONTOLOGY_EXPORT_FLAG,
        user_id=principal.user_id,
        document_type=document.document_type,
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "FEATURE_NOT_ENABLED",
                "feature": ONTOLOGY_EXPORT_FLAG,
            },
        )
    if payload.external_processing_consent and (
        tenant.private_mode or not tenant.external_transfer_allowed
    ):
        raise HTTPException(status_code=403, detail={"code": "EXTERNAL_TRANSFER_DENIED"})
    values = await estimate_document(session, document)
    if values["total_pages"] <= 0:
        raise HTTPException(status_code=409, detail={"code": "DOCUMENT_HAS_NO_PAGES"})
    if payload.max_credits is not None and payload.max_credits < values["reserved"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CREDIT_CAP_BELOW_ESTIMATE",
                "required": str(values["reserved"]),
                "maximum": str(payload.max_credits),
            },
        )
    job_id = uuid.uuid4()
    dispatch_idempotency_key = idempotency_key or f"job:{job_id}"
    job = ProcessingJob(
        id=job_id,
        tenant_id=principal.tenant_id,
        project_id=document.project_id,
        document_id=document.id,
        job_type="compile",
        priority=queue_priority_for_plan(tenant.plan_code),
        requested_options={
            **payload.model_dump(mode="json"),
            "idempotency_key": dispatch_idempotency_key,
            "document_version": document.active_version,
            "document_version_id": f"{document.id}:v{document.active_version}",
            "requested_by": str(principal.user_id),
            "queue_class": (
                "free_low" if queue_priority_for_plan(tenant.plan_code) == 1 else "standard"
            ),
        },
        cost_estimate={key: str(value) for key, value in values.items()},
        progress={"done": 0, "total": values["total_pages"]},
    )
    session.add(job)
    await session.flush()
    gpu_cost = estimate_gpu_cost(
        visual_pages=int(values["visual_pages"]),
        per_visual_page_usd=(request.app.state.settings.free_gpu_cost_per_visual_page_usd),
    )
    try:
        if gpu_cost > 0:
            await reserve_free_usage(
                session,
                tenant_id=principal.tenant_id,
                plan_code=tenant.plan_code,
                operation_key=f"compile:{job.id}:gpu",
                delta=FreeUsageDelta(gpu_cost_usd=gpu_cost),
                caps=_free_caps(request.app.state.settings),
            )
    except FreeTierCapExceeded as exc:
        await _raise_free_cap(
            request,
            session,
            principal=principal,
            control="free_gpu_cap",
            target_type="job",
            target_id=str(job.id),
            error=exc,
        )
    await credit_entry(
        session,
        tenant_id=principal.tenant_id,
        operation_key=f"job:{job.id}:attempt:0:reserve",
        entry_type="reserve",
        credits=values["reserved"],
        job_id=job.id,
    )
    await emit_event(
        session,
        job=job,
        event_type="job.created.v1",
        payload={"status": "queued", "job_type": "compile"},
    )
    await emit_event(
        session,
        job=job,
        event_type="credit.reserved.v1",
        payload={"credits": str(values["reserved"])},
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
                "document_version": document.active_version,
                "document_version_id": f"{document.id}:v{document.active_version}",
                "idempotency_key": dispatch_idempotency_key,
            },
        )
    )
    await session.commit()
    if request.app.state.settings.local_background_tasks:
        background_tasks.add_task(
            _execute_background_job,
            request.app,
            job.id,
            principal.tenant_id,
        )
    return job


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _snapshot_block_type_totals(blocks: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for block in blocks:
        block_type = str(block.get("type") or block.get("block_type") or "unknown")
        totals[block_type] = totals.get(block_type, 0) + 1
    return dict(sorted(totals.items()))


def _snapshot_removed_marginals(blocks: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"header": 0, "footer": 0}
    for block in blocks:
        structured = block.get("structured_content")
        if not isinstance(structured, dict):
            continue
        normalization = structured.get("normalization")
        if not isinstance(normalization, dict):
            continue
        annotation = normalization.get("repeatedMarginal")
        if not isinstance(annotation, dict) or annotation.get("excludedFromBody") is not True:
            continue
        classified_type = annotation.get("classifiedType")
        if classified_type in totals:
            totals[classified_type] += 1
    return totals


def _gpu_seconds_from_invocations(invocations: list[GpuProviderInvocation]) -> float | None:
    measured: list[float] = []
    for invocation in invocations:
        manifest = invocation.result_manifest
        if not isinstance(manifest, dict):
            continue
        metrics = manifest.get("metrics")
        if not isinstance(metrics, dict):
            continue
        value = metrics.get("gpu_seconds")
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            continue
        measured.append(float(value))
    return round(sum(measured), 6) if measured else None


async def _job_operational_counters(
    session: AsyncSession,
    *,
    job: ProcessingJob,
    tenant_id: uuid.UUID,
) -> dict[str, int | float | None]:
    invocations = list(
        (
            await session.scalars(
                select(GpuProviderInvocation).where(
                    GpuProviderInvocation.tenant_id == tenant_id,
                    GpuProviderInvocation.job_id == job.id,
                )
            )
        ).all()
    )
    queue_position: int | None = None
    if job.status == "queued":
        ahead = await session.scalar(
            select(func.count(ProcessingJob.id)).where(
                ProcessingJob.tenant_id == tenant_id,
                ProcessingJob.status == "queued",
                or_(
                    ProcessingJob.priority < job.priority,
                    and_(
                        ProcessingJob.priority == job.priority,
                        or_(
                            ProcessingJob.created_at < job.created_at,
                            and_(
                                ProcessingJob.created_at == job.created_at,
                                ProcessingJob.id < job.id,
                            ),
                        ),
                    ),
                ),
            )
        )
        queue_position = int(ahead or 0) + 1
    return {
        "gpu_seconds": _gpu_seconds_from_invocations(invocations),
        "queue_position": queue_position,
    }


async def _archived_job_snapshot_payload(
    session: AsyncSession,
    *,
    job: ProcessingJob,
    document: Document,
    tenant_id: uuid.UUID,
    document_version: int,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Render an old job from its authenticated immutable document snapshot."""

    source_value = snapshot.get("source")
    source = source_value if isinstance(source_value, dict) else {}
    document_value = snapshot.get("document")
    document_snapshot = document_value if isinstance(document_value, dict) else {}
    page_values = snapshot.get("pages")
    pages = (
        [value for value in page_values if isinstance(value, dict)]
        if isinstance(page_values, list)
        else []
    )
    attempt_values = snapshot.get("page_attempts")
    attempts = (
        [value for value in attempt_values if isinstance(value, dict)]
        if isinstance(attempt_values, list)
        else []
    )
    block_values = snapshot.get("blocks")
    blocks = (
        [value for value in block_values if isinstance(value, dict)]
        if isinstance(block_values, list)
        else []
    )
    review_values = snapshot.get("review_items")
    reviews = (
        [value for value in review_values if isinstance(value, dict)]
        if isinstance(review_values, list)
        else []
    )
    note_values = snapshot.get("knowledge_notes")
    notes = (
        [value for value in note_values if isinstance(value, dict)]
        if isinstance(note_values, list)
        else []
    )
    classification_values = snapshot.get("semantic_classifications")
    classifications = (
        [value for value in classification_values if isinstance(value, dict)]
        if isinstance(classification_values, list)
        else []
    )

    semantic_payload: dict[str, Any] | None = None
    semantic_row = next(
        (value for value in reversed(classifications) if value.get("is_active") is True),
        classifications[-1] if classifications else None,
    )
    if semantic_row is not None:
        try:
            semantic = DocumentClassification.model_validate(semantic_row.get("classification"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "SEMANTIC_CLASSIFICATION_INVALID"},
            ) from exc
        semantic_payload = {
            "semantic_type": semantic.document_type,
            "languages": list(semantic.languages or (semantic.language,)),
            "topics": list(semantic.topics),
            "domains": list(semantic.domain),
            "evidence_block_ids": list(semantic.evidence_block_ids),
            "confidence": semantic.confidence,
            "model_attestation": {
                "provider_key": semantic_row.get("provider_key"),
                "model_revision": semantic_row.get("model_revision"),
                "runtime_image_digest": semantic_row.get("runtime_image_digest"),
                "adapter_version": semantic_row.get("adapter_version"),
                "prompt_revision": semantic_row.get("prompt_revision"),
                "schema_sha256": semantic_row.get("schema_sha256"),
            },
        }

    latest_attempts: dict[str, dict[str, Any]] = {}
    for attempt in attempts:
        page_id = str(attempt.get("page_id", ""))
        if not page_id:
            continue
        previous = latest_attempts.get(page_id)
        if previous is None or int(attempt.get("attempt_number", 0)) > int(
            previous.get("attempt_number", 0)
        ):
            latest_attempts[page_id] = attempt

    blocks_by_page: dict[str, list[dict[str, Any]]] = {}
    page_numbers = {str(page.get("id")): int(page.get("page_number", 0)) for page in pages}
    for block in blocks:
        page_id_value = block.get("page_id")
        if page_id_value is None:
            continue
        page_id = str(page_id_value)
        origin = str(block.get("origin") or "source_extracted")
        content_layer = (
            "knowledge"
            if origin in {"ai_summarized", "ai_inferred"}
            else "structured"
            if origin in {"rule_reconstructed", "ai_reconstructed"}
            else "extracted"
        )
        block_type = str(block.get("type") or "unknown")
        if block_type not in {
            "title",
            "heading",
            "paragraph",
            "list",
            "table",
            "figure",
            "caption",
            "formula",
            "code",
            "quote",
            "footnote",
            "unknown",
        }:
            block_type = "unknown"
        page_number = page_numbers.get(page_id, 0)
        blocks_by_page.setdefault(page_id, []).append(
            {
                "id": str(block.get("id")),
                "order": int(block.get("order", 0)),
                "type": block_type,
                "markdown": (block.get("markdown") or block.get("normalized_text") or ""),
                "source_text": block.get("source_text") or "",
                "origin": origin,
                "content_layer": content_layer,
                "source_refs": [
                    {
                        "document_id": str(document.id),
                        "document_version_id": (f"{document.id}:v{document_version}"),
                        "page_index": max(0, page_number - 1),
                        "page_number": page_number,
                        "bbox1000": block.get("bbox1000"),
                    }
                ],
                "confidence": block.get("confidence"),
                "quality_flags": block.get("warnings") or [],
                "revision": int(block.get("revision", 1)),
            }
        )

    page_payload: list[dict[str, Any]] = []
    for page in pages:
        page_id = str(page.get("id"))
        route = str(page.get("route") or "manual_review")
        latest_attempt = latest_attempts.get(page_id)
        quality_value = page.get("quality_metrics")
        quality_metrics = quality_value if isinstance(quality_value, dict) else {}
        preflight_value = page.get("preflight_metrics")
        preflight_metrics = preflight_value if isinstance(preflight_value, dict) else {}
        quality_state = str(quality_metrics.get("state", "review"))
        if quality_state not in {"verified", "warning", "review", "failed"}:
            quality_state = "review"
        page_payload.append(
            {
                "id": page_id,
                "page_number": int(page.get("page_number", 0)),
                "status": str(page.get("status") or "PENDING").casefold(),
                "route_profile": str(preflight_metrics.get("route_profile", route)),
                "route_label": {
                    "native": "Native",
                    "paddle_vl": "OCR",
                    "paddle_fast": "Fast",
                    "hpd_fast": "Fast",
                    "mistral_fallback": "Fallback",
                    "manual_review": "Fallback",
                }.get(route, "Fallback"),
                "quality_state": quality_state,
                "attempt": (
                    {
                        "id": str(latest_attempt.get("id")),
                        "number": int(latest_attempt.get("attempt_number", 0)),
                        "status": str(latest_attempt.get("status") or "PENDING").casefold(),
                        "route": latest_attempt.get("route"),
                        "route_profile": latest_attempt.get("route_profile"),
                        "quality": latest_attempt.get("quality_evaluation") or {},
                        "escalation": latest_attempt.get("escalation_decision") or {},
                    }
                    if latest_attempt is not None
                    else None
                ),
                # Archived rows are intentionally not routed through mutable page APIs.
                "thumbnail_url": None,
                "blocks": blocks_by_page.get(page_id, []),
            }
        )

    ledger = list(
        (
            await session.scalars(
                select(CreditLedger).where(
                    CreditLedger.tenant_id == tenant_id,
                    CreditLedger.job_id == job.id,
                )
            )
        ).all()
    )
    events = list(
        (
            await session.scalars(
                select(JobEvent)
                .where(
                    JobEvent.tenant_id == tenant_id,
                    JobEvent.job_id == job.id,
                    JobEvent.event_type == "job.stage.progress.v1",
                )
                .order_by(JobEvent.sequence)
            )
        ).all()
    )
    stage_progress: dict[str, dict[str, int]] = {}
    for event in events:
        stage = str(event.payload.get("stage", ""))
        if stage:
            stage_progress[stage] = {
                "done": int(event.payload.get("done", 0)),
                "total": int(event.payload.get("total", 0)),
            }
    reserved = sum(Decimal(row.credits) for row in ledger if row.entry_type == "reserve") - sum(
        Decimal(row.credits) for row in ledger if row.entry_type in {"consume", "release"}
    )
    used = sum(Decimal(row.credits) for row in ledger if row.entry_type == "consume")
    total = int(job.progress.get("total", len(pages) or 1))
    done = int(job.progress.get("done", 0))
    started = _aware(job.started_at or job.created_at)
    finished = _aware(job.completed_at or utcnow())
    operational = await _job_operational_counters(
        session,
        job=job,
        tenant_id=tenant_id,
    )
    nested_job = {
        "id": str(job.id),
        "status": job.status,
        "route_profile": job.requested_options.get(
            "route_profile",
            "parse_balanced_v1",
        ),
        "progress": min(1.0, done / max(1, total)),
        "credits": {
            "estimated": float(Decimal(str(job.cost_estimate.get("expected", "0")))),
            "used": float(used),
            "reserved": float(max(Decimal("0"), reserved)),
            "maximum": float(
                Decimal(
                    str(
                        job.requested_options.get("max_credits")
                        or job.cost_estimate.get("reserved", "0")
                    )
                )
            ),
        },
    }
    return {
        "id": str(job.id),
        "status": job.status,
        "job_type": job.job_type,
        "last_sequence": job.event_sequence,
        "document_version": document_version,
        "job": nested_job,
        "document": {
            "id": str(document.id),
            "version": document_version,
            "title": str(document_snapshot.get("title") or document.title),
            "filename": str(source.get("filename") or document.title),
            "file_type": document_snapshot.get("source_format"),
            "semantic_classification": semantic_payload,
        },
        "stage_progress": stage_progress,
        "pages": page_payload,
        "reviews": [
            {
                "id": str(review.get("id")),
                "severity": review.get("severity"),
                "category": review.get("category"),
                "message": (
                    review.get("evidence", {}).get(
                        "message",
                        review.get("category"),
                    )
                    if isinstance(review.get("evidence"), dict)
                    else review.get("category")
                ),
                "page_id": review.get("page_id"),
                "block_id": review.get("block_id"),
                "status": review.get("status"),
                "candidates": (
                    review.get("evidence", {}).get("candidates", [])
                    if isinstance(review.get("evidence"), dict)
                    else []
                ),
            }
            for review in reviews
        ],
        "summary": {
            "completed_pages": sum(
                str(page.get("status") or "").upper() == "COMPLETED" for page in pages
            ),
            "native_pages": sum(page.get("route") == "native" for page in pages),
            "ocr_pages": sum(
                page.get("route") not in {None, "native", "manual_review"} for page in pages
            ),
            "tables_rebuilt": sum(block.get("type") == "table" for block in blocks),
            "knowledge_notes": sum(note.get("is_active", True) is not False for note in notes),
            "third_party_pages": sum(page.get("route") == "mistral_fallback" for page in pages),
            "elapsed_seconds": max(0.0, (finished - started).total_seconds()),
            "blocks": len(blocks),
            "route_totals": {
                route: sum(str(page.get("route") or "manual_review") == route for page in pages)
                for route in sorted(
                    {str(page.get("route") or "manual_review") for page in pages}
                )
            },
            "block_type_totals": _snapshot_block_type_totals(blocks),
            "removed_header_footer": _snapshot_removed_marginals(blocks),
            "review_blocks": sum(review.get("status") == "open" for review in reviews),
            **operational,
        },
    }


async def _job_snapshot_payload(
    session: AsyncSession,
    *,
    job: ProcessingJob,
    tenant_id: uuid.UUID,
    object_store: ObjectStore,
) -> dict[str, Any]:
    if job.document_id is None:
        raise HTTPException(status_code=409, detail={"code": "JOB_DOCUMENT_MISSING"})
    document = await _tenant_document(session, tenant_id, job.document_id)
    raw_document_version = job.requested_options.get(
        "document_version",
        document.active_version,
    )
    if isinstance(raw_document_version, bool):
        raise HTTPException(
            status_code=409,
            detail={"code": "JOB_DOCUMENT_VERSION_INVALID"},
        )
    try:
        document_version = int(raw_document_version)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "JOB_DOCUMENT_VERSION_INVALID"},
        ) from exc
    if document_version < 1:
        raise HTTPException(
            status_code=409,
            detail={"code": "JOB_DOCUMENT_VERSION_INVALID"},
        )
    if document_version != document.active_version:
        version = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.document_id == document.id,
                DocumentVersion.version == document_version,
            )
        )
        if version is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "JOB_DOCUMENT_VERSION_MISSING"},
            )
        try:
            archived_snapshot = await read_public_document_version_snapshot(
                store=object_store,
                version=version,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "JOB_DOCUMENT_VERSION_SNAPSHOT_INVALID"},
            ) from exc
        return await _archived_job_snapshot_payload(
            session,
            job=job,
            document=document,
            tenant_id=tenant_id,
            document_version=document_version,
            snapshot=archived_snapshot,
        )
    semantic_row = await session.scalar(
        select(DocumentSemanticClassification).where(
            DocumentSemanticClassification.tenant_id == tenant_id,
            DocumentSemanticClassification.document_id == document.id,
            DocumentSemanticClassification.document_version == document.active_version,
            DocumentSemanticClassification.is_active.is_(True),
        )
    )
    semantic_payload: dict[str, Any] | None = None
    if semantic_row is not None:
        try:
            semantic = DocumentClassification.model_validate(semantic_row.classification)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "SEMANTIC_CLASSIFICATION_INVALID"},
            ) from exc
        semantic_payload = {
            "semantic_type": semantic.document_type,
            "languages": list(semantic.languages or (semantic.language,)),
            "topics": list(semantic.topics),
            "domains": list(semantic.domain),
            "evidence_block_ids": list(semantic.evidence_block_ids),
            "confidence": semantic.confidence,
            "model_attestation": {
                "provider_key": semantic_row.provider_key,
                "model_revision": semantic_row.model_revision,
                "runtime_image_digest": semantic_row.runtime_image_digest,
                "adapter_version": semantic_row.adapter_version,
                "prompt_revision": semantic_row.prompt_revision,
                "schema_sha256": semantic_row.schema_sha256,
            },
        }
    source = (
        await session.get(SourceFile, document.source_file_id) if document.source_file_id else None
    )
    pages = list(
        (
            await session.scalars(
                select(Page)
                .where(
                    Page.tenant_id == tenant_id,
                    Page.document_id == document.id,
                )
                .order_by(Page.page_number)
            )
        ).all()
    )
    latest_page_attempts = await latest_attempts_for_pages(
        session,
        tenant_id=tenant_id,
        page_ids=(page.id for page in pages),
    )
    blocks = list(
        (
            await session.scalars(
                select(Block)
                .where(
                    Block.tenant_id == tenant_id,
                    Block.document_id == document.id,
                )
                .order_by(Block.block_order)
            )
        ).all()
    )
    review_rows = list(
        (
            await session.scalars(
                select(ReviewItem)
                .where(
                    ReviewItem.tenant_id == tenant_id,
                    ReviewItem.document_id == document.id,
                )
                .order_by(ReviewItem.created_at)
            )
        ).all()
    )
    ledger = list(
        (
            await session.scalars(
                select(CreditLedger).where(
                    CreditLedger.tenant_id == tenant_id,
                    CreditLedger.job_id == job.id,
                )
            )
        ).all()
    )
    events = list(
        (
            await session.scalars(
                select(JobEvent)
                .where(
                    JobEvent.tenant_id == tenant_id,
                    JobEvent.job_id == job.id,
                    JobEvent.event_type == "job.stage.progress.v1",
                )
                .order_by(JobEvent.sequence)
            )
        ).all()
    )
    stage_progress: dict[str, dict[str, int]] = {}
    for event in events:
        stage = str(event.payload.get("stage", ""))
        if stage:
            stage_progress[stage] = {
                "done": int(event.payload.get("done", 0)),
                "total": int(event.payload.get("total", 0)),
            }

    blocks_by_page: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for block in blocks:
        if block.page_id is None:
            continue
        page = next((row for row in pages if row.id == block.page_id), None)
        if page is None:
            continue
        content_layer = (
            "knowledge"
            if block.origin in {"ai_summarized", "ai_inferred"}
            else "structured"
            if block.origin in {"rule_reconstructed", "ai_reconstructed"}
            else "extracted"
        )
        blocks_by_page.setdefault(block.page_id, []).append(
            {
                "id": str(block.id),
                "order": block.block_order,
                "type": block.block_type
                if block.block_type
                in {
                    "title",
                    "heading",
                    "paragraph",
                    "list",
                    "table",
                    "figure",
                    "caption",
                    "formula",
                    "code",
                    "quote",
                    "footnote",
                    "unknown",
                }
                else "unknown",
                "markdown": block.markdown or block.normalized_text or "",
                "source_text": block.source_text or "",
                "origin": block.origin,
                "content_layer": content_layer,
                "source_refs": [
                    {
                        "document_id": str(document.id),
                        "document_version_id": (f"{document.id}:v{document.active_version}"),
                        "page_index": page.page_number - 1,
                        "page_number": page.page_number,
                        "bbox1000": block.bbox1000,
                    }
                ],
                "confidence": block.confidence,
                "quality_flags": block.warnings,
                "revision": block.revision,
            }
        )

    page_payload = []
    for page in pages:
        route = page.route or "manual_review"
        latest_attempt = latest_page_attempts.get(page.id)
        quality_state = str(page.quality_metrics.get("state", "review"))
        if quality_state not in {"verified", "warning", "review", "failed"}:
            quality_state = "review"
        page_payload.append(
            {
                "id": str(page.id),
                "page_number": page.page_number,
                "status": page.status.casefold(),
                "route_profile": str(page.preflight_metrics.get("route_profile", route)),
                "route_label": {
                    "native": "Native",
                    "paddle_vl": "OCR",
                    "paddle_fast": "Fast",
                    "hpd_fast": "Fast",
                    "mistral_fallback": "Fallback",
                    "manual_review": "Fallback",
                }.get(route, "Fallback"),
                "quality_state": quality_state,
                "attempt": (
                    {
                        "id": str(latest_attempt.id),
                        "number": latest_attempt.attempt_number,
                        "status": latest_attempt.status.casefold(),
                        "route": latest_attempt.route,
                        "route_profile": latest_attempt.route_profile,
                        "quality": latest_attempt.quality_evaluation,
                        "escalation": latest_attempt.escalation_decision,
                    }
                    if latest_attempt is not None
                    else None
                ),
                "thumbnail_url": (f"/v1/pages/{page.id}/preview" if page.thumbnail_key else None),
                "blocks": blocks_by_page.get(page.id, []),
            }
        )
    reserved = sum(Decimal(row.credits) for row in ledger if row.entry_type == "reserve") - sum(
        Decimal(row.credits) for row in ledger if row.entry_type in {"consume", "release"}
    )
    used = sum(Decimal(row.credits) for row in ledger if row.entry_type == "consume")
    total = int(job.progress.get("total", len(pages) or 1))
    done = int(job.progress.get("done", 0))
    started = _aware(job.started_at or job.created_at)
    finished = _aware(job.completed_at or utcnow())
    operational = await _job_operational_counters(
        session,
        job=job,
        tenant_id=tenant_id,
    )
    serialized_blocks = [
        {
            "type": block.block_type,
            "structured_content": block.structured_content,
        }
        for block in blocks
    ]
    nested_job = {
        "id": str(job.id),
        "status": job.status,
        "route_profile": job.requested_options.get(
            "route_profile",
            "parse_balanced_v1",
        ),
        "progress": min(1.0, done / max(1, total)),
        "credits": {
            "estimated": float(Decimal(str(job.cost_estimate.get("expected", "0")))),
            "used": float(used),
            "reserved": float(max(Decimal("0"), reserved)),
            "maximum": float(
                Decimal(
                    str(
                        job.requested_options.get("max_credits")
                        or job.cost_estimate.get("reserved", "0")
                    )
                )
            ),
        },
    }
    return {
        "id": str(job.id),
        "status": job.status,
        "job_type": job.job_type,
        "last_sequence": job.event_sequence,
        "document_version": document_version,
        "job": nested_job,
        "document": {
            "id": str(document.id),
            "version": document_version,
            "title": document.title,
            "filename": source.safe_filename if source else document.title,
            "file_type": document.document_type,
            "semantic_classification": semantic_payload,
        },
        "stage_progress": stage_progress,
        "pages": page_payload,
        "reviews": [
            {
                "id": str(review.id),
                "severity": review.severity,
                "category": review.category,
                "message": review.evidence.get("message", review.category),
                "page_id": str(review.page_id) if review.page_id else None,
                "block_id": str(review.block_id) if review.block_id else None,
                "status": review.status,
                "candidates": review.evidence.get("candidates", []),
            }
            for review in review_rows
        ],
        "summary": {
            "completed_pages": sum(page.status == "COMPLETED" for page in pages),
            "native_pages": sum(page.route == "native" for page in pages),
            "ocr_pages": sum(page.route not in {None, "native", "manual_review"} for page in pages),
            "tables_rebuilt": sum(block.block_type == "table" for block in blocks),
            "knowledge_notes": await session.scalar(
                select(func.count(KnowledgeNote.id)).where(
                    KnowledgeNote.tenant_id == tenant_id,
                    KnowledgeNote.project_id == job.project_id,
                    KnowledgeNote.document_id == document.id,
                    KnowledgeNote.document_version == document.active_version,
                    KnowledgeNote.is_active.is_(True),
                )
            )
            or 0,
            "third_party_pages": sum(page.route == "mistral_fallback" for page in pages),
            "elapsed_seconds": max(
                0.0,
                (finished - started).total_seconds(),
            ),
            "blocks": len(blocks),
            "route_totals": {
                route: sum((page.route or "manual_review") == route for page in pages)
                for route in sorted({page.route or "manual_review" for page in pages})
            },
            "block_type_totals": _snapshot_block_type_totals(serialized_blocks),
            "removed_header_footer": _snapshot_removed_marginals(serialized_blocks),
            "review_blocks": sum(review.status == "open" for review in review_rows),
            **operational,
        },
    }


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> dict[str, Any]:
    job = await _tenant_job(
        session,
        principal.tenant_id,
        job_id,
        principal=principal,
        capability="read",
    )
    return await _job_snapshot_payload(
        session,
        job=job,
        tenant_id=principal.tenant_id,
        object_store=request.app.state.object_store,
    )


def _event_wire(
    row: JobEvent,
    *,
    project_id: uuid.UUID,
    document_id: uuid.UUID | None,
) -> EventWire:
    page_id = row.payload.get("page_id")
    return EventWire(
        event_id=row.id,
        event_type=row.event_type,
        occurred_at=row.occurred_at,
        project_id=project_id,
        document_id=document_id,
        job_id=row.job_id,
        page_id=uuid.UUID(page_id) if page_id else None,
        sequence=row.sequence,
        schema_version="1.0",
        payload=row.payload,
    )


@router.get(
    "/jobs/{job_id}/events/replay",
    response_model=list[EventWire],
    response_model_exclude_none=True,
)
async def replay_events(
    job_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    after_sequence: int = Query(default=0, ge=0),
) -> list[EventWire]:
    job = await _tenant_job(
        session,
        principal.tenant_id,
        job_id,
        principal=principal,
        capability="read",
    )
    rows = list(
        (
            await session.scalars(
                select(JobEvent)
                .where(
                    JobEvent.tenant_id == principal.tenant_id,
                    JobEvent.job_id == job.id,
                    JobEvent.sequence > after_sequence,
                )
                .order_by(JobEvent.sequence)
                .limit(1000)
            )
        ).all()
    )
    return [
        _event_wire(
            row,
            project_id=job.project_id,
            document_id=job.document_id,
        )
        for row in rows
    ]


@router.get("/jobs/{job_id}/snapshot")
async def job_snapshot(
    job_id: uuid.UUID,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> dict[str, Any]:
    job = await _tenant_job(
        session,
        principal.tenant_id,
        job_id,
        principal=principal,
        capability="read",
    )
    return await _job_snapshot_payload(
        session,
        job=job,
        tenant_id=principal.tenant_id,
        object_store=request.app.state.object_store,
    )


@router.get("/jobs/{job_id}/events")
async def stream_events(
    job_id: uuid.UUID,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    job = await _tenant_job(
        session,
        principal.tenant_id,
        job_id,
        principal=principal,
        capability="read",
    )
    start_sequence = 0
    reset_required = False
    if last_event_id:
        try:
            start_sequence = max(0, int(last_event_id))
        except ValueError:
            try:
                event_uuid = uuid.UUID(last_event_id)
            except ValueError:
                reset_required = True
            else:
                event = await session.scalar(
                    select(JobEvent).where(
                        JobEvent.tenant_id == principal.tenant_id,
                        JobEvent.job_id == job.id,
                        JobEvent.id == event_uuid,
                    )
                )
                if event:
                    start_sequence = event.sequence
                else:
                    reset_required = True

    stream_job_id = job.id
    stream_project_id = job.project_id
    stream_document_id = job.document_id
    # A FastAPI yield dependency is not finalized until StreamingResponse
    # closes. Release the ownership-check transaction before opening the
    # long-lived stream so SQLite and PostgreSQL writers can finalize the job.
    await session.commit()

    async def generate() -> AsyncIterator[str]:
        sequence = start_sequence
        if reset_required:
            snapshot = {
                "event_id": str(uuid.uuid4()),
                "event_type": "stream.replay.reset.v1",
                "occurred_at": utcnow().isoformat(),
                "project_id": str(stream_project_id),
                "document_id": (str(stream_document_id) if stream_document_id else None),
                "job_id": str(stream_job_id),
                "page_id": None,
                "sequence": 0,
                "schema_version": "1.0",
                "payload": {"snapshot_url": f"/v1/jobs/{stream_job_id}/snapshot"},
            }
            yield f"event: stream.replay.reset.v1\ndata: {json.dumps(snapshot)}\n\n"
        while not await request.is_disconnected():
            async with request.app.state.database.sessions() as event_session:
                await set_rls_context(
                    event_session,
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                )
                active_job = await event_session.scalar(
                    select(ProcessingJob)
                    .join(
                        Project,
                        (Project.tenant_id == ProcessingJob.tenant_id)
                        & (Project.id == ProcessingJob.project_id),
                    )
                    .outerjoin(
                        Document,
                        (Document.tenant_id == ProcessingJob.tenant_id)
                        & (Document.id == ProcessingJob.document_id),
                    )
                    .where(
                        ProcessingJob.tenant_id == principal.tenant_id,
                        ProcessingJob.id == stream_job_id,
                        Project.deletion_requested_at.is_(None),
                        project_access_predicate(
                            principal,
                            ProcessingJob.project_id,
                            "read",
                        ),
                        or_(
                            ProcessingJob.document_id.is_(None),
                            Document.deletion_requested_at.is_(None),
                        ),
                    )
                )
                if active_job is None:
                    return
                rows = list(
                    (
                        await event_session.scalars(
                            select(JobEvent)
                            .where(
                                JobEvent.tenant_id == principal.tenant_id,
                                JobEvent.job_id == stream_job_id,
                                JobEvent.sequence > sequence,
                            )
                            .order_by(JobEvent.sequence)
                            .limit(100)
                        )
                    ).all()
                )
                current_job = active_job
                for row in rows:
                    if row.sequence != sequence + 1:
                        reset = {
                            "snapshot_url": (f"/v1/jobs/{stream_job_id}/snapshot"),
                            "expected_sequence": sequence + 1,
                            "received_sequence": row.sequence,
                        }
                        yield (f"event: stream.replay.reset.v1\ndata: {json.dumps(reset)}\n\n")
                    sequence = row.sequence
                    wire = _event_wire(
                        row,
                        project_id=stream_project_id,
                        document_id=stream_document_id,
                    ).model_dump_json(exclude_none=True)
                    yield f"id: {row.id}\nevent: {row.event_type}\ndata: {wire}\n\n"
                terminal = current_job and current_job.status in {
                    "completed",
                    "failed",
                    "cancelled",
                }
            if rows:
                if terminal and sequence >= (current_job.event_sequence if current_job else 0):
                    return
                continue
            yield ": heartbeat\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/documents/{document_id}/pages", response_model=list[PageResponse])
async def list_pages(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[dict[str, Any]]:
    await _tenant_document(
        session,
        principal.tenant_id,
        document_id,
        principal=principal,
        capability="read",
    )
    pages = list(
        (
            await session.scalars(
                select(Page)
                .where(
                    Page.tenant_id == principal.tenant_id,
                    Page.document_id == document_id,
                )
                .order_by(Page.page_number)
            )
        ).all()
    )
    latest = await latest_attempts_for_pages(
        session,
        tenant_id=principal.tenant_id,
        page_ids=(page.id for page in pages),
    )
    return [
        {
            "id": page.id,
            "document_id": page.document_id,
            "page_number": page.page_number,
            "status": page.status,
            "route": page.route,
            "preflight_metrics": page.preflight_metrics,
            "quality_metrics": page.quality_metrics,
            "latest_attempt_id": (latest[page.id].id if page.id in latest else None),
            "latest_attempt_number": (
                latest[page.id].attempt_number if page.id in latest else None
            ),
            "latest_attempt_status": (latest[page.id].status if page.id in latest else None),
        }
        for page in pages
    ]


@router.get("/documents/{document_id}/blocks", response_model=list[BlockResponse])
async def list_blocks(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[Block]:
    await _tenant_document(
        session,
        principal.tenant_id,
        document_id,
        principal=principal,
        capability="read",
    )
    return list(
        (
            await session.scalars(
                select(Block)
                .where(
                    Block.tenant_id == principal.tenant_id,
                    Block.document_id == document_id,
                )
                .order_by(Block.block_order)
            )
        ).all()
    )


@router.get("/pages/{page_id}/preview")
async def get_page_preview(
    page_id: uuid.UUID,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> Response:
    """Serve only authenticated, worker-produced derived previews."""

    page = await session.scalar(
        select(Page).where(
            Page.tenant_id == principal.tenant_id,
            Page.id == page_id,
        )
    )
    if page is None:
        raise HTTPException(status_code=404, detail={"code": "PAGE_NOT_FOUND"})
    await _tenant_document(
        session,
        principal.tenant_id,
        page.document_id,
        principal=principal,
        capability="read",
    )
    asset = await session.scalar(
        select(PageAsset)
        .where(
            PageAsset.tenant_id == principal.tenant_id,
            PageAsset.page_id == page.id,
            PageAsset.asset_type.in_(("preview", "thumbnail")),
        )
        .order_by(
            (PageAsset.asset_type == "preview").desc(),
            PageAsset.created_at.desc(),
        )
    )
    if asset is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PREVIEW_NOT_AVAILABLE",
                "reason": page.preflight_metrics.get(
                    "preview_unavailable_reason",
                    "not_generated",
                ),
            },
        )
    data = await request.app.state.object_store.read_derived(asset.storage_key)
    expected_size = int(asset.metadata_json.get("size_bytes", len(data)))
    if (
        len(data) <= 0
        or len(data) > 16 * 1024 * 1024
        or len(data) != expected_size
        or hashlib.sha256(data).hexdigest() != asset.sha256
    ):
        raise HTTPException(
            status_code=503,
            detail={"code": "PREVIEW_INTEGRITY_FAILURE"},
        )
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})
    effective_sha256 = asset.sha256
    redaction_state = "disabled"
    masked_region_count = 0
    if tenant.preview_pii_masking:
        redaction_state = "no-findings"
        page_blocks = list(
            (
                await session.scalars(
                    select(Block)
                    .where(
                        Block.tenant_id == principal.tenant_id,
                        Block.page_id == page.id,
                    )
                    .order_by(Block.block_order)
                )
            ).all()
        )
        boxes: set[tuple[int, int, int, int]] = set()
        unlocated_sensitive_block = False
        for block in page_blocks:
            source_text = block.source_text or block.normalized_text or block.markdown or ""
            if not source_text or not detect_sensitive_data(source_text).findings:
                continue
            bbox = block.bbox1000
            if (
                bbox is None
                or len(bbox) != 4
                or any(not isinstance(value, int) or isinstance(value, bool) for value in bbox)
                or not (0 <= bbox[0] < bbox[2] <= 1000)
                or not (0 <= bbox[1] < bbox[3] <= 1000)
            ):
                unlocated_sensitive_block = True
                continue
            boxes.add((bbox[0], bbox[1], bbox[2], bbox[3]))
        if unlocated_sensitive_block:
            raise HTTPException(
                status_code=503,
                detail={"code": "PREVIEW_REDACTION_LOCATION_UNAVAILABLE"},
            )
        if boxes:
            try:
                derivative = redact_preview_png(data, tuple(sorted(boxes)))
            except UnsafePreviewError as exc:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "PREVIEW_REDACTION_FAILED"},
                ) from exc
            data = derivative.png_bytes
            effective_sha256 = derivative.sha256
            masked_region_count = derivative.masked_region_count
            redaction_state = "masked"
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "ETag": f'"sha256-{effective_sha256}"',
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-AKC-Preview-Redaction": redaction_state,
            "X-AKC-Masked-Regions": str(masked_region_count),
        },
    )


@router.post("/pages/{page_id}/retry", response_model=JobResponse, status_code=202)
@router.post(
    "/pages/{page_id}/reprocess",
    response_model=JobResponse,
    status_code=202,
    deprecated=True,
)
@idempotent_mutation
async def retry_page(
    page_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: EditorDep,
    session: SessionDep,
) -> ProcessingJob:
    page = await session.scalar(
        select(Page)
        .where(
            Page.tenant_id == principal.tenant_id,
            Page.id == page_id,
        )
        .with_for_update()
    )
    if page is None:
        raise HTTPException(status_code=404, detail={"code": "PAGE_NOT_FOUND"})
    active_attempt = await session.scalar(
        select(PageAttempt)
        .where(
            PageAttempt.tenant_id == principal.tenant_id,
            PageAttempt.page_id == page.id,
            PageAttempt.status.not_in(tuple(state.value for state in TERMINAL_PAGE_STATES)),
        )
        .with_for_update()
    )
    if active_attempt is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PAGE_RETRY_IN_PROGRESS",
                "attempt_id": str(active_attempt.id),
                "attempt_number": active_attempt.attempt_number,
            },
        )
    persisted_retries = int(
        await session.scalar(
            select(func.count(PageAttempt.id)).where(
                PageAttempt.tenant_id == principal.tenant_id,
                PageAttempt.page_id == page.id,
                PageAttempt.trigger == "user_retry",
            )
        )
        or 0
    )
    retry_count = max(
        persisted_retries,
        int(page.quality_metrics.get("retry_count", 0)),
    )
    if retry_count >= 3:
        raise HTTPException(
            status_code=409,
            detail={"code": "PAGE_RETRY_BUDGET_EXHAUSTED"},
        )
    document = await _tenant_document(
        session,
        principal.tenant_id,
        page.document_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    reserve = Decimal("1.0")
    attempt_number = await next_attempt_number(
        session,
        tenant_id=principal.tenant_id,
        page_id=page.id,
    )
    retry_ordinal = retry_count + 1
    job = ProcessingJob(
        tenant_id=principal.tenant_id,
        project_id=document.project_id,
        document_id=document.id,
        job_type="page_retry",
        requested_options={
            "route_profile": page.preflight_metrics.get(
                "route_profile",
                "parse_balanced_v1",
            ),
            "page_ids": [str(page.id)],
            "retry_count": retry_ordinal,
            "external_processing_consent": False,
            "document_version": document.active_version,
            "document_version_id": f"{document.id}:v{document.active_version}",
            "requested_by": str(principal.user_id),
        },
        cost_estimate={
            "expected": str(reserve),
            "upper_bound": str(reserve),
            "reserved": str(reserve),
        },
        progress={
            "done": 0,
            "total": 1,
            "stage": "retry_scheduled",
            "attempt_number": attempt_number,
        },
    )
    session.add(job)
    await session.flush()
    requested_route = (
        page.route
        if page.route
        in {
            "paddle_vl",
            "paddle_fast",
            "hpd_fast",
            "unlimited_long",
            "mistral_fallback",
        }
        else "paddle_vl"
    )
    try:
        async with session.begin_nested():
            page_attempt = await create_page_attempt(
                session,
                tenant_id=principal.tenant_id,
                page_id=page.id,
                attempt_number=attempt_number,
                trigger="user_retry",
                initial_state=PageState.RETRY_SCHEDULED,
                route=requested_route,
                route_profile=str(job.requested_options["route_profile"]),
                route_policy_version=(page.route_policy_version or "router-2026-07-30.1"),
                max_attempts=3,
                job_id=job.id,
                reason="user_retry_requested",
                payload={"retry_ordinal": retry_ordinal},
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "PAGE_RETRY_IN_PROGRESS"},
        ) from exc
    job.progress = {
        **job.progress,
        "attempt_id": str(page_attempt.id),
    }
    job.requested_options = {
        **job.requested_options,
        "page_attempt_id": str(page_attempt.id),
        "page_attempt_number": page_attempt.attempt_number,
    }
    await credit_entry(
        session,
        tenant_id=principal.tenant_id,
        operation_key=f"page-attempt:{page_attempt.id}:reserve",
        entry_type="reserve",
        credits=reserve,
        job_id=job.id,
        metadata={
            "page_id": str(page.id),
            "page_attempt_id": str(page_attempt.id),
            "page_attempt_number": page_attempt.attempt_number,
        },
    )
    await emit_event(
        session,
        job=job,
        event_type="job.created.v1",
        payload={
            "status": "queued",
            "job_type": "page_retry",
            "page_attempt_id": str(page_attempt.id),
            "page_attempt_number": page_attempt.attempt_number,
        },
    )
    await emit_event(
        session,
        job=job,
        event_type="credit.reserved.v1",
        payload={"credits": str(reserve)},
    )
    await emit_event(
        session,
        job=job,
        event_type="page.retry.scheduled.v1",
        payload={
            "page_id": str(page.id),
            "status": "retry_scheduled",
            "attempt": retry_ordinal,
            "attempt_id": str(page_attempt.id),
            "attempt_number": page_attempt.attempt_number,
        },
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
                "document_version": document.active_version,
                "document_version_id": f"{document.id}:v{document.active_version}",
                "page_attempt_id": str(page_attempt.id),
                "page_attempt_number": page_attempt.attempt_number,
            },
        )
    )
    await session.commit()
    if request.app.state.settings.local_background_tasks:
        background_tasks.add_task(
            _execute_background_job,
            request.app,
            job.id,
            principal.tenant_id,
        )
    return job


@router.patch("/blocks/{block_id}", response_model=BlockResponse)
@idempotent_mutation
async def patch_block(
    block_id: uuid.UUID,
    payload: BlockPatch,
    response: Response,
    principal: EditorDep,
    session: SessionDep,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Block:
    block = await session.scalar(
        select(Block)
        .where(Block.tenant_id == principal.tenant_id, Block.id == block_id)
        .with_for_update()
    )
    if block is None:
        raise HTTPException(status_code=404, detail={"code": "BLOCK_NOT_FOUND"})
    await _tenant_document(
        session,
        principal.tenant_id,
        block.document_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    expected = f'"revision-{block.revision}"'
    if if_match != expected:
        raise HTTPException(
            status_code=412,
            detail={"code": "REVISION_CONFLICT", "expected": expected},
        )
    try:
        ensure_portable_markdown_safe(payload.markdown)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNSAFE_MARKDOWN"},
        ) from exc
    old_revision = block.revision
    old_markdown = block.markdown or ""
    block.markdown = payload.markdown
    block.user_locked = payload.user_locked
    block.origin = "user_edited"
    block.revision += 1
    block.content_hash = hashlib.sha256(payload.markdown.encode()).hexdigest()
    session.add(
        BlockRevision(
            tenant_id=principal.tenant_id,
            block_id=block.id,
            base_revision=old_revision,
            new_revision=block.revision,
            operation="replace_markdown",
            base_value=old_markdown,
            value=payload.markdown,
            actor_id=principal.user_id,
        )
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="block.updated",
        target_type="block",
        target_id=str(block.id),
        metadata={"revision": block.revision},
    )
    latest_job = await session.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.tenant_id == principal.tenant_id,
            ProcessingJob.document_id == block.document_id,
        )
        .order_by(ProcessingJob.created_at.desc())
    )
    if latest_job is not None:
        await emit_event(
            session,
            job=latest_job,
            event_type="page.markdown.updated.v1",
            payload={
                "page_id": str(block.page_id) if block.page_id else None,
                "block_id": str(block.id),
                "markdown": block.markdown,
                "revision": block.revision,
                "origin": block.origin,
            },
        )
    await session.commit()
    response.headers["ETag"] = f'"revision-{block.revision}"'
    return block


@router.post(
    "/blocks/{block_id}/model-merge",
    response_model=BlockModelMergeResponse,
)
@idempotent_mutation
async def merge_model_rerun(
    block_id: uuid.UUID,
    payload: BlockModelMergeRequest,
    response: Response,
    principal: EditorDep,
    session: SessionDep,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> BlockModelMergeResponse:
    """Preview or apply a base/user/new-model merge without overwriting locks."""

    block = await session.scalar(
        select(Block)
        .where(Block.tenant_id == principal.tenant_id, Block.id == block_id)
        .with_for_update()
    )
    if block is None:
        raise HTTPException(status_code=404, detail={"code": "BLOCK_NOT_FOUND"})
    await _tenant_document(
        session,
        principal.tenant_id,
        block.document_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    expected = f'"revision-{block.revision}"'
    if if_match != expected:
        raise HTTPException(
            status_code=412,
            detail={"code": "REVISION_CONFLICT", "expected": expected},
        )
    if payload.base_revision > block.revision:
        raise HTTPException(
            status_code=409,
            detail={"code": "BASE_REVISION_AHEAD_OF_CURRENT"},
        )
    try:
        ensure_portable_markdown_safe(payload.new_model_markdown)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNSAFE_MARKDOWN"},
        ) from exc

    user_value = block.markdown or ""
    if payload.base_revision == block.revision:
        base_value = user_value
    else:
        base_record = await session.scalar(
            select(BlockRevision)
            .where(
                BlockRevision.tenant_id == principal.tenant_id,
                BlockRevision.block_id == block.id,
                BlockRevision.base_revision == payload.base_revision,
                BlockRevision.new_revision <= block.revision,
            )
            .order_by(BlockRevision.new_revision, BlockRevision.id)
        )
        if base_record is None or base_record.base_value is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "BASE_REVISION_UNAVAILABLE",
                    "base_revision": payload.base_revision,
                },
            )
        base_value = base_record.base_value

    merge = three_way_merge(
        base=base_value,
        user=user_value,
        new_model=payload.new_model_markdown,
        user_locked=block.user_locked,
    )
    applied = False
    if (
        payload.apply_non_conflicting
        and merge.status != "conflict"
        and merge.merged is not None
        and merge.merged != user_value
    ):
        try:
            ensure_portable_markdown_safe(merge.merged)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "UNSAFE_MERGED_MARKDOWN"},
            ) from exc
        previous_revision = block.revision
        block.markdown = merge.merged
        block.origin = "model_merged" if merge.status == "auto_merged" else "model_rerun"
        block.engine_revision = payload.model_revision
        block.revision += 1
        block.content_hash = hashlib.sha256(merge.merged.encode()).hexdigest()
        session.add(
            BlockRevision(
                tenant_id=principal.tenant_id,
                block_id=block.id,
                base_revision=previous_revision,
                new_revision=block.revision,
                operation="model_rerun_merge",
                base_value=user_value,
                value=merge.merged,
                actor_id=principal.user_id,
            )
        )
        applied = True

    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action=("block.model_merge_applied" if applied else "block.model_merge_previewed"),
        target_type="block",
        target_id=str(block.id),
        metadata={
            "base_revision": payload.base_revision,
            "current_revision": block.revision,
            "status": merge.status,
            "conflict_count": merge.conflict_count,
            "applied": applied,
            "model_revision": payload.model_revision,
        },
    )
    if applied:
        latest_job = await session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.tenant_id == principal.tenant_id,
                ProcessingJob.document_id == block.document_id,
            )
            .order_by(ProcessingJob.created_at.desc())
        )
        if latest_job is not None:
            await emit_event(
                session,
                job=latest_job,
                event_type="page.markdown.updated.v1",
                payload={
                    "page_id": str(block.page_id) if block.page_id else None,
                    "block_id": str(block.id),
                    "markdown": block.markdown,
                    "revision": block.revision,
                    "origin": block.origin,
                    "merge_status": merge.status,
                },
            )
    await session.commit()
    etag = f'"revision-{block.revision}"'
    response.headers["ETag"] = etag
    return BlockModelMergeResponse(
        block_id=block.id,
        status=merge.status,
        base_revision=payload.base_revision,
        current_revision=block.revision,
        applied=applied,
        user_locked=block.user_locked,
        base=base_value,
        user=user_value,
        new_model=payload.new_model_markdown,
        merged=merge.merged,
        conflict_count=merge.conflict_count,
        etag=etag,
    )


@router.post("/review-items/{review_id}/resolve")
@idempotent_mutation
async def resolve_review(
    review_id: uuid.UUID,
    payload: ReviewResolve,
    principal: ReviewerDep,
    session: SessionDep,
) -> dict[str, Any]:
    review_scope = select(ReviewItem).where(
        ReviewItem.tenant_id == principal.tenant_id,
        ReviewItem.id == review_id,
    )
    review = await session.scalar(review_scope)
    if review is None:
        raise HTTPException(status_code=404, detail={"code": "REVIEW_NOT_FOUND"})
    await _tenant_document(
        session,
        principal.tenant_id,
        review.document_id,
        lock=True,
        principal=principal,
        capability="review",
    )
    # The first lookup establishes the document scope. Re-lock and refresh the
    # review after the document lock so a waiter cannot act on stale "open"
    # state from before another resolver committed.
    review = await session.scalar(
        review_scope.with_for_update().execution_options(populate_existing=True)
    )
    if review is None:
        raise HTTPException(status_code=404, detail={"code": "REVIEW_NOT_FOUND"})
    if review.status != "open":
        raise HTTPException(status_code=409, detail={"code": "REVIEW_ALREADY_RESOLVED"})
    replacement = payload.value
    target_block: Block | None = None
    if payload.action == "adopt_source":
        if review.block_id is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "REVIEW_SOURCE_BLOCK_REQUIRED"},
            )
        target_block = await session.scalar(
            select(Block)
            .where(
                Block.tenant_id == principal.tenant_id,
                Block.id == review.block_id,
            )
            .with_for_update()
        )
        if target_block is None:
            raise HTTPException(status_code=409, detail={"code": "REVIEW_BLOCK_MISSING"})
        replacement = target_block.source_text
        if not replacement:
            raise HTTPException(
                status_code=422,
                detail={"code": "REVIEW_SOURCE_TEXT_UNAVAILABLE"},
            )
    if payload.action == "replace" and not replacement:
        raise HTTPException(
            status_code=422,
            detail={"code": "REPLACEMENT_VALUE_REQUIRED"},
        )
    if payload.action in {"replace", "adopt_source"} and review.block_id is not None:
        assert replacement is not None
        try:
            ensure_portable_markdown_safe(replacement)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "UNSAFE_MARKDOWN"},
            ) from exc
    # FOR UPDATE is authoritative on PostgreSQL. The compare-and-set also
    # preserves exactly-once resolution on SQLite and other dialects where row
    # locking is unavailable or weakened.
    claimed_review_id = await session.scalar(
        update(ReviewItem)
        .where(
            ReviewItem.tenant_id == principal.tenant_id,
            ReviewItem.id == review.id,
            ReviewItem.status == "open",
        )
        .values(status="resolved")
        .returning(ReviewItem.id)
        .execution_options(synchronize_session=False)
    )
    if claimed_review_id is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "REVIEW_ALREADY_RESOLVED"},
        )
    if payload.action in {"replace", "adopt_source"} and review.block_id is not None:
        assert replacement is not None
        block = target_block or await session.scalar(
            select(Block)
            .where(
                Block.tenant_id == principal.tenant_id,
                Block.id == review.block_id,
            )
            .with_for_update()
        )
        if block is None:
            raise HTTPException(status_code=409, detail={"code": "REVIEW_BLOCK_MISSING"})
        previous_revision = block.revision
        previous_markdown = block.markdown or ""
        block.markdown = replacement
        block.normalized_text = replacement
        block.origin = "user_edited"
        block.user_locked = True
        block.revision += 1
        block.content_hash = hashlib.sha256(replacement.encode()).hexdigest()
        session.add(
            BlockRevision(
                tenant_id=principal.tenant_id,
                block_id=block.id,
                base_revision=previous_revision,
                new_revision=block.revision,
                operation=(
                    "resolve_review_adopt_source"
                    if payload.action == "adopt_source"
                    else "resolve_review_replace"
                ),
                base_value=previous_markdown,
                value=replacement,
                actor_id=principal.user_id,
            )
        )
    review.status = "resolved"
    review.resolution = payload.model_dump()
    review.resolved_by = principal.user_id
    review.resolved_at = utcnow()
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="review.resolved",
        target_type="review_item",
        target_id=str(review.id),
        metadata={
            "action": payload.action,
            "document_id": str(review.document_id),
            "page_id": str(review.page_id) if review.page_id is not None else None,
            "block_id": str(review.block_id) if review.block_id is not None else None,
        },
    )
    await session.commit()
    return {"id": review.id, "status": review.status, "resolution": review.resolution}


def _review_scope_preview(review: ReviewItem, rows: list[ReviewItem]) -> dict[str, Any]:
    review_ids = sorted(str(row.id) for row in rows)
    canonical = json.dumps(
        {
            "document_id": str(review.document_id),
            "category": review.category,
            "review_ids": review_ids,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "document_id": str(review.document_id),
        "category": review.category,
        "item_count": len(review_ids),
        "review_ids": review_ids,
        "preview_sha256": hashlib.sha256(canonical).hexdigest(),
        "allowed_actions": ["accept", "adopt_source", "reject"],
    }


@router.get("/review-items/{review_id}/scope-preview")
async def preview_review_rule_scope(
    review_id: uuid.UUID,
    principal: ReviewerDep,
    session: SessionDep,
) -> dict[str, Any]:
    review = await session.scalar(
        select(ReviewItem).where(
            ReviewItem.tenant_id == principal.tenant_id,
            ReviewItem.id == review_id,
        )
    )
    if review is None:
        raise HTTPException(status_code=404, detail={"code": "REVIEW_NOT_FOUND"})
    await _tenant_document(
        session,
        principal.tenant_id,
        review.document_id,
        principal=principal,
        capability="review",
    )
    rows = list(
        (
            await session.scalars(
                select(ReviewItem)
                .where(
                    ReviewItem.tenant_id == principal.tenant_id,
                    ReviewItem.document_id == review.document_id,
                    ReviewItem.category == review.category,
                    ReviewItem.status == "open",
                )
                .order_by(ReviewItem.id)
            )
        ).all()
    )
    return _review_scope_preview(review, rows)


@router.post("/review-items/{review_id}/apply-rule")
@idempotent_mutation
async def apply_review_rule(
    review_id: uuid.UUID,
    payload: ReviewRuleApply,
    principal: ReviewerDep,
    session: SessionDep,
) -> dict[str, Any]:
    review = await session.scalar(
        select(ReviewItem).where(
            ReviewItem.tenant_id == principal.tenant_id,
            ReviewItem.id == review_id,
        )
    )
    if review is None:
        raise HTTPException(status_code=404, detail={"code": "REVIEW_NOT_FOUND"})
    await _tenant_document(
        session,
        principal.tenant_id,
        review.document_id,
        lock=True,
        principal=principal,
        capability="review",
    )
    rows = list(
        (
            await session.scalars(
                select(ReviewItem)
                .where(
                    ReviewItem.tenant_id == principal.tenant_id,
                    ReviewItem.document_id == review.document_id,
                    ReviewItem.category == review.category,
                    ReviewItem.status == "open",
                )
                .order_by(ReviewItem.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    current_preview = _review_scope_preview(review, rows)
    if current_preview["preview_sha256"] != payload.preview_sha256:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REVIEW_SCOPE_CHANGED",
                "current_preview": current_preview,
            },
        )
    if not rows:
        raise HTTPException(status_code=409, detail={"code": "REVIEW_SCOPE_EMPTY"})

    blocks_by_id: dict[uuid.UUID, Block] = {}
    if payload.action == "adopt_source":
        block_ids = {row.block_id for row in rows if row.block_id is not None}
        if len(block_ids) != len(rows):
            raise HTTPException(
                status_code=422,
                detail={"code": "REVIEW_SCOPE_SOURCE_BLOCK_REQUIRED"},
            )
        blocks = list(
            (
                await session.scalars(
                    select(Block)
                    .where(
                        Block.tenant_id == principal.tenant_id,
                        Block.id.in_(block_ids),
                    )
                    .order_by(Block.id)
                    .with_for_update()
                )
            ).all()
        )
        blocks_by_id = {block.id: block for block in blocks}
        if len(blocks_by_id) != len(block_ids) or any(
            not blocks_by_id[block_id].source_text for block_id in block_ids
        ):
            raise HTTPException(
                status_code=422,
                detail={"code": "REVIEW_SCOPE_SOURCE_TEXT_UNAVAILABLE"},
            )
        try:
            for block_id in block_ids:
                ensure_portable_markdown_safe(blocks_by_id[block_id].source_text)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "UNSAFE_MARKDOWN"},
            ) from exc

    resolved_ids: list[str] = []
    for row in rows:
        claimed = await session.scalar(
            update(ReviewItem)
            .where(
                ReviewItem.tenant_id == principal.tenant_id,
                ReviewItem.id == row.id,
                ReviewItem.status == "open",
            )
            .values(status="resolved")
            .returning(ReviewItem.id)
            .execution_options(synchronize_session=False)
        )
        if claimed is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "REVIEW_SCOPE_CHANGED"},
            )
        if payload.action == "adopt_source":
            assert row.block_id is not None
            block = blocks_by_id[row.block_id]
            previous_revision = block.revision
            previous_markdown = block.markdown or ""
            block.markdown = block.source_text
            block.normalized_text = block.source_text
            block.origin = "user_edited"
            block.user_locked = True
            block.revision += 1
            block.content_hash = hashlib.sha256(block.source_text.encode()).hexdigest()
            session.add(
                BlockRevision(
                    tenant_id=principal.tenant_id,
                    block_id=block.id,
                    base_revision=previous_revision,
                    new_revision=block.revision,
                    operation="resolve_review_rule_adopt_source",
                    base_value=previous_markdown,
                    value=block.source_text,
                    actor_id=principal.user_id,
                )
            )
        row.status = "resolved"
        row.resolution = {
            "action": payload.action,
            "note": payload.note,
            "scope": "document_category",
            "preview_sha256": payload.preview_sha256,
        }
        row.resolved_by = principal.user_id
        row.resolved_at = utcnow()
        resolved_ids.append(str(row.id))
        await audit(
            session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action="review.rule_applied",
            target_type="review_item",
            target_id=str(row.id),
            metadata={
                "action": payload.action,
                "document_id": str(row.document_id),
                "category": row.category,
                "preview_sha256": payload.preview_sha256,
            },
        )
    await session.commit()
    return {
        "status": "resolved",
        "action": payload.action,
        "scope": "document_category",
        "affected_count": len(resolved_ids),
        "review_ids": resolved_ids,
        "preview_sha256": payload.preview_sha256,
    }


@router.post("/projects/{project_id}/exports", response_model=ExportResponse, status_code=201)
@idempotent_mutation
async def create_export(
    project_id: uuid.UUID,
    payload: ExportCreate,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
) -> Export:
    await _require_verified_for_operation(
        request,
        session,
        principal,
        control="export",
    )
    await _tenant_project(
        session,
        principal.tenant_id,
        project_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    if payload.document_id is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "DOCUMENT_ID_REQUIRED"},
        )
    document = await _tenant_document(
        session,
        principal.tenant_id,
        payload.document_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    if document.project_id != project_id:
        raise HTTPException(status_code=409, detail={"code": "DOCUMENT_PROJECT_MISMATCH"})
    if payload.export_type == "jsonld" and not await feature_enabled(
        session,
        tenant_id=principal.tenant_id,
        key=ONTOLOGY_EXPORT_FLAG,
        user_id=principal.user_id,
        document_type=document.document_type,
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "FEATURE_NOT_ENABLED",
                "feature": ONTOLOGY_EXPORT_FLAG,
            },
        )
    row = Export(
        tenant_id=principal.tenant_id,
        project_id=project_id,
        document_id=payload.document_id,
        export_type=payload.export_type,
        options=payload.options,
        created_by=principal.user_id,
        status="running",
    )
    session.add(row)
    await session.flush()
    try:
        bundle, digest = await build_export_bundle(
            session,
            row,
            object_store=request.app.state.object_store,
        )
    except ValueError as exc:
        row.status = "failed"
        await session.commit()
        raise HTTPException(
            status_code=422,
            detail={"code": "EXPORT_VALIDATION_FAILED"},
        ) from exc
    key = f"tenants/{principal.tenant_id}/projects/{project_id}/exports/{row.id}/package.zip"
    await request.app.state.object_store.put_export(key, bundle)
    row.storage_key = key
    row.sha256 = digest
    row.size_bytes = len(bundle)
    row.status = "completed"
    row.completed_at = utcnow()
    session.add(
        OutboxEvent(
            tenant_id=principal.tenant_id,
            aggregate_type="export",
            aggregate_id=row.id,
            event_type="export.completed.v1",
            payload={"export_id": str(row.id), "project_id": str(project_id)},
        )
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="export.completed",
        target_type="export",
        target_id=str(row.id),
        metadata={"sha256": digest},
    )
    await session.commit()
    return row


@router.post("/jobs/{job_id}/exports", status_code=201)
@idempotent_mutation
async def create_job_export(
    job_id: uuid.UUID,
    payload: JobExportCreate,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
) -> dict[str, Any]:
    await _require_verified_for_operation(
        request,
        session,
        principal,
        control="export",
    )
    job = await _tenant_job(
        session,
        principal.tenant_id,
        job_id,
        lock=True,
        principal=principal,
        capability="write",
    )
    document: Document | None = None
    if job.document_id is not None:
        document = await _tenant_document(
            session,
            principal.tenant_id,
            job.document_id,
            lock=True,
            principal=principal,
            capability="write",
        )
    if job.status != "completed" or job.document_id is None or document is None:
        raise HTTPException(status_code=409, detail={"code": "JOB_NOT_EXPORTABLE"})
    profiles = list(dict.fromkeys(payload.profiles))
    if "jsonld" in profiles and not await feature_enabled(
        session,
        tenant_id=principal.tenant_id,
        key=ONTOLOGY_EXPORT_FLAG,
        user_id=principal.user_id,
        document_type=document.document_type,
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "FEATURE_NOT_ENABLED",
                "feature": ONTOLOGY_EXPORT_FLAG,
            },
        )
    row = Export(
        tenant_id=principal.tenant_id,
        project_id=job.project_id,
        document_id=job.document_id,
        export_type="bundle" if len(profiles) > 1 else profiles[0],
        options={**payload.options, "profiles": profiles},
        created_by=principal.user_id,
        status="running",
    )
    session.add(row)
    await session.flush()
    await emit_event(
        session,
        job=job,
        event_type="export.started.v1",
        payload={"export_id": str(row.id), "profiles": profiles},
    )
    try:
        bundle, digest = await build_export_bundle(
            session,
            row,
            profiles=profiles,
            object_store=request.app.state.object_store,
        )
    except ValueError as exc:
        row.status = "failed"
        await session.commit()
        raise HTTPException(
            status_code=422,
            detail={"code": "EXPORT_VALIDATION_FAILED"},
        ) from exc
    key = f"tenants/{principal.tenant_id}/projects/{job.project_id}/exports/{row.id}/package.zip"
    await request.app.state.object_store.put_export(key, bundle)
    row.storage_key = key
    row.sha256 = digest
    row.size_bytes = len(bundle)
    row.status = "completed"
    row.completed_at = utcnow()
    await emit_event(
        session,
        job=job,
        event_type="export.completed.v1",
        payload={
            "export_id": str(row.id),
            "profiles": profiles,
            "sha256": digest,
            "size_bytes": len(bundle),
        },
    )
    session.add(
        OutboxEvent(
            tenant_id=principal.tenant_id,
            aggregate_type="export",
            aggregate_id=row.id,
            event_type="export.completed.v1",
            payload={
                "export_id": str(row.id),
                "job_id": str(job.id),
                "profiles": profiles,
            },
        )
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="export.completed",
        target_type="export",
        target_id=str(row.id),
        metadata={"sha256": digest, "profiles": profiles},
    )
    await session.commit()
    return {
        "export_id": str(row.id),
        "download_url": f"/v1/exports/{row.id}/download",
        "sha256": digest,
        "size_bytes": len(bundle),
    }


@router.get("/exports/{export_id}", response_model=ExportResponse)
async def get_export(export_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> Export:
    row = await session.scalar(
        select(Export)
        .join(
            Project,
            (Project.tenant_id == Export.tenant_id) & (Project.id == Export.project_id),
        )
        .outerjoin(
            Document,
            (Document.tenant_id == Export.tenant_id) & (Document.id == Export.document_id),
        )
        .where(
            Export.tenant_id == principal.tenant_id,
            Export.id == export_id,
            Project.deletion_requested_at.is_(None),
            project_access_predicate(principal, Project.id, "read"),
            or_(
                Export.document_id.is_(None),
                Document.deletion_requested_at.is_(None),
            ),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "EXPORT_NOT_FOUND"})
    return row


@router.post(
    "/exports/{export_id}/vault-merge-preview",
    response_model=VaultMergePreviewResponse,
)
async def preview_export_vault_merge(
    export_id: uuid.UUID,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
    existing_vault: Annotated[UploadFile, File()],
    policy: Annotated[MergePolicy, Form()] = MergePolicy.ERROR,
) -> VaultMergePreviewResponse:
    """Dry-run an exported Obsidian profile against an untrusted Vault ZIP."""

    row = await session.scalar(
        select(Export)
        .join(
            Project,
            (Project.tenant_id == Export.tenant_id) & (Project.id == Export.project_id),
        )
        .outerjoin(
            Document,
            (Document.tenant_id == Export.tenant_id) & (Document.id == Export.document_id),
        )
        .where(
            Export.tenant_id == principal.tenant_id,
            Export.id == export_id,
            Export.status == "completed",
            Export.storage_key.is_not(None),
            Project.deletion_requested_at.is_(None),
            project_access_predicate(principal, Project.id, "write"),
            or_(
                Export.document_id.is_(None),
                Document.deletion_requested_at.is_(None),
            ),
        )
    )
    if row is None or not row.storage_key or not row.sha256:
        raise HTTPException(status_code=404, detail={"code": "EXPORT_NOT_READY"})
    export_document_type = (
        await session.scalar(
            select(Document.document_type).where(
                Document.tenant_id == principal.tenant_id,
                Document.id == row.document_id,
                Document.deletion_requested_at.is_(None),
            )
        )
        if row.document_id is not None
        else None
    )
    if not await feature_enabled(
        session,
        tenant_id=principal.tenant_id,
        key=EXISTING_VAULT_MERGE_FLAG,
        user_id=principal.user_id,
        document_type=export_document_type,
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "FEATURE_NOT_ENABLED",
                "feature": EXISTING_VAULT_MERGE_FLAG,
            },
        )
    maximum = DEFAULT_VAULT_ZIP_LIMITS.max_archive_bytes
    try:
        existing_payload = await existing_vault.read(maximum + 1)
    finally:
        await existing_vault.close()
    if len(existing_payload) > maximum:
        raise HTTPException(
            status_code=413,
            detail={"code": "VAULT_ARCHIVE_TOO_LARGE"},
        )
    export_payload = await request.app.state.object_store.read_export(row.storage_key)
    if hashlib.sha256(export_payload).hexdigest() != row.sha256:
        raise HTTPException(status_code=500, detail={"code": "EXPORT_CHECKSUM_FAILED"})
    try:
        plan, summary = build_vault_merge_preview(
            existing_zip=existing_payload,
            export_zip=export_payload,
            policy=policy,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "VAULT_MERGE_PREVIEW_INVALID"},
        ) from exc
    response = VaultMergePreviewResponse.model_validate(
        {
            **summary,
            "conflicts": [
                conflict.model_dump(
                    mode="json",
                    by_alias=False,
                    exclude_none=True,
                )
                for conflict in plan.conflicts
            ],
            "broken_links": [
                broken.model_dump(
                    mode="json",
                    by_alias=False,
                    exclude_none=True,
                )
                for broken in plan.broken_links
            ],
        }
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="vault.merge_previewed",
        target_type="export",
        target_id=str(row.id),
        metadata={
            "policy": policy.value,
            "existing_file_count": response.existing_file_count,
            "incoming_file_count": response.incoming_file_count,
            "conflict_count": response.conflict_count,
            "unresolved_conflict_count": response.unresolved_conflict_count,
            "broken_link_count": response.broken_link_count,
            "safe_to_apply": response.safe_to_apply,
            "plan_sha256": response.plan_sha256,
        },
    )
    await session.commit()
    return response


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: uuid.UUID,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> Response:
    row = await session.scalar(
        select(Export)
        .join(
            Project,
            (Project.tenant_id == Export.tenant_id) & (Project.id == Export.project_id),
        )
        .outerjoin(
            Document,
            (Document.tenant_id == Export.tenant_id) & (Document.id == Export.document_id),
        )
        .where(
            Export.tenant_id == principal.tenant_id,
            Export.id == export_id,
            Project.deletion_requested_at.is_(None),
            project_access_predicate(principal, Project.id, "read"),
            or_(
                Export.document_id.is_(None),
                Document.deletion_requested_at.is_(None),
            ),
        )
    )
    if row is None or row.status != "completed" or not row.storage_key:
        raise HTTPException(status_code=404, detail={"code": "EXPORT_NOT_READY"})
    data = await request.app.state.object_store.read_export(row.storage_key)
    if hashlib.sha256(data).hexdigest() != row.sha256:
        raise HTTPException(status_code=500, detail={"code": "EXPORT_CHECKSUM_FAILED"})
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="export.downloaded",
        target_type="export",
        target_id=str(row.id),
    )
    await session.commit()
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="akc-export-{row.id}.zip"'},
    )


@router.get("/credits", response_model=CreditBalance)
async def credits(principal: PrincipalDep, session: SessionDep) -> CreditBalance:
    account = await session.get(CreditAccount, principal.tenant_id)
    if account is None:
        raise HTTPException(status_code=404, detail={"code": "CREDIT_ACCOUNT_NOT_FOUND"})
    balance = Decimal(account.balance)
    reserved = Decimal(account.reserved)
    return CreditBalance(balance=balance, reserved=reserved, available=balance - reserved)


@router.get("/settings")
async def get_workspace_settings(
    principal: PrincipalDep,
    session: SessionDep,
) -> dict[str, Any]:
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})
    analytics_enabled = await product_analytics_enabled(session, principal.tenant_id)
    member_rows = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.tenant_id == principal.tenant_id)
            .order_by(User.created_at)
        )
    ).all()
    return {
        "tenant_id": str(tenant.id),
        "workspace_name": tenant.name,
        "updated_at": tenant.updated_at,
        "private_mode": tenant.private_mode,
        "external_transfer_allowed": tenant.external_transfer_allowed,
        "training_opt_in": tenant.training_opt_in,
        "preview_pii_masking": tenant.preview_pii_masking,
        "data_retention_days": tenant.data_retention_days,
        "product_analytics_enabled": analytics_enabled,
        "can_manage_policy": not principal.roles.isdisjoint({"owner", "admin"}),
        "members": [
            {
                "id": str(user.id),
                "display_name": user.display_name,
                "email": user.email,
                "role": membership.role,
                "status": "active" if user.is_active else "disabled",
            }
            for membership, user in member_rows
        ],
    }


@router.patch("/settings")
@router.patch("/privacy")
@idempotent_mutation
async def patch_privacy(
    payload: PrivacyPatch, principal: AdminDep, session: SessionDep
) -> dict[str, Any]:
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})
    values = payload.model_dump(exclude_unset=True)
    analytics_value = values.pop("product_analytics_enabled", None)
    changed_fields = [*values]
    if analytics_value is not None:
        changed_fields.append("product_analytics_enabled")
    if values.get("private_mode") is True:
        values["external_transfer_allowed"] = False
    effective_private = values.get("private_mode", tenant.private_mode)
    if effective_private and values.get("external_transfer_allowed") is True:
        raise HTTPException(
            status_code=409, detail={"code": "PRIVATE_MODE_EXTERNAL_TRANSFER_DENIED"}
        )
    for key, value in values.items():
        setattr(tenant, key, value)
    if analytics_value is not None:
        await set_product_analytics_enabled(
            session,
            tenant_id=tenant.id,
            enabled=analytics_value,
        )
    await audit(
        session,
        tenant_id=tenant.id,
        actor_id=principal.user_id,
        action="privacy.updated",
        target_type="tenant",
        target_id=str(tenant.id),
        metadata={"fields": sorted(changed_fields)},
    )
    await session.commit()
    return {
        "private_mode": tenant.private_mode,
        "external_transfer_allowed": tenant.external_transfer_allowed,
        "training_opt_in": tenant.training_opt_in,
        "preview_pii_masking": tenant.preview_pii_masking,
        "data_retention_days": tenant.data_retention_days,
        "product_analytics_enabled": (
            analytics_value
            if analytics_value is not None
            else await product_analytics_enabled(session, tenant.id)
        ),
        "updated_at": tenant.updated_at,
    }


async def _purge_documents(
    *,
    documents: list[Document],
    target_type: str,
    target_id: uuid.UUID,
    request: Request,
    principal: Principal,
    session: AsyncSession,
) -> DeletionReceipt:
    requested_at = utcnow()
    document_ids = [document.id for document in documents]
    project_ids = {document.project_id for document in documents}
    keys: set[tuple[str, str]] = set()

    pages = list(
        (
            await session.scalars(
                select(Page).where(
                    Page.tenant_id == principal.tenant_id,
                    Page.document_id.in_(document_ids),
                )
            )
        ).all()
    )
    page_ids = [page.id for page in pages]
    for page in pages:
        if page.render_key:
            keys.add(("working", page.render_key))
        if page.thumbnail_key:
            keys.add(("derived", page.thumbnail_key))
    if page_ids:
        assets = list(
            (
                await session.scalars(
                    select(PageAsset).where(
                        PageAsset.tenant_id == principal.tenant_id,
                        PageAsset.page_id.in_(page_ids),
                    )
                )
            ).all()
        )
        for asset in assets:
            bucket = str(asset.metadata_json.get("bucket", "derived"))
            if bucket not in {"working", "derived"}:
                bucket = "derived"
            keys.add((bucket, asset.storage_key))

    versions = list(
        (
            await session.scalars(
                select(DocumentVersion).where(
                    DocumentVersion.tenant_id == principal.tenant_id,
                    DocumentVersion.document_id.in_(document_ids),
                )
            )
        ).all()
    )
    keys.update(
        ("derived", version.cir_object_key) for version in versions if version.cir_object_key
    )
    exports = list(
        (
            await session.scalars(
                select(Export).where(
                    Export.tenant_id == principal.tenant_id,
                    Export.document_id.in_(document_ids),
                )
            )
        ).all()
    )
    keys.update(
        ("exports", export.storage_key) for export in exports if export.storage_key is not None
    )

    source_ids = {
        document.source_file_id for document in documents if document.source_file_id is not None
    }
    purge_sources: list[SourceFile] = []
    if source_ids:
        sources = list(
            (
                await session.scalars(
                    select(SourceFile).where(
                        SourceFile.tenant_id == principal.tenant_id,
                        SourceFile.id.in_(source_ids),
                    )
                )
            ).all()
        )
        for source in sources:
            external_references = await session.scalar(
                select(func.count(Document.id)).where(
                    Document.tenant_id == principal.tenant_id,
                    Document.source_file_id == source.id,
                    Document.id.not_in(document_ids),
                )
            )
            if not external_references:
                purge_sources.append(source)
                keys.add(("source", source.storage_key))

    purge_upload_ids = {source.upload_id for source in purge_sources}
    uploads = list(
        (
            await session.scalars(
                select(UploadSession).where(
                    UploadSession.tenant_id == principal.tenant_id,
                    (
                        UploadSession.document_id.in_(document_ids)
                        | UploadSession.id.in_(purge_upload_ids)
                    ),
                )
            )
        ).all()
    )
    keys.update(("quarantine", upload.object_key) for upload in uploads)

    manifest = "\n".join(f"{bucket}:{key}" for bucket, key in sorted(keys))
    manifest_hash = hashlib.sha256(manifest.encode()).hexdigest()
    deleted = 0
    failures: list[str] = []
    for bucket, key in sorted(keys):
        try:
            deleted += int(await request.app.state.object_store.delete(bucket, key))
        except (OSError, KeyError, BotoCoreError, ClientError):
            failures.append(hashlib.sha256(f"{bucket}:{key}".encode()).hexdigest())
    if failures:
        for document in documents:
            document.status = "DELETE_REQUESTED"
        session.add(
            OutboxEvent(
                tenant_id=principal.tenant_id,
                aggregate_type=target_type,
                aggregate_id=target_id,
                event_type="deletion.retry.requested.v1",
                payload={
                    "target_type": target_type,
                    "target_id": str(target_id),
                    "manifest_hash": manifest_hash,
                    "failed_object_hashes": failures,
                },
            )
        )
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail={"code": "DELETION_INCOMPLETE", "manifest_hash": manifest_hash},
        )

    block_ids = {
        str(value)
        for value in (
            await session.scalars(
                select(Block.id).where(
                    Block.tenant_id == principal.tenant_id,
                    Block.document_id.in_(document_ids),
                )
            )
        ).all()
    }
    if project_ids:
        notes = list(
            (
                await session.scalars(
                    select(KnowledgeNote).where(
                        KnowledgeNote.tenant_id == principal.tenant_id,
                        KnowledgeNote.project_id.in_(project_ids),
                    )
                )
            ).all()
        )
        for note in notes:
            if target_type == "project" or block_ids.intersection(note.evidence_block_ids):
                await session.delete(note)

    jobs = list(
        (
            await session.scalars(
                select(ProcessingJob).where(
                    ProcessingJob.tenant_id == principal.tenant_id,
                    ProcessingJob.document_id.in_(document_ids),
                )
            )
        ).all()
    )
    aggregate_ids = {
        *document_ids,
        *(job.id for job in jobs),
        *(export.id for export in exports),
    }
    if aggregate_ids:
        outbox_rows = list(
            (
                await session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.tenant_id == principal.tenant_id,
                        OutboxEvent.aggregate_id.in_(aggregate_ids),
                    )
                )
            ).all()
        )
        for row in outbox_rows:
            await session.delete(row)

    for document in documents:
        await session.delete(document)
    await session.flush()
    for source in purge_sources:
        await session.delete(source)
    await session.flush()
    for upload in uploads:
        still_referenced = await session.scalar(
            select(func.count(SourceFile.id)).where(
                SourceFile.tenant_id == principal.tenant_id,
                SourceFile.upload_id == upload.id,
            )
        )
        if not still_referenced:
            await session.delete(upload)

    target_hash = hashlib.sha256(str(target_id).encode()).hexdigest()
    receipt = DeletionReceipt(
        tenant_id=principal.tenant_id,
        target_type=target_type,
        target_id_hash=target_hash,
        manifest_hash=manifest_hash,
        deleted_count=deleted,
        requested_at=requested_at,
    )
    session.add(receipt)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action=f"{target_type}.deleted",
        target_type=target_type,
        target_id=target_hash,
        metadata={
            "manifest_hash": manifest_hash,
            "deleted_objects": deleted,
        },
    )
    await session.commit()
    return receipt


def _deletion_status_response(
    deletion_request: DeletionRequest,
    receipt: DeletionReceipt | None = None,
) -> DeletionRequestResponse:
    return DeletionRequestResponse(
        id=deletion_request.id,
        target_type=cast(DeletionTargetType, deletion_request.target_type),
        state=cast(
            Literal["requested", "purging", "retry", "purged", "dead_letter"],
            deletion_request.state,
        ),
        manifest_hash=deletion_request.manifest_hash,
        object_count=deletion_request.object_count,
        deleted_count=deletion_request.deleted_count,
        requested_at=deletion_request.requested_at,
        completed_at=deletion_request.completed_at,
        status_url=f"/v1/deletions/{deletion_request.id}",
        receipt=(DeleteReceiptResponse.model_validate(receipt) if receipt is not None else None),
    )


async def _run_local_deletion(app: FastAPI, request_id: uuid.UUID) -> None:
    await process_deletion_request(
        app.state.database.sessions,
        object_store=app.state.object_store,
        request_id=request_id,
    )


async def _request_deletion(
    *,
    target_type: DeletionTargetType,
    target_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: Principal,
    session: AsyncSession,
) -> DeletionRequestResponse:
    if target_type == "project":
        await _tenant_project(
            session,
            principal.tenant_id,
            target_id,
            principal=principal,
            capability="write",
        )
    else:
        await _tenant_document(
            session,
            principal.tenant_id,
            target_id,
            principal=principal,
            capability="write",
        )
    try:
        deletion_request, _created = await create_deletion_request(
            session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            target_type=target_type,
            target_id=target_id,
        )
    except LookupError as exc:
        code = "PROJECT_NOT_FOUND" if target_type == "project" else "DOCUMENT_NOT_FOUND"
        raise HTTPException(status_code=404, detail={"code": code}) from exc

    receipt = await get_deletion_receipt(
        session,
        tenant_id=principal.tenant_id,
        request_id=deletion_request.id,
    )
    response = _deletion_status_response(deletion_request, receipt)
    await session.commit()
    if request.app.state.settings.local_background_tasks:
        background_tasks.add_task(
            _run_local_deletion,
            request.app,
            deletion_request.id,
        )
    return response


@router.get("/deletions/{request_id}", response_model=DeletionRequestResponse)
async def get_deletion_status(
    request_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> DeletionRequestResponse:
    deletion_request = await session.scalar(
        select(DeletionRequest).where(
            DeletionRequest.tenant_id == principal.tenant_id,
            DeletionRequest.id == request_id,
        )
    )
    if deletion_request is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "DELETION_NOT_FOUND"},
        )
    if deletion_request.requested_by != principal.user_id:
        if deletion_request.target_type == "project":
            await require_project_access(
                session,
                principal=principal,
                project_id=deletion_request.target_id,
                capability="read",
            )
        else:
            deleted_document = await session.scalar(
                select(Document).where(
                    Document.tenant_id == principal.tenant_id,
                    Document.id == deletion_request.target_id,
                )
            )
            if deleted_document is None:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "DELETION_NOT_FOUND"},
                )
            await require_project_access(
                session,
                principal=principal,
                project_id=deleted_document.project_id,
                capability="read",
            )
    receipt = await get_deletion_receipt(
        session,
        tenant_id=principal.tenant_id,
        request_id=deletion_request.id,
    )
    return _deletion_status_response(deletion_request, receipt)


@router.delete(
    "/documents/{document_id}",
    response_model=DeletionRequestResponse,
    status_code=202,
)
@idempotent_mutation
async def delete_document(
    document_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: EditorDep,
    session: SessionDep,
) -> DeletionRequestResponse:
    return await _request_deletion(
        target_type="document",
        target_id=document_id,
        request=request,
        background_tasks=background_tasks,
        principal=principal,
        session=session,
    )


@router.delete(
    "/projects/{project_id}",
    response_model=DeletionRequestResponse,
    status_code=202,
)
@idempotent_mutation
async def delete_project(
    project_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: AdminDep,
    session: SessionDep,
) -> DeletionRequestResponse:
    return await _request_deletion(
        target_type="project",
        target_id=project_id,
        request=request,
        background_tasks=background_tasks,
        principal=principal,
        session=session,
    )


@router.get("/dashboard")
async def dashboard(principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
    project_rows = list(
        (
            await session.scalars(
                select(Project)
                .where(
                    Project.tenant_id == principal.tenant_id,
                    Project.deletion_requested_at.is_(None),
                    project_access_predicate(principal, Project.id, "read"),
                )
                .order_by(Project.updated_at.desc())
            )
        ).all()
    )
    active_document = (Document.tenant_id == Page.tenant_id) & (Document.id == Page.document_id)
    pages = list(
        (
            await session.scalars(
                select(Page)
                .join(Document, active_document)
                .join(
                    Project,
                    (Project.tenant_id == Document.tenant_id) & (Project.id == Document.project_id),
                )
                .where(
                    Page.tenant_id == principal.tenant_id,
                    Document.deletion_requested_at.is_(None),
                    Project.deletion_requested_at.is_(None),
                    project_access_predicate(principal, Project.id, "read"),
                )
            )
        ).all()
    )
    blocks_total = await session.scalar(
        select(func.count(Block.id))
        .join(
            Document,
            (Document.tenant_id == Block.tenant_id) & (Document.id == Block.document_id),
        )
        .join(
            Project,
            (Project.tenant_id == Document.tenant_id) & (Project.id == Document.project_id),
        )
        .where(
            Block.tenant_id == principal.tenant_id,
            Document.deletion_requested_at.is_(None),
            Project.deletion_requested_at.is_(None),
            project_access_predicate(principal, Project.id, "read"),
        )
    )
    blocks_with_source = await session.scalar(
        select(func.count(Block.id))
        .join(
            Document,
            (Document.tenant_id == Block.tenant_id) & (Document.id == Block.document_id),
        )
        .join(
            Project,
            (Project.tenant_id == Document.tenant_id) & (Project.id == Document.project_id),
        )
        .where(
            Block.tenant_id == principal.tenant_id,
            Block.source_text.is_not(None),
            Document.deletion_requested_at.is_(None),
            Project.deletion_requested_at.is_(None),
            project_access_predicate(principal, Project.id, "read"),
        )
    )
    coverage = float(blocks_with_source or 0) / float(blocks_total) if blocks_total else None
    summaries = []
    for project in project_rows:
        doc_count = await session.scalar(
            select(func.count(Document.id)).where(
                Document.tenant_id == principal.tenant_id,
                Document.project_id == project.id,
                Document.deletion_requested_at.is_(None),
            )
        )
        review_count = await session.scalar(
            select(func.count(ReviewItem.id)).where(
                ReviewItem.tenant_id == principal.tenant_id,
                ReviewItem.project_id == project.id,
                ReviewItem.status == "open",
            )
        )
        processing_count = await session.scalar(
            select(func.count(ProcessingJob.id)).where(
                ProcessingJob.tenant_id == principal.tenant_id,
                ProcessingJob.project_id == project.id,
                ProcessingJob.status.in_(("queued", "running", "waiting_review")),
            )
        )
        ready_count = await session.scalar(
            select(func.count(Document.id)).where(
                Document.tenant_id == principal.tenant_id,
                Document.project_id == project.id,
                Document.status == "COMPLETED",
                Document.deletion_requested_at.is_(None),
            )
        )
        project_status = (
            "attention"
            if review_count
            else "processing"
            if processing_count
            else "ready"
            if doc_count and ready_count == doc_count
            else "draft"
        )
        summaries.append(
            {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "document_count": doc_count or 0,
                "review_count": review_count or 0,
                "status": project_status,
                "updated_at": project.updated_at,
            }
        )
    return {
        "active_project_count": len(project_rows),
        "processed_pages": len(pages),
        "native_pages": sum(page.route == "native" for page in pages),
        "visual_pages": sum(page.route not in {None, "native"} for page in pages),
        "provenance_coverage": coverage,
        "external_pages": sum((page.route or "").startswith("external") for page in pages),
        "projects": summaries,
    }


@router.get("/analytics", response_model=ProductAnalyticsSnapshot)
async def analytics(
    principal: PrincipalDep,
    session: SessionDep,
    window: Literal["7d", "30d", "90d"] = Query(default="30d"),
) -> ProductAnalyticsSnapshot:
    try:
        snapshot = await build_product_analytics_snapshot(
            session,
            tenant_id=principal.tenant_id,
            window_key=window,
            principal=principal,
        )
    except Exception:
        record_product_analytics_snapshot("failed")
        raise
    record_product_analytics_snapshot("enabled" if snapshot.privacy.enabled else "disabled")
    return snapshot


@router.get("/feature-flags")
async def feature_flags(principal: PrincipalDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(FeatureFlag).where(
                    (FeatureFlag.tenant_id == principal.tenant_id)
                    | (FeatureFlag.tenant_id.is_(None))
                )
            )
        ).all()
    )
    return [
        {
            "key": row.key,
            "enabled": row.enabled,
            "rollout_percent": row.rollout_percent,
            "conditions": row.conditions,
        }
        for row in rows
    ]


@router.post(
    "/webhooks",
    response_model=WebhookCreated,
    status_code=201,
)
@idempotent_mutation
async def create_webhook(
    payload: WebhookCreate,
    request: Request,
    principal: AdminDep,
    session: SessionDep,
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    if (
        not settings.webhook_delivery_enabled
        or not settings.webhook_encryption_key
        or not settings.allowed_webhook_hosts
    ):
        raise HTTPException(
            status_code=503,
            detail={"code": "WEBHOOK_DELIVERY_NOT_CONFIGURED"},
        )
    try:
        target = await validate_webhook_url(
            payload.url,
            allowed_hosts=settings.allowed_webhook_hosts,
        )
    except WebhookDnsError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "WEBHOOK_DNS_UNAVAILABLE"},
        ) from exc
    except WebhookTargetError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNSAFE_WEBHOOK_TARGET"},
        ) from exc
    secret = generate_webhook_secret()
    row = WebhookEndpoint(
        tenant_id=principal.tenant_id,
        url=target.normalized_url,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        encrypted_secret=encrypt_secret(
            secret,
            settings.webhook_encryption_key,
        ),
        event_types=list(dict.fromkeys(payload.event_types)),
        active=True,
        created_by=principal.user_id,
    )
    await session.scalar(select(Tenant).where(Tenant.id == principal.tenant_id).with_for_update())
    endpoint_count = int(
        await session.scalar(
            select(func.count())
            .select_from(WebhookEndpoint)
            .where(WebhookEndpoint.tenant_id == principal.tenant_id)
        )
        or 0
    )
    if endpoint_count >= settings.webhook_max_endpoints_per_tenant:
        raise HTTPException(
            status_code=409,
            detail={"code": "WEBHOOK_ENDPOINT_QUOTA_EXCEEDED"},
        )
    session.add(row)
    await session.flush()
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="webhook.created",
        target_type="webhook",
        target_id=str(row.id),
        metadata={"event_types": row.event_types},
    )
    await session.commit()
    return {
        "id": row.id,
        "url": row.url,
        "event_types": row.event_types,
        "active": row.active,
        "created_at": row.created_at,
        "signing_secret": secret,
    }


@router.get("/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(
    principal: AdminDep,
    session: SessionDep,
) -> list[WebhookEndpoint]:
    return list(
        (
            await session.scalars(
                select(WebhookEndpoint)
                .where(WebhookEndpoint.tenant_id == principal.tenant_id)
                .order_by(WebhookEndpoint.created_at.desc())
            )
        ).all()
    )


@router.patch("/webhooks/{webhook_id}", response_model=WebhookResponse)
@idempotent_mutation
async def patch_webhook(
    webhook_id: uuid.UUID,
    payload: WebhookPatch,
    principal: AdminDep,
    session: SessionDep,
) -> WebhookEndpoint:
    row = await session.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.tenant_id == principal.tenant_id,
            WebhookEndpoint.id == webhook_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "WEBHOOK_NOT_FOUND"})
    values = payload.model_dump(exclude_unset=True)
    if "event_types" in values:
        values["event_types"] = list(dict.fromkeys(values["event_types"]))
    for key, value in values.items():
        setattr(row, key, value)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="webhook.updated",
        target_type="webhook",
        target_id=str(row.id),
        metadata={"fields": sorted(values)},
    )
    await session.commit()
    return row


@router.delete("/webhooks/{webhook_id}", status_code=204)
@idempotent_mutation
async def delete_webhook(
    webhook_id: uuid.UUID,
    principal: AdminDep,
    session: SessionDep,
) -> None:
    row = await session.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.tenant_id == principal.tenant_id,
            WebhookEndpoint.id == webhook_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "WEBHOOK_NOT_FOUND"})
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="webhook.deleted",
        target_type="webhook",
        target_id=str(row.id),
    )
    await session.delete(row)
    await session.commit()


@router.get("/webhooks/{webhook_id}/deliveries")
async def webhook_deliveries(
    webhook_id: uuid.UUID,
    principal: AdminDep,
    session: SessionDep,
) -> list[dict[str, Any]]:
    endpoint = await session.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.tenant_id == principal.tenant_id,
            WebhookEndpoint.id == webhook_id,
        )
    )
    if endpoint is None:
        raise HTTPException(status_code=404, detail={"code": "WEBHOOK_NOT_FOUND"})
    rows = list(
        (
            await session.scalars(
                select(WebhookDelivery)
                .where(
                    WebhookDelivery.tenant_id == principal.tenant_id,
                    WebhookDelivery.endpoint_id == endpoint.id,
                )
                .order_by(WebhookDelivery.next_attempt_at.desc())
                .limit(200)
            )
        ).all()
    )
    return [
        {
            "id": str(row.id),
            "event_type": row.event_type,
            "status": row.status,
            "attempts": row.attempts,
            "last_status_code": row.last_status_code,
            "last_error": row.last_error,
            "next_attempt_at": row.next_attempt_at,
            "delivered_at": row.delivered_at,
        }
        for row in rows
    ]


@router.post("/webhooks/{webhook_id}/deliveries/{delivery_id}/replay")
@idempotent_mutation
async def replay_webhook_delivery(
    webhook_id: uuid.UUID,
    delivery_id: uuid.UUID,
    principal: AdminDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Requeue one terminal delivery without changing its idempotency identity."""

    delivery = await session.scalar(
        select(WebhookDelivery)
        .where(
            WebhookDelivery.tenant_id == principal.tenant_id,
            WebhookDelivery.endpoint_id == webhook_id,
            WebhookDelivery.id == delivery_id,
        )
        .with_for_update()
    )
    if delivery is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "WEBHOOK_DELIVERY_NOT_FOUND"},
        )
    if delivery.status != "dead_letter":
        raise HTTPException(
            status_code=409,
            detail={"code": "WEBHOOK_DELIVERY_NOT_DEAD_LETTER"},
        )
    delivery.status = "pending"
    delivery.attempts = 0
    delivery.next_attempt_at = utcnow()
    delivery.last_status_code = None
    delivery.last_error = None
    delivery.delivered_at = None
    if hasattr(delivery, "dead_lettered_at"):
        delivery.dead_lettered_at = None
    if hasattr(delivery, "updated_at"):
        delivery.updated_at = utcnow()
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="webhook.delivery_replayed",
        target_type="webhook_delivery",
        target_id=str(delivery.id),
        metadata={"webhook_id": str(webhook_id)},
    )
    await session.commit()
    return {
        "id": str(delivery.id),
        "status": delivery.status,
        "attempts": delivery.attempts,
        "next_attempt_at": delivery.next_attempt_at,
    }


@router.get("/admin/models")
async def model_registry(principal: AdminDep, session: SessionDep) -> list[dict[str, Any]]:
    del principal
    rows = list(
        (
            await session.scalars(
                select(ModelRegistry).order_by(
                    ModelRegistry.endpoint,
                    ModelRegistry.created_at.desc(),
                    ModelRegistry.id.desc(),
                )
            )
        ).all()
    )
    return [
        {
            "id": str(row.id),
            "endpoint": row.endpoint,
            "model_id": row.model_id,
            "revision": row.revision,
            "runtime_image_digest": row.runtime_image_digest,
            "adapter_version": row.adapter_version,
            "policy_version": row.policy_version,
            "enabled": row.enabled,
            "canary_percent": row.canary_percent,
            "lifecycle_state": row.lifecycle_state,
            "generation": row.generation,
            "promoted_from_id": (str(row.promoted_from_id) if row.promoted_from_id else None),
            "benchmark_sha256": row.benchmark_sha256,
            "recipe_sha256": row.recipe_sha256,
            "approval_ref": row.approval_ref,
            "retired_at": row.retired_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


def _model_lifecycle_payload(row: ModelRegistry) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "endpoint": row.endpoint,
        "model_id": row.model_id,
        "revision": row.revision,
        "lifecycle_state": row.lifecycle_state,
        "generation": row.generation,
        "enabled": row.enabled,
        "canary_percent": row.canary_percent,
        "promoted_from_id": (str(row.promoted_from_id) if row.promoted_from_id else None),
        "benchmark_sha256": row.benchmark_sha256,
        "recipe_sha256": row.recipe_sha256,
        "approval_ref": row.approval_ref,
        "retired_at": row.retired_at,
        "updated_at": row.updated_at,
    }


def _model_generation_conflict(row: ModelRegistry) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "MODEL_GENERATION_CONFLICT",
            "current_generation": row.generation,
        },
    )


@router.post("/admin/models/{model_id}/promote")
async def promote_model(
    model_id: uuid.UUID,
    payload: ModelPromotionRequest,
    principal: AdminDep,
    session: SessionDep,
) -> dict[str, Any]:
    target = await session.scalar(
        select(ModelRegistry).where(ModelRegistry.id == model_id).with_for_update()
    )
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "MODEL_NOT_FOUND"})
    if target.generation != payload.expected_generation:
        raise _model_generation_conflict(target)
    if target.lifecycle_state == "retired":
        raise HTTPException(
            status_code=409,
            detail={"code": "MODEL_RETIRED"},
        )
    try:
        binding = validate_registry_binding(target)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "MODEL_RECIPE_INVALID", "message": str(exc)},
        ) from exc

    champions = list(
        (
            await session.scalars(
                select(ModelRegistry)
                .where(
                    ModelRegistry.endpoint == target.endpoint,
                    ModelRegistry.lifecycle_state == "champion",
                    ModelRegistry.id != target.id,
                )
                .with_for_update()
            )
        ).all()
    )
    previous = champions[0] if champions else None
    now = utcnow()
    for champion in champions:
        champion.lifecycle_state = "fallback"
        champion.enabled = True
        champion.canary_percent = 100
        champion.generation += 1
        champion.updated_at = now

    target.lifecycle_state = "champion"
    target.enabled = True
    target.canary_percent = 100
    target.promoted_from_id = previous.id if previous is not None else None
    target.benchmark_sha256 = payload.benchmark_sha256
    target.recipe_sha256 = payload.recipe_sha256
    target.approval_ref = payload.approval_ref
    target.retired_at = None
    target.generation += 1
    target.updated_at = now
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="model.promoted",
        target_type="model_registry",
        target_id=str(target.id),
        metadata={
            "endpoint": target.endpoint,
            "route": binding.route.value,
            "previous_champion_id": str(previous.id) if previous else None,
            "approval_ref": payload.approval_ref,
            "benchmark_sha256": payload.benchmark_sha256,
            "recipe_sha256": payload.recipe_sha256,
            "reason": payload.reason,
        },
    )
    await session.commit()
    return _model_lifecycle_payload(target)


@router.post("/admin/models/{model_id}/rollback")
async def rollback_model(
    model_id: uuid.UUID,
    payload: ModelRollbackRequest,
    principal: AdminDep,
    session: SessionDep,
) -> dict[str, Any]:
    champion = await session.scalar(
        select(ModelRegistry).where(ModelRegistry.id == model_id).with_for_update()
    )
    if champion is None:
        raise HTTPException(status_code=404, detail={"code": "MODEL_NOT_FOUND"})
    if champion.generation != payload.expected_generation:
        raise _model_generation_conflict(champion)
    if champion.lifecycle_state != "champion" or champion.promoted_from_id is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "MODEL_ROLLBACK_UNAVAILABLE"},
        )
    previous = await session.scalar(
        select(ModelRegistry).where(ModelRegistry.id == champion.promoted_from_id).with_for_update()
    )
    if (
        previous is None
        or previous.endpoint != champion.endpoint
        or previous.lifecycle_state == "retired"
        or not previous.benchmark_sha256
        or not previous.recipe_sha256
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "MODEL_ROLLBACK_TARGET_INVALID"},
        )
    try:
        binding = validate_registry_binding(previous)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "MODEL_ROLLBACK_TARGET_INVALID", "message": str(exc)},
        ) from exc

    now = utcnow()
    champion.lifecycle_state = "fallback"
    champion.generation += 1
    champion.updated_at = now
    previous.lifecycle_state = "champion"
    previous.enabled = True
    previous.canary_percent = 100
    previous.promoted_from_id = champion.id
    previous.approval_ref = payload.approval_ref
    previous.generation += 1
    previous.updated_at = now
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="model.rolled_back",
        target_type="model_registry",
        target_id=str(champion.id),
        metadata={
            "endpoint": champion.endpoint,
            "restored_model_id": str(previous.id),
            "route": binding.route.value,
            "approval_ref": payload.approval_ref,
            "reason": payload.reason,
        },
    )
    await session.commit()
    return {
        "rolled_back": _model_lifecycle_payload(champion),
        "restored": _model_lifecycle_payload(previous),
    }


@router.post("/admin/models/{model_id}/retire")
async def retire_model(
    model_id: uuid.UUID,
    payload: ModelRetireRequest,
    principal: AdminDep,
    session: SessionDep,
) -> dict[str, Any]:
    target = await session.scalar(
        select(ModelRegistry).where(ModelRegistry.id == model_id).with_for_update()
    )
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "MODEL_NOT_FOUND"})
    if target.generation != payload.expected_generation:
        raise _model_generation_conflict(target)
    if target.lifecycle_state == "champion":
        raise HTTPException(
            status_code=409,
            detail={"code": "MODEL_CHAMPION_REQUIRES_REPLACEMENT"},
        )
    rollback_reference = await session.scalar(
        select(ModelRegistry.id)
        .where(
            ModelRegistry.lifecycle_state == "champion",
            ModelRegistry.promoted_from_id == target.id,
        )
        .limit(1)
    )
    if rollback_reference is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "MODEL_REQUIRED_FOR_ROLLBACK"},
        )
    now = utcnow()
    target.lifecycle_state = "retired"
    target.enabled = False
    target.canary_percent = 0
    target.approval_ref = payload.approval_ref
    target.retired_at = now
    target.generation += 1
    target.updated_at = now
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="model.retired",
        target_type="model_registry",
        target_id=str(target.id),
        metadata={
            "endpoint": target.endpoint,
            "approval_ref": payload.approval_ref,
            "reason": payload.reason,
        },
    )
    await session.commit()
    return _model_lifecycle_payload(target)


@router.get("/admin/health")
async def admin_health(
    request: Request,
    principal: AdminDep,
    session: SessionDep,
) -> dict[str, Any]:
    queued_rows = list(
        (
            await session.scalars(
                select(ProcessingJob)
                .where(
                    ProcessingJob.tenant_id == principal.tenant_id,
                    ProcessingJob.status == "queued",
                )
                .order_by(ProcessingJob.created_at)
            )
        ).all()
    )
    running = await session.scalar(
        select(func.count(ProcessingJob.id)).where(
            ProcessingJob.tenant_id == principal.tenant_id,
            ProcessingJob.status == "running",
        )
    )
    failed_rows = list(
        (
            await session.scalars(
                select(ProcessingJob)
                .where(
                    ProcessingJob.tenant_id == principal.tenant_id,
                    ProcessingJob.status == "failed",
                )
                .order_by(ProcessingJob.completed_at.desc())
                .limit(50)
            )
        ).all()
    )
    completed = await session.scalar(
        select(func.count(ProcessingJob.id)).where(
            ProcessingJob.tenant_id == principal.tenant_id,
            ProcessingJob.status == "completed",
        )
    )
    cancelled = await session.scalar(
        select(func.count(ProcessingJob.id)).where(
            ProcessingJob.tenant_id == principal.tenant_id,
            ProcessingJob.status == "cancelled",
        )
    )
    dead_letters = await session.scalar(
        select(func.count(WebhookDelivery.id)).where(
            WebhookDelivery.tenant_id == principal.tenant_id,
            WebhookDelivery.status == "dead_letter",
        )
    )
    terminal = (completed or 0) + len(failed_rows) + (cancelled or 0)
    oldest_age = (
        max(
            0.0,
            (utcnow() - _aware(queued_rows[0].created_at)).total_seconds(),
        )
        if queued_rows
        else 0.0
    )
    settings: Settings = request.app.state.settings
    antivirus_state = (
        "ok"
        if settings.clamav_enabled
        else "development_only"
        if settings.env in {"development", "test"} and settings.allow_development_antivirus_bypass
        else "blocked"
    )
    status_value = (
        "degraded" if failed_rows or dead_letters or antivirus_state == "blocked" else "ok"
    )
    return {
        "status": status_value,
        "generated_at": utcnow(),
        "oldest_queue_age_seconds": oldest_age,
        "queued_jobs": len(queued_rows),
        "running_jobs": running or 0,
        "dlq_count": dead_letters or 0,
        "terminal_success_rate": ((completed or 0) / terminal if terminal else None),
        "dependencies": {
            "database": {"status": "ok", "detail": "query verified"},
            "object_store": {
                "status": "configured",
                "detail": settings.object_store_driver,
            },
            "antivirus": {"status": antivirus_state},
            "scheduler": {
                "status": (
                    "embedded-development"
                    if settings.local_background_tasks
                    else "durable-required"
                )
            },
        },
        "interventions": [
            {
                "job_id": str(job.id),
                "error_code": (job.error or {}).get("code"),
                "route_history": [str(job.requested_options.get("route_profile", "unknown"))],
                "attempts": int(job.requested_options.get("retry_count", 0)),
                "max_attempts": 1,
                "retryable": int(job.requested_options.get("retry_count", 0)) < 1,
                "action_url": f"/v1/admin/jobs/{job.id}/retry",
            }
            for job in failed_rows
        ],
    }


@router.get("/admin/dispatch-dlq")
async def list_dispatch_dead_letters(
    principal: AdminDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.tenant_id == principal.tenant_id,
                    OutboxEvent.event_type == "job.dispatch.requested.v1",
                    OutboxEvent.dead_lettered_at.is_not(None),
                )
                .order_by(
                    OutboxEvent.dead_lettered_at.desc(),
                    OutboxEvent.id.desc(),
                )
                .limit(limit)
            )
        ).all()
    )
    return [
        {
            "original_event_id": row.id,
            "original_job_id": row.aggregate_id,
            "attempts": row.attempts,
            "last_error": row.last_error,
            "dead_lettered_at": row.dead_lettered_at,
            "disposition": row.payload.get("operator_disposition"),
            "state_sha256": _dispatch_dlq_state_sha256(row),
        }
        for row in rows
    ]


def _dispatch_dlq_state_sha256(row: OutboxEvent) -> str:
    canonical = json.dumps(
        {
            "id": str(row.id),
            "aggregate_id": str(row.aggregate_id),
            "attempts": row.attempts,
            "dead_lettered_at": (
                _aware(row.dead_lettered_at).isoformat() if row.dead_lettered_at else None
            ),
            "last_error": row.last_error,
            "payload": row.payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


async def _locked_dispatch_dead_letter(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
) -> tuple[OutboxEvent, ProcessingJob]:
    event = await session.scalar(
        select(OutboxEvent)
        .where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.id == event_id,
            OutboxEvent.event_type == "job.dispatch.requested.v1",
            OutboxEvent.dead_lettered_at.is_not(None),
        )
        .with_for_update()
    )
    if event is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "DISPATCH_DEAD_LETTER_NOT_FOUND"},
        )
    if event.payload.get("operator_disposition") or event.payload.get("replayed_by_event_id"):
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_DEAD_LETTER_ALREADY_DISPOSED"},
        )
    try:
        payload_job_id = uuid.UUID(str(event.payload["job_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_DEAD_LETTER_PAYLOAD_INVALID"},
        ) from exc
    if event.aggregate_type != "job" or payload_job_id != event.aggregate_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_DEAD_LETTER_PAYLOAD_INVALID"},
        )
    job = await session.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.tenant_id == tenant_id,
            ProcessingJob.id == event.aggregate_id,
        )
        .with_for_update()
    )
    if job is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_ORIGINAL_JOB_MISSING"},
        )
    if job.status != "failed":
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_ORIGINAL_JOB_NOT_TERMINAL"},
        )
    return event, job


@router.post("/admin/dispatch-dlq/{event_id}/close")
@idempotent_mutation
async def close_dispatch_dead_letter(
    event_id: uuid.UUID,
    payload: DispatchDlqClose,
    principal: AdminDep,
    session: SessionDep,
) -> dict[str, Any]:
    event, job = await _locked_dispatch_dead_letter(
        session,
        tenant_id=principal.tenant_id,
        event_id=event_id,
    )
    actual_state = _dispatch_dlq_state_sha256(event)
    if actual_state != payload.expected_state_sha256:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DISPATCH_DEAD_LETTER_STATE_CHANGED",
                "state_sha256": actual_state,
            },
        )
    disposed_at = utcnow()
    event.payload = {
        **event.payload,
        "operator_disposition": "closed",
        "disposition_reason_code": payload.reason_code,
        "disposed_at": disposed_at.isoformat(),
    }
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="dispatch_dlq.closed",
        target_type="outbox_event",
        target_id=str(event.id),
        metadata={
            "job_id": str(job.id),
            "reason_code": payload.reason_code,
            "note": payload.note,
            "previous_state_sha256": actual_state,
        },
    )
    await session.commit()
    return {
        "event_id": event.id,
        "job_id": job.id,
        "disposition": "closed",
        "reason_code": payload.reason_code,
    }


@router.post("/admin/dispatch-dlq/{event_id}/fallback", status_code=202)
@idempotent_mutation
async def fallback_dispatch_dead_letter(
    event_id: uuid.UUID,
    payload: DispatchDlqFallback,
    principal: AdminDep,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(
            status_code=400,
            detail={"code": "IDEMPOTENCY_KEY_REQUIRED"},
        )
    event, job = await _locked_dispatch_dead_letter(
        session,
        tenant_id=principal.tenant_id,
        event_id=event_id,
    )
    actual_state = _dispatch_dlq_state_sha256(event)
    if actual_state != payload.expected_state_sha256:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DISPATCH_DEAD_LETTER_STATE_CHANGED",
                "state_sha256": actual_state,
            },
        )
    current_route = str(job.requested_options.get("route_profile", "parse_balanced_v1"))
    if payload.fallback_route_profile == current_route:
        raise HTTPException(
            status_code=422,
            detail={"code": "DISPATCH_FALLBACK_ROUTE_UNCHANGED"},
        )
    reserve = Decimal(str(job.cost_estimate.get("reserved", "0")))
    if reserve <= 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_REPLAY_RESERVE_INVALID"},
        )
    recovery_job = ProcessingJob(
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        document_id=job.document_id,
        job_type=job.job_type,
        status="queued",
        priority=job.priority,
        requested_options={
            **job.requested_options,
            "route_profile": payload.fallback_route_profile,
            "retry_count": int(job.requested_options.get("retry_count", 0)) + 1,
            "fallback_of_job_id": str(job.id),
            "fallback_of_event_id": str(event.id),
            "fallback_reason_code": payload.reason_code,
            "idempotency_key": idempotency_key,
        },
        progress={"done": 0, "total": job.progress.get("total", 1)},
        cost_estimate=dict(job.cost_estimate),
    )
    session.add(recovery_job)
    await session.flush()
    await credit_entry(
        session,
        tenant_id=principal.tenant_id,
        operation_key=f"job:{recovery_job.id}:attempt:0:reserve",
        entry_type="reserve",
        credits=reserve,
        job_id=recovery_job.id,
        metadata={
            "fallback_of_job_id": str(job.id),
            "fallback_of_event_id": str(event.id),
            "fallback_route_profile": payload.fallback_route_profile,
        },
    )
    await emit_event(
        session,
        job=recovery_job,
        event_type="job.created.v1",
        payload={
            "status": "queued",
            "job_type": recovery_job.job_type,
            "fallback_of_job_id": str(job.id),
            "route_profile": payload.fallback_route_profile,
        },
    )
    await emit_event(
        session,
        job=recovery_job,
        event_type="credit.reserved.v1",
        payload={"credits": str(reserve), "reason": "dispatch_dlq_fallback"},
    )
    recovery_event = OutboxEvent(
        tenant_id=principal.tenant_id,
        aggregate_type="job",
        aggregate_id=recovery_job.id,
        event_type="job.dispatch.requested.v1",
        payload={
            "job_id": str(recovery_job.id),
            "tenant_id": str(principal.tenant_id),
            "fallback_of_event_id": str(event.id),
            "idempotency_key": idempotency_key,
        },
    )
    session.add(recovery_event)
    await session.flush()
    event.payload = {
        **event.payload,
        "operator_disposition": "fallback",
        "fallback_by_event_id": str(recovery_event.id),
        "fallback_by_job_id": str(recovery_job.id),
        "fallback_route_profile": payload.fallback_route_profile,
        "disposition_reason_code": payload.reason_code,
        "disposed_at": utcnow().isoformat(),
    }
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="dispatch_dlq.fallback_created",
        target_type="processing_job",
        target_id=str(recovery_job.id),
        metadata={
            "original_event_id": str(event.id),
            "original_job_id": str(job.id),
            "new_event_id": str(recovery_event.id),
            "from_route_profile": current_route,
            "to_route_profile": payload.fallback_route_profile,
            "reason_code": payload.reason_code,
            "note": payload.note,
            "previous_state_sha256": actual_state,
        },
    )
    await session.commit()
    return {
        "original_event_id": event.id,
        "new_job_id": recovery_job.id,
        "new_event_id": recovery_event.id,
        "fallback_route_profile": payload.fallback_route_profile,
    }


@router.post("/admin/dispatch-dlq/{event_id}/replay", status_code=202)
@idempotent_mutation
async def replay_dispatch_dead_letter(
    event_id: uuid.UUID,
    principal: AdminDep,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, uuid.UUID]:
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(
            status_code=400,
            detail={"code": "IDEMPOTENCY_KEY_REQUIRED"},
        )
    original_event = await session.scalar(
        select(OutboxEvent)
        .where(
            OutboxEvent.tenant_id == principal.tenant_id,
            OutboxEvent.id == event_id,
            OutboxEvent.event_type == "job.dispatch.requested.v1",
            OutboxEvent.dead_lettered_at.is_not(None),
        )
        .with_for_update()
    )
    if original_event is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "DISPATCH_DEAD_LETTER_NOT_FOUND"},
        )

    if original_event.payload.get("operator_disposition"):
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_DEAD_LETTER_ALREADY_DISPOSED"},
        )
    if original_event.payload.get("replayed_by_event_id"):
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_DEAD_LETTER_ALREADY_REPLAYED"},
        )

    try:
        payload_job_id = uuid.UUID(str(original_event.payload["job_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_DEAD_LETTER_PAYLOAD_INVALID"},
        ) from exc
    if original_event.aggregate_type != "job" or payload_job_id != original_event.aggregate_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_DEAD_LETTER_PAYLOAD_INVALID"},
        )

    original_job = await session.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.tenant_id == principal.tenant_id,
            ProcessingJob.id == original_event.aggregate_id,
        )
        .with_for_update()
    )
    if original_job is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_ORIGINAL_JOB_MISSING"},
        )
    if original_job.status != "failed":
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_ORIGINAL_JOB_NOT_TERMINAL"},
        )
    if (original_job.error or {}).get("code") != "DISPATCH_ATTEMPTS_EXHAUSTED":
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_ORIGINAL_JOB_NOT_REPLAYABLE"},
        )

    reserve = Decimal(str(original_job.cost_estimate.get("reserved", "0")))
    if reserve <= 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "DISPATCH_REPLAY_RESERVE_INVALID"},
        )
    requested_options = {
        **original_job.requested_options,
        "retry_count": int(original_job.requested_options.get("retry_count", 0)) + 1,
        "replay_of_job_id": str(original_job.id),
        "replay_of_event_id": str(original_event.id),
        "idempotency_key": idempotency_key,
    }
    new_job = ProcessingJob(
        tenant_id=original_job.tenant_id,
        project_id=original_job.project_id,
        document_id=original_job.document_id,
        job_type=original_job.job_type,
        status="queued",
        priority=original_job.priority,
        requested_options=requested_options,
        progress={"done": 0, "total": original_job.progress.get("total", 1)},
        cost_estimate=dict(original_job.cost_estimate),
    )
    session.add(new_job)
    await session.flush()
    await credit_entry(
        session,
        tenant_id=principal.tenant_id,
        operation_key=f"job:{new_job.id}:attempt:0:reserve",
        entry_type="reserve",
        credits=reserve,
        job_id=new_job.id,
        metadata={
            "replay_of_job_id": str(original_job.id),
            "replay_of_event_id": str(original_event.id),
        },
    )
    await emit_event(
        session,
        job=new_job,
        event_type="job.created.v1",
        payload={
            "status": "queued",
            "job_type": new_job.job_type,
            "replay_of_job_id": str(original_job.id),
        },
    )
    await emit_event(
        session,
        job=new_job,
        event_type="credit.reserved.v1",
        payload={"credits": str(reserve), "reason": "dispatch_dlq_replay"},
    )
    new_event = OutboxEvent(
        tenant_id=principal.tenant_id,
        aggregate_type="job",
        aggregate_id=new_job.id,
        event_type="job.dispatch.requested.v1",
        payload={
            "job_id": str(new_job.id),
            "tenant_id": str(principal.tenant_id),
            "replay_of_event_id": str(original_event.id),
            "idempotency_key": idempotency_key,
        },
    )
    session.add(new_event)
    await session.flush()
    original_event.payload = {
        **original_event.payload,
        "replayed_by_event_id": str(new_event.id),
        "replayed_by_job_id": str(new_job.id),
    }
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="dispatch_dlq.replayed",
        target_type="processing_job",
        target_id=str(new_job.id),
        metadata={
            "original_event_id": str(original_event.id),
            "original_job_id": str(original_job.id),
            "new_event_id": str(new_event.id),
        },
    )
    await session.commit()
    return {
        "original_event_id": original_event.id,
        "new_job_id": new_job.id,
        "new_event_id": new_event.id,
    }


@router.post("/admin/jobs/{job_id}/retry", response_model=JobResponse)
@idempotent_mutation
async def admin_retry_job(
    job_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: AdminDep,
    session: SessionDep,
) -> ProcessingJob:
    job = await _tenant_job(
        session,
        principal.tenant_id,
        job_id,
        principal=principal,
        capability="write",
    )
    if job.status != "failed":
        raise HTTPException(status_code=409, detail={"code": "JOB_NOT_FAILED"})
    if job.requested_options.get("retry_count", 0) >= 1:
        raise HTTPException(status_code=409, detail={"code": "RETRY_BUDGET_EXHAUSTED"})
    job.requested_options = {
        **job.requested_options,
        "retry_count": job.requested_options.get("retry_count", 0) + 1,
    }
    job.status = "queued"
    job.error = None
    job.completed_at = None
    retry_number = int(job.requested_options["retry_count"])
    reserve = Decimal(str(job.cost_estimate.get("reserved", "0")))
    await credit_entry(
        session,
        tenant_id=principal.tenant_id,
        operation_key=f"job:{job.id}:attempt:{retry_number}:reserve",
        entry_type="reserve",
        credits=reserve,
        job_id=job.id,
    )
    await emit_event(
        session,
        job=job,
        event_type="credit.reserved.v1",
        payload={"credits": str(reserve), "attempt": retry_number},
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
                "attempt": retry_number,
            },
        )
    )
    await session.commit()
    if request.app.state.settings.local_background_tasks:
        background_tasks.add_task(
            _execute_background_job,
            request.app,
            job.id,
            principal.tenant_id,
        )
    return job


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    database = Database(runtime_settings)
    object_store = build_object_store(runtime_settings)
    cdr_adapter = build_cdr_adapter(runtime_settings)
    url_secret_codec = (
        UrlSecretCodec(
            encryption_key=runtime_settings.effective_url_encryption_key,
            query_hmac_secret=runtime_settings.effective_url_query_hmac_secret,
        )
        if runtime_settings.url_ingestion_enabled
        else None
    )
    identity_hasher = IdentityHasher(runtime_settings.effective_abuse_identity_hmac_secret)
    client_identity_resolver = TrustedProxyIdentityResolver(
        hasher=identity_hasher,
        trusted_proxy_cidrs=runtime_settings.trusted_proxy_networks,
    )
    rate_limiter = build_rate_limiter(
        environment=runtime_settings.env,
        redis_url=runtime_settings.redis_url,
        memory_max_buckets=runtime_settings.rate_limit_memory_max_buckets,
    )
    captcha_provider = (
        TurnstileCaptchaProvider(
            secret_key=runtime_settings.captcha_secret_key or "",
            verify_url=runtime_settings.captcha_verify_url,
            timeout_seconds=runtime_settings.captcha_timeout_seconds,
        )
        if runtime_settings.captcha_provider == "turnstile"
        else UnavailableCaptchaProvider()
    )
    verification_token_codec = VerificationTokenCodec(
        runtime_settings.effective_verification_hmac_secret,
        ttl_seconds=runtime_settings.verification_token_ttl_seconds,
    )
    team_invitation_token_codec = TeamInvitationTokenCodec(
        runtime_settings.effective_verification_hmac_secret,
        ttl_seconds=runtime_settings.team_invitation_ttl_seconds,
    )
    verification_payload_cipher = VerificationPayloadCipher(
        encryption_key=(runtime_settings.effective_verification_delivery_encryption_key),
        identity_hasher=identity_hasher,
    )
    verification_capture: DevelopmentCaptureProvider | None = None
    verification_delivery_provider: VerificationDeliveryProvider
    if runtime_settings.email_verification_provider == "capture":
        verification_capture = DevelopmentCaptureProvider(
            environment=runtime_settings.env,
        )
        verification_delivery_provider = verification_capture
    elif runtime_settings.email_verification_provider == "resend":
        verification_delivery_provider = ResendVerificationDeliveryProvider(
            api_key=runtime_settings.resend_api_key or "",
            sender=runtime_settings.resend_sender or "",
            public_base_url=runtime_settings.verification_public_base_url,
            timeout_seconds=runtime_settings.resend_timeout_seconds,
        )
    else:
        verification_delivery_provider = UnavailableVerificationDeliveryProvider()
    payment_provider = build_payment_provider(runtime_settings)
    pdf_secret_store = (
        RedisPdfSecretStore.from_url(
            runtime_settings.redis_url,
            encryption_key=runtime_settings.effective_pdf_password_encryption_key,
            key_secret=runtime_settings.effective_pdf_password_hmac_secret,
        )
        if runtime_settings.redis_url
        and runtime_settings.pdf_password_encryption_key
        and runtime_settings.pdf_password_hmac_secret
        else InMemoryPdfSecretStore(
            key_secret=runtime_settings.effective_pdf_password_hmac_secret,
        )
    )
    telemetry_runtime = create_telemetry_runtime(
        enabled=runtime_settings.otel_enabled,
        service_name=runtime_settings.otel_service_name,
        environment=runtime_settings.env,
        endpoint=runtime_settings.otel_exporter_otlp_endpoint,
        export_timeout_seconds=runtime_settings.otel_export_timeout_seconds,
    )
    mfa_security = MfaSecurity(runtime_settings)
    oidc_client = OidcClient(runtime_settings) if runtime_settings.oidc_enabled else None
    oidc_transaction_cipher = (
        OidcTransactionCipher(runtime_settings) if runtime_settings.oidc_enabled else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        try:
            await rate_limiter.healthcheck()
            if runtime_settings.env in {"development", "test"}:
                await database.create_schema()
            yield
        finally:
            try:
                await pdf_secret_store.close()
            finally:
                try:
                    await payment_provider.aclose()
                finally:
                    try:
                        await verification_delivery_provider.aclose()
                    finally:
                        try:
                            await captcha_provider.aclose()
                        finally:
                            try:
                                await rate_limiter.aclose()
                            finally:
                                try:
                                    await database.dispose()
                                finally:
                                    try:
                                        if oidc_client is not None:
                                            await oidc_client.aclose()
                                    finally:
                                        try:
                                            await cdr_adapter.aclose()
                                        finally:
                                            telemetry_runtime.shutdown()

    app = FastAPI(
        title="AI Knowledge Compiler API",
        version="1.0.0",
        lifespan=lifespan,
    )
    install_fastapi_observability(app, telemetry_runtime)
    app.state.settings = runtime_settings
    app.state.database = database
    app.state.object_store = object_store
    app.state.cdr_adapter = cdr_adapter
    app.state.url_secret_codec = url_secret_codec
    app.state.identity_hasher = identity_hasher
    app.state.client_identity_resolver = client_identity_resolver
    app.state.rate_limiter = rate_limiter
    app.state.captcha_provider = captcha_provider
    app.state.verification_token_codec = verification_token_codec
    app.state.team_invitation_token_codec = team_invitation_token_codec
    app.state.verification_payload_cipher = verification_payload_cipher
    app.state.verification_delivery_provider = verification_delivery_provider
    app.state.verification_capture = verification_capture
    app.state.payment_provider = payment_provider
    app.state.pdf_secret_store = pdf_secret_store
    app.state.telemetry_runtime = telemetry_runtime
    app.state.mfa_security = mfa_security
    app.state.oidc_client = oidc_client
    app.state.oidc_transaction_cipher = oidc_transaction_cipher
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "Last-Event-ID",
            "X-Captcha-Token",
        ],
        expose_headers=["ETag", "Retry-After", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_security(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4()}"
        request.state.request_id = request_id
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("Origin")
            has_cookie = runtime_settings.session_cookie_name in request.cookies
            if has_cookie and origin and origin not in runtime_settings.allowed_origins:
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "CSRF_ORIGIN_DENIED",
                            "message": "Request origin is not allowed.",
                            "request_id": request_id,
                            "retryable": False,
                            "details": {},
                        }
                    },
                )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        raw_detail = cast(object, exc.detail)
        detail: dict[str, Any]
        if isinstance(raw_detail, dict):
            detail = {str(key): value for key, value in raw_detail.items()}
        else:
            detail = {"message": str(raw_detail)}
        code = str(detail.pop("code", "HTTP_ERROR"))
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "error": {
                    "code": code,
                    "message": str(detail.pop("message", code)),
                    "request_id": getattr(
                        request.state,
                        "request_id",
                        request.headers.get(
                            "X-Request-ID",
                            f"req_{uuid.uuid4()}",
                        ),
                    ),
                    "retryable": exc.status_code >= 500,
                    "details": detail,
                }
            },
        )

    @app.get("/health/live", include_in_schema=False)
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    async def health_ready() -> dict[str, str]:
        try:
            await rate_limiter.healthcheck()
        except RateLimitBackendUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "ABUSE_CONTROL_UNAVAILABLE"},
            ) from exc
        async with database.sessions() as session:
            await session.scalar(select(func.count(Tenant.id)))
        if runtime_settings.clamav_enabled and not await malware_scanner_ready(runtime_settings):
            raise HTTPException(
                status_code=503,
                detail={"code": "ANTIVIRUS_UNAVAILABLE"},
            )
        if runtime_settings.cdr_enabled and not await cdr_adapter.ready():
            raise HTTPException(
                status_code=503,
                detail={"code": "CDR_UNAVAILABLE"},
            )
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        if not runtime_settings.metrics_enabled:
            raise HTTPException(status_code=404, detail={"code": "METRICS_DISABLED"})
        return Response(
            content=render_prometheus(),
            media_type=PROMETHEUS_CONTENT_TYPE,
        )

    if (
        runtime_settings.env == "test"
        and runtime_settings.test_support_key
        and verification_capture is not None
    ):

        @app.post("/__test__/verification-token", include_in_schema=False)
        async def take_test_verification_token(
            request: Request,
            x_akc_test_support_key: Annotated[
                str | None,
                Header(alias="X-AKC-Test-Support-Key"),
            ] = None,
        ) -> JSONResponse:
            configured_key = runtime_settings.test_support_key or ""
            if x_akc_test_support_key is None or not secrets.compare_digest(
                x_akc_test_support_key,
                configured_key,
            ):
                raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
            try:
                body = await request.json()
                email = normalize_public_email(str(body["email"]))
            except (KeyError, TypeError, ValueError):
                raise HTTPException(
                    status_code=404,
                    detail={"code": "NOT_FOUND"},
                ) from None
            message = await verification_capture.take_for(email)
            if message is None:
                raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
            return JSONResponse(
                content={"token": message.token},
                headers={
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                    "Referrer-Policy": "no-referrer",
                },
            )

    app.include_router(router)
    app.include_router(advanced_auth_router)
    app.include_router(payment_router)
    app.include_router(pdf_password_router)
    app.include_router(knowledge_api_router)
    app.include_router(batch_router)
    app.include_router(team_router)
    app.include_router(project_access_router)
    app.include_router(product_analytics_event_router)
    app.include_router(domain_api_router)
    return app


app = create_app()
