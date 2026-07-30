from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import AnalysisTask, ProcessingJob, SourceFile
from akc_api.services import run_compile_job
from akc_api.settings import Settings
from akc_security import PdfSecretBinding, PdfSecretError
from akc_worker_document.worker import AnalysisRuntime, AnalysisWorker
from pypdf import PdfWriter
from sqlalchemy import func, select

_TEST_SUPPORT_KEY = "knowledge-api-verification-key"
_TEST_PDF_PASSWORD = "open sesame"  # noqa: S105


@pytest_asyncio.fixture
async def api(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, Settings]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        analysis_max_source_bytes=1024 * 1024,
        analysis_lease_seconds=40,
        analysis_attempt_timeout_seconds=30,
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


async def _register(client: httpx.AsyncClient) -> dict[str, Any]:
    email = f"owner-{uuid.uuid4()}@example.com"
    registered = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": "Knowledge Owner",
            "tenant_name": f"Knowledge {uuid.uuid4()}",
        },
    )
    assert registered.status_code == 201, registered.text
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


async def _project(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/v1/projects",
        headers={"Idempotency-Key": f"project-{uuid.uuid4()}"},
        json={"name": f"Knowledge {uuid.uuid4()}", "description": "API evidence"},
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
        headers={"Idempotency-Key": f"initiate-{uuid.uuid4()}"},
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
        headers={"Idempotency-Key": f"complete-{uuid.uuid4()}"},
        json={"sha256": digest},
    )
    assert completed.status_code == 200, completed.text
    return str(target["document_id"])


def _encrypted_pdf() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt(user_password=_TEST_PDF_PASSWORD, algorithm="AES-256-R5")
    writer.write(output)
    return output.getvalue()


def _analysis_worker(app: Any, settings: Settings) -> AnalysisWorker:
    return AnalysisWorker(
        engine=app.state.database.engine,
        store=app.state.object_store,
        runtime=AnalysisRuntime.from_api_settings(settings),
        pdf_secret_store=app.state.pdf_secret_store,
    )


async def test_encrypted_pdf_password_requeues_without_persisting_secret(
    api: tuple[httpx.AsyncClient, Any, Settings],
) -> None:
    client, app, settings = api
    registration = await _register(client)
    project_id = await _project(client)
    document_id = await _upload(
        client,
        project_id=project_id,
        filename="protected.pdf",
        content_type="application/pdf",
        content=_encrypted_pdf(),
    )
    queued = await client.post(
        f"/v1/documents/{document_id}/analyze",
        headers={"Idempotency-Key": "encrypted-first-analysis"},
    )
    assert queued.status_code == 202, queued.text
    task_id = uuid.UUID(queued.json()["task_id"])
    worker = _analysis_worker(app, settings)
    assert await worker.run_once(task_id=task_id) is True
    async with app.state.database.sessions() as session:
        failed = await session.get(AnalysisTask, task_id)
    assert failed is not None
    assert failed.status == "dead_letter"
    assert failed.last_error_code == "ENCRYPTED_PDF"

    headers = {"Idempotency-Key": "pdf-password-correct"}
    accepted = await client.post(
        f"/v1/documents/{document_id}/password",
        headers=headers,
        json={"password": "open sesame"},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["status"] == "queued"
    assert "open sesame" not in accepted.text
    replay = await client.post(
        f"/v1/documents/{document_id}/password",
        headers=headers,
        json={"password": "open sesame"},
    )
    assert replay.status_code == accepted.status_code
    assert replay.content == accepted.content

    assert await worker.run_once(task_id=task_id) is True
    async with app.state.database.sessions() as session:
        completed = await session.get(AnalysisTask, task_id)
        source = await session.get(SourceFile, completed.source_file_id)
    assert completed is not None and completed.status == "completed"
    assert source is not None
    binding = PdfSecretBinding(
        tenant_id=uuid.UUID(registration["tenant_id"]),
        document_id=uuid.UUID(document_id),
        source_sha256=source.sha256,
    )
    with pytest.raises(PdfSecretError, match="PDF_PASSWORD_REQUIRED"):
        await app.state.pdf_secret_store.acquire(binding)


async def test_batch_idempotency_and_knowledge_provenance_usage_cost_api(
    api: tuple[httpx.AsyncClient, Any, Settings],
) -> None:
    client, app, settings = api
    await _register(client)
    project_id = await _project(client)
    document_ids = [
        await _upload(
            client,
            project_id=project_id,
            filename=f"source-{index}.txt",
            content_type="text/plain",
            content=(f"Evidence document {index}: deterministic batch knowledge. " * 12).encode(),
        )
        for index in (1, 2)
    ]
    worker = _analysis_worker(app, settings)
    for index, document_id in enumerate(document_ids):
        queued = await client.post(
            f"/v1/documents/{document_id}/analyze",
            headers={"Idempotency-Key": f"analyze-{index}"},
        )
        assert queued.status_code == 202, queued.text
        assert await worker.run_once(task_id=uuid.UUID(queued.json()["task_id"])) is True

    payload = {
        "document_ids": document_ids,
        "route_profile": "parse_balanced_v1",
        "output_profiles": ["portable_markdown_v1", "rag_jsonl_v1"],
        "max_total_credits": "20",
    }
    headers = {"Idempotency-Key": "batch-two-documents"}
    created = await client.post("/v1/batches/compile", headers=headers, json=payload)
    assert created.status_code == 202, created.text
    body = created.json()
    assert len(body["jobs"]) == 2
    replay = await client.post("/v1/batches/compile", headers=headers, json=payload)
    assert replay.status_code == 202
    assert replay.content == created.content

    conflict = await client.post(
        "/v1/batches/compile",
        headers=headers,
        json={**payload, "document_ids": document_ids[:1]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    async with app.state.database.sessions() as session:
        count = await session.scalar(
            select(func.count(ProcessingJob.id)).where(
                ProcessingJob.id.in_([uuid.UUID(job["job_id"]) for job in body["jobs"]])
            )
        )
    assert count == 2

    for job in body["jobs"]:
        async with app.state.database.sessions() as session:
            await run_compile_job(
                session=session,
                job_id=uuid.UUID(job["job_id"]),
                settings=settings,
            )

    batch = await client.get(f"/v1/batches/{body['batch_id']}")
    assert batch.status_code == 200, batch.text
    async with app.state.database.sessions() as session:
        job_errors = list(
            (
                await session.execute(
                    select(ProcessingJob.id, ProcessingJob.status, ProcessingJob.error).where(
                        ProcessingJob.id.in_([uuid.UUID(job["job_id"]) for job in body["jobs"]])
                    )
                )
            ).all()
        )
    assert batch.json()["status"] == "completed", job_errors

    schemas = await client.get("/v1/schema-profiles")
    assert schemas.status_code == 200
    profile_ids = {item["id"] for item in schemas.json()["profiles"]}
    assert {
        "cir",
        "akmp",
        "knowledge_standard_v1",
        "portable_markdown_v1",
    } <= profile_ids

    provenance = await client.get(f"/v1/documents/{document_ids[0]}/provenance")
    assert provenance.status_code == 200, provenance.text
    graph = provenance.json()
    assert graph["source"]["sha256"]
    assert graph["blocks"]
    assert graph["knowledge_notes"]
    assert graph["source_coverage_ratio"] == 1
    block_ids = {item["block_id"] for item in graph["blocks"]}
    assert set(graph["knowledge_notes"][0]["evidence_block_ids"]) <= block_ids
    assert "source_text" not in provenance.text

    knowledge = await client.get(f"/v1/projects/{project_id}/knowledge")
    assert knowledge.status_code == 200
    assert len(knowledge.json()) == 2

    usage = await client.get("/v1/usage")
    assert usage.status_code == 200, usage.text
    assert Decimal(usage.json()["totals_by_entry_type"]["consume"]) > 0
    assert usage.json()["entries"]

    costs = await client.get("/v1/costs")
    assert costs.status_code == 200, costs.text
    assert costs.json()["completed_jobs"] == 2
    assert Decimal(costs.json()["total_credits"]) > 0
