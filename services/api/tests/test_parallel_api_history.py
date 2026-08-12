"""History-isolation contracts for the v6 customer snapshot."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from akc_api.database import Database
from akc_api.models import (
    Collection,
    CreditLedger,
    Document,
    Membership,
    ProcessingJob,
    Project,
    Tenant,
    User,
    utcnow,
)
from akc_api.parallel_api import get_parallel_document_snapshot
from akc_api.parallel_models import (
    AcceptedBlock,
    AcceptedBlockInvalidation,
    ArbitrationDecision,
    AttemptValidation,
    ParallelParseAttempt,
    ParallelParseShard,
    RecoveryTask,
)
from akc_api.security import Principal
from akc_api.settings import Settings
from fastapi import HTTPException

_SHA = "a" * 64


def _shard(
    ids: dict[str, Any],
    *,
    job_id: uuid.UUID,
    version_id: str,
    tag: str,
    status: str,
) -> ParallelParseShard:
    return ParallelParseShard(
        tenant_id=ids["tenant_id"],
        collection_id=ids["collection_id"],
        document_id=ids["document_id"],
        processing_job_id=job_id,
        document_version_id=version_id,
        parent_shard_id=None,
        shard_key=f"{tag}-shard",
        shard_kind="page",
        ordinal=0,
        page_start=1,
        page_end=1,
        region={},
        context={},
        overlap={},
        ownership={},
        route_class="text",
        priority=50,
        size_units=1,
        plan_version=f"{tag}-plan",
        input_sha256=_SHA,
        status=status,
        dispatch_idempotency_key=f"{tag}-dispatch",
    )


def _attempt(
    ids: dict[str, Any],
    *,
    shard_id: uuid.UUID,
    tag: str,
    state: str,
    billing_disposition: str,
    gpu_milliseconds: int,
    cost_usd: Decimal,
) -> ParallelParseAttempt:
    return ParallelParseAttempt(
        tenant_id=ids["tenant_id"],
        shard_id=shard_id,
        parent_attempt_id=None,
        attempt_number=1,
        attempt_kind="primary",
        state=state,
        pool_key=f"{tag}-pool",
        worker_id=f"{tag}-worker",
        model_id=f"{tag}-model",
        model_revision="revision-1",
        runtime_identity="runtime-1",
        route_policy_version="route-v6",
        idempotency_key=f"{tag}-attempt",
        request_sha256=_SHA,
        output_summary={},
        billing_disposition=billing_disposition,
        gpu_milliseconds=gpu_milliseconds,
        cost_usd=cost_usd,
    )


@pytest_asyncio.fixture
async def history_db(tmp_path: Path) -> AsyncIterator[tuple[Database, dict[str, Any]]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'history.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
    )
    database = Database(settings)
    await database.create_schema()
    async with database.sessions() as session:
        tenant = Tenant(slug="parallel-history", name="Parallel History")
        user = User(
            email="parallel-history@example.com",
            password_hash="inert-test-hash",  # noqa: S106
            display_name="History Owner",
            email_verified_at=utcnow(),
        )
        session.add_all([tenant, user])
        await session.flush()
        session.add(Membership(tenant_id=tenant.id, user_id=user.id, role="owner"))
        project = Project(
            tenant_id=tenant.id,
            name="History Project",
            description=None,
            created_by=user.id,
        )
        session.add(project)
        await session.flush()
        collection = Collection(
            tenant_id=tenant.id,
            project_id=project.id,
            name="History Collection",
            description=None,
            status="PROCESSING",
            created_by=user.id,
        )
        document = Document(
            tenant_id=tenant.id,
            project_id=project.id,
            source_file_id=None,
            title="Versioned parallel document",
            document_type="pdf",
            language_codes=["ko"],
            page_count=3,
            status="PREFLIGHTED",
        )
        session.add_all([collection, document])
        await session.flush()
        old_job = ProcessingJob(
            tenant_id=tenant.id,
            project_id=project.id,
            document_id=document.id,
            job_type="parallel_v6",
            status="completed",
            created_at=utcnow() - timedelta(hours=1),
            completed_at=utcnow() - timedelta(minutes=50),
        )
        new_job = ProcessingJob(
            tenant_id=tenant.id,
            project_id=project.id,
            document_id=document.id,
            job_type="parallel_v6",
            status="running",
            created_at=utcnow(),
            started_at=utcnow(),
        )
        session.add_all([old_job, new_job])
        await session.flush()
        ids: dict[str, Any] = {
            "tenant_id": tenant.id,
            "user_id": user.id,
            "project_id": project.id,
            "collection_id": collection.id,
            "document_id": document.id,
            "old_job_id": old_job.id,
            "new_job_id": new_job.id,
            "old_version": "document-version-1",
            "new_version": "document-version-2",
        }
        old_shard = _shard(
            ids,
            job_id=old_job.id,
            version_id=ids["old_version"],
            tag="old",
            status="QUARANTINED",
        )
        new_shard = _shard(
            ids,
            job_id=new_job.id,
            version_id=ids["new_version"],
            tag="new",
            status="ACCEPTED",
        )
        session.add_all([old_shard, new_shard])
        await session.flush()
        old_attempt = _attempt(
            ids,
            shard_id=old_shard.id,
            tag="old",
            state="QUARANTINED",
            billing_disposition="refunded",
            gpu_milliseconds=9_000,
            cost_usd=Decimal("9"),
        )
        new_attempt = _attempt(
            ids,
            shard_id=new_shard.id,
            tag="new",
            state="ACCEPTED",
            billing_disposition="accepted_billable",
            gpu_milliseconds=2_000,
            cost_usd=Decimal("2"),
        )
        session.add_all([old_attempt, new_attempt])
        await session.flush()
        session.add_all(
            [
                AttemptValidation(
                    tenant_id=tenant.id,
                    attempt_id=old_attempt.id,
                    level=6,
                    validator_key="old-validator",
                    validator_revision="v1",
                    status="failed",
                    hard_fail=True,
                    reason_codes=["old-only-failure"],
                    findings=[],
                    evidence={},
                    evidence_sha256=_SHA,
                ),
                AttemptValidation(
                    tenant_id=tenant.id,
                    attempt_id=new_attempt.id,
                    level=6,
                    validator_key="new-validator",
                    validator_revision="v2",
                    status="passed",
                    hard_fail=False,
                    reason_codes=[],
                    findings=[],
                    evidence={},
                    evidence_sha256=_SHA,
                ),
            ]
        )
        old_recovery = RecoveryTask(
            tenant_id=tenant.id,
            document_id=document.id,
            shard_id=old_shard.id,
            source_attempt_id=old_attempt.id,
            recovery_level="page",
            reason_code="old-only-recovery",
            target={},
            preprocessing_variants=[],
            route_candidates=[],
            state="REQUESTED",
            idempotency_key="old-recovery",
        )
        old_arbitration = ArbitrationDecision(
            tenant_id=tenant.id,
            document_id=document.id,
            shard_id=old_shard.id,
            decision_key="old-arbitration",
            logical_unit_key="old-unit",
            logical_unit_sha256=_SHA,
            candidate_attempt_ids=[str(old_attempt.id)],
            excluded_attempt_ids=[],
            selected_attempt_id=old_attempt.id,
            decision="selected",
            authority_tier="native",
            reason_codes=[],
            evidence={},
            evidence_sha256=_SHA,
            policy_version="v6",
            priced_credit_amount=Decimal("9"),
        )
        new_arbitration = ArbitrationDecision(
            tenant_id=tenant.id,
            document_id=document.id,
            shard_id=new_shard.id,
            decision_key="new-arbitration",
            logical_unit_key="new-unit",
            logical_unit_sha256=_SHA,
            candidate_attempt_ids=[str(new_attempt.id)],
            excluded_attempt_ids=[],
            selected_attempt_id=new_attempt.id,
            decision="selected",
            authority_tier="native",
            reason_codes=[],
            evidence={},
            evidence_sha256=_SHA,
            policy_version="v6",
            priced_credit_amount=Decimal("2"),
        )
        session.add_all([old_recovery, old_arbitration, new_arbitration])
        await session.flush()
        old_consume = CreditLedger(
            tenant_id=tenant.id,
            job_id=old_job.id,
            operation_key="old-consume",
            entry_type="consume",
            credits=Decimal("9"),
            balance_after=Decimal("91"),
            reserved_after=Decimal("0"),
            metadata_json={},
        )
        old_refund = CreditLedger(
            tenant_id=tenant.id,
            job_id=old_job.id,
            operation_key="old-refund",
            entry_type="refund",
            credits=Decimal("9"),
            balance_after=Decimal("100"),
            reserved_after=Decimal("0"),
            metadata_json={},
        )
        new_consume = CreditLedger(
            tenant_id=tenant.id,
            job_id=new_job.id,
            operation_key="new-consume",
            entry_type="consume",
            credits=Decimal("2"),
            balance_after=Decimal("98"),
            reserved_after=Decimal("0"),
            metadata_json={},
        )
        session.add_all([old_consume, old_refund, new_consume])
        await session.flush()
        old_block = AcceptedBlock(
            tenant_id=tenant.id,
            document_id=document.id,
            processing_job_id=old_job.id,
            document_version_id=ids["old_version"],
            generation=1,
            shard_id=old_shard.id,
            attempt_id=old_attempt.id,
            arbitration_id=old_arbitration.id,
            logical_block_key="old-unit",
            final_state="verified",
            artifact_key="old/artifact.json",
            artifact_sha256=_SHA,
            provenance={},
            acceptance_idempotency_key="old-acceptance",
            credit_settlement_key="old-consume",
            billable=True,
            credit_amount=Decimal("9"),
        )
        new_block = AcceptedBlock(
            tenant_id=tenant.id,
            document_id=document.id,
            processing_job_id=new_job.id,
            document_version_id=ids["new_version"],
            generation=1,
            shard_id=new_shard.id,
            attempt_id=new_attempt.id,
            arbitration_id=new_arbitration.id,
            logical_block_key="new-unit",
            final_state="verified",
            artifact_key="new/artifact.json",
            artifact_sha256=_SHA,
            provenance={},
            acceptance_idempotency_key="new-acceptance",
            credit_settlement_key="new-consume",
            billable=True,
            credit_amount=Decimal("2"),
        )
        session.add_all([old_block, new_block])
        await session.flush()
        session.add(
            AcceptedBlockInvalidation(
                tenant_id=tenant.id,
                document_id=document.id,
                processing_job_id=old_job.id,
                document_version_id=ids["old_version"],
                generation=1,
                shard_id=old_shard.id,
                attempt_id=old_attempt.id,
                accepted_block_id=old_block.id,
                recovery_task_id=old_recovery.id,
                action="invalidated",
                reason_code="old-worker-quarantined",
                operation_key="old-invalidation",
                operation_sha256="b" * 64,
                evidence={},
                evidence_sha256="c" * 64,
                refund_settlement_key="old-refund",
                refund_amount=Decimal("9"),
                refund_ledger_id=old_refund.id,
            )
        )
        await session.commit()
    try:
        yield database, ids
    finally:
        await database.dispose()


def _principal(ids: dict[str, Any]) -> Principal:
    return Principal(
        user_id=ids["user_id"],
        tenant_id=ids["tenant_id"],
        roles=frozenset({"owner"}),
        scopes=frozenset({"api:read"}),
        auth_type="test",
    )


@pytest.mark.asyncio
async def test_snapshot_defaults_to_running_scope_without_mixing_history(
    history_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = history_db
    async with database.sessions() as session:
        snapshot = await get_parallel_document_snapshot(
            collection_id=ids["collection_id"],
            document_id=ids["document_id"],
            session=session,
            principal=_principal(ids),
        )

    assert snapshot.processing_job_id == ids["new_job_id"]
    assert snapshot.document_version_id == ids["new_version"]
    assert snapshot.processing_job_status == "running"
    assert snapshot.shards_total == 1
    assert snapshot.attempts_total == 1
    assert snapshot.shard_state_counts == {"ACCEPTED": 1}
    assert snapshot.integrity.validation_status_counts == {"passed": 1}
    assert snapshot.integrity.hard_fail_count == 0
    assert snapshot.integrity.recovery_state_counts == {}
    assert snapshot.integrity.active_accepted_block_count == 1
    assert snapshot.integrity.invalidated_block_count == 0
    assert snapshot.usage.gpu_milliseconds == 2_000
    assert snapshot.usage.cost_usd == Decimal("2")
    assert snapshot.usage.billable_credits == Decimal("2")
    assert snapshot.usage.refunded_credits == Decimal("0")
    assert str(ids["new_job_id"]) in snapshot.event_stream_url
    assert snapshot.event_stream_url.endswith("/events/stream")


@pytest.mark.asyncio
async def test_explicit_historical_scope_is_isolated_and_wrong_scope_is_hidden(
    history_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = history_db
    async with database.sessions() as session:
        old = await get_parallel_document_snapshot(
            collection_id=ids["collection_id"],
            document_id=ids["document_id"],
            session=session,
            principal=_principal(ids),
            processing_job_id=ids["old_job_id"],
            document_version_id=ids["old_version"],
        )
        with pytest.raises(HTTPException) as wrong_version:
            await get_parallel_document_snapshot(
                collection_id=ids["collection_id"],
                document_id=ids["document_id"],
                session=session,
                principal=_principal(ids),
                processing_job_id=ids["old_job_id"],
                document_version_id=ids["new_version"],
            )
        with pytest.raises(HTTPException) as incomplete:
            await get_parallel_document_snapshot(
                collection_id=ids["collection_id"],
                document_id=ids["document_id"],
                session=session,
                principal=_principal(ids),
                processing_job_id=ids["old_job_id"],
            )

    assert old.processing_job_id == ids["old_job_id"]
    assert old.document_version_id == ids["old_version"]
    assert old.shard_state_counts == {"QUARANTINED": 1}
    assert old.integrity.validation_status_counts == {"failed": 1}
    assert old.integrity.hard_fail_count == 1
    assert old.integrity.recovery_state_counts == {"REQUESTED": 1}
    assert old.integrity.active_accepted_block_count == 0
    assert old.integrity.invalidated_block_count == 1
    assert old.usage.gpu_milliseconds == 9_000
    assert old.usage.cost_usd == Decimal("9")
    assert old.usage.billable_credits == Decimal("0")
    assert old.usage.refunded_credits == Decimal("9")
    assert wrong_version.value.status_code == 404
    assert incomplete.value.status_code == 422


@pytest.mark.asyncio
async def test_default_scope_fails_closed_for_ambiguous_active_jobs(
    history_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = history_db
    async with database.sessions() as session:
        other = ProcessingJob(
            tenant_id=ids["tenant_id"],
            project_id=ids["project_id"],
            document_id=ids["document_id"],
            job_type="parallel_v6",
            status="running",
        )
        session.add(other)
        await session.flush()
        session.add(
            _shard(
                ids,
                job_id=other.id,
                version_id="document-version-3",
                tag="other-active",
                status="PLANNED",
            )
        )
        await session.flush()
        with pytest.raises(HTTPException) as raised:
            await get_parallel_document_snapshot(
                collection_id=ids["collection_id"],
                document_id=ids["document_id"],
                session=session,
                principal=_principal(ids),
            )

    assert raised.value.status_code == 409
    detail = getattr(raised.value, "detail", None)
    assert isinstance(detail, dict)
    assert detail == {"code": "PARALLEL_SNAPSHOT_SCOPE_AMBIGUOUS"}


@pytest.mark.asyncio
async def test_new_unmaterialized_active_job_never_falls_back_to_old_snapshot(
    history_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = history_db
    async with database.sessions() as session:
        current = await session.get(ProcessingJob, ids["new_job_id"])
        assert current is not None
        current.status = "completed"
        current.completed_at = utcnow()
        pending = ProcessingJob(
            tenant_id=ids["tenant_id"],
            project_id=ids["project_id"],
            document_id=ids["document_id"],
            job_type="parallel_v6",
            status="running",
        )
        session.add(pending)
        await session.flush()
        with pytest.raises(HTTPException) as raised:
            await get_parallel_document_snapshot(
                collection_id=ids["collection_id"],
                document_id=ids["document_id"],
                session=session,
                principal=_principal(ids),
            )

    assert raised.value.status_code == 409
    detail = getattr(raised.value, "detail", None)
    assert isinstance(detail, dict)
    assert detail == {"code": "PARALLEL_SNAPSHOT_SCOPE_NOT_READY"}
