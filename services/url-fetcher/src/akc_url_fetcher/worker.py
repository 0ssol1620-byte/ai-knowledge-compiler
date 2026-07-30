"""Durable, lease-fenced URL ingestion worker."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO, Protocol, cast

from akc_api.malware import MalwareDetectedError, MalwareScanError
from akc_api.models import (
    AuditEvent,
    Document,
    DocumentVersion,
    Project,
    SourceFile,
    UploadSession,
    utcnow,
)
from akc_api.storage import ObjectStore
from akc_api.telemetry import track_audit_write
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from akc_url_fetcher.fetcher import FetchResult, SecureUrlFetcher, UrlFetchError
from akc_url_fetcher.models import UrlFetchTask
from akc_url_fetcher.security import UrlSecretCodec
from akc_url_fetcher.settings import UrlFetcherSettings
from akc_url_fetcher.telemetry import (
    URL_FETCH_DLQ,
    URL_FETCH_DURATION,
    URL_FETCH_QUEUE_DEPTH,
    record_url_fetch_attempt,
)

logger = logging.getLogger(__name__)
_SQLITE_WORKER_LOCKS: dict[str, asyncio.Lock] = {}

_MIME_EXTENSIONS = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/html": "html",
    "text/plain": "txt",
}
_SAFE_FETCH_CODES = frozenset(
    {
        "URL_FETCH_ADDRESS_FORBIDDEN",
        "URL_FETCH_ANTIVIRUS_UNAVAILABLE",
        "URL_FETCH_CANCELLED",
        "URL_FETCH_CONTENT_ENCODING_FORBIDDEN",
        "URL_FETCH_CONTENT_LENGTH_INVALID",
        "URL_FETCH_CONTENT_TYPE_FORBIDDEN",
        "URL_FETCH_CONTENT_TYPE_REQUIRED",
        "URL_FETCH_DNS_FAILED",
        "URL_FETCH_DNS_INVALID",
        "URL_FETCH_EMPTY_RESPONSE",
        "URL_FETCH_INTERNAL_ERROR",
        "URL_FETCH_MALWARE_DETECTED",
        "URL_FETCH_MIME_MISMATCH",
        "URL_FETCH_NETWORK_ERROR",
        "URL_FETCH_PORT_FORBIDDEN",
        "URL_FETCH_RESPONSE_TOO_LARGE",
        "URL_FETCH_SECRET_INVALID",
        "URL_FETCH_SOURCE_MISMATCH",
        "URL_FETCH_STORAGE_ERROR",
        "URL_FETCH_TARGET_DELETED",
        "URL_FETCH_TOO_MANY_REDIRECTS",
        "URL_FETCH_TOTAL_TIMEOUT",
        "URL_FETCH_UPSTREAM_REJECTED",
        "URL_FETCH_UPSTREAM_UNAVAILABLE",
        "URL_FETCH_URL_INVALID",
        "URL_FETCH_REDIRECT_INVALID",
    }
)


class Fetcher(Protocol):
    def fetch(self, url: str) -> FetchResult: ...


class ScanResult(Protocol):
    status: str


Scanner = Callable[[BinaryIO], Awaitable[ScanResult]]


class StaleUrlFetchLease(RuntimeError):
    """Another worker or cancellation owns the durable task now."""


class UrlAttemptError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        safe_code = code if code in _SAFE_FETCH_CODES else "URL_FETCH_INTERNAL_ERROR"
        super().__init__(safe_code)
        self.code = safe_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class UrlFetchRuntime:
    environment: str
    lease_seconds: float
    max_attempts: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    backoff_jitter_ratio: float
    poll_seconds: float
    max_bytes: int

    @classmethod
    def from_settings(cls, settings: UrlFetcherSettings) -> UrlFetchRuntime:
        return cls(
            environment=settings.env,
            lease_seconds=settings.url_fetch_lease_seconds,
            max_attempts=settings.url_fetch_max_attempts,
            backoff_base_seconds=settings.url_fetch_backoff_base_seconds,
            backoff_max_seconds=settings.url_fetch_backoff_max_seconds,
            backoff_jitter_ratio=settings.url_fetch_backoff_jitter_ratio,
            poll_seconds=settings.url_fetch_poll_interval_seconds,
            max_bytes=settings.url_fetch_max_bytes,
        )


@dataclass(frozen=True, slots=True)
class UrlFetchClaim:
    task_id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID
    requested_by: uuid.UUID
    encrypted_url: bytes
    canonical_url: str
    query_hmac: str | None
    lease_token: uuid.UUID
    attempt: int


@dataclass(frozen=True, slots=True)
class StagedSource:
    quarantine_key: str
    source_key: str
    content_type: str
    size_bytes: int
    sha256: str
    antivirus_status: str
    extension: str


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _stream_sha256(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def url_fetch_advisory_lock_key(task_id: uuid.UUID) -> int:
    digest = hashlib.sha256(b"akc-url-fetch-task-v1\0" + task_id.bytes).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def source_advisory_lock_key(
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    sha256: str,
) -> int:
    digest = hashlib.sha256(
        b"akc-url-source-v1\0" + tenant_id.bytes + project_id.bytes + bytes.fromhex(sha256)
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def url_fetch_claim_statement(
    *,
    now: datetime,
    dialect_name: str,
    task_id: uuid.UUID | None = None,
) -> Any:
    statement = (
        select(UrlFetchTask)
        .where(
            UrlFetchTask.status.in_(("queued", "retry", "running")),
            UrlFetchTask.available_at <= now,
            or_(
                UrlFetchTask.status.in_(("queued", "retry")),
                UrlFetchTask.lease_expires_at.is_(None),
                UrlFetchTask.lease_expires_at <= now,
            ),
        )
        .order_by(UrlFetchTask.available_at, UrlFetchTask.created_at, UrlFetchTask.id)
        .limit(1)
    )
    if task_id is not None:
        statement = statement.where(UrlFetchTask.id == task_id)
    if dialect_name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    return statement


class UrlFetchWorker:
    """Fetch, quarantine, scan, promote, and persist one URL exactly once."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        store: ObjectStore,
        codec: UrlSecretCodec,
        scanner: Scanner,
        runtime: UrlFetchRuntime,
        fetcher: Fetcher | None = None,
    ) -> None:
        if runtime.environment == "production" and engine.dialect.name != "postgresql":
            raise RuntimeError("production_url_fetch_requires_postgresql")
        self._engine = engine
        self._store = store
        self._codec = codec
        self._scanner = scanner
        self._runtime = runtime
        self._fetcher = fetcher or SecureUrlFetcher()
        self._sessions = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self._sqlite_lock = _SQLITE_WORKER_LOCKS.setdefault(
            str(engine.url),
            asyncio.Lock(),
        )
        self._stopping = False

    @property
    def stopping(self) -> bool:
        return self._stopping

    def request_stop(self) -> None:
        self._stopping = True

    def _retry_delay(self, task_id: uuid.UUID, attempt: int) -> float:
        base = float(
            min(
                self._runtime.backoff_max_seconds,
                self._runtime.backoff_base_seconds * (2 ** max(0, attempt - 1)),
            )
        )
        if self._runtime.backoff_jitter_ratio == 0:
            return base
        digest = hashlib.sha256(task_id.bytes + attempt.to_bytes(4, "big")).digest()
        fraction = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
        multiplier = 1 + (((fraction * 2) - 1) * self._runtime.backoff_jitter_ratio)
        return max(0.1, base * multiplier)

    async def _release_advisory_lock(
        self,
        connection: AsyncConnection,
        lock_key: int,
    ) -> None:
        try:
            released = bool(
                await connection.scalar(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            )
            if not released:
                raise RuntimeError("url_fetch_advisory_unlock_failed")
        except BaseException:
            await connection.invalidate()
            raise

    async def _claim(
        self,
        connection: AsyncConnection,
        *,
        task_id: uuid.UUID | None,
    ) -> tuple[UrlFetchClaim | None, int | None]:
        now = utcnow()
        async with AsyncSession(
            bind=connection,
            expire_on_commit=False,
            autoflush=False,
        ) as session:
            task = await session.scalar(
                url_fetch_claim_statement(
                    now=now,
                    dialect_name=connection.dialect.name,
                    task_id=task_id,
                )
            )
            if task is None:
                await session.commit()
                return None, None
            if task.attempt_count >= task.max_attempts:
                await self._terminal_without_claim(
                    session,
                    task=task,
                    code="URL_FETCH_INTERNAL_ERROR",
                    dead_letter=True,
                    now=now,
                )
                await session.commit()
                record_url_fetch_attempt("dead_letter")
                return None, None

            lock_key: int | None = None
            if connection.dialect.name == "postgresql":
                lock_key = url_fetch_advisory_lock_key(task.id)
                acquired = bool(
                    await session.scalar(
                        text("SELECT pg_try_advisory_lock(:lock_key)"),
                        {"lock_key": lock_key},
                    )
                )
                if not acquired:
                    task.available_at = now + timedelta(seconds=1)
                    await session.commit()
                    return None, None

            document = await session.scalar(
                select(Document)
                .where(
                    Document.tenant_id == task.tenant_id,
                    Document.id == task.document_id,
                )
                .with_for_update()
            )
            project = await session.scalar(
                select(Project).where(
                    Project.tenant_id == task.tenant_id,
                    Project.id == task.project_id,
                )
            )
            if (
                document is None
                or project is None
                or document.deletion_requested_at is not None
                or project.deletion_requested_at is not None
            ):
                await self._terminal_without_claim(
                    session,
                    task=task,
                    code="URL_FETCH_TARGET_DELETED",
                    dead_letter=False,
                    cancelled=True,
                    now=now,
                )
                await session.commit()
                if lock_key is not None:
                    await self._release_advisory_lock(connection, lock_key)
                record_url_fetch_attempt("cancelled")
                return None, None

            token = uuid.uuid4()
            attempt = task.attempt_count + 1
            lease_until = now + timedelta(seconds=self._runtime.lease_seconds)
            task.status = "running"
            task.attempt_count = attempt
            task.lease_token = token
            task.lease_expires_at = lease_until
            task.available_at = lease_until
            task.last_error_code = None
            task.started_at = task.started_at or now
            task.updated_at = now
            document.status = "URL_FETCHING"
            document.updated_at = now
            await session.commit()
            return (
                UrlFetchClaim(
                    task_id=task.id,
                    tenant_id=task.tenant_id,
                    project_id=task.project_id,
                    document_id=task.document_id,
                    requested_by=task.requested_by,
                    encrypted_url=bytes(task.encrypted_url),
                    canonical_url=task.canonical_url,
                    query_hmac=task.query_hmac,
                    lease_token=token,
                    attempt=attempt,
                ),
                lock_key,
            )

    async def _terminal_without_claim(
        self,
        session: AsyncSession,
        *,
        task: UrlFetchTask,
        code: str,
        dead_letter: bool,
        now: datetime,
        cancelled: bool = False,
    ) -> None:
        if cancelled:
            task.status = "cancelled"
            task.cancelled_at = now
        else:
            task.status = "dead_letter" if dead_letter else "failed"
            task.completed_at = now
        task.last_error_code = code
        task.lease_token = None
        task.lease_expires_at = None
        task.available_at = now
        task.updated_at = now
        document = await session.scalar(
            select(Document)
            .where(
                Document.tenant_id == task.tenant_id,
                Document.id == task.document_id,
            )
            .with_for_update()
        )
        if document is not None and document.deletion_requested_at is None:
            document.status = (
                "URL_FETCH_CANCELLED"
                if cancelled
                else ("URL_FETCH_DEAD_LETTER" if dead_letter else "URL_FETCH_FAILED")
            )
            document.updated_at = now
        track_audit_write(session)
        session.add(
            AuditEvent(
                tenant_id=task.tenant_id,
                actor_id=task.requested_by,
                action=(
                    "document.url_fetch_cancelled"
                    if cancelled
                    else (
                        "document.url_fetch_dead_lettered"
                        if dead_letter
                        else "document.url_fetch_failed"
                    )
                ),
                target_type="document",
                target_id=str(task.document_id),
                metadata_json={
                    "task_id": str(task.id),
                    "canonical_url": task.canonical_url,
                    "query_hmac": task.query_hmac,
                    "code": code,
                    "attempts": task.attempt_count,
                },
            )
        )

    async def _stage_source(
        self,
        claim: UrlFetchClaim,
        result: FetchResult,
    ) -> StagedSource:
        if (
            len(result.body) > self._runtime.max_bytes
            or hashlib.sha256(result.body).hexdigest() != result.sha256
        ):
            raise UrlAttemptError("URL_FETCH_SOURCE_MISMATCH", retryable=False)
        extension = _MIME_EXTENSIONS.get(result.content_type)
        if extension is None:
            raise UrlAttemptError("URL_FETCH_CONTENT_TYPE_FORBIDDEN", retryable=False)
        quarantine_key = (
            f"tenants/{claim.tenant_id}/projects/{claim.project_id}/"
            f"quarantine/url/{claim.task_id}/{claim.lease_token}/source.bin"
        )
        source_key = (
            f"tenants/{claim.tenant_id}/projects/{claim.project_id}/"
            f"sources/url/{claim.task_id}/{result.sha256}.{extension}"
        )
        try:
            await self._store.put_quarantine(quarantine_key, result.body)
            spool_limit = min(self._runtime.max_bytes, 8 * 1024**2)
            with tempfile.SpooledTemporaryFile(max_size=spool_limit) as stream:
                scan_stream = cast(BinaryIO, stream)
                await self._store.download_quarantine(quarantine_key, scan_stream)
                scan_stream.seek(0, 2)
                stored_size = scan_stream.tell()
                scan_stream.seek(0)
                stored_digest = await asyncio.to_thread(_stream_sha256, scan_stream)
                scan_stream.seek(0)
                if stored_size != len(result.body) or stored_digest != result.sha256:
                    raise UrlAttemptError("URL_FETCH_SOURCE_MISMATCH", retryable=True)
                try:
                    scan = await self._scanner(scan_stream)
                except MalwareDetectedError:
                    raise UrlAttemptError(
                        "URL_FETCH_MALWARE_DETECTED",
                        retryable=False,
                    ) from None
                except MalwareScanError:
                    raise UrlAttemptError(
                        "URL_FETCH_ANTIVIRUS_UNAVAILABLE",
                        retryable=True,
                    ) from None
                antivirus_status = scan.status
                if antivirus_status not in {"clean", "development_static_only"} or (
                    self._runtime.environment == "production" and antivirus_status != "clean"
                ):
                    raise UrlAttemptError(
                        "URL_FETCH_ANTIVIRUS_UNAVAILABLE",
                        retryable=True,
                    )
            await self._store.promote_source(quarantine_key, source_key)
        except asyncio.CancelledError:
            await self._delete_best_effort("quarantine", quarantine_key)
            await self._delete_best_effort("source", source_key)
            raise
        except UrlAttemptError:
            await self._delete_best_effort("quarantine", quarantine_key)
            await self._delete_best_effort("source", source_key)
            raise
        except Exception:
            await self._delete_best_effort("quarantine", quarantine_key)
            await self._delete_best_effort("source", source_key)
            # Never persist or log exception text because provider/storage
            # errors may echo the secret URL.
            raise UrlAttemptError("URL_FETCH_STORAGE_ERROR", retryable=True) from None
        return StagedSource(
            quarantine_key=quarantine_key,
            source_key=source_key,
            content_type=result.content_type,
            size_bytes=len(result.body),
            sha256=result.sha256,
            antivirus_status=antivirus_status,
            extension=extension,
        )

    async def _delete_best_effort(self, bucket: str, object_key: str) -> None:
        try:
            await self._store.delete(bucket, object_key)
        except Exception:
            logger.error(
                "URL ingestion object cleanup failed",
                extra={"bucket": bucket},
            )

    async def _persist_success(
        self,
        connection: AsyncConnection,
        *,
        claim: UrlFetchClaim,
        staged: StagedSource,
    ) -> bool:
        """Persist the fenced result and return whether its source object is retained."""

        now = utcnow()
        async with (
            AsyncSession(
                bind=connection,
                expire_on_commit=False,
                autoflush=False,
            ) as session,
            session.begin(),
        ):
            task = await session.scalar(
                select(UrlFetchTask)
                .where(
                    UrlFetchTask.id == claim.task_id,
                    UrlFetchTask.tenant_id == claim.tenant_id,
                )
                .with_for_update()
            )
            if (
                task is None
                or task.status != "running"
                or task.lease_token != claim.lease_token
                or _aware(task.lease_expires_at or now) < now
            ):
                raise StaleUrlFetchLease
            document = await session.scalar(
                select(Document)
                .where(
                    Document.id == claim.document_id,
                    Document.tenant_id == claim.tenant_id,
                )
                .with_for_update()
            )
            project = await session.scalar(
                select(Project).where(
                    Project.id == claim.project_id,
                    Project.tenant_id == claim.tenant_id,
                )
            )
            if (
                document is None
                or project is None
                or document.deletion_requested_at is not None
                or project.deletion_requested_at is not None
            ):
                raise UrlAttemptError("URL_FETCH_TARGET_DELETED", retryable=False)
            if connection.dialect.name == "postgresql":
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {
                        "lock_key": source_advisory_lock_key(
                            claim.tenant_id,
                            claim.project_id,
                            staged.sha256,
                        )
                    },
                )
            source = await session.scalar(
                select(SourceFile).where(
                    SourceFile.tenant_id == claim.tenant_id,
                    SourceFile.project_id == claim.project_id,
                    SourceFile.sha256 == staged.sha256,
                )
            )
            retain_promoted_source = source is None
            if source is None:
                upload = UploadSession(
                    tenant_id=claim.tenant_id,
                    project_id=claim.project_id,
                    document_id=claim.document_id,
                    document_version=document.active_version,
                    created_by=claim.requested_by,
                    original_filename=f"url-source-{claim.task_id}.{staged.extension}",
                    safe_filename=f"url-source-{claim.task_id}.{staged.extension}",
                    expected_mime=staged.content_type,
                    expected_size=staged.size_bytes,
                    expected_sha256=staged.sha256,
                    object_key=staged.quarantine_key,
                    upload_mode="single",
                    status="completed",
                    expires_at=now,
                    completed_at=now,
                )
                session.add(upload)
                await session.flush()
                source = SourceFile(
                    tenant_id=claim.tenant_id,
                    project_id=claim.project_id,
                    upload_id=upload.id,
                    original_filename=upload.original_filename,
                    safe_filename=upload.safe_filename,
                    mime_type=staged.content_type,
                    size_bytes=staged.size_bytes,
                    sha256=staged.sha256,
                    storage_key=staged.source_key,
                    antivirus_status=staged.antivirus_status,
                    uploaded_by=claim.requested_by,
                )
                session.add(source)
                await session.flush()
            document.source_file_id = source.id
            document.document_type = staged.extension
            document.status = "SECURITY_VERIFIED"
            document.updated_at = now
            existing_version = await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.tenant_id == claim.tenant_id,
                    DocumentVersion.document_id == claim.document_id,
                    DocumentVersion.version == document.active_version,
                )
            )
            if existing_version is None:
                session.add(
                    DocumentVersion(
                        tenant_id=claim.tenant_id,
                        document_id=claim.document_id,
                        version=document.active_version,
                        source_file_id=source.id,
                        source_sha256=source.sha256,
                        source_filename=source.safe_filename,
                        source_mime_type=source.mime_type,
                        source_size_bytes=source.size_bytes,
                        cir_object_key=None,
                        cir_snapshot_sha256=None,
                        input_revision_hash=source.sha256,
                        policy_version="url-ingestion-v1",
                        model_revision="secure-url-fetcher-1",
                        prompt_revision=None,
                        normalization_revision="secure-url-normalization-1",
                        akmp_schema_version="1.0",
                        status="source_verified",
                    )
                )
            task.status = "completed"
            task.last_error_code = None
            task.content_type = staged.content_type
            task.size_bytes = staged.size_bytes
            task.source_sha256 = staged.sha256
            task.source_file_id = source.id
            task.lease_token = None
            task.lease_expires_at = None
            task.available_at = now
            task.completed_at = now
            task.updated_at = now
            track_audit_write(session)
            session.add(
                AuditEvent(
                    tenant_id=claim.tenant_id,
                    actor_id=claim.requested_by,
                    action="document.url_fetch_completed",
                    target_type="document",
                    target_id=str(claim.document_id),
                    metadata_json={
                        "task_id": str(claim.task_id),
                        "canonical_url": claim.canonical_url,
                        "query_hmac": claim.query_hmac,
                        "content_type": staged.content_type,
                        "size_bytes": staged.size_bytes,
                        "source_sha256": staged.sha256,
                        "antivirus_status": staged.antivirus_status,
                    },
                )
            )
        return retain_promoted_source

    async def _record_failure(
        self,
        connection: AsyncConnection,
        *,
        claim: UrlFetchClaim,
        error: UrlAttemptError,
    ) -> str:
        now = utcnow()
        result = "failed"
        async with (
            AsyncSession(
                bind=connection,
                expire_on_commit=False,
                autoflush=False,
            ) as session,
            session.begin(),
        ):
            task = await session.scalar(
                select(UrlFetchTask)
                .where(
                    UrlFetchTask.id == claim.task_id,
                    UrlFetchTask.tenant_id == claim.tenant_id,
                )
                .with_for_update()
            )
            if task is None or task.status != "running" or task.lease_token != claim.lease_token:
                raise StaleUrlFetchLease
            document = await session.scalar(
                select(Document)
                .where(
                    Document.tenant_id == claim.tenant_id,
                    Document.id == claim.document_id,
                )
                .with_for_update()
            )
            project = await session.scalar(
                select(Project).where(
                    Project.tenant_id == claim.tenant_id,
                    Project.id == claim.project_id,
                )
            )
            target_deleted = (
                document is None
                or project is None
                or document.deletion_requested_at is not None
                or project.deletion_requested_at is not None
            )
            if target_deleted or error.code == "URL_FETCH_CANCELLED":
                task.status = "cancelled"
                task.cancelled_at = now
                task.completed_at = None
                result = "cancelled"
            elif error.retryable and task.attempt_count < task.max_attempts:
                available = now + timedelta(seconds=self._retry_delay(task.id, task.attempt_count))
                task.status = "retry"
                task.available_at = available
                result = "retry"
                if document is not None:
                    document.status = "URL_FETCH_QUEUED"
                    document.updated_at = now
            else:
                dead_letter = error.retryable
                task.status = "dead_letter" if dead_letter else "failed"
                task.completed_at = now
                result = "dead_letter" if dead_letter else "failed"
                if document is not None and document.deletion_requested_at is None:
                    document.status = "URL_FETCH_DEAD_LETTER" if dead_letter else "URL_FETCH_FAILED"
                    document.updated_at = now
            task.last_error_code = "URL_FETCH_TARGET_DELETED" if target_deleted else error.code
            task.lease_token = None
            task.lease_expires_at = None
            task.updated_at = now
            track_audit_write(session)
            session.add(
                AuditEvent(
                    tenant_id=claim.tenant_id,
                    actor_id=claim.requested_by,
                    action=f"document.url_fetch_{result}",
                    target_type="document",
                    target_id=str(claim.document_id),
                    metadata_json={
                        "task_id": str(claim.task_id),
                        "canonical_url": claim.canonical_url,
                        "query_hmac": claim.query_hmac,
                        "code": task.last_error_code,
                        "attempt": task.attempt_count,
                    },
                )
            )
        return result

    async def _execute_claim(
        self,
        connection: AsyncConnection,
        claim: UrlFetchClaim,
    ) -> None:
        started = time.monotonic()
        staged: StagedSource | None = None
        source_retained = False
        try:
            url = self._codec.reveal(claim.encrypted_url)
            try:
                result = await asyncio.to_thread(self._fetcher.fetch, url)
            except UrlFetchError as exc:
                raise UrlAttemptError(exc.code, retryable=exc.retryable) from None
            staged = await self._stage_source(claim, result)
            source_retained = await self._persist_success(
                connection,
                claim=claim,
                staged=staged,
            )
            if not source_retained:
                await self._delete_best_effort("source", staged.source_key)
            record_url_fetch_attempt("completed")
        except asyncio.CancelledError:
            if staged is not None and not source_retained:
                await self._delete_best_effort("quarantine", staged.quarantine_key)
                await self._delete_best_effort("source", staged.source_key)
            raise
        except StaleUrlFetchLease:
            if staged is not None:
                await self._delete_best_effort("quarantine", staged.quarantine_key)
                await self._delete_best_effort("source", staged.source_key)
            record_url_fetch_attempt("stale")
        except UrlAttemptError as exc:
            if staged is not None and not source_retained:
                await self._delete_best_effort("quarantine", staged.quarantine_key)
                await self._delete_best_effort("source", staged.source_key)
            try:
                outcome = await self._record_failure(
                    connection,
                    claim=claim,
                    error=exc,
                )
            except StaleUrlFetchLease:
                record_url_fetch_attempt("stale")
            else:
                record_url_fetch_attempt(outcome)
        except Exception:
            if staged is not None and not source_retained:
                await self._delete_best_effort("quarantine", staged.quarantine_key)
                await self._delete_best_effort("source", staged.source_key)
            logger.error(
                "URL ingestion attempt failed",
                extra={"task_id": str(claim.task_id), "attempt": claim.attempt},
            )
            try:
                outcome = await self._record_failure(
                    connection,
                    claim=claim,
                    error=UrlAttemptError(
                        "URL_FETCH_INTERNAL_ERROR",
                        retryable=True,
                    ),
                )
            except StaleUrlFetchLease:
                record_url_fetch_attempt("stale")
            else:
                record_url_fetch_attempt(outcome)
        finally:
            URL_FETCH_DURATION.observe(max(0.0, time.monotonic() - started))

    async def _run_once_on_connection(
        self,
        *,
        task_id: uuid.UUID | None,
    ) -> bool:
        async with self._engine.connect() as connection:
            claim: UrlFetchClaim | None = None
            lock_key: int | None = None
            try:
                claim, lock_key = await self._claim(connection, task_id=task_id)
                if claim is None:
                    return False
                # The claim transaction has committed. HTTP, quarantine IO, and
                # ClamAV all happen with no open database transaction.
                await self._execute_claim(connection, claim)
                return True
            finally:
                if lock_key is not None:
                    await self._release_advisory_lock(connection, lock_key)

    async def run_once(self, *, task_id: uuid.UUID | None = None) -> bool:
        if self._engine.dialect.name == "sqlite":
            async with self._sqlite_lock:
                return await self._run_once_on_connection(task_id=task_id)
        return await self._run_once_on_connection(task_id=task_id)

    async def refresh_metrics(self) -> None:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(UrlFetchTask.status, func.count(UrlFetchTask.id))
                    .where(UrlFetchTask.status.in_(("queued", "retry", "running")))
                    .group_by(UrlFetchTask.status)
                )
            ).all()
            dead = await session.scalar(
                select(func.count(UrlFetchTask.id)).where(UrlFetchTask.status == "dead_letter")
            )
        counts = {str(status): int(count) for status, count in rows}
        for status in ("queued", "retry", "running"):
            URL_FETCH_QUEUE_DEPTH.labels(status=status).set(counts.get(status, 0))
        URL_FETCH_DLQ.set(int(dead or 0))

    async def run(self) -> None:
        while not self._stopping:
            processed = await self.run_once()
            await self.refresh_metrics()
            if not processed and not self._stopping:
                await asyncio.sleep(self._runtime.poll_seconds)
