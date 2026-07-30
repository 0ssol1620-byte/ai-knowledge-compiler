"""Executable evidence for durable, sandboxed document analysis."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import (
    AnalysisTask,
    Block,
    CreditLedger,
    Document,
    FeatureFlag,
    GpuProviderInvocation,
    ModelRegistry,
    OutboxEvent,
    Page,
    PageAsset,
    ProcessingJob,
    Project,
    ReviewItem,
    Tenant,
    utcnow,
)
from akc_api.services import run_compile_job
from akc_api.settings import Settings
from akc_api.visual_gpu import validate_visual_result, visual_attestation
from akc_worker_document.settings import AnalysisWorkerSettings
from akc_worker_document.worker import (
    AnalysisAttemptError,
    AnalysisRuntime,
    AnalysisWorker,
    analysis_claim_statement,
)
from docx import Document as WordDocument
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfWriter
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

_TEST_SUPPORT_KEY = "analysis-isolation-verification-key"


@pytest_asyncio.fixture
async def analysis_api(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, Settings]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'analysis.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        analysis_max_source_bytes=1024 * 1024,
        analysis_max_attempts=2,
        analysis_lease_seconds=40,
        analysis_attempt_timeout_seconds=30,
        analysis_backoff_base_seconds=0.01,
        analysis_backoff_max_seconds=0.02,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
        test_support_key=_TEST_SUPPORT_KEY,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client, app, settings


async def _register(
    client: httpx.AsyncClient,
    *,
    email: str = "analysis-owner@example.com",
    tenant_name: str = "Analysis Isolation",
) -> dict[str, Any]:
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": "Analysis Owner",
            "tenant_name": tenant_name,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["email_verified"] is False
    captured = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _TEST_SUPPORT_KEY},
        json={"email": email},
    )
    assert captured.status_code == 200
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": captured.json()["token"]},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def _create_project(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/v1/projects",
        json={"name": f"Sandbox {uuid.uuid4()}", "description": "Isolation evidence"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _upload(
    client: httpx.AsyncClient,
    *,
    project_id: str,
    filename: str,
    content_type: str,
    content: bytes,
) -> str:
    digest = hashlib.sha256(content).hexdigest()
    initiated = await client.post(
        "/v1/uploads/initiate",
        json={
            "project_id": project_id,
            "filename": filename,
            "size": len(content),
            "content_type": content_type,
            "sha256": digest,
        },
    )
    assert initiated.status_code == 201, initiated.text
    target = initiated.json()
    uploaded = await client.put(
        target["upload_url"],
        content=content,
        headers=target["headers"],
    )
    assert uploaded.status_code == 204, uploaded.text
    completed = await client.post(
        f"/v1/uploads/{target['upload_id']}/complete",
        json={"sha256": digest},
    )
    assert completed.status_code == 200, completed.text
    return str(target["document_id"])


async def _enqueue(client: httpx.AsyncClient, document_id: str) -> uuid.UUID:
    response = await client.post(f"/v1/documents/{document_id}/analyze")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    return uuid.UUID(response.json()["task_id"])


def _worker(app: Any, settings: Settings) -> AnalysisWorker:
    return AnalysisWorker(
        engine=app.state.database.engine,
        store=app.state.object_store,
        runtime=AnalysisRuntime.from_api_settings(settings),
    )


async def test_enqueue_is_naturally_idempotent_and_rejects_oversize_before_upload(
    analysis_api: tuple[httpx.AsyncClient, Any, Settings],
) -> None:
    client, app, settings = analysis_api
    registration = await _register(client)
    tenant_id = uuid.UUID(registration["tenant_id"])
    project_id = await _create_project(client)

    async with app.state.database.sessions.begin() as session:
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None
        tenant.plan_code = "team"
    rejected = await client.post(
        "/v1/uploads/initiate",
        json={
            "project_id": project_id,
            "filename": "too-large.pdf",
            "size": settings.analysis_max_source_bytes + 1,
            "content_type": "application/pdf",
            "sha256": "0" * 64,
        },
    )
    assert rejected.status_code == 413
    assert rejected.json()["error"]["code"] == "ANALYSIS_SOURCE_TOO_LARGE"
    assert rejected.json()["error"]["details"]["max_bytes"] == settings.analysis_max_source_bytes

    document_id = await _upload(
        client,
        project_id=project_id,
        filename="idempotent.txt",
        content_type="text/plain",
        content=b"one durable task and one outbox event",
    )
    first = await client.post(f"/v1/documents/{document_id}/analyze")
    second = await client.post(f"/v1/documents/{document_id}/analyze")
    assert first.status_code == second.status_code == 202
    assert first.json()["task_id"] == second.json()["task_id"]
    assert first.json()["status"] == second.json()["status"] == "queued"

    task_id = uuid.UUID(first.json()["task_id"])
    async with app.state.database.sessions() as session:
        task_count = await session.scalar(
            select(func.count(AnalysisTask.id)).where(AnalysisTask.id == task_id)
        )
        outbox_count = await session.scalar(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.aggregate_id == task_id,
                OutboxEvent.event_type == "document.analysis.requested.v1",
            )
        )
    assert task_count == 1
    assert outbox_count == 1


async def test_single_worker_concurrency_persists_one_result_and_tenant_safe_preview(
    analysis_api: tuple[httpx.AsyncClient, Any, Settings],
) -> None:
    client, app, settings = analysis_api
    await _register(client)
    project_id = await _create_project(client)
    document_id = await _upload(
        client,
        project_id=project_id,
        filename="preview.txt",
        content_type="text/plain",
        content=b"Rendered preview with a provenance-aligned bounding box.",
    )
    task_id = await _enqueue(client, document_id)
    worker = _worker(app, settings)

    outcomes = await asyncio.gather(
        worker.run_once(task_id=task_id),
        worker.run_once(task_id=task_id),
    )
    assert sorted(outcomes) == [False, True]
    assert await worker.run_once(task_id=task_id) is False

    async with app.state.database.sessions() as session:
        task = await session.get(AnalysisTask, task_id)
        pages = list(
            await session.scalars(select(Page).where(Page.document_id == uuid.UUID(document_id)))
        )
        blocks = list(
            await session.scalars(select(Block).where(Block.document_id == uuid.UUID(document_id)))
        )
        assets = (
            list(await session.scalars(select(PageAsset).where(PageAsset.page_id == pages[0].id)))
            if pages
            else []
        )
    assert task is not None
    assert task.status == "completed"
    assert task.attempt_count == 1
    assert len(pages) == len(blocks) == 1
    assert blocks[0].bbox1000 == [1, 1, 999, 999]
    assert {asset.asset_type for asset in assets} == {
        "preview",
        "thumbnail",
        "inference_raster",
    }
    inference = [
        asset for asset in assets if asset.asset_type == "inference_raster"
    ]
    assert {asset.metadata_json["dpi"] for asset in inference} == {200, 300}
    assert all(
        asset.metadata_json["colorspace"] == "RGB"
        and asset.metadata_json["page_index0"] == 0
        for asset in inference
    )

    preview = await client.get(f"/v1/pages/{pages[0].id}/preview")
    assert preview.status_code == 200
    assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert preview.headers["cache-control"].startswith("private")
    assert preview.headers["etag"].startswith('"sha256-')

    await _register(
        client,
        email="other-tenant@example.com",
        tenant_name="Other Preview Tenant",
    )
    cross_tenant = await client.get(f"/v1/pages/{pages[0].id}/preview")
    assert cross_tenant.status_code == 404
    login = await client.post(
        "/v1/auth/login",
        json={
            "email": "analysis-owner@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert login.status_code == 200
    assert (await client.get(f"/v1/pages/{pages[0].id}/preview")).status_code == 200


def _scanned_fixture(kind: str) -> tuple[str, str, bytes]:
    if kind == "image":
        payload = io.BytesIO()
        Image.new("RGB", (600, 800), "white").save(
            payload,
            format="PNG",
            dpi=(300, 300),
        )
        return "scan.png", "image/png", payload.getvalue()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    payload = io.BytesIO()
    writer.write(payload)
    return "scan.pdf", "application/pdf", payload.getvalue()


@pytest.mark.parametrize("kind", ["image", "pdf"])
async def test_scanned_input_fake_provider_admits_exact_inference_page_once(
    analysis_api: tuple[httpx.AsyncClient, Any, Settings],
    kind: str,
) -> None:
    client, app, settings = analysis_api
    registration = await _register(
        client,
        email=f"visual-{kind}@example.com",
        tenant_name=f"Visual {kind}",
    )
    tenant_id = uuid.UUID(registration["tenant_id"])
    project_id = await _create_project(client)
    filename, content_type, content = _scanned_fixture(kind)
    document_id = await _upload(
        client,
        project_id=project_id,
        filename=filename,
        content_type=content_type,
        content=content,
    )
    async with app.state.database.sessions.begin() as session:
        tenant = await session.get(Tenant, tenant_id)
        project = await session.get(Project, uuid.UUID(project_id))
        assert tenant is not None and project is not None
        tenant.private_mode = False
        project.output_profile = {"processing_mode": "speed"}
        session.add_all(
            [
                FeatureFlag(
                    tenant_id=tenant_id,
                    key="paddle_fast_route",
                    enabled=True,
                    rollout_percent=100,
                ),
                ModelRegistry(
                    endpoint="paddle_fast_e2e",
                    model_id="paddle_fast_e2e_model",
                    revision="a" * 40,
                    runtime_image_digest="sha256:" + "b" * 64,
                    adapter_version="parser-adapter-1.0.0",
                    policy_version="router-scanned-e2e",
                    benchmark_report="benchmarks/paddle-fast-e2e.json",
                    enabled=True,
                    canary_percent=100,
                ),
            ]
        )
    task_id = await _enqueue(client, document_id)
    assert await _worker(app, settings).run_once(task_id=task_id) is True
    async with app.state.database.sessions() as session:
        page = await session.scalar(
            select(Page).where(Page.document_id == uuid.UUID(document_id))
        )
        task = await session.get(AnalysisTask, task_id)
        assert page is not None, (
            task.status if task is not None else None,
            task.last_error_code if task is not None else None,
        )
        original_page_status = page.status
        inference_assets = list(
            (
                await session.scalars(
                    select(PageAsset).where(
                        PageAsset.page_id == page.id,
                        PageAsset.asset_type == "inference_raster",
                    )
                )
            ).all()
        )
        assert {asset.metadata_json["dpi"] for asset in inference_assets} == {
            200,
            300,
        }

    compiled = await client.post(
        f"/v1/documents/{document_id}/compile",
        json={"route_profile": "parse_fast_v1"},
        headers={"Idempotency-Key": f"scanned-{kind}-fake-provider"},
    )
    assert compiled.status_code == 202, compiled.text
    job_id = uuid.UUID(compiled.json()["job_id"])
    async with app.state.database.sessions() as session:
        await run_compile_job(
            session=session,
            job_id=job_id,
            settings=app.state.settings,
            object_store=app.state.object_store,
        )
    async with app.state.database.sessions.begin() as session:
        job = await session.get(ProcessingJob, job_id)
        invocation = await session.scalar(
            select(GpuProviderInvocation).where(
                GpuProviderInvocation.job_id == job_id
            )
        )
        page = await session.scalar(
            select(Page).where(Page.document_id == uuid.UUID(document_id))
        )
        document = await session.get(Document, uuid.UUID(document_id))
        assert (
            job is not None
            and invocation is not None
            and page is not None
            and document is not None
        ), {
            "job_status": job.status if job is not None else None,
            "job_error": job.error if job is not None else None,
            "requested_options": (
                job.requested_options if job is not None else None
            ),
            "page_route": page.route if page is not None else None,
            "page_status": page.status if page is not None else None,
        }
        page_asset = await session.get(
            PageAsset,
            uuid.UUID(invocation.options["page_asset_id"]),
        )
        assert page_asset is not None
        assert page_asset.asset_type == "inference_raster"
        assert invocation.input_object_key == page_asset.storage_key
        assert invocation.options["dpi"] == 200
        result_id = "sha256:" + "c" * 64
        output_payload = {
            "ok": True,
            "schema_version": "1.0",
            "result_id": result_id,
            "job_id": str(job.id),
            "tenant_id": str(tenant_id),
            "provider": invocation.provider_key,
            "worker_kind": "parser",
            "model_revision": invocation.model_revision,
            "runtime_image_digest": invocation.runtime_image_digest,
            "adapter_version": invocation.adapter_version,
            "input_sha256": f"sha256:{page_asset.sha256}",
            "input_bytes": page_asset.metadata_json["size_bytes"],
            "idempotency_key": invocation.idempotency_key,
            "idempotent_replay": False,
            "blocks": [
                {
                    "block_id": f"blk_scanned_{kind}",
                    "type": "paragraph",
                    "text": f"Verified scanned {kind} output",
                    "origin": "ocr_extracted",
                    "source_refs": [
                        {
                            "document_id": str(document.id),
                            "document_version_id": (
                                f"{document.id}:v{document.active_version}"
                            ),
                            "page_index0": 0,
                            "page_number1": 1,
                            "bbox1000": [10, 20, 900, 200],
                        }
                    ],
                    "confidence": 0.99,
                    "token_confidences": [0.99, 0.98, 0.99],
                    "quality_flags": [],
                }
            ],
            "generated_claims": [],
            "warnings": [],
            "provider_metrics": {"block_count": 1},
            "provider_raw": {},
            "metrics": {"gpu_seconds": 1.0},
            "verification": None,
        }
        output_body = json.dumps(
            output_payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        await app.state.object_store.put_derived(
            invocation.output_object_key,
            output_body,
        )
        result = validate_visual_result(
            output_payload=output_payload,
            expected_job_id=job.id,
            expected_tenant_id=tenant_id,
            expected_document_id=document.id,
            expected_document_version_id=invocation.document_version_id,
            expected_page_index0=0,
            expected_provider=invocation.provider_key,
            expected_model_revision=invocation.model_revision,
            expected_runtime_image_digest=invocation.runtime_image_digest,
            expected_adapter_version=invocation.adapter_version,
            expected_input_sha256=page_asset.sha256,
            expected_input_bytes=page_asset.metadata_json["size_bytes"],
            expected_idempotency_key=invocation.idempotency_key,
            expected_image_asset_id=page_asset.id,
        )
        manifest = {
            "schema_version": "1.0",
            "invocation_id": str(invocation.id),
            "job_id": str(job.id),
            "tenant_id": str(tenant_id),
            "provider": "runpod",
            "provider_job_id": f"fake-{kind}-provider",
            "endpoint_id": invocation.endpoint_id,
            "provider_key": invocation.provider_key,
            "model_revision": invocation.model_revision,
            "runtime_image_digest": invocation.runtime_image_digest,
            "adapter_version": invocation.adapter_version,
            "result_id": result_id,
            "output_object_key": invocation.output_object_key,
            "output_sha256": (
                "sha256:" + hashlib.sha256(output_body).hexdigest()
            ),
            "output_bytes": len(output_body),
            "metrics": output_payload["metrics"],
            "warning_count": 0,
            "warning_sha256": [],
            "raw_provider_response_sha256": "sha256:" + "d" * 64,
            "completion_source": "poll",
            "visual_attestation": visual_attestation(
                result,
                page_id=page.id,
                page_index0=0,
                page_width_px=page_asset.metadata_json["width"],
                page_height_px=page_asset.metadata_json["height"],
                input_size_bytes=page_asset.metadata_json["size_bytes"],
            ),
        }
        invocation.status = "completed"
        invocation.provider_status = "COMPLETED"
        invocation.provider_job_id = f"fake-{kind}-provider"
        invocation.result_manifest = manifest
        invocation.result_manifest_sha256 = hashlib.sha256(
            json.dumps(
                manifest,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        invocation.started_at = utcnow()
        invocation.completed_at = utcnow()

    async with app.state.database.sessions() as session:
        await run_compile_job(
            session=session,
            job_id=job_id,
            settings=app.state.settings,
            object_store=app.state.object_store,
        )
        await run_compile_job(
            session=session,
            job_id=job_id,
            settings=app.state.settings,
            object_store=app.state.object_store,
        )
    async with app.state.database.sessions() as session:
        job = await session.get(ProcessingJob, job_id)
        page = await session.scalar(
            select(Page).where(Page.document_id == uuid.UUID(document_id))
        )
        consumes = int(
            await session.scalar(
                select(func.count(CreditLedger.id)).where(
                    CreditLedger.job_id == job_id,
                    CreditLedger.entry_type == "consume",
                )
            )
            or 0
        )
        assert job is not None and job.status == "completed"
        assert page is not None and page.status == original_page_status
        assert consumes == 1


async def test_sensitive_preview_is_masked_by_default_and_opt_out_is_explicit(
    analysis_api: tuple[httpx.AsyncClient, Any, Settings],
) -> None:
    client, app, settings = analysis_api
    await _register(client)
    project_id = await _create_project(client)
    document_id = await _upload(
        client,
        project_id=project_id,
        filename="sensitive.txt",
        content_type="text/plain",
        content=(
            b"Contact the account owner at pii@example.com. "
            b"Rotate github_pat_12345678901234567890 immediately."
        ),
    )
    task_id = await _enqueue(client, document_id)
    assert await _worker(app, settings).run_once(task_id=task_id) is True

    async with app.state.database.sessions() as session:
        page = await session.scalar(select(Page).where(Page.document_id == uuid.UUID(document_id)))
        block = await session.scalar(
            select(Block).where(Block.document_id == uuid.UUID(document_id))
        )
        secret_review = await session.scalar(
            select(ReviewItem).where(
                ReviewItem.document_id == uuid.UUID(document_id),
                ReviewItem.category == "secret_detected",
            )
        )
    assert page is not None
    assert block is not None
    assert page.preflight_metrics["sensitive_data"] == {
        "has_pii": True,
        "has_secret": True,
        "external_transfer_requires_confirmation": True,
        "counts": {"api_key": 1, "email": 1},
        "detector_limitations": [
            "pattern detection can miss sensitive data",
            "pattern detection can produce false positives",
        ],
    }
    assert "mistral_fallback" not in page.preflight_metrics["ready_routes"]
    assert block.warnings == ["sensitive_api_key_detected", "sensitive_email_detected"]
    assert secret_review is not None
    assert secret_review.evidence["counts"] == {"api_key": 1, "email": 1}
    assert "github_pat_" not in str(secret_review.evidence)
    masked = await client.get(f"/v1/pages/{page.id}/preview")
    assert masked.status_code == 200
    assert masked.headers["x-akc-preview-redaction"] == "masked"
    assert masked.headers["x-akc-masked-regions"] == "1"
    with Image.open(io.BytesIO(masked.content)) as image:
        assert image.convert("RGB").getpixel((image.width // 2, image.height // 2)) == (
            0,
            0,
            0,
        )

    updated = await client.patch(
        "/v1/privacy",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"preview_pii_masking": False},
    )
    assert updated.status_code == 200, updated.text
    unmasked = await client.get(f"/v1/pages/{page.id}/preview")
    assert unmasked.status_code == 200
    assert unmasked.headers["x-akc-preview-redaction"] == "disabled"
    assert unmasked.headers["x-akc-masked-regions"] == "0"
    assert unmasked.headers["etag"] != masked.headers["etag"]
    with Image.open(io.BytesIO(unmasked.content)) as image:
        assert image.convert("RGB").getpixel((image.width // 2, image.height // 2)) == (
            255,
            255,
            255,
        )


async def test_hostile_text_is_dead_lettered_without_partial_rows(
    analysis_api: tuple[httpx.AsyncClient, Any, Settings],
) -> None:
    client, app, settings = analysis_api
    await _register(client)
    project_id = await _create_project(client)
    document_id = await _upload(
        client,
        project_id=project_id,
        filename="hostile.txt",
        content_type="text/plain",
        content=b"valid UTF-8 prefix\x00hidden binary suffix",
    )
    task_id = await _enqueue(client, document_id)
    assert await _worker(app, settings).run_once(task_id=task_id) is True

    async with app.state.database.sessions() as session:
        task = await session.get(AnalysisTask, task_id)
        document = await session.get(Document, uuid.UUID(document_id))
        event = await session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == task_id))
        page_count = await session.scalar(
            select(func.count(Page.id)).where(Page.document_id == uuid.UUID(document_id))
        )
    assert task is not None and task.status == "dead_letter"
    assert task.last_error_code == "BINARY_TEXT_FILE"
    assert task.attempt_count == 1
    assert document is not None and document.status == "PARSE_FAILED"
    assert event is not None
    assert event.last_error == "BINARY_TEXT_FILE"
    assert event.published_at is not None and event.dead_lettered_at is not None
    assert page_count == 0


async def test_timeout_retries_then_dead_letters_without_duplicate_pages(
    analysis_api: tuple[httpx.AsyncClient, Any, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app, settings = analysis_api
    await _register(client)
    project_id = await _create_project(client)
    document_id = await _upload(
        client,
        project_id=project_id,
        filename="timeout.txt",
        content_type="text/plain",
        content=b"bounded retry evidence",
    )
    task_id = await _enqueue(client, document_id)
    worker = _worker(app, settings)

    async def timeout_sandbox(**_: object) -> object:
        raise AnalysisAttemptError("PARSER_TIMEOUT", retryable=True)

    monkeypatch.setattr(worker, "_invoke_sandbox", timeout_sandbox)
    assert await worker.run_once(task_id=task_id) is True
    async with app.state.database.sessions.begin() as session:
        task = await session.get(AnalysisTask, task_id)
        event = await session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == task_id))
        assert task is not None and task.status == "queued"
        assert task.attempt_count == 1
        assert task.last_error_code == "PARSER_TIMEOUT"
        assert event is not None and event.published_at is None
        task.available_at = utcnow()
        event.available_at = utcnow()

    assert await worker.run_once(task_id=task_id) is True
    assert await worker.run_once(task_id=task_id) is False
    async with app.state.database.sessions() as session:
        task = await session.get(AnalysisTask, task_id)
        event = await session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == task_id))
        pages = await session.scalar(
            select(func.count(Page.id)).where(Page.document_id == uuid.UUID(document_id))
        )
    assert task is not None and task.status == "dead_letter"
    assert task.attempt_count == task.max_attempts == 2
    assert task.last_error_code == "PARSER_TIMEOUT"
    assert event is not None
    assert event.published_at is not None and event.dead_lettered_at is not None
    assert pages == 0


async def test_office_analysis_is_explicitly_no_preview(
    analysis_api: tuple[httpx.AsyncClient, Any, Settings],
) -> None:
    client, app, settings = analysis_api
    await _register(client)
    project_id = await _create_project(client)
    buffer = io.BytesIO()
    word = WordDocument()
    word.add_heading("No synthetic Office preview", level=1)
    word.add_paragraph("The extracted content remains available with provenance.")
    word.save(buffer)
    document_id = await _upload(
        client,
        project_id=project_id,
        filename="office.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=buffer.getvalue(),
    )
    task_id = await _enqueue(client, document_id)
    assert await _worker(app, settings).run_once(task_id=task_id) is True

    async with app.state.database.sessions() as session:
        task = await session.get(AnalysisTask, task_id)
        page = await session.scalar(select(Page).where(Page.document_id == uuid.UUID(document_id)))
    assert task is not None and task.status == "completed"
    assert task.preview_count == 0
    assert page is not None
    assert page.thumbnail_key is None
    assert page.preflight_metrics["preview_unavailable_reason"] == "unsupported_document_preview"
    unavailable = await client.get(f"/v1/pages/{page.id}/preview")
    assert unavailable.status_code == 404
    assert unavailable.json()["error"]["details"]["reason"] == "unsupported_document_preview"


def test_production_import_graph_and_worker_resource_guards() -> None:
    statement = analysis_claim_statement(
        now=utcnow(),
        dialect_name="postgresql",
    )
    assert (
        "SKIP LOCKED"
        in str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).upper()
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import akc_api.main; "
                "assert 'akc_api.parsers' not in sys.modules; "
                "assert 'akc_worker_document.sandbox_runner' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr

    with pytest.raises(ValidationError, match="in-process analysis adapter"):
        Settings(env="production", local_analysis_worker_enabled=True)
    with pytest.raises(ValidationError, match="child memory"):
        AnalysisWorkerSettings(
            analysis_child_memory_bytes=128 * 1024 * 1024,
        )
