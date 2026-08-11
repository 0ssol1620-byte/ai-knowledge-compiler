"""Durability, concurrency, and cancellation evidence for the deletion worker."""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import pytest_asyncio
from akc_api import deletions as deletion_domain
from akc_api.database import Database
from akc_api.deletions import create_deletion_request, process_deletion_request
from akc_api.models import (
    AnalysisTask,
    Block,
    CreditAccount,
    CreditLedger,
    DeletionAttempt,
    DeletionObject,
    DeletionReceipt,
    DeletionRequest,
    Document,
    DocumentVersion,
    Export,
    KnowledgeNote,
    OutboxEvent,
    Page,
    ProcessingJob,
    Project,
    SourceFile,
    Tenant,
    UploadSession,
    User,
    utcnow,
)
from akc_api.services import credit_entry, run_compile_job
from akc_api.settings import Settings
from akc_api.storage import LocalObjectStore, S3ObjectStore
from akc_scheduler.database import (
    _POSTGRES_DELETION_CAPABILITY_QUERY,
    SchedulerDatabasePrivilegeError,
    verify_deletion_database,
)
from akc_scheduler.deletions import (
    DeletionWorker,
    deletion_claim_statement,
    retention_claim_statement,
)
from akc_scheduler.settings import SchedulerSettings
from akc_security.tenant_context import TenantContextMismatch, TenantContextMissing
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite


@dataclass(slots=True)
class Harness:
    database: Database
    settings: SchedulerSettings
    store: LocalObjectStore


@dataclass(frozen=True, slots=True)
class Seed:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID | None
    job_id: uuid.UUID | None
    request_id: uuid.UUID | None
    object_keys: tuple[tuple[str, str], ...]


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class FakeMappingResult:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row

    def mappings(self) -> FakeMappingResult:
        return self

    def one_or_none(self) -> dict[str, object]:
        return self.row


class FakePostgresEngine:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row

    def connect(self) -> FakePostgresEngine:
        return self

    async def __aenter__(self) -> FakePostgresEngine:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def execute(self, statement: object) -> FakeMappingResult:
        assert statement is _POSTGRES_DELETION_CAPABILITY_QUERY
        return FakeMappingResult(self.row)


class FailOnceStore:
    def __init__(
        self,
        base: LocalObjectStore,
        *,
        failure: tuple[str, str],
        always_fail: bool = False,
    ) -> None:
        self.base = base
        self.failure = failure
        self.always_fail = always_fail
        self.failed = False
        self.calls: Counter[tuple[str, str]] = Counter()

    async def delete(self, bucket: str, object_key: str) -> bool:
        identity = (bucket, object_key)
        self.calls[identity] += 1
        if identity == self.failure and (self.always_fail or not self.failed):
            self.failed = True
            raise OSError("synthetic object-store outage")
        return await self.base.delete(bucket, object_key)

    async def abort_multipart_upload(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
    ) -> None:
        await self.base.abort_multipart_upload(
            object_key=object_key,
            provider_upload_id=provider_upload_id,
        )


class GatedKnowledgeProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def compile(
        self,
        *,
        title: str,
        blocks: list[tuple[str, str]],
    ) -> list[SimpleNamespace]:
        del title
        self.started.set()
        await self.release.wait()
        return [
            SimpleNamespace(
                stable_key="compile-race-note",
                title="Compile race",
                markdown="This must roll back after the tombstone fence.",
                evidence_block_ids=[blocks[0][0]],
                content_origin="derived",
            )
        ]


class PartialVersionDeleteS3:
    """S3 double that returns one HTTP-200 partial delete failure."""

    def __init__(self) -> None:
        self.initialized: set[tuple[str, str]] = set()
        self.versions: set[tuple[str, str, str]] = set()
        self.failed = False

    def list_object_versions(self, **kwargs: Any) -> dict[str, Any]:
        identity = (str(kwargs["Bucket"]), str(kwargs["Prefix"]))
        if identity not in self.initialized:
            self.initialized.add(identity)
            self.versions.add((*identity, "version-1"))
        return {
            "IsTruncated": False,
            "Versions": [
                {"Key": key, "VersionId": version_id}
                for bucket, key, version_id in self.versions
                if (bucket, key) == identity
            ],
            "DeleteMarkers": [],
        }

    def delete_objects(self, **kwargs: Any) -> dict[str, Any]:
        bucket = str(kwargs["Bucket"])
        objects = list(kwargs["Delete"]["Objects"])
        if not self.failed:
            self.failed = True
            first = objects[0]
            return {
                "Errors": [
                    {
                        "Key": first["Key"],
                        "VersionId": first["VersionId"],
                        "Code": "AccessDenied",
                    }
                ]
            }
        for item in objects:
            self.versions.discard((bucket, str(item["Key"]), str(item["VersionId"])))
        return {"Errors": []}


def _versioned_s3_store(client: object) -> S3ObjectStore:
    store = S3ObjectStore.__new__(S3ObjectStore)
    store.settings = cast(
        Any,
        SimpleNamespace(
            s3_deletion_mode="versioned",
            s3_bucket_quarantine="quarantine",
            s3_bucket_source="source",
            s3_bucket_working="working",
            s3_bucket_derived="derived",
            s3_bucket_exports="exports",
            s3_bucket_audit="audit",
        ),
    )
    store.client = cast(Any, client)
    return store


@pytest_asyncio.fixture
async def harness(tmp_path: Path) -> AsyncIterator[Harness]:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'deletions.db').as_posix()}"
    api_settings = Settings(
        env="test",
        database_url=database_url,
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
    )
    database = Database(api_settings)
    await database.create_schema()
    worker_settings = SchedulerSettings(
        env="test",
        database_url=database_url,
        data_dir=tmp_path / "data",
        scheduler_batch_size=20,
        deletion_max_attempts=4,
        deletion_lease_seconds=30,
        deletion_attempt_timeout_seconds=10,
        deletion_backoff_base_seconds=2,
        deletion_backoff_max_seconds=30,
        deletion_backoff_jitter_ratio=0,
    )
    yield Harness(
        database=database,
        settings=worker_settings,
        store=LocalObjectStore(worker_settings),
    )
    await database.dispose()


async def _seed_document(
    harness: Harness,
    *,
    request_deletion: bool = True,
    job_status: str = "running",
) -> Seed:
    document_id = uuid.uuid4()
    quarantine_key = f"quarantine/{document_id}.pdf"
    source_key = f"source/{document_id}.pdf"
    thumbnail_key = f"derived/{document_id}/thumbnail.webp"
    cir_key = f"derived/{document_id}/cir.json.zst"
    export_key = f"exports/{document_id}.zip"

    async with harness.database.sessions.begin() as session:
        tenant = Tenant(slug=f"deletion-{uuid.uuid4()}", name="Deletion Tenant")
        user = User(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=uuid.uuid4().hex,
            display_name="Deletion Owner",
        )
        session.add_all([tenant, user])
        await session.flush()
        project = Project(
            tenant_id=tenant.id,
            name="Deletion Project",
            created_by=user.id,
        )
        session.add(project)
        await session.flush()
        upload = UploadSession(
            tenant_id=tenant.id,
            project_id=project.id,
            document_id=document_id,
            created_by=user.id,
            original_filename="evidence.pdf",
            safe_filename="evidence.pdf",
            expected_mime="application/pdf",
            expected_size=8,
            expected_sha256="1" * 64,
            object_key=quarantine_key,
            upload_mode="single",
            status="completed",
            expires_at=utcnow() + timedelta(hours=1),
            completed_at=utcnow(),
        )
        session.add(upload)
        await session.flush()
        source = SourceFile(
            tenant_id=tenant.id,
            project_id=project.id,
            upload_id=upload.id,
            original_filename="evidence.pdf",
            safe_filename="evidence.pdf",
            mime_type="application/pdf",
            size_bytes=8,
            sha256="1" * 64,
            storage_key=source_key,
            uploaded_by=user.id,
        )
        session.add(source)
        await session.flush()
        document = Document(
            id=document_id,
            tenant_id=tenant.id,
            project_id=project.id,
            source_file_id=source.id,
            title="Deletion evidence",
            document_type="pdf",
            page_count=1,
            status="COMPLETED",
        )
        session.add(document)
        await session.flush()
        page = Page(
            tenant_id=tenant.id,
            document_id=document.id,
            page_number=1,
            status="COMPLETED",
            route="native",
            thumbnail_key=thumbnail_key,
        )
        version = DocumentVersion(
            tenant_id=tenant.id,
            document_id=document.id,
            version=1,
            cir_object_key=cir_key,
            policy_version="test",
            model_revision="test",
        )
        session.add_all([page, version])
        await session.flush()
        block = Block(
            tenant_id=tenant.id,
            document_id=document.id,
            page_id=page.id,
            block_order=1,
            block_type="paragraph",
            origin="native",
            source_text="Evidence",
            normalized_text="Evidence",
            markdown="Evidence",
            confidence=1.0,
        )
        export = Export(
            tenant_id=tenant.id,
            project_id=project.id,
            document_id=document.id,
            export_type="portable",
            status="completed",
            storage_key=export_key,
            sha256="2" * 64,
            size_bytes=8,
            created_by=user.id,
            completed_at=utcnow(),
        )
        job = ProcessingJob(
            tenant_id=tenant.id,
            project_id=project.id,
            document_id=document.id,
            job_type="compile",
            status=job_status,
            requested_options={"retry_count": 0},
            cost_estimate={"reserved": "10", "expected": "6"},
            progress={"done": 0, "total": 1},
        )
        analysis_task = AnalysisTask(
            tenant_id=tenant.id,
            project_id=project.id,
            document_id=document.id,
            source_file_id=source.id,
            requested_by=user.id,
            status="running",
            attempt_count=1,
            max_attempts=3,
            lease_token=uuid.uuid4(),
            lease_expires_at=utcnow() + timedelta(minutes=5),
        )
        session.add_all([block, export, job, analysis_task])
        await session.flush()
        await credit_entry(
            session,
            tenant_id=tenant.id,
            operation_key="deletion-fixture-grant",
            entry_type="grant",
            credits=Decimal("100"),
        )
        await credit_entry(
            session,
            tenant_id=tenant.id,
            operation_key=f"job:{job.id}:attempt:0:reserve",
            entry_type="reserve",
            credits=Decimal("10"),
            job_id=job.id,
        )
        deletion_request = None
        if request_deletion:
            deletion_request, created = await create_deletion_request(
                session,
                tenant_id=tenant.id,
                actor_id=user.id,
                target_type="document",
                target_id=document.id,
            )
            assert created

    await harness.store.put_quarantine(quarantine_key, b"evidence")
    await harness.store.promote_source(quarantine_key, source_key)
    await harness.store.put_derived(thumbnail_key, b"thumbnail")
    await harness.store.put_derived(cir_key, b"cir")
    await harness.store.put_export(export_key, b"export")
    return Seed(
        tenant_id=tenant.id,
        user_id=user.id,
        project_id=project.id,
        document_id=document.id,
        job_id=job.id,
        request_id=deletion_request.id if deletion_request is not None else None,
        object_keys=(
            ("source", source_key),
            ("derived", thumbnail_key),
            ("derived", cir_key),
            ("exports", export_key),
        ),
    )


async def _seed_empty_project(harness: Harness) -> Seed:
    async with harness.database.sessions.begin() as session:
        tenant = Tenant(slug=f"empty-{uuid.uuid4()}", name="Empty Tenant")
        user = User(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=uuid.uuid4().hex,
            display_name="Deletion Owner",
        )
        session.add_all([tenant, user])
        await session.flush()
        project = Project(
            tenant_id=tenant.id,
            name="Empty Project",
            created_by=user.id,
        )
        session.add(project)
        await session.flush()
        request, created = await create_deletion_request(
            session,
            tenant_id=tenant.id,
            actor_id=user.id,
            target_type="project",
            target_id=project.id,
        )
        assert created
    return Seed(
        tenant_id=tenant.id,
        user_id=user.id,
        project_id=project.id,
        document_id=None,
        job_id=None,
        request_id=request.id,
        object_keys=(),
    )


async def test_document_deletion_includes_every_immutable_version_source(
    harness: Harness,
) -> None:
    seed = await _seed_document(harness, request_deletion=False)
    assert seed.document_id is not None
    old_quarantine_key = f"quarantine/{seed.document_id}-v1.pdf"
    old_source_key = f"source/{seed.document_id}-v1.pdf"

    async with harness.database.sessions.begin() as session:
        document = await session.get(Document, seed.document_id)
        current_version = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == seed.document_id,
                DocumentVersion.version == 1,
            )
        )
        current_source = await session.get(SourceFile, document.source_file_id)
        current_upload = await session.get(UploadSession, current_source.upload_id)
        assert (
            document is not None
            and current_version is not None
            and current_source is not None
            and current_upload is not None
        )
        old_upload = UploadSession(
            tenant_id=seed.tenant_id,
            project_id=seed.project_id,
            document_id=seed.document_id,
            document_version=1,
            created_by=seed.user_id,
            original_filename="evidence-v1.pdf",
            safe_filename="evidence-v1.pdf",
            expected_mime="application/pdf",
            expected_size=11,
            expected_sha256="3" * 64,
            object_key=old_quarantine_key,
            upload_mode="single",
            status="completed",
            expires_at=utcnow() + timedelta(hours=1),
            completed_at=utcnow(),
        )
        session.add(old_upload)
        await session.flush()
        old_source = SourceFile(
            tenant_id=seed.tenant_id,
            project_id=seed.project_id,
            upload_id=old_upload.id,
            original_filename="evidence-v1.pdf",
            safe_filename="evidence-v1.pdf",
            mime_type="application/pdf",
            size_bytes=11,
            sha256="3" * 64,
            storage_key=old_source_key,
            uploaded_by=seed.user_id,
        )
        session.add(old_source)
        await session.flush()
        current_version.source_file_id = old_source.id
        current_version.source_sha256 = old_source.sha256
        current_version.source_filename = old_source.safe_filename
        current_version.source_mime_type = old_source.mime_type
        current_version.source_size_bytes = old_source.size_bytes
        current_version.status = "archived"
        current_version.archived_at = utcnow()
        current_upload.document_version = 2
        document.active_version = 2
        session.add(
            DocumentVersion(
                tenant_id=seed.tenant_id,
                document_id=seed.document_id,
                version=2,
                source_file_id=current_source.id,
                source_sha256=current_source.sha256,
                source_filename=current_source.safe_filename,
                source_mime_type=current_source.mime_type,
                source_size_bytes=current_source.size_bytes,
                policy_version="test",
                model_revision="test",
                status="processed",
            )
        )
        request, created = await create_deletion_request(
            session,
            tenant_id=seed.tenant_id,
            actor_id=seed.user_id,
            target_type="document",
            target_id=seed.document_id,
        )
        assert created

    await harness.store.put_quarantine(old_quarantine_key, b"old-evidence")
    await harness.store.promote_source(old_quarantine_key, old_source_key)
    async with harness.database.sessions() as session:
        source_targets = set(
            await session.scalars(
                select(DeletionObject.object_key).where(
                    DeletionObject.deletion_request_id == request.id,
                    DeletionObject.bucket == "source",
                )
            )
        )
    assert source_targets == {
        old_source_key,
        f"source/{seed.document_id}.pdf",
    }

    result = await process_deletion_request(
        harness.database.sessions,
        object_store=harness.store,
        request_id=request.id,
    )
    assert result.state == "purged"
    assert not harness.store._path("source", old_source_key).exists()
    assert not harness.store._path(
        "source",
        f"source/{seed.document_id}.pdf",
    ).exists()


async def test_partial_failure_retries_preserve_manifest_cancel_work_and_release_once(
    harness: Harness,
) -> None:
    seed = await _seed_document(harness)
    assert seed.request_id is not None
    failure = seed.object_keys[0]
    store = FailOnceStore(harness.store, failure=failure)
    clock = MutableClock(utcnow() + timedelta(seconds=1))
    worker = DeletionWorker(
        engine=harness.database.engine,
        object_store=store,  # type: ignore[arg-type]
        settings=harness.settings,
        clock=clock,
    )

    async with harness.database.sessions() as session:
        request = await session.get(DeletionRequest, seed.request_id)
        job = await session.get(ProcessingJob, seed.job_id)
        account = await session.get(CreditAccount, seed.tenant_id)
        release_count = await session.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.tenant_id == seed.tenant_id,
                CreditLedger.operation_key == f"job:{seed.job_id}:deletion-release",
            )
        )
        task = await session.scalar(
            select(AnalysisTask).where(AnalysisTask.document_id == seed.document_id)
        )
        assert request is not None
        original_manifest = copy.deepcopy(request.manifest)
        original_hash = request.manifest_hash
    assert job is not None and job.status == "cancelled"
    assert account is not None and Decimal(account.reserved) == 0
    assert release_count == 1
    assert task is not None and task.status == "dead_letter"

    assert await worker.run_once()
    async with harness.database.sessions() as session:
        request = await session.get(DeletionRequest, seed.request_id)
        receipt = await session.get(DeletionReceipt, seed.request_id)
        job = await session.get(ProcessingJob, seed.job_id)
        account = await session.get(CreditAccount, seed.tenant_id)
        release_count = await session.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.tenant_id == seed.tenant_id,
                CreditLedger.operation_key == f"job:{seed.job_id}:deletion-release",
            )
        )
        pending_objects = list(
            await session.scalars(
                select(DeletionObject).where(
                    DeletionObject.deletion_request_id == seed.request_id,
                    DeletionObject.state == "pending",
                )
            )
        )
        task = await session.scalar(
            select(AnalysisTask).where(AnalysisTask.document_id == seed.document_id)
        )
    assert request is not None and request.state == "retry"
    assert request.manifest == original_manifest
    assert request.manifest_hash == original_hash
    assert receipt is None
    assert job is not None and job.status == "cancelled"
    assert account is not None and Decimal(account.reserved) == 0
    assert release_count == 1
    assert task is not None and task.status == "dead_letter"
    assert len(pending_objects) == 1
    assert pending_objects[0].object_key_hash

    clock.value += timedelta(seconds=2)
    assert await worker.run_once()
    assert not await worker.run_once()
    async with harness.database.sessions() as session:
        request = await session.get(DeletionRequest, seed.request_id)
        receipt = await session.get(DeletionReceipt, seed.request_id)
        release_count = await session.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.tenant_id == seed.tenant_id,
                CreditLedger.operation_key == f"job:{seed.job_id}:deletion-release",
            )
        )
        attempts = list(
            await session.scalars(
                select(DeletionAttempt)
                .where(DeletionAttempt.deletion_request_id == seed.request_id)
                .order_by(DeletionAttempt.attempt_number)
            )
        )
    assert request is not None and request.state == "purged"
    assert request.manifest == original_manifest
    assert request.manifest_hash == original_hash
    assert receipt is not None
    assert receipt.id == request.id
    assert receipt.manifest_hash == original_hash
    assert receipt.deleted_count == request.object_count
    assert release_count == 1
    assert [attempt.outcome for attempt in attempts] == ["retry", "purged"]
    assert store.calls[failure] == 2
    assert all(not path.is_file() for path in harness.settings.object_root.rglob("*"))


async def test_deletion_cancels_paused_processing_job_and_releases_reservation(
    harness: Harness,
) -> None:
    seed = await _seed_document(harness, job_status="paused")
    async with harness.database.sessions() as session:
        job = await session.get(ProcessingJob, seed.job_id)
        account = await session.get(CreditAccount, seed.tenant_id)
        release_count = int(
            await session.scalar(
                select(func.count(CreditLedger.id)).where(
                    CreditLedger.tenant_id == seed.tenant_id,
                    CreditLedger.operation_key == f"job:{seed.job_id}:deletion-release",
                )
            )
            or 0
        )
    assert job is not None and job.status == "cancelled"
    assert account is not None and Decimal(account.reserved) == 0
    assert release_count == 1


async def test_s3_partial_version_delete_never_issues_receipt(
    harness: Harness,
) -> None:
    seed = await _seed_document(harness)
    assert seed.request_id is not None
    client = PartialVersionDeleteS3()

    result = await process_deletion_request(
        harness.database.sessions,
        object_store=_versioned_s3_store(client),
        request_id=seed.request_id,
    )

    assert result.state == "retry"
    assert client.failed
    async with harness.database.sessions() as session:
        request = await session.get(DeletionRequest, seed.request_id)
        receipt = await session.get(DeletionReceipt, seed.request_id)
    assert request is not None and request.state == "retry"
    assert receipt is None


async def test_crash_after_remote_delete_is_recovered_after_lease_expiry(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await _seed_document(harness)
    assert seed.request_id is not None
    clock = MutableClock(utcnow() + timedelta(seconds=1))
    original_record = deletion_domain._record_object_result
    crashed = False

    async def crash_before_recording(*args: Any, **kwargs: Any) -> bool:
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("synthetic process crash")
        return await original_record(*args, **kwargs)

    monkeypatch.setattr(deletion_domain, "_record_object_result", crash_before_recording)
    with pytest.raises(RuntimeError, match="synthetic process crash"):
        await process_deletion_request(
            harness.database.sessions,
            object_store=harness.store,
            request_id=seed.request_id,
            lease_seconds=10,
            max_attempts=4,
            clock=clock,
        )
    assert any(
        not harness.store._path(bucket, object_key).exists()
        for bucket, object_key in seed.object_keys
    )

    async with harness.database.sessions() as session:
        request = await session.get(DeletionRequest, seed.request_id)
        receipt = await session.get(DeletionReceipt, seed.request_id)
    assert request is not None and request.state == "purging"
    assert receipt is None

    monkeypatch.setattr(deletion_domain, "_record_object_result", original_record)
    clock.value += timedelta(seconds=11)
    result = await process_deletion_request(
        harness.database.sessions,
        object_store=harness.store,
        request_id=seed.request_id,
        lease_seconds=10,
        max_attempts=4,
        clock=clock,
    )
    assert result.state == "purged"
    assert result.receipt is not None
    async with harness.database.sessions() as session:
        attempts = list(
            await session.scalars(
                select(DeletionAttempt)
                .where(DeletionAttempt.deletion_request_id == seed.request_id)
                .order_by(DeletionAttempt.attempt_number)
            )
        )
    assert [attempt.outcome for attempt in attempts] == ["retry", "purged"]
    assert attempts[0].error_code == "deletion_lease_expired"


async def test_max_attempts_dead_letters_without_receipt_or_database_purge(
    harness: Harness,
) -> None:
    seed = await _seed_document(harness)
    assert seed.request_id is not None
    failure = seed.object_keys[0]
    store = FailOnceStore(harness.store, failure=failure, always_fail=True)
    clock = MutableClock(utcnow() + timedelta(seconds=1))
    settings = harness.settings.model_copy(update={"deletion_max_attempts": 1})
    worker = DeletionWorker(
        engine=harness.database.engine,
        object_store=store,  # type: ignore[arg-type]
        settings=settings,
        clock=clock,
    )

    assert await worker.run_once()
    async with harness.database.sessions() as session:
        request = await session.get(DeletionRequest, seed.request_id)
        receipt = await session.get(DeletionReceipt, seed.request_id)
        document = await session.get(Document, seed.document_id)
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_type == "deletion_request",
                OutboxEvent.aggregate_id == seed.request_id,
            )
        )
    assert request is not None and request.state == "dead_letter"
    assert request.completed_at is None
    assert receipt is None
    assert document is not None and document.deletion_requested_at is not None
    assert event is not None and event.dead_lettered_at is not None


async def test_two_worker_instances_claim_one_event_and_create_one_receipt(
    harness: Harness,
) -> None:
    seed = await _seed_document(harness)
    assert seed.request_id is not None
    clock = MutableClock(utcnow() + timedelta(seconds=1))
    first = DeletionWorker(
        engine=harness.database.engine,
        object_store=harness.store,
        settings=harness.settings,
        clock=clock,
    )
    second = DeletionWorker(
        engine=harness.database.engine,
        object_store=harness.store,
        settings=harness.settings,
        clock=clock,
    )

    results = await asyncio.gather(first.run_once(), second.run_once())
    assert sorted(results) == [False, True]
    async with harness.database.sessions() as session:
        request = await session.get(DeletionRequest, seed.request_id)
        receipt_count = await session.scalar(
            select(func.count(DeletionReceipt.id)).where(DeletionReceipt.id == seed.request_id)
        )
        attempt_count = await session.scalar(
            select(func.count(DeletionAttempt.id)).where(
                DeletionAttempt.deletion_request_id == seed.request_id
            )
        )
    assert request is not None and request.state == "purged"
    assert receipt_count == 1
    assert attempt_count == 1


async def test_legacy_target_event_is_bridged_to_the_durable_manifest(
    harness: Harness,
) -> None:
    seed = await _seed_document(harness, request_deletion=False)
    assert seed.document_id is not None
    async with harness.database.sessions.begin() as session:
        session.add(
            OutboxEvent(
                tenant_id=seed.tenant_id,
                aggregate_type="document",
                aggregate_id=seed.document_id,
                event_type="deletion.retry.requested.v1",
                payload={
                    "target_type": "document",
                    "target_id": str(seed.document_id),
                    "manifest_hash": "0" * 64,
                },
            )
        )
    worker = DeletionWorker(
        engine=harness.database.engine,
        object_store=harness.store,
        settings=harness.settings,
        clock=MutableClock(utcnow() + timedelta(seconds=1)),
    )
    assert await worker.run_once()
    async with harness.database.sessions() as session:
        request = await session.scalar(
            select(DeletionRequest).where(
                DeletionRequest.tenant_id == seed.tenant_id,
                DeletionRequest.target_type == "document",
                DeletionRequest.target_id == seed.document_id,
            )
        )
    assert request is not None and request.state == "purged"
    assert await worker.run_once() is False


async def test_empty_project_reaches_terminal_receipt(
    harness: Harness,
) -> None:
    seed = await _seed_empty_project(harness)
    assert seed.request_id is not None
    result = await process_deletion_request(
        harness.database.sessions,
        object_store=harness.store,
        request_id=seed.request_id,
    )
    assert result.state == "purged"
    assert result.receipt is not None
    assert result.receipt.deleted_count == 0
    async with harness.database.sessions() as session:
        assert await session.get(Project, seed.project_id) is None


async def test_retention_sweep_is_bounded_and_duplicate_safe_across_workers(
    harness: Harness,
) -> None:
    seed = await _seed_document(harness, request_deletion=False)
    assert seed.document_id is not None
    clock = MutableClock(utcnow() + timedelta(seconds=1))
    async with harness.database.sessions.begin() as session:
        tenant = await session.get(Tenant, seed.tenant_id)
        document = await session.get(Document, seed.document_id)
        assert tenant is not None and document is not None
        tenant.data_retention_days = 7
        document.created_at = clock.value - timedelta(days=8)

    first = DeletionWorker(
        engine=harness.database.engine,
        object_store=harness.store,
        settings=harness.settings,
        clock=clock,
    )
    second = DeletionWorker(
        engine=harness.database.engine,
        object_store=harness.store,
        settings=harness.settings,
        clock=clock,
    )
    created = await asyncio.gather(
        first.run_retention_sweep(),
        second.run_retention_sweep(),
    )
    assert sorted(created) == [0, 1]
    async with harness.database.sessions() as session:
        requests = list(
            await session.scalars(
                select(DeletionRequest).where(
                    DeletionRequest.tenant_id == seed.tenant_id,
                    DeletionRequest.target_type == "document",
                    DeletionRequest.target_id == seed.document_id,
                )
            )
        )
        document = await session.get(Document, seed.document_id)
    assert len(requests) == 1
    assert document is not None and document.deletion_requested_at is not None
    assert await first.run_once()
    async with harness.database.sessions() as session:
        request = await session.get(DeletionRequest, requests[0].id)
    assert request is not None and request.state == "purged"


async def test_retention_sweep_filters_expiry_before_applying_batch_limit(
    harness: Harness,
) -> None:
    unexpired = await _seed_document(harness, request_deletion=False)
    expired = await _seed_document(harness, request_deletion=False)
    assert unexpired.document_id is not None and expired.document_id is not None
    clock = MutableClock(utcnow() + timedelta(seconds=1))
    async with harness.database.sessions.begin() as session:
        unexpired_tenant = await session.get(Tenant, unexpired.tenant_id)
        expired_tenant = await session.get(Tenant, expired.tenant_id)
        unexpired_document = await session.get(Document, unexpired.document_id)
        expired_document = await session.get(Document, expired.document_id)
        assert (
            unexpired_tenant is not None
            and expired_tenant is not None
            and unexpired_document is not None
            and expired_document is not None
        )
        unexpired_tenant.data_retention_days = 365
        unexpired_document.created_at = clock.value - timedelta(days=100)
        expired_tenant.data_retention_days = 1
        expired_document.created_at = clock.value - timedelta(days=2)

    worker = DeletionWorker(
        engine=harness.database.engine,
        object_store=harness.store,
        settings=harness.settings.model_copy(update={"scheduler_batch_size": 1}),
        clock=clock,
    )
    assert await worker.run_retention_sweep() == 1

    async with harness.database.sessions() as session:
        unexpired_request = await session.scalar(
            select(DeletionRequest).where(
                DeletionRequest.tenant_id == unexpired.tenant_id,
                DeletionRequest.target_type == "document",
                DeletionRequest.target_id == unexpired.document_id,
            )
        )
        expired_request = await session.scalar(
            select(DeletionRequest).where(
                DeletionRequest.tenant_id == expired.tenant_id,
                DeletionRequest.target_type == "document",
                DeletionRequest.target_id == expired.document_id,
            )
        )
    assert unexpired_request is None
    assert expired_request is not None


async def test_inflight_compile_cannot_consume_or_resurrect_after_tombstone(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await _seed_document(
        harness,
        request_deletion=False,
        job_status="queued",
    )
    assert seed.document_id is not None
    assert seed.job_id is not None
    provider = GatedKnowledgeProvider()
    monkeypatch.setattr(
        "akc_api.services.knowledge_provider",
        lambda _settings, _consent: provider,
    )

    async def compile_in_own_session() -> None:
        async with harness.database.sessions() as session:
            await run_compile_job(
                session=session,
                job_id=seed.job_id,
                settings=harness.database.settings,
            )

    compile_task = asyncio.create_task(compile_in_own_session())
    await asyncio.wait_for(provider.started.wait(), timeout=10)
    async with harness.database.sessions.begin() as session:
        request, created = await create_deletion_request(
            session,
            tenant_id=seed.tenant_id,
            actor_id=seed.user_id,
            target_type="document",
            target_id=seed.document_id,
        )
        assert created
        request_id = request.id
    provider.release.set()
    await asyncio.wait_for(compile_task, timeout=10)

    async with harness.database.sessions() as session:
        job = await session.get(ProcessingJob, seed.job_id)
        consume_count = await session.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.tenant_id == seed.tenant_id,
                CreditLedger.entry_type == "consume",
            )
        )
        note_count = await session.scalar(
            select(func.count(KnowledgeNote.id)).where(
                KnowledgeNote.tenant_id == seed.tenant_id,
                KnowledgeNote.project_id == seed.project_id,
            )
        )
    assert job is not None and job.status == "cancelled"
    assert consume_count == 0
    assert note_count == 0

    result = await process_deletion_request(
        harness.database.sessions,
        object_store=harness.store,
        request_id=request_id,
    )
    assert result.state == "purged"
    async with harness.database.sessions() as session:
        release_count = await session.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.tenant_id == seed.tenant_id,
                CreditLedger.operation_key == f"job:{seed.job_id}:deletion-release",
            )
        )
        consume_count = await session.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.tenant_id == seed.tenant_id,
                CreditLedger.entry_type == "consume",
            )
        )
        account = await session.get(CreditAccount, seed.tenant_id)
    assert release_count == 1
    assert consume_count == 0
    assert account is not None and Decimal(account.reserved) == 0


def test_deletion_claim_uses_skip_locked_only_on_postgresql() -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    postgres_sql = str(
        deletion_claim_statement(now=now, dialect_name="postgresql").compile(
            dialect=postgresql.dialect()
        )
    )
    sqlite_sql = str(
        deletion_claim_statement(now=now, dialect_name="sqlite").compile(dialect=sqlite.dialect())
    )
    retention_postgres = str(
        retention_claim_statement(now=now, dialect_name="postgresql", limit=10).compile(
            dialect=postgresql.dialect()
        )
    )
    retention_sqlite = str(
        retention_claim_statement(now=now, dialect_name="sqlite", limit=10).compile(
            dialect=sqlite.dialect()
        )
    )
    assert "FOR UPDATE" in postgres_sql
    assert "SKIP LOCKED" in postgres_sql
    assert "FOR UPDATE" not in sqlite_sql
    assert "FOR UPDATE" in retention_postgres
    assert "SKIP LOCKED" in retention_postgres
    assert "FOR UPDATE" not in retention_sqlite


async def test_postgres_deletion_capability_is_fail_closed_and_scope_aware() -> None:
    settings = SchedulerSettings(
        env="test",
        database_url="postgresql+asyncpg://runtime:secret@localhost/akc",
    )
    row: dict[str, object] = {
        "effective_role": settings.deletion_database_role,
        "login_role": "akc_deletion_runtime",
        "can_login": False,
        "bypass_rls": True,
        "effective_role_safe": True,
        "login_role_safe": True,
        "login_has_only_effective_role": True,
        "effective_role_has_no_memberships": True,
        "login_has_no_direct_table_acl": True,
        "application_tables_have_no_public_acl": True,
        "login_owns_no_application_table": True,
        "effective_role_owns_no_application_table": True,
        "login_is_not_database_owner": True,
        "effective_role_is_not_database_owner": True,
        "effective_role_is_not_public_schema_owner": True,
        "login_cannot_create_in_public": True,
        "schema_usage": True,
        "evidence_access": True,
        "manifest_access": True,
        "target_access": True,
        "request_update_access": True,
        "object_update_access": True,
        "outbox_update_access": True,
        "mutation_update_access": True,
        "forbidden_access_absent": True,
        "forced_rls_present": True,
    }
    capability = await verify_deletion_database(
        FakePostgresEngine(row),  # type: ignore[arg-type]
        settings,
    )
    assert capability.purpose == "deletion"
    assert capability.effective_role == "akc_deletion_worker"

    for failed_flag in (
        "manifest_access",
        "mutation_update_access",
        "forbidden_access_absent",
        "forced_rls_present",
    ):
        failed = {**row, failed_flag: False}
        with pytest.raises(
            SchedulerDatabasePrivilegeError,
            match=failed_flag,
        ):
            await verify_deletion_database(
                FakePostgresEngine(failed),  # type: ignore[arg-type]
                settings,
            )

    query = str(_POSTGRES_DELETION_CAPABILITY_QUERY)
    for required_scope in (
        "analysis_tasks",
        "deletion_attempts",
        "idempotency_records",
        "webhook_deliveries",
        "feature_flags",
    ):
        assert required_scope in query


async def test_purge_refuses_when_the_request_tenant_disagrees_with_the_claim(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A request that changes tenant mid-attempt must not delete anything.

    This is the failure the deletion path is most exposed to once BYPASSRLS is
    removed: an unbound or wrongly-bound transaction would compare
    ``tenant_id`` against the wrong value, delete zero rows, and still record a
    purge. The guard has to raise instead.
    """

    seed = await _seed_document(harness)
    assert seed.request_id is not None

    # Hand the purge a tenant that is not the claimed request's tenant.
    original_claim = deletion_domain._claim_request

    async def claim_with_foreign_tenant(
        *args: Any, **kwargs: Any
    ) -> tuple[uuid.UUID, int, uuid.UUID] | None:
        claimed = await original_claim(*args, **kwargs)
        if claimed is None:
            return None
        token, attempt, _tenant = claimed
        return token, attempt, uuid.uuid4()

    monkeypatch.setattr(deletion_domain, "_claim_request", claim_with_foreign_tenant)

    # A tenant disagreement is an integrity violation, not a retryable
    # operational failure, so it propagates instead of being recorded as a
    # retry. Loud beats a zero-row purge that looks successful.
    with pytest.raises(TenantContextMismatch):
        await process_deletion_request(
            harness.database.sessions,
            object_store=harness.store,
            request_id=seed.request_id,
        )

    async with harness.database.sessions() as session:
        request = await session.get(DeletionRequest, seed.request_id)
        receipt = await session.get(DeletionReceipt, seed.request_id)
        document = await session.get(Document, seed.document_id)
    assert request is not None and request.state != "purged"
    assert receipt is None
    assert document is not None, "a tenant mismatch must not delete domain rows"


async def test_missing_tenant_context_fails_closed_before_any_delete(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No tenant means no purge — never a silent zero-row 'success'."""

    seed = await _seed_document(harness)
    assert seed.request_id is not None
    original_claim = deletion_domain._claim_request

    async def claim_without_tenant(*args: Any, **kwargs: Any) -> Any:
        claimed = await original_claim(*args, **kwargs)
        if claimed is None:
            return None
        token, attempt, _tenant = claimed
        return token, attempt, None

    monkeypatch.setattr(deletion_domain, "_claim_request", claim_without_tenant)

    with pytest.raises(TenantContextMissing):
        await process_deletion_request(
            harness.database.sessions,
            object_store=harness.store,
            request_id=seed.request_id,
        )

    async with harness.database.sessions() as session:
        receipt = await session.get(DeletionReceipt, seed.request_id)
        document = await session.get(Document, seed.document_id)
    assert receipt is None
    assert document is not None, "a missing tenant must not delete domain rows"


def test_every_sessionmaker_site_in_the_deletion_module_binds_a_tenant() -> None:
    """Structural guard: a new unbound session here is the defect class itself.

    The audit that found this counted sessions by hand. This makes the count
    fail on its own the next time somebody adds one.
    """

    import re

    source = Path(deletion_domain.__file__).read_text(encoding="utf-8").splitlines()
    opens = [i for i, line in enumerate(source) if re.search(r"async with sessions\(\)", line)]
    contexts = [i for i, line in enumerate(source) if "enter_tenant_context(" in line]
    assert opens, "expected the deletion module to open worker sessions"
    unbound = []
    for start in opens:
        end = min([o for o in opens if o > start], default=len(source))
        if not any(start < c < end for c in contexts):
            unbound.append(start + 1)
    assert not unbound, f"session opened without a tenant context at line(s): {unbound}"
