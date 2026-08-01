"""Deterministic v6 persistence, lineage, health, and billing invariants."""

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
    ArbitrationDecision,
    AttemptValidation,
    ParallelParseAttempt,
    ParallelParseShard,
    RecoveryTask,
    SemanticHealthEvent,
)
from akc_api.parallel_runtime_store import (
    ParallelRuntimeConflict,
    accept_verified_block,
    canonical_sha256,
    create_parse_attempt,
    create_parse_shard,
    emit_parallel_event,
    record_attempt_output,
    record_attempt_validation,
    request_recovery,
    transition_parse_attempt,
    update_worker_health,
)
from akc_api.security import Principal
from akc_api.settings import Settings
from fastapi import HTTPException
from sqlalchemy import func, select

VALIDATOR_CONTEXT = {
    "cross_page_table": True,
    "required_validator_revisions": {
        "0": {"validator_key": "transport", "validator_revision": "validator-v6"},
        "1": {"validator_key": "structural", "validator_revision": "validator-v6"},
        "6": {"validator_key": "downstream", "validator_revision": "validator-v6"},
    },
}


@pytest_asyncio.fixture
async def runtime_db(tmp_path: Path) -> AsyncIterator[tuple[Database, dict[str, Any]]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'parallel.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
    )
    database = Database(settings)
    await database.create_schema()
    async with database.sessions() as session:
        tenant = Tenant(slug="parallel-test", name="Parallel Test")
        user = User(
            email="parallel@example.com",
            password_hash="not-a-secret-hash",  # noqa: S106 - inert test fixture
            display_name="Parallel Owner",
            email_verified_at=utcnow(),
        )
        session.add_all([tenant, user])
        await session.flush()
        session.add(Membership(tenant_id=tenant.id, user_id=user.id, role="owner"))
        project = Project(
            tenant_id=tenant.id,
            name="Parallel Project",
            description=None,
            created_by=user.id,
        )
        session.add(project)
        await session.flush()
        collection = Collection(
            tenant_id=tenant.id,
            project_id=project.id,
            name="Parallel Collection",
            description=None,
            status="PROCESSING",
            created_by=user.id,
        )
        document = Document(
            tenant_id=tenant.id,
            project_id=project.id,
            source_file_id=None,
            title="Parallel document",
            document_type="pdf",
            language_codes=["ko"],
            page_count=4,
            status="PREFLIGHTED",
        )
        session.add_all([collection, document])
        await session.flush()
        job = ProcessingJob(
            tenant_id=tenant.id,
            project_id=project.id,
            document_id=document.id,
            job_type="compile",
            status="running",
        )
        session.add(job)
        await session.commit()
        ids = {
            "tenant_id": tenant.id,
            "user_id": user.id,
            "project_id": project.id,
            "collection_id": collection.id,
            "document_id": document.id,
            "job_id": job.id,
            "document_version_id": f"{document.id}:v1",
        }
    try:
        yield database, ids
    finally:
        await database.dispose()


async def _shard_attempt(
    database: Database,
    ids: dict[str, Any],
    *,
    attempt_kind: str = "primary",
    suffix: str = "primary",
) -> tuple[uuid.UUID, uuid.UUID]:
    async with database.sessions() as session:
        shard, _ = await create_parse_shard(
            session,
            tenant_id=ids["tenant_id"],
            collection_id=ids["collection_id"],
            document_id=ids["document_id"],
            processing_job_id=ids["job_id"],
            document_version_id=ids["document_version_id"],
            parent_shard_id=None,
            shard_key="pages-1-2",
            shard_kind="page_group",
            ordinal=0,
            page_start=1,
            page_end=2,
            region={},
            context=VALIDATOR_CONTEXT,
            overlap={"trailing_pages": [2]},
            ownership={"page:1": "owner", "page:2": "owner"},
            route_class="cross_page_table",
            priority=90,
            size_units=2,
            plan_version="v6-test",
            input_sha256="a" * 64,
            dispatch_idempotency_key="dispatch-pages-1-2",
        )
        attempt, _ = await create_parse_attempt(
            session,
            tenant_id=ids["tenant_id"],
            shard_id=shard.id,
            attempt_kind=attempt_kind,
            pool_key="mineru-3-4-4",
            model_id="mineru-3.4.4-pipeline",
            model_revision="revision-verified",
            runtime_identity="sha256:runtime-verified",
            route_policy_version="router-v2-shadow",
            idempotency_key=f"attempt-{suffix}",
            request_sha256="b" * 64,
        )
        await session.commit()
        return shard.id, attempt.id


async def _selected_arbitration(
    session: Any,
    ids: dict[str, Any],
    *,
    shard_id: uuid.UUID,
    attempt_id: uuid.UUID,
    logical_unit_key: str,
    credit_amount: Decimal,
    suffix: str,
) -> ArbitrationDecision:
    evidence = {
        "verification_state": "authority_verified",
        "selected_attempt_id": str(attempt_id),
    }
    row = ArbitrationDecision(
        tenant_id=ids["tenant_id"],
        document_id=ids["document_id"],
        shard_id=shard_id,
        decision_key=f"arbitration-{suffix}",
        logical_unit_key=logical_unit_key,
        logical_unit_sha256=canonical_sha256({"logical_unit_key": logical_unit_key}),
        candidate_attempt_ids=[str(attempt_id)],
        excluded_attempt_ids=[],
        selected_attempt_id=attempt_id,
        decision="selected",
        authority_tier="exact_authority",
        reason_codes=["authority_exact"],
        evidence=evidence,
        evidence_sha256=canonical_sha256(evidence),
        policy_version="arbitration-v6",
        priced_credit_amount=credit_amount,
    )
    session.add(row)
    await session.flush()
    return row


def _arbitration_key(namespace: str, arbitration_id: uuid.UUID) -> str:
    return f"{namespace}:{canonical_sha256({'key': str(arbitration_id), 'parts': ()})}"


@pytest.mark.asyncio
async def test_shard_and_attempt_idempotency_are_content_bound(
    runtime_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = runtime_db
    shard_id, attempt_id = await _shard_attempt(database, ids)
    async with database.sessions() as session:
        replayed, replay = await create_parse_shard(
            session,
            tenant_id=ids["tenant_id"],
            collection_id=ids["collection_id"],
            document_id=ids["document_id"],
            processing_job_id=ids["job_id"],
            document_version_id=ids["document_version_id"],
            parent_shard_id=None,
            shard_key="pages-1-2",
            shard_kind="page_group",
            ordinal=0,
            page_start=1,
            page_end=2,
            region={},
            context=VALIDATOR_CONTEXT,
            overlap={"trailing_pages": [2]},
            ownership={"page:1": "owner", "page:2": "owner"},
            route_class="cross_page_table",
            priority=90,
            size_units=2,
            plan_version="v6-test",
            input_sha256="a" * 64,
            dispatch_idempotency_key="dispatch-pages-1-2",
        )
        assert replay is True
        assert replayed.id == shard_id
        replayed_attempt, attempt_replay = await create_parse_attempt(
            session,
            tenant_id=ids["tenant_id"],
            shard_id=shard_id,
            attempt_kind="primary",
            pool_key="mineru-3-4-4",
            model_id="mineru-3.4.4-pipeline",
            model_revision="revision-verified",
            runtime_identity="sha256:runtime-verified",
            route_policy_version="router-v2-shadow",
            idempotency_key="attempt-primary",
            request_sha256="b" * 64,
        )
        assert attempt_replay is True
        assert replayed_attempt.id == attempt_id
        with pytest.raises(ParallelRuntimeConflict, match="different input"):
            await create_parse_shard(
                session,
                tenant_id=ids["tenant_id"],
                collection_id=ids["collection_id"],
                document_id=ids["document_id"],
                processing_job_id=ids["job_id"],
                document_version_id=ids["document_version_id"],
                parent_shard_id=None,
                shard_key="pages-1-3",
                shard_kind="page_group",
                ordinal=0,
                page_start=1,
                page_end=3,
                region={},
                context=VALIDATOR_CONTEXT,
                overlap={"trailing_pages": [2]},
                ownership={"page:1": "owner", "page:2": "owner"},
                route_class="cross_page_table",
                priority=90,
                size_units=3,
                plan_version="v6-test",
                input_sha256="a" * 64,
                dispatch_idempotency_key="dispatch-pages-1-2",
            )
        with pytest.raises(ParallelRuntimeConflict, match="different input"):
            await create_parse_attempt(
                session,
                tenant_id=ids["tenant_id"],
                shard_id=shard_id,
                attempt_kind="primary",
                pool_key="mineru-3-4-4",
                model_id="mineru-3.4.4-pipeline",
                model_revision="revision-verified",
                runtime_identity="sha256:runtime-verified",
                route_policy_version="router-v2-shadow",
                idempotency_key="attempt-primary",
                request_sha256="b" * 64,
                provider_invocation_id=uuid.uuid4(),
            )


@pytest.mark.asyncio
async def test_validated_first_winner_is_immutable_and_billed_once(
    runtime_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = runtime_db
    shard_id, attempt_id = await _shard_attempt(database, ids)
    async with database.sessions() as session:
        attempt = await session.get(ParallelParseAttempt, attempt_id)
        assert attempt is not None
        await transition_parse_attempt(session, attempt, "QUEUED")
        await transition_parse_attempt(session, attempt, "RUNNING")
        await record_attempt_output(
            session,
            attempt,
            artifact_key="tenant-safe/output.json",
            output_sha256="c" * 64,
            output_summary={"page_count": 2, "row_count": 18},
            gpu_milliseconds=2_500,
            cost_usd=Decimal("0.0125"),
        )
        with pytest.raises(ParallelRuntimeConflict, match="output is immutable"):
            await record_attempt_output(
                session,
                attempt,
                artifact_key="tenant-safe/output.json",
                output_sha256="c" * 64,
                output_summary={"page_count": 2, "row_count": 18},
                gpu_milliseconds=2_501,
                cost_usd=Decimal("0.0125"),
            )
        for level, validator in (
            (0, "transport"),
            (1, "structural"),
            (3, "authority"),
            (6, "downstream"),
        ):
            row, replay = await record_attempt_validation(
                session,
                attempt=attempt,
                level=level,
                validator_key=validator,
                validator_revision="validator-v6",
                status="passed",
                score=Decimal("1"),
                hard_fail=False,
                reason_codes=[],
                findings=[],
                evidence={"validator": validator, "passed": True},
            )
            assert replay is False
            assert row.evidence_sha256
        with pytest.raises(ParallelRuntimeConflict, match="different evidence"):
            await record_attempt_validation(
                session,
                attempt=attempt,
                level=0,
                validator_key="transport",
                validator_revision="validator-v6",
                status="passed",
                score=Decimal("0.99"),
                hard_fail=False,
                reason_codes=[],
                findings=[],
                evidence={"validator": "transport", "passed": True},
            )
        first_arbitration = await _selected_arbitration(
            session,
            ids,
            shard_id=shard_id,
            attempt_id=attempt.id,
            logical_unit_key="table-1",
            credit_amount=Decimal("1.25"),
            suffix="table-1",
        )
        with pytest.raises(ParallelRuntimeConflict, match="server-derived"):
            await accept_verified_block(
                session,
                attempt=attempt,
                document_id=ids["document_id"],
                processing_job_id=ids["job_id"],
                document_version_id=ids["document_version_id"],
                arbitration_id=first_arbitration.id,
                logical_block_key="table-1",
                final_state="authority_verified",
                artifact_key="tenant-safe/block.json",
                artifact_sha256="c" * 64,
                provenance={"attempt_id": str(attempt.id), "authority": "native"},
                acceptance_idempotency_key="caller-selected-acceptance-key",
                credit_settlement_key="caller-selected-credit-key",
                credit_amount=Decimal("1.25"),
            )
        block, replay = await accept_verified_block(
            session,
            attempt=attempt,
            document_id=ids["document_id"],
            processing_job_id=ids["job_id"],
            document_version_id=ids["document_version_id"],
            arbitration_id=first_arbitration.id,
            logical_block_key="table-1",
            final_state="authority_verified",
            artifact_key="tenant-safe/block.json",
            artifact_sha256="c" * 64,
            provenance={"attempt_id": str(attempt.id), "authority": "native"},
            acceptance_idempotency_key=_arbitration_key("accept", first_arbitration.id),
            credit_settlement_key=_arbitration_key("credit", first_arbitration.id),
            credit_amount=Decimal("1.25"),
        )
        assert replay is False
        assert block.billable is True
        assert attempt.billing_disposition == "accepted_billable"
        second_arbitration = await _selected_arbitration(
            session,
            ids,
            shard_id=shard_id,
            attempt_id=attempt.id,
            logical_unit_key="paragraph-2",
            credit_amount=Decimal("0.25"),
            suffix="paragraph-2",
        )
        second_block, second_replay = await accept_verified_block(
            session,
            attempt=attempt,
            document_id=ids["document_id"],
            processing_job_id=ids["job_id"],
            document_version_id=ids["document_version_id"],
            arbitration_id=second_arbitration.id,
            logical_block_key="paragraph-2",
            final_state="verified",
            artifact_key="tenant-safe/block-2.json",
            artifact_sha256="c" * 64,
            provenance={"attempt_id": str(attempt.id), "authority": "pixel_ocr"},
            acceptance_idempotency_key=_arbitration_key("accept", second_arbitration.id),
            credit_settlement_key=_arbitration_key("credit", second_arbitration.id),
            credit_amount=Decimal("0.25"),
        )
        assert second_replay is False
        assert second_block.attempt_id == attempt.id
        with pytest.raises(ParallelRuntimeConflict, match="document lineage"):
            await accept_verified_block(
                session,
                attempt=attempt,
                document_id=uuid.uuid4(),
                processing_job_id=ids["job_id"],
                document_version_id=ids["document_version_id"],
                arbitration_id=first_arbitration.id,
                logical_block_key="cross-document",
                final_state="verified",
                artifact_key="tenant-safe/cross-document.json",
                artifact_sha256="7" * 64,
                provenance={"attempt_id": str(attempt.id)},
                acceptance_idempotency_key=_arbitration_key("accept", first_arbitration.id),
                credit_settlement_key=_arbitration_key("credit", first_arbitration.id),
                credit_amount=Decimal("0.1"),
            )
        replayed_block, replayed = await accept_verified_block(
            session,
            attempt=attempt,
            document_id=ids["document_id"],
            processing_job_id=ids["job_id"],
            document_version_id=ids["document_version_id"],
            arbitration_id=second_arbitration.id,
            logical_block_key="paragraph-2",
            final_state="verified",
            artifact_key="tenant-safe/block-2.json",
            artifact_sha256="c" * 64,
            provenance={"attempt_id": str(attempt.id), "authority": "pixel_ocr"},
            acceptance_idempotency_key=_arbitration_key("accept", second_arbitration.id),
            credit_settlement_key=_arbitration_key("credit", second_arbitration.id),
            credit_amount=Decimal("0.25"),
        )
        assert replayed is True
        assert replayed_block.id == second_block.id
        with pytest.raises(ParallelRuntimeConflict, match="idempotency key was reused"):
            await accept_verified_block(
                session,
                attempt=attempt,
                document_id=ids["document_id"],
                processing_job_id=ids["job_id"],
                document_version_id=ids["document_version_id"],
                arbitration_id=second_arbitration.id,
                logical_block_key="paragraph-2",
                final_state="verified",
                artifact_key="tenant-safe/block-2.json",
                artifact_sha256="f" * 64,
                provenance={"attempt_id": str(attempt.id), "authority": "pixel_ocr"},
                acceptance_idempotency_key=_arbitration_key("accept", second_arbitration.id),
                credit_settlement_key=_arbitration_key("credit", second_arbitration.id),
                credit_amount=Decimal("0.25"),
            )
        with pytest.raises(ParallelRuntimeConflict, match="terminal parse attempt"):
            await transition_parse_attempt(session, attempt, "REJECTED")
        await session.commit()

    async with database.sessions() as session:
        stored_attempt = await session.get(ParallelParseAttempt, attempt_id)
        assert stored_attempt is not None and stored_attempt.state == "ACCEPTED"
        assert stored_attempt.billing_disposition == "accepted_billable"
        assert await session.scalar(select(func.count(AcceptedBlock.id))) == 2
        assert await session.scalar(select(func.count(AttemptValidation.id))) == 4
        shard = await session.get(ParallelParseShard, shard_id)
        assert shard is not None and shard.status == "ACCEPTED"


@pytest.mark.asyncio
async def test_unavailable_or_abstained_mandatory_validator_cannot_bill(
    runtime_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = runtime_db
    _shard_id, attempt_id = await _shard_attempt(database, ids, suffix="fail-closed")
    async with database.sessions() as session:
        attempt = await session.get(ParallelParseAttempt, attempt_id)
        assert attempt is not None
        await transition_parse_attempt(session, attempt, "QUEUED")
        await transition_parse_attempt(session, attempt, "RUNNING")
        await record_attempt_output(
            session,
            attempt,
            artifact_key="tenant-safe/unverified-output.json",
            output_sha256="9" * 64,
            output_summary={"page_count": 2},
            gpu_milliseconds=1_000,
            cost_usd=Decimal("0.005"),
        )
        for level, status in ((0, "unavailable"), (1, "abstained"), (6, "unavailable")):
            await record_attempt_validation(
                session,
                attempt=attempt,
                level=level,
                validator_key=f"validator-{level}",
                validator_revision="validator-v6",
                status=status,
                score=None,
                hard_fail=False,
                reason_codes=["EVIDENCE_UNAVAILABLE"],
                findings=[],
                evidence={"level": level, "status": status},
            )
        arbitration = await _selected_arbitration(
            session,
            ids,
            shard_id=_shard_id,
            attempt_id=attempt.id,
            logical_unit_key="table-unverified",
            credit_amount=Decimal("1"),
            suffix="table-unverified",
        )
        with pytest.raises(
            ParallelRuntimeConflict,
            match="required validator level L0 has no pinned passing receipt",
        ):
            await accept_verified_block(
                session,
                attempt=attempt,
                document_id=ids["document_id"],
                processing_job_id=ids["job_id"],
                document_version_id=ids["document_version_id"],
                arbitration_id=arbitration.id,
                logical_block_key="table-unverified",
                final_state="verified",
                artifact_key="tenant-safe/unverified-block.json",
                artifact_sha256="9" * 64,
                provenance={"attempt_id": str(attempt.id)},
                acceptance_idempotency_key=_arbitration_key("accept", arbitration.id),
                credit_settlement_key=_arbitration_key("credit", arbitration.id),
                credit_amount=Decimal("1"),
            )
        assert attempt.state == "VALIDATING"
        assert attempt.billing_disposition == "pending"
        assert await session.scalar(select(func.count(AcceptedBlock.id))) == 0


@pytest.mark.asyncio
async def test_recovery_health_and_collection_events_are_append_only(
    runtime_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = runtime_db
    shard_id, attempt_id = await _shard_attempt(database, ids)
    async with database.sessions() as session:
        task, replay = await request_recovery(
            session,
            tenant_id=ids["tenant_id"],
            document_id=ids["document_id"],
            shard_id=shard_id,
            source_attempt_id=attempt_id,
            recovery_level="row",
            reason_code="ROW_OMISSION_DETECTED",
            target={"page": 2, "table": 1, "row": 7},
            preprocessing_variants=["deskew", "contrast"],
            route_candidates=["authority_reconstruction", "region_recovery"],
            idempotency_key="recover-row-7",
        )
        assert replay is False
        health, event = await update_worker_health(
            session,
            tenant_id=ids["tenant_id"],
            worker_id="worker-a",
            pool_key="mineru-3-4-4",
            model_id="mineru-3.4.4-pipeline",
            runtime_identity="sha256:runtime-verified",
            region="ap-northeast",
            state="QUARANTINED",
            infrastructure_status="healthy",
            semantic_status="failing",
            infrastructure_score=Decimal("1"),
            semantic_score=Decimal("0.25"),
            inflight=0,
            capacity=4,
            consecutive_semantic_failures=3,
            metrics={"canary_failures": 3},
            reason_codes=["SILENT_ROW_OMISSION"],
            impacted_attempt_ids=[attempt_id],
        )
        assert health.state == "QUARANTINED"
        assert event is not None and event.event_type == "quarantined"
        assert event.reason_codes == ["SILENT_ROW_OMISSION"]
        with pytest.raises(ParallelRuntimeConflict, match="stale worker health"):
            await update_worker_health(
                session,
                tenant_id=ids["tenant_id"],
                worker_id="worker-a",
                pool_key="mineru-3-4-4",
                model_id="mineru-3.4.4-pipeline",
                runtime_identity="sha256:runtime-verified",
                region="ap-northeast",
                state="HEALTHY",
                infrastructure_status="healthy",
                semantic_status="healthy",
                infrastructure_score=Decimal("1"),
                semantic_score=Decimal("1"),
                inflight=0,
                capacity=4,
                consecutive_semantic_failures=0,
                metrics={},
                observed_at=event.occurred_at - timedelta(seconds=1),
            )
        emitted = await emit_parallel_event(
            session,
            tenant_id=ids["tenant_id"],
            collection_id=ids["collection_id"],
            job_id=None,
            event_type="recovery.region.requested.v1",
            payload={
                "collection_id": str(ids["collection_id"]),
                "document_id": str(ids["document_id"]),
                "shard_id": str(shard_id),
                "source_attempt_id": str(attempt_id),
                "recovery_task_id": str(task.id),
                "recovery_level": "row",
                "reason_codes": ["ROW_OMISSION_DETECTED"],
                "recovery_state": "REQUESTED",
            },
        )
        assert emitted.sequence == 1
        await session.commit()

    async with database.sessions() as session:
        assert await session.scalar(select(func.count(RecoveryTask.id))) == 1
        assert await session.scalar(select(func.count(SemanticHealthEvent.id))) == 1
        collection = await session.get(Collection, ids["collection_id"])
        assert collection is not None and collection.event_sequence == 1


@pytest.mark.asyncio
async def test_worker_health_cannot_claim_healthy_over_semantic_failure(
    runtime_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = runtime_db
    async with database.sessions() as session:
        health, event = await update_worker_health(
            session,
            tenant_id=ids["tenant_id"],
            worker_id="worker-fail-closed",
            pool_key="paddleocr-vl-1-6",
            model_id="paddleocr-vl-1.6",
            runtime_identity="sha256:runtime-verified",
            region="ap-northeast",
            state="HEALTHY",
            infrastructure_status="healthy",
            semantic_status="failing",
            infrastructure_score=Decimal("1"),
            semantic_score=Decimal("0.1"),
            inflight=1,
            capacity=2,
            consecutive_semantic_failures=1,
            metrics={"canary": "failed"},
            reason_codes=(code for code in ["SEMANTIC_CANARY_FAILED"]),
        )
        assert health.state == "QUARANTINED"
        assert event is not None
        assert event.current_state == "QUARANTINED"
        assert event.reason_codes == ["SEMANTIC_CANARY_FAILED"]
        with pytest.raises(ValueError, match="between zero and capacity"):
            await update_worker_health(
                session,
                tenant_id=ids["tenant_id"],
                worker_id="worker-over-capacity",
                pool_key="paddleocr-vl-1-6",
                model_id="paddleocr-vl-1.6",
                runtime_identity="sha256:runtime-verified",
                region="ap-northeast",
                state="HEALTHY",
                infrastructure_status="healthy",
                semantic_status="healthy",
                infrastructure_score=Decimal("1"),
                semantic_score=Decimal("1"),
                inflight=3,
                capacity=2,
                consecutive_semantic_failures=0,
                metrics={},
            )


@pytest.mark.asyncio
async def test_parallel_snapshot_is_project_and_tenant_scoped(
    runtime_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = runtime_db
    await _shard_attempt(database, ids)
    principal = Principal(
        user_id=ids["user_id"],
        tenant_id=ids["tenant_id"],
        roles=frozenset({"owner"}),
        scopes=frozenset({"api:read"}),
        auth_type="test",
    )
    async with database.sessions() as session:
        snapshot = await get_parallel_document_snapshot(
            collection_id=ids["collection_id"],
            document_id=ids["document_id"],
            session=session,
            principal=principal,
        )
        assert snapshot.schema_version == "6.0"
        assert snapshot.event_stream_url.endswith("/events/stream")
        assert snapshot.shard_state_counts == {"PLANNED": 1}
        assert snapshot.shards_total == 1
        assert snapshot.attempts_total == 1
        assert snapshot.shards_truncated is False
        assert snapshot.attempts_truncated is False
        assert snapshot.usage.duplicate_billable_attempts == 0
        assert snapshot.usage.settlement_mismatch_count == 0

        wrong_tenant = Principal(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            roles=frozenset({"owner"}),
            scopes=frozenset({"api:read"}),
            auth_type="test",
        )
        with pytest.raises(HTTPException) as raised:
            await get_parallel_document_snapshot(
                collection_id=ids["collection_id"],
                document_id=ids["document_id"],
                session=session,
                principal=wrong_tenant,
            )
        assert getattr(raised.value, "status_code", None) == 404
