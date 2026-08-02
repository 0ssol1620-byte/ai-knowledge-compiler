"""Real-SQLite evidence for the resumable autonomous v6 scheduler saga.

The provider/runtime port is deliberately fake: these tests prove scheduler
composition and durability without claiming external RunPod evidence.  The
production-mode case verifies that such test-only output fails closed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from akc_api.database import Base
from akc_api.models import Collection, Document, ProcessingJob, Project, Tenant, User
from akc_parallel_runtime import (
    AttemptKind,
    BackpressureSnapshot,
    BlockKind,
    CandidateObservation,
    ContinuityMergeResult,
    EndpointPool,
    EvidenceReceipt,
    FinalizationResult,
    PageClass,
    PageDescriptor,
    ParsedBlock,
    ParseShard,
    PoolWorker,
    QualityEstimate,
    RecipeProfile,
    RecoveryDecision,
    RecoveryTask,
    RouteCandidate,
    RouteDecision,
    RouteTier,
    RuntimeStack,
    ShardOutput,
    ShardPlan,
    ValidationLevel,
    ValidationResult,
    WorkerSnapshot,
    WorkerState,
    WorkerType,
    canonical_sha256,
)
from akc_scheduler.autonomous_v6_pipeline import (
    AdmissionEvidenceKind,
    AdmittedProviderCandidate,
    AutonomousV6PipelineCoordinator,
    PipelineCheckpoint,
    PipelineExecutionMode,
    PipelineInventory,
    PipelinePhase,
    ProviderPoll,
    ProviderPollState,
    RouteEstimateBinding,
    SqlAlchemyProcessingJobCheckpointStore,
    SubmissionReceipt,
    V6PipelineJobSpec,
)
from akc_scheduler.trusted_v6_admission import (
    PersistedEd25519AdmissionVerifier,
    TrustedAdmissionContext,
    admission_receipt_sha256,
    build_trusted_admission_payload,
    sign_trusted_admission_envelope,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
RELEASE_MANIFEST_SHA256 = "9" * 64
TRUSTED_KEY_ID = "structara-v6-admission-2026-08"


class Scenario(StrEnum):
    SUCCESS = "success"
    SEMANTIC_FAILURE = "semantic_failure"
    STRAGGLER = "straggler"
    RESTART = "restart"


@dataclass(frozen=True, slots=True)
class SqliteHarness:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    collection_id: uuid.UUID
    document_id: uuid.UUID
    job_id: uuid.UUID


class InMemoryPersistedAdmissionReader:
    """Test double for durable object/DB storage, not a verifier."""

    def __init__(self) -> None:
        self.envelopes: dict[str, dict[str, Any]] = {}
        self.lookups: list[str] = []

    async def load_persisted_admission_envelope(
        self,
        *,
        receipt_sha256: str,
    ) -> dict[str, Any] | None:
        self.lookups.append(receipt_sha256)
        return self.envelopes.get(receipt_sha256)


@dataclass(slots=True)
class _AdmissionSigner:
    private_key: Ed25519PrivateKey
    reader: InMemoryPersistedAdmissionReader
    signed_context_overrides: dict[str, str] | None = None
    tamper_payload_after_signing: bool = False
    tamper_candidate_after_signing: bool = False

    def seal(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        route: RouteCandidate,
        receipt: SubmissionReceipt,
        candidate: AdmittedProviderCandidate,
    ) -> AdmittedProviderCandidate:
        material = {
            "tenant_id": spec.tenant_id,
            "collection_id": spec.collection_id,
            "processing_job_id": spec.processing_job_id,
            "document_id": spec.document_id,
            "document_version_id": spec.document_version_id,
            "source_sha256": spec.source_sha256,
            "shard_id": shard.shard_id,
            "submission_id": receipt.submission_id,
            "attempt_id": receipt.attempt_id,
            "dispatch_operation_key": receipt.operation_key,
            "recipe_id": receipt.recipe_id,
            "worker_id": receipt.worker_id,
            "provider_key": candidate.provider_key,
            "provider_job_id": candidate.provider_job_id,
            "endpoint_id": candidate.endpoint_id,
            "prediction_uri": candidate.prediction_uri,
            "prediction_sha256": candidate.prediction_sha256,
            "candidate_material_sha256": candidate.signed_material_sha256,
            "model_revision": route.recipe.model_revision,
            "runtime_image_digest": route.recipe.runtime_image_digest,
            "release_manifest_sha256": spec.release_manifest_sha256,
        }
        expected = TrustedAdmissionContext(**material)
        signed_material = {**material, **(self.signed_context_overrides or {})}
        signed_context = TrustedAdmissionContext(**signed_material)
        envelope = sign_trusted_admission_envelope(
            build_trusted_admission_payload(
                signed_context,
                admission_id=str(uuid.uuid4()),
            ),
            private_key=self.private_key,
            key_id=TRUSTED_KEY_ID,
            signed_at="2026-08-01T12:00:00Z",
        )
        if self.tamper_payload_after_signing:
            payload = dict(envelope["payload"])
            payload["provider_job_id"] = "tampered-after-signing"
            envelope["payload"] = payload
        receipt_sha256 = admission_receipt_sha256(expected)
        self.reader.envelopes[receipt_sha256] = envelope
        sealed = replace(candidate, admission_receipt_sha256=receipt_sha256)
        if self.tamper_candidate_after_signing:
            sealed = replace(sealed, provider_job_id="tampered-candidate-job")
        return sealed


@pytest_asyncio.fixture
async def sqlite_harness(tmp_path: Path) -> AsyncIterator[SqliteHarness]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'autonomous-v6.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    document_id = uuid.uuid4()
    job_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with sessions() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, slug=f"v6-{tenant_id.hex[:8]}", name="V6 Test"),
                User(
                    id=user_id,
                    email=f"{user_id.hex}@example.com",
                    password_hash="not-used",  # noqa: S106
                    display_name="V6 Scheduler Test",
                ),
            ]
        )
        await session.flush()
        session.add(
            Project(
                id=project_id,
                tenant_id=tenant_id,
                name="V6 Project",
                created_by=user_id,
            )
        )
        await session.flush()
        session.add_all(
            [
                Collection(
                    id=collection_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    name="V6 Collection",
                    status="PROCESSING",
                    created_by=user_id,
                ),
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    title="Autonomous V6",
                    document_type="pdf",
                    language_codes=["ko"],
                    page_count=1,
                    status="PREFLIGHTED",
                ),
            ]
        )
        await session.flush()
        session.add(
            ProcessingJob(
                id=job_id,
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                job_type="parallel_v6",
                status="queued",
                requested_options={},
                progress={},
            )
        )
        await session.commit()
    yield SqliteHarness(
        engine=engine,
        sessions=sessions,
        tenant_id=tenant_id,
        project_id=project_id,
        collection_id=collection_id,
        document_id=document_id,
        job_id=job_id,
    )
    await engine.dispose()


class FakeAutonomousRuntime:
    """Content-bound idempotent fake for an already-admitted provider callback."""

    def __init__(
        self,
        scenario: Scenario,
        *,
        evidence_kind: AdmissionEvidenceKind = AdmissionEvidenceKind.TEST_ONLY,
        admission_signer: _AdmissionSigner | None = None,
    ) -> None:
        self.scenario = scenario
        self.evidence_kind = evidence_kind
        self.admission_signer = admission_signer
        self.operation_digests: dict[str, str] = {}
        self.receipts: dict[str, SubmissionReceipt] = {}
        self.submission_context: dict[
            str, tuple[V6PipelineJobSpec, ParseShard, RouteCandidate, AttemptKind]
        ] = {}
        self.poll_counts: dict[str, int] = {}
        self.submission_calls: list[SubmissionReceipt] = []
        self.rejections: list[tuple[str, tuple[str, ...]]] = []
        self.settlements: list[str] = []
        self.recovery_settlements: list[str] = []
        self.recovery_tasks: list[str] = []
        self.superseded: list[tuple[str, str]] = []
        self.continuity_results: list[ContinuityMergeResult] = []
        self.finalization_results: list[FinalizationResult] = []

    def _record(self, operation_key: str, value: object) -> None:
        digest = canonical_sha256(value)
        existing = self.operation_digests.setdefault(operation_key, digest)
        if existing != digest:
            raise AssertionError("operation key was reused with different content")

    async def persist_plan(
        self,
        spec: V6PipelineJobSpec,
        plan: ShardPlan,
        *,
        operation_key: str,
    ) -> None:
        self._record(operation_key, (spec.processing_job_id, plan))

    async def record_route(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        decision: RouteDecision,
        *,
        pool_id: str,
        operation_key: str,
    ) -> None:
        self._record(operation_key, (spec.processing_job_id, shard, decision, pool_id))

    async def submit_attempt(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        route: RouteCandidate,
        *,
        attempt_kind: AttemptKind,
        parent_attempt_id: str | None,
        recovery_task: RecoveryTask | None,
        operation_key: str,
    ) -> SubmissionReceipt:
        content = (
            spec.processing_job_id,
            shard,
            route,
            attempt_kind,
            parent_attempt_id,
            recovery_task,
        )
        self._record(operation_key, content)
        receipt = self.receipts.get(operation_key)
        if receipt is None:
            suffix = canonical_sha256((operation_key, content))[:24]
            receipt = SubmissionReceipt(
                submission_id=f"submission-{suffix}",
                attempt_id=f"attempt-{suffix}",
                shard_id=shard.shard_id,
                recipe_id=route.recipe.recipe_id,
                worker_id=route.worker.worker_id,
                attempt_kind=attempt_kind,
                operation_key=operation_key,
            )
            self.receipts[operation_key] = receipt
            self.submission_context[receipt.attempt_id] = (
                spec,
                shard,
                route,
                attempt_kind,
            )
            self.submission_calls.append(receipt)
        return receipt

    async def poll_output(self, receipt: SubmissionReceipt) -> ProviderPoll:
        count = self.poll_counts.get(receipt.attempt_id, 0) + 1
        self.poll_counts[receipt.attempt_id] = count
        if self.scenario is Scenario.RESTART and count == 1:
            return ProviderPoll(state=ProviderPollState.PENDING)
        if self.scenario is Scenario.STRAGGLER and receipt.attempt_kind is AttemptKind.PRIMARY:
            return ProviderPoll(
                state=ProviderPollState.STRAGGLER,
                elapsed_seconds=13,
                predicted_p95_seconds=10,
            )
        valid = self.scenario is not Scenario.SEMANTIC_FAILURE
        return ProviderPoll(
            state=ProviderPollState.COMPLETED,
            candidate=self._candidate(receipt, valid=valid),
        )

    def _candidate(
        self,
        receipt: SubmissionReceipt,
        *,
        valid: bool,
    ) -> AdmittedProviderCandidate:
        spec, shard, route, _ = self.submission_context[receipt.attempt_id]
        page_id = shard.primary_page_ids[0]
        text = f"verified:{receipt.attempt_id}"
        output = ShardOutput(
            shard_id=shard.shard_id,
            primary_page_ids=shard.primary_page_ids,
            context_page_ids=shard.context_page_ids,
            blocks=(
                ParsedBlock(
                    block_id=f"block-{canonical_sha256(receipt.attempt_id)[:20]}",
                    page_id=page_id,
                    page_index0=0,
                    order=0,
                    kind=BlockKind.PARAGRAPH,
                    text=text,
                    source_refs=(f"page://{page_id}",),
                ),
            ),
        )
        evidence = tuple(
            (
                level,
                (
                    EvidenceReceipt(
                        source_ref=f"fake://{receipt.attempt_id}/{int(level)}",
                        sha256=canonical_sha256((receipt.attempt_id, int(level))),
                        kind="fake-admitted-evidence",
                    ),
                ),
            )
            for level in (
                ValidationLevel.TRANSPORT,
                ValidationLevel.STRUCTURAL,
                ValidationLevel.DOWNSTREAM,
            )
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
            actual_page_ids=shard.primary_page_ids,
            block_count=1,
            bbox_valid=True,
            reading_order_valid=valid,
            output_nonempty=True,
            repetition_detected=False,
            source_coverage=1.0,
            downstream_available=True,
            markdown_valid=True,
            package_import_valid=True,
            source_links_valid=True,
            retrieval_valid=True,
            evidence=evidence,
        )
        prediction_sha256 = canonical_sha256((receipt.attempt_id, output))
        candidate = AdmittedProviderCandidate(
            submission_id=receipt.submission_id,
            attempt_id=receipt.attempt_id,
            shard_id=receipt.shard_id,
            prediction_uri=f"fake://outputs/{receipt.attempt_id}",
            prediction_sha256=prediction_sha256,
            admission_receipt_sha256=canonical_sha256(("admission", receipt.attempt_id)),
            evidence_kind=self.evidence_kind,
            provider_key="runpod",
            provider_job_id=f"runpod-{receipt.attempt_id}",
            endpoint_id=f"endpoint-{route.recipe.recipe_id}",
            model_revision=route.recipe.model_revision,
            runtime_image_digest=route.recipe.runtime_image_digest,
            observation=observation,
            shard_output=output,
            independent_family=route.recipe.independent_family,
            structure_fingerprint=canonical_sha256(("structure", text)),
            source_geometry_exact=True,
            downstream_consistent=True,
        )
        if self.admission_signer is not None:
            return self.admission_signer.seal(spec, shard, route, receipt, candidate)
        return candidate

    async def reject_candidate(
        self,
        spec: V6PipelineJobSpec,
        receipt: SubmissionReceipt,
        validation: ValidationResult | None,
        *,
        reason_codes: tuple[str, ...],
        operation_key: str,
    ) -> None:
        self._record(
            operation_key,
            (spec.processing_job_id, receipt, validation, reason_codes),
        )
        item = (receipt.attempt_id, reason_codes)
        if item not in self.rejections:
            self.rejections.append(item)

    async def settle_candidate(
        self,
        spec: V6PipelineJobSpec,
        receipt: SubmissionReceipt,
        candidate: AdmittedProviderCandidate,
        validation: ValidationResult,
        decision: Any,
        *,
        logical_block_key: str,
        credit_amount: Decimal,
        operation_key: str,
    ) -> None:
        self._record(
            operation_key,
            (
                spec.processing_job_id,
                receipt,
                candidate.prediction_sha256,
                validation.digest,
                decision,
                logical_block_key,
                credit_amount,
            ),
        )
        if receipt.attempt_id not in self.settlements:
            self.settlements.append(receipt.attempt_id)

    async def record_recovery(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        task: RecoveryTask,
        *,
        operation_key: str,
    ) -> None:
        self._record(operation_key, (spec.processing_job_id, shard.shard_id, task))
        if task.task_id not in self.recovery_tasks:
            self.recovery_tasks.append(task.task_id)

    async def settle_recovery(
        self,
        spec: V6PipelineJobSpec,
        receipt: SubmissionReceipt,
        candidate: AdmittedProviderCandidate,
        validation: ValidationResult,
        decision: RecoveryDecision,
        *,
        logical_block_key: str,
        credit_amount: Decimal,
        operation_key: str,
    ) -> None:
        self._record(
            operation_key,
            (
                spec.processing_job_id,
                receipt,
                candidate.prediction_sha256,
                validation.digest,
                decision,
                logical_block_key,
                credit_amount,
            ),
        )
        if receipt.attempt_id not in self.recovery_settlements:
            self.recovery_settlements.append(receipt.attempt_id)

    async def supersede_duplicate(
        self,
        receipt: SubmissionReceipt,
        *,
        winner_attempt_id: str,
        operation_key: str,
    ) -> None:
        self._record(operation_key, (receipt, winner_attempt_id))
        item = (receipt.attempt_id, winner_attempt_id)
        if item not in self.superseded:
            self.superseded.append(item)

    async def persist_continuity(
        self,
        spec: V6PipelineJobSpec,
        result: ContinuityMergeResult,
        *,
        operation_key: str,
    ) -> None:
        self._record(operation_key, (spec.processing_job_id, result))
        if result not in self.continuity_results:
            self.continuity_results.append(result)

    async def finalize(
        self,
        spec: V6PipelineJobSpec,
        result: FinalizationResult,
        *,
        operation_key: str,
    ) -> None:
        self._record(operation_key, (spec.processing_job_id, result))
        if result not in self.finalization_results:
            self.finalization_results.append(result)


class SimulatedSchedulerCrash(RuntimeError):
    pass


class CrashBeforeWaitingCheckpointStore(SqlAlchemyProcessingJobCheckpointStore):
    """Lose the dispatch checkpoint once, after the provider side effect ran."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(sessions)
        self.crashed = False

    async def save(
        self,
        *,
        tenant_id: str,
        checkpoint: PipelineCheckpoint,
        expected_revision: int | None,
        occurred_at: datetime,
    ) -> PipelineCheckpoint:
        if checkpoint.phase is PipelinePhase.WAITING_OUTPUTS and not self.crashed:
            self.crashed = True
            raise SimulatedSchedulerCrash("simulated crash after provider submission")
        return await super().save(
            tenant_id=tenant_id,
            checkpoint=checkpoint,
            expected_revision=expected_revision,
            occurred_at=occurred_at,
        )


def _inventory() -> PipelineInventory:
    capabilities = frozenset({"standard", "large_context_precision"})
    stacks = (
        RuntimeStack(
            runtime_image_digest="sha256:" + ("a" * 64),
            framework="vllm",
            cuda_version="13.0",
            serving_runtime="runpod-serverless",
        ),
        RuntimeStack(
            runtime_image_digest="sha256:" + ("b" * 64),
            framework="transformers",
            cuda_version="13.0",
            serving_runtime="runpod-serverless",
        ),
    )
    recipes = (
        RecipeProfile(
            recipe_id="mineru-primary",
            model_revision="mineru-3.4-a",
            runtime_image_digest=stacks[0].runtime_image_digest,
            tier=RouteTier.PRECISION,
            capabilities=capabilities,
            supported_languages=frozenset({"ko"}),
            independent_family="mineru",
        ),
        RecipeProfile(
            recipe_id="paddle-challenger",
            model_revision="paddleocr-vl-1.6-b",
            runtime_image_digest=stacks[1].runtime_image_digest,
            tier=RouteTier.PRECISION,
            capabilities=capabilities,
            supported_languages=frozenset({"ko"}),
            independent_family="paddle-vl",
        ),
    )
    workers = (
        WorkerSnapshot(
            worker_id="worker-mineru",
            model_revision=recipes[0].model_revision,
            runtime_image_digest=recipes[0].runtime_image_digest,
            state=WorkerState.HEALTHY,
            capabilities=capabilities,
            warm=True,
            cached_models=frozenset({recipes[0].model_revision}),
            estimated_available_at=0,
            semantic_score=99,
        ),
        WorkerSnapshot(
            worker_id="worker-paddle",
            model_revision=recipes[1].model_revision,
            runtime_image_digest=recipes[1].runtime_image_digest,
            state=WorkerState.HEALTHY,
            capabilities=capabilities,
            warm=True,
            cached_models=frozenset({recipes[1].model_revision}),
            estimated_available_at=0,
            semantic_score=96,
        ),
    )
    pools = tuple(
        EndpointPool(
            pool_id=f"pool-{index}",
            model_revision=recipe.model_revision,
            worker_type=WorkerType.FLEX,
            runtime_stack=stack,
            capabilities=capabilities,
            minimum_workers=0,
            maximum_workers=1,
        )
        for index, (recipe, stack) in enumerate(zip(recipes, stacks, strict=True), start=1)
    )
    pool_workers = tuple(
        PoolWorker(
            worker_id=worker.worker_id,
            pool_id=pool.pool_id,
            model_revision=worker.model_revision,
            runtime_stack=stack,
            gpu_type="NVIDIA L40S",
        )
        for worker, pool, stack in zip(workers, pools, stacks, strict=True)
    )
    estimates = (
        RouteEstimateBinding(
            recipe_id=recipes[0].recipe_id,
            worker_id=workers[0].worker_id,
            estimate=QualityEstimate(
                pass_hard_gate=0.99,
                numeric_exact=0.99,
                row_complete=0.99,
                repetition_probability=0.001,
                timeout_probability=0.001,
                oom_probability=0.001,
                expected_latency_seconds=5,
                expected_cost=1,
            ),
        ),
        RouteEstimateBinding(
            recipe_id=recipes[1].recipe_id,
            worker_id=workers[1].worker_id,
            estimate=QualityEstimate(
                pass_hard_gate=0.90,
                numeric_exact=0.90,
                row_complete=0.90,
                repetition_probability=0.02,
                timeout_probability=0.02,
                oom_probability=0.02,
                expected_latency_seconds=8,
                expected_cost=1.2,
            ),
        ),
    )
    return PipelineInventory(
        pools=pools,
        pool_workers=pool_workers,
        recipes=recipes,
        workers=workers,
        estimates=estimates,
        recipe_pool_ids=tuple(
            (recipe.recipe_id, pool.pool_id) for recipe, pool in zip(recipes, pools, strict=True)
        ),
        backpressure=BackpressureSnapshot(
            queue_depth=0,
            queue_high_watermark=100,
            presigned_url_seconds_remaining=1_000,
            estimated_work_seconds=5,
            object_cache_available=True,
            evaluator_capacity=2,
            database_capacity=2,
        ),
    )


def _spec(
    harness: SqliteHarness,
    *,
    complex_page: bool = False,
    production_canary: bool = False,
    speculative_dispatch: bool = True,
    max_recovery_attempts: int = 1,
) -> V6PipelineJobSpec:
    return V6PipelineJobSpec(
        tenant_id=str(harness.tenant_id),
        collection_id=str(harness.collection_id),
        processing_job_id=str(harness.job_id),
        document_id=str(harness.document_id),
        document_version_id=f"{harness.document_id}:v1",
        source_sha256="c" * 64,
        release_manifest_sha256=RELEASE_MANIFEST_SHA256,
        pages=(
            PageDescriptor(
                page_id="page-1",
                index0=0,
                page_class=(PageClass.COMPLEX_LAYOUT if complex_page else PageClass.NORMAL_SCAN),
                width_px=1600,
                height_px=2200,
                token_estimate=800,
                expected_output_tokens=1_000,
            ),
        ),
        orchestration_started_at=NOW,
        production_canary=production_canary,
        speculative_dispatch=speculative_dispatch,
        max_recovery_attempts=max_recovery_attempts,
    )


def _coordinator(
    harness: SqliteHarness,
    runtime: FakeAutonomousRuntime,
    *,
    mode: PipelineExecutionMode = PipelineExecutionMode.TEST,
    store: SqlAlchemyProcessingJobCheckpointStore | None = None,
    trusted_admission_verifier: object | None = None,
) -> AutonomousV6PipelineCoordinator:
    return AutonomousV6PipelineCoordinator(
        store=store or SqlAlchemyProcessingJobCheckpointStore(harness.sessions),
        runtime=runtime,
        inventory=_inventory(),
        mode=mode,
        trusted_admission_verifier=trusted_admission_verifier,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


async def _job(harness: SqliteHarness) -> ProcessingJob:
    async with harness.sessions() as session:
        job = await session.scalar(select(ProcessingJob).where(ProcessingJob.id == harness.job_id))
        assert job is not None
        return job


@pytest.mark.asyncio
async def test_success_persists_publishable_checkpoint_in_real_sqlite(
    sqlite_harness: SqliteHarness,
) -> None:
    runtime = FakeAutonomousRuntime(Scenario.SUCCESS)
    result = await _coordinator(sqlite_harness, runtime).run(_spec(sqlite_harness))

    assert result.terminal
    assert result.checkpoint.phase is PipelinePhase.COMPLETED
    assert result.checkpoint.publishable
    assert not result.checkpoint.production_evidence
    assert len(runtime.submission_calls) == 1
    assert len(runtime.settlements) == 1
    assert len(runtime.continuity_results) == 1
    assert runtime.continuity_results[0].accepted
    assert len(runtime.finalization_results) == 1
    assert runtime.finalization_results[0].publishable
    job = await _job(sqlite_harness)
    assert job.status == "completed"
    assert job.progress["parallel_v6_autonomous_pipeline"]["checkpoint_sha256"] == (
        result.checkpoint.checkpoint_sha256
    )


@pytest.mark.asyncio
async def test_semantic_failure_attempts_bounded_recovery_then_needs_review(
    sqlite_harness: SqliteHarness,
) -> None:
    runtime = FakeAutonomousRuntime(Scenario.SEMANTIC_FAILURE)
    result = await _coordinator(sqlite_harness, runtime).run(_spec(sqlite_harness))

    assert result.checkpoint.phase is PipelinePhase.NEEDS_REVIEW
    assert not result.checkpoint.publishable
    assert len(runtime.recovery_tasks) == 1
    assert [item.attempt_kind for item in runtime.submission_calls] == [
        AttemptKind.PRIMARY,
        AttemptKind.RECOVERY,
    ]
    assert len(runtime.rejections) == 2
    assert not runtime.settlements
    assert not runtime.recovery_settlements
    assert not runtime.finalization_results[0].publishable
    job = await _job(sqlite_harness)
    assert job.status == "waiting_review"
    assert job.error is not None


@pytest.mark.asyncio
async def test_straggler_launches_one_hedge_and_settles_only_the_winner(
    sqlite_harness: SqliteHarness,
) -> None:
    runtime = FakeAutonomousRuntime(Scenario.STRAGGLER)
    spec = _spec(
        sqlite_harness,
        complex_page=True,
        production_canary=True,
        speculative_dispatch=False,
    )
    result = await _coordinator(sqlite_harness, runtime).run(spec)

    assert result.checkpoint.phase is PipelinePhase.COMPLETED
    assert [item.attempt_kind for item in runtime.submission_calls] == [
        AttemptKind.PRIMARY,
        AttemptKind.HEDGE,
    ]
    hedge = runtime.submission_calls[1]
    assert runtime.settlements == [hedge.attempt_id]
    assert runtime.superseded == [(runtime.submission_calls[0].attempt_id, hedge.attempt_id)]


@pytest.mark.asyncio
async def test_restart_resumes_checkpoint_without_duplicate_submit_or_charge(
    sqlite_harness: SqliteHarness,
) -> None:
    runtime = FakeAutonomousRuntime(Scenario.RESTART)
    spec = _spec(sqlite_harness)
    crash_store = CrashBeforeWaitingCheckpointStore(sqlite_harness.sessions)
    with pytest.raises(SimulatedSchedulerCrash):
        await _coordinator(sqlite_harness, runtime, store=crash_store).run(spec)

    crashed_job = await _job(sqlite_harness)
    assert crashed_job.progress["parallel_v6_autonomous_pipeline"]["phase"] == "routed"
    assert len(runtime.submission_calls) == 1

    first = await _coordinator(sqlite_harness, runtime).run(spec)

    assert first.checkpoint.phase is PipelinePhase.WAITING_OUTPUTS
    assert not first.terminal
    assert len(runtime.submission_calls) == 1
    resumed = await _coordinator(sqlite_harness, runtime).run(spec)
    assert resumed.checkpoint.phase is PipelinePhase.COMPLETED
    assert len(runtime.submission_calls) == 1
    assert len(runtime.settlements) == 1

    final_revision = resumed.checkpoint.revision
    replay = await _coordinator(sqlite_harness, runtime).run(spec)
    assert replay.checkpoint.revision == final_revision
    assert len(runtime.submission_calls) == 1
    assert len(runtime.settlements) == 1
    assert len(runtime.finalization_results) == 1


@pytest.mark.asyncio
async def test_production_mode_fails_closed_on_test_only_admission_evidence(
    sqlite_harness: SqliteHarness,
) -> None:
    runtime = FakeAutonomousRuntime(
        Scenario.SUCCESS,
        evidence_kind=AdmissionEvidenceKind.TEST_ONLY,
    )
    result = await _coordinator(
        sqlite_harness,
        runtime,
        mode=PipelineExecutionMode.PRODUCTION,
    ).run(_spec(sqlite_harness, max_recovery_attempts=0))

    assert result.checkpoint.phase is PipelinePhase.NEEDS_REVIEW
    assert not result.checkpoint.publishable
    assert not result.checkpoint.production_evidence
    assert result.checkpoint.shards[0].failure_codes == ("production_or_scope_evidence_invalid",)
    assert not runtime.settlements
    assert len(runtime.rejections) == 1
    assert not runtime.finalization_results[0].publishable


def _signed_runtime_and_verifier(
    *,
    signed_context_overrides: dict[str, str] | None = None,
    tamper_payload_after_signing: bool = False,
    tamper_candidate_after_signing: bool = False,
    verifier_public_key: object | None = None,
) -> tuple[
    FakeAutonomousRuntime,
    PersistedEd25519AdmissionVerifier,
    InMemoryPersistedAdmissionReader,
]:
    private_key = Ed25519PrivateKey.generate()
    reader = InMemoryPersistedAdmissionReader()
    signer = _AdmissionSigner(
        private_key=private_key,
        reader=reader,
        signed_context_overrides=signed_context_overrides,
        tamper_payload_after_signing=tamper_payload_after_signing,
        tamper_candidate_after_signing=tamper_candidate_after_signing,
    )
    runtime = FakeAutonomousRuntime(
        Scenario.SUCCESS,
        evidence_kind=AdmissionEvidenceKind.PRODUCTION_SIGNED,
        admission_signer=signer,
    )
    public_key = private_key.public_key() if verifier_public_key is None else verifier_public_key
    verifier = PersistedEd25519AdmissionVerifier(
        reader=reader,
        public_key=public_key,  # type: ignore[arg-type]
        key_id=TRUSTED_KEY_ID,
    )
    return runtime, verifier, reader


@pytest.mark.asyncio
async def test_production_accepts_only_persisted_ed25519_exact_binding(
    sqlite_harness: SqliteHarness,
) -> None:
    runtime, verifier, reader = _signed_runtime_and_verifier()

    result = await _coordinator(
        sqlite_harness,
        runtime,
        mode=PipelineExecutionMode.PRODUCTION,
        trusted_admission_verifier=verifier,
    ).run(_spec(sqlite_harness, max_recovery_attempts=0))

    assert result.checkpoint.phase is PipelinePhase.COMPLETED
    assert result.checkpoint.publishable
    assert result.checkpoint.production_evidence
    assert result.checkpoint.shards[0].winner is not None
    assert result.checkpoint.shards[0].winner.production_evidence
    assert len(reader.lookups) == 1
    assert reader.lookups[0] in reader.envelopes
    assert len(runtime.settlements) == 1
    assert not runtime.rejections


@pytest.mark.asyncio
async def test_production_rejects_runtime_enum_and_digest_spoof_without_verifier(
    sqlite_harness: SqliteHarness,
) -> None:
    runtime = FakeAutonomousRuntime(
        Scenario.SUCCESS,
        evidence_kind=AdmissionEvidenceKind.PRODUCTION_SIGNED,
    )

    result = await _coordinator(
        sqlite_harness,
        runtime,
        mode=PipelineExecutionMode.PRODUCTION,
    ).run(_spec(sqlite_harness, max_recovery_attempts=0))

    assert result.checkpoint.phase is PipelinePhase.NEEDS_REVIEW
    assert not result.checkpoint.production_evidence
    assert not runtime.settlements
    assert runtime.rejections[0][1] == ("production_or_scope_evidence_invalid",)


class AlwaysTrueTestVerifier:
    async def verify(self, expected: TrustedAdmissionContext) -> bool:
        del expected
        return True


@pytest.mark.asyncio
async def test_production_rejects_structural_test_verifier_even_when_it_returns_true(
    sqlite_harness: SqliteHarness,
) -> None:
    runtime = FakeAutonomousRuntime(
        Scenario.SUCCESS,
        evidence_kind=AdmissionEvidenceKind.PRODUCTION_SIGNED,
    )

    result = await _coordinator(
        sqlite_harness,
        runtime,
        mode=PipelineExecutionMode.PRODUCTION,
        trusted_admission_verifier=AlwaysTrueTestVerifier(),
    ).run(_spec(sqlite_harness, max_recovery_attempts=0))

    assert result.checkpoint.phase is PipelinePhase.NEEDS_REVIEW
    assert not runtime.settlements


@pytest.mark.parametrize(
    ("signed_context_overrides", "tamper_payload", "tamper_candidate"),
    [
        (None, True, False),
        (None, False, True),
        ({"attempt_id": "attempt-from-another-job"}, False, False),
        ({"processing_job_id": str(uuid.UUID(int=1))}, False, False),
        ({"release_manifest_sha256": "8" * 64}, False, False),
    ],
    ids=(
        "signed-payload-tamper",
        "candidate-after-signing-tamper",
        "attempt-replay",
        "wrong-job-context",
        "wrong-release-context",
    ),
)
@pytest.mark.asyncio
async def test_production_rejects_tamper_replay_and_wrong_context(
    sqlite_harness: SqliteHarness,
    signed_context_overrides: dict[str, str] | None,
    tamper_payload: bool,
    tamper_candidate: bool,
) -> None:
    runtime, verifier, _ = _signed_runtime_and_verifier(
        signed_context_overrides=signed_context_overrides,
        tamper_payload_after_signing=tamper_payload,
        tamper_candidate_after_signing=tamper_candidate,
    )

    result = await _coordinator(
        sqlite_harness,
        runtime,
        mode=PipelineExecutionMode.PRODUCTION,
        trusted_admission_verifier=verifier,
    ).run(_spec(sqlite_harness, max_recovery_attempts=0))

    assert result.checkpoint.phase is PipelinePhase.NEEDS_REVIEW
    assert not result.checkpoint.publishable
    assert not result.checkpoint.production_evidence
    assert not runtime.settlements
    assert len(runtime.rejections) == 1


@pytest.mark.asyncio
async def test_production_rejects_envelope_signed_by_unpinned_key(
    sqlite_harness: SqliteHarness,
) -> None:
    wrong_public_key = Ed25519PrivateKey.generate().public_key()
    runtime, verifier, _ = _signed_runtime_and_verifier(
        verifier_public_key=wrong_public_key,
    )

    result = await _coordinator(
        sqlite_harness,
        runtime,
        mode=PipelineExecutionMode.PRODUCTION,
        trusted_admission_verifier=verifier,
    ).run(_spec(sqlite_harness, max_recovery_attempts=0))

    assert result.checkpoint.phase is PipelinePhase.NEEDS_REVIEW
    assert not result.checkpoint.production_evidence
    assert not runtime.settlements
