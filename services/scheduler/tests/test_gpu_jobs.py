from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from akc_api.database import Base
from akc_api.deletions import create_deletion_request, process_deletion_request
from akc_api.gpu_jobs import (
    GpuInvocationConflict,
    GpuInvocationSpec,
    GpuTransitionPolicy,
    GpuTransitionTarget,
    enqueue_gpu_invocation,
)
from akc_api.gpu_provider import (
    GpuJobPoll,
    GpuJobRequest,
    GpuJobResult,
    GpuProviderError,
    SubmittedGpuJob,
)
from akc_api.knowledge_gpu import KNOWLEDGE_ARTIFACT_CONTRACT
from akc_api.models import (
    AuditEvent,
    CreditLedger,
    Document,
    GpuInvocationEvent,
    GpuProviderAttempt,
    GpuProviderInvocation,
    JobEvent,
    ModelRegistry,
    OutboxEvent,
    Page,
    ProcessingJob,
    Project,
    Tenant,
    User,
)
from akc_api.storage import UploadTarget
from akc_api.visual_gpu import VISUAL_ARTIFACT_CONTRACT
from akc_scheduler.database import (
    _POSTGRES_GPU_CAPABILITY_QUERY,
    SchedulerDatabasePrivilegeError,
    verify_gpu_database,
)
from akc_scheduler.gpu_jobs import (
    GpuInvocationWorker,
    GpuResultConflict,
    GpuWorkerPolicy,
)
from akc_scheduler.settings import SchedulerSettings
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

NOW = datetime(2099, 7, 29, 12, 0, tzinfo=UTC)
MODEL_REVISION = "a" * 40
IMAGE_DIGEST = "sha256:" + ("b" * 64)
ADAPTER_VERSION = "parser-adapter-1.3.0"
KNOWLEDGE_ADAPTER_VERSION = "qwen-adapter-1.0.0"
PROMPT_REVISION = "sha256:" + ("1" * 64)
SCHEMA_REVISION = "sha256:" + ("2" * 64)


class MutableClock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


@dataclass(frozen=True, slots=True)
class Seed:
    tenant_id: uuid.UUID
    job_id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID
    page_id: uuid.UUID


class MockObjectStore:
    def __init__(self) -> None:
        self.output_body = b""
        self.objects: dict[str, bytes] = {}
        self.grants: list[tuple[str, str, int]] = []
        self.delete_calls = 0

    async def create_gpu_input_target(
        self,
        *,
        bucket: str,
        object_key: str,
        expires: int,
    ) -> UploadTarget:
        self.grants.append(("input", object_key, expires))
        return UploadTarget(
            url=f"https://objects.example/{object_key}?X-Amz-Signature=test",
            headers={},
        )

    async def create_gpu_output_target(
        self,
        *,
        object_key: str,
        expires: int,
    ) -> UploadTarget:
        self.grants.append(("output", object_key, expires))
        return UploadTarget(
            url=f"https://objects.example/{object_key}?X-Amz-Signature=test",
            headers={"Content-Type": "application/json"},
        )

    async def read_derived(self, object_key: str) -> bytes:
        assert "/derived/" in f"/{object_key}"
        return self.objects.get(object_key, self.output_body)

    async def delete(self, bucket: str, object_key: str) -> bool:
        del bucket, object_key
        self.delete_calls += 1
        return True

    async def abort_multipart_upload(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
    ) -> None:
        del object_key, provider_upload_id


class FakeGpuClient:
    def __init__(
        self,
        *,
        engine: AsyncEngine,
        store: MockObjectStore,
        failures: int = 0,
    ) -> None:
        self.engine = engine
        self.store = store
        self.failures = failures
        self.requests: list[GpuJobRequest] = []
        self.cancelled: list[str] = []
        self.transaction_probe_succeeded = False

    async def _probe_no_open_write_transaction(self, job_id: uuid.UUID) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                update(GpuProviderInvocation)
                .where(GpuProviderInvocation.job_id == job_id)
                .values(updated_at=GpuProviderInvocation.updated_at)
            )
        self.transaction_probe_succeeded = True

    async def submit(self, request: GpuJobRequest) -> SubmittedGpuJob:
        self.requests.append(request)
        await self._probe_no_open_write_transaction(uuid.UUID(request.job_id))
        if self.failures:
            self.failures -= 1
            raise GpuProviderError("GPU_PROVIDER_UNAVAILABLE", retryable=True)
        return SubmittedGpuJob(
            provider_job_id="runpod-job-1",
            endpoint_id=request.endpoint_id,
            status="IN_QUEUE",
        )

    async def poll_once(
        self,
        request: GpuJobRequest,
        submitted: SubmittedGpuJob,
    ) -> GpuJobPoll:
        self.requests.append(request)
        await self._probe_no_open_write_transaction(uuid.UUID(request.job_id))
        result_id = "sha256:" + ("c" * 64)
        payload = {
            "ok": True,
            "schema_version": "1.0",
            "result_id": result_id,
            "job_id": request.job_id,
            "tenant_id": request.tenant_id,
            "provider": request.provider_key,
            "worker_kind": "parser",
            "model_revision": request.model_revision,
            "runtime_image_digest": request.runtime_image_digest,
            "adapter_version": request.adapter_version,
            "input_sha256": f"sha256:{request.input_sha256}",
            "input_bytes": 7,
            "idempotency_key": request.idempotency_key,
            "idempotent_replay": False,
            "blocks": [],
            "generated_claims": [],
            "warnings": [],
            "provider_metrics": {},
            "provider_raw": {},
            "metrics": {
                "gpu_seconds": 1.25,
                "cold_start_ms": 50.0,
                "estimated_cost_usd": 0.0002375,
                "metering_source": "worker_estimate_not_provider_invoice",
            },
        }
        body = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        self.store.output_body = body
        result = GpuJobResult(
            provider_job_id=submitted.provider_job_id,
            endpoint_id=request.endpoint_id,
            provider_key=request.provider_key,
            model_revision=request.model_revision,
            runtime_image_digest=request.runtime_image_digest,
            adapter_version=request.adapter_version,
            result_id=result_id,
            output_object_key=request.output_object_key,
            output_sha256="sha256:" + hashlib.sha256(body).hexdigest(),
            output_bytes=len(body),
            metrics=payload["metrics"],
            warnings=(),
            raw_provider_response_sha256="sha256:" + ("d" * 64),
        )
        return GpuJobPoll(status="COMPLETED", result=result)

    async def cancel(self, submitted: SubmittedGpuJob) -> None:
        self.cancelled.append(submitted.provider_job_id)


class FailFirstInvocationClient(FakeGpuClient):
    def __init__(
        self,
        *,
        engine: AsyncEngine,
        store: MockObjectStore,
        root_idempotency_key: str,
        error: GpuProviderError,
    ) -> None:
        super().__init__(engine=engine, store=store)
        self.root_idempotency_key = root_idempotency_key
        self.error = error
        self.failed = False

    async def submit(self, request: GpuJobRequest) -> SubmittedGpuJob:
        self.requests.append(request)
        await self._probe_no_open_write_transaction(uuid.UUID(request.job_id))
        if request.idempotency_key == self.root_idempotency_key and not self.failed:
            self.failed = True
            raise self.error
        return SubmittedGpuJob(
            provider_job_id=f"runpod-job-{len(self.requests)}",
            endpoint_id=request.endpoint_id,
            status="IN_QUEUE",
        )


class FakeKnowledgeClient(FakeGpuClient):
    def __init__(
        self,
        *,
        engine: AsyncEngine,
        store: MockObjectStore,
        evidence_block_id: str,
    ) -> None:
        super().__init__(engine=engine, store=store)
        self.evidence_block_id = evidence_block_id
        self.last_result: GpuJobResult | None = None

    async def poll_once(
        self,
        request: GpuJobRequest,
        submitted: SubmittedGpuJob,
    ) -> GpuJobPoll:
        self.requests.append(request)
        await self._probe_no_open_write_transaction(uuid.UUID(request.job_id))
        result_id = "sha256:" + ("9" * 64)
        payload = {
            "ok": True,
            "schema_version": "1.0",
            "result_id": result_id,
            "job_id": request.job_id,
            "tenant_id": request.tenant_id,
            "provider": request.provider_key,
            "worker_kind": "knowledge",
            "model_revision": request.model_revision,
            "runtime_image_digest": request.runtime_image_digest,
            "adapter_version": request.adapter_version,
            "input_sha256": f"sha256:{request.input_sha256}",
            "input_bytes": 100,
            "idempotency_key": request.idempotency_key,
            "idempotent_replay": False,
            "knowledge_bundle": {
                "schemaVersion": "knowledge-1.0.0",
                "documentId": request.document_id,
                "notes": [
                    {
                        "noteId": "note.summary",
                        "title": "Summary",
                        "noteType": "document",
                        "contentOrigin": "ai_summarized",
                        "evidenceBlockIds": [self.evidence_block_id],
                        "summary": "Grounded summary",
                        "claims": [],
                        "aliases": [],
                        "tags": [],
                        "relatedNoteCandidates": [],
                        "reviewStatus": "pending",
                    }
                ],
                "relations": [],
                "conflicts": [],
            },
            "warnings": [],
            "provider_metrics": {
                "prompt_sha256": PROMPT_REVISION,
                "knowledge_schema_sha256": SCHEMA_REVISION,
                "unsupported_claim_count": 0,
            },
            "provider_raw": {},
            "metrics": {
                "gpu_seconds": 1.0,
                "estimated_cost_usd": 0.001,
                "metering_source": "worker_estimate_not_provider_invoice",
            },
        }
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        self.store.objects[request.output_object_key] = body
        result = GpuJobResult(
            provider_job_id=submitted.provider_job_id,
            endpoint_id=request.endpoint_id,
            provider_key=request.provider_key,
            model_revision=request.model_revision,
            runtime_image_digest=request.runtime_image_digest,
            adapter_version=request.adapter_version,
            result_id=result_id,
            output_object_key=request.output_object_key,
            output_sha256="sha256:" + hashlib.sha256(body).hexdigest(),
            output_bytes=len(body),
            metrics=payload["metrics"],
            warnings=(),
            raw_provider_response_sha256="sha256:" + ("8" * 64),
        )
        self.last_result = result
        return GpuJobPoll(status="COMPLETED", result=result)


class FakeVisualClient(FakeGpuClient):
    async def poll_once(
        self,
        request: GpuJobRequest,
        submitted: SubmittedGpuJob,
    ) -> GpuJobPoll:
        self.requests.append(request)
        await self._probe_no_open_write_transaction(uuid.UUID(request.job_id))
        result_id = "sha256:" + ("7" * 64)
        payload = {
            "ok": True,
            "schema_version": "1.0",
            "result_id": result_id,
            "job_id": request.job_id,
            "tenant_id": request.tenant_id,
            "provider": request.provider_key,
            "worker_kind": "parser",
            "model_revision": request.model_revision,
            "runtime_image_digest": request.runtime_image_digest,
            "adapter_version": request.adapter_version,
            "input_sha256": f"sha256:{request.input_sha256}",
            "input_bytes": request.options["input_size_bytes"],
            "idempotency_key": request.idempotency_key,
            "idempotent_replay": False,
            "blocks": [
                {
                    "block_id": "blk_visual_fake_1",
                    "type": "paragraph",
                    "text": "Page-scoped visual output",
                    "origin": "ocr_extracted",
                    "confidence": 0.99,
                    "token_confidences": [0.99, 0.98, 0.99],
                    "source_refs": [
                        {
                            "document_id": request.document_id,
                            "document_version_id": request.document_version_id,
                            "page_index0": request.page_index0,
                            "page_number1": int(request.page_index0 or 0) + 1,
                            "bbox1000": [10, 20, 900, 200],
                        }
                    ],
                    "quality_flags": [],
                }
            ],
            "generated_claims": [],
            "warnings": [],
            "provider_metrics": {
                "pipeline_version": "v1.6",
                "block_count": 1,
            },
            "provider_raw": {},
            "metrics": {
                "gpu_seconds": 1.0,
                "estimated_cost_usd": 0.001,
                "metering_source": "worker_estimate_not_provider_invoice",
            },
        }
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        self.store.objects[request.output_object_key] = body
        return GpuJobPoll(
            status="COMPLETED",
            result=GpuJobResult(
                provider_job_id=submitted.provider_job_id,
                endpoint_id=request.endpoint_id,
                provider_key=request.provider_key,
                model_revision=request.model_revision,
                runtime_image_digest=request.runtime_image_digest,
                adapter_version=request.adapter_version,
                result_id=result_id,
                output_object_key=request.output_object_key,
                output_sha256="sha256:" + hashlib.sha256(body).hexdigest(),
                output_bytes=len(body),
                metrics=payload["metrics"],
                warnings=(),
                raw_provider_response_sha256="sha256:" + ("6" * 64),
            ),
        )


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
        assert statement is _POSTGRES_GPU_CAPABILITY_QUERY
        return FakeMappingResult(self.row)


@pytest_asyncio.fixture
async def harness(
    tmp_path: Path,
) -> tuple[
    AsyncEngine,
    async_sessionmaker[AsyncSession],
    Seed,
    MutableClock,
]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'gpu-jobs.db').as_posix()}")
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
    page_id = uuid.uuid4()
    job_id = uuid.uuid4()
    async with sessions() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, slug=f"t-{tenant_id.hex[:8]}", name="Tenant"),
                User(
                    id=user_id,
                    email=f"{user_id.hex}@example.com",
                    password_hash="not-used",  # noqa: S106
                    display_name="GPU test",
                ),
                Project(
                    id=project_id,
                    tenant_id=tenant_id,
                    name="GPU project",
                    created_by=user_id,
                ),
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    title="GPU document",
                    document_type="pdf",
                    status="READY",
                ),
                Page(
                    id=page_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    page_number=1,
                    status="NEEDS_REVIEW",
                    route="paddle_vl",
                    preflight_metrics={},
                    quality_metrics={},
                ),
                ProcessingJob(
                    id=job_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_id=document_id,
                    job_type="compile",
                    status="running",
                ),
            ]
        )
        await session.commit()
    clock = MutableClock()
    yield (
        engine,
        sessions,
        Seed(
            tenant_id,
            job_id,
            project_id,
            document_id,
            page_id,
        ),
        clock,
    )
    await engine.dispose()


def spec(seed: Seed, *, key: str = "gpu-job-1", max_attempts: int = 3) -> GpuInvocationSpec:
    return GpuInvocationSpec(
        tenant_id=seed.tenant_id,
        job_id=seed.job_id,
        project_id=seed.project_id,
        document_id=seed.document_id,
        document_version_id=f"{seed.document_id}:v1",
        provider_key="paddleocr_vl_1_6",
        endpoint_id="parser-accurate",
        idempotency_key=key,
        input_bucket="source",
        input_object_key=f"tenants/{seed.tenant_id}/source/input.bin",
        input_sha256="e" * 64,
        output_object_key=f"tenants/{seed.tenant_id}/derived/gpu/{key}.json",
        model_revision=MODEL_REVISION,
        runtime_image_digest=IMAGE_DIGEST,
        adapter_version=ADAPTER_VERSION,
        options={"language_hints": ["ko", "en"], "chart_recognition": True},
        max_attempts=max_attempts,
    )


def internal_fallback_policy(
    *,
    target_revision: str = "f" * 40,
    target_image_digest: str = "sha256:" + ("9" * 64),
    target_adapter_version: str = "paddle-adapter-2.0.0",
) -> GpuTransitionPolicy:
    target = GpuTransitionTarget(
        route="paddle_vl",
        route_profile="parse_balanced_v1",
        provider_key="paddleocr_vl_1_6",
        endpoint_id="parser-accurate",
        model_revision=target_revision,
        runtime_image_digest=target_image_digest,
        adapter_version=target_adapter_version,
        registry_policy_version="router-policy-1.0",
    )
    return GpuTransitionPolicy(
        source_route="hpd_fast",
        source_provider_key="hpd_parsing_1b",
        router_policy_version="router-policy-1.0",
        invalid_output_fallback=target,
        oom_escalation=target,
    )


def hpd_spec(
    seed: Seed,
    *,
    key: str,
    max_attempts: int = 3,
    transition_policy: GpuTransitionPolicy | None = None,
) -> GpuInvocationSpec:
    return GpuInvocationSpec(
        tenant_id=seed.tenant_id,
        job_id=seed.job_id,
        project_id=seed.project_id,
        document_id=seed.document_id,
        document_version_id=f"{seed.document_id}:v1",
        provider_key="hpd_parsing_1b",
        endpoint_id="parser-fast",
        idempotency_key=key,
        input_bucket="source",
        input_object_key=f"tenants/{seed.tenant_id}/source/input.bin",
        input_sha256="e" * 64,
        output_object_key=f"tenants/{seed.tenant_id}/derived/gpu/{key}.json",
        model_revision="d" * 40,
        runtime_image_digest="sha256:" + ("8" * 64),
        adapter_version="hpd-adapter-1.0.0",
        options={
            "route_profile": "parse_fast_v1",
            "max_output_tokens": 4096,
        },
        max_attempts=max_attempts,
        transition_policy=transition_policy,
    )


def knowledge_spec(
    seed: Seed,
    *,
    input_sha256: str,
    key: str = "knowledge-job-1",
) -> GpuInvocationSpec:
    return GpuInvocationSpec(
        tenant_id=seed.tenant_id,
        job_id=seed.job_id,
        project_id=seed.project_id,
        document_id=seed.document_id,
        document_version_id=f"{seed.document_id}:v1",
        provider_key="qwen3_5_4b",
        endpoint_id="knowledge-qwen",
        idempotency_key=key,
        input_bucket="derived",
        input_object_key=f"tenants/{seed.tenant_id}/derived/knowledge/input.json",
        input_sha256=input_sha256,
        output_object_key=f"tenants/{seed.tenant_id}/derived/knowledge/output.json",
        model_revision=MODEL_REVISION,
        runtime_image_digest=IMAGE_DIGEST,
        adapter_version=KNOWLEDGE_ADAPTER_VERSION,
        options={
            "artifact_contract": KNOWLEDGE_ARTIFACT_CONTRACT,
            "prompt_revision": PROMPT_REVISION,
            "knowledge_schema_sha256": SCHEMA_REVISION,
        },
    )


def visual_spec(
    seed: Seed,
    *,
    input_sha256: str,
    input_size_bytes: int,
) -> GpuInvocationSpec:
    return GpuInvocationSpec(
        tenant_id=seed.tenant_id,
        job_id=seed.job_id,
        project_id=seed.project_id,
        document_id=seed.document_id,
        document_version_id=f"{seed.document_id}:v1",
        page_id=seed.page_id,
        provider_key="paddleocr_vl_1_6",
        endpoint_id="parser-accurate",
        idempotency_key="visual-page-1",
        input_bucket="derived",
        input_object_key=(f"tenants/{seed.tenant_id}/derived/pages/1/inference-300.png"),
        input_sha256=input_sha256,
        output_object_key=(f"tenants/{seed.tenant_id}/derived/pages/1/visual.json"),
        model_revision=MODEL_REVISION,
        runtime_image_digest=IMAGE_DIGEST,
        adapter_version=ADAPTER_VERSION,
        options={
            "artifact_contract": VISUAL_ARTIFACT_CONTRACT,
            "page_index0": 0,
            "page_range": [1],
            "page_width_px": 1200,
            "page_height_px": 1600,
            "input_size_bytes": input_size_bytes,
            "page_asset_id": str(seed.page_id),
            "dpi": 300,
            "colorspace": "RGB",
            "route_profile": "parse_balanced_v1",
            "quality_profile": "normal",
            "schema_profile": "canonical-page-1.0",
        },
    )


def knowledge_input(seed: Seed, block_id: str = "blk_source") -> bytes:
    return json.dumps(
        {
            "schema_version": "knowledge-input-1.0.0",
            "document_id": str(seed.document_id),
            "document_version_id": f"{seed.document_id}:v1",
            "title": "Knowledge document",
            "blocks": [
                {
                    "block_id": block_id,
                    "text": "Grounded source text",
                    "source_refs": [
                        {
                            "document_id": str(seed.document_id),
                            "document_version_id": f"{seed.document_id}:v1",
                            "page_index0": 0,
                            "page_number1": 1,
                            "bbox1000": [0, 0, 1000, 1000],
                        }
                    ],
                }
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def policy() -> GpuWorkerPolicy:
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


def gpu_role_evidence() -> dict[str, object]:
    return {
        "effective_role": "akc_gpu_worker",
        "login_role": "akc_gpu_login",
        "bypass_rls": True,
        "can_login": False,
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
        "effective_table_acl_exact": True,
        "effective_column_acl_exact": True,
        "required_table_access": True,
        "forced_rls_present": True,
    }


@pytest.mark.asyncio
async def test_gpu_database_role_and_runtime_fail_closed() -> None:
    settings = SchedulerSettings(
        database_url="postgresql+asyncpg://user:pass@localhost/test",
        gpu_database_role="akc_gpu_worker",
    )
    capability = await verify_gpu_database(
        FakePostgresEngine(gpu_role_evidence()),  # type: ignore[arg-type]
        settings,
    )
    assert capability.purpose == "gpu"
    missing = gpu_role_evidence()
    missing["effective_column_acl_exact"] = False
    with pytest.raises(SchedulerDatabasePrivilegeError, match="effective_column_acl_exact"):
        await verify_gpu_database(
            FakePostgresEngine(missing),  # type: ignore[arg-type]
            settings,
        )
    with pytest.raises(ValueError, match="GPU worker mode requires"):
        SchedulerSettings().validate_gpu_runtime()


@pytest.mark.asyncio
async def test_enqueue_is_content_free_and_idempotent(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    _engine, sessions, seed, _clock = harness
    request = spec(seed)
    async with sessions() as session:
        first = await enqueue_gpu_invocation(session, request)
        replay = await enqueue_gpu_invocation(session, request)
        assert replay.id == first.id
        await session.commit()
    with pytest.raises(GpuInvocationConflict):
        async with sessions() as session:
            await enqueue_gpu_invocation(
                session,
                replace(spec(seed, key="gpu-job-1"), model_revision="f" * 40),
            )
    with pytest.raises(ValueError, match="content-bearing"):
        replace(
            spec(seed, key="gpu-content"),
            options={"blocks": [{"text": "forbidden original"}]},
        )


@pytest.mark.asyncio
async def test_submit_poll_and_verified_result_are_durable(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    async with sessions() as session:
        invocation = await enqueue_gpu_invocation(session, spec(seed))
        invocation_id = invocation.id
        await session.commit()
    store = MockObjectStore()
    client = FakeGpuClient(engine=engine, store=store)
    worker = GpuInvocationWorker(
        engine=engine,
        client=client,
        object_store=store,  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )

    assert await worker.run_one()
    clock.advance(2)
    assert await worker.run_one()
    assert client.transaction_probe_succeeded
    assert all("X-Amz-Signature" in request.input_url for request in client.requests)

    async with sessions() as session:
        stored = await session.get(GpuProviderInvocation, invocation_id)
        assert stored is not None
        assert stored.status == "completed"
        assert stored.result_manifest_sha256
        assert stored.result_manifest is not None
        assert stored.result_manifest["model_revision"] == MODEL_REVISION
        assert stored.result_manifest["runtime_image_digest"] == IMAGE_DIGEST
        assert "input_url" not in json.dumps(stored.result_manifest)
        attempts = list(
            (
                await session.scalars(
                    select(GpuProviderAttempt).where(
                        GpuProviderAttempt.invocation_id == invocation_id
                    )
                )
            ).all()
        )
        assert [(item.attempt_number, item.status) for item in attempts] == [(1, "completed")]
        events = list(
            (
                await session.scalars(
                    select(GpuInvocationEvent)
                    .where(GpuInvocationEvent.invocation_id == invocation_id)
                    .order_by(GpuInvocationEvent.sequence)
                )
            ).all()
        )
        assert events[-1].event_type == "gpu.invocation.completed.v1"


@pytest.mark.asyncio
async def test_visual_result_is_page_scoped_attested_and_resumes_parent(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    raster = b"\x89PNG\r\n\x1a\nexact-page-raster"
    raster_sha = hashlib.sha256(raster).hexdigest()
    request = visual_spec(
        seed,
        input_sha256=raster_sha,
        input_size_bytes=len(raster),
    )
    store = MockObjectStore()
    store.objects[request.input_object_key] = raster
    client = FakeVisualClient(engine=engine, store=store)
    async with sessions() as session:
        job = await session.get(ProcessingJob, seed.job_id)
        assert job is not None
        job.progress = {
            "stage": "visual_waiting",
            "state": "WAITING_PROVIDER",
            "page_id": str(seed.page_id),
        }
        invocation = await enqueue_gpu_invocation(session, request)
        invocation_id = invocation.id
        await session.commit()
    worker = GpuInvocationWorker(
        engine=engine,
        client=client,
        object_store=store,  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )

    assert await worker.run_one() is True
    assert client.requests[0].page_index0 == 0
    assert client.requests[0].input_object_key == request.input_object_key
    assert client.requests[0].options["page_width_px"] == 1200
    assert client.requests[0].options["page_height_px"] == 1600
    clock.advance(2)
    assert await worker.run_one() is True

    async with sessions() as session:
        invocation = await session.get(GpuProviderInvocation, invocation_id)
        assert invocation is not None and invocation.status == "completed"
        manifest = invocation.result_manifest
        assert manifest is not None
        assert manifest["visual_attestation"] == {
            "artifact_contract": VISUAL_ARTIFACT_CONTRACT,
            "schema_version": "1.0",
            "page_id": str(seed.page_id),
            "page_index0": 0,
            "page_width_px": 1200,
            "page_height_px": 1600,
            "input_size_bytes": len(raster),
            "block_count": 1,
            "source_ref_count": 1,
            "confidence_count": 4,
            "verification_present": 0,
        }
        resume = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == seed.job_id,
                OutboxEvent.event_type == "job.dispatch.requested.v1",
            )
        )
        assert resume is not None
        assert resume.payload["resume_invocation_id"] == str(invocation_id)


@pytest.mark.asyncio
async def test_knowledge_result_is_strictly_admitted_and_resumed_once(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    input_body = knowledge_input(seed)
    request_spec = knowledge_spec(
        seed,
        input_sha256=hashlib.sha256(input_body).hexdigest(),
    )
    async with sessions() as session:
        job = await session.get(ProcessingJob, seed.job_id)
        assert job is not None
        job.progress = {"stage": "knowledge_waiting"}
        invocation = await enqueue_gpu_invocation(session, request_spec)
        invocation_id = invocation.id
        await session.commit()
    store = MockObjectStore()
    store.objects[request_spec.input_object_key] = input_body
    client = FakeKnowledgeClient(
        engine=engine,
        store=store,
        evidence_block_id="blk_source",
    )
    worker = GpuInvocationWorker(
        engine=engine,
        client=client,
        object_store=store,  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )
    assert await worker.run_one()
    request = client.requests[-1]
    observation = await client.poll_once(
        request,
        SubmittedGpuJob("runpod-job-1", request.endpoint_id, "COMPLETED"),
    )
    assert observation.result is not None
    assert await worker.admit_callback(
        invocation_id=invocation_id,
        provider_event_id="knowledge-callback-replay",
        provider_event_sha256="7" * 64,
        result=observation.result,
    )
    assert client.last_result is not None
    assert await worker.admit_callback(
        invocation_id=invocation_id,
        provider_event_id="knowledge-callback-replay",
        provider_event_sha256="7" * 64,
        result=client.last_result,
    )
    async with sessions() as session:
        stored = await session.get(GpuProviderInvocation, invocation_id)
        assert stored is not None and stored.status == "completed"
        assert stored.result_manifest is not None
        assert stored.result_manifest["knowledge_attestation"] == {
            "artifact_contract": KNOWLEDGE_ARTIFACT_CONTRACT,
            "prompt_revision": PROMPT_REVISION,
            "knowledge_schema_sha256": SCHEMA_REVISION,
            "note_count": 1,
            "relation_count": 0,
            "conflict_count": 0,
            "unsupported_claim_count": 0,
        }
        resumes = list(
            (
                await session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id == seed.job_id,
                        OutboxEvent.event_type == "job.dispatch.requested.v1",
                    )
                )
            ).all()
        )
        assert len(resumes) == 1
        assert resumes[0].payload["resume_invocation_id"] == str(invocation_id)


@pytest.mark.asyncio
async def test_knowledge_evidence_mismatch_fails_and_wakes_dispatch(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    input_body = knowledge_input(seed)
    request_spec = knowledge_spec(
        seed,
        input_sha256=hashlib.sha256(input_body).hexdigest(),
        key="knowledge-evidence-mismatch",
    )
    async with sessions() as session:
        job = await session.get(ProcessingJob, seed.job_id)
        assert job is not None
        job.progress = {"stage": "knowledge_waiting"}
        invocation = await enqueue_gpu_invocation(session, request_spec)
        invocation_id = invocation.id
        await session.commit()
    store = MockObjectStore()
    store.objects[request_spec.input_object_key] = input_body
    client = FakeKnowledgeClient(
        engine=engine,
        store=store,
        evidence_block_id="blk_hallucinated",
    )
    worker = GpuInvocationWorker(
        engine=engine,
        client=client,
        object_store=store,  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )
    assert await worker.run_one()
    clock.advance(2)
    assert await worker.run_one()
    async with sessions() as session:
        stored = await session.get(GpuProviderInvocation, invocation_id)
        assert stored is not None
        assert stored.status == "failed"
        assert stored.last_error_code == "GPU_KNOWLEDGE_RESULT_INVALID"
        resume_count = len(
            list(
                (
                    await session.scalars(
                        select(OutboxEvent).where(
                            OutboxEvent.aggregate_id == seed.job_id,
                            OutboxEvent.event_type == "job.dispatch.requested.v1",
                        )
                    )
                ).all()
            )
        )
        assert resume_count == 1


@pytest.mark.asyncio
async def test_retry_budget_dead_letters_without_unbounded_submission(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    async with sessions() as session:
        job = await session.get(ProcessingJob, seed.job_id)
        assert job is not None
        job.progress = {"stage": "knowledge_waiting"}
        invocation = await enqueue_gpu_invocation(
            session,
            spec(seed, key="gpu-retry", max_attempts=2),
        )
        invocation_id = invocation.id
        await session.commit()
    store = MockObjectStore()
    client = FakeGpuClient(engine=engine, store=store, failures=2)
    worker = GpuInvocationWorker(
        engine=engine,
        client=client,
        object_store=store,  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )

    assert await worker.run_one()
    clock.advance(2)
    assert await worker.run_one()
    async with sessions() as session:
        stored = await session.get(GpuProviderInvocation, invocation_id)
        assert stored is not None
        assert stored.status == "dead_letter"
        assert stored.attempt_count == 2
        assert stored.last_error_code == "GPU_PROVIDER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_oom_creates_one_immutable_reduced_child_and_preserves_credit(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    request = replace(
        spec(seed, key="gpu-oom-transition", max_attempts=3),
        options={
            "language_hints": ["ko", "en"],
            "max_output_tokens": 4096,
        },
    )
    async with sessions() as session:
        job = await session.get(ProcessingJob, seed.job_id)
        assert job is not None
        session.add(
            CreditLedger(
                tenant_id=seed.tenant_id,
                job_id=seed.job_id,
                operation_key=f"job:{seed.job_id}:reserve",
                entry_type="reserve",
                credits=Decimal("5"),
                balance_after=Decimal("10"),
                reserved_after=Decimal("5"),
                metadata_json={"reason": "test_reservation"},
            )
        )
        parent = await enqueue_gpu_invocation(session, request)
        parent_id = parent.id
        parent_manifest_sha = parent.request_manifest_sha256
        job.progress = {
            "stage": "visual_waiting",
            "invocation_id": str(parent.id),
        }
        await session.commit()

    store = MockObjectStore()
    client = FakeGpuClient(engine=engine, store=store)
    worker = GpuInvocationWorker(
        engine=engine,
        client=client,
        object_store=store,  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )
    claim = await worker._claim()
    assert claim is not None
    oom = GpuProviderError("GPU_WORKER_OUT_OF_MEMORY", retryable=False)
    await worker._schedule_failure(claim, oom)
    # At-least-once delivery of the same leased failure is a no-op.
    await worker._schedule_failure(claim, oom)

    clock.advance(2)
    assert await worker.run_one()
    clock.advance(2)
    assert await worker.run_one()

    async with sessions() as session:
        invocations = list(
            (
                await session.scalars(
                    select(GpuProviderInvocation).order_by(
                        GpuProviderInvocation.created_at,
                        GpuProviderInvocation.id,
                    )
                )
            ).all()
        )
        assert len(invocations) == 2
        parent, child = (
            next(row for row in invocations if row.id == parent_id),
            next(row for row in invocations if row.id != parent_id),
        )
        assert parent.status == "failed"
        assert parent.request_manifest_sha256 == parent_manifest_sha
        assert parent.output_object_key == request.output_object_key
        assert child.status == "completed"
        assert child.parent_invocation_id == parent.id
        assert child.lineage_root_invocation_id == parent.id
        assert child.transition_category == "gpu_oom"
        assert child.transition_strategy == "reduce_or_escalate"
        assert child.transition_action == "reduce"
        assert child.transition_attempt == 1
        assert child.input_object_key == parent.input_object_key
        assert child.input_sha256 == parent.input_sha256
        assert child.output_object_key != parent.output_object_key
        assert child.options["max_output_tokens"] == 2048
        assert child.provider_key == parent.provider_key
        assert child.model_revision == parent.model_revision
        job = await session.get(ProcessingJob, seed.job_id)
        assert job is not None
        assert job.progress["invocation_id"] == str(child.id)
        ledger = list(
            (
                await session.scalars(
                    select(CreditLedger).where(CreditLedger.tenant_id == seed.tenant_id)
                )
            ).all()
        )
        assert len(ledger) == 1
        assert ledger[0].operation_key == f"job:{seed.job_id}:reserve"
        assert ledger[0].credits == Decimal("5")
        resumes = list(
            (
                await session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id == seed.job_id,
                        OutboxEvent.event_type == "job.dispatch.requested.v1",
                    )
                )
            ).all()
        )
        assert len(resumes) == 1
        assert resumes[0].payload["resume_invocation_id"] == str(child.id)
        transition_events = list(
            (
                await session.scalars(
                    select(GpuInvocationEvent).where(
                        GpuInvocationEvent.invocation_id == parent.id,
                        GpuInvocationEvent.event_type == "gpu.invocation.transitioned.v1",
                    )
                )
            ).all()
        )
        assert len(transition_events) == 1
        assert transition_events[0].payload["child_invocation_id"] == str(child.id)
        assert transition_events[0].payload["input_sha256"] == parent.input_sha256
        job_events = list(
            (
                await session.scalars(
                    select(JobEvent).where(
                        JobEvent.job_id == seed.job_id,
                        JobEvent.event_type == "job.stage.progress.v1",
                    )
                )
            ).all()
        )
        assert len(job_events) == 1
        assert job_events[0].payload["parent_invocation_id"] == str(parent.id)
        audits = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == seed.tenant_id,
                        AuditEvent.action == "gpu.invocation.transitioned",
                    )
                )
            ).all()
        )
        assert len(audits) == 1
        assert audits[0].target_id == str(child.id)


@pytest.mark.asyncio
async def test_invalid_output_uses_only_exact_enabled_registry_fallback(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    transition_policy = internal_fallback_policy()
    target = transition_policy.invalid_output_fallback
    assert target is not None
    request = hpd_spec(
        seed,
        key="gpu-invalid-fallback",
        transition_policy=transition_policy,
    )
    async with sessions() as session:
        job = await session.get(ProcessingJob, seed.job_id)
        assert job is not None
        session.add(
            ModelRegistry(
                endpoint=target.endpoint_id,
                model_id=target.provider_key,
                revision=target.model_revision,
                runtime_image_digest=target.runtime_image_digest,
                adapter_version=target.adapter_version,
                policy_version=target.registry_policy_version,
                benchmark_report="local-fake-transition.json",
                enabled=True,
                canary_percent=100,
            )
        )
        parent = await enqueue_gpu_invocation(session, request)
        parent_id = parent.id
        job.progress = {
            "stage": "visual_waiting",
            "invocation_id": str(parent.id),
        }
        await session.commit()

    store = MockObjectStore()
    client = FakeGpuClient(engine=engine, store=store)
    worker = GpuInvocationWorker(
        engine=engine,
        client=client,
        object_store=store,  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )
    claim = await worker._claim()
    assert claim is not None
    invalid = GpuProviderError("GPU_PROVIDER_INVALID_RESULT", retryable=False)
    await worker._schedule_failure(claim, invalid)
    await worker._schedule_failure(claim, invalid)
    assert await worker.run_one()
    clock.advance(2)
    assert await worker.run_one()

    async with sessions() as session:
        rows = list(
            (
                await session.scalars(
                    select(GpuProviderInvocation).order_by(
                        GpuProviderInvocation.created_at,
                        GpuProviderInvocation.id,
                    )
                )
            ).all()
        )
        assert len(rows) == 2
        parent = next(row for row in rows if row.id == parent_id)
        child = next(row for row in rows if row.id != parent_id)
        assert parent.status == "failed"
        assert child.status == "completed"
        assert child.parent_invocation_id == parent.id
        assert child.transition_category == "invalid_output"
        assert child.transition_strategy == "fallback"
        assert child.transition_action == "fallback"
        assert child.transition_attempt == 1
        assert child.provider_key == target.provider_key
        assert child.endpoint_id == target.endpoint_id
        assert child.model_revision == target.model_revision
        assert child.runtime_image_digest == target.runtime_image_digest
        assert child.adapter_version == target.adapter_version
        assert child.input_sha256 == parent.input_sha256
        assert child.output_object_key != parent.output_object_key
        assert child.options["route_profile"] == target.route_profile
        assert len(client.requests) == 2
        assert all(request.provider_key == target.provider_key for request in client.requests)
        assert await session.scalar(select(CreditLedger.id).limit(1)) is None


@pytest.mark.asyncio
async def test_transition_budget_registry_and_unsupported_fail_closed(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    transition_policy = internal_fallback_policy()
    async with sessions() as session:
        job = await session.get(ProcessingJob, seed.job_id)
        assert job is not None
        job.progress = {"stage": "visual_waiting"}
        oom_parent = await enqueue_gpu_invocation(
            session,
            replace(
                spec(seed, key="gpu-oom-budget", max_attempts=1),
                options={"max_output_tokens": 4096},
            ),
        )
        oom_parent_id = oom_parent.id
        await session.commit()

    worker = GpuInvocationWorker(
        engine=engine,
        client=FakeGpuClient(engine=engine, store=MockObjectStore()),
        object_store=MockObjectStore(),  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )
    claim = await worker._claim()
    assert claim is not None
    await worker._schedule_failure(
        claim,
        GpuProviderError("GPU_WORKER_OUT_OF_MEMORY", retryable=True),
    )

    async with sessions() as session:
        oom_parent = await session.get(GpuProviderInvocation, oom_parent_id)
        assert oom_parent is not None
        assert oom_parent.status == "dead_letter"
        assert (
            await session.scalar(
                select(GpuProviderInvocation.id).where(
                    GpuProviderInvocation.parent_invocation_id == oom_parent_id
                )
            )
            is None
        )
        terminal = await session.scalar(
            select(GpuInvocationEvent).where(
                GpuInvocationEvent.invocation_id == oom_parent_id,
                GpuInvocationEvent.event_type == "gpu.invocation.dead_letter.v1",
            )
        )
        assert terminal is not None
        assert terminal.payload["next_action"] == "manual_review"

        invalid_parent = await enqueue_gpu_invocation(
            session,
            hpd_spec(
                seed,
                key="gpu-unapproved-fallback",
                transition_policy=transition_policy,
            ),
        )
        invalid_parent_id = invalid_parent.id
        await session.commit()

    claim = await worker._claim()
    assert claim is not None
    await worker._schedule_failure(
        claim,
        GpuProviderError("GPU_PROVIDER_INVALID_RESULT", retryable=False),
    )
    async with sessions() as session:
        invalid_parent = await session.get(GpuProviderInvocation, invalid_parent_id)
        assert invalid_parent is not None
        assert invalid_parent.status == "failed"
        assert (
            await session.scalar(
                select(GpuProviderInvocation.id).where(
                    GpuProviderInvocation.parent_invocation_id == invalid_parent_id
                )
            )
            is None
        )
        failed = await session.scalar(
            select(GpuInvocationEvent).where(
                GpuInvocationEvent.invocation_id == invalid_parent_id,
                GpuInvocationEvent.event_type == "gpu.invocation.failed.v1",
            )
        )
        assert failed is not None
        assert failed.payload["transition_unavailable"] is True
        assert failed.payload["next_action"] == "manual_review"

        unsupported_parent = await enqueue_gpu_invocation(
            session,
            spec(seed, key="gpu-unsupported", max_attempts=3),
        )
        unsupported_parent_id = unsupported_parent.id
        await session.commit()

    claim = await worker._claim()
    assert claim is not None
    await worker._schedule_failure(
        claim,
        GpuProviderError("GPU_UNSUPPORTED_FILE_TYPE", retryable=True),
    )
    async with sessions() as session:
        unsupported_parent = await session.get(
            GpuProviderInvocation,
            unsupported_parent_id,
        )
        assert unsupported_parent is not None
        assert unsupported_parent.status == "failed"
        unsupported_event = await session.scalar(
            select(GpuInvocationEvent).where(
                GpuInvocationEvent.invocation_id == unsupported_parent_id,
                GpuInvocationEvent.event_type == "gpu.invocation.failed.v1",
            )
        )
        assert unsupported_event is not None
        assert unsupported_event.payload["next_action"] == "close"
        assert await session.scalar(select(CreditLedger.id).limit(1)) is None


@pytest.mark.asyncio
async def test_tombstone_cancels_provider_and_fences_result(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    async with sessions() as session:
        job = await session.get(ProcessingJob, seed.job_id)
        assert job is not None
        job.progress = {"stage": "knowledge_waiting"}
        invocation = await enqueue_gpu_invocation(
            session,
            spec(seed, key="gpu-cancel"),
        )
        invocation_id = invocation.id
        await session.commit()
    store = MockObjectStore()
    client = FakeGpuClient(engine=engine, store=store)
    worker = GpuInvocationWorker(
        engine=engine,
        client=client,
        object_store=store,  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )
    assert await worker.run_one()
    async with sessions() as session:
        document = await session.get(Document, seed.document_id)
        assert document is not None
        document.deletion_requested_at = clock()
        await session.commit()
    clock.advance(2)
    assert await worker.run_one()
    assert client.cancelled == ["runpod-job-1"]
    async with sessions() as session:
        stored = await session.get(GpuProviderInvocation, invocation_id)
        assert stored is not None
        assert stored.status == "cancelled"
        assert stored.result_manifest is None
        assert (
            await session.scalar(
                select(OutboxEvent.id).where(
                    OutboxEvent.aggregate_id == seed.job_id,
                    OutboxEvent.event_type == "job.dispatch.requested.v1",
                )
            )
            is None
        )


@pytest.mark.asyncio
async def test_callback_replay_is_idempotent_and_conflict_detected(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    async with sessions() as session:
        invocation = await enqueue_gpu_invocation(
            session,
            spec(seed, key="gpu-callback"),
        )
        invocation_id = invocation.id
        await session.commit()
    store = MockObjectStore()
    client = FakeGpuClient(engine=engine, store=store)
    worker = GpuInvocationWorker(
        engine=engine,
        client=client,
        object_store=store,  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )
    assert await worker.run_one()
    request = client.requests[-1]
    submitted = SubmittedGpuJob("runpod-job-1", request.endpoint_id, "COMPLETED")
    observation = await client.poll_once(request, submitted)
    assert observation.result is not None
    assert await worker.admit_callback(
        invocation_id=invocation_id,
        provider_event_id="callback-1",
        provider_event_sha256="f" * 64,
        result=observation.result,
    )
    assert await worker.admit_callback(
        invocation_id=invocation_id,
        provider_event_id="callback-1",
        provider_event_sha256="f" * 64,
        result=observation.result,
    )
    with pytest.raises(GpuResultConflict):
        await worker.admit_callback(
            invocation_id=invocation_id,
            provider_event_id="callback-1",
            provider_event_sha256="0" * 64,
            result=observation.result,
        )


@pytest.mark.asyncio
async def test_output_checksum_mismatch_fails_closed(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    async with sessions() as session:
        invocation = await enqueue_gpu_invocation(
            session,
            spec(seed, key="gpu-corrupt"),
        )
        invocation_id = invocation.id
        await session.commit()
    store = MockObjectStore()
    client = FakeGpuClient(engine=engine, store=store)
    original_poll = client.poll_once

    async def corrupt_poll(
        request: GpuJobRequest,
        submitted: SubmittedGpuJob,
    ) -> GpuJobPoll:
        result = await original_poll(request, submitted)
        store.output_body += b"tampered"
        return result

    client.poll_once = corrupt_poll  # type: ignore[method-assign]
    worker = GpuInvocationWorker(
        engine=engine,
        client=client,
        object_store=store,  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )
    assert await worker.run_one()
    clock.advance(2)
    assert await worker.run_one()
    async with sessions() as session:
        stored = await session.get(GpuProviderInvocation, invocation_id)
        assert stored is not None
        assert stored.status == "failed"
        assert stored.last_error_code == "GPU_RESULT_OBJECT_CHECKSUM_MISMATCH"


@pytest.mark.asyncio
async def test_provider_summary_must_match_verified_output_object(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    engine, sessions, seed, clock = harness
    async with sessions() as session:
        invocation = await enqueue_gpu_invocation(
            session,
            spec(seed, key="gpu-summary-mismatch"),
        )
        invocation_id = invocation.id
        await session.commit()
    store = MockObjectStore()
    client = FakeGpuClient(engine=engine, store=store)
    original_poll = client.poll_once

    async def mismatched_poll(
        request: GpuJobRequest,
        submitted: SubmittedGpuJob,
    ) -> GpuJobPoll:
        observation = await original_poll(request, submitted)
        assert observation.result is not None
        return replace(
            observation,
            result=replace(
                observation.result,
                metrics={"gpu_seconds": 999},
            ),
        )

    client.poll_once = mismatched_poll  # type: ignore[method-assign]
    worker = GpuInvocationWorker(
        engine=engine,
        client=client,
        object_store=store,  # type: ignore[arg-type]
        policy=policy(),
        clock=clock,
        random_source=lambda: 0.5,
    )
    assert await worker.run_one()
    clock.advance(2)
    assert await worker.run_one()
    async with sessions() as session:
        stored = await session.get(GpuProviderInvocation, invocation_id)
        assert stored is not None
        assert stored.status == "failed"
        assert stored.last_error_code == "GPU_RESULT_OBJECT_SCOPE_MISMATCH"


@pytest.mark.asyncio
async def test_deletion_manifest_and_barrier_cover_inflight_gpu_output(
    harness: tuple[AsyncEngine, async_sessionmaker[AsyncSession], Seed, MutableClock],
) -> None:
    _engine, sessions, seed, clock = harness
    request_spec = spec(seed, key="gpu-delete")
    async with sessions() as session:
        invocation = await enqueue_gpu_invocation(session, request_spec)
        invocation.provider_job_id = "runpod-job-delete"
        invocation.provider_status = "IN_PROGRESS"
        invocation.status = "running"
        invocation.object_grant_expires_at = clock() + timedelta(minutes=10)
        invocation_id = invocation.id
        await session.commit()
    async with sessions() as session:
        deletion, created = await create_deletion_request(
            session,
            tenant_id=seed.tenant_id,
            actor_id=None,
            target_type="document",
            target_id=seed.document_id,
        )
        assert created
        assert (
            str(invocation_id) in deletion.manifest["database_targets"]["gpu_provider_invocations"]
        )
        assert any(
            target["bucket"] == "derived" and target["object_key"] == request_spec.output_object_key
            for target in deletion.manifest["object_targets"]
        )
        deletion_id = deletion.id
        await session.commit()
    store = MockObjectStore()
    result = await process_deletion_request(
        sessions,
        object_store=store,  # type: ignore[arg-type]
        request_id=deletion_id,
        clock=clock,
    )
    assert result.state == "retry"
    assert store.delete_calls == 0
    async with sessions() as session:
        invocation = await session.get(GpuProviderInvocation, invocation_id)
        assert invocation is not None
        assert invocation.status == "cancel_requested"
        assert invocation.cancellation_reason == "tombstone"
