"""Production-callable, resumable orchestration for the Structara v6 runtime.

The scheduler owns orchestration, not trust. Provider output becomes visible to
this coordinator only after the existing signed-output admission boundary has
accepted it.  The durable runtime port owns all mutations to parse attempts,
validator receipts, arbitration, credit settlement, recovery, continuity, and
finalization.  This module composes those boundaries as a checkpointed saga.

Every side effect receives a deterministic operation key.  A crash after a
side effect but before checkpoint persistence therefore replays the same
content-bound operation instead of creating another attempt or charge.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from akc_api.models import ProcessingJob
from akc_parallel_runtime import (
    AdaptiveRouter,
    AdaptiveShardPredictor,
    ArbitrationCandidate,
    ArbitrationDecision,
    Arbitrator,
    AttemptKind,
    BackpressureSnapshot,
    CandidateObservation,
    ContinuityEdge,
    ContinuityMerger,
    ContinuityMergeResult,
    DeterministicShardPlanner,
    EndpointPool,
    EndpointPoolRegistry,
    FinalizationResult,
    FinalizationUnit,
    Finalizer,
    HealthTransition,
    HedgeController,
    InfrastructureObservation,
    LineageEdge,
    PageClass,
    PageDescriptor,
    ParsedBlock,
    ParseShard,
    PoolWorker,
    QualityEstimate,
    RecipeProfile,
    RecoveryCandidate,
    RecoveryDecision,
    RecoveryPlanner,
    RecoveryScope,
    RecoveryTask,
    RegionLevel,
    RouteCandidate,
    RouteDecision,
    RouteRequest,
    RouterStage,
    RoutingUnavailable,
    ShardOutput,
    ShardPlan,
    ValidationPolicy,
    ValidationResult,
    ValidatorPipeline,
    VerificationState,
    WorkerHealthRegistry,
    WorkerSnapshot,
    canonical_sha256,
    evaluate_backpressure,
    require_sha256,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .trusted_v6_admission import (
    PersistedEd25519AdmissionVerifier,
    TrustedAdmissionContext,
    TrustedAdmissionVerifier,
    admission_receipt_sha256,
)

_CHECKPOINT_KEY = "parallel_v6_autonomous_pipeline"
_SCHEMA_VERSION = "6.0.0"


class PipelineExecutionMode(StrEnum):
    PRODUCTION = "production"
    TEST = "test"


class PipelinePhase(StrEnum):
    INITIALIZED = "initialized"
    PLANNED = "planned"
    ROUTED = "routed"
    WAITING_OUTPUTS = "waiting_outputs"
    RECOVERING = "recovering"
    CONTINUITY = "continuity"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


class ShardPhase(StrEnum):
    PLANNED = "planned"
    ROUTED = "routed"
    WAITING = "waiting"
    RECOVERING = "recovering"
    VERIFIED = "verified"
    UNRESOLVED = "unresolved"


class ProviderPollState(StrEnum):
    PENDING = "pending"
    STRAGGLER = "straggler"
    COMPLETED = "completed"
    FAILED = "failed"


class AdmissionEvidenceKind(StrEnum):
    PRODUCTION_SIGNED = "production_signed"
    TEST_ONLY = "test_only"


class PipelineCheckpointConflict(RuntimeError):
    """The stored saga revision or immutable input differs from the caller."""


class PipelineContractError(RuntimeError):
    """A provider/runtime callback violated the fail-closed coordinator contract."""


@dataclass(frozen=True, slots=True)
class RouteEstimateBinding:
    recipe_id: str
    worker_id: str
    estimate: QualityEstimate


@dataclass(frozen=True, slots=True)
class PipelineInventory:
    pools: tuple[EndpointPool, ...]
    pool_workers: tuple[PoolWorker, ...]
    recipes: tuple[RecipeProfile, ...]
    workers: tuple[WorkerSnapshot, ...]
    estimates: tuple[RouteEstimateBinding, ...]
    recipe_pool_ids: tuple[tuple[str, str], ...]
    backpressure: BackpressureSnapshot

    def __post_init__(self) -> None:
        recipe_ids = [item.recipe_id for item in self.recipes]
        worker_ids = [item.worker_id for item in self.workers]
        if len(recipe_ids) != len(set(recipe_ids)) or len(worker_ids) != len(set(worker_ids)):
            raise ValueError("pipeline recipe and worker identities must be unique")
        mapping = dict(self.recipe_pool_ids)
        if len(mapping) != len(self.recipe_pool_ids) or set(mapping) != set(recipe_ids):
            raise ValueError("every recipe must map to exactly one isolated endpoint pool")
        pool_ids = {pool.pool_id for pool in self.pools}
        if set(mapping.values()) - pool_ids:
            raise ValueError("recipe references an unknown endpoint pool")
        estimate_keys = [(item.recipe_id, item.worker_id) for item in self.estimates]
        if len(estimate_keys) != len(set(estimate_keys)):
            raise ValueError("quality estimates must be unique per recipe and worker")

    @property
    def estimate_map(self) -> dict[tuple[str, str], QualityEstimate]:
        return {(item.recipe_id, item.worker_id): item.estimate for item in self.estimates}

    @property
    def recipe_pool_map(self) -> dict[str, str]:
        return dict(self.recipe_pool_ids)


@dataclass(frozen=True, slots=True)
class V6PipelineJobSpec:
    tenant_id: str
    collection_id: str
    processing_job_id: str
    document_id: str
    document_version_id: str
    source_sha256: str
    release_manifest_sha256: str
    pages: tuple[PageDescriptor, ...]
    orchestration_started_at: datetime
    language: str = "ko"
    private_processing: bool = True
    external_api_allowed: bool = False
    production_canary: bool = False
    native_comparison_required: bool = False
    authority_required: bool = False
    differential_required: bool = False
    multimodal_required: bool = False
    downstream_required: bool = True
    credit_per_shard: Decimal = Decimal("1")
    max_recovery_attempts: int = 1
    speculative_dispatch: bool = True
    continuity_edges: tuple[ContinuityEdge, ...] = ()
    lineage_edges: tuple[LineageEdge, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "collection_id",
            "processing_job_id",
            "document_id",
        ):
            try:
                uuid.UUID(getattr(self, name))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{name} must be a UUID") from exc
        if not self.document_version_id or not self.language or not self.pages:
            raise ValueError("document version, language, and pages are required")
        require_sha256(self.source_sha256, field_name="source_sha256")
        require_sha256(
            self.release_manifest_sha256,
            field_name="release_manifest_sha256",
        )
        if (
            self.orchestration_started_at.tzinfo is None
            or self.orchestration_started_at.utcoffset() is None
        ):
            raise ValueError("orchestration_started_at must be timezone-aware")
        if self.private_processing and self.external_api_allowed:
            raise ValueError("private processing cannot allow external APIs")
        if self.credit_per_shard <= 0:
            raise ValueError("credit_per_shard must be positive")
        if self.max_recovery_attempts not in {0, 1, 2}:
            raise ValueError("max_recovery_attempts must be bounded to zero, one, or two")


@dataclass(frozen=True, slots=True)
class SubmissionReceipt:
    submission_id: str
    attempt_id: str
    shard_id: str
    recipe_id: str
    worker_id: str
    attempt_kind: AttemptKind
    operation_key: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.submission_id,
                self.attempt_id,
                self.shard_id,
                self.recipe_id,
                self.worker_id,
                self.operation_key,
            )
        ):
            raise ValueError("submission receipt identities are required")


@dataclass(frozen=True, slots=True)
class AdmittedProviderCandidate:
    submission_id: str
    attempt_id: str
    shard_id: str
    prediction_uri: str
    prediction_sha256: str
    admission_receipt_sha256: str
    evidence_kind: AdmissionEvidenceKind
    provider_key: str
    provider_job_id: str
    endpoint_id: str
    model_revision: str
    runtime_image_digest: str
    observation: CandidateObservation
    shard_output: ShardOutput
    independent_family: str
    structure_fingerprint: str
    source_geometry_exact: bool
    downstream_consistent: bool
    recovery_scopes: tuple[RecoveryScope, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "prediction_sha256",
            "admission_receipt_sha256",
            "structure_fingerprint",
        ):
            value = getattr(self, name)
            if len(value) != 64:
                raise ValueError(f"{name} must be an unprefixed SHA-256 digest")
        if not all(
            (
                self.independent_family,
                self.prediction_uri,
                self.provider_key,
                self.provider_job_id,
                self.endpoint_id,
                self.model_revision,
                self.runtime_image_digest,
            )
        ):
            raise ValueError("provider candidate identity is incomplete")
        require_sha256(self.prediction_sha256, field_name="prediction_sha256")
        require_sha256(
            self.admission_receipt_sha256,
            field_name="admission_receipt_sha256",
        )
        require_sha256(self.structure_fingerprint, field_name="structure_fingerprint")
        if not self.runtime_image_digest.startswith("sha256:"):
            raise ValueError("runtime_image_digest must be an exact sha256 image digest")
        require_sha256(
            self.runtime_image_digest.removeprefix("sha256:"),
            field_name="runtime_image_digest",
        )

    @property
    def signed_material_sha256(self) -> str:
        """Bind semantic observations and parsed content, not only an opaque URI."""

        return canonical_sha256(
            {
                "submission_id": self.submission_id,
                "attempt_id": self.attempt_id,
                "shard_id": self.shard_id,
                "prediction_uri": self.prediction_uri,
                "prediction_sha256": self.prediction_sha256,
                "provider_key": self.provider_key,
                "provider_job_id": self.provider_job_id,
                "endpoint_id": self.endpoint_id,
                "model_revision": self.model_revision,
                "runtime_image_digest": self.runtime_image_digest,
                "observation": self.observation,
                "shard_output": self.shard_output,
                "independent_family": self.independent_family,
                "structure_fingerprint": self.structure_fingerprint,
                "source_geometry_exact": self.source_geometry_exact,
                "downstream_consistent": self.downstream_consistent,
                "recovery_scopes": self.recovery_scopes,
            }
        )


@dataclass(frozen=True, slots=True)
class ProviderPoll:
    state: ProviderPollState
    candidate: AdmittedProviderCandidate | None = None
    reason_codes: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0
    predicted_p95_seconds: float = 1.0
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.state is ProviderPollState.COMPLETED and self.candidate is None:
            raise ValueError("completed provider polls require an admitted candidate")
        if self.state is not ProviderPollState.COMPLETED and self.candidate is not None:
            raise ValueError("only completed provider polls may carry a candidate")
        if self.elapsed_seconds < 0 or self.predicted_p95_seconds <= 0:
            raise ValueError("provider timing must be non-negative with positive p95")
        if self.observed_at is not None and (
            self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None
        ):
            raise ValueError("provider observation time must be timezone-aware")


class AutonomousV6RuntimePort(Protocol):
    """Callback boundary implemented with existing API/RunPod adapters in production.

    ``poll_output`` MUST return ``COMPLETED`` only after the existing signed
    output-admission callback has persisted and content-bound the provider
    result.  All methods MUST implement content-bound idempotency by
    ``operation_key``.
    """

    async def persist_plan(
        self, spec: V6PipelineJobSpec, plan: ShardPlan, *, operation_key: str
    ) -> None: ...

    async def record_route(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        decision: RouteDecision,
        *,
        pool_id: str,
        operation_key: str,
    ) -> None: ...

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
    ) -> SubmissionReceipt: ...

    async def poll_output(self, receipt: SubmissionReceipt) -> ProviderPoll: ...

    async def record_infrastructure_health(
        self,
        receipt: SubmissionReceipt,
        observation: InfrastructureObservation,
        transition: HealthTransition,
        *,
        operation_key: str,
    ) -> None: ...

    async def reject_candidate(
        self,
        spec: V6PipelineJobSpec,
        receipt: SubmissionReceipt,
        validation: ValidationResult | None,
        *,
        reason_codes: tuple[str, ...],
        operation_key: str,
    ) -> None: ...

    async def settle_candidate(
        self,
        spec: V6PipelineJobSpec,
        receipt: SubmissionReceipt,
        candidate: AdmittedProviderCandidate,
        validation: ValidationResult,
        decision: ArbitrationDecision,
        *,
        logical_block_key: str,
        credit_amount: Decimal,
        operation_key: str,
    ) -> None: ...

    async def record_recovery(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        task: RecoveryTask,
        *,
        operation_key: str,
    ) -> None: ...

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
    ) -> None: ...

    async def schedule_selective_replay(
        self,
        spec: V6PipelineJobSpec,
        receipt: SubmissionReceipt,
        *,
        impacted_object_ids: tuple[str, ...],
        operation_key: str,
    ) -> None: ...

    async def supersede_duplicate(
        self,
        receipt: SubmissionReceipt,
        *,
        winner_attempt_id: str,
        operation_key: str,
    ) -> None: ...

    async def persist_continuity(
        self,
        spec: V6PipelineJobSpec,
        result: ContinuityMergeResult,
        *,
        operation_key: str,
    ) -> None: ...

    async def finalize(
        self,
        spec: V6PipelineJobSpec,
        result: FinalizationResult,
        *,
        operation_key: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class AcceptedCandidateSummary:
    attempt_id: str
    prediction_sha256: str
    state: VerificationState
    source_refs: tuple[str, ...]
    provenance_attempt_ids: tuple[str, ...]
    shard_output: ShardOutput
    production_evidence: bool

    def __post_init__(self) -> None:
        if not self.attempt_id or not self.source_refs or not self.provenance_attempt_ids:
            raise ValueError("accepted candidate summary requires complete provenance")
        require_sha256(self.prediction_sha256, field_name="prediction_sha256")


@dataclass(frozen=True, slots=True)
class ShardCheckpoint:
    shard_id: str
    phase: ShardPhase
    primary_recipe_id: str | None = None
    primary_worker_id: str | None = None
    primary_pool_id: str | None = None
    secondary_recipe_id: str | None = None
    secondary_worker_id: str | None = None
    submissions: tuple[SubmissionReceipt, ...] = ()
    winner: AcceptedCandidateSummary | None = None
    base_attempt_id: str | None = None
    base_prediction_sha256: str | None = None
    recovery_scopes: tuple[RecoveryScope, ...] = ()
    recovery_scope_candidates: tuple[RecoveryScope, ...] = ()
    failure_codes: tuple[str, ...] = ()
    recovery_attempts: int = 0
    recovery_family_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.shard_id or self.recovery_attempts < 0:
            raise ValueError("shard checkpoint identity or recovery count is invalid")
        attempt_ids = [item.attempt_id for item in self.submissions]
        submission_ids = [item.submission_id for item in self.submissions]
        if len(attempt_ids) != len(set(attempt_ids)) or len(submission_ids) != len(
            set(submission_ids)
        ):
            raise ValueError("checkpoint submissions must be unique")
        if any(item.shard_id != self.shard_id for item in self.submissions):
            raise ValueError("checkpoint submission crossed shard scope")
        if self.phase is ShardPhase.VERIFIED and self.winner is None:
            raise ValueError("verified shard checkpoint requires a winner")
        if self.winner is not None and self.winner.attempt_id not in set(attempt_ids):
            raise ValueError("checkpoint winner is not one of its submitted attempts")
        if self.phase is ShardPhase.UNRESOLVED and self.winner is not None:
            raise ValueError("unresolved shard checkpoint cannot carry a winner")


@dataclass(frozen=True, slots=True)
class PipelineCheckpoint:
    job_id: str
    document_id: str
    document_version_id: str
    spec_sha256: str
    revision: int
    phase: PipelinePhase
    plan_sha256: str | None = None
    shards: tuple[ShardCheckpoint, ...] = ()
    merge_sha256: str | None = None
    finalization_sha256: str | None = None
    publishable: bool = False
    production_evidence: bool = False
    blocker_codes: tuple[str, ...] = ()
    last_operation_key: str = "initialize"

    def __post_init__(self) -> None:
        if self.revision < 0 or not self.document_version_id:
            raise ValueError("checkpoint revision and spec digest are invalid")
        try:
            uuid.UUID(self.job_id)
            uuid.UUID(self.document_id)
        except ValueError as exc:
            raise ValueError("checkpoint job and document scope must be UUIDs") from exc
        require_sha256(self.spec_sha256, field_name="spec_sha256")
        shard_ids = [item.shard_id for item in self.shards]
        if len(shard_ids) != len(set(shard_ids)):
            raise ValueError("checkpoint shard ids must be unique")
        if self.production_evidence and (
            not self.publishable or self.phase is not PipelinePhase.COMPLETED
        ):
            raise ValueError("production evidence requires a publishable completed checkpoint")

    def material(self) -> dict[str, Any]:
        serialized = _jsonable(dataclasses.asdict(self))
        if not isinstance(serialized, dict):
            raise PipelineContractError("checkpoint serialization did not produce an object")
        return {str(key): item for key, item in serialized.items()}

    @property
    def checkpoint_sha256(self) -> str:
        return canonical_sha256(self.material())

    def to_dict(self) -> dict[str, Any]:
        material = self.material()
        return {
            "schema_version": _SCHEMA_VERSION,
            **material,
            "checkpoint_sha256": self.checkpoint_sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PipelineCheckpoint:
        expected = {
            "schema_version",
            "job_id",
            "document_id",
            "document_version_id",
            "spec_sha256",
            "revision",
            "phase",
            "plan_sha256",
            "shards",
            "merge_sha256",
            "finalization_sha256",
            "publishable",
            "production_evidence",
            "blocker_codes",
            "last_operation_key",
            "checkpoint_sha256",
        }
        if set(value) != expected or value.get("schema_version") != _SCHEMA_VERSION:
            raise PipelineCheckpointConflict("pipeline checkpoint shape is invalid")
        shards_raw = value.get("shards")
        if not isinstance(shards_raw, list):
            raise PipelineCheckpointConflict("pipeline checkpoint shards are invalid")
        checkpoint = cls(
            job_id=str(value["job_id"]),
            document_id=str(value["document_id"]),
            document_version_id=str(value["document_version_id"]),
            spec_sha256=str(value["spec_sha256"]),
            revision=int(value["revision"]),
            phase=PipelinePhase(str(value["phase"])),
            plan_sha256=_optional_string(value.get("plan_sha256")),
            shards=tuple(_shard_checkpoint_from_dict(item) for item in shards_raw),
            merge_sha256=_optional_string(value.get("merge_sha256")),
            finalization_sha256=_optional_string(value.get("finalization_sha256")),
            publishable=bool(value["publishable"]),
            production_evidence=bool(value["production_evidence"]),
            blocker_codes=tuple(str(item) for item in value["blocker_codes"]),
            last_operation_key=str(value["last_operation_key"]),
        )
        if value.get("checkpoint_sha256") != checkpoint.checkpoint_sha256:
            raise PipelineCheckpointConflict("pipeline checkpoint digest mismatch")
        return checkpoint


class PipelineCheckpointStore(Protocol):
    async def load(self, *, tenant_id: str, job_id: str) -> PipelineCheckpoint | None: ...

    async def save(
        self,
        *,
        tenant_id: str,
        checkpoint: PipelineCheckpoint,
        expected_revision: int | None,
        occurred_at: datetime,
    ) -> PipelineCheckpoint: ...


class SqlAlchemyProcessingJobCheckpointStore:
    """CAS checkpoint persistence in the existing ``ProcessingJob.progress`` JSON."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    def _uuid(value: str) -> uuid.UUID:
        try:
            return uuid.UUID(value)
        except ValueError as exc:
            raise PipelineCheckpointConflict("checkpoint scope is not a UUID") from exc

    async def load(self, *, tenant_id: str, job_id: str) -> PipelineCheckpoint | None:
        async with self._sessions() as session:
            job = await session.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.tenant_id == self._uuid(tenant_id),
                    ProcessingJob.id == self._uuid(job_id),
                )
            )
            if job is None or job.job_type != "parallel_v6":
                raise PipelineCheckpointConflict("parallel v6 processing job is outside scope")
            progress = job.progress if isinstance(job.progress, dict) else {}
            raw = progress.get(_CHECKPOINT_KEY)
            if raw is None:
                return None
            if not isinstance(raw, Mapping):
                raise PipelineCheckpointConflict("stored parallel v6 checkpoint is malformed")
            checkpoint = PipelineCheckpoint.from_dict(raw)
            if checkpoint.job_id != job_id:
                raise PipelineCheckpointConflict("checkpoint processing job identity mismatch")
            if job.document_id is None or checkpoint.document_id != str(job.document_id):
                raise PipelineCheckpointConflict("checkpoint document identity mismatch")
            return checkpoint

    async def save(
        self,
        *,
        tenant_id: str,
        checkpoint: PipelineCheckpoint,
        expected_revision: int | None,
        occurred_at: datetime,
    ) -> PipelineCheckpoint:
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("checkpoint time must be timezone-aware")
        async with self._sessions() as session, session.begin():
            job = await session.scalar(
                select(ProcessingJob)
                .where(
                    ProcessingJob.tenant_id == self._uuid(tenant_id),
                    ProcessingJob.id == self._uuid(checkpoint.job_id),
                )
                .with_for_update()
            )
            if job is None or job.job_type != "parallel_v6":
                raise PipelineCheckpointConflict("parallel v6 processing job is outside scope")
            progress = dict(job.progress) if isinstance(job.progress, dict) else {}
            raw = progress.get(_CHECKPOINT_KEY)
            if raw is not None and not isinstance(raw, Mapping):
                raise PipelineCheckpointConflict("stored parallel v6 checkpoint is malformed")
            current = PipelineCheckpoint.from_dict(raw) if isinstance(raw, Mapping) else None
            if current is not None and current.checkpoint_sha256 == checkpoint.checkpoint_sha256:
                return current
            observed_revision = current.revision if current is not None else None
            if observed_revision != expected_revision:
                raise PipelineCheckpointConflict(
                    "checkpoint CAS mismatch: "
                    f"expected {expected_revision}, observed {observed_revision}"
                )
            required_revision = 0 if expected_revision is None else expected_revision + 1
            if checkpoint.revision != required_revision:
                raise PipelineCheckpointConflict("checkpoint revision did not advance exactly once")
            if current is not None and current.spec_sha256 != checkpoint.spec_sha256:
                raise PipelineCheckpointConflict("pipeline spec changed after execution started")
            if job.document_id is None or checkpoint.document_id != str(job.document_id):
                raise PipelineCheckpointConflict("checkpoint document identity mismatch")
            if current is None and job.status in {"completed", "failed", "cancelled"}:
                raise PipelineCheckpointConflict("terminal processing job cannot start a new saga")
            progress[_CHECKPOINT_KEY] = checkpoint.to_dict()
            job.progress = progress
            if job.started_at is None:
                job.started_at = occurred_at
            if checkpoint.phase is PipelinePhase.COMPLETED:
                job.status = "completed"
                job.completed_at = occurred_at
                job.error = None
            elif checkpoint.phase is PipelinePhase.NEEDS_REVIEW:
                job.status = "waiting_review"
                job.error = {"codes": list(checkpoint.blocker_codes)}
            elif checkpoint.phase is PipelinePhase.BLOCKED:
                job.status = "paused"
                job.error = {"codes": list(checkpoint.blocker_codes)}
            else:
                job.status = "running"
            await session.flush()
        return checkpoint


@dataclass(frozen=True, slots=True)
class PipelineRunResult:
    checkpoint: PipelineCheckpoint

    @property
    def terminal(self) -> bool:
        return self.checkpoint.phase in {
            PipelinePhase.COMPLETED,
            PipelinePhase.NEEDS_REVIEW,
            PipelinePhase.BLOCKED,
        }


class AutonomousV6PipelineCoordinator:
    """Drive one processing job through the complete v6 safety pipeline."""

    def __init__(
        self,
        *,
        store: PipelineCheckpointStore,
        runtime: AutonomousV6RuntimePort,
        inventory: PipelineInventory,
        mode: PipelineExecutionMode,
        trusted_admission_verifier: TrustedAdmissionVerifier | None = None,
        clock: Callable[[], datetime] | None = None,
        shard_predictor: AdaptiveShardPredictor | None = None,
        health_registry: WorkerHealthRegistry | None = None,
    ) -> None:
        self._store = store
        self._runtime = runtime
        self._inventory = inventory
        self._mode = mode
        self._trusted_admission_verifier = trusted_admission_verifier
        self._clock = clock or (lambda: datetime.now(UTC))
        self._planner = DeterministicShardPlanner(shard_predictor or AdaptiveShardPredictor())
        self._router = AdaptiveRouter()
        self._validator = ValidatorPipeline()
        self._arbitrator = Arbitrator()
        self._recovery = RecoveryPlanner()
        self._continuity = ContinuityMerger()
        self._finalizer = Finalizer()
        self._hedges = HedgeController()
        self._health = health_registry or WorkerHealthRegistry()
        self._pools = EndpointPoolRegistry()
        for pool in inventory.pools:
            self._pools.register_pool(pool)
        for worker in inventory.pool_workers:
            self._pools.attach_worker(worker)
        for worker in inventory.workers:
            self._health.register(
                worker_id=worker.worker_id,
                model_revision=worker.model_revision,
                runtime_image_digest=worker.runtime_image_digest,
                capabilities=worker.capabilities,
                warm=worker.warm,
                cached_models=worker.cached_models,
                estimated_available_at=worker.estimated_available_at,
            )
        self._validate_inventory_identity()

    def _validate_inventory_identity(self) -> None:
        pool_by_id = {pool.pool_id: pool for pool in self._inventory.pools}
        recipe_by_id = {recipe.recipe_id: recipe for recipe in self._inventory.recipes}
        for recipe_id, pool_id in self._inventory.recipe_pool_ids:
            recipe = recipe_by_id[recipe_id]
            pool = pool_by_id[pool_id]
            if (
                recipe.model_revision != pool.model_revision
                or recipe.runtime_image_digest != pool.runtime_stack.runtime_image_digest
                or not recipe.capabilities.issubset(pool.capabilities)
            ):
                raise ValueError("recipe identity differs from its isolated endpoint pool")

    @staticmethod
    def _operation(spec: V6PipelineJobSpec, *parts: object) -> str:
        return f"v6:{spec.processing_job_id}:{canonical_sha256(parts)[:24]}"

    @staticmethod
    def _spec_sha256(spec: V6PipelineJobSpec) -> str:
        return canonical_sha256(spec)

    def _plan(self, spec: V6PipelineJobSpec) -> ShardPlan:
        return self._planner.plan(
            document_id=spec.document_id,
            document_version_id=spec.document_version_id,
            source_sha256=spec.source_sha256,
            pages=spec.pages,
        )

    async def _save(
        self,
        spec: V6PipelineJobSpec,
        current: PipelineCheckpoint | None,
        **changes: Any,
    ) -> PipelineCheckpoint:
        expected = current.revision if current is not None else None
        if current is None:
            initial_phase = changes.pop("phase", PipelinePhase.INITIALIZED)
            if not isinstance(initial_phase, PipelinePhase):
                raise PipelineContractError("initial checkpoint phase is invalid")
            checkpoint = PipelineCheckpoint(
                job_id=spec.processing_job_id,
                document_id=spec.document_id,
                document_version_id=spec.document_version_id,
                spec_sha256=self._spec_sha256(spec),
                revision=0,
                phase=initial_phase,
                **changes,
            )
        else:
            checkpoint = replace(current, revision=current.revision + 1, **changes)
        return await self._store.save(
            tenant_id=spec.tenant_id,
            checkpoint=checkpoint,
            expected_revision=expected,
            occurred_at=self._clock(),
        )

    def _route_request(self, spec: V6PipelineJobSpec, shard: ParseShard) -> RouteRequest:
        pages = {page.page_id: page for page in spec.pages}
        owned = tuple(pages[page_id] for page_id in shard.primary_page_ids)
        classes = {page.page_class for page in owned}
        high_risk = bool(
            classes
            & {
                PageClass.COMPLEX_LAYOUT,
                PageClass.LONG_TABLE,
                PageClass.FORMULA_HEAVY,
                PageClass.PHOTOGRAPHED,
            }
        )
        return RouteRequest(
            stage=RouterStage.PAGE,
            required_capabilities=frozenset({shard.required_worker_class}),
            language=spec.language,
            high_risk=high_risk,
            private_processing=spec.private_processing,
            external_api_allowed=spec.external_api_allowed,
            financial_numeric=spec.authority_required,
            long_complex_table=PageClass.LONG_TABLE in classes,
            photographed_low_quality=PageClass.PHOTOGRAPHED in classes,
            production_canary=spec.production_canary,
        )

    def _decision(self, spec: V6PipelineJobSpec, shard: ParseShard) -> RouteDecision:
        return self._router.route(
            self._route_request(spec, shard),
            recipes=self._inventory.recipes,
            workers=self._inventory.workers,
            estimates=self._inventory.estimate_map,
        )

    def _recovery_decision(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        *,
        excluded_families: frozenset[str],
        excluded_workers: frozenset[str] = frozenset(),
    ) -> RouteDecision:
        request = replace(
            self._route_request(spec, shard),
            stage=RouterStage.RECOVERY,
            prior_template_failure=True,
            excluded_worker_ids=excluded_workers,
            excluded_independent_families=excluded_families,
        )
        return self._router.route(
            request,
            recipes=self._inventory.recipes,
            workers=tuple(
                self._health.snapshot(worker.worker_id)
                for worker in self._inventory.workers
            ),
            estimates=self._inventory.estimate_map,
        )

    async def _record_provider_health(
        self,
        spec: V6PipelineJobSpec,
        receipt: SubmissionReceipt,
        poll: ProviderPoll,
    ) -> None:
        reasons = tuple(code.casefold() for code in poll.reason_codes)

        def reason_contains(*needles: str) -> bool:
            return any(needle in code for code in reasons for needle in needles)

        failed = poll.state is ProviderPollState.FAILED
        observation = InfrastructureObservation(
            observed_at=poll.observed_at or self._clock(),
            ping=not (failed and reason_contains("connection", "network", "dns")),
            process=not (failed and reason_contains("process", "runner", "worker_lost")),
            gpu=not (failed and reason_contains("gpu", "cuda", "oom")),
            ram=not (failed and reason_contains("ram", "memory", "oom")),
            disk=not (failed and reason_contains("disk", "storage")),
            model_loaded=not (failed and reason_contains("model_load", "model_missing")),
            cuda_ready=not (failed and reason_contains("cuda", "gpu")),
            request_response=not failed,
            heartbeat=not (failed and reason_contains("heartbeat", "worker_lost")),
            model_identity_matches=not reason_contains("model_identity_mismatch"),
            checksum_matches=not reason_contains("model_checksum_mismatch", "checksum_mismatch"),
            memory_slope_exceeded=reason_contains("memory_slope"),
            latency_p99_spike=poll.state is ProviderPollState.STRAGGLER,
        )
        before = self._health.snapshot(receipt.worker_id).state
        snapshot = self._health.record_infrastructure(receipt.worker_id, observation)
        if snapshot.state is before:
            return
        transition = self._health.transitions(receipt.worker_id)[-1]
        sink = getattr(self._runtime, "record_infrastructure_health", None)
        if sink is not None:
            await sink(
                receipt,
                observation,
                transition,
                operation_key=self._operation(
                    spec,
                    "worker-health",
                    receipt.attempt_id,
                    transition.to_state.value,
                    observation.observed_at.isoformat(),
                ),
            )

    def _recipe_family(self, recipe_id: str) -> str:
        recipe = next(
            (item for item in self._inventory.recipes if item.recipe_id == recipe_id),
            None,
        )
        if recipe is None:
            raise PipelineContractError("attempt references an unknown recipe")
        return recipe.independent_family

    def _pool_for(self, route: RouteCandidate) -> str:
        pool_id = self._inventory.recipe_pool_map[route.recipe.recipe_id]
        workers = {worker.worker_id for worker in self._pools.workers(pool_id)}
        if route.worker.worker_id not in workers:
            raise PipelineContractError("adaptive route escaped its isolated endpoint pool")
        return pool_id

    @staticmethod
    def _route_by_ids(
        decision: RouteDecision, recipe_id: str | None, worker_id: str | None
    ) -> RouteCandidate | None:
        if recipe_id is None or worker_id is None:
            return None
        for candidate in (decision.primary, decision.secondary):
            if candidate is not None and (
                candidate.recipe.recipe_id,
                candidate.worker.worker_id,
            ) == (recipe_id, worker_id):
                return candidate
        raise PipelineContractError("checkpointed route differs from deterministic routing")

    def _validation_policy(self, spec: V6PipelineJobSpec, shard: ParseShard) -> ValidationPolicy:
        return ValidationPolicy(
            expected_page_ids=shard.primary_page_ids,
            native_comparison_required=spec.native_comparison_required,
            authority_required=spec.authority_required,
            differential_required=spec.differential_required,
            multimodal_required=spec.multimodal_required,
            downstream_required=spec.downstream_required,
        )

    @staticmethod
    def _logical_block_key(shard: ParseShard) -> str:
        return f"shard:{shard.shard_id}"

    @staticmethod
    def _source_refs(candidate: AdmittedProviderCandidate) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                ref for block in candidate.shard_output.blocks for ref in block.source_refs
            )
        )

    async def _assert_candidate_scope(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        receipt: SubmissionReceipt,
        candidate: AdmittedProviderCandidate,
    ) -> bool:
        if (
            candidate.submission_id != receipt.submission_id
            or candidate.attempt_id != receipt.attempt_id
            or candidate.shard_id != shard.shard_id
            or candidate.shard_output.shard_id != shard.shard_id
            or candidate.shard_output.primary_page_ids != shard.primary_page_ids
            or candidate.shard_output.context_page_ids != shard.context_page_ids
            or candidate.observation.actual_page_ids != shard.primary_page_ids
            or candidate.observation.block_count != len(candidate.shard_output.blocks)
        ):
            raise PipelineContractError("admitted provider output crossed immutable shard scope")
        recipe = next(
            (item for item in self._inventory.recipes if item.recipe_id == receipt.recipe_id),
            None,
        )
        worker = next(
            (item for item in self._inventory.workers if item.worker_id == receipt.worker_id),
            None,
        )
        if (
            recipe is None
            or worker is None
            or candidate.model_revision != recipe.model_revision
            or candidate.model_revision != worker.model_revision
            or candidate.runtime_image_digest != recipe.runtime_image_digest
            or candidate.runtime_image_digest != worker.runtime_image_digest
        ):
            raise PipelineContractError("provider output crossed pinned model or runtime scope")
        if self._mode is not PipelineExecutionMode.PRODUCTION:
            return False
        verifier = self._trusted_admission_verifier
        if (
            candidate.evidence_kind is not AdmissionEvidenceKind.PRODUCTION_SIGNED
            or verifier is None
            or type(verifier) is not PersistedEd25519AdmissionVerifier
        ):
            raise PipelineContractError(
                "production pipeline requires the approved persisted Ed25519 verifier"
            )
        expected = TrustedAdmissionContext(
            tenant_id=spec.tenant_id,
            collection_id=spec.collection_id,
            processing_job_id=spec.processing_job_id,
            document_id=spec.document_id,
            document_version_id=spec.document_version_id,
            source_sha256=spec.source_sha256,
            shard_id=shard.shard_id,
            submission_id=receipt.submission_id,
            attempt_id=receipt.attempt_id,
            dispatch_operation_key=receipt.operation_key,
            recipe_id=receipt.recipe_id,
            worker_id=receipt.worker_id,
            provider_key=candidate.provider_key,
            provider_job_id=candidate.provider_job_id,
            endpoint_id=candidate.endpoint_id,
            prediction_uri=candidate.prediction_uri,
            prediction_sha256=candidate.prediction_sha256,
            candidate_material_sha256=candidate.signed_material_sha256,
            model_revision=candidate.model_revision,
            runtime_image_digest=candidate.runtime_image_digest,
            release_manifest_sha256=spec.release_manifest_sha256,
        )
        if candidate.admission_receipt_sha256 != admission_receipt_sha256(expected):
            raise PipelineContractError("production admission receipt identity is invalid")
        if not await verifier.verify(expected):
            raise PipelineContractError("persisted signed admission verification failed")
        return True

    @staticmethod
    def _assert_submission_receipt(
        shard: ParseShard,
        route: RouteCandidate,
        attempt_kind: AttemptKind,
        operation_key: str,
        receipt: SubmissionReceipt,
    ) -> None:
        if (
            receipt.shard_id != shard.shard_id
            or receipt.recipe_id != route.recipe.recipe_id
            or receipt.worker_id != route.worker.worker_id
            or receipt.attempt_kind is not attempt_kind
            or receipt.operation_key != operation_key
        ):
            raise PipelineContractError(
                "runtime submission receipt crossed immutable dispatch scope"
            )

    async def run(self, spec: V6PipelineJobSpec, *, max_transitions: int = 64) -> PipelineRunResult:
        if max_transitions < 1:
            raise ValueError("max_transitions must be positive")
        checkpoint = await self._store.load(
            tenant_id=spec.tenant_id,
            job_id=spec.processing_job_id,
        )
        spec_sha256 = self._spec_sha256(spec)
        if checkpoint is not None and checkpoint.spec_sha256 != spec_sha256:
            raise PipelineCheckpointConflict("pipeline job spec changed during resume")
        if checkpoint is not None and (
            checkpoint.document_id != spec.document_id
            or checkpoint.document_version_id != spec.document_version_id
        ):
            raise PipelineCheckpointConflict("pipeline document scope changed during resume")
        if checkpoint is None:
            checkpoint = await self._save(
                spec,
                None,
                phase=PipelinePhase.INITIALIZED,
                last_operation_key=self._operation(spec, "initialize"),
            )
        for _ in range(max_transitions):
            if checkpoint.phase in {
                PipelinePhase.COMPLETED,
                PipelinePhase.NEEDS_REVIEW,
                PipelinePhase.BLOCKED,
            }:
                return PipelineRunResult(checkpoint)
            plan = self._plan(spec)
            if checkpoint.phase is PipelinePhase.INITIALIZED:
                operation = self._operation(spec, "plan", canonical_sha256(plan))
                await self._runtime.persist_plan(spec, plan, operation_key=operation)
                checkpoint = await self._save(
                    spec,
                    checkpoint,
                    phase=PipelinePhase.PLANNED,
                    plan_sha256=canonical_sha256(plan),
                    shards=tuple(
                        ShardCheckpoint(shard_id=shard.shard_id, phase=ShardPhase.PLANNED)
                        for shard in plan.shards
                    ),
                    last_operation_key=operation,
                )
                continue
            if checkpoint.plan_sha256 != canonical_sha256(plan):
                raise PipelineCheckpointConflict("deterministic shard plan changed during resume")
            if checkpoint.phase is PipelinePhase.PLANNED:
                checkpoint = await self._route_all(spec, plan, checkpoint)
                continue
            if checkpoint.phase is PipelinePhase.ROUTED:
                checkpoint = await self._dispatch_all(spec, plan, checkpoint)
                continue
            if checkpoint.phase in {
                PipelinePhase.WAITING_OUTPUTS,
                PipelinePhase.RECOVERING,
            }:
                next_checkpoint, made_progress = await self._poll_all(spec, plan, checkpoint)
                checkpoint = next_checkpoint
                if not made_progress and checkpoint.phase in {
                    PipelinePhase.WAITING_OUTPUTS,
                    PipelinePhase.RECOVERING,
                }:
                    return PipelineRunResult(checkpoint)
                continue
            if checkpoint.phase is PipelinePhase.CONTINUITY:
                checkpoint = await self._merge(spec, plan, checkpoint)
                continue
            if checkpoint.phase is PipelinePhase.FINALIZING:
                checkpoint = await self._finalize(spec, plan, checkpoint)
                continue
            raise PipelineContractError(f"unsupported pipeline phase: {checkpoint.phase}")
        return PipelineRunResult(checkpoint)

    async def _route_all(
        self,
        spec: V6PipelineJobSpec,
        plan: ShardPlan,
        checkpoint: PipelineCheckpoint,
    ) -> PipelineCheckpoint:
        updated: list[ShardCheckpoint] = []
        by_id = {item.shard_id: item for item in checkpoint.shards}
        for shard in plan.shards:
            current = by_id[shard.shard_id]
            decision = self._decision(spec, shard)
            pool_id = self._pool_for(decision.primary)
            operation = self._operation(spec, "route", shard.shard_id, canonical_sha256(decision))
            await self._runtime.record_route(
                spec,
                shard,
                decision,
                pool_id=pool_id,
                operation_key=operation,
            )
            updated.append(
                replace(
                    current,
                    phase=ShardPhase.ROUTED,
                    primary_recipe_id=decision.primary.recipe.recipe_id,
                    primary_worker_id=decision.primary.worker.worker_id,
                    primary_pool_id=pool_id,
                    secondary_recipe_id=(
                        decision.secondary.recipe.recipe_id if decision.secondary else None
                    ),
                    secondary_worker_id=(
                        decision.secondary.worker.worker_id if decision.secondary else None
                    ),
                )
            )
        return await self._save(
            spec,
            checkpoint,
            phase=PipelinePhase.ROUTED,
            shards=tuple(updated),
            last_operation_key=self._operation(spec, "routes-complete"),
        )

    async def _dispatch_all(
        self,
        spec: V6PipelineJobSpec,
        plan: ShardPlan,
        checkpoint: PipelineCheckpoint,
    ) -> PipelineCheckpoint:
        admission = evaluate_backpressure(self._inventory.backpressure)
        if not admission.admitted:
            return await self._save(
                spec,
                checkpoint,
                phase=PipelinePhase.BLOCKED,
                blocker_codes=admission.reason_codes,
                last_operation_key=self._operation(spec, "backpressure-blocked"),
            )
        updated: list[ShardCheckpoint] = []
        by_id = {item.shard_id: item for item in checkpoint.shards}
        for shard in plan.shards:
            current = by_id[shard.shard_id]
            decision = self._decision(spec, shard)
            primary = self._route_by_ids(
                decision, current.primary_recipe_id, current.primary_worker_id
            )
            if primary is None:
                raise PipelineContractError("checkpoint lost its primary route")
            submissions = list(current.submissions)
            operation = self._operation(spec, "dispatch", shard.shard_id, "primary")
            primary_receipt = await self._runtime.submit_attempt(
                spec,
                shard,
                primary,
                attempt_kind=AttemptKind.PRIMARY,
                parent_attempt_id=None,
                recovery_task=None,
                operation_key=operation,
            )
            self._assert_submission_receipt(
                shard,
                primary,
                AttemptKind.PRIMARY,
                operation,
                primary_receipt,
            )
            submissions.append(primary_receipt)
            if decision.speculative and spec.speculative_dispatch and decision.secondary:
                secondary = self._route_by_ids(
                    decision,
                    current.secondary_recipe_id,
                    current.secondary_worker_id,
                )
                if secondary is None:
                    raise PipelineContractError("speculative route lost its independent candidate")
                operation = self._operation(spec, "dispatch", shard.shard_id, "challenger")
                secondary_receipt = await self._runtime.submit_attempt(
                    spec,
                    shard,
                    secondary,
                    attempt_kind=AttemptKind.CHALLENGER,
                    parent_attempt_id=submissions[0].attempt_id,
                    recovery_task=None,
                    operation_key=operation,
                )
                self._assert_submission_receipt(
                    shard,
                    secondary,
                    AttemptKind.CHALLENGER,
                    operation,
                    secondary_receipt,
                )
                submissions.append(secondary_receipt)
            updated.append(
                replace(
                    current,
                    phase=ShardPhase.WAITING,
                    submissions=tuple(submissions),
                )
            )
        return await self._save(
            spec,
            checkpoint,
            phase=PipelinePhase.WAITING_OUTPUTS,
            shards=tuple(updated),
            last_operation_key=self._operation(spec, "dispatch-complete"),
        )

    async def _poll_all(
        self,
        spec: V6PipelineJobSpec,
        plan: ShardPlan,
        checkpoint: PipelineCheckpoint,
    ) -> tuple[PipelineCheckpoint, bool]:
        updated: list[ShardCheckpoint] = []
        made_progress = False
        by_id = {item.shard_id: item for item in checkpoint.shards}
        for shard in plan.shards:
            current = by_id[shard.shard_id]
            if current.phase in {ShardPhase.VERIFIED, ShardPhase.UNRESOLVED}:
                updated.append(current)
                continue
            next_shard, progressed = await self._poll_shard(spec, shard, current)
            made_progress = made_progress or progressed
            updated.append(next_shard)
        if all(item.phase in {ShardPhase.VERIFIED, ShardPhase.UNRESOLVED} for item in updated):
            next_phase = (
                PipelinePhase.CONTINUITY
                if all(item.phase is ShardPhase.VERIFIED for item in updated)
                else PipelinePhase.FINALIZING
            )
            made_progress = True
        elif any(item.phase is ShardPhase.RECOVERING for item in updated):
            next_phase = PipelinePhase.RECOVERING
        else:
            next_phase = PipelinePhase.WAITING_OUTPUTS
        if not made_progress:
            return checkpoint, False
        saved = await self._save(
            spec,
            checkpoint,
            phase=next_phase,
            shards=tuple(updated),
            last_operation_key=self._operation(spec, "poll", checkpoint.revision),
        )
        return saved, True

    async def _poll_shard(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        current: ShardCheckpoint,
    ) -> tuple[ShardCheckpoint, bool]:
        active = tuple(
            receipt
            for receipt in current.submissions
            if (
                receipt.attempt_kind is AttemptKind.RECOVERY
                if current.phase is ShardPhase.RECOVERING
                else receipt.attempt_kind is not AttemptKind.RECOVERY
            )
        )
        if not active:
            raise PipelineContractError("waiting shard has no active provider submission")
        polls = [(receipt, await self._runtime.poll_output(receipt)) for receipt in active]
        for receipt, poll in polls:
            await self._record_provider_health(spec, receipt, poll)
        completed = [
            (receipt, poll.candidate)
            for receipt, poll in polls
            if poll.state is ProviderPollState.COMPLETED and poll.candidate is not None
        ]
        for receipt, candidate in completed:
            try:
                production_verified = await self._assert_candidate_scope(
                    spec,
                    shard,
                    receipt,
                    candidate,
                )
            except PipelineContractError as exc:
                operation = self._operation(spec, "reject", receipt.attempt_id, str(exc))
                await self._runtime.reject_candidate(
                    spec,
                    receipt,
                    None,
                    reason_codes=("production_or_scope_evidence_invalid",),
                    operation_key=operation,
                )
                return await self._recover_or_resolve(
                    spec,
                    shard,
                    current,
                    receipt,
                    candidate,
                    ("production_or_scope_evidence_invalid",),
                ), True
            policy = self._validation_policy(spec, shard)
            validation = self._validator.validate(candidate.observation, policy)
            if not validation.passed:
                failures = tuple(
                    sorted(
                        {finding.code for finding in validation.findings}
                        or {"semantic_validation_failed"}
                    )
                )
                operation = self._operation(spec, "reject", receipt.attempt_id, validation.digest)
                await self._runtime.reject_candidate(
                    spec,
                    receipt,
                    validation,
                    reason_codes=failures,
                    operation_key=operation,
                )
                return await self._recover_or_resolve(
                    spec,
                    shard,
                    current,
                    receipt,
                    candidate,
                    failures,
                    validation=validation,
                ), True
            if current.phase is ShardPhase.RECOVERING:
                return await self._accept_recovery(
                    spec,
                    shard,
                    current,
                    receipt,
                    candidate,
                    validation,
                    production_verified=production_verified,
                ), True
            arbitration_candidate = ArbitrationCandidate(
                attempt_id=receipt.attempt_id,
                prediction_sha256=candidate.prediction_sha256,
                hard_gate_pass=True,
                numeric_value=None,
                structure_fingerprint=candidate.structure_fingerprint,
                independent_family=candidate.independent_family,
                source_geometry_exact=candidate.source_geometry_exact,
                downstream_consistent=candidate.downstream_consistent,
                source_coverage=candidate.observation.source_coverage,
                structure_score=1.0,
                runtime_reliability=1.0,
            )
            decision = self._arbitrator.arbitrate_structure(
                shard.shard_id,
                (arbitration_candidate,),
            )
            if not decision.accepted:
                operation = self._operation(
                    spec,
                    "reject",
                    receipt.attempt_id,
                    decision.decision_sha256,
                )
                await self._runtime.reject_candidate(
                    spec,
                    receipt,
                    validation,
                    reason_codes=decision.reason_codes,
                    operation_key=operation,
                )
                return await self._recover_or_resolve(
                    spec,
                    shard,
                    current,
                    receipt,
                    candidate,
                    decision.reason_codes,
                    validation=validation,
                ), True
            operation = self._operation(spec, "settle", shard.shard_id, decision.decision_sha256)
            await self._runtime.settle_candidate(
                spec,
                receipt,
                candidate,
                validation,
                decision,
                logical_block_key=self._logical_block_key(shard),
                credit_amount=spec.credit_per_shard,
                operation_key=operation,
            )
            for other in active:
                if other.attempt_id != receipt.attempt_id:
                    await self._runtime.supersede_duplicate(
                        other,
                        winner_attempt_id=receipt.attempt_id,
                        operation_key=self._operation(
                            spec, "supersede", other.attempt_id, receipt.attempt_id
                        ),
                    )
            summary = AcceptedCandidateSummary(
                attempt_id=receipt.attempt_id,
                prediction_sha256=candidate.prediction_sha256,
                state=decision.verification_state,
                source_refs=self._source_refs(candidate),
                provenance_attempt_ids=(receipt.attempt_id,),
                shard_output=candidate.shard_output,
                production_evidence=production_verified,
            )
            return replace(current, phase=ShardPhase.VERIFIED, winner=summary), True

        stragglers = [
            (receipt, poll) for receipt, poll in polls if poll.state is ProviderPollState.STRAGGLER
        ]
        if stragglers and len(active) == 1 and current.secondary_recipe_id:
            route_decision = self._decision(spec, shard)
            secondary = self._route_by_ids(
                route_decision,
                current.secondary_recipe_id,
                current.secondary_worker_id,
            )
            if secondary is not None:
                receipt, poll = stragglers[0]
                hedge = self._hedges.decide(
                    original_attempt_id=receipt.attempt_id,
                    shard_id=shard.shard_id,
                    elapsed_seconds=poll.elapsed_seconds,
                    predicted_p95_seconds=poll.predicted_p95_seconds,
                    alternate_worker_id=secondary.worker.worker_id,
                    original_verified=False,
                    occurred_at=self._clock(),
                    idempotency_key=self._operation(spec, "hedge-decision", receipt.attempt_id),
                )
                if hedge.launch:
                    operation = self._operation(spec, "dispatch", shard.shard_id, "hedge")
                    hedge_receipt = await self._runtime.submit_attempt(
                        spec,
                        shard,
                        secondary,
                        attempt_kind=AttemptKind.HEDGE,
                        parent_attempt_id=receipt.attempt_id,
                        recovery_task=None,
                        operation_key=operation,
                    )
                    self._assert_submission_receipt(
                        shard,
                        secondary,
                        AttemptKind.HEDGE,
                        operation,
                        hedge_receipt,
                    )
                    return replace(current, submissions=(*current.submissions, hedge_receipt)), True
        if all(poll.state is ProviderPollState.FAILED for _, poll in polls):
            reasons = tuple(
                sorted(
                    {
                        code
                        for _, poll in polls
                        for code in (poll.reason_codes or ("provider_failed",))
                    }
                )
            )
            return await self._retry_provider_failure(
                spec,
                shard,
                current,
                tuple(receipt for receipt, _ in polls),
                reasons,
            ), True
        return current, False

    async def _retry_provider_failure(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        current: ShardCheckpoint,
        failed_receipts: tuple[SubmissionReceipt, ...],
        failure_codes: tuple[str, ...],
    ) -> ShardCheckpoint:
        if current.recovery_attempts >= spec.max_recovery_attempts:
            return replace(current, phase=ShardPhase.UNRESOLVED, failure_codes=failure_codes)
        excluded_workers = frozenset(receipt.worker_id for receipt in failed_receipts)
        try:
            decision = self._recovery_decision(
                spec,
                shard,
                excluded_families=frozenset(current.recovery_family_ids),
                excluded_workers=excluded_workers,
            )
        except RoutingUnavailable:
            return replace(current, phase=ShardPhase.UNRESOLVED, failure_codes=failure_codes)
        route = decision.primary
        operation = self._operation(
            spec,
            "dispatch-provider-retry",
            shard.shard_id,
            current.recovery_attempts + 1,
        )
        receipt = await self._runtime.submit_attempt(
            spec,
            shard,
            route,
            attempt_kind=AttemptKind.RETRY,
            parent_attempt_id=failed_receipts[0].attempt_id,
            recovery_task=None,
            operation_key=operation,
        )
        self._assert_submission_receipt(shard, route, AttemptKind.RETRY, operation, receipt)
        families = tuple(
            dict.fromkeys((*current.recovery_family_ids, route.recipe.independent_family))
        )
        return replace(
            current,
            phase=ShardPhase.WAITING,
            submissions=(*current.submissions, receipt),
            failure_codes=failure_codes,
            recovery_attempts=current.recovery_attempts + 1,
            recovery_family_ids=families,
        )

    async def _recover_or_resolve(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        current: ShardCheckpoint,
        receipt: SubmissionReceipt,
        candidate: AdmittedProviderCandidate,
        failure_codes: tuple[str, ...],
        *,
        validation: ValidationResult | None = None,
    ) -> ShardCheckpoint:
        if current.recovery_attempts >= spec.max_recovery_attempts or validation is None:
            return replace(
                current,
                phase=ShardPhase.UNRESOLVED,
                base_attempt_id=receipt.attempt_id,
                base_prediction_sha256=candidate.prediction_sha256,
                failure_codes=failure_codes,
            )
        proposed_scopes = candidate.recovery_scopes or _default_recovery_scopes(
            shard, failure_codes
        )
        scope_candidates = _merge_recovery_scopes(
            current.recovery_scope_candidates, proposed_scopes
        )
        scopes = scope_candidates
        if current.recovery_attempts and current.recovery_scopes:
            broader = self._recovery.next_broader_scope(
                current.recovery_scopes[0], scope_candidates
            )
            if broader is None:
                return replace(
                    current,
                    phase=ShardPhase.UNRESOLVED,
                    base_attempt_id=receipt.attempt_id,
                    base_prediction_sha256=candidate.prediction_sha256,
                    failure_codes=failure_codes,
                )
            scopes = (broader,)
        failed_family = self._recipe_family(receipt.recipe_id)
        excluded_families = frozenset((*current.recovery_family_ids, failed_family))
        try:
            route_decision = self._recovery_decision(
                spec,
                shard,
                excluded_families=excluded_families,
            )
        except RoutingUnavailable:
            return replace(
                current,
                phase=ShardPhase.UNRESOLVED,
                base_attempt_id=receipt.attempt_id,
                base_prediction_sha256=candidate.prediction_sha256,
                failure_codes=failure_codes,
            )
        route = route_decision.primary
        operation = self._operation(
            spec,
            "recovery-plan",
            shard.shard_id,
            current.recovery_attempts + 1,
        )
        try:
            task = self._recovery.plan(
                base_attempt_id=receipt.attempt_id,
                base_prediction_sha256=candidate.prediction_sha256,
                scopes=scopes,
                failure_codes=frozenset(failure_codes),
                parser_recipe=route.recipe.recipe_id,
                created_at=spec.orchestration_started_at,
                idempotency_key=operation,
            )
        except ValueError:
            return replace(
                current,
                phase=ShardPhase.UNRESOLVED,
                base_attempt_id=receipt.attempt_id,
                base_prediction_sha256=candidate.prediction_sha256,
                failure_codes=(*failure_codes, "minimum_recovery_scope_unavailable"),
            )
        await self._runtime.record_recovery(spec, shard, task, operation_key=operation)
        dispatch_operation = self._operation(
            spec,
            "dispatch-recovery",
            shard.shard_id,
            current.recovery_attempts + 1,
        )
        recovery_receipt = await self._runtime.submit_attempt(
            spec,
            shard,
            route,
            attempt_kind=AttemptKind.RECOVERY,
            parent_attempt_id=receipt.attempt_id,
            recovery_task=task,
            operation_key=dispatch_operation,
        )
        self._assert_submission_receipt(
            shard,
            route,
            AttemptKind.RECOVERY,
            dispatch_operation,
            recovery_receipt,
        )
        return replace(
            current,
            phase=ShardPhase.RECOVERING,
            submissions=(*current.submissions, recovery_receipt),
            base_attempt_id=receipt.attempt_id,
            base_prediction_sha256=candidate.prediction_sha256,
            recovery_scopes=(task.scope,),
            recovery_scope_candidates=scope_candidates,
            failure_codes=failure_codes,
            recovery_attempts=current.recovery_attempts + 1,
            recovery_family_ids=tuple(
                dict.fromkeys(
                    (*current.recovery_family_ids, failed_family, route.recipe.independent_family)
                )
            ),
        )

    async def _accept_recovery(
        self,
        spec: V6PipelineJobSpec,
        shard: ParseShard,
        current: ShardCheckpoint,
        receipt: SubmissionReceipt,
        candidate: AdmittedProviderCandidate,
        validation: ValidationResult,
        *,
        production_verified: bool,
    ) -> ShardCheckpoint:
        if current.base_attempt_id is None or current.base_prediction_sha256 is None:
            raise PipelineContractError("recovery checkpoint lost its base lineage")
        operation = self._operation(
            spec, "recovery-plan", shard.shard_id, current.recovery_attempts
        )
        task = self._recovery.plan(
            base_attempt_id=current.base_attempt_id,
            base_prediction_sha256=current.base_prediction_sha256,
            scopes=current.recovery_scopes,
            failure_codes=frozenset(current.failure_codes),
            parser_recipe=receipt.recipe_id,
            created_at=spec.orchestration_started_at,
            idempotency_key=operation,
        )
        source_evidence = tuple(
            receipt_item
            for _, receipts in candidate.observation.evidence
            for receipt_item in receipts
        )
        base_receipt = next(
            (
                item
                for item in current.submissions
                if item.attempt_id == current.base_attempt_id
            ),
            None,
        )
        if base_receipt is None:
            raise PipelineContractError("recovery checkpoint lost its base attempt receipt")
        recovery_candidate = RecoveryCandidate(
            task=task,
            repair_attempt_id=receipt.attempt_id,
            prediction_sha256=candidate.prediction_sha256,
            diff_sha256=canonical_sha256(
                {
                    "base": current.base_prediction_sha256,
                    "repair": candidate.prediction_sha256,
                }
            ),
            validation=validation,
            source_evidence=source_evidence,
            base_independent_family=self._recipe_family(base_receipt.recipe_id),
            repair_independent_family=self._recipe_family(receipt.recipe_id),
            lineage_edges=spec.lineage_edges,
        )
        decision = self._recovery.accept(recovery_candidate, completed_at=self._clock())
        if not decision.accepted:
            await self._runtime.reject_candidate(
                spec,
                receipt,
                validation,
                reason_codes=decision.reason_codes,
                operation_key=self._operation(spec, "reject-recovery", receipt.attempt_id),
            )
            return replace(
                current,
                phase=ShardPhase.UNRESOLVED,
                failure_codes=decision.reason_codes,
            )
        await self._runtime.settle_recovery(
            spec,
            receipt,
            candidate,
            validation,
            decision,
            logical_block_key=self._logical_block_key(shard),
            credit_amount=spec.credit_per_shard,
            operation_key=self._operation(
                spec, "settle-recovery", shard.shard_id, decision.decision_sha256
            ),
        )
        if decision.impacted_object_ids:
            await self._runtime.schedule_selective_replay(
                spec,
                receipt,
                impacted_object_ids=decision.impacted_object_ids,
                operation_key=self._operation(
                    spec,
                    "selective-replay",
                    shard.shard_id,
                    decision.decision_sha256,
                ),
            )
        summary = AcceptedCandidateSummary(
            attempt_id=receipt.attempt_id,
            prediction_sha256=candidate.prediction_sha256,
            state=VerificationState.AUTO_REPAIRED,
            source_refs=self._source_refs(candidate),
            provenance_attempt_ids=(current.base_attempt_id, receipt.attempt_id),
            shard_output=candidate.shard_output,
            production_evidence=production_verified,
        )
        return replace(current, phase=ShardPhase.VERIFIED, winner=summary)

    async def _merge(
        self,
        spec: V6PipelineJobSpec,
        plan: ShardPlan,
        checkpoint: PipelineCheckpoint,
    ) -> PipelineCheckpoint:
        winners = [item.winner for item in checkpoint.shards]
        if any(winner is None for winner in winners):
            raise PipelineContractError("continuity cannot merge an unresolved shard")
        typed_winners = tuple(winner for winner in winners if winner is not None)
        operation = self._operation(spec, "continuity", checkpoint.plan_sha256)
        result = self._continuity.merge(
            document_version_id=spec.document_version_id,
            outputs=tuple(winner.shard_output for winner in typed_winners),
            edges=spec.continuity_edges,
            expected_page_ids=plan.owned_page_ids,
            occurred_at=self._clock(),
            idempotency_key=operation,
        )
        await self._runtime.persist_continuity(spec, result, operation_key=operation)
        return await self._save(
            spec,
            checkpoint,
            phase=PipelinePhase.FINALIZING,
            merge_sha256=result.merge_sha256,
            blocker_codes=(result.reason_codes if not result.accepted else ()),
            last_operation_key=operation,
        )

    async def _finalize(
        self,
        spec: V6PipelineJobSpec,
        plan: ShardPlan,
        checkpoint: PipelineCheckpoint,
    ) -> PipelineCheckpoint:
        by_id = {item.shard_id: item for item in checkpoint.shards}
        units: list[FinalizationUnit] = []
        for shard in plan.shards:
            item = by_id[shard.shard_id]
            if item.winner is None:
                units.append(
                    FinalizationUnit(
                        unit_id=self._logical_block_key(shard),
                        state=VerificationState.UNRESOLVED,
                        prediction_sha256=None,
                        source_refs=tuple(
                            f"page://{page_id}" for page_id in shard.primary_page_ids
                        ),
                        provenance_attempt_ids=(),
                        reason_codes=item.failure_codes or ("required_shard_unresolved",),
                    )
                )
            else:
                units.append(
                    FinalizationUnit(
                        unit_id=self._logical_block_key(shard),
                        state=item.winner.state,
                        prediction_sha256=item.winner.prediction_sha256,
                        source_refs=item.winner.source_refs,
                        provenance_attempt_ids=item.winner.provenance_attempt_ids,
                    )
                )
        if checkpoint.blocker_codes:
            units.append(
                FinalizationUnit(
                    unit_id=f"continuity:{spec.document_version_id}",
                    state=VerificationState.UNRESOLVED,
                    prediction_sha256=None,
                    source_refs=tuple(f"page://{page_id}" for page_id in plan.owned_page_ids),
                    provenance_attempt_ids=(),
                    reason_codes=checkpoint.blocker_codes,
                )
            )
        merge_sha256 = checkpoint.merge_sha256 or canonical_sha256(
            {
                "document_version_id": spec.document_version_id,
                "continuity": "not_publishable",
                "units": units,
            }
        )
        operation = self._operation(spec, "finalize", merge_sha256)
        result = self._finalizer.finalize(
            document_version_id=spec.document_version_id,
            units=tuple(units),
            merge_sha256=merge_sha256,
            occurred_at=self._clock(),
            idempotency_key=operation,
        )
        await self._runtime.finalize(spec, result, operation_key=operation)
        production_evidence = bool(
            result.publishable
            and self._mode is PipelineExecutionMode.PRODUCTION
            and all(
                item.winner is not None and item.winner.production_evidence
                for item in checkpoint.shards
            )
        )
        blocker_codes = tuple(
            sorted(
                {
                    *result.reason_codes,
                    *checkpoint.blocker_codes,
                    *(
                        code
                        for item in checkpoint.shards
                        if item.phase is ShardPhase.UNRESOLVED
                        for code in item.failure_codes
                    ),
                }
            )
        )
        return await self._save(
            spec,
            checkpoint,
            phase=(PipelinePhase.COMPLETED if result.publishable else PipelinePhase.NEEDS_REVIEW),
            finalization_sha256=result.manifest_sha256,
            publishable=result.publishable,
            production_evidence=production_evidence,
            blocker_codes=blocker_codes,
            last_operation_key=operation,
        )


def _default_recovery_scopes(
    shard: ParseShard, failure_codes: tuple[str, ...]
) -> tuple[RecoveryScope, ...]:
    if set(failure_codes) & {"C01", "cross_page_split"}:
        if len(shard.primary_page_ids) < 2:
            return ()
        page_ids = tuple(str(page_id) for page_id in shard.primary_page_ids)
        return (
            RecoveryScope(
                level=RegionLevel.PAGE_PAIR,
                scope_id=f"page-pair:{':'.join(page_ids)}",
                source_refs=tuple(f"page://{page_id}" for page_id in page_ids),
            ),
        )
    return tuple(
        RecoveryScope(
            level=RegionLevel.PAGE,
            scope_id=f"page:{page_id}",
            source_refs=(f"page://{page_id}",),
        )
        for page_id in shard.primary_page_ids
    )


def _merge_recovery_scopes(
    existing: tuple[RecoveryScope, ...], proposed: tuple[RecoveryScope, ...]
) -> tuple[RecoveryScope, ...]:
    by_id = {scope.scope_id: scope for scope in existing}
    for scope in proposed:
        previous = by_id.get(scope.scope_id)
        if previous is not None and previous != scope:
            raise PipelineContractError(
                "recovery scope identity was reused with different evidence"
            )
        by_id[scope.scope_id] = scope
    return tuple(by_id[scope_id] for scope_id in sorted(by_id))


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def _submission_from_dict(value: Mapping[str, Any]) -> SubmissionReceipt:
    return SubmissionReceipt(
        submission_id=str(value["submission_id"]),
        attempt_id=str(value["attempt_id"]),
        shard_id=str(value["shard_id"]),
        recipe_id=str(value["recipe_id"]),
        worker_id=str(value["worker_id"]),
        attempt_kind=AttemptKind(str(value["attempt_kind"])),
        operation_key=str(value["operation_key"]),
    )


def _scope_from_dict(value: Mapping[str, Any]) -> RecoveryScope:
    return RecoveryScope(
        level=RegionLevel(str(value["level"])),
        scope_id=str(value["scope_id"]),
        source_refs=tuple(str(item) for item in value["source_refs"]),
    )


def _block_from_dict(value: Mapping[str, Any]) -> ParsedBlock:
    from akc_parallel_runtime import BlockKind, MarginalRole, TableIdentity

    table_raw = value.get("table_identity")
    table = None
    if isinstance(table_raw, Mapping):
        table = TableIdentity(
            normalized_header=tuple(str(item) for item in table_raw["normalized_header"]),
            column_geometry=tuple(int(item) for item in table_raw["column_geometry"]),
            title=str(table_raw["title"]),
            unit=str(table_raw["unit"]),
            row_style=str(table_raw.get("row_style", "")),
            surrounding_text=str(table_raw.get("surrounding_text", "")),
        )
    role = value.get("marginal_role")
    return ParsedBlock(
        block_id=str(value["block_id"]),
        page_id=str(value["page_id"]),
        page_index0=int(value["page_index0"]),
        order=int(value["order"]),
        kind=BlockKind(str(value["kind"])),
        text=str(value["text"]),
        source_refs=tuple(str(item) for item in value["source_refs"]),
        heading_depth=(None if value.get("heading_depth") is None else int(value["heading_depth"])),
        marginal_role=(None if role is None else MarginalRole(str(role))),
        table_identity=table,
        table_row_count=int(value.get("table_row_count", 0)),
    )


def _summary_from_dict(value: Mapping[str, Any]) -> AcceptedCandidateSummary:
    output_raw = value["shard_output"]
    if not isinstance(output_raw, Mapping):
        raise PipelineCheckpointConflict("checkpoint shard output is malformed")
    return AcceptedCandidateSummary(
        attempt_id=str(value["attempt_id"]),
        prediction_sha256=str(value["prediction_sha256"]),
        state=VerificationState(str(value["state"])),
        source_refs=tuple(str(item) for item in value["source_refs"]),
        provenance_attempt_ids=tuple(str(item) for item in value["provenance_attempt_ids"]),
        shard_output=ShardOutput(
            shard_id=str(output_raw["shard_id"]),
            primary_page_ids=tuple(str(item) for item in output_raw["primary_page_ids"]),
            context_page_ids=tuple(str(item) for item in output_raw["context_page_ids"]),
            blocks=tuple(_block_from_dict(item) for item in output_raw["blocks"]),
        ),
        production_evidence=bool(value["production_evidence"]),
    )


def _shard_checkpoint_from_dict(value: object) -> ShardCheckpoint:
    if not isinstance(value, Mapping):
        raise PipelineCheckpointConflict("checkpoint shard entry is malformed")
    winner_raw = value.get("winner")
    return ShardCheckpoint(
        shard_id=str(value["shard_id"]),
        phase=ShardPhase(str(value["phase"])),
        primary_recipe_id=_optional_string(value.get("primary_recipe_id")),
        primary_worker_id=_optional_string(value.get("primary_worker_id")),
        primary_pool_id=_optional_string(value.get("primary_pool_id")),
        secondary_recipe_id=_optional_string(value.get("secondary_recipe_id")),
        secondary_worker_id=_optional_string(value.get("secondary_worker_id")),
        submissions=tuple(_submission_from_dict(item) for item in value["submissions"]),
        winner=(_summary_from_dict(winner_raw) if isinstance(winner_raw, Mapping) else None),
        base_attempt_id=_optional_string(value.get("base_attempt_id")),
        base_prediction_sha256=_optional_string(value.get("base_prediction_sha256")),
        recovery_scopes=tuple(_scope_from_dict(item) for item in value["recovery_scopes"]),
        recovery_scope_candidates=tuple(
            _scope_from_dict(item)
            for item in value.get("recovery_scope_candidates", value["recovery_scopes"])
        ),
        failure_codes=tuple(str(item) for item in value["failure_codes"]),
        recovery_attempts=int(value["recovery_attempts"]),
        recovery_family_ids=tuple(
            str(item) for item in value.get("recovery_family_ids", ())
        ),
    )


__all__ = [
    "AcceptedCandidateSummary",
    "AdmissionEvidenceKind",
    "AdmittedProviderCandidate",
    "AutonomousV6PipelineCoordinator",
    "AutonomousV6RuntimePort",
    "PipelineCheckpoint",
    "PipelineCheckpointConflict",
    "PipelineCheckpointStore",
    "PipelineContractError",
    "PipelineExecutionMode",
    "PipelineInventory",
    "PipelinePhase",
    "PipelineRunResult",
    "ProviderPoll",
    "ProviderPollState",
    "RouteEstimateBinding",
    "ShardCheckpoint",
    "ShardPhase",
    "SqlAlchemyProcessingJobCheckpointStore",
    "SubmissionReceipt",
    "V6PipelineJobSpec",
]
