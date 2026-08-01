from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from akc_api.database import Base
from akc_api.gpu_provider import GpuJobResult, GpuProviderError
from akc_api.models import (
    Collection,
    CollectionEvent,
    CreditLedger,
    Document,
    GpuProviderAttempt,
    GpuProviderInvocation,
    ProcessingJob,
    Project,
    Tenant,
    User,
)
from akc_api.parallel_models import (
    AcceptedBlock,
    AttemptValidation,
    ParallelParseAttempt,
    ParallelParseShard,
)
from akc_api.storage import UploadTarget
from akc_scheduler.gpu_jobs import GpuInvocationWorker, GpuWorkerPolicy
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

NOW = datetime(2099, 8, 1, 12, 0, tzinfo=UTC)
MODEL_REVISION = "a" * 40
IMAGE_DIGEST = "sha256:" + ("b" * 64)
ADAPTER_VERSION = "parallel-parser-adapter-6.0.0"
GPU_INPUT_SHA256 = "c" * 64
SHARD_INPUT_SHA256 = "d" * 64
REQUEST_SHA256 = "e" * 64


@dataclass(frozen=True, slots=True)
class ParallelSeed:
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID
    job_id: uuid.UUID
    collection_id: uuid.UUID
    invocation_id: uuid.UUID
    shard_id: uuid.UUID
    attempt_id: uuid.UUID
    output_object_key: str
    envelope: dict[str, Any]


class CallbackObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def read_derived(self, object_key: str) -> bytes:
        return self.objects[object_key]

    async def create_gpu_input_target(
        self,
        *,
        bucket: str,
        object_key: str,
        expires: int,
    ) -> UploadTarget:
        del bucket, expires
        return UploadTarget(url=f"https://objects.example/{object_key}", headers={})

    async def create_gpu_output_target(
        self,
        *,
        object_key: str,
        expires: int,
    ) -> UploadTarget:
        del expires
        return UploadTarget(url=f"https://objects.example/{object_key}", headers={})


class UnusedGpuClient:
    async def submit(self, request: object) -> object:
        del request
        raise AssertionError("callback tests do not submit")

    async def poll_once(self, request: object, submitted: object) -> object:
        del request, submitted
        raise AssertionError("callback tests do not poll")

    async def cancel(self, submitted: object) -> None:
        del submitted
        raise AssertionError("callback tests do not cancel")


def _policy() -> GpuWorkerPolicy:
    return GpuWorkerPolicy(
        lease_seconds=60,
        provider_call_timeout_seconds=10,
        provider_job_timeout_seconds=600,
        poll_interval_seconds=1,
        presign_ttl_seconds=600,
        backoff_base_seconds=1,
        backoff_max_seconds=2,
        backoff_jitter_ratio=0,
    )


@pytest_asyncio.fixture
async def parallel_harness(
    tmp_path: Path,
) -> tuple[
    AsyncEngine,
    async_sessionmaker[AsyncSession],
    CallbackObjectStore,
    ParallelSeed,
]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'parallel-v6-gpu.db').as_posix()}"
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
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    job_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    invocation_id = uuid.uuid4()
    shard_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    output_object_key = f"tenants/{tenant_id}/derived/parallel/{attempt_id}.json"
    document_version_id = f"{document_id}:v1"
    envelope: dict[str, Any] = {
        "schema_version": "parallel-v6-output-admission-1.0",
        "issuer": "akc-api",
        "tenant_id": str(tenant_id),
        "collection_id": str(collection_id),
        "processing_job_id": str(job_id),
        "document_id": str(document_id),
        "document_version_id": document_version_id,
        "shard_id": str(shard_id),
        "attempt_id": str(attempt_id),
        "expected_input_sha256": GPU_INPUT_SHA256,
        "expected_shard_input_sha256": SHARD_INPUT_SHA256,
        "expected_request_sha256": REQUEST_SHA256,
        "expected_output_object_key": output_object_key,
        "expected_model_revision": MODEL_REVISION,
        "expected_runtime_image_digest": IMAGE_DIGEST,
        "expected_adapter_version": ADAPTER_VERSION,
    }
    async with sessions() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, slug=f"t-{tenant_id.hex[:8]}", name="Tenant"),
                User(
                    id=user_id,
                    email=f"{user_id.hex}@example.com",
                    password_hash="not-used",  # noqa: S106
                    display_name="Parallel GPU test",
                ),
                Project(
                    id=project_id,
                    tenant_id=tenant_id,
                    name="Parallel project",
                    created_by=user_id,
                ),
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    title="Parallel document",
                    document_type="pdf",
                    status="READY",
                ),
                ProcessingJob(
                    id=job_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_id=document_id,
                    job_type="compile",
                    status="running",
                ),
                Collection(
                    id=collection_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    name="Parallel collection",
                    status="PROCESSING",
                    created_by=user_id,
                ),
            ]
        )
        await session.flush()
        invocation = GpuProviderInvocation(
            id=invocation_id,
            tenant_id=tenant_id,
            job_id=job_id,
            project_id=project_id,
            document_id=document_id,
            document_version_id=document_version_id,
            provider="runpod",
            provider_key="paddleocr_vl_1_6",
            endpoint_id="parser-accurate",
            idempotency_key=f"parallel-v6-{attempt_id}",
            request_manifest_sha256="f" * 64,
            status="submitted",
            input_bucket="source",
            input_object_key=f"tenants/{tenant_id}/source/input.pdf",
            input_sha256=GPU_INPUT_SHA256,
            output_object_key=output_object_key,
            options={"parallel_v6": envelope},
            model_revision=MODEL_REVISION,
            runtime_image_digest=IMAGE_DIGEST,
            adapter_version=ADAPTER_VERSION,
            attempt_count=1,
            max_attempts=3,
            provider_job_id="runpod-parallel-job-1",
            provider_status="COMPLETED",
        )
        session.add(invocation)
        await session.flush()
        session.add_all(
            [
                GpuProviderAttempt(
                    tenant_id=tenant_id,
                    invocation_id=invocation_id,
                    attempt_number=1,
                    status="submitted",
                    request_manifest_sha256="f" * 64,
                    provider_job_id="runpod-parallel-job-1",
                ),
                ParallelParseShard(
                    id=shard_id,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    document_id=document_id,
                    processing_job_id=job_id,
                    document_version_id=document_version_id,
                    shard_key=f"parallel-shard-{shard_id}",
                    shard_kind="page",
                    ordinal=0,
                    page_start=1,
                    page_end=1,
                    region={},
                    context={},
                    overlap={},
                    ownership={"primary_page_ids": ["page-1"]},
                    route_class="normal_scan",
                    priority=50,
                    size_units=1,
                    plan_version="parallel-v6",
                    input_sha256=SHARD_INPUT_SHA256,
                    status="RUNNING",
                    dispatch_idempotency_key=f"dispatch-{shard_id}",
                ),
            ]
        )
        await session.flush()
        session.add(
            ParallelParseAttempt(
                id=attempt_id,
                tenant_id=tenant_id,
                shard_id=shard_id,
                provider_invocation_id=invocation_id,
                attempt_number=1,
                attempt_kind="primary",
                state="RUNNING",
                pool_key="paddleocr-vl",
                worker_id="runpod-worker-1",
                model_id="paddleocr-vl-1.6",
                model_revision=MODEL_REVISION,
                runtime_identity=IMAGE_DIGEST,
                route_policy_version="parallel-router-v6",
                idempotency_key=f"attempt-{attempt_id}",
                request_sha256=REQUEST_SHA256,
                billing_disposition="pending",
            )
        )
        await session.commit()
    store = CallbackObjectStore()
    seed = ParallelSeed(
        tenant_id=tenant_id,
        project_id=project_id,
        document_id=document_id,
        job_id=job_id,
        collection_id=collection_id,
        invocation_id=invocation_id,
        shard_id=shard_id,
        attempt_id=attempt_id,
        output_object_key=output_object_key,
        envelope=envelope,
    )
    yield engine, sessions, store, seed
    await engine.dispose()


def _result(seed: ParallelSeed, store: CallbackObjectStore) -> GpuJobResult:
    result_id = "sha256:" + ("1" * 64)
    metrics = {
        "gpu_seconds": 1.25,
        "estimated_cost_usd": 0.0002375,
        "metering_source": "worker_estimate_not_provider_invoice",
    }
    payload = {
        "ok": True,
        "schema_version": "1.0",
        "result_id": result_id,
        "job_id": str(seed.job_id),
        "tenant_id": str(seed.tenant_id),
        "provider": "paddleocr_vl_1_6",
        "worker_kind": "parser",
        "model_revision": MODEL_REVISION,
        "runtime_image_digest": IMAGE_DIGEST,
        "adapter_version": ADAPTER_VERSION,
        "input_sha256": f"sha256:{GPU_INPUT_SHA256}",
        "input_bytes": 42,
        "idempotency_key": f"parallel-v6-{seed.attempt_id}",
        "idempotent_replay": False,
        "blocks": [],
        "generated_claims": [],
        "warnings": [],
        "provider_metrics": {},
        "provider_raw": {},
        "metrics": metrics,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    store.objects[seed.output_object_key] = body
    return GpuJobResult(
        provider_job_id="runpod-parallel-job-1",
        endpoint_id="parser-accurate",
        provider_key="paddleocr_vl_1_6",
        model_revision=MODEL_REVISION,
        runtime_image_digest=IMAGE_DIGEST,
        adapter_version=ADAPTER_VERSION,
        result_id=result_id,
        output_object_key=seed.output_object_key,
        output_sha256="sha256:" + hashlib.sha256(body).hexdigest(),
        output_bytes=len(body),
        metrics=metrics,
        warnings=(),
        raw_provider_response_sha256="sha256:" + ("2" * 64),
        provider_queue_delay_ms=250,
        provider_execution_time_ms=1250,
    )


def _worker(
    engine: AsyncEngine,
    store: CallbackObjectStore,
) -> GpuInvocationWorker:
    return GpuInvocationWorker(
        engine=engine,
        client=UnusedGpuClient(),  # type: ignore[arg-type]
        object_store=store,  # type: ignore[arg-type]
        policy=_policy(),
        clock=lambda: NOW,
        random_source=lambda: 0.5,
    )


@pytest.mark.asyncio
async def test_parallel_callback_admits_output_only_and_replays_without_duplicate_event(
    parallel_harness: tuple[
        AsyncEngine,
        async_sessionmaker[AsyncSession],
        CallbackObjectStore,
        ParallelSeed,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions, store, seed = parallel_harness
    worker = _worker(engine, store)
    result = _result(seed, store)
    observations: list[dict[str, object]] = []
    monkeypatch.setattr(
        "akc_scheduler.gpu_jobs.observe_parallel_provider_job",
        lambda **kwargs: observations.append(kwargs),
    )

    assert await worker.admit_callback(
        invocation_id=seed.invocation_id,
        provider_event_id="parallel-provider-event-1",
        provider_event_sha256="3" * 64,
        result=result,
    )
    assert observations == [
        {
            "provider": "runpod",
            "queue_delay_seconds": 0.25,
            "execution_seconds": 1.25,
        }
    ]
    assert await worker.admit_callback(
        invocation_id=seed.invocation_id,
        provider_event_id="parallel-provider-event-1",
        provider_event_sha256="3" * 64,
        result=result,
    )
    assert len(observations) == 1

    async with sessions() as session:
        invocation = await session.get(GpuProviderInvocation, seed.invocation_id)
        attempt = await session.get(ParallelParseAttempt, seed.attempt_id)
        shard = await session.get(ParallelParseShard, seed.shard_id)
        assert invocation is not None and invocation.status == "completed"
        assert attempt is not None
        assert attempt.state == "OUTPUT_RECEIVED"
        assert attempt.output_sha256 == result.output_sha256.removeprefix("sha256:")
        assert attempt.output_artifact_key == seed.output_object_key
        assert attempt.gpu_milliseconds == 1_250
        assert attempt.billing_disposition == "pending"
        assert shard is not None and shard.status == "RUNNING"
        assert await session.scalar(select(func.count()).select_from(CreditLedger)) == 0
        assert await session.scalar(select(func.count()).select_from(AcceptedBlock)) == 0
        assert await session.scalar(select(func.count()).select_from(AttemptValidation)) == 0
        event_count = await session.scalar(
            select(func.count())
            .select_from(CollectionEvent)
            .where(
                CollectionEvent.collection_id == seed.collection_id,
                CollectionEvent.event_type == "attempt.output.received.v1",
            )
        )
        assert event_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["malformed", "cross_scope"])
async def test_parallel_callback_rejects_bad_envelope_without_completing_provider_result(
    parallel_harness: tuple[
        AsyncEngine,
        async_sessionmaker[AsyncSession],
        CallbackObjectStore,
        ParallelSeed,
    ],
    mutation: str,
) -> None:
    engine, sessions, store, seed = parallel_harness
    async with sessions() as session:
        invocation = await session.get(GpuProviderInvocation, seed.invocation_id)
        assert invocation is not None
        envelope = dict(seed.envelope)
        if mutation == "malformed":
            envelope.pop("expected_request_sha256")
        else:
            envelope["tenant_id"] = str(uuid.uuid4())
        invocation.options = {"parallel_v6": envelope}
        await session.commit()
    worker = _worker(engine, store)
    result = _result(seed, store)

    with pytest.raises(GpuProviderError) as exc_info:
        await worker.admit_callback(
            invocation_id=seed.invocation_id,
            provider_event_id=f"parallel-provider-event-{mutation}",
            provider_event_sha256="4" * 64,
            result=result,
        )
    assert exc_info.value.code in {
        "GPU_PARALLEL_V6_ENVELOPE_INVALID_OUTPUT",
        "GPU_PARALLEL_V6_RESULT_SCOPE_MISMATCH",
    }

    async with sessions() as session:
        invocation = await session.get(GpuProviderInvocation, seed.invocation_id)
        attempt = await session.get(ParallelParseAttempt, seed.attempt_id)
        assert invocation is not None and invocation.status == "submitted"
        assert invocation.result_manifest is None
        assert attempt is not None and attempt.state == "RUNNING"
        assert attempt.output_sha256 is None
        assert await session.scalar(select(func.count()).select_from(CollectionEvent)) == 0


@pytest.mark.asyncio
async def test_parallel_output_rolls_back_if_gpu_completion_event_cannot_persist(
    parallel_harness: tuple[
        AsyncEngine,
        async_sessionmaker[AsyncSession],
        CallbackObjectStore,
        ParallelSeed,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions, store, seed = parallel_harness
    worker = _worker(engine, store)
    result = _result(seed, store)

    async def fail_gpu_event(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced gpu event failure")

    monkeypatch.setattr("akc_scheduler.gpu_jobs.append_gpu_event", fail_gpu_event)
    with pytest.raises(RuntimeError, match="forced gpu event failure"):
        await worker.admit_callback(
            invocation_id=seed.invocation_id,
            provider_event_id="parallel-provider-event-rollback",
            provider_event_sha256="5" * 64,
            result=result,
        )

    async with sessions() as session:
        invocation = await session.get(GpuProviderInvocation, seed.invocation_id)
        attempt = await session.get(ParallelParseAttempt, seed.attempt_id)
        assert invocation is not None and invocation.status == "submitted"
        assert attempt is not None and attempt.state == "RUNNING"
        assert attempt.output_sha256 is None
        assert await session.scalar(select(func.count()).select_from(CollectionEvent)) == 0
