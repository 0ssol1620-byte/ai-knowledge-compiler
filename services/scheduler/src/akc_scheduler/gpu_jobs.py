"""Lease-based serverless GPU submission, polling, cancellation, and admission."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol, cast

from akc_api.feature_flags import cohort_enabled
from akc_api.gpu_jobs import (
    GpuInvocationSpec,
    GpuTransitionPolicy,
    GpuTransitionTarget,
    append_gpu_event,
    enqueue_gpu_invocation,
)
from akc_api.gpu_provider import (
    GpuJobPoll,
    GpuJobRequest,
    GpuJobResult,
    GpuProviderError,
    SubmittedGpuJob,
)
from akc_api.knowledge_gpu import (
    KNOWLEDGE_ARTIFACT_CONTRACT,
    KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT,
    knowledge_stage_result_counts,
    validate_knowledge_result,
    validate_knowledge_stage_result,
)
from akc_api.models import (
    AuditEvent,
    Document,
    GpuProviderAttempt,
    GpuProviderInvocation,
    JobEvent,
    ModelRegistry,
    OutboxEvent,
    ProcessingJob,
    Project,
)
from akc_api.storage import ObjectStore, UploadTarget
from akc_api.visual_gpu import (
    VISUAL_ARTIFACT_CONTRACT,
    VISUAL_RASTER_MAX_BYTES,
    VISUAL_RASTER_MAX_DIMENSION,
    VISUAL_RASTER_MAX_PIXELS,
    validate_visual_result,
    visual_attestation,
)
from akc_telemetry import (
    observe_provider_cold_start,
    record_provider_cost,
    record_provider_request,
    record_provider_revision_mismatch,
    record_unsupported_claim,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from akc_scheduler.retry_policy import classify_retry_error, decide_retry

Clock = Callable[[], datetime]
RandomSource = Callable[[], float]
_ACTIVE_STATES = (
    "queued",
    "submitting",
    "submitted",
    "running",
    "retry",
    "cancel_requested",
    "cancelling",
)
_TERMINAL_STATES = frozenset({"completed", "failed", "dead_letter", "cancelled"})
_TERMINAL_PROVIDER_FAILURES = frozenset(
    {
        "GPU_PROVIDER_JOB_FAILED",
        "GPU_PROVIDER_JOB_TIMED_OUT",
        "GPU_PROVIDER_JOB_CANCELLED",
    }
)
_ATTESTATION_ERRORS = frozenset(
    {
        "GPU_PROVIDER_RESULT_SCOPE_MISMATCH",
        "GPU_RESULT_OBJECT_SCOPE_MISMATCH",
        "GPU_RESULT_OBJECT_CHECKSUM_MISMATCH",
        "GPU_RESULT_OBJECT_INVALID",
    }
)
_APPROVED_INTERNAL_TRANSITIONS = frozenset(
    {
        ("hpd_fast", "paddle_vl"),
        ("paddle_fast", "paddle_vl"),
    }
)
_SYSTEM_RANDOM = random.SystemRandom()


class DurableGpuClient(Protocol):
    async def submit(self, request: GpuJobRequest) -> SubmittedGpuJob: ...

    async def poll_once(
        self,
        request: GpuJobRequest,
        submitted: SubmittedGpuJob,
    ) -> GpuJobPoll: ...

    async def cancel(self, submitted: SubmittedGpuJob) -> None: ...


@dataclass(frozen=True, slots=True)
class GpuWorkerPolicy:
    lease_seconds: float = 60
    provider_call_timeout_seconds: float = 30
    provider_job_timeout_seconds: float = 900
    poll_interval_seconds: float = 2
    presign_ttl_seconds: int = 1200
    backoff_base_seconds: float = 2
    backoff_max_seconds: float = 120
    backoff_jitter_ratio: float = 0.2
    max_cancel_attempts: int = 8
    max_output_bytes: int = 12 * 1024 * 1024

    def __post_init__(self) -> None:
        finite_positive = (
            self.lease_seconds,
            self.provider_call_timeout_seconds,
            self.provider_job_timeout_seconds,
            self.poll_interval_seconds,
            self.backoff_base_seconds,
            self.backoff_max_seconds,
        )
        if any(not math.isfinite(value) or value <= 0 for value in finite_positive):
            raise ValueError("GPU worker durations must be finite and positive")
        if self.lease_seconds <= self.provider_call_timeout_seconds:
            raise ValueError("GPU lease must exceed one provider control-plane call")
        if self.backoff_max_seconds < self.backoff_base_seconds:
            raise ValueError("GPU backoff maximum must be at least its base")
        if not 0 <= self.backoff_jitter_ratio <= 1:
            raise ValueError("invalid GPU backoff jitter")
        if not 600 <= self.presign_ttl_seconds <= 1800:
            raise ValueError("GPU object grants must expire in 10..30 minutes")
        if self.presign_ttl_seconds < self.provider_job_timeout_seconds:
            raise ValueError("GPU object grants must outlive the provider job timeout")
        if not 1 <= self.max_cancel_attempts <= 100:
            raise ValueError("invalid GPU cancellation attempt limit")
        if not 1024 <= self.max_output_bytes <= 64 * 1024 * 1024:
            raise ValueError("invalid GPU output verification limit")


@dataclass(frozen=True, slots=True)
class _Claim:
    invocation_id: uuid.UUID
    tenant_id: uuid.UUID
    job_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: str
    page_id: uuid.UUID | None
    provider_key: str
    endpoint_id: str
    idempotency_key: str
    input_bucket: Literal["source", "derived"]
    input_object_key: str
    input_sha256: str
    output_object_key: str
    options: dict[str, Any]
    model_revision: str
    runtime_image_digest: str
    adapter_version: str
    attempt_number: int
    lease_token: uuid.UUID
    provider_job_id: str | None
    provider_status: str | None
    action: Literal["submit", "poll", "cancel", "local_terminal"]
    cancellation_reason: str | None


@dataclass(frozen=True, slots=True)
class _LineageState:
    root_invocation_id: uuid.UUID
    total_attempts: int
    max_attempts: int
    category_transitions: dict[str, int]


@dataclass(frozen=True, slots=True)
class _TransitionPlan:
    category: Literal["gpu_oom", "invalid_output"]
    strategy: Literal["reduce_or_escalate", "fallback"]
    action: Literal["reduce", "escalate", "fallback"]
    transition_attempt: int
    provider_key: str
    endpoint_id: str
    model_revision: str
    runtime_image_digest: str
    adapter_version: str
    options: dict[str, Any]
    output_object_key: str
    policy: GpuTransitionPolicy | None


class GpuResultConflict(RuntimeError):
    """A terminal replay disagrees with already admitted immutable evidence."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _backoff(
    attempt: int,
    *,
    policy: GpuWorkerPolicy,
    random_source: RandomSource,
) -> float:
    base = min(
        policy.backoff_max_seconds,
        policy.backoff_base_seconds * (2 ** max(0, attempt - 1)),
    )
    jittered = base * (1 + ((random_source() * 2) - 1) * policy.backoff_jitter_ratio)
    return float(max(0.0, jittered))


def _safe_metrics(value: dict[str, Any]) -> dict[str, int | float | str | bool | None]:
    if len(value) > 64:
        raise GpuProviderError("GPU_RESULT_OBJECT_INVALID")
    safe: dict[str, int | float | str | bool | None] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 80:
            raise GpuProviderError("GPU_RESULT_OBJECT_INVALID")
        if item is None or isinstance(item, bool):
            safe[key] = item
        elif isinstance(item, int):
            if isinstance(item, bool) or abs(item) > 2**53:
                raise GpuProviderError("GPU_RESULT_OBJECT_INVALID")
            safe[key] = item
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise GpuProviderError("GPU_RESULT_OBJECT_INVALID")
            safe[key] = item
        elif isinstance(item, str) and len(item) <= 120:
            safe[key] = item
        else:
            raise GpuProviderError("GPU_RESULT_OBJECT_INVALID")
    return safe


def _validated_output_body(
    claim: _Claim,
    result: GpuJobResult,
    body: bytes,
    *,
    max_output_bytes: int,
) -> dict[str, Any]:
    if (
        not body
        or len(body) > max_output_bytes
        or len(body) != result.output_bytes
        or hashlib.sha256(body).hexdigest() != result.output_sha256.removeprefix("sha256:")
    ):
        raise GpuProviderError("GPU_RESULT_OBJECT_CHECKSUM_MISMATCH")
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GpuProviderError("GPU_RESULT_OBJECT_INVALID") from exc
    if not isinstance(value, dict):
        raise GpuProviderError("GPU_RESULT_OBJECT_INVALID")
    expected = {
        "schema_version": "1.0",
        "result_id": result.result_id,
        "job_id": str(claim.job_id),
        "tenant_id": str(claim.tenant_id),
        "provider": claim.provider_key,
        "model_revision": claim.model_revision,
        "runtime_image_digest": claim.runtime_image_digest,
        "adapter_version": claim.adapter_version,
        "input_sha256": f"sha256:{claim.input_sha256}",
        "idempotency_key": claim.idempotency_key,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise GpuProviderError("GPU_RESULT_OBJECT_SCOPE_MISMATCH")
    expected_worker_kind = (
        "knowledge"
        if claim.options.get("artifact_contract")
        in {
            KNOWLEDGE_ARTIFACT_CONTRACT,
            KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT,
        }
        else "parser"
    )
    if value.get("worker_kind") != expected_worker_kind:
        raise GpuProviderError("GPU_RESULT_OBJECT_SCOPE_MISMATCH")
    if value.get("metrics") != result.metrics or value.get("warnings", []) != list(result.warnings):
        raise GpuProviderError("GPU_RESULT_OBJECT_SCOPE_MISMATCH")
    return value


def _result_manifest(
    claim: _Claim,
    result: GpuJobResult,
    *,
    completion_source: Literal["poll", "callback"],
    knowledge_attestation: dict[str, int | str] | None = None,
    visual_attestation: dict[str, int | str] | None = None,
) -> tuple[dict[str, Any], str]:
    metrics = _safe_metrics(result.metrics)
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "invocation_id": str(claim.invocation_id),
        "job_id": str(claim.job_id),
        "tenant_id": str(claim.tenant_id),
        "provider": "runpod",
        "provider_job_id": result.provider_job_id,
        "endpoint_id": result.endpoint_id,
        "provider_key": result.provider_key,
        "model_revision": result.model_revision,
        "runtime_image_digest": result.runtime_image_digest,
        "adapter_version": result.adapter_version,
        "result_id": result.result_id,
        "output_object_key": result.output_object_key,
        "output_sha256": result.output_sha256,
        "output_bytes": result.output_bytes,
        "metrics": metrics,
        "warning_count": len(result.warnings),
        "warning_sha256": [
            hashlib.sha256(warning.encode()).hexdigest() for warning in result.warnings
        ],
        "raw_provider_response_sha256": result.raw_provider_response_sha256,
        "completion_source": completion_source,
    }
    if knowledge_attestation is not None:
        manifest["knowledge_attestation"] = knowledge_attestation
    if visual_attestation is not None:
        manifest["visual_attestation"] = visual_attestation
    return manifest, hashlib.sha256(_canonical_json(manifest)).hexdigest()


class GpuInvocationWorker:
    """Process one durable state transition per pass.

    Every provider or object-store operation occurs after the claim transaction
    commits. Results are admitted only in a new locked transaction after
    rechecking job and deletion fences.
    """

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        client: DurableGpuClient,
        object_store: ObjectStore,
        policy: GpuWorkerPolicy,
        clock: Clock = _utcnow,
        random_source: RandomSource = _SYSTEM_RANDOM.random,
    ) -> None:
        self._engine = engine
        self._sessions = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self._client = client
        self._object_store = object_store
        self._policy = policy
        self._clock = clock
        self._random = random_source
        self._stopping = False

    def request_stop(self) -> None:
        self._stopping = True

    @property
    def stopping(self) -> bool:
        return self._stopping

    async def _fence_reason(
        self,
        session: AsyncSession,
        invocation: GpuProviderInvocation,
    ) -> str | None:
        row = (
            await session.execute(
                select(
                    ProcessingJob.status,
                    Project.deletion_requested_at,
                    Document.deletion_requested_at,
                )
                .join(
                    Project,
                    (Project.tenant_id == ProcessingJob.tenant_id)
                    & (Project.id == ProcessingJob.project_id),
                )
                .join(
                    Document,
                    (Document.tenant_id == ProcessingJob.tenant_id)
                    & (Document.id == ProcessingJob.document_id),
                )
                .where(
                    ProcessingJob.tenant_id == invocation.tenant_id,
                    ProcessingJob.id == invocation.job_id,
                    ProcessingJob.project_id == invocation.project_id,
                    ProcessingJob.document_id == invocation.document_id,
                )
            )
        ).one_or_none()
        if row is None:
            return "tombstone"
        status, project_deleted, document_deleted = row
        if project_deleted is not None or document_deleted is not None:
            return "tombstone"
        if status == "cancelled":
            return "job_cancelled"
        if status not in {"queued", "running"}:
            return "job_terminal"
        return None

    async def _terminal_local(
        self,
        session: AsyncSession,
        invocation: GpuProviderInvocation,
        *,
        status: Literal["cancelled", "dead_letter"],
        code: str,
        now: datetime,
    ) -> None:
        invocation.status = status
        invocation.last_error_code = code
        invocation.lease_token = None
        invocation.lease_expires_at = None
        invocation.completed_at = now
        invocation.updated_at = now
        await append_gpu_event(
            session,
            invocation,
            event_type=f"gpu.invocation.{status}.v1",
            payload={"attempt": invocation.attempt_count, "code": code},
            occurred_at=now,
        )
        if status == "dead_letter" and invocation.cancellation_reason not in {
            "tombstone",
            "job_cancelled",
            "job_terminal",
        }:
            await self._enqueue_resume(session, invocation, now=now)

    async def _enqueue_resume(
        self,
        session: AsyncSession,
        invocation: GpuProviderInvocation,
        *,
        now: datetime,
    ) -> None:
        """Wake the owning durable dispatch exactly once after terminal GPU state."""

        job = await session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.tenant_id == invocation.tenant_id,
                ProcessingJob.id == invocation.job_id,
                ProcessingJob.status == "running",
            )
            .with_for_update()
        )
        progress = job.progress if job is not None and isinstance(job.progress, dict) else {}
        if job is None or not str(progress.get("stage", "")).endswith("_waiting"):
            return
        event_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"akc:gpu-resume:{invocation.id}",
        )
        if await session.scalar(select(OutboxEvent.id).where(OutboxEvent.id == event_id)):
            return
        session.add(
            OutboxEvent(
                id=event_id,
                tenant_id=invocation.tenant_id,
                aggregate_type="job",
                aggregate_id=invocation.job_id,
                event_type="job.dispatch.requested.v1",
                payload={
                    "job_id": str(invocation.job_id),
                    "resume_invocation_id": str(invocation.id),
                },
                available_at=now,
            )
        )

    async def _lineage_state(
        self,
        session: AsyncSession,
        invocation: GpuProviderInvocation,
    ) -> _LineageState:
        """Read and lock a bounded, acyclic parent chain."""

        current = invocation
        seen: set[uuid.UUID] = set()
        total_attempts = 0
        categories: dict[str, int] = {}
        root = invocation
        for _ in range(10):
            if current.id in seen:
                raise RuntimeError("gpu_invocation_lineage_cycle")
            seen.add(current.id)
            total_attempts += current.attempt_count
            if current.transition_category is not None:
                categories[current.transition_category] = (
                    categories.get(current.transition_category, 0) + 1
                )
            root = current
            if current.parent_invocation_id is None:
                break
            parent = await session.scalar(
                select(GpuProviderInvocation)
                .where(
                    GpuProviderInvocation.tenant_id == invocation.tenant_id,
                    GpuProviderInvocation.id == current.parent_invocation_id,
                )
                .with_for_update()
            )
            if parent is None:
                raise RuntimeError("gpu_invocation_lineage_parent_missing")
            current = parent
        else:
            raise RuntimeError("gpu_invocation_lineage_too_deep")
        expected_root = invocation.lineage_root_invocation_id
        if expected_root is not None and expected_root != root.id:
            raise RuntimeError("gpu_invocation_lineage_root_mismatch")
        if total_attempts < 1 or total_attempts > root.max_attempts:
            raise RuntimeError("gpu_invocation_lineage_budget_invalid")
        return _LineageState(
            root_invocation_id=root.id,
            total_attempts=total_attempts,
            max_attempts=root.max_attempts,
            category_transitions=categories,
        )

    @staticmethod
    def _reduced_options(options: dict[str, Any]) -> dict[str, Any] | None:
        reduced = dict(options)
        changed = False
        for key, minimum in (
            ("max_output_tokens", 128),
            ("batch_size", 1),
            ("tile_size", 256),
        ):
            value = reduced.get(key)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= minimum
            ):
                continue
            reduced[key] = max(minimum, value // 2)
            changed = True
        return reduced if changed else None

    @staticmethod
    def _transition_output_key(
        invocation: GpuProviderInvocation,
        *,
        root_invocation_id: uuid.UUID,
        category: str,
        transition_attempt: int,
    ) -> str:
        return (
            f"tenants/{invocation.tenant_id}/derived/gpu-transitions/"
            f"{root_invocation_id.hex}/{invocation.id.hex}/"
            f"{category}-{transition_attempt}.json"
        )

    async def _approved_registry_target(
        self,
        session: AsyncSession,
        invocation: GpuProviderInvocation,
        *,
        policy: GpuTransitionPolicy,
        target: GpuTransitionTarget,
    ) -> bool:
        if (policy.source_route, target.route) not in _APPROVED_INTERNAL_TRANSITIONS:
            return False
        if (
            target.provider_key == invocation.provider_key
            and target.endpoint_id == invocation.endpoint_id
            and target.model_revision == invocation.model_revision
            and target.runtime_image_digest == invocation.runtime_image_digest
            and target.adapter_version == invocation.adapter_version
        ):
            return False
        row = await session.scalar(
            select(ModelRegistry)
            .where(
                ModelRegistry.endpoint == target.endpoint_id,
                ModelRegistry.model_id == target.provider_key,
                ModelRegistry.revision == target.model_revision,
                ModelRegistry.runtime_image_digest == target.runtime_image_digest,
                ModelRegistry.adapter_version == target.adapter_version,
                ModelRegistry.policy_version == target.registry_policy_version,
                ModelRegistry.enabled.is_(True),
            )
            .with_for_update()
        )
        return bool(
            row is not None
            and cohort_enabled(
                tenant_id=invocation.tenant_id,
                key=f"model:{row.endpoint}:{row.revision}",
                enabled=row.enabled,
                percent=row.canary_percent,
            )
        )

    async def _transition_plan(
        self,
        session: AsyncSession,
        invocation: GpuProviderInvocation,
        *,
        category: str,
        transition_attempt: int,
        root_invocation_id: uuid.UUID,
    ) -> _TransitionPlan | None:
        try:
            policy = GpuTransitionPolicy.from_manifest(invocation.transition_policy)
        except ValueError:
            return None
        if category == "gpu_oom":
            reduced = self._reduced_options(invocation.options)
            if reduced is not None:
                return _TransitionPlan(
                    category="gpu_oom",
                    strategy="reduce_or_escalate",
                    action="reduce",
                    transition_attempt=transition_attempt,
                    provider_key=invocation.provider_key,
                    endpoint_id=invocation.endpoint_id,
                    model_revision=invocation.model_revision,
                    runtime_image_digest=invocation.runtime_image_digest,
                    adapter_version=invocation.adapter_version,
                    options=reduced,
                    output_object_key=self._transition_output_key(
                        invocation,
                        root_invocation_id=root_invocation_id,
                        category=category,
                        transition_attempt=transition_attempt,
                    ),
                    policy=policy,
                )
            if policy is None or policy.oom_escalation is None:
                return None
            target = policy.oom_escalation
            if not await self._approved_registry_target(
                session,
                invocation,
                policy=policy,
                target=target,
            ):
                return None
            options = dict(invocation.options)
            options["route_profile"] = target.route_profile
            return _TransitionPlan(
                category="gpu_oom",
                strategy="reduce_or_escalate",
                action="escalate",
                transition_attempt=transition_attempt,
                provider_key=target.provider_key,
                endpoint_id=target.endpoint_id,
                model_revision=target.model_revision,
                runtime_image_digest=target.runtime_image_digest,
                adapter_version=target.adapter_version,
                options=options,
                output_object_key=self._transition_output_key(
                    invocation,
                    root_invocation_id=root_invocation_id,
                    category=category,
                    transition_attempt=transition_attempt,
                ),
                policy=policy,
            )
        if category != "invalid_output":
            return None
        if policy is None or policy.invalid_output_fallback is None:
            return None
        target = policy.invalid_output_fallback
        if not await self._approved_registry_target(
            session,
            invocation,
            policy=policy,
            target=target,
        ):
            return None
        options = dict(invocation.options)
        options["route_profile"] = target.route_profile
        return _TransitionPlan(
            category="invalid_output",
            strategy="fallback",
            action="fallback",
            transition_attempt=transition_attempt,
            provider_key=target.provider_key,
            endpoint_id=target.endpoint_id,
            model_revision=target.model_revision,
            runtime_image_digest=target.runtime_image_digest,
            adapter_version=target.adapter_version,
            options=options,
            output_object_key=self._transition_output_key(
                invocation,
                root_invocation_id=root_invocation_id,
                category=category,
                transition_attempt=transition_attempt,
            ),
            policy=policy,
        )

    async def _create_transition(
        self,
        session: AsyncSession,
        invocation: GpuProviderInvocation,
        attempt: GpuProviderAttempt | None,
        *,
        error: GpuProviderError,
        lineage: _LineageState,
        plan: _TransitionPlan,
        now: datetime,
        delay_seconds: float,
    ) -> GpuProviderInvocation:
        child = await enqueue_gpu_invocation(
            session,
            GpuInvocationSpec(
                tenant_id=invocation.tenant_id,
                job_id=invocation.job_id,
                project_id=invocation.project_id,
                document_id=invocation.document_id,
                document_version_id=invocation.document_version_id,
                page_id=invocation.page_id,
                provider_key=plan.provider_key,
                endpoint_id=plan.endpoint_id,
                idempotency_key=(
                    f"transition-{invocation.id.hex}-{plan.category}-"
                    f"{plan.transition_attempt}"
                ),
                input_bucket=cast(Literal["source", "derived"], invocation.input_bucket),
                input_object_key=invocation.input_object_key,
                input_sha256=invocation.input_sha256,
                output_object_key=plan.output_object_key,
                model_revision=plan.model_revision,
                runtime_image_digest=plan.runtime_image_digest,
                adapter_version=plan.adapter_version,
                options=plan.options,
                max_attempts=lineage.max_attempts,
                transition_policy=plan.policy,
                parent_invocation_id=invocation.id,
                lineage_root_invocation_id=lineage.root_invocation_id,
                transition_category=plan.category,
                transition_strategy=plan.strategy,
                transition_action=plan.action,
                transition_attempt=plan.transition_attempt,
            ),
        )
        child.available_at = now + timedelta(seconds=delay_seconds)
        invocation.status = "failed"
        invocation.last_error_code = error.code
        invocation.completed_at = now
        invocation.lease_token = None
        invocation.lease_expires_at = None
        invocation.updated_at = now
        if attempt is not None:
            attempt.status = "failed"
            attempt.error_code = error.code
            attempt.retryable = error.retryable or plan.category == "gpu_oom"
            attempt.last_polled_at = now
            attempt.completed_at = now

        evidence: dict[str, Any] = {
            "attempt": invocation.attempt_count,
            "child_invocation_id": str(child.id),
            "child_model_revision": child.model_revision,
            "child_provider_key": child.provider_key,
            "child_request_manifest_sha256": child.request_manifest_sha256,
            "code": error.code,
            "input_sha256": invocation.input_sha256,
            "delay_seconds": delay_seconds,
            "lineage_attempt": lineage.total_attempts,
            "lineage_root_invocation_id": str(lineage.root_invocation_id),
            "parent_invocation_id": str(invocation.id),
            "parent_model_revision": invocation.model_revision,
            "parent_provider_key": invocation.provider_key,
            "parent_request_manifest_sha256": invocation.request_manifest_sha256,
            "strategy": plan.strategy,
            "transition_action": plan.action,
            "transition_attempt": plan.transition_attempt,
            "transition_category": plan.category,
        }
        await append_gpu_event(
            session,
            invocation,
            event_type="gpu.invocation.transitioned.v1",
            payload=evidence,
            occurred_at=now,
        )
        await append_gpu_event(
            session,
            child,
            event_type="gpu.invocation.parent_linked.v1",
            payload=evidence,
            occurred_at=now,
        )
        job = await session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.tenant_id == invocation.tenant_id,
                ProcessingJob.id == invocation.job_id,
                ProcessingJob.status == "running",
            )
            .with_for_update()
        )
        if job is None:
            raise RuntimeError("gpu_transition_job_not_active")
        progress = dict(job.progress) if isinstance(job.progress, dict) else {}
        if progress.get("invocation_id") == str(invocation.id):
            progress["invocation_id"] = str(child.id)
        invocation_ids = progress.get("invocation_ids")
        if isinstance(invocation_ids, list):
            progress["invocation_ids"] = [
                str(child.id) if value == str(invocation.id) else value
                for value in invocation_ids
            ]
        job.progress = progress
        job.event_sequence += 1
        session.add(
            JobEvent(
                tenant_id=job.tenant_id,
                job_id=job.id,
                sequence=job.event_sequence,
                event_type="job.stage.progress.v1",
                schema_version="1.0",
                payload={"stage": "gpu_transition", **evidence},
                occurred_at=now,
            )
        )
        session.add(
            AuditEvent(
                tenant_id=invocation.tenant_id,
                actor_id=None,
                action="gpu.invocation.transitioned",
                target_type="gpu_provider_invocation",
                target_id=str(child.id),
                metadata_json=evidence,
                occurred_at=now,
            )
        )
        return child

    async def _claim(self) -> _Claim | None:
        now = self._clock()
        async with self._sessions() as session:
            invocation = await session.scalar(
                select(GpuProviderInvocation)
                .where(
                    GpuProviderInvocation.status.in_(_ACTIVE_STATES),
                    GpuProviderInvocation.available_at <= now,
                    or_(
                        GpuProviderInvocation.lease_expires_at.is_(None),
                        GpuProviderInvocation.lease_expires_at <= now,
                    ),
                )
                .order_by(
                    GpuProviderInvocation.available_at,
                    GpuProviderInvocation.created_at,
                    GpuProviderInvocation.id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if invocation is None:
                return None
            fence = await self._fence_reason(session, invocation)
            if fence is not None:
                invocation.cancellation_reason = fence
                invocation.status = "cancel_requested"

            token = uuid.uuid4()
            invocation.lease_token = token
            invocation.lease_expires_at = now + timedelta(seconds=self._policy.lease_seconds)
            invocation.updated_at = now
            action: Literal["submit", "poll", "cancel", "local_terminal"]
            if invocation.status in {"cancel_requested", "cancelling"}:
                if invocation.provider_job_id is None:
                    await self._terminal_local(
                        session,
                        invocation,
                        status="cancelled",
                        code=(
                            "GPU_INVOCATION_"
                            f"{(invocation.cancellation_reason or 'CANCELLED').upper()}"
                        ),
                        now=now,
                    )
                    action = "local_terminal"
                elif invocation.cancel_attempt_count >= self._policy.max_cancel_attempts:
                    await self._terminal_local(
                        session,
                        invocation,
                        status="dead_letter",
                        code="GPU_PROVIDER_CANCEL_UNCONFIRMED",
                        now=now,
                    )
                    action = "local_terminal"
                else:
                    invocation.status = "cancelling"
                    invocation.cancel_attempt_count += 1
                    action = "cancel"
            elif (
                invocation.provider_job_id is not None
                and _aware(invocation.provider_deadline_at) is not None
                and cast(datetime, _aware(invocation.provider_deadline_at)) <= now
            ):
                invocation.status = "cancelling"
                invocation.cancellation_reason = "timeout"
                invocation.cancel_attempt_count += 1
                action = "cancel"
            elif invocation.provider_job_id is not None:
                invocation.status = "running"
                action = "poll"
            elif invocation.attempt_count >= invocation.max_attempts:
                await self._terminal_local(
                    session,
                    invocation,
                    status="dead_letter",
                    code=invocation.last_error_code or "GPU_PROVIDER_ATTEMPTS_EXHAUSTED",
                    now=now,
                )
                action = "local_terminal"
            else:
                invocation.attempt_count += 1
                invocation.status = "submitting"
                invocation.started_at = invocation.started_at or now
                invocation.last_error_code = None
                attempt = GpuProviderAttempt(
                    tenant_id=invocation.tenant_id,
                    invocation_id=invocation.id,
                    attempt_number=invocation.attempt_count,
                    status="submitting",
                    request_manifest_sha256=invocation.request_manifest_sha256,
                )
                session.add(attempt)
                await append_gpu_event(
                    session,
                    invocation,
                    event_type="gpu.invocation.submitting.v1",
                    payload={
                        "attempt": invocation.attempt_count,
                        "endpoint_id": invocation.endpoint_id,
                        "provider_key": invocation.provider_key,
                    },
                    occurred_at=now,
                )
                action = "submit"
            await session.commit()
            return _Claim(
                invocation_id=invocation.id,
                tenant_id=invocation.tenant_id,
                job_id=invocation.job_id,
                document_id=invocation.document_id,
                document_version_id=invocation.document_version_id,
                page_id=invocation.page_id,
                provider_key=invocation.provider_key,
                endpoint_id=invocation.endpoint_id,
                idempotency_key=invocation.idempotency_key,
                input_bucket=cast(Literal["source", "derived"], invocation.input_bucket),
                input_object_key=invocation.input_object_key,
                input_sha256=invocation.input_sha256,
                output_object_key=invocation.output_object_key,
                options=dict(invocation.options),
                model_revision=invocation.model_revision,
                runtime_image_digest=invocation.runtime_image_digest,
                adapter_version=invocation.adapter_version,
                attempt_number=invocation.attempt_count,
                lease_token=token,
                provider_job_id=invocation.provider_job_id,
                provider_status=invocation.provider_status,
                action=action,
                cancellation_reason=invocation.cancellation_reason,
            )

    async def _request(self, claim: _Claim) -> GpuJobRequest:
        input_target, output_target = await asyncio.gather(
            self._object_store.create_gpu_input_target(
                bucket=claim.input_bucket,
                object_key=claim.input_object_key,
                expires=self._policy.presign_ttl_seconds,
            ),
            self._object_store.create_gpu_output_target(
                object_key=claim.output_object_key,
                expires=self._policy.presign_ttl_seconds,
            ),
        )
        if not isinstance(input_target, UploadTarget) or not isinstance(
            output_target,
            UploadTarget,
        ):
            raise GpuProviderError("GPU_OBJECT_GRANT_INVALID")
        page_index0: int | None = None
        if claim.options.get("artifact_contract") == VISUAL_ARTIFACT_CONTRACT:
            candidate = claim.options.get("page_index0")
            if (
                claim.page_id is None
                or not isinstance(candidate, int)
                or isinstance(candidate, bool)
                or candidate < 0
            ):
                raise GpuProviderError("GPU_VISUAL_PAGE_SCOPE_INVALID")
            page_index0 = candidate
        return GpuJobRequest(
            endpoint_id=claim.endpoint_id,
            provider_key=claim.provider_key,
            model_revision=claim.model_revision,
            runtime_image_digest=claim.runtime_image_digest,
            adapter_version=claim.adapter_version,
            job_id=str(claim.job_id),
            tenant_id=str(claim.tenant_id),
            idempotency_key=claim.idempotency_key,
            input_url=input_target.url,
            input_object_key=claim.input_object_key,
            input_sha256=claim.input_sha256,
            output_url=output_target.url,
            output_object_key=claim.output_object_key,
            options=claim.options,
            document_id=str(claim.document_id),
            document_version_id=claim.document_version_id,
            page_index0=page_index0,
        )

    async def _locked_invocation(
        self,
        session: AsyncSession,
        claim: _Claim,
        *,
        require_lease: bool = True,
    ) -> GpuProviderInvocation | None:
        invocation = await session.scalar(
            select(GpuProviderInvocation)
            .where(
                GpuProviderInvocation.tenant_id == claim.tenant_id,
                GpuProviderInvocation.id == claim.invocation_id,
            )
            .with_for_update()
        )
        if invocation is None:
            return None
        if require_lease and invocation.lease_token != claim.lease_token:
            return None
        return invocation

    async def _attempt(
        self,
        session: AsyncSession,
        claim: _Claim,
    ) -> GpuProviderAttempt | None:
        return cast(
            GpuProviderAttempt | None,
            await session.scalar(
                select(GpuProviderAttempt)
                .where(
                    GpuProviderAttempt.tenant_id == claim.tenant_id,
                    GpuProviderAttempt.invocation_id == claim.invocation_id,
                    GpuProviderAttempt.attempt_number == claim.attempt_number,
                )
                .with_for_update()
            ),
        )

    async def _record_submission(
        self,
        claim: _Claim,
        submitted: SubmittedGpuJob,
    ) -> None:
        now = self._clock()
        async with self._sessions() as session:
            invocation = await self._locked_invocation(session, claim)
            if invocation is None:
                return
            attempt = await self._attempt(session, claim)
            if attempt is None:
                raise RuntimeError("gpu_attempt_missing")
            if submitted.endpoint_id != invocation.endpoint_id:
                raise GpuProviderError("GPU_PROVIDER_RESULT_SCOPE_MISMATCH")
            fence = await self._fence_reason(session, invocation)
            invocation.provider_job_id = submitted.provider_job_id
            invocation.provider_status = submitted.status
            invocation.provider_deadline_at = now + timedelta(
                seconds=self._policy.provider_job_timeout_seconds
            )
            invocation.object_grant_expires_at = now + timedelta(
                seconds=self._policy.presign_ttl_seconds
            )
            invocation.lease_token = None
            invocation.lease_expires_at = None
            invocation.available_at = now + timedelta(seconds=self._policy.poll_interval_seconds)
            invocation.status = "cancel_requested" if fence else "submitted"
            invocation.cancellation_reason = fence
            invocation.updated_at = now
            attempt.provider_job_id = submitted.provider_job_id
            attempt.status = "submitted"
            attempt.submitted_at = now
            await append_gpu_event(
                session,
                invocation,
                event_type="gpu.invocation.submitted.v1",
                payload={
                    "attempt": claim.attempt_number,
                    "provider_status": submitted.status,
                },
                occurred_at=now,
            )
            await session.commit()
        record_provider_request(claim.provider_key, result="success")

    async def _record_poll_wait(
        self,
        claim: _Claim,
        observation: GpuJobPoll,
    ) -> None:
        now = self._clock()
        async with self._sessions() as session:
            invocation = await self._locked_invocation(session, claim)
            if invocation is None:
                return
            fence = await self._fence_reason(session, invocation)
            attempt = await self._attempt(session, claim)
            if attempt is not None:
                attempt.status = "running" if observation.status == "IN_PROGRESS" else "submitted"
                attempt.last_polled_at = now
            invocation.provider_status = observation.status
            invocation.status = (
                "cancel_requested"
                if fence
                else ("running" if observation.status == "IN_PROGRESS" else "submitted")
            )
            invocation.cancellation_reason = fence
            invocation.available_at = now + timedelta(seconds=self._policy.poll_interval_seconds)
            invocation.lease_token = None
            invocation.lease_expires_at = None
            invocation.updated_at = now
            await append_gpu_event(
                session,
                invocation,
                event_type="gpu.invocation.polled.v1",
                payload={
                    "attempt": claim.attempt_number,
                    "provider_status": observation.status,
                },
                occurred_at=now,
            )
            await session.commit()

    async def _admit_result(
        self,
        claim: _Claim,
        result: GpuJobResult,
        body: bytes,
        *,
        source: Literal["poll", "callback"],
        callback_id: str | None = None,
        callback_sha256: str | None = None,
        require_lease: bool = True,
    ) -> bool:
        output_payload = _validated_output_body(
            claim,
            result,
            body,
            max_output_bytes=self._policy.max_output_bytes,
        )
        knowledge_attestation: dict[str, int | str] | None = None
        visual_attestation_value: dict[str, int | str] | None = None
        artifact_contract = claim.options.get("artifact_contract")
        if artifact_contract in {
            KNOWLEDGE_ARTIFACT_CONTRACT,
            KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT,
        }:
            if claim.input_bucket != "derived":
                raise GpuProviderError("GPU_KNOWLEDGE_INPUT_SCOPE_INVALID")
            try:
                input_body = await self._object_store.read_derived(claim.input_object_key)
            except Exception as exc:
                raise GpuProviderError(
                    "GPU_KNOWLEDGE_INPUT_UNAVAILABLE",
                    retryable=True,
                ) from exc
            if hashlib.sha256(input_body).hexdigest() != claim.input_sha256:
                raise GpuProviderError("GPU_KNOWLEDGE_INPUT_CHECKSUM_MISMATCH")
            try:
                if artifact_contract == KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT:
                    stage = claim.options.get("knowledge_stage")
                    unit_id = claim.options.get("knowledge_unit_id")
                    if stage not in {"A", "B", "C", "D"} or not isinstance(
                        unit_id,
                        str,
                    ):
                        raise ValueError("knowledge stage attestation missing")
                    stage_result = validate_knowledge_stage_result(
                        output_payload=output_payload,
                        input_body=input_body,
                        expected_prompt_revision=str(claim.options.get("prompt_revision", "")),
                        expected_schema_sha256=str(
                            claim.options.get("knowledge_schema_sha256", "")
                        ),
                        expected_stage=cast(
                            Literal["A", "B", "C", "D"],
                            stage,
                        ),
                        expected_unit_id=unit_id,
                    )
                    knowledge_attestation = {
                        "artifact_contract": KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT,
                        "prompt_revision": str(claim.options["prompt_revision"]),
                        "knowledge_schema_sha256": str(claim.options["knowledge_schema_sha256"]),
                        "knowledge_stage": stage,
                        "knowledge_unit_id": unit_id,
                        "knowledge_compile_input_sha256": str(
                            claim.options.get(
                                "knowledge_compile_input_sha256",
                                "",
                            )
                        ),
                        **knowledge_stage_result_counts(stage_result),
                        "unsupported_claim_count": 0,
                    }
                else:
                    bundle = validate_knowledge_result(
                        output_payload=output_payload,
                        input_body=input_body,
                        expected_prompt_revision=str(claim.options.get("prompt_revision", "")),
                        expected_schema_sha256=str(
                            claim.options.get("knowledge_schema_sha256", "")
                        ),
                    )
                    knowledge_attestation = {
                        "artifact_contract": KNOWLEDGE_ARTIFACT_CONTRACT,
                        "prompt_revision": str(claim.options["prompt_revision"]),
                        "knowledge_schema_sha256": str(claim.options["knowledge_schema_sha256"]),
                        "note_count": len(bundle.notes),
                        "relation_count": len(bundle.relations),
                        "conflict_count": len(bundle.conflicts),
                        "unsupported_claim_count": 0,
                    }
            except (TypeError, ValueError) as exc:
                raise GpuProviderError("GPU_KNOWLEDGE_RESULT_INVALID") from exc
        elif claim.options.get("artifact_contract") == VISUAL_ARTIFACT_CONTRACT:
            page_index0 = claim.options.get("page_index0")
            page_width_px = claim.options.get("page_width_px")
            page_height_px = claim.options.get("page_height_px")
            input_size_bytes = claim.options.get("input_size_bytes")
            dpi = claim.options.get("dpi")
            colorspace = claim.options.get("colorspace")
            try:
                page_asset_id = uuid.UUID(str(claim.options.get("page_asset_id")))
            except (TypeError, ValueError) as exc:
                raise GpuProviderError("GPU_VISUAL_INPUT_SCOPE_INVALID") from exc
            if (
                claim.input_bucket != "derived"
                or claim.page_id is None
                or not isinstance(page_index0, int)
                or isinstance(page_index0, bool)
                or page_index0 < 0
                or not isinstance(page_width_px, int)
                or isinstance(page_width_px, bool)
                or not 1 <= page_width_px <= VISUAL_RASTER_MAX_DIMENSION
                or not isinstance(page_height_px, int)
                or isinstance(page_height_px, bool)
                or not 1 <= page_height_px <= VISUAL_RASTER_MAX_DIMENSION
                or page_width_px * page_height_px > VISUAL_RASTER_MAX_PIXELS
                or not isinstance(input_size_bytes, int)
                or isinstance(input_size_bytes, bool)
                or not 1 <= input_size_bytes <= VISUAL_RASTER_MAX_BYTES
                or not isinstance(dpi, int)
                or isinstance(dpi, bool)
                or not (180 <= dpi <= 220 or 250 <= dpi <= 300)
                or colorspace != "RGB"
            ):
                raise GpuProviderError("GPU_VISUAL_INPUT_SCOPE_INVALID")
            try:
                visual_result = validate_visual_result(
                    output_payload=output_payload,
                    expected_job_id=claim.job_id,
                    expected_tenant_id=claim.tenant_id,
                    expected_document_id=claim.document_id,
                    expected_document_version_id=claim.document_version_id,
                    expected_page_index0=page_index0,
                    expected_provider=claim.provider_key,
                    expected_model_revision=claim.model_revision,
                    expected_runtime_image_digest=claim.runtime_image_digest,
                    expected_adapter_version=claim.adapter_version,
                    expected_input_sha256=claim.input_sha256,
                    expected_input_bytes=input_size_bytes,
                    expected_idempotency_key=claim.idempotency_key,
                    expected_image_asset_id=page_asset_id,
                )
            except (TypeError, ValueError) as exc:
                raise GpuProviderError("GPU_VISUAL_RESULT_INVALID") from exc
            visual_attestation_value = visual_attestation(
                visual_result,
                page_id=claim.page_id,
                page_index0=page_index0,
                page_width_px=page_width_px,
                page_height_px=page_height_px,
                input_size_bytes=input_size_bytes,
            )
        manifest, manifest_sha = _result_manifest(
            claim,
            result,
            completion_source=source,
            knowledge_attestation=knowledge_attestation,
            visual_attestation=visual_attestation_value,
        )
        now = self._clock()
        async with self._sessions() as session:
            invocation = await self._locked_invocation(
                session,
                claim,
                require_lease=require_lease,
            )
            if invocation is None:
                return False
            if invocation.status == "completed":
                if invocation.result_manifest_sha256 == manifest_sha and (
                    callback_id is None or invocation.provider_callback_id == callback_id
                ):
                    return True
                raise GpuResultConflict("gpu_terminal_result_conflict")
            if invocation.status in _TERMINAL_STATES:
                return False
            if invocation.provider_job_id != result.provider_job_id:
                raise GpuResultConflict("gpu_provider_job_id_conflict")
            fence = await self._fence_reason(session, invocation)
            if fence is not None:
                invocation.status = "cancel_requested"
                invocation.cancellation_reason = fence
                invocation.available_at = now
                invocation.lease_token = None
                invocation.lease_expires_at = None
                await append_gpu_event(
                    session,
                    invocation,
                    event_type="gpu.invocation.result_fenced.v1",
                    payload={"attempt": claim.attempt_number, "reason": fence},
                    occurred_at=now,
                )
                await session.commit()
                return False
            attempt = await self._attempt(session, claim)
            if attempt is None:
                raise RuntimeError("gpu_attempt_missing")
            invocation.status = "completed"
            invocation.provider_status = "COMPLETED"
            invocation.result_manifest = manifest
            invocation.result_manifest_sha256 = manifest_sha
            invocation.completion_source = source
            invocation.provider_callback_id = callback_id
            invocation.provider_callback_sha256 = callback_sha256
            invocation.last_error_code = None
            invocation.completed_at = now
            invocation.updated_at = now
            invocation.lease_token = None
            invocation.lease_expires_at = None
            attempt.status = "completed"
            attempt.provider_response_sha256 = result.raw_provider_response_sha256
            attempt.result_manifest_sha256 = manifest_sha
            attempt.last_polled_at = now
            attempt.completed_at = now
            await append_gpu_event(
                session,
                invocation,
                event_type="gpu.invocation.completed.v1",
                payload={
                    "attempt": claim.attempt_number,
                    "output_bytes": result.output_bytes,
                    "result_manifest_sha256": manifest_sha,
                    "source": source,
                },
                occurred_at=now,
            )
            await self._enqueue_resume(session, invocation, now=now)
            await session.commit()
        metrics = manifest["metrics"]
        assert isinstance(metrics, dict)
        cold_ms = metrics.get("cold_start_ms")
        if isinstance(cold_ms, (int, float)) and not isinstance(cold_ms, bool):
            observe_provider_cold_start(claim.provider_key, float(cold_ms) / 1000)
        estimated_cost = metrics.get("estimated_cost_usd")
        if isinstance(estimated_cost, (int, float, str)) and not isinstance(
            estimated_cost,
            bool,
        ):
            with contextlib.suppress(InvalidOperation):
                record_provider_cost(claim.provider_key, Decimal(str(estimated_cost)))
        record_provider_request(claim.provider_key, result="success")
        return True

    async def _schedule_failure(
        self,
        claim: _Claim,
        error: GpuProviderError,
        *,
        terminal_provider_job: bool = False,
    ) -> None:
        now = self._clock()
        async with self._sessions() as session:
            invocation = await self._locked_invocation(session, claim)
            if invocation is None or invocation.status in _TERMINAL_STATES:
                return
            attempt = await self._attempt(session, claim)
            lineage = await self._lineage_state(session, invocation)
            retry_category = classify_retry_error(error.code)
            category_attempt = (
                lineage.category_transitions.get(retry_category, 0) + 1
            )
            retry_decision = decide_retry(
                code=error.code,
                retryable=error.retryable,
                attempt_number=lineage.total_attempts,
                category_attempt_number=category_attempt,
                job_max_attempts=lineage.max_attempts,
                legacy_base_seconds=self._policy.backoff_base_seconds,
                legacy_cap_seconds=self._policy.backoff_max_seconds,
                jitter_ratio=self._policy.backoff_jitter_ratio,
                random_value=self._random(),
            )
            if attempt is not None:
                attempt.error_code = error.code
                attempt.retryable = error.retryable or retry_decision.category == "gpu_oom"
                attempt.last_polled_at = now
            invocation.last_error_code = error.code
            invocation.lease_token = None
            invocation.lease_expires_at = None
            invocation.updated_at = now
            transition_requested = retry_decision.strategy in {
                "reduce_or_escalate",
                "fallback",
            }
            transition_created = False
            transition_unavailable = False
            if transition_requested and retry_decision.transition_allowed:
                plan = await self._transition_plan(
                    session,
                    invocation,
                    category=retry_decision.category,
                    transition_attempt=category_attempt,
                    root_invocation_id=lineage.root_invocation_id,
                )
                if plan is not None:
                    await self._create_transition(
                        session,
                        invocation,
                        attempt,
                        error=error,
                        lineage=lineage,
                        plan=plan,
                        now=now,
                        delay_seconds=retry_decision.delay_seconds,
                    )
                    transition_created = True
                else:
                    transition_unavailable = True
            if transition_created:
                pass
            elif (
                not transition_requested
                and retry_decision.should_retry
                and not terminal_provider_job
                and invocation.provider_job_id
            ):
                invocation.status = "running"
                invocation.available_at = now + timedelta(seconds=retry_decision.delay_seconds)
                if attempt is not None:
                    attempt.status = "running"
            elif not transition_requested and retry_decision.should_retry:
                invocation.status = "retry"
                invocation.provider_job_id = None
                invocation.provider_status = None
                invocation.provider_deadline_at = None
                invocation.available_at = now + timedelta(seconds=retry_decision.delay_seconds)
                if attempt is not None:
                    attempt.status = "retry"
                    attempt.completed_at = now
                await append_gpu_event(
                    session,
                    invocation,
                    event_type="gpu.invocation.retry_scheduled.v1",
                    payload={
                        "attempt": invocation.attempt_count,
                        "code": error.code,
                        "delay_seconds": retry_decision.delay_seconds,
                        "retry_category": retry_decision.category,
                        "strategy": retry_decision.strategy,
                    },
                    occurred_at=now,
                )
            else:
                exhausted_retry = retry_decision.category in {
                    "provider_429",
                    "provider_5xx",
                    "download_timeout",
                    "gpu_oom",
                    "default",
                } and (
                    retry_decision.rule_exhausted
                    or retry_decision.job_budget_exhausted
                )
                invocation.status = "dead_letter" if exhausted_retry else "failed"
                invocation.completed_at = now
                if attempt is not None:
                    attempt.status = "failed"
                    attempt.completed_at = now
                await append_gpu_event(
                    session,
                    invocation,
                    event_type=f"gpu.invocation.{invocation.status}.v1",
                    payload={
                        "attempt": invocation.attempt_count,
                        "code": error.code,
                        "next_action": (
                            "manual_review"
                            if transition_requested
                            and (
                                transition_unavailable
                                or retry_decision.rule_exhausted
                                or retry_decision.job_budget_exhausted
                            )
                            else retry_decision.next_action
                        ),
                        "retry_category": retry_decision.category,
                        "strategy": retry_decision.strategy,
                        "transition_attempt": category_attempt,
                        "transition_unavailable": transition_unavailable,
                    },
                    occurred_at=now,
                )
                await self._enqueue_resume(session, invocation, now=now)
            await session.commit()
        if error.code in _ATTESTATION_ERRORS:
            record_provider_revision_mismatch(claim.provider_key)
        else:
            record_provider_request(claim.provider_key, result="failed")
        if error.code == "GPU_KNOWLEDGE_RESULT_INVALID":
            record_unsupported_claim(accepted=False)

    async def _finish_cancel(self, claim: _Claim) -> None:
        now = self._clock()
        async with self._sessions() as session:
            invocation = await self._locked_invocation(session, claim)
            if invocation is None or invocation.status in _TERMINAL_STATES:
                return
            attempt = await self._attempt(session, claim)
            timed_out = invocation.cancellation_reason == "timeout"
            invocation.provider_job_id = None
            invocation.provider_status = "CANCELLED"
            invocation.provider_deadline_at = None
            invocation.lease_token = None
            invocation.lease_expires_at = None
            invocation.updated_at = now
            if timed_out and invocation.attempt_count < invocation.max_attempts:
                invocation.status = "retry"
                invocation.cancellation_reason = None
                invocation.available_at = now + timedelta(
                    seconds=_backoff(
                        invocation.attempt_count,
                        policy=self._policy,
                        random_source=self._random,
                    )
                )
                if attempt is not None:
                    attempt.status = "timed_out"
                    attempt.error_code = "GPU_PROVIDER_JOB_TIMEOUT"
                    attempt.retryable = True
                    attempt.completed_at = now
                event_type = "gpu.invocation.retry_scheduled.v1"
                payload = {
                    "attempt": invocation.attempt_count,
                    "code": "GPU_PROVIDER_JOB_TIMEOUT",
                }
            elif timed_out:
                invocation.status = "dead_letter"
                invocation.last_error_code = "GPU_PROVIDER_JOB_TIMEOUT"
                invocation.completed_at = now
                if attempt is not None:
                    attempt.status = "timed_out"
                    attempt.error_code = "GPU_PROVIDER_JOB_TIMEOUT"
                    attempt.retryable = True
                    attempt.completed_at = now
                event_type = "gpu.invocation.dead_letter.v1"
                payload = {
                    "attempt": invocation.attempt_count,
                    "code": "GPU_PROVIDER_JOB_TIMEOUT",
                }
            else:
                invocation.status = "cancelled"
                invocation.completed_at = now
                if attempt is not None:
                    attempt.status = "cancelled"
                    attempt.completed_at = now
                event_type = "gpu.invocation.cancelled.v1"
                payload = {
                    "attempt": invocation.attempt_count,
                    "reason": invocation.cancellation_reason or "cancelled",
                }
            await append_gpu_event(
                session,
                invocation,
                event_type=event_type,
                payload=payload,
                occurred_at=now,
            )
            if invocation.status == "dead_letter" or (
                invocation.status == "cancelled"
                and invocation.cancellation_reason
                not in {"tombstone", "job_cancelled", "job_terminal"}
            ):
                await self._enqueue_resume(session, invocation, now=now)
            await session.commit()

    async def _retry_cancel(
        self,
        claim: _Claim,
        error: GpuProviderError,
    ) -> None:
        now = self._clock()
        async with self._sessions() as session:
            invocation = await self._locked_invocation(session, claim)
            if invocation is None or invocation.status in _TERMINAL_STATES:
                return
            invocation.last_error_code = error.code
            invocation.lease_token = None
            invocation.lease_expires_at = None
            invocation.updated_at = now
            if (
                error.retryable
                and invocation.cancel_attempt_count < self._policy.max_cancel_attempts
            ):
                invocation.status = "cancel_requested"
                invocation.available_at = now + timedelta(
                    seconds=_backoff(
                        invocation.cancel_attempt_count,
                        policy=self._policy,
                        random_source=self._random,
                    )
                )
                await append_gpu_event(
                    session,
                    invocation,
                    event_type="gpu.invocation.cancel_retry_scheduled.v1",
                    payload={
                        "attempt": invocation.cancel_attempt_count,
                        "code": error.code,
                    },
                    occurred_at=now,
                )
            else:
                invocation.status = "dead_letter"
                invocation.completed_at = now
                await append_gpu_event(
                    session,
                    invocation,
                    event_type="gpu.invocation.dead_letter.v1",
                    payload={
                        "attempt": invocation.cancel_attempt_count,
                        "code": "GPU_PROVIDER_CANCEL_UNCONFIRMED",
                    },
                    occurred_at=now,
                )
                if invocation.cancellation_reason not in {
                    "tombstone",
                    "job_cancelled",
                    "job_terminal",
                }:
                    await self._enqueue_resume(session, invocation, now=now)
            await session.commit()
        record_provider_request(claim.provider_key, result="failed")

    async def run_one(self) -> bool:
        claim = await self._claim()
        if claim is None:
            return False
        if claim.action == "local_terminal":
            return True
        try:
            if claim.action == "cancel":
                assert claim.provider_job_id is not None
                submitted = SubmittedGpuJob(
                    provider_job_id=claim.provider_job_id,
                    endpoint_id=claim.endpoint_id,
                    status=claim.provider_status or "IN_PROGRESS",
                )
                async with asyncio.timeout(self._policy.provider_call_timeout_seconds):
                    await self._client.cancel(submitted)
                await self._finish_cancel(claim)
                return True
            request = await self._request(claim)
            if claim.action == "submit":
                async with asyncio.timeout(self._policy.provider_call_timeout_seconds):
                    submitted = await self._client.submit(request)
                await self._record_submission(claim, submitted)
                return True
            assert claim.provider_job_id is not None
            submitted = SubmittedGpuJob(
                provider_job_id=claim.provider_job_id,
                endpoint_id=claim.endpoint_id,
                status=claim.provider_status or "IN_PROGRESS",
            )
            async with asyncio.timeout(self._policy.provider_call_timeout_seconds):
                observation = await self._client.poll_once(request, submitted)
            if observation.result is None:
                await self._record_poll_wait(claim, observation)
                return True
            body = await self._object_store.read_derived(claim.output_object_key)
            await self._admit_result(
                claim,
                observation.result,
                body,
                source="poll",
            )
            return True
        except TimeoutError:
            error = GpuProviderError("GPU_PROVIDER_CONTROL_PLANE_TIMEOUT", retryable=True)
        except GpuProviderError as exc:
            error = exc
        except Exception:
            error = GpuProviderError("GPU_PROVIDER_INTERNAL_FAILURE", retryable=False)
        if claim.action == "cancel":
            await self._retry_cancel(claim, error)
        else:
            await self._schedule_failure(
                claim,
                error,
                terminal_provider_job=error.code in _TERMINAL_PROVIDER_FAILURES,
            )
        return True

    async def admit_callback(
        self,
        *,
        invocation_id: uuid.UUID,
        provider_event_id: str,
        provider_event_sha256: str,
        result: GpuJobResult,
    ) -> bool:
        """Idempotently admit an already authenticated provider callback.

        The HTTP boundary must validate the callback signature before invoking
        this method. This method revalidates object evidence and tenant/job
        fences; it never trusts inline callback output.
        """

        if (
            not provider_event_id
            or len(provider_event_id) > 160
            or len(provider_event_sha256) != 64
            or any(character not in "0123456789abcdef" for character in provider_event_sha256)
        ):
            raise ValueError("invalid provider callback identity")
        async with self._sessions() as session:
            invocation = await session.scalar(
                select(GpuProviderInvocation).where(GpuProviderInvocation.id == invocation_id)
            )
            if invocation is None:
                return False
            if (
                invocation.provider_callback_id == provider_event_id
                and invocation.provider_callback_sha256 != provider_event_sha256
            ):
                raise GpuResultConflict("gpu_callback_payload_conflict")
            claim = _Claim(
                invocation_id=invocation.id,
                tenant_id=invocation.tenant_id,
                job_id=invocation.job_id,
                document_id=invocation.document_id,
                document_version_id=invocation.document_version_id,
                page_id=invocation.page_id,
                provider_key=invocation.provider_key,
                endpoint_id=invocation.endpoint_id,
                idempotency_key=invocation.idempotency_key,
                input_bucket=cast(Literal["source", "derived"], invocation.input_bucket),
                input_object_key=invocation.input_object_key,
                input_sha256=invocation.input_sha256,
                output_object_key=invocation.output_object_key,
                options=dict(invocation.options),
                model_revision=invocation.model_revision,
                runtime_image_digest=invocation.runtime_image_digest,
                adapter_version=invocation.adapter_version,
                attempt_number=invocation.attempt_count,
                lease_token=invocation.lease_token or uuid.uuid4(),
                provider_job_id=invocation.provider_job_id,
                provider_status=invocation.provider_status,
                action="poll",
                cancellation_reason=invocation.cancellation_reason,
            )
        body = await self._object_store.read_derived(claim.output_object_key)
        return await self._admit_result(
            claim,
            result,
            body,
            source="callback",
            callback_id=provider_event_id,
            callback_sha256=provider_event_sha256,
            require_lease=False,
        )

    async def run_batch(self, *, limit: int = 25) -> int:
        processed = 0
        for _ in range(max(1, min(500, limit))):
            if not await self.run_one():
                break
            processed += 1
        return processed

    async def run(self, *, poll_interval_seconds: float = 0.5) -> None:
        while not self._stopping:
            processed = await self.run_batch()
            if processed == 0 and not self._stopping:
                await asyncio.sleep(max(0.05, min(30.0, poll_interval_seconds)))


__all__ = [
    "DurableGpuClient",
    "GpuInvocationWorker",
    "GpuResultConflict",
    "GpuWorkerPolicy",
]
