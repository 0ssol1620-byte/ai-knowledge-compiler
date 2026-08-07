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

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast

from akc_security import ALLOWED_EXTENSIONS, sanitize_display_filename
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.abuse import RateLimitPolicy
from akc_api.abuse_controls import client_subject, consume_rate_control
from akc_api.database import get_session, set_rls_context
from akc_api.models import Document, Project, TrialSession, UploadSession
from akc_api.schemas import (
    TrialPreflight,
    TrialSessionCreated,
    TrialUploadAccepted,
    TrialUploadRequest,
)
from akc_api.settings import Settings


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
        upload_url=target.url,
        headers=target.headers,
        expires_at=expires_at,
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

    page_count = document.page_count
    cap = settings.trial_ingest_max_pages
    # §25.7 — a document longer than the cap is inspected in part, and a partial
    # measurement is never reported as a whole one.
    inspected = min(page_count, cap) if page_count is not None else 0
    truncated = page_count is not None and page_count > cap

    return TrialPreflight(
        session_id=trial.id,
        document_id=document.id,
        status=_public_status(document.status),
        page_count=page_count,
        pages_inspected=inspected,
        truncated=truncated,
        detected_language_codes=list(document.language_codes or []),
        encrypted=None,
        route_profile=None,
        error_code=None,
        expires_at=_as_utc(trial.expires_at),
    )


# Internal states are richer than the trial contract admits. Anything past
# preflight is not reachable here, and anything unrecognised is reported as
# FAILED rather than leaked — a status string is a small information channel,
# but it is one.
_PUBLIC_STATUS = {
    "UPLOADING": "UPLOADED",
    "UPLOADED": "UPLOADED",
    "SECURITY_SCANNING": "SECURITY_SCANNING",
    "SECURITY_VERIFIED": "SECURITY_VERIFIED",
    "SECURITY_REJECTED": "SECURITY_REJECTED",
    "PREFLIGHTING": "PREFLIGHTING",
    "PREFLIGHTED": "PREFLIGHTED",
}


def _public_status(status: str) -> str:
    return _PUBLIC_STATUS.get(status, "FAILED")
