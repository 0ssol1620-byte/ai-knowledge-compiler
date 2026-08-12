"""SQLite evidence for the v6 durable parallel-runtime orchestration boundary."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from akc_api.database import Database
from akc_api.models import (
    Collection,
    CollectionEvent,
    CreditAccount,
    CreditLedger,
    Document,
    GpuProviderInvocation,
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
    AttemptValidation,
    ContinuityEdge,
    ParallelParseAttempt,
    ParallelParseShard,
    RecoveryTask,
    SemanticHealthEvent,
    WorkerHealth,
)
from akc_api.parallel_models import (
    ArbitrationDecision as DurableArbitrationDecision,
)
from akc_api.parallel_orchestrator import (
    AcceptanceWrite,
    ContinuityEdgeInput,
    DurableParallelOrchestrator,
    ParallelRuntimeScope,
    ValidatorRevision,
    admit_gpu_invocation_result,
    sign_parallel_v6_verification,
)
from akc_api.parallel_runtime_store import ParallelRuntimeConflict
from akc_api.security import Principal
from akc_api.services import credit_entry
from akc_api.settings import Settings
from akc_parallel_runtime import (
    ArbitrationBasis,
    ArbitrationCandidate,
    Arbitrator,
    AttemptKind,
    AttemptOutput,
    BlockKind,
    CandidateObservation,
    ContinuityMergeResult,
    CostRecord,
    EvidenceReceipt,
    FinalizationResult,
    FinalizationUnit,
    Finalizer,
    HealthTransition,
    MergedBlock,
    ParseShard,
    PreprocessingVariant,
    RecoveryDecision,
    RecoveryScope,
    RegionLevel,
    ShardPlan,
    ValidationLevel,
    ValidationPolicy,
    ValidatorPipeline,
    VerificationState,
    WorkerState,
)
from akc_parallel_runtime import (
    RecoveryTask as CoreRecoveryTask,
)
from akc_parallel_runtime import (
    canonical_sha256 as runtime_sha256,
)
from sqlalchemy import func, select, text

ALL_LEVELS = frozenset(ValidationLevel)
BINDINGS = {
    level: ValidatorRevision(
        validator_key=f"validator-l{int(level)}",
        validator_revision="validator-v6-pinned",
    )
    for level in ValidationLevel
}


@pytest_asyncio.fixture
async def orchestrator_db(
    tmp_path: Path,
) -> AsyncIterator[tuple[Database, dict[str, Any]]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'orchestrator.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
    )
    database = Database(settings)
    await database.create_schema()
    async with database.sessions() as session:
        tenant = Tenant(slug="orchestrator-test", name="Orchestrator Test")
        user = User(
            email="orchestrator@example.com",
            password_hash="inert-test-hash",  # noqa: S106
            display_name="Orchestrator Owner",
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
            title="Durable parallel document",
            document_type="pdf",
            language_codes=["ko"],
            page_count=2,
            status="PREFLIGHTED",
        )
        session.add_all([collection, document])
        await session.flush()
        job = ProcessingJob(
            tenant_id=tenant.id,
            project_id=project.id,
            document_id=document.id,
            job_type="parallel_v6",
            status="running",
            priority=5,
            requested_options={},
        )
        session.add(job)
        await session.flush()
        await credit_entry(
            session,
            tenant_id=tenant.id,
            operation_key="fixture:grant",
            entry_type="grant",
            credits=Decimal("20"),
            metadata={"source": "orchestrator_test"},
        )
        await credit_entry(
            session,
            tenant_id=tenant.id,
            operation_key="fixture:reserve",
            entry_type="reserve",
            credits=Decimal("2"),
            metadata={"source": "orchestrator_test"},
        )
        await session.commit()
        ids = {
            "tenant_id": tenant.id,
            "user_id": user.id,
            "project_id": project.id,
            "collection_id": collection.id,
            "document_id": document.id,
            "job_id": job.id,
        }
    try:
        yield database, ids
    finally:
        await database.dispose()


def _scope(
    ids: dict[str, Any],
    *,
    job_id: uuid.UUID | None = None,
    document_version_id: str = "document-version-1",
) -> ParallelRuntimeScope:
    return ParallelRuntimeScope(
        tenant_id=ids["tenant_id"],
        collection_id=ids["collection_id"],
        document_id=ids["document_id"],
        processing_job_id=job_id or ids["job_id"],
        document_version_id=document_version_id,
    )


def _plan(
    ids: dict[str, Any],
    *,
    shard_count: int,
    document_version_id: str = "document-version-1",
) -> ShardPlan:
    shards: list[ParseShard] = []
    for index in range(1, shard_count + 1):
        page_id = f"page-{index}"
        context_ids = (
            ("page-2",)
            if shard_count == 2 and index == 1
            else ("page-1",)
            if shard_count == 2
            else ()
        )
        ordered = ("page-1", "page-2") if shard_count == 2 else (page_id,)
        shards.append(
            ParseShard(
                shard_id=f"core-shard-{index}",
                document_id=str(ids["document_id"]),
                document_version_id=document_version_id,
                ordinal=index - 1,
                primary_page_ids=(page_id,),
                context_page_ids=context_ids,
                ordered_input_page_ids=ordered,
                expected_seconds=1.5,
                required_worker_class="large_context_precision",
                policy_version="adaptive-shard-v6",
            )
        )
    return ShardPlan(
        document_id=str(ids["document_id"]),
        document_version_id=document_version_id,
        source_sha256=runtime_sha256({"source": str(ids["document_id"])}),
        shards=tuple(shards),
        policy_version="adaptive-shard-v6",
    )


def _evidence(
    levels: frozenset[ValidationLevel], *, page_id: str
) -> tuple[tuple[ValidationLevel, tuple[EvidenceReceipt, ...]], ...]:
    return tuple(
        (
            level,
            (
                EvidenceReceipt(
                    source_ref=f"r2://validator/{page_id}/l{int(level)}",
                    sha256=runtime_sha256({"page_id": page_id, "validation_level": int(level)}),
                    kind="validator_receipt",
                ),
            ),
        )
        for level in sorted(levels, key=int)
    )


def _validation(
    *,
    page_id: str,
    required_levels: frozenset[ValidationLevel],
    authority_available: bool,
) -> tuple[ValidationPolicy, Any]:
    policy = ValidationPolicy(
        expected_page_ids=(page_id,),
        native_comparison_required=ValidationLevel.NATIVE in required_levels,
        authority_required=ValidationLevel.AUTHORITY in required_levels,
        differential_required=ValidationLevel.DIFFERENTIAL in required_levels,
        multimodal_required=ValidationLevel.MULTIMODAL in required_levels,
        downstream_required=ValidationLevel.DOWNSTREAM in required_levels,
    )
    evidenced_levels = (
        required_levels if authority_available else required_levels - {ValidationLevel.AUTHORITY}
    )
    observation = CandidateObservation(
        http_status=200,
        response_received=True,
        identity_matches=True,
        checksum_matches=True,
        schema_valid=True,
        size_valid=True,
        finish_reason_complete=True,
        timed_out=False,
        actual_page_ids=(page_id,),
        block_count=1,
        bbox_valid=True,
        reading_order_valid=True,
        output_nonempty=True,
        repetition_detected=False,
        source_coverage=1.0,
        native_available=True,
        native_text_coverage=1.0,
        native_numeric_exact=True,
        native_headings_match=True,
        native_object_count_match=True,
        authority_available=authority_available,
        authority_numeric_exact=True if authority_available else None,
        authority_period_unit_account_match=True if authority_available else None,
        differential_available=True,
        differential_agreement=True,
        expected_invariants_hold=True,
        multimodal_available=True,
        visible_regions_complete=True,
        tables_uncut=True,
        captions_complete=True,
        hierarchy_valid=True,
        downstream_available=True,
        markdown_valid=True,
        package_import_valid=True,
        source_links_valid=True,
        retrieval_valid=True,
        evidence=_evidence(evidenced_levels, page_id=page_id),
    )
    return policy, ValidatorPipeline().validate(observation, policy)


async def _dispatch_validate(
    orchestrator: DurableParallelOrchestrator,
    shard: ParallelParseShard,
    *,
    index: int,
    required_levels: frozenset[ValidationLevel],
    authority_available: bool,
    attempt_kind: AttemptKind = AttemptKind.PRIMARY,
    parent_attempt_id: uuid.UUID | None = None,
) -> tuple[ParallelParseAttempt, str, Any]:
    request_sha256 = runtime_sha256(
        {"shard_id": str(shard.id), "attempt_index": index, "kind": attempt_kind.value}
    )
    dispatched = await orchestrator.dispatch(
        shard.id,
        attempt_kind=attempt_kind,
        pool_key="mineru-3-4-4",
        model_id="mineru-3.4.4-pipeline",
        model_revision="mineru-revision-v6",
        runtime_identity="runtime-image-v6",
        route_policy_version="router-v6",
        request_sha256=request_sha256,
        parent_attempt_id=parent_attempt_id,
        operation_key=f"dispatch-{index}-{attempt_kind.value}",
    )
    attempt = dispatched.row
    await orchestrator.start(
        attempt.id,
        worker_id=f"worker-{index}-{attempt_kind.value}",
        operation_key=f"start-{index}-{attempt_kind.value}",
    )
    output_sha256 = runtime_sha256({"attempt_id": str(attempt.id), "output": "verified-candidate"})
    output = AttemptOutput(
        prediction_uri=f"r2://parallel/{attempt.id}.json",
        prediction_sha256=output_sha256,
        completed_at=utcnow(),
        cost=CostRecord(
            gpu_seconds=Decimal("1.25"),
            provider_cost=Decimal("0.125"),
            user_credits=Decimal("1"),
            duplicate_compute=False,
        ),
    )
    await orchestrator.receive_output(
        attempt.id,
        output,
        output_summary={"block_count": 1, "page_count": 1},
        operation_key=f"output-{index}-{attempt_kind.value}",
    )
    page_id = str(shard.ownership["primary_page_ids"][0])
    _, validation = _validation(
        page_id=page_id,
        required_levels=required_levels,
        authority_available=authority_available,
    )
    await orchestrator.persist_validation(
        attempt.id,
        validation,
        validator_revisions=BINDINGS,
        operation_key=f"validation-{index}-{attempt_kind.value}",
    )
    return attempt, output_sha256, validation


async def _accept_shard(
    orchestrator: DurableParallelOrchestrator,
    shard: ParallelParseShard,
    *,
    index: int,
    launch_hedge: bool = False,
    logical_unit_key: str | None = None,
    operation_tag: str | None = None,
    attempt_kind: AttemptKind = AttemptKind.PRIMARY,
    parent_attempt_id: uuid.UUID | None = None,
    worker_id: str | None = None,
) -> tuple[ParallelParseAttempt, AcceptanceWrite, DurableArbitrationDecision]:
    tag = operation_tag or str(index)
    unit_key = logical_unit_key or f"block-{index}"
    dispatched = await orchestrator.dispatch(
        shard.id,
        attempt_kind=attempt_kind,
        pool_key="mineru-3-4-4",
        model_id="mineru-3.4.4-pipeline",
        model_revision="mineru-revision-v6",
        runtime_identity="runtime-image-v6",
        route_policy_version="router-v6",
        request_sha256=runtime_sha256({"shard": str(shard.id), "index": index}),
        parent_attempt_id=parent_attempt_id,
        operation_key=f"dispatch-{tag}-{attempt_kind.value}",
    )
    attempt = dispatched.row
    await orchestrator.start(
        attempt.id,
        worker_id=worker_id or f"worker-{index}-{attempt_kind.value}",
        operation_key=f"start-{tag}-{attempt_kind.value}",
    )
    if launch_hedge:
        hedge = await orchestrator.hedge(
            attempt.id,
            pool_key="paddleocr-vl",
            model_id="paddleocr-vl-1.6",
            model_revision="paddle-revision-v6",
            runtime_identity="runtime-image-v6-secondary",
            route_policy_version="router-v6",
            request_sha256=runtime_sha256({"hedge": str(attempt.id)}),
            predicted_p95_milliseconds=1_000,
            elapsed_milliseconds=1_250,
            operation_key=f"hedge-{tag}",
        )
        assert hedge.row.billing_disposition == "speculative_unbillable"
    output_sha256 = runtime_sha256({"attempt": str(attempt.id), "accepted": True})
    output = AttemptOutput(
        prediction_uri=f"r2://parallel/{attempt.id}.json",
        prediction_sha256=output_sha256,
        completed_at=utcnow(),
        cost=CostRecord(
            gpu_seconds=Decimal("1.25"),
            provider_cost=Decimal("0.125"),
            user_credits=Decimal("1"),
        ),
    )
    await orchestrator.receive_output(
        attempt.id,
        output,
        output_summary={"block_count": 1, "page_count": 1},
        operation_key=f"output-{tag}-{attempt_kind.value}",
    )
    page_id = str(shard.ownership["primary_page_ids"][0])
    _, validation = _validation(
        page_id=page_id,
        required_levels=ALL_LEVELS,
        authority_available=True,
    )
    persisted_validation = await orchestrator.persist_validation(
        attempt.id,
        validation,
        validator_revisions=BINDINGS,
        operation_key=f"validation-{tag}-{attempt_kind.value}",
    )
    assert len(persisted_validation.rows) == 7
    assert not persisted_validation.failure_events
    candidate = ArbitrationCandidate(
        attempt_id=str(attempt.id),
        prediction_sha256=output_sha256,
        hard_gate_pass=validation.passed,
        numeric_value=Decimal(index),
        structure_fingerprint=runtime_sha256({"structure": index}),
        independent_family="mineru",
        authority_exact=True,
        native_exact=True,
        pixel_specialist_exact=True,
        source_coverage=1.0,
        structure_score=1.0,
        cross_model_agreement=1.0,
        runtime_reliability=1.0,
    )
    decision = Arbitrator().arbitrate_numeric(
        unit_key,
        (candidate,),
        authority_required=True,
    )
    arbitration = await orchestrator.persist_arbitration(
        shard.id,
        decision,
        policy_version="authority-arbitration-v6",
        evidence={"authority_receipt_sha256": runtime_sha256({"authority": str(attempt.id)})},
        operation_key=f"arbitration-{tag}",
        priced_credit_amount=Decimal("1"),
    )
    acceptance = await orchestrator.accept(
        arbitration.row.id,
        logical_block_key=unit_key,
        artifact_key=output.prediction_uri,
        artifact_sha256=output_sha256,
        provenance={"source_refs": [f"page://{page_id}"]},
        credit_amount=Decimal("1"),
        operation_key=f"accept-{tag}",
    )
    return attempt, acceptance, arbitration.row


@pytest.mark.asyncio
async def test_full_happy_path_persists_state_evidence_credit_and_events_atomically(
    orchestrator_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = orchestrator_db
    plan = _plan(ids, shard_count=2)
    async with database.sessions() as session:
        orchestrator = DurableParallelOrchestrator(session, _scope(ids))
        planned = await orchestrator.persist_plan(
            plan,
            page_number_by_id={"page-1": 1, "page-2": 2},
            required_levels=ALL_LEVELS,
            validator_revisions=BINDINGS,
            operation_key="plan-happy",
        )
        assert len(planned.shards) == 2
        first_attempt, first_acceptance, _ = await _accept_shard(
            orchestrator,
            planned.shards[0].row,
            index=1,
            launch_hedge=True,
        )
        second_attempt, second_acceptance, _ = await _accept_shard(
            orchestrator,
            planned.shards[1].row,
            index=2,
        )
        started = await orchestrator.start_continuity(
            merge_revision="continuity-v6",
            edges=(
                ContinuityEdgeInput(
                    source_shard_id=planned.shards[0].row.id,
                    target_shard_id=planned.shards[1].row.id,
                    edge_type="reading_order",
                    confidence=Decimal("1"),
                    authority="authority",
                    evidence={"receipt_sha256": runtime_sha256({"edge": "1-to-2"})},
                ),
            ),
            operation_key="continuity-start-happy",
        )
        merge_sha256 = runtime_sha256(
            {
                "blocks": [
                    first_acceptance.block.artifact_sha256,
                    second_acceptance.block.artifact_sha256,
                ]
            }
        )
        merge_result = ContinuityMergeResult(
            merge_id="merge-happy",
            accepted=True,
            markdown="first\n\nsecond",
            blocks=(
                MergedBlock(
                    merged_block_id="block-1",
                    kind=BlockKind.PARAGRAPH,
                    text="first",
                    page_ids=("page-1",),
                    page_index0=0,
                    order=0,
                    source_refs=("page://page-1",),
                    provenance_block_ids=("source-block-1",),
                ),
                MergedBlock(
                    merged_block_id="block-2",
                    kind=BlockKind.PARAGRAPH,
                    text="second",
                    page_ids=("page-2",),
                    page_index0=1,
                    order=1,
                    source_refs=("page://page-2",),
                    provenance_block_ids=("source-block-2",),
                ),
            ),
            dropped_marginal_block_ids=(),
            reason_codes=(),
            merge_sha256=merge_sha256,
        )
        completed = await orchestrator.complete_continuity(
            merge_result,
            merge_revision="continuity-v6",
            accepted_edge_ids=(started.edges[0].id,),
            operation_key="continuity-complete-happy",
        )
        assert completed.edges[0].status == "accepted"
        finalized = Finalizer().finalize(
            document_version_id=plan.document_version_id,
            units=(
                FinalizationUnit(
                    unit_id="block-1",
                    state=VerificationState.AUTHORITY_VERIFIED,
                    prediction_sha256=first_acceptance.block.artifact_sha256,
                    source_refs=("page://page-1",),
                    provenance_attempt_ids=(str(first_attempt.id),),
                ),
                FinalizationUnit(
                    unit_id="block-2",
                    state=VerificationState.AUTHORITY_VERIFIED,
                    prediction_sha256=second_acceptance.block.artifact_sha256,
                    source_refs=("page://page-2",),
                    provenance_attempt_ids=(str(second_attempt.id),),
                ),
            ),
            merge_sha256=merge_sha256,
            occurred_at=utcnow(),
            idempotency_key="finalize-happy-core",
        )
        durable_final = await orchestrator.finalize_document(
            finalized,
            operation_key="finalize-happy",
        )
        assert durable_final.row.status == "COMPLETED"
        await session.commit()

    async with database.sessions() as session:
        assert await session.scalar(select(func.count(ParallelParseShard.id))) == 2
        assert await session.scalar(select(func.count(ParallelParseAttempt.id))) == 3
        assert await session.scalar(select(func.count(AttemptValidation.id))) == 14
        assert await session.scalar(select(func.count(DurableArbitrationDecision.id))) == 2
        assert await session.scalar(select(func.count(AcceptedBlock.id))) == 2
        assert await session.scalar(select(func.count(ContinuityEdge.id))) == 1
        consumes = list(
            (
                await session.scalars(
                    select(CreditLedger).where(CreditLedger.entry_type == "consume")
                )
            ).all()
        )
        assert len(consumes) == 2
        account = await session.get(CreditAccount, ids["tenant_id"])
        assert account is not None
        assert Decimal(account.balance) == Decimal("18")
        assert Decimal(account.reserved) == Decimal("0")
        document = await session.get(Document, ids["document_id"])
        assert document is not None and document.status == "COMPLETED"
        event_types = set((await session.scalars(select(CollectionEvent.event_type))).all())
        assert {
            "shard.planned.v1",
            "shard.dispatched.v1",
            "attempt.started.v1",
            "attempt.output.received.v1",
            "attempt.accepted.v1",
            "attempt.hedged.v1",
            "continuity.merge.started.v1",
            "continuity.merge.completed.v1",
            "document.finalized.v1",
        } <= event_types


@pytest.mark.asyncio
async def test_duplicate_replay_is_content_bound_and_never_double_charges(
    orchestrator_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = orchestrator_db
    async with database.sessions() as session:
        orchestrator = DurableParallelOrchestrator(session, _scope(ids))
        planned = await orchestrator.persist_plan(
            _plan(ids, shard_count=1),
            page_number_by_id={"page-1": 1},
            required_levels=ALL_LEVELS,
            validator_revisions=BINDINGS,
            operation_key="plan-replay",
        )
        _, accepted, arbitration = await _accept_shard(
            orchestrator,
            planned.shards[0].row,
            index=1,
        )
        replay = await orchestrator.accept(
            arbitration.id,
            logical_block_key="block-1",
            artifact_key=accepted.block.artifact_key,
            artifact_sha256=accepted.block.artifact_sha256,
            provenance={"source_refs": ["page://page-1"]},
            credit_amount=Decimal("1"),
            operation_key="accept-1",
        )
        assert replay.replayed is True
        with pytest.raises(ParallelRuntimeConflict):
            await orchestrator.accept(
                arbitration.id,
                logical_block_key="block-1",
                artifact_key=accepted.block.artifact_key,
                artifact_sha256=accepted.block.artifact_sha256,
                provenance={"source_refs": ["page://page-1"]},
                credit_amount=Decimal("2"),
                operation_key="accept-1",
            )
        with pytest.raises(ParallelRuntimeConflict):
            await orchestrator.accept(
                arbitration.id,
                logical_block_key="block-1",
                artifact_key=accepted.block.artifact_key,
                artifact_sha256=accepted.block.artifact_sha256,
                provenance={"source_refs": ["page://page-1"]},
                credit_amount=Decimal("1"),
                operation_key="accept-1-forged-operation",
            )
        with pytest.raises(ParallelRuntimeConflict):
            await orchestrator.accept(
                arbitration.id,
                logical_block_key="block-1-forged-logical-unit",
                artifact_key=accepted.block.artifact_key,
                artifact_sha256=accepted.block.artifact_sha256,
                provenance={"source_refs": ["page://page-1"]},
                credit_amount=Decimal("1"),
                operation_key="accept-1",
            )
        await session.commit()

    async with database.sessions() as session:
        consumes = list(
            (
                await session.scalars(
                    select(CreditLedger).where(CreditLedger.entry_type == "consume")
                )
            ).all()
        )
        duplicate_count = len(consumes) - len({entry.operation_key for entry in consumes})
        assert len(consumes) == 1
        assert duplicate_count == 0
        assert await session.scalar(select(func.count(AcceptedBlock.id))) == 1
        account = await session.get(CreditAccount, ids["tenant_id"])
        assert account is not None
        assert Decimal(account.balance) == Decimal("19")
        assert Decimal(account.reserved) == Decimal("1")


@pytest.mark.asyncio
async def test_validation_and_arbitration_recompute_canonical_authority_evidence(
    orchestrator_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = orchestrator_db
    required = frozenset(
        {
            ValidationLevel.TRANSPORT,
            ValidationLevel.STRUCTURAL,
            ValidationLevel.NATIVE,
        }
    )
    async with database.sessions() as session:
        orchestrator = DurableParallelOrchestrator(session, _scope(ids))
        planned = await orchestrator.persist_plan(
            _plan(ids, shard_count=1),
            page_number_by_id={"page-1": 1},
            required_levels=required,
            validator_revisions=BINDINGS,
            operation_key="plan-canonical-evidence",
        )
        shard = planned.shards[0].row
        attempt, output_sha256, validation = await _dispatch_validate(
            orchestrator,
            shard,
            index=41,
            required_levels=required,
            authority_available=True,
        )
        with pytest.raises(ParallelRuntimeConflict, match="validation digest"):
            await orchestrator.persist_validation(
                attempt.id,
                replace(validation, digest="f" * 64),
                validator_revisions=BINDINGS,
                operation_key="validation-forged-digest",
            )

        authority_decision = Arbitrator().arbitrate_numeric(
            "authority-without-receipt",
            (
                ArbitrationCandidate(
                    attempt_id=str(attempt.id),
                    prediction_sha256=output_sha256,
                    hard_gate_pass=True,
                    numeric_value=Decimal("1"),
                    structure_fingerprint=runtime_sha256({"structure": "authority"}),
                    independent_family="mineru",
                    authority_exact=True,
                    native_exact=True,
                ),
            ),
            authority_required=True,
        )
        assert authority_decision.basis is ArbitrationBasis.AUTHORITY_EXACT
        with pytest.raises(ParallelRuntimeConflict, match="pinned validation policy"):
            await orchestrator.persist_arbitration(
                shard.id,
                authority_decision,
                policy_version="authority-arbitration-v6",
                evidence={},
                operation_key="forged-authority-basis",
                priced_credit_amount=Decimal("1"),
            )

        native_decision = Arbitrator().arbitrate_numeric(
            "native-with-receipt",
            (
                ArbitrationCandidate(
                    attempt_id=str(attempt.id),
                    prediction_sha256=output_sha256,
                    hard_gate_pass=True,
                    numeric_value=Decimal("1"),
                    structure_fingerprint=runtime_sha256({"structure": "native"}),
                    independent_family="mineru",
                    authority_exact=None,
                    native_exact=True,
                ),
            ),
        )
        assert native_decision.basis is ArbitrationBasis.NATIVE_EXACT
        with pytest.raises(ParallelRuntimeConflict, match="arbitration digest"):
            await orchestrator.persist_arbitration(
                shard.id,
                replace(native_decision, decision_sha256="e" * 64),
                policy_version="authority-arbitration-v6",
                evidence={},
                operation_key="forged-arbitration-digest",
                priced_credit_amount=Decimal("1"),
            )


@pytest.mark.asyncio
async def test_unavailable_required_validator_is_unresolved_and_never_billed(
    orchestrator_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = orchestrator_db
    required = frozenset(
        {
            ValidationLevel.TRANSPORT,
            ValidationLevel.STRUCTURAL,
            ValidationLevel.AUTHORITY,
        }
    )
    plan = _plan(ids, shard_count=1)
    async with database.sessions() as session:
        orchestrator = DurableParallelOrchestrator(session, _scope(ids))
        planned = await orchestrator.persist_plan(
            plan,
            page_number_by_id={"page-1": 1},
            required_levels=required,
            validator_revisions=BINDINGS,
            operation_key="plan-unavailable",
        )
        attempt, output_sha256, validation = await _dispatch_validate(
            orchestrator,
            planned.shards[0].row,
            index=11,
            required_levels=required,
            authority_available=False,
        )
        assert validation.passed is False
        candidate = ArbitrationCandidate(
            attempt_id=str(attempt.id),
            prediction_sha256=output_sha256,
            hard_gate_pass=False,
            numeric_value=Decimal("1"),
            structure_fingerprint=None,
            independent_family="mineru",
            authority_exact=None,
        )
        unresolved = Arbitrator().arbitrate_numeric(
            "block-unavailable",
            (candidate,),
            authority_required=True,
        )
        arbitration = await orchestrator.persist_arbitration(
            planned.shards[0].row.id,
            unresolved,
            policy_version="authority-arbitration-v6",
            evidence={"validator_state": "authority_unavailable"},
            operation_key="arbitration-unavailable",
        )
        assert arbitration.row.decision == "unresolved"
        await orchestrator.reject(
            attempt.id,
            target_state="REJECTED",
            failure_domain="semantic",
            reason_codes=("authority_evidence_unavailable",),
            operation_key="reject-unavailable",
        )
        finalized = Finalizer().finalize(
            document_version_id=plan.document_version_id,
            units=(
                FinalizationUnit(
                    unit_id="core-shard-1",
                    state=VerificationState.UNRESOLVED,
                    prediction_sha256=output_sha256,
                    source_refs=("page://page-1",),
                    provenance_attempt_ids=(str(attempt.id),),
                    reason_codes=("authority_evidence_unavailable",),
                ),
            ),
            merge_sha256=runtime_sha256({"merge": "unavailable"}),
            occurred_at=utcnow(),
            idempotency_key="core-final-unavailable",
        )
        durable = await orchestrator.finalize_document(
            finalized,
            operation_key="final-unavailable",
        )
        assert durable.row.status == "PARTIAL"
        await session.commit()

    async with database.sessions() as session:
        authority_row = await session.scalar(
            select(AttemptValidation).where(
                AttemptValidation.level == int(ValidationLevel.AUTHORITY)
            )
        )
        assert authority_row is not None
        assert authority_row.status == "unavailable" and authority_row.hard_fail
        assert await session.scalar(select(func.count(AcceptedBlock.id))) == 0
        assert (
            await session.scalar(
                select(func.count(CreditLedger.id)).where(CreditLedger.entry_type == "consume")
            )
            == 0
        )
        final_event = await session.scalar(
            select(CollectionEvent).where(CollectionEvent.event_type == "document.finalized.v1")
        )
        assert final_event is not None
        assert final_event.payload["final_state"] == "unresolved"
        assert final_event.payload["billable_credits"] == "0"


@pytest.mark.asyncio
async def test_finalizer_rejects_omissions_and_forged_manifest_unit_bindings(
    orchestrator_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = orchestrator_db
    plan = _plan(ids, shard_count=2)
    async with database.sessions() as session:
        orchestrator = DurableParallelOrchestrator(session, _scope(ids))
        planned = await orchestrator.persist_plan(
            plan,
            page_number_by_id={"page-1": 1, "page-2": 2},
            required_levels=ALL_LEVELS,
            validator_revisions=BINDINGS,
            operation_key="plan-finalizer-forgery",
        )
        first_attempt, first_acceptance, _ = await _accept_shard(
            orchestrator,
            planned.shards[0].row,
            index=51,
        )
        first_unit = FinalizationUnit(
            unit_id=first_acceptance.block.logical_block_key,
            state=VerificationState.AUTHORITY_VERIFIED,
            prediction_sha256=first_acceptance.block.artifact_sha256,
            source_refs=("page://page-1",),
            provenance_attempt_ids=(str(first_attempt.id),),
        )
        omitted = Finalizer().finalize(
            document_version_id=plan.document_version_id,
            units=(first_unit,),
            merge_sha256=runtime_sha256({"merge": "omitted-shard"}),
            occurred_at=utcnow(),
            idempotency_key="core-omitted-shard",
        )
        with pytest.raises(ParallelRuntimeConflict, match="omits required"):
            await orchestrator.finalize_document(
                omitted,
                operation_key="finalize-omitted-shard",
            )

        second_attempt, second_acceptance, _ = await _accept_shard(
            orchestrator,
            planned.shards[1].row,
            index=52,
        )
        second_unit = FinalizationUnit(
            unit_id=second_acceptance.block.logical_block_key,
            state=VerificationState.AUTHORITY_VERIFIED,
            prediction_sha256=second_acceptance.block.artifact_sha256,
            source_refs=("page://page-2",),
            provenance_attempt_ids=(str(second_attempt.id),),
        )
        valid = Finalizer().finalize(
            document_version_id=plan.document_version_id,
            units=(first_unit, second_unit),
            merge_sha256=runtime_sha256({"merge": "valid-two-shards"}),
            occurred_at=utcnow(),
            idempotency_key="core-valid-two-shards",
        )
        forged_results = (
            replace(valid, manifest_sha256="f" * 64),
            replace(valid, document_version_id="foreign-document-version"),
            replace(
                valid,
                accepted_units=(
                    replace(first_unit, prediction_sha256="e" * 64),
                    second_unit,
                ),
            ),
            replace(
                valid,
                accepted_units=(
                    replace(first_unit, state=VerificationState.VERIFIED),
                    second_unit,
                ),
            ),
            replace(
                valid,
                accepted_units=(
                    replace(first_unit, source_refs=("page://forged",)),
                    second_unit,
                ),
            ),
            replace(
                valid,
                accepted_units=(
                    replace(
                        first_unit,
                        provenance_attempt_ids=(str(second_attempt.id),),
                    ),
                    second_unit,
                ),
            ),
        )
        for index, forged in enumerate(forged_results):
            with pytest.raises(ParallelRuntimeConflict):
                await orchestrator.finalize_document(
                    forged,
                    operation_key=f"finalize-forged-{index}",
                )
        durable = await orchestrator.finalize_document(
            valid,
            operation_key="finalize-valid-two-shards",
        )
        assert durable.row.status == "COMPLETED"


@pytest.mark.asyncio
async def test_finalizer_rejects_zero_shard_empty_publishable_projection(
    orchestrator_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = orchestrator_db
    async with database.sessions() as session:
        empty_job = ProcessingJob(
            tenant_id=ids["tenant_id"],
            project_id=ids["project_id"],
            document_id=ids["document_id"],
            job_type="parallel_v6",
            status="running",
            requested_options={},
        )
        session.add(empty_job)
        await session.flush()
        merge_sha256 = runtime_sha256({"merge": "empty-forgery"})
        manifest_sha256 = runtime_sha256(
            {
                "document_version_id": "empty-document-version",
                "merge_sha256": merge_sha256,
                "accepted_unit_ids": (),
                "unresolved": (),
                "excluded": (),
                "publishable": True,
                "reason_codes": (),
            }
        )
        forged_empty = FinalizationResult(
            finalization_id="forged-empty-finalization",
            document_version_id="empty-document-version",
            merge_sha256=merge_sha256,
            publishable=True,
            accepted_units=(),
            unresolved_manifest=(),
            excluded_unit_ids=(),
            billable_unit_ids=(),
            manifest_sha256=manifest_sha256,
            reason_codes=(),
        )
        orchestrator = DurableParallelOrchestrator(
            session,
            _scope(
                ids,
                job_id=empty_job.id,
                document_version_id="empty-document-version",
            ),
        )
        with pytest.raises(ParallelRuntimeConflict, match="at least one"):
            await orchestrator.finalize_document(
                forged_empty,
                operation_key="finalize-empty-forgery",
            )


@pytest.mark.asyncio
async def test_same_document_jobs_and_versions_are_history_safe_and_isolated(
    orchestrator_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = orchestrator_db
    async with database.sessions() as session:
        first_orchestrator = DurableParallelOrchestrator(session, _scope(ids))
        first_plan = await first_orchestrator.persist_plan(
            _plan(ids, shard_count=1),
            page_number_by_id={"page-1": 1},
            required_levels=ALL_LEVELS,
            validator_revisions=BINDINGS,
            operation_key="history-plan-v1",
        )
        first_attempt, first_acceptance, _ = await _accept_shard(
            first_orchestrator,
            first_plan.shards[0].row,
            index=61,
            logical_unit_key="shared-logical-unit",
            operation_tag="history-v1",
        )

        second_job = ProcessingJob(
            tenant_id=ids["tenant_id"],
            project_id=ids["project_id"],
            document_id=ids["document_id"],
            job_type="parallel_v6",
            status="running",
            requested_options={},
        )
        session.add(second_job)
        await session.flush()
        second_scope = _scope(
            ids,
            job_id=second_job.id,
            document_version_id="document-version-2",
        )
        second_orchestrator = DurableParallelOrchestrator(session, second_scope)
        second_plan = await second_orchestrator.persist_plan(
            _plan(
                ids,
                shard_count=1,
                document_version_id="document-version-2",
            ),
            page_number_by_id={"page-1": 1},
            required_levels=ALL_LEVELS,
            validator_revisions=BINDINGS,
            operation_key="history-plan-v2",
        )
        with pytest.raises(ParallelRuntimeConflict, match="outside the durable scope"):
            await second_orchestrator.start(
                first_attempt.id,
                worker_id="foreign-history-worker",
                operation_key="history-cross-job-attempt",
            )
        second_attempt, second_acceptance, _ = await _accept_shard(
            second_orchestrator,
            second_plan.shards[0].row,
            index=62,
            logical_unit_key="shared-logical-unit",
            operation_tag="history-v2",
        )
        second_result = Finalizer().finalize(
            document_version_id="document-version-2",
            units=(
                FinalizationUnit(
                    unit_id="shared-logical-unit",
                    state=VerificationState.AUTHORITY_VERIFIED,
                    prediction_sha256=second_acceptance.block.artifact_sha256,
                    source_refs=("page://page-1",),
                    provenance_attempt_ids=(str(second_attempt.id),),
                ),
            ),
            merge_sha256=runtime_sha256({"merge": "history-v2"}),
            occurred_at=utcnow(),
            idempotency_key="core-history-v2",
        )
        durable = await second_orchestrator.finalize_document(
            second_result,
            operation_key="finalize-history-v2",
        )
        assert durable.event is not None
        assert durable.event.payload["verified_block_count"] == 1
        assert durable.event.payload["billable_credits"] == "1"
        assert first_acceptance.block.processing_job_id != second_acceptance.block.processing_job_id
        await session.commit()

    async with database.sessions() as session:
        blocks = list((await session.scalars(select(AcceptedBlock))).all())
        assert len(blocks) == 2
        assert {block.logical_block_key for block in blocks} == {"shared-logical-unit"}
        assert len({block.processing_job_id for block in blocks}) == 2
        assert len({block.document_version_id for block in blocks}) == 2


@pytest.mark.asyncio
async def test_worker_quarantine_discovers_acceptance_refunds_and_recovers_once(
    orchestrator_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = orchestrator_db
    plan = _plan(ids, shard_count=1)
    transition = HealthTransition(
        worker_id="worker-71-primary",
        from_state=WorkerState.HEALTHY,
        to_state=WorkerState.QUARANTINED,
        occurred_at=utcnow(),
        reason_codes=("semantic_canary_prediction_mismatch",),
        semantic_score=10.0,
    )
    async with database.sessions() as session:
        orchestrator = DurableParallelOrchestrator(session, _scope(ids))
        planned = await orchestrator.persist_plan(
            plan,
            page_number_by_id={"page-1": 1},
            required_levels=ALL_LEVELS,
            validator_revisions=BINDINGS,
            operation_key="plan-accepted-quarantine",
        )
        attempt, acceptance, _ = await _accept_shard(
            orchestrator,
            planned.shards[0].row,
            index=71,
        )
        valid_finalization = Finalizer().finalize(
            document_version_id=plan.document_version_id,
            units=(
                FinalizationUnit(
                    unit_id=acceptance.block.logical_block_key,
                    state=VerificationState.AUTHORITY_VERIFIED,
                    prediction_sha256=acceptance.block.artifact_sha256,
                    source_refs=("page://page-1",),
                    provenance_attempt_ids=(str(attempt.id),),
                ),
            ),
            merge_sha256=runtime_sha256({"merge": "before-quarantine"}),
            occurred_at=utcnow(),
            idempotency_key="core-before-quarantine",
        )
        job = await session.get(ProcessingJob, ids["job_id"])
        assert job is not None
        revoked_checkpoint_sha256 = runtime_sha256({"checkpoint": "generation-1-completed"})
        job.progress = {
            "parallel_v6_autonomous_pipeline": {
                "phase": "completed",
                "checkpoint_sha256": revoked_checkpoint_sha256,
            }
        }
        first_final = await orchestrator.finalize_document(
            valid_finalization,
            operation_key="finalize-before-invalidation",
        )
        assert first_final.row.status == "COMPLETED"
        assert job.status == "completed"
        assert job.completed_at is not None
        health = await orchestrator.record_worker_health(
            transition,
            pool_key="mineru-3-4-4",
            model_id="mineru-3.4.4-pipeline",
            runtime_identity="runtime-image-v6",
            region="ap-northeast",
            infrastructure_status="healthy",
            semantic_status="failing",
            infrastructure_score=Decimal("1"),
            inflight=0,
            capacity=4,
            consecutive_semantic_failures=3,
            metrics={"semantic_canary": "prediction_mismatch"},
            impacted_attempt_ids=(),
            operation_key="accepted-worker-quarantine",
        )
        assert not health.replayed
        assert len(health.invalidations) == 1
        assert len(health.refund_ledgers) == 1
        assert len(health.recovery_tasks) == 1
        assert len(health.recovery_events) == 1
        assert acceptance.block.final_state == "authority_verified"
        assert attempt.state == "ACCEPTED"
        assert planned.shards[0].row.status == "QUARANTINED"
        document = await session.get(Document, ids["document_id"])
        recovery_job = await session.get(ProcessingJob, ids["job_id"])
        assert document is not None and document.status == "PROCESSING"
        assert recovery_job is not None and recovery_job.status == "running"
        assert recovery_job.completed_at is None
        assert "parallel_v6_autonomous_pipeline" not in recovery_job.progress
        recovery_projection = recovery_job.progress["parallel_v6_recovery"]
        assert recovery_projection["schema_version"] == "parallel-v6-recovery-projection-1.0"
        assert recovery_projection["epoch"] == 1
        assert recovery_projection["phase"] == "requested"
        assert recovery_projection["revoked_checkpoint_sha256"] == revoked_checkpoint_sha256
        assert recovery_projection["accepted_block_ids"] == [str(acceptance.block.id)]
        assert recovery_projection["recovery_task_ids"] == [str(health.recovery_tasks[0].id)]
        requested_projection_sha256 = recovery_projection["projection_sha256"]

        replay = await orchestrator.record_worker_health(
            transition,
            pool_key="mineru-3-4-4",
            model_id="mineru-3.4.4-pipeline",
            runtime_identity="runtime-image-v6",
            region="ap-northeast",
            infrastructure_status="healthy",
            semantic_status="failing",
            infrastructure_score=Decimal("1"),
            inflight=0,
            capacity=4,
            consecutive_semantic_failures=3,
            metrics={"semantic_canary": "prediction_mismatch"},
            impacted_attempt_ids=(),
            operation_key="accepted-worker-quarantine",
        )
        assert replay.replayed
        assert recovery_job.progress["parallel_v6_recovery"]["epoch"] == 1
        assert (
            recovery_job.progress["parallel_v6_recovery"]["projection_sha256"]
            == requested_projection_sha256
        )
        with pytest.raises(ParallelRuntimeConflict):
            await orchestrator.finalize_document(
                valid_finalization,
                operation_key="finalize-after-invalidation",
            )

        principal = Principal(
            user_id=ids["user_id"],
            tenant_id=ids["tenant_id"],
            roles=frozenset({"owner"}),
            scopes=frozenset({"api:read"}),
            auth_type="test",
        )
        snapshot = await get_parallel_document_snapshot(
            collection_id=ids["collection_id"],
            document_id=ids["document_id"],
            session=session,
            principal=principal,
        )
        assert snapshot.integrity.active_accepted_block_count == 0
        assert snapshot.integrity.invalidated_block_count == 1
        assert snapshot.usage.accepted_billable_attempts == 0
        assert snapshot.usage.billable_credits == Decimal("0")
        assert snapshot.usage.refunded_credits == Decimal("1")

        recovery_attempt, recovery_acceptance, _ = await _accept_shard(
            orchestrator,
            planned.shards[0].row,
            index=72,
            logical_unit_key=acceptance.block.logical_block_key,
            operation_tag="accepted-worker-recovery",
            attempt_kind=AttemptKind.RECOVERY,
            parent_attempt_id=attempt.id,
            worker_id="worker-72-recovery",
        )
        assert recovery_attempt.attempt_kind == "recovery"
        assert recovery_acceptance.block.generation == 2
        assert recovery_acceptance.block.shard_id == acceptance.block.shard_id
        assert attempt.state == "ACCEPTED"
        recovery_decision = RecoveryDecision(
            task_id=str(health.recovery_tasks[0].target["core_task_id"]),
            accepted=True,
            state=VerificationState.AUTO_REPAIRED,
            selected_attempt_id=str(recovery_attempt.id),
            base_prediction_sha256=acceptance.block.artifact_sha256,
            repaired_prediction_sha256=recovery_acceptance.block.artifact_sha256,
            reason_codes=(),
            decision_sha256=runtime_sha256(
                {
                    "recovery_task_id": str(health.recovery_tasks[0].id),
                    "selected_attempt_id": str(recovery_attempt.id),
                }
            ),
        )
        completed_recovery = await orchestrator.complete_recovery(
            health.recovery_tasks[0].id,
            recovery_decision,
            observed_result_attempt_id=recovery_attempt.id,
            operation_key="accepted-worker-recovery-completed",
        )
        assert completed_recovery.row.state == "COMPLETED"
        recovered_finalization = Finalizer().finalize(
            document_version_id=plan.document_version_id,
            units=(
                FinalizationUnit(
                    unit_id=recovery_acceptance.block.logical_block_key,
                    state=VerificationState(recovery_acceptance.block.final_state),
                    prediction_sha256=recovery_acceptance.block.artifact_sha256,
                    source_refs=("page://page-1",),
                    provenance_attempt_ids=(str(recovery_attempt.id),),
                ),
            ),
            merge_sha256=runtime_sha256({"merge": "after-worker-recovery"}),
            occurred_at=utcnow(),
            idempotency_key="core-after-worker-recovery",
        )
        recovered_final = await orchestrator.finalize_document(
            recovered_finalization,
            operation_key="finalize-after-worker-recovery",
        )
        assert recovered_final.row.status == "COMPLETED"
        completed_job = await session.get(ProcessingJob, ids["job_id"])
        assert completed_job is not None and completed_job.status == "completed"
        assert completed_job.completed_at is not None
        completed_projection = completed_job.progress["parallel_v6_recovery"]
        assert completed_projection["epoch"] == 1
        assert completed_projection["phase"] == "completed"
        assert completed_projection["completion"]["manifest_sha256"] == (
            recovered_finalization.manifest_sha256
        )
        assert completed_projection["completion"]["active_blocks"] == [
            {
                "accepted_block_id": str(recovery_acceptance.block.id),
                "generation": 2,
                "logical_block_key": acceptance.block.logical_block_key,
            }
        ]

        post_recovery_replay = await orchestrator.record_worker_health(
            transition,
            pool_key="mineru-3-4-4",
            model_id="mineru-3.4.4-pipeline",
            runtime_identity="runtime-image-v6",
            region="ap-northeast",
            infrastructure_status="healthy",
            semantic_status="failing",
            infrastructure_score=Decimal("1"),
            inflight=0,
            capacity=4,
            consecutive_semantic_failures=3,
            metrics={"semantic_canary": "prediction_mismatch"},
            impacted_attempt_ids=(),
            operation_key="accepted-worker-quarantine",
        )
        assert post_recovery_replay.replayed
        post_replay_job = await session.get(ProcessingJob, ids["job_id"])
        assert post_replay_job is not None and post_replay_job.status == "completed"
        assert post_replay_job.progress["parallel_v6_recovery"]["phase"] == "completed"
        finalization_replay = await orchestrator.finalize_document(
            recovered_finalization,
            operation_key="finalize-after-worker-recovery",
        )
        assert finalization_replay.replayed

        recovered_snapshot = await get_parallel_document_snapshot(
            collection_id=ids["collection_id"],
            document_id=ids["document_id"],
            session=session,
            principal=principal,
        )
        assert recovered_snapshot.integrity.active_accepted_block_count == 1
        assert recovered_snapshot.integrity.invalidated_block_count == 1
        assert recovered_snapshot.usage.accepted_billable_attempts == 1
        assert recovered_snapshot.usage.billable_credits == Decimal("1")
        assert recovered_snapshot.usage.refunded_credits == Decimal("1")
        await session.commit()

    async with database.sessions() as session:
        assert await session.scalar(select(func.count(AcceptedBlock.id))) == 2
        assert await session.scalar(select(func.count(AcceptedBlockInvalidation.id))) == 1
        attempts = list(
            (
                await session.scalars(
                    select(ParallelParseAttempt).order_by(ParallelParseAttempt.attempt_number)
                )
            ).all()
        )
        assert [item.state for item in attempts] == ["ACCEPTED", "ACCEPTED"]
        assert {item.attempt_kind for item in attempts} == {"primary", "recovery"}
        assert (
            await session.scalar(
                select(func.count(CreditLedger.id)).where(CreditLedger.entry_type == "refund")
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(CollectionEvent.id)).where(
                    CollectionEvent.event_type == "recovery.region.requested.v1"
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(CreditLedger.id)).where(CreditLedger.entry_type == "consume")
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count(CollectionEvent.id)).where(
                    CollectionEvent.event_type == "recovery.completed.v1"
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(CollectionEvent.id)).where(
                    CollectionEvent.event_type == "document.finalized.v1"
                )
            )
            == 2
        )
        recovery = await session.scalar(select(RecoveryTask))
        assert recovery is not None and recovery.state == "COMPLETED"
        account = await session.get(CreditAccount, ids["tenant_id"])
        assert account is not None
        assert Decimal(account.balance) == Decimal("19")
        assert Decimal(account.reserved) == Decimal("0")
        document = await session.get(Document, ids["document_id"])
        job = await session.get(ProcessingJob, ids["job_id"])
        assert document is not None and document.status == "COMPLETED"
        assert job is not None and job.status == "completed"
        assert job.progress["parallel_v6_recovery"]["phase"] == "completed"


@pytest.mark.asyncio
async def test_recovery_quarantine_health_and_finalization_remain_nonbillable(
    orchestrator_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = orchestrator_db
    required = frozenset(
        {
            ValidationLevel.TRANSPORT,
            ValidationLevel.STRUCTURAL,
            ValidationLevel.AUTHORITY,
        }
    )
    plan = _plan(ids, shard_count=1)
    async with database.sessions() as session:
        orchestrator = DurableParallelOrchestrator(session, _scope(ids))
        planned = await orchestrator.persist_plan(
            plan,
            page_number_by_id={"page-1": 1},
            required_levels=required,
            validator_revisions=BINDINGS,
            operation_key="plan-quarantine",
        )
        shard = planned.shards[0].row
        base, base_sha256, _ = await _dispatch_validate(
            orchestrator,
            shard,
            index=21,
            required_levels=required,
            authority_available=False,
        )
        core_task = CoreRecoveryTask(
            task_id="core-recovery-row-1",
            base_attempt_id=str(base.id),
            base_prediction_sha256=base_sha256,
            scope=RecoveryScope(
                level=RegionLevel.ROW,
                scope_id="page-1-table-1-row-7",
                source_refs=("page://page-1",),
            ),
            variant=PreprocessingVariant.OVERLAPPING_TILE,
            parser_recipe="region-recovery-v6",
            created_at=utcnow(),
            idempotency_key="core-recovery-row-1",
        )
        recovery = await orchestrator.request_recovery(
            shard.id,
            core_task,
            reason_codes=("row_omission_detected",),
            operation_key="recovery-request-row-1",
        )
        repaired, repaired_sha256, _ = await _dispatch_validate(
            orchestrator,
            shard,
            index=22,
            required_levels=required,
            authority_available=False,
            attempt_kind=AttemptKind.RECOVERY,
            parent_attempt_id=base.id,
        )
        recovery_decision = RecoveryDecision(
            task_id=core_task.task_id,
            accepted=False,
            state=VerificationState.UNRESOLVED,
            selected_attempt_id=None,
            base_prediction_sha256=base_sha256,
            repaired_prediction_sha256=repaired_sha256,
            reason_codes=("authority_evidence_unavailable",),
            decision_sha256=runtime_sha256({"recovery": core_task.task_id, "accepted": False}),
        )
        completed = await orchestrator.complete_recovery(
            recovery.row.id,
            recovery_decision,
            observed_result_attempt_id=repaired.id,
            operation_key="recovery-complete-row-1",
        )
        assert completed.row.state == "UNRESOLVED"
        await orchestrator.reject(
            repaired.id,
            target_state="QUARANTINED",
            failure_domain="semantic",
            reason_codes=("silent_row_omission",),
            operation_key="reject-quarantine-row-1",
        )
        health = await orchestrator.record_worker_health(
            HealthTransition(
                worker_id="worker-22-recovery",
                from_state=WorkerState.HEALTHY,
                to_state=WorkerState.QUARANTINED,
                occurred_at=utcnow(),
                reason_codes=("silent_row_omission",),
                semantic_score=20.0,
            ),
            pool_key="mineru-3-4-4",
            model_id="mineru-3.4.4-pipeline",
            runtime_identity="runtime-image-v6",
            region="ap-northeast",
            infrastructure_status="healthy",
            semantic_status="failing",
            infrastructure_score=Decimal("1"),
            inflight=0,
            capacity=4,
            consecutive_semantic_failures=3,
            metrics={"canary_failures": 3},
            impacted_attempt_ids=(repaired.id,),
            operation_key="worker-quarantine-row-1",
        )
        assert health.worker.state == "QUARANTINED"
        finalized = Finalizer().finalize(
            document_version_id=plan.document_version_id,
            units=(
                FinalizationUnit(
                    unit_id="core-shard-1",
                    state=VerificationState.QUARANTINED,
                    prediction_sha256=repaired_sha256,
                    source_refs=("page://page-1",),
                    provenance_attempt_ids=(str(base.id), str(repaired.id)),
                    reason_codes=("silent_row_omission",),
                ),
            ),
            merge_sha256=runtime_sha256({"merge": "quarantined"}),
            occurred_at=utcnow(),
            idempotency_key="core-final-quarantined",
        )
        durable = await orchestrator.finalize_document(
            finalized,
            operation_key="final-quarantined",
        )
        assert durable.row.status == "QUARANTINED"
        await session.commit()

    async with database.sessions() as session:
        recovery_row = await session.scalar(select(RecoveryTask))
        assert recovery_row is not None and recovery_row.state == "UNRESOLVED"
        worker = await session.scalar(select(WorkerHealth))
        assert worker is not None
        assert worker.infrastructure_status == "healthy"
        assert worker.semantic_status == "failing"
        assert worker.state == "QUARANTINED"
        assert await session.scalar(select(func.count(SemanticHealthEvent.id))) == 1
        assert await session.scalar(select(func.count(AcceptedBlock.id))) == 0
        assert (
            await session.scalar(
                select(func.count(CreditLedger.id)).where(CreditLedger.entry_type == "consume")
            )
            == 0
        )
        event_types = set((await session.scalars(select(CollectionEvent.event_type))).all())
        assert {
            "recovery.region.requested.v1",
            "recovery.completed.v1",
            "worker.quarantined.v1",
            "document.finalized.v1",
        } <= event_types


@pytest.mark.asyncio
async def test_signed_gpu_verification_is_explicit_atomic_and_exactly_once(
    orchestrator_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = orchestrator_db
    signing_key = b"parallel-v6-test-signing-key-32-bytes-minimum"
    worker_id = "runpod-worker-gpu-v6"
    model_revision = "a" * 64
    runtime_image_digest = f"sha256:{'b' * 64}"
    adapter_version = "mineru-adapter-v6"
    provider_key = "mineru-pipeline"
    endpoint_id = "runpod-endpoint-v6"
    provider_job_id = "runpod-job-v6"
    input_sha256 = runtime_sha256({"gpu": "input"})
    output_sha256 = runtime_sha256({"gpu": "output"})
    raw_provider_sha256 = runtime_sha256({"gpu": "raw-provider-response"})
    gpu_scope = ParallelRuntimeScope(
        tenant_id=ids["tenant_id"],
        collection_id=ids["collection_id"],
        document_id=ids["document_id"],
        processing_job_id=ids["job_id"],
        document_version_id="document-version-1",
    )

    async with database.sessions() as session:
        orchestrator = DurableParallelOrchestrator(session, gpu_scope)
        planned = await orchestrator.persist_plan(
            _plan(ids, shard_count=1),
            page_number_by_id={"page-1": 1},
            required_levels=ALL_LEVELS,
            validator_revisions=BINDINGS,
            operation_key="gpu-plan-v6",
        )
        shard = planned.shards[0].row
        invocation = GpuProviderInvocation(
            tenant_id=ids["tenant_id"],
            job_id=ids["job_id"],
            project_id=ids["project_id"],
            document_id=ids["document_id"],
            document_version_id="document-version-1",
            page_id=None,
            provider="runpod",
            provider_key=provider_key,
            endpoint_id=endpoint_id,
            idempotency_key="gpu-invocation-v6",
            request_manifest_sha256=runtime_sha256({"gpu": "request-manifest"}),
            status="running",
            input_bucket="source",
            input_object_key=f"tenants/{ids['tenant_id']}/source/document.pdf",
            input_sha256=input_sha256,
            output_object_key=f"tenants/{ids['tenant_id']}/derived/result.json",
            options={},
            model_revision=model_revision,
            runtime_image_digest=runtime_image_digest,
            adapter_version=adapter_version,
            transition_policy={},
            provider_job_id=provider_job_id,
            provider_status="RUNNING",
            attempt_count=1,
            max_attempts=3,
        )
        session.add(invocation)
        await session.flush()
        request_sha256 = runtime_sha256(
            {"shard_id": str(shard.id), "invocation_id": str(invocation.id)}
        )
        dispatched = await orchestrator.dispatch(
            shard.id,
            attempt_kind=AttemptKind.PRIMARY,
            pool_key="mineru-runpod",
            model_id="mineru-3.4.4-pipeline",
            model_revision=model_revision,
            runtime_identity=runtime_image_digest,
            route_policy_version="router-v6",
            request_sha256=request_sha256,
            provider_invocation_id=invocation.id,
            operation_key="gpu-dispatch-v6",
        )
        attempt = dispatched.row
        await orchestrator.start(
            attempt.id,
            worker_id=worker_id,
            operation_key="gpu-start-v6",
        )
        completed_at = utcnow()
        result_id = "gpu-result-v6"
        await orchestrator.receive_output(
            attempt.id,
            AttemptOutput(
                prediction_uri=invocation.output_object_key,
                prediction_sha256=output_sha256,
                completed_at=completed_at,
                cost=CostRecord(
                    gpu_seconds=Decimal("1.25"),
                    provider_cost=Decimal("0.125"),
                    user_credits=Decimal("0"),
                ),
            ),
            output_summary={
                "provider_invocation_id": str(invocation.id),
                "provider_job_id": provider_job_id,
                "provider_key": provider_key,
                "endpoint_id": endpoint_id,
                "result_id": result_id,
                "output_bytes": 128,
                "warning_count": 0,
                "completion_source": "poll",
                "schema_version": "1.0",
                "raw_provider_response_sha256": raw_provider_sha256,
            },
            operation_key="gpu-output-v6",
        )
        _, validation = _validation(
            page_id="page-1",
            required_levels=ALL_LEVELS,
            authority_available=True,
        )
        decision = Arbitrator().arbitrate_numeric(
            "gpu-block-v6",
            (
                ArbitrationCandidate(
                    attempt_id=str(attempt.id),
                    prediction_sha256=output_sha256,
                    hard_gate_pass=True,
                    numeric_value=Decimal("1"),
                    structure_fingerprint=runtime_sha256({"gpu": "structure"}),
                    independent_family="mineru",
                    authority_exact=True,
                    native_exact=True,
                    pixel_specialist_exact=True,
                    source_coverage=1.0,
                    structure_score=1.0,
                    cross_model_agreement=1.0,
                    runtime_reliability=1.0,
                ),
            ),
            authority_required=True,
        )
        result_manifest = {
            "schema_version": "1.0",
            "invocation_id": str(invocation.id),
            "job_id": str(ids["job_id"]),
            "tenant_id": str(ids["tenant_id"]),
            "provider": "runpod",
            "provider_job_id": provider_job_id,
            "endpoint_id": endpoint_id,
            "provider_key": provider_key,
            "model_revision": model_revision,
            "runtime_image_digest": runtime_image_digest,
            "adapter_version": adapter_version,
            "result_id": result_id,
            "output_object_key": invocation.output_object_key,
            "output_sha256": f"sha256:{output_sha256}",
            "output_bytes": 128,
            "metrics": {
                "gpu_seconds": "1.25",
                "estimated_cost_usd": "0.125",
            },
            "warning_count": 0,
            "warning_sha256": [],
            "raw_provider_response_sha256": raw_provider_sha256,
            "completion_source": "poll",
        }
        result_manifest_sha256 = runtime_sha256(result_manifest)
        output_envelope = {
            "schema_version": "parallel-v6-output-admission-1.0",
            "issuer": "akc-api",
            "tenant_id": str(ids["tenant_id"]),
            "collection_id": str(ids["collection_id"]),
            "processing_job_id": str(ids["job_id"]),
            "document_id": str(ids["document_id"]),
            "document_version_id": "document-version-1",
            "shard_id": str(shard.id),
            "attempt_id": str(attempt.id),
            "expected_input_sha256": input_sha256,
            "expected_shard_input_sha256": shard.input_sha256,
            "expected_request_sha256": request_sha256,
            "expected_output_object_key": invocation.output_object_key,
            "expected_model_revision": model_revision,
            "expected_runtime_image_digest": runtime_image_digest,
            "expected_adapter_version": adapter_version,
        }
        verification = sign_parallel_v6_verification(
            {
                "schema_version": "parallel-v6-verification-1.0",
                "issuer": "akc-api",
                "tenant_id": str(ids["tenant_id"]),
                "collection_id": str(ids["collection_id"]),
                "processing_job_id": str(ids["job_id"]),
                "document_id": str(ids["document_id"]),
                "document_version_id": "document-version-1",
                "shard_id": str(shard.id),
                "attempt_id": str(attempt.id),
                "provider_invocation_id": str(invocation.id),
                "output_envelope_sha256": runtime_sha256(output_envelope),
                "result_manifest_sha256": result_manifest_sha256,
                "output_sha256": output_sha256,
                "operation_prefix": "gpu-verification-v6",
                "required_validation_levels": [int(level) for level in ValidationLevel],
                "validator_revisions": {
                    str(int(level)): {
                        "validator_key": BINDINGS[level].validator_key,
                        "validator_revision": BINDINGS[level].validator_revision,
                    }
                    for level in ValidationLevel
                },
                "arbitration_policy_version": "authority-arbitration-v6",
                "validation_digest": validation.digest,
                "arbitration_decision_sha256": decision.decision_sha256,
                "selected_attempt_id": str(attempt.id),
                "logical_block_key": "gpu-block-v6",
                "credit_amount": "1",
            },
            signing_key=signing_key,
        )
        invocation.options = {
            "parallel_v6": output_envelope,
            "parallel_v6_verification": verification,
        }
        invocation.status = "completed"
        invocation.provider_status = "COMPLETED"
        invocation.result_manifest = result_manifest
        invocation.result_manifest_sha256 = result_manifest_sha256
        invocation.completion_source = "poll"
        invocation.completed_at = completed_at
        await session.flush()

        with pytest.raises(ParallelRuntimeConflict, match="signature"):
            await admit_gpu_invocation_result(
                session,
                gpu_scope,
                invocation.id,
                validation,
                decision,
                worker_id=worker_id,
                signing_key=b"wrong-parallel-v6-signing-key-32-bytes",
            )
        assert attempt.state == "OUTPUT_RECEIVED"
        assert await session.scalar(select(func.count(AttemptValidation.id))) == 0
        admitted = await admit_gpu_invocation_result(
            session,
            gpu_scope,
            invocation.id,
            validation,
            decision,
            worker_id=worker_id,
            signing_key=signing_key,
        )
        assert admitted.accepted
        assert admitted.attempt.state == "ACCEPTED"
        replay = await admit_gpu_invocation_result(
            session,
            gpu_scope,
            invocation.id,
            validation,
            decision,
            worker_id=worker_id,
            signing_key=signing_key,
        )
        assert replay.acceptance is not None and replay.acceptance.replayed
        await session.commit()

    async with database.sessions() as session:
        assert await session.scalar(select(func.count(AttemptValidation.id))) == 7
        assert await session.scalar(select(func.count(AcceptedBlock.id))) == 1
        consumes = list(
            (
                await session.scalars(
                    select(CreditLedger).where(CreditLedger.entry_type == "consume")
                )
            ).all()
        )
        assert len(consumes) == 1
        assert consumes[0].job_id == ids["job_id"]
        assert Decimal(consumes[0].credits) == Decimal("1")
        account = await session.scalar(
            select(CreditAccount).where(CreditAccount.tenant_id == ids["tenant_id"])
        )
        assert account is not None
        assert Decimal(account.balance) == Decimal("19")
        assert Decimal(account.reserved) == Decimal("1")


@pytest.mark.asyncio
async def test_flush_only_scope_rolls_state_and_events_back_together(
    orchestrator_db: tuple[Database, dict[str, Any]],
) -> None:
    database, ids = orchestrator_db
    async with database.sessions() as session:
        # SQLite defers its physical transaction until a write; force the
        # caller-owned boundary before the orchestrator opens a SAVEPOINT.
        await session.execute(text("BEGIN IMMEDIATE"))
        orchestrator = DurableParallelOrchestrator(session, _scope(ids))
        await orchestrator.persist_plan(
            _plan(ids, shard_count=1),
            page_number_by_id={"page-1": 1},
            required_levels=ALL_LEVELS,
            validator_revisions=BINDINGS,
            operation_key="plan-rollback",
        )
        assert await session.scalar(select(func.count(ParallelParseShard.id))) == 1
        assert await session.scalar(select(func.count(CollectionEvent.id))) == 1
        await session.rollback()

    async with database.sessions() as session:
        assert await session.scalar(select(func.count(ParallelParseShard.id))) == 0
        assert await session.scalar(select(func.count(CollectionEvent.id))) == 0
        wrong_scope = ParallelRuntimeScope(
            tenant_id=uuid.uuid4(),
            collection_id=ids["collection_id"],
            document_id=ids["document_id"],
        )
        orchestrator = DurableParallelOrchestrator(session, wrong_scope)
        with pytest.raises(ParallelRuntimeConflict):
            await orchestrator.persist_plan(
                _plan(ids, shard_count=1),
                page_number_by_id={"page-1": 1},
                required_levels=ALL_LEVELS,
                validator_revisions=BINDINGS,
                operation_key="plan-wrong-tenant",
            )
