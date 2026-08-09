"""Anonymous trial ingest — ADR-006.

A visitor with no account may submit one document and see the preflight it
produces. Kept in its own module rather than added to ``main.py`` because it is
the only unauthenticated write surface in the product: it should be obvious in
a diff, and reviewable without reading nine thousand lines of authenticated
handlers around it.

Four properties hold by construction and each is enforced here rather than
assumed:

1. Tenant scoping. Every row and every object key sits under the reserved
   system trial tenant from migration 0023. There is no tenant-less write and
   no RLS bypass.
2. The ADR-004 quarantine path is not shortened. A trial document enters at
   ``UPLOADED`` and reaches preflight only through security scanning.
3. The flow stops at ``PREFLIGHTED``. Nothing here can reach extraction,
   knowledge construction, export, or GPU work — the cost surface stays behind
   a principal.
4. Every entry point charges the limiter before it does anything else, and the
   limiter fails closed.
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Annotated, BinaryIO, cast

from akc_security import (
    ALLOWED_EXTENSIONS,
    CdrStatus,
    PlanTier,
    sanitize_display_filename,
)
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.abuse import RateLimitPolicy
from akc_api.abuse_controls import client_subject, consume_rate_control
from akc_api.database import get_session, set_rls_context
from akc_api.models import (
    Document,
    Page,
    Project,
    SourceFile,
    TrialSession,
    UploadSession,
)
from akc_api.quarantine_screening import (
    SPOOL_MAX_BYTES,
    QuarantineUnavailable,
    QuarantineVerdict,
    screen_quarantined_object,
)
from akc_api.schemas import (
    TrialPreflight,
    TrialSessionCreated,
    TrialUploadAccepted,
    TrialUploadRequest,
)
from akc_api.settings import Settings
from akc_api.storage import LocalObjectStore


def require_trial_enabled(request: Request) -> Settings:
    """Refuse every route in this module while the capability is off.

    A router-level dependency rather than a check inside each handler: FastAPI
    resolves these before it validates a request body, so a disabled endpoint
    answers 404 instead of 422. A 422 would describe the request schema of a
    capability that is supposed to look absent.

    404 rather than 403 for the same reason — a disabled capability should not
    advertise that it exists.
    """
    settings = cast(Settings, request.app.state.settings)
    if not settings.trial_ingest_enabled:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return settings


router = APIRouter(
    prefix="/v1/trial",
    tags=["trial"],
    dependencies=[Depends(require_trial_enabled)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(require_trial_enabled)]

# Reserved identifiers seeded by migration 0023. Duplicated as constants rather
# than looked up by slug so a renamed row cannot silently redirect anonymous
# writes into a different tenant.
TRIAL_TENANT_ID = uuid.UUID("00000000-0000-4000-a000-000000000b01")
TRIAL_USER_ID = uuid.UUID("00000000-0000-4000-a000-000000000b02")

# Two controls, not one. Creating a session and presigning an object cost
# different things, so they get different budgets — sharing a counter meant a
# visitor who mis-picked a file twice could no longer upload at all.
CONTROL_SESSION = "trial_session"
CONTROL_UPLOAD = "trial_upload"


def _utcnow() -> datetime:
    from akc_api.models import utcnow

    return utcnow()


def _as_utc(value: datetime) -> datetime:
    """Normalise a persisted timestamp before comparing it.

    Columns are ``DateTime(timezone=True)``, but SQLite — the deterministic
    development adapter — hands back naive values. Comparing one against an
    aware ``utcnow()`` raises, so the comparison must not depend on which
    driver is underneath. Same convention as deletions.py and auth_api.py.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _session_policy(settings: Settings) -> RateLimitPolicy:
    return RateLimitPolicy(
        limit=settings.trial_ingest_sessions_per_client,
        window_seconds=settings.trial_ingest_window_seconds,
        # Escalate before refusing, so a human near the boundary gets a
        # challenge rather than a wall.
        captcha_after=settings.trial_ingest_captcha_after,
    )


def _upload_policy(settings: Settings) -> RateLimitPolicy:
    return RateLimitPolicy(
        limit=settings.trial_ingest_uploads_per_client,
        window_seconds=settings.trial_ingest_window_seconds,
    )


async def _load_session(
    session: AsyncSession,
    session_id: uuid.UUID,
    *,
    now: datetime,
) -> TrialSession:
    """Resolve a session id, treating expired and deleted as absent.

    The identifier is the only credential a trial visitor holds, so an expired
    one must be indistinguishable from one that never existed — otherwise the
    endpoint reports whether a given id was ever issued.
    """
    await set_rls_context(session, tenant_id=TRIAL_TENANT_ID)
    trial = await session.scalar(
        select(TrialSession).where(
            TrialSession.id == session_id,
            TrialSession.tenant_id == TRIAL_TENANT_ID,
            TrialSession.deletion_requested_at.is_(None),
            TrialSession.expires_at > now,
        )
    )
    if trial is None:
        raise HTTPException(status_code=404, detail={"code": "TRIAL_SESSION_NOT_FOUND"})
    return trial


@router.post("/sessions", response_model=TrialSessionCreated, status_code=201)
async def create_trial_session(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> TrialSessionCreated:
    """Issue one session and the project that will hold its document."""
    response.headers["Cache-Control"] = "no-store"

    subject = client_subject(request)
    await consume_rate_control(
        request,
        control=CONTROL_SESSION,
        subjects=[(subject, _session_policy(settings))],
        captcha_action="trial_ingest",
    )

    now = _utcnow()
    await set_rls_context(session, tenant_id=TRIAL_TENANT_ID, user_id=TRIAL_USER_ID)

    trial_id = uuid.uuid4()
    project = Project(
        tenant_id=TRIAL_TENANT_ID,
        name=f"Trial {trial_id}",
        description="Anonymous trial session (ADR-006). Deleted at expiry.",
        classification="trial",
        created_by=TRIAL_USER_ID,
    )
    session.add(project)
    await session.flush()

    trial = TrialSession(
        id=trial_id,
        tenant_id=TRIAL_TENANT_ID,
        project_id=project.id,
        client_subject=subject,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.trial_ingest_ttl_seconds),
    )
    session.add(trial)
    await session.commit()

    return TrialSessionCreated(
        session_id=trial.id,
        expires_at=trial.expires_at,
        max_bytes=settings.trial_ingest_max_bytes,
        max_pages=settings.trial_ingest_max_pages,
        accepted_content_types=sorted(ALLOWED_EXTENSIONS),
    )


@router.post(
    "/sessions/{session_id}/uploads",
    response_model=TrialUploadAccepted,
    status_code=201,
)
async def initiate_trial_upload(
    session_id: uuid.UUID,
    payload: TrialUploadRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> TrialUploadAccepted:
    """Presign one object for this session. One document per session, ever."""
    response.headers["Cache-Control"] = "no-store"

    now = _utcnow()
    trial = await _load_session(session, session_id, now=now)

    # Validation runs before the limiter is charged. A rejected size or an
    # unreadable extension costs the server a JSON parse and nothing else, and
    # charging for it locked out a visitor who picked the wrong file twice —
    # the budget exists to bound work, not to punish a mis-click.
    #
    # Cheap validation is not unbounded: reaching this line at all requires a
    # live session id, and creating those is limited separately.
    if payload.size > settings.trial_ingest_max_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "TRIAL_FILE_TOO_LARGE",
                "max_bytes": settings.trial_ingest_max_bytes,
            },
        )

    normalized_filename = sanitize_display_filename(payload.filename)
    extension = "." + normalized_filename.rsplit(".", 1)[-1].casefold()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail={"code": "UNSUPPORTED_FILE_TYPE"})

    # From here the request does real work — a row and a presign — so it pays.
    await consume_rate_control(
        request,
        control=CONTROL_UPLOAD,
        subjects=[(client_subject(request), _upload_policy(settings))],
    )

    # ADR-006 caps a session at one document. Checked against the project rather
    # than trusted from the client, so a replayed request cannot add a second.
    existing = await session.scalar(
        select(func.count())
        .select_from(Document)
        .where(
            Document.tenant_id == TRIAL_TENANT_ID,
            Document.project_id == trial.project_id,
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"code": "TRIAL_DOCUMENT_ALREADY_SUBMITTED"},
        )

    document = Document(
        tenant_id=TRIAL_TENANT_ID,
        project_id=trial.project_id,
        source_file_id=None,
        title=normalized_filename,
        document_type=extension.removeprefix("."),
        active_version=1,
        # ADR-004's entry state. Nothing reads this object until the scanner
        # promotes it.
        status="UPLOADING",
    )
    session.add(document)
    await session.flush()

    upload_id = uuid.uuid4()
    # Same tenant/project prefix shape as the authenticated path, which ADR-004
    # requires for object authorization to be checkable.
    object_key = (
        f"tenants/{TRIAL_TENANT_ID}/projects/{trial.project_id}/"
        f"documents/{document.id}/versions/v1/uploads/{upload_id}/original.bin"
    )

    try:
        target = await request.app.state.object_store.create_upload_target(
            upload_id=str(upload_id),
            object_key=object_key,
            content_type=payload.content_type,
            expected_sha256=payload.sha256.lower(),
            expires=settings.presigned_upload_ttl_seconds,
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise HTTPException(
            status_code=503, detail={"code": "OBJECT_STORE_UNAVAILABLE"}
        ) from exc

    upload_url = target.url
    if isinstance(request.app.state.object_store, LocalObjectStore):
        # The adapter's URL points at an authenticated route. Anonymous
        # visitors cannot use it, so the trial serves its own.
        upload_url = f"/v1/trial/sessions/{trial.id}/uploads/{upload_id}/content"

    # The presign must not outlive the session it belongs to.
    expires_at = min(
        now + timedelta(seconds=settings.presigned_upload_ttl_seconds),
        _as_utc(trial.expires_at),
    )

    session.add(
        UploadSession(
            id=upload_id,
            tenant_id=TRIAL_TENANT_ID,
            project_id=trial.project_id,
            document_id=document.id,
            document_version=1,
            created_by=TRIAL_USER_ID,
            original_filename=payload.filename,
            safe_filename=normalized_filename,
            expected_mime=payload.content_type,
            expected_size=payload.size,
            expected_sha256=payload.sha256.lower(),
            object_key=object_key,
            upload_mode="single",
            status="initiated",
            expires_at=expires_at,
        )
    )
    await session.commit()

    return TrialUploadAccepted(
        document_id=document.id,
        upload_id=upload_id,
        upload_url=upload_url,
        headers=target.headers,
        expires_at=expires_at,
    )


@router.put(
    "/sessions/{session_id}/uploads/{upload_id}/content",
    status_code=204,
)
async def put_trial_upload_content(
    session_id: uuid.UUID,
    upload_id: uuid.UUID,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> None:
    """Receive the bytes, for the development object store only.

    In production ``create_upload_target`` returns a presigned S3 URL and the
    visitor's browser writes straight to the bucket, so this route is never
    reached. The local adapter instead returns a URL pointing back at the API,
    and the one it returns requires an authenticated editor — which an
    anonymous visitor is not. Without this route the trial flow is broken
    outside production, and the security path below can never be exercised by
    a test.

    Authorization is by trial session rather than by principal: the session id
    is the visitor's only credential, and the upload must belong to it.
    """
    response.headers["Cache-Control"] = "no-store"

    if not isinstance(request.app.state.object_store, LocalObjectStore):
        raise HTTPException(status_code=405, detail={"code": "DIRECT_UPLOAD_REQUIRED"})

    now = _utcnow()
    trial = await _load_session(session, session_id, now=now)
    upload, document = await _load_upload(session, upload_id, trial=trial)
    if upload.status != "initiated":
        raise HTTPException(status_code=409, detail={"code": "UPLOAD_NOT_ACTIVE"})
    if _as_utc(upload.expires_at) <= now:
        raise HTTPException(status_code=409, detail={"code": "UPLOAD_EXPIRED"})

    content_type = request.headers.get("Content-Type", "").split(";", 1)[0].casefold()
    if content_type != upload.expected_mime.split(";", 1)[0].casefold():
        raise HTTPException(status_code=422, detail={"code": "CONTENT_TYPE_MISMATCH"})

    size = 0
    digest = hashlib.sha256()
    with tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES, mode="w+b") as staged:
        async for chunk in request.stream():
            size += len(chunk)
            # Two ceilings, and the smaller one wins. The upload session's own
            # expected size bounds this request; the trial cap bounds what a
            # session could have been issued in the first place.
            if size > min(upload.expected_size, settings.trial_ingest_max_bytes):
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
    # ADR-004's name for "bytes are in quarantine and nothing has read them".
    document.status = "QUARANTINED"
    await session.commit()


@router.post(
    "/sessions/{session_id}/uploads/{upload_id}/complete",
    response_model=TrialPreflight,
)
async def complete_trial_upload(
    session_id: uuid.UUID,
    upload_id: uuid.UUID,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> TrialPreflight:
    """Screen the uploaded object and, if it passes, preflight it.

    This is the same ADR-004 gauntlet the authenticated route runs — literally
    the same function — so a trial document is not screened more cheaply than
    a paid one. What differs is only the bookkeeping around it: the audit rows
    are written under the system trial identity, and there is no free-tier
    duplicate check because there is no plan to bill against.

    The flow then stops at ``PREFLIGHTED``. That is the boundary ADR-006 draws,
    and it is enforced here by simply not enqueueing anything: no processing
    job is created, so no worker can pick this document up and no GPU can be
    reached from an anonymous request.
    """
    response.headers["Cache-Control"] = "no-store"

    now = _utcnow()
    trial = await _load_session(session, session_id, now=now)
    upload, document = await _load_upload(session, upload_id, trial=trial)

    if upload.status == "completed":
        # Idempotent: a retried completion reports where the document actually
        # got to rather than screening the same bytes twice.
        return _preflight_of(document, trial=trial, settings=settings)
    if upload.status not in {"initiated", "uploaded"}:
        # "initiated" covers a presigned S3 write the API never saw; "uploaded"
        # is what the development adapter's content route leaves behind.
        raise HTTPException(status_code=409, detail={"code": "TRIAL_UPLOAD_NOT_PENDING"})

    document.status = "SECURITY_SCANNING"
    await session.commit()

    try:
        verdict = await screen_quarantined_object(
            object_store=request.app.state.object_store,
            cdr_adapter=request.app.state.cdr_adapter,
            settings=settings,
            object_key=upload.object_key,
            safe_filename=upload.safe_filename,
            expected_size=upload.expected_size,
            expected_mime=upload.expected_mime,
            expected_sha256=upload.expected_sha256,
            upload_mode=upload.upload_mode,
            # The trial has no plan, so it gets the most restrictive limits the
            # product defines rather than a tier invented for it.
            tier=PlanTier.FREE,
        )
    except QuarantineUnavailable as exc:
        await _audit_trial(session, action=exc.audit_action, document=document)
        await session.commit()
        raise HTTPException(status_code=503, detail={"code": exc.code}) from exc

    if not verdict.accepted:
        return await _reject_trial_upload(
            session,
            request=request,
            upload=upload,
            document=document,
            trial=trial,
            settings=settings,
            code=verdict.rejection_code or "UNSAFE_FILE",
        )

    source = await _promote_trial_source(
        session,
        request=request,
        upload=upload,
        document=document,
        verdict=verdict,
        now=now,
    )
    await _preflight_trial_document(
        session,
        request=request,
        document=document,
        source=source,
        settings=settings,
    )
    await session.commit()

    with suppress(BotoCoreError, ClientError, OSError, KeyError):
        await request.app.state.object_store.delete("quarantine", upload.object_key)

    return _preflight_of(document, trial=trial, settings=settings)


async def _load_upload(
    session: AsyncSession,
    upload_id: uuid.UUID,
    *,
    trial: TrialSession,
) -> tuple[UploadSession, Document]:
    """Resolve the upload and its document, both scoped to this session.

    Scoped to ``trial.project_id`` rather than to the tenant alone: every trial
    session shares one tenant, so tenant scoping by itself would let one
    visitor's session id complete another visitor's upload.
    """
    upload = await session.scalar(
        select(UploadSession).where(
            UploadSession.id == upload_id,
            UploadSession.tenant_id == TRIAL_TENANT_ID,
            UploadSession.project_id == trial.project_id,
        )
    )
    if upload is None:
        raise HTTPException(status_code=404, detail={"code": "TRIAL_UPLOAD_NOT_FOUND"})
    document = await session.scalar(
        select(Document).where(
            Document.id == upload.document_id,
            Document.tenant_id == TRIAL_TENANT_ID,
            Document.project_id == trial.project_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "TRIAL_UPLOAD_NOT_FOUND"})
    return upload, document


async def _audit_trial(
    session: AsyncSession,
    *,
    action: str,
    document: Document,
    metadata: dict[str, object] | None = None,
) -> None:
    """Write an audit row under the system trial identity.

    The trial has no principal, and inventing one would defeat the point of
    ADR-006. The reserved service user is used as the actor instead: it exists,
    it is inactive, and it cannot authenticate — so the row is attributable to
    the capability rather than to a person.
    """
    from akc_api.services import audit

    await audit(
        session,
        tenant_id=TRIAL_TENANT_ID,
        actor_id=TRIAL_USER_ID,
        action=action,
        target_type="document",
        target_id=str(document.id),
        metadata=metadata,
    )


async def _reject_trial_upload(
    session: AsyncSession,
    *,
    request: Request,
    upload: UploadSession,
    document: Document,
    trial: TrialSession,
    settings: Settings,
    code: str,
) -> TrialPreflight:
    """Record a refusal and remove the object.

    §11.2 R3: what fails verification stays visible. The document row survives
    in ``SECURITY_REJECTED`` so the visitor is told what happened and why. The
    bytes do not survive — they are deleted from quarantine and were never
    promoted, so nothing that failed screening is readable afterwards.
    """
    document.status = "SECURITY_REJECTED"
    upload.status = "aborted"
    with suppress(BotoCoreError, ClientError, OSError, KeyError):
        await request.app.state.object_store.delete("quarantine", upload.object_key)
    await _audit_trial(
        session,
        action="document.security_rejected",
        document=document,
        metadata={"code": code, "trial": True},
    )
    await session.commit()
    return _preflight_of(document, trial=trial, settings=settings, error_code=code)


async def _promote_trial_source(
    session: AsyncSession,
    *,
    request: Request,
    upload: UploadSession,
    document: Document,
    verdict: QuarantineVerdict,
    now: datetime,
) -> SourceFile:
    """Move the screened object out of quarantine and record its provenance."""
    digest = verdict.digest
    source_key = (
        f"tenants/{TRIAL_TENANT_ID}/projects/{upload.project_id}/"
        f"sources/sha256/{digest}/original.bin"
    )
    try:
        await request.app.state.object_store.promote_source(upload.object_key, source_key)
    except (BotoCoreError, ClientError, FileNotFoundError, OSError, KeyError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "SOURCE_PROMOTION_INTEGRITY_FAILED"},
        ) from exc

    cdr = verdict.cdr_result
    sanitized_key: str | None = None
    sanitized_sha256: str | None = None
    sanitized_size: int | None = None
    if cdr is not None and cdr.status is CdrStatus.SANITIZED:
        assert cdr.sanitized_payload is not None
        assert cdr.sanitized_sha256 is not None
        sanitized_sha256 = cdr.sanitized_sha256
        sanitized_size = len(cdr.sanitized_payload)
        sanitized_key = (
            f"tenants/{TRIAL_TENANT_ID}/projects/{upload.project_id}/"
            f"derived/cdr/sha256/{sanitized_sha256}/sanitized.bin"
        )
        await request.app.state.object_store.put_derived(sanitized_key, cdr.sanitized_payload)

    source = SourceFile(
        id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"akc-source:{TRIAL_TENANT_ID}:{upload.project_id}:{digest}",
        ),
        tenant_id=TRIAL_TENANT_ID,
        project_id=upload.project_id,
        upload_id=upload.id,
        original_filename=upload.original_filename,
        safe_filename=upload.safe_filename,
        mime_type=upload.expected_mime,
        size_bytes=verdict.size_bytes,
        sha256=digest,
        storage_key=source_key,
        antivirus_status=verdict.scan_status,
        cdr_status=(cdr.status.value if cdr is not None else "not_requested"),
        cdr_provider=(cdr.provider if cdr is not None else None),
        cdr_revision=(cdr.revision if cdr is not None else None),
        sanitized_storage_key=sanitized_key,
        sanitized_sha256=sanitized_sha256,
        sanitized_size_bytes=sanitized_size,
        uploaded_by=TRIAL_USER_ID,
    )
    session.add(source)
    # Same ordering requirement as the authenticated route: SQLite checks the
    # composite foreign key immediately, so the source identity has to exist
    # before the document points at it.
    await session.flush()

    upload.status = "completed"
    upload.completed_at = now
    document.source_file_id = source.id
    document.status = "SECURITY_VERIFIED"
    document.updated_at = now
    await _audit_trial(
        session,
        action="document.security_verified",
        document=document,
        metadata={
            "source_digest": request.app.state.identity_hasher.pseudonymize(
                purpose="source-digest",
                value=digest,
            ),
            "trial": True,
        },
    )
    return source


async def _preflight_trial_document(
    session: AsyncSession,
    *,
    request: Request,
    document: Document,
    source: SourceFile,
    settings: Settings,
) -> None:
    """Parse the document far enough to describe it, then stop.

    Run inline rather than enqueued, which is a deliberate departure from the
    authenticated route and worth stating plainly. The authenticated route
    hands preflight to the document worker because the file it accepts can be
    hundreds of megabytes and hundreds of pages. A trial file cannot: ADR-006
    caps it at ``trial_ingest_max_bytes`` and ``trial_ingest_max_pages``.
    Preflight itself is page geometry and text statistics — no OCR, no model,
    no network — so the bounded version of it fits inside the request that
    asked for it.

    The page cap has to be applied *by the parser*, not to its output, and that
    is the reason for the settings override below. ``parse_document`` reads
    ``settings.max_pages``, which is the product limit of 500. Slicing its
    result to ten afterwards would still have let one anonymous request drive a
    five-hundred-page text extraction — the cap would have described the answer
    rather than bounded the work. Passing the trial's own limit makes the
    parser check the page tree and stop before extracting anything.

    The alternative was to enqueue a job and let the visitor poll. That makes
    the first thing a visitor sees depend on worker infrastructure being up,
    to save work the caps now genuinely bound. It also creates a queue entry
    from an unauthenticated request, which is the cost surface ADR-006 keeps
    behind a principal.

    A parse failure is not an error here. The document reaches ``FAILED`` and
    the visitor is told the file could not be read, which is a true statement
    about their file and a more useful one than a 500.
    """
    from akc_api.parsers import FileValidationError, page_preflight, parse_document

    document.status = "PREFLIGHTING"
    await session.flush()

    # Read the promoted object, not the quarantined one. They are the same
    # bytes, but only one of them has passed screening, and reading the other
    # would make that distinction meaningless.
    try:
        raw = await request.app.state.object_store.read_source(source.storage_key)
    except (BotoCoreError, ClientError, FileNotFoundError, OSError, KeyError):
        document.status = "FAILED"
        await _audit_trial(
            session,
            action="document.preflight_failed",
            document=document,
            metadata={"code": "SOURCE_UNREADABLE", "trial": True},
        )
        return

    bounded = settings.model_copy(update={"max_pages": settings.trial_ingest_max_pages})
    try:
        parsed = parse_document(source.safe_filename, raw, bounded)
    except FileValidationError as exc:
        if exc.code != "PAGE_LIMIT":
            document.status = "FAILED"
            await _audit_trial(
                session,
                action="document.preflight_failed",
                document=document,
                metadata={"code": "UNREADABLE_DOCUMENT", "trial": True},
            )
            return
        # Longer than the trial reads. This is a real, reportable outcome, not
        # a failure — but the page count is deliberately absent, because the
        # parser stopped at the page tree and nothing counted them. §25.7:
        # a figure that was not measured is not published.
        document.page_count = None
        document.status = "PREFLIGHTED"
        await _audit_trial(
            session,
            action="document.preflighted",
            document=document,
            metadata={"pages": 0, "pages_truncated": True, "trial": True},
        )
        return
    except Exception:  # any parser failure is the same outcome to the visitor
        document.status = "FAILED"
        await _audit_trial(
            session,
            action="document.preflight_failed",
            document=document,
            metadata={"code": "UNREADABLE_DOCUMENT", "trial": True},
        )
        return

    # The parser already refused anything longer, so this is the whole document.
    pages = parsed.pages
    for parsed_page in pages:
        session.add(
            Page(
                tenant_id=TRIAL_TENANT_ID,
                document_id=document.id,
                page_number=parsed_page.page_number,
                width_pt=parsed_page.width_pt,
                height_pt=parsed_page.height_pt,
                status="PREFLIGHTED",
                # No route is recorded. Routing decides how a page would be
                # extracted, and the trial never extracts.
                preflight_metrics=dict(
                    page_preflight(
                        parsed_page.text,
                        image_coverage=parsed_page.image_coverage,
                    )
                ),
            )
        )
    # The whole document: the parser refused anything longer than the cap,
    # so this is a complete count rather than a partial one.
    document.page_count = len(parsed.pages)
    document.status = "PREFLIGHTED"
    await _audit_trial(
        session,
        action="document.preflighted",
        document=document,
        metadata={
            "pages": len(pages),
            "pages_truncated": False,
            "trial": True,
        },
    )


def _preflight_of(
    document: Document,
    *,
    trial: TrialSession,
    settings: Settings,
    error_code: str | None = None,
) -> TrialPreflight:
    """The one place a document row becomes a trial preflight response.

    Shared by the completion route and the polling route so the two cannot
    disagree about what a given document state means — in particular about
    ``truncated``, which is the §25.7 guard and is easy to get subtly wrong
    twice.
    """
    page_count = document.page_count
    cap = settings.trial_ingest_max_pages
    # A preflighted document with no page count is the over-cap case: the parser
    # stopped at the page tree, so nothing was counted and nothing may be
    # reported as if it had been (§25.7). The combination cannot arise any other
    # way — every document the parser did read has a count.
    over_cap = document.status == "PREFLIGHTED" and page_count is None
    return TrialPreflight(
        session_id=trial.id,
        document_id=document.id,
        status=_public_status(document.status),
        page_count=page_count,
        pages_inspected=min(page_count, cap) if page_count is not None else 0,
        truncated=over_cap or (page_count is not None and page_count > cap),
        detected_language_codes=list(document.language_codes or []),
        encrypted=None,
        route_profile=None,
        error_code=error_code,
        expires_at=_as_utc(trial.expires_at),
    )


@router.get("/sessions/{session_id}", response_model=TrialPreflight)
async def read_trial_preflight(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> TrialPreflight:
    """Report where the document is in the quarantine path, and what preflight found."""
    response.headers["Cache-Control"] = "no-store"

    now = _utcnow()
    trial = await _load_session(session, session_id, now=now)

    document = await session.scalar(
        select(Document).where(
            Document.tenant_id == TRIAL_TENANT_ID,
            Document.project_id == trial.project_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "TRIAL_DOCUMENT_NOT_FOUND"})

    return _preflight_of(document, trial=trial, settings=settings)


# Internal states are richer than the trial contract admits. Anything past
# preflight is not reachable here, and anything unrecognised is reported as
# FAILED rather than leaked — a status string is a small information channel,
# but it is one.
_PUBLIC_STATUS = {
    "UPLOADING": "UPLOADED",
    "UPLOADED": "UPLOADED",
    "QUARANTINED": "UPLOADED",
    "SECURITY_SCANNING": "SECURITY_SCANNING",
    "SECURITY_VERIFIED": "SECURITY_VERIFIED",
    "SECURITY_REJECTED": "SECURITY_REJECTED",
    "PREFLIGHTING": "PREFLIGHTING",
    "PREFLIGHTED": "PREFLIGHTED",
}


def _public_status(status: str) -> str:
    return _PUBLIC_STATUS.get(status, "FAILED")
