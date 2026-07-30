"""Executable API vertical-slice and tenant-boundary evidence."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import (
    AuditEvent,
    Block,
    BlockRevision,
    CreditAccount,
    CreditLedger,
    Document,
    FeatureFlag,
    ModelRegistry,
    OutboxEvent,
    Page,
    PageAttempt,
    ProcessingJob,
    ReviewItem,
    SourceFile,
    Tenant,
    WebhookEndpoint,
    utcnow,
)
from akc_api.services import credit_entry
from akc_api.settings import Settings
from akc_security import CdrRequest, CdrResult, CdrStatus
from cryptography.fernet import Fernet
from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import func, select

_TEST_SUPPORT_KEY = "api-integration-verification-key-2026"
_EXPORT_MANIFEST_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "contracts"
        / "schemas"
        / "export-manifest.schema.json"
    ).read_text(encoding="utf-8")
)


@pytest_asyncio.fixture
async def api(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=True,
        local_analysis_worker_enabled=True,
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
            yield client, app


async def _register(
    client: httpx.AsyncClient,
    *,
    email: str = "owner@example.com",
    tenant_name: str = "Evidence Workspace",
) -> dict[str, Any]:
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": "Evidence Owner",
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
    assert verified.json()["email_verified"] is True
    return verified.json()


async def test_metrics_use_route_templates_without_customer_identifiers(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _ = api
    concrete_id = str(uuid.uuid4())
    response = await client.get(
        f"/v1/jobs/{concrete_id}",
        params={"email": "customer@example.com"},
    )
    assert response.status_code == 401

    metrics = await client.get("/metrics")
    assert metrics.status_code == 200
    assert 'route="/v1/jobs/{job_id}"' in metrics.text
    assert concrete_id not in metrics.text
    assert "customer@example.com" not in metrics.text


async def test_webhook_create_audits_real_id_and_enforces_tenant_quota(
    api: tuple[httpx.AsyncClient, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app = api
    registration = await _register(client)
    app.state.settings.webhook_delivery_enabled = True
    app.state.settings.webhook_encryption_key = Fernet.generate_key().decode("ascii")
    app.state.settings.webhook_allowed_hosts = "hooks.example.com"
    app.state.settings.webhook_max_endpoints_per_tenant = 1

    async def fake_validate_webhook_url(
        url: str,
        *,
        allowed_hosts: tuple[str, ...],
    ) -> SimpleNamespace:
        assert allowed_hosts == ("hooks.example.com",)
        return SimpleNamespace(normalized_url=url)

    monkeypatch.setattr(
        "akc_api.main.validate_webhook_url",
        fake_validate_webhook_url,
    )
    created = await client.post(
        "/v1/webhooks",
        json={
            "url": "https://hooks.example.com/events",
            "event_types": ["job.completed.v1"],
        },
    )
    assert created.status_code == 201, created.text
    created_id = uuid.UUID(created.json()["id"])

    async with app.state.database.sessions() as session:
        endpoint = await session.get(WebhookEndpoint, created_id)
        audit_event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == uuid.UUID(registration["tenant_id"]),
                AuditEvent.action == "webhook.created",
            )
        )
    assert endpoint is not None
    assert audit_event is not None
    assert audit_event.target_id == str(created_id)

    rejected = await client.post(
        "/v1/webhooks",
        json={
            "url": "https://hooks.example.com/second",
            "event_types": ["job.failed.v1"],
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "WEBHOOK_ENDPOINT_QUOTA_EXCEEDED"

    async with app.state.database.sessions() as session:
        endpoints = list(await session.scalars(select(WebhookEndpoint)))
    assert [row.id for row in endpoints] == [created_id]


async def test_cdr_preserves_original_and_binds_a_separate_parser_derivative(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = api
    registration = await _register(client, email="cdr-owner@example.com")
    original = _native_pdf(1)
    sanitized = _native_pdf(1, metadata_marker="synthetic-cdr-derivative")
    sanitized_digest = hashlib.sha256(sanitized).hexdigest()

    class SyntheticCdr:
        async def sanitize(self, request: CdrRequest) -> CdrResult:
            assert request.payload == original
            return CdrResult(
                status=CdrStatus.SANITIZED,
                provider="synthetic-contract-adapter",
                revision="ruleset-2026-07-30",
                sanitized_payload=sanitized,
                sanitized_sha256=sanitized_digest,
            )

        async def ready(self) -> bool:
            return True

        async def aclose(self) -> None:
            return None

    app.state.settings.cdr_enabled = True
    app.state.cdr_adapter = SyntheticCdr()
    project = await client.post("/v1/projects", json={"name": "CDR evidence"})
    assert project.status_code == 201
    digest = hashlib.sha256(original).hexdigest()
    initiated = await client.post(
        "/v1/uploads/initiate",
        json={
            "project_id": project.json()["id"],
            "filename": "untrusted.pdf",
            "size": len(original),
            "content_type": "application/pdf",
            "sha256": digest,
        },
    )
    assert initiated.status_code == 201, initiated.text
    target = initiated.json()
    uploaded = await client.put(
        target["upload_url"],
        content=original,
        headers=target["headers"],
    )
    assert uploaded.status_code == 204, uploaded.text
    completed = await client.post(
        f"/v1/uploads/{target['upload_id']}/complete",
        json={"sha256": digest},
    )
    assert completed.status_code == 200, completed.text

    async with app.state.database.sessions() as session:
        source = await session.get(
            SourceFile,
            uuid.UUID(completed.json()["source_file_id"]),
        )
    assert source is not None
    assert source.tenant_id == uuid.UUID(registration["tenant_id"])
    assert source.sha256 == digest
    assert source.cdr_status == "sanitized"
    assert source.sanitized_sha256 == sanitized_digest
    assert source.storage_key != source.sanitized_storage_key
    assert await app.state.object_store.read_source(source.storage_key) == original
    assert source.sanitized_storage_key is not None
    assert await app.state.object_store.read_derived(source.sanitized_storage_key) == sanitized
    analyzed = await client.post(f"/v1/documents/{target['document_id']}/analyze")
    assert analyzed.status_code == 202, analyzed.text
    analysis: dict[str, Any] = {}
    for _attempt in range(1_200):
        analysis = (await client.get(f"/v1/documents/{target['document_id']}/analysis")).json()
        if analysis["status"] not in {"queued", "running"}:
            break
        await asyncio.sleep(0.05)
    assert analysis["status"] == "completed", (
        analysis["status"],
        analysis.get("error_code"),
    )
    assert analysis["page_count"] == 1


async def _upload_text(
    client: httpx.AsyncClient,
    project_id: str,
    *,
    filename: str = "research.v2.txt",
) -> tuple[str, bytes]:
    content = (
        b"# Evidence-first compilation\n\n"
        b"Every generated knowledge claim preserves a source block reference.\n"
        b"The compiler uses deterministic native extraction for trusted UTF-8 text.\n"
    )
    digest = hashlib.sha256(content).hexdigest()
    initiated = await client.post(
        "/v1/uploads/initiate",
        json={
            "project_id": project_id,
            "filename": filename,
            "size": len(content),
            "content_type": "text/plain",
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
    # Finalization is idempotent and never creates a second source object.
    finalized_again = await client.post(
        f"/v1/uploads/{target['upload_id']}/complete",
        json={"sha256": digest},
    )
    assert finalized_again.status_code == 200
    assert finalized_again.json()["source_file_id"] == completed.json()["source_file_id"]
    return target["document_id"], content


async def _seed_dispatch_dead_letter(
    app: Any,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    status: str = "failed",
) -> tuple[uuid.UUID, uuid.UUID]:
    async with app.state.database.sessions.begin() as session:
        document = Document(
            tenant_id=tenant_id,
            project_id=project_id,
            title="Dispatch replay evidence",
            document_type="text",
            status="COMPLETED",
        )
        session.add(document)
        await session.flush()
        job = ProcessingJob(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=document.id,
            job_type="compile",
            status=status,
            requested_options={"retry_count": 0},
            progress={"done": 0, "total": 1},
            cost_estimate={"reserved": "1", "expected": "1"},
            error=(
                {"code": "DISPATCH_ATTEMPTS_EXHAUSTED", "retryable": True}
                if status == "failed"
                else None
            ),
            completed_at=utcnow() if status == "failed" else None,
        )
        session.add(job)
        await session.flush()
        event = OutboxEvent(
            tenant_id=tenant_id,
            aggregate_type="job",
            aggregate_id=job.id,
            event_type="job.dispatch.requested.v1",
            payload={"job_id": str(job.id), "tenant_id": str(tenant_id)},
            attempts=5,
            last_error="dispatch_adapter_error:RuntimeError",
            published_at=utcnow(),
            dead_lettered_at=utcnow(),
        )
        session.add(event)
        await session.flush()
        return job.id, event.id


def _native_pdf(page_count: int, *, metadata_marker: str | None = None) -> bytes:
    writer = PdfWriter()
    if metadata_marker is not None:
        writer.add_metadata({"/AKCCDR": metadata_marker})
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for page_number in range(1, page_count + 1):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        sentence = (
            f"Evidence page {page_number}. "
            "This native PDF page preserves deterministic source provenance and "
            "contains enough trusted text for native routing. "
        )
        text = (sentence * 8).replace("(", r"\(").replace(")", r"\)")
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 10 Tf 36 740 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
    payload = io.BytesIO()
    writer.write(payload)
    return payload.getvalue()


@pytest.mark.integration
async def test_dispatch_dlq_replay_creates_new_job_and_preserves_evidence(api) -> None:
    client, app = api
    registration = await _register(
        client,
        email="dispatch-replay@example.com",
        tenant_name="Dispatch Replay",
    )
    tenant_id = uuid.UUID(registration["tenant_id"])
    project_response = await client.post(
        "/v1/projects",
        json={"name": "Dispatch replay project"},
    )
    assert project_response.status_code == 201
    project_id = uuid.UUID(project_response.json()["id"])
    original_job_id, original_event_id = await _seed_dispatch_dead_letter(
        app,
        tenant_id=tenant_id,
        project_id=project_id,
    )

    listed = await client.get("/v1/admin/dispatch-dlq")
    assert listed.status_code == 200
    assert listed.json()[0]["original_event_id"] == str(original_event_id)
    assert listed.json()[0]["original_job_id"] == str(original_job_id)

    missing_key = await client.post(f"/v1/admin/dispatch-dlq/{original_event_id}/replay")
    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    replayed = await client.post(
        f"/v1/admin/dispatch-dlq/{original_event_id}/replay",
        headers={"Idempotency-Key": "dispatch-replay-once"},
    )
    assert replayed.status_code == 202, replayed.text
    replay = replayed.json()
    assert replay["original_event_id"] == str(original_event_id)
    assert replay["new_job_id"] != str(original_job_id)

    duplicate = await client.post(
        f"/v1/admin/dispatch-dlq/{original_event_id}/replay",
        headers={"Idempotency-Key": "dispatch-replay-once"},
    )
    assert duplicate.status_code == 202
    assert duplicate.json() == replay
    rejected_second_replay = await client.post(
        f"/v1/admin/dispatch-dlq/{original_event_id}/replay",
        headers={"Idempotency-Key": "different-replay-key"},
    )
    assert rejected_second_replay.status_code == 409
    assert rejected_second_replay.json()["error"]["code"] == "DISPATCH_DEAD_LETTER_ALREADY_REPLAYED"

    async with app.state.database.sessions() as session:
        original_event = await session.get(OutboxEvent, original_event_id)
        new_job = await session.get(
            ProcessingJob,
            uuid.UUID(replay["new_job_id"]),
        )
        new_event = await session.get(
            OutboxEvent,
            uuid.UUID(replay["new_event_id"]),
        )
        account = await session.get(CreditAccount, tenant_id)
        reserve_entry = await session.scalar(
            select(CreditLedger).where(
                CreditLedger.job_id == uuid.UUID(replay["new_job_id"]),
                CreditLedger.entry_type == "reserve",
            )
        )
        replay_audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action == "dispatch_dlq.replayed",
            )
        )
    assert original_event is not None
    assert original_event.dead_lettered_at is not None
    assert original_event.published_at is not None
    assert original_event.attempts == 5
    assert new_job is not None and new_job.status == "queued"
    assert new_job.requested_options["replay_of_job_id"] == str(original_job_id)
    assert new_event is not None and new_event.published_at is None
    assert new_event.dead_lettered_at is None
    assert new_event.aggregate_id == new_job.id
    assert account is not None and Decimal(account.reserved) == Decimal("1")
    assert reserve_entry is not None
    assert replay_audit is not None
    assert replay_audit.target_id == str(new_job.id)


@pytest.mark.integration
async def test_dispatch_dlq_replay_fails_closed_for_nonterminal_and_no_credit(api) -> None:
    client, app = api
    registration = await _register(
        client,
        email="dispatch-fail-closed@example.com",
        tenant_name="Dispatch Fail Closed",
    )
    tenant_id = uuid.UUID(registration["tenant_id"])
    project_response = await client.post(
        "/v1/projects",
        json={"name": "Dispatch fail-closed project"},
    )
    project_id = uuid.UUID(project_response.json()["id"])
    _, nonterminal_event_id = await _seed_dispatch_dead_letter(
        app,
        tenant_id=tenant_id,
        project_id=project_id,
        status="queued",
    )
    nonterminal = await client.post(
        f"/v1/admin/dispatch-dlq/{nonterminal_event_id}/replay",
        headers={"Idempotency-Key": "nonterminal-replay"},
    )
    assert nonterminal.status_code == 409
    assert nonterminal.json()["error"]["code"] == "DISPATCH_ORIGINAL_JOB_NOT_TERMINAL"

    _, insufficient_event_id = await _seed_dispatch_dead_letter(
        app,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    async with app.state.database.sessions.begin() as session:
        account = await session.get(CreditAccount, tenant_id)
        assert account is not None
        account.balance = Decimal("0")
        account.reserved = Decimal("0")
    insufficient = await client.post(
        f"/v1/admin/dispatch-dlq/{insufficient_event_id}/replay",
        headers={"Idempotency-Key": "insufficient-credit-replay"},
    )
    assert insufficient.status_code == 402
    assert insufficient.json()["error"]["code"] == "INSUFFICIENT_CREDITS"
    async with app.state.database.sessions() as session:
        pending_replay = await session.scalar(
            select(ProcessingJob.id).where(
                ProcessingJob.tenant_id == tenant_id,
                ProcessingJob.requested_options["replay_of_event_id"].as_string()
                == str(insufficient_event_id),
            )
        )
    assert pending_replay is None


@pytest.mark.integration
async def test_dispatch_dlq_fallback_and_close_are_preview_bound_and_audited(api) -> None:
    client, app = api
    registration = await _register(
        client,
        email="dispatch-disposition@example.com",
        tenant_name="Dispatch Disposition",
    )
    tenant_id = uuid.UUID(registration["tenant_id"])
    project = await client.post(
        "/v1/projects",
        json={"name": "Dispatch disposition project"},
    )
    project_id = uuid.UUID(project.json()["id"])
    fallback_job_id, fallback_event_id = await _seed_dispatch_dead_letter(
        app,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    _, close_event_id = await _seed_dispatch_dead_letter(
        app,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    listed = (await client.get("/v1/admin/dispatch-dlq")).json()
    by_id = {row["original_event_id"]: row for row in listed}

    stale = await client.post(
        f"/v1/admin/dispatch-dlq/{fallback_event_id}/fallback",
        headers={"Idempotency-Key": "fallback-stale"},
        json={
            "expected_state_sha256": "0" * 64,
            "fallback_route_profile": "parse_private_v1",
            "reason_code": "provider_unavailable",
            "note": "Provider unavailable; use native-only routing.",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "DISPATCH_DEAD_LETTER_STATE_CHANGED"

    fallback = await client.post(
        f"/v1/admin/dispatch-dlq/{fallback_event_id}/fallback",
        headers={"Idempotency-Key": "fallback-current"},
        json={
            "expected_state_sha256": by_id[str(fallback_event_id)]["state_sha256"],
            "fallback_route_profile": "parse_private_v1",
            "reason_code": "provider_unavailable",
            "note": "Provider unavailable; use native-only routing.",
        },
    )
    assert fallback.status_code == 202, fallback.text
    assert fallback.json()["fallback_route_profile"] == "parse_private_v1"

    closed = await client.post(
        f"/v1/admin/dispatch-dlq/{close_event_id}/close",
        headers={"Idempotency-Key": "close-current"},
        json={
            "expected_state_sha256": by_id[str(close_event_id)]["state_sha256"],
            "reason_code": "manual_resolution",
            "note": "The operator resolved the upstream condition manually.",
        },
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["disposition"] == "closed"

    async with app.state.database.sessions() as session:
        fallback_event = await session.get(OutboxEvent, fallback_event_id)
        new_job = await session.get(
            ProcessingJob,
            uuid.UUID(fallback.json()["new_job_id"]),
        )
        close_event = await session.get(OutboxEvent, close_event_id)
        audits = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.action.in_(
                            ["dispatch_dlq.fallback_created", "dispatch_dlq.closed"]
                        ),
                    )
                )
            ).all()
        )
    assert fallback_event is not None
    assert fallback_event.payload["operator_disposition"] == "fallback"
    assert new_job is not None
    assert new_job.id != fallback_job_id
    assert new_job.requested_options["route_profile"] == "parse_private_v1"
    assert close_event is not None
    assert close_event.payload["operator_disposition"] == "closed"
    assert len(audits) == 2


@pytest.mark.integration
async def test_native_vertical_slice_export_edit_and_verified_purge(api) -> None:
    client, app = api
    unauthenticated = await client.get("/v1/projects")
    assert unauthenticated.status_code == 401
    registration = await _register(client)
    async with app.state.database.sessions.begin() as session:
        for key in ("ontology_export", "existing_vault_merge"):
            session.add(
                FeatureFlag(
                    tenant_id=uuid.UUID(registration["tenant_id"]),
                    key=key,
                    enabled=True,
                    rollout_percent=0,
                )
            )
    project_response = await client.post(
        "/v1/projects",
        json={
            "name": "Provenance Research",
            "description": "An executable Gate 1 evidence project.",
        },
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    document_id, _ = await _upload_text(client, project_id)

    analyzed = await client.post(f"/v1/documents/{document_id}/analyze")
    assert analyzed.status_code == 202, analyzed.text
    analysis = (await client.get(f"/v1/documents/{document_id}/analysis")).json()
    assert analysis["task_id"] == analyzed.json()["task_id"]
    assert analysis["document_id"] == document_id
    assert analysis["error_code"] is None, analysis["error_code"]
    assert analysis["status"] == "completed", analysis
    assert analysis["page_count"] == 1
    assert analysis["block_count"] == 1
    assert analysis["preview_count"] == 1
    estimate = (await client.get(f"/v1/documents/{document_id}/estimate")).json()
    assert estimate["total_pages"] == 1
    assert estimate["native_pages"] == 1
    assert estimate["third_party_model_api"] is False
    assert float(estimate["credit_max"]) >= float(estimate["credit_min"]) > 0

    compile_payload = {
        "route_profile": "parse_balanced_v1",
        "max_credits": 10,
        "external_processing_consent": False,
        "output_profiles": ["portable", "obsidian", "rag", "jsonld"],
    }
    first = await client.post(
        f"/v1/documents/{document_id}/compile",
        json=compile_payload,
        headers={"Idempotency-Key": "native-evidence-job"},
    )
    assert first.status_code == 202, first.text
    job_id = first.json()["job_id"]
    duplicate = await client.post(
        f"/v1/documents/{document_id}/compile",
        json=compile_payload,
        headers={"Idempotency-Key": "native-evidence-job"},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["job_id"] == job_id
    conflict = await client.post(
        f"/v1/documents/{document_id}/compile",
        json={**compile_payload, "route_profile": "parse_fast_v1"},
        headers={"Idempotency-Key": "native-evidence-job"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    async with app.state.database.sessions() as session:
        persisted_job = await session.get(ProcessingJob, uuid.UUID(job_id))
        dispatch_event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == uuid.UUID(job_id),
                OutboxEvent.event_type == "job.dispatch.requested.v1",
            )
        )
    assert persisted_job is not None
    assert persisted_job.requested_options["idempotency_key"] == "native-evidence-job"
    assert dispatch_event is not None
    assert dispatch_event.payload["idempotency_key"] == "native-evidence-job"

    snapshot = (await client.get(f"/v1/jobs/{job_id}")).json()
    assert snapshot["status"] == "completed", snapshot.get("error")
    assert snapshot["summary"]["completed_pages"] == 1
    assert snapshot["summary"]["knowledge_notes"] == 1
    assert snapshot["summary"]["route_totals"] == {"native": 1}
    assert snapshot["summary"]["block_type_totals"] == {"paragraph": 1}
    assert snapshot["summary"]["removed_header_footer"] == {"header": 0, "footer": 0}
    assert snapshot["summary"]["review_blocks"] == 0
    assert snapshot["summary"]["gpu_seconds"] is None
    assert snapshot["summary"]["queue_position"] is None
    events = (await client.get(f"/v1/jobs/{job_id}/events/replay")).json()
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert events[-1]["event_type"] == "job.completed.v1"
    assert "page_id" not in events[-1]
    assert any(event["event_type"] == "credit.released.v1" for event in events)

    blocks = (await client.get(f"/v1/documents/{document_id}/blocks")).json()
    assert len(blocks) == 1
    block_id = blocks[0]["id"]
    base_markdown = blocks[0]["markdown"] or ""
    stale = await client.patch(
        f"/v1/blocks/{block_id}",
        json={"markdown": "stale", "user_locked": True},
        headers={"If-Match": '"revision-0"'},
    )
    assert stale.status_code == 412
    edited = await client.patch(
        f"/v1/blocks/{block_id}",
        json={"markdown": "User-verified source text.", "user_locked": True},
        headers={"If-Match": '"revision-1"'},
    )
    assert edited.status_code == 200, edited.text
    assert edited.headers["etag"] == '"revision-2"'
    assert edited.json()["origin"] == "user_edited"
    conflict = await client.post(
        f"/v1/blocks/{block_id}/model-merge",
        headers={
            "If-Match": '"revision-2"',
            "Idempotency-Key": "model-merge-conflict",
        },
        json={
            "base_revision": 1,
            "new_model_markdown": "Model-rewritten source text.",
            "model_revision": "model-rerun-test-v2",
            "apply_non_conflicting": True,
        },
    )
    assert conflict.status_code == 200, conflict.text
    assert conflict.json() == {
        "block_id": block_id,
        "status": "conflict",
        "base_revision": 1,
        "current_revision": 2,
        "applied": False,
        "user_locked": True,
        "base": base_markdown,
        "user": "User-verified source text.",
        "new_model": "Model-rewritten source text.",
        "merged": None,
        "conflict_count": 1,
        "etag": '"revision-2"',
    }
    newline_base = await client.patch(
        f"/v1/blocks/{block_id}",
        headers={
            "If-Match": '"revision-2"',
            "Idempotency-Key": "model-merge-newline-base",
        },
        json={
            "markdown": "User-verified source text.\n",
            "user_locked": True,
        },
    )
    assert newline_base.status_code == 200, newline_base.text
    user_appendix = await client.patch(
        f"/v1/blocks/{block_id}",
        headers={
            "If-Match": '"revision-3"',
            "Idempotency-Key": "model-merge-user-appendix",
        },
        json={
            "markdown": "User-verified source text.\nUser appendix.\n",
            "user_locked": True,
        },
    )
    assert user_appendix.status_code == 200, user_appendix.text
    auto_merged = await client.post(
        f"/v1/blocks/{block_id}/model-merge",
        headers={
            "If-Match": '"revision-4"',
            "Idempotency-Key": "model-merge-auto",
        },
        json={
            "base_revision": 3,
            "new_model_markdown": "Model heading.\nUser-verified source text.\n",
            "model_revision": "model-rerun-test-v3",
            "apply_non_conflicting": True,
        },
    )
    assert auto_merged.status_code == 200, auto_merged.text
    assert auto_merged.json()["status"] == "auto_merged"
    assert auto_merged.json()["applied"] is True
    assert auto_merged.json()["current_revision"] == 5
    assert (
        auto_merged.json()["merged"]
        == "Model heading.\nUser-verified source text.\nUser appendix.\n"
    )
    assert auto_merged.headers["etag"] == '"revision-5"'

    exported = await client.post(
        f"/v1/jobs/{job_id}/exports",
        json={"profiles": ["portable", "obsidian", "rag", "jsonld"], "options": {}},
    )
    assert exported.status_code == 201, exported.text
    export_info = exported.json()
    downloaded = await client.get(export_info["download_url"])
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == export_info["sha256"]
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "rag/chunks.jsonl" in names
        assert "rag/documents.jsonl" in names
        assert "knowledge/graph.jsonld" in names
        assert "linked-data/context-v1.jsonld" in names
        assert "linked-data/knowledge-note.shacl.ttl" in names
        assert "knowledge/entities.jsonl" in names
        assert "knowledge/relations.jsonl" in names
        assert f"source-map/{document_id}.json" in names
        assert f"source-map/{document_id}.raw.json" in names
        assert f"quality/{document_id}.json" in names
        assert f"quality/{document_id}.html" in names
        assert any(name.startswith("obsidian/10-Documents/") for name in names)
        assert any(name.startswith("10-Documents/") for name in names)
        assert any(name.startswith("10-Documents/") and name.endswith(".raw.md") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        Draft202012Validator(
            _EXPORT_MANIFEST_SCHEMA,
            format_checker=FormatChecker(),
        ).validate(manifest)
        assert manifest["schemaVersion"] == "export-manifest-1.0.0"
        assert manifest["profile"] == "bundle"
        assert manifest["documentId"] == document_id
        for item in manifest["files"]:
            payload = archive.read(item["path"])
            assert len(payload) == item["sizeBytes"]
            assert f"sha256:{hashlib.sha256(payload).hexdigest()}" == item["sha256"]

    existing_vault_buffer = io.BytesIO()
    with zipfile.ZipFile(existing_vault_buffer, "w") as existing_vault:
        existing_vault.writestr(
            "00-Home/Home.md",
            "# User-owned Home\n\nThis content must never be overwritten by a preview.\n",
        )
    merge_preview = await client.post(
        f"/v1/exports/{export_info['export_id']}/vault-merge-preview",
        data={"policy": "error"},
        files={
            "existing_vault": (
                "existing-vault.zip",
                existing_vault_buffer.getvalue(),
                "application/zip",
            )
        },
    )
    assert merge_preview.status_code == 200, merge_preview.text
    merge_plan = merge_preview.json()
    assert merge_plan["schema_version"] == "vault-merge-preview-1.0.0"
    assert merge_plan["safe_to_apply"] is False
    assert merge_plan["conflict_count"] == 1
    assert merge_plan["unresolved_conflict_count"] == 1
    assert merge_plan["conflicts"][0]["existing_path"] == "00-Home/Home.md"
    assert merge_plan["conflicts"][0]["resolution"] is None
    assert len(merge_plan["plan_sha256"]) == 64
    # Preview is read-only: the generated package remains byte-identical.
    downloaded_again = await client.get(export_info["download_url"])
    assert downloaded_again.content == downloaded.content

    credits = (await client.get("/v1/credits")).json()
    assert float(credits["reserved"]) == 0
    assert float(credits["available"]) > 0
    dashboard = (await client.get("/v1/dashboard")).json()
    assert dashboard["active_project_count"] == 1
    assert dashboard["provenance_coverage"] == 1.0

    accepted = await client.delete(f"/v1/documents/{document_id}")
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["target_type"] == "document"
    assert len(accepted.json()["manifest_hash"]) == 64
    deletion = await client.get(accepted.json()["status_url"])
    assert deletion.status_code == 200, deletion.text
    assert deletion.json()["state"] == "purged"
    assert deletion.json()["receipt"]["manifest_hash"] == accepted.json()["manifest_hash"]
    assert (await client.get(f"/v1/documents/{document_id}")).status_code == 404
    assert (await client.get(export_info["download_url"])).status_code == 404
    remaining_objects = [
        path for path in app.state.settings.object_root.rglob("*") if path.is_file()
    ]
    assert remaining_objects == []


@pytest.mark.integration
@pytest.mark.slow
async def test_hundred_page_native_pdf_gate_one_journey(api) -> None:
    client, app = api
    registration = await _register(
        client,
        email="gate-one@example.com",
        tenant_name="Gate One",
    )
    async with app.state.database.sessions() as session:
        tenant = await session.get(Tenant, uuid.UUID(registration["tenant_id"]))
        assert tenant is not None
        tenant.plan_code = "pro"
        await credit_entry(
            session,
            tenant_id=uuid.UUID(registration["tenant_id"]),
            operation_key="gate-one-evidence-credit",
            entry_type="grant",
            credits=Decimal("100"),
            metadata={"source": "bounded_test_fixture"},
        )
        await session.commit()
    project = await client.post("/v1/projects", json={"name": "100-page Gate One"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    pdf = _native_pdf(100)
    digest = hashlib.sha256(pdf).hexdigest()
    initiated = await client.post(
        "/v1/uploads/initiate",
        json={
            "project_id": project_id,
            "filename": "gate-one-100-pages.pdf",
            "size": len(pdf),
            "content_type": "application/pdf",
            "sha256": digest,
        },
    )
    assert initiated.status_code == 201, initiated.text
    upload = initiated.json()
    assert (
        await client.put(
            upload["upload_url"],
            content=pdf,
            headers=upload["headers"],
        )
    ).status_code == 204
    finalized = await client.post(
        f"/v1/uploads/{upload['upload_id']}/complete",
        json={"sha256": digest},
    )
    assert finalized.status_code == 200, finalized.text

    document_id = upload["document_id"]
    analyzed = await client.post(f"/v1/documents/{document_id}/analyze")
    assert analyzed.status_code == 202, analyzed.text
    analysis = (await client.get(f"/v1/documents/{document_id}/analysis")).json()
    assert analysis["status"] == "completed"
    assert analysis["page_count"] == 100
    assert analysis["block_count"] == 100
    estimate = (await client.get(f"/v1/documents/{document_id}/estimate")).json()
    assert estimate["total_pages"] == 100
    assert estimate["native_pages"] == 100
    assert estimate["visual_pages"] == 0

    compiled = await client.post(
        f"/v1/documents/{document_id}/compile",
        json={
            "max_credits": 100,
            "external_processing_consent": False,
            "output_profiles": ["portable", "rag"],
        },
        headers={"Idempotency-Key": "gate-one-100-page-native"},
    )
    assert compiled.status_code == 202, compiled.text
    job_id = compiled.json()["job_id"]
    snapshot = (await client.get(f"/v1/jobs/{job_id}")).json()
    async with app.state.database.sessions() as session:
        persisted = await session.get(ProcessingJob, uuid.UUID(job_id))
    assert snapshot["status"] == "completed", persisted.error if persisted is not None else None
    assert snapshot["summary"]["completed_pages"] == 100
    assert snapshot["summary"]["knowledge_notes"] == 1
    events = (await client.get(f"/v1/jobs/{job_id}/events/replay")).json()
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert events[-1]["event_type"] == "job.completed.v1"

    exported = await client.post(
        f"/v1/jobs/{job_id}/exports",
        json={"profiles": ["portable", "rag"], "options": {}},
    )
    assert exported.status_code == 201, exported.text
    archive_response = await client.get(exported.json()["download_url"])
    assert archive_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "rag/chunks.jsonl" in names
        assert any(name.startswith("10-Documents/") for name in names)
        assert any(name.startswith("10-Documents/") and name.endswith(".raw.md") for name in names)
        assert f"source-map/{document_id}.raw.json" in names
        assert f"quality/{document_id}.json" in names
        assert f"quality/{document_id}.html" in names
        source_map = json.loads(archive.read(f"source-map/{document_id}.json"))
        assert len(source_map["entries"]) == 100
        assert {entry["sourceRefs"][0]["pageNumber1"] for entry in source_map["entries"]} == set(
            range(1, 101)
        )

    accepted = await client.delete(f"/v1/documents/{document_id}")
    assert accepted.status_code == 202, accepted.text
    deletion = await client.get(accepted.json()["status_url"])
    assert deletion.status_code == 200, deletion.text
    assert deletion.json()["state"] == "purged"
    assert deletion.json()["receipt"]["completed_at"] is not None
    assert not [path for path in app.state.settings.object_root.rglob("*") if path.is_file()]


@pytest.mark.integration
async def test_tenant_isolation_api_key_scope_csrf_and_url_fail_closed(api) -> None:
    owner, app = api
    first_session = await _register(owner, email="first@example.com", tenant_name="First")
    project = await owner.post("/v1/projects", json={"name": "Tenant One Only"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    key_response = await owner.post(
        "/v1/api-keys",
        json={"name": "read-only automation", "scopes": ["api:read"]},
    )
    assert key_response.status_code == 201
    raw_key = key_response.json()["key"]
    empty_scope = await owner.post(
        "/v1/api-keys",
        json={"name": "invalid empty scope", "scopes": []},
    )
    assert empty_scope.status_code == 422
    events_key_response = await owner.post(
        "/v1/api-keys",
        json={"name": "event stream only", "scopes": ["events:read"]},
    )
    assert events_key_response.status_code == 201
    exports_key_response = await owner.post(
        "/v1/api-keys",
        json={"name": "export download only", "scopes": ["exports:read"]},
    )
    assert exports_key_response.status_code == 201
    write_key_response = await owner.post(
        "/v1/api-keys",
        json={"name": "write only", "scopes": ["api:write"]},
    )
    assert write_key_response.status_code == 201

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {raw_key}"},
    ) as key_client:
        assert (await key_client.get("/v1/projects")).status_code == 200
        denied = await key_client.post("/v1/projects", json={"name": "Denied"})
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "API_KEY_SCOPE_DENIED"

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={
            "Authorization": f"Bearer {events_key_response.json()['key']}",
        },
    ) as events_client:
        denied = await events_client.get("/v1/projects")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "API_KEY_SCOPE_DENIED"
        scoped = await events_client.get(f"/v1/jobs/{uuid.uuid4()}/events/replay")
        assert scoped.status_code == 404

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={
            "Authorization": f"Bearer {exports_key_response.json()['key']}",
        },
    ) as exports_client:
        denied = await exports_client.get("/v1/settings")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "API_KEY_SCOPE_DENIED"
        scoped = await exports_client.get(f"/v1/exports/{uuid.uuid4()}")
        assert scoped.status_code == 404

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={
            "Authorization": f"Bearer {write_key_response.json()['key']}",
        },
    ) as write_client:
        denied = await write_client.get("/v1/projects")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "API_KEY_SCOPE_DENIED"
        created = await write_client.post(
            "/v1/projects",
            json={"name": "Write scoped project"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert created.status_code == 201

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as second:
        second_session = await _register(
            second,
            email="second@example.com",
            tenant_name="Second",
        )
        assert second_session["tenant_id"] != first_session["tenant_id"]
        hidden = await second.get(f"/v1/projects/{project_id}")
        assert hidden.status_code == 404

    csrf = await owner.post(
        "/v1/projects",
        json={"name": "Cross-site denied"},
        headers={"Origin": "https://attacker.invalid"},
    )
    assert csrf.status_code == 403
    assert csrf.json()["error"]["code"] == "CSRF_ORIGIN_DENIED"
    url_document = await owner.post(
        "/v1/documents",
        json={
            "project_id": project_id,
            "title": "Remote source",
            "source_url": "https://example.com/source.pdf",
        },
    )
    assert url_document.status_code == 403
    assert url_document.json()["error"]["code"] == "URL_INGESTION_DISABLED"


@pytest.mark.integration
async def test_upload_contract_rejects_extension_mime_size_and_checksum(api) -> None:
    client, _ = api
    await _register(client)
    project_id = (await client.post("/v1/projects", json={"name": "Security"})).json()["id"]
    executable = await client.post(
        "/v1/uploads/initiate",
        json={
            "project_id": project_id,
            "filename": "report.txt.exe",
            "size": 3,
            "content_type": "application/octet-stream",
            "sha256": hashlib.sha256(b"bad").hexdigest(),
        },
    )
    assert executable.status_code == 422
    assert executable.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"

    content = b"safe utf-8 source"
    initiated = await client.post(
        "/v1/uploads/initiate",
        json={
            "project_id": project_id,
            "filename": "../../normalized.txt",
            "size": len(content),
            "content_type": "text/plain",
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    )
    assert initiated.status_code == 201
    target = initiated.json()
    wrong_mime = await client.put(
        target["upload_url"],
        content=content,
        headers={"Content-Type": "application/pdf"},
    )
    assert wrong_mime.status_code == 422
    assert wrong_mime.json()["error"]["code"] == "CONTENT_TYPE_MISMATCH"
    wrong_checksum = await client.put(
        target["upload_url"],
        content=b"x" * len(content),
        headers={"Content-Type": "text/plain"},
    )
    assert wrong_checksum.status_code == 422
    assert wrong_checksum.json()["error"]["code"] == "CHECKSUM_MISMATCH"


@pytest.mark.integration
async def test_visual_input_fails_closed_and_releases_reserved_credit(api) -> None:
    client, _ = api
    await _register(client)
    project_id = (await client.post("/v1/projects", json={"name": "Visual"})).json()["id"]
    image_buffer = io.BytesIO()
    Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(image_buffer, format="PNG")
    png = image_buffer.getvalue()
    digest = hashlib.sha256(png).hexdigest()
    initiated = await client.post(
        "/v1/uploads/initiate",
        json={
            "project_id": project_id,
            "filename": "scan.png",
            "size": len(png),
            "content_type": "image/png",
            "sha256": digest,
        },
    )
    assert initiated.status_code == 201
    target = initiated.json()
    assert (
        await client.put(
            target["upload_url"],
            content=png,
            headers=target["headers"],
        )
    ).status_code == 204
    assert (
        await client.post(
            f"/v1/uploads/{target['upload_id']}/complete",
            json={"sha256": digest},
        )
    ).status_code == 200
    analyzed = await client.post(f"/v1/documents/{target['document_id']}/analyze")
    assert analyzed.status_code == 202
    analysis = (await client.get(f"/v1/documents/{target['document_id']}/analysis")).json()
    assert analysis["status"] == "completed"
    compiled = await client.post(
        f"/v1/documents/{target['document_id']}/compile",
        json={},
        headers={"Idempotency-Key": "visual-fail-closed"},
    )
    assert compiled.status_code == 202
    job_id = compiled.json()["job_id"]
    job = (await client.get(f"/v1/jobs/{job_id}")).json()
    assert job["status"] == "failed"
    assert job["job"]["credits"]["reserved"] == 0.0
    events = (await client.get(f"/v1/jobs/{job_id}/events/replay")).json()
    assert events[-2]["event_type"] == "job.failed.v1"
    assert events[-1]["event_type"] == "credit.released.v1"
    assert (await client.get("/v1/credits")).json()["reserved"] == "0.000000"


@pytest.mark.integration
async def test_concurrent_retry_idempotency_preserves_page_and_reserves_once(api) -> None:
    client, app = api
    await _register(
        client,
        email="retry-attempt@example.com",
        tenant_name="Retry Attempt Evidence",
    )
    project = await client.post(
        "/v1/projects",
        json={"name": "Immutable page retry"},
    )
    assert project.status_code == 201
    document_id, _ = await _upload_text(client, project.json()["id"])
    analyzed = await client.post(f"/v1/documents/{document_id}/analyze")
    assert analyzed.status_code == 202
    pages = await client.get(f"/v1/documents/{document_id}/pages")
    assert pages.status_code == 200
    page_payload = pages.json()[0]
    page_id = uuid.UUID(page_payload["id"])
    original_status = page_payload["status"]
    original_attempt_id = page_payload["latest_attempt_id"]
    assert original_attempt_id is not None

    app.state.settings.local_background_tasks = False

    async def retry_once() -> httpx.Response:
        return await client.post(
            f"/v1/pages/{page_id}/retry",
            headers={"Idempotency-Key": "same-page-retry"},
        )

    first, duplicate = await asyncio.gather(retry_once(), retry_once())
    assert first.status_code == 202, first.text
    assert duplicate.status_code == 202, duplicate.text
    assert duplicate.json() == first.json()
    retry_job_id = uuid.UUID(first.json()["job_id"])
    retry_attempt_id = first.json()["progress"]["attempt_id"]
    retry_snapshot = await client.get(f"/v1/jobs/{retry_job_id}")
    assert retry_snapshot.status_code == 200
    assert retry_snapshot.json()["pages"][0]["attempt"]["id"] == retry_attempt_id
    retry_events = await client.get(f"/v1/jobs/{retry_job_id}/events/replay")
    assert retry_events.status_code == 200
    scheduled_event = next(
        event for event in retry_events.json() if event["event_type"] == "page.retry.scheduled.v1"
    )
    assert scheduled_event["payload"]["attempt_id"] == retry_attempt_id
    assert scheduled_event["payload"]["attempt_number"] == 2

    async with app.state.database.sessions() as session:
        page = await session.get(Page, page_id)
        attempts = list(
            (
                await session.scalars(
                    select(PageAttempt)
                    .where(PageAttempt.page_id == page_id)
                    .order_by(PageAttempt.attempt_number)
                )
            ).all()
        )
        reserve_count = await session.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.job_id == retry_job_id,
                CreditLedger.entry_type == "reserve",
            )
        )
    assert page is not None and page.status == original_status
    assert len(attempts) == 2
    assert str(attempts[0].id) == original_attempt_id
    assert attempts[0].status == "COMPLETED"
    assert str(attempts[1].id) == retry_attempt_id
    assert attempts[1].status == "RETRY_SCHEDULED"
    assert reserve_count == 1


@pytest.mark.integration
async def test_concurrent_distinct_review_resolutions_commit_once_and_audit(api) -> None:
    client, app = api
    registration = await _register(
        client,
        email="review-race@example.com",
        tenant_name="Review Race Evidence",
    )
    tenant_id = uuid.UUID(registration["tenant_id"])
    project = await client.post(
        "/v1/projects",
        json={"name": "Atomic review resolution"},
    )
    assert project.status_code == 201, project.text
    project_id = uuid.UUID(project.json()["id"])
    document_id_value, _ = await _upload_text(client, str(project_id))
    document_id = uuid.UUID(document_id_value)
    analyzed = await client.post(f"/v1/documents/{document_id}/analyze")
    assert analyzed.status_code == 202, analyzed.text

    async with app.state.database.sessions.begin() as session:
        block = await session.scalar(
            select(Block)
            .where(
                Block.tenant_id == tenant_id,
                Block.document_id == document_id,
            )
            .order_by(Block.block_order)
        )
        assert block is not None
        review = ReviewItem(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=document_id,
            page_id=block.page_id,
            block_id=block.id,
            severity="high",
            category="numeric_exactness",
            status="open",
            evidence={"message": "Resolve this block exactly once."},
        )
        session.add(review)
        await session.flush()
        review_id = review.id
        block_id = block.id
        initial_revision = block.revision

    async def resolve_once(key: str, value: str) -> httpx.Response:
        return await client.post(
            f"/v1/review-items/{review_id}/resolve",
            headers={"Idempotency-Key": key},
            json={
                "action": "replace",
                "value": value,
                "note": f"decision-{key}",
            },
        )

    first, second = await asyncio.gather(
        resolve_once("review-race-first", "First approved replacement."),
        resolve_once("review-race-second", "Second approved replacement."),
    )
    winner, loser = (first, second) if first.status_code == 200 else (second, first)
    assert winner.status_code == 200, winner.text
    assert loser.status_code == 409, loser.text
    assert loser.json()["error"]["code"] == "REVIEW_ALREADY_RESOLVED"

    async with app.state.database.sessions() as session:
        persisted_review = await session.get(ReviewItem, review_id)
        persisted_block = await session.get(Block, block_id)
        revisions = list(
            (
                await session.scalars(
                    select(BlockRevision).where(
                        BlockRevision.tenant_id == tenant_id,
                        BlockRevision.block_id == block_id,
                        BlockRevision.operation == "resolve_review_replace",
                    )
                )
            ).all()
        )
        audits = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.action == "review.resolved",
                        AuditEvent.target_id == str(review_id),
                    )
                )
            ).all()
        )

    assert persisted_review is not None
    assert persisted_review.status == "resolved"
    assert persisted_review.resolution == winner.json()["resolution"]
    assert persisted_block is not None
    assert persisted_block.revision == initial_revision + 1
    assert persisted_block.markdown == winner.json()["resolution"]["value"]
    assert len(revisions) == 1
    assert len(audits) == 1
    assert audits[0].target_type == "review_item"
    assert audits[0].metadata_json == {
        "action": "replace",
        "document_id": str(document_id),
        "page_id": str(persisted_block.page_id),
        "block_id": str(block_id),
    }
    assert "First approved replacement." not in json.dumps(audits[0].metadata_json)
    assert "Second approved replacement." not in json.dumps(audits[0].metadata_json)


@pytest.mark.integration
async def test_review_source_adoption_and_document_rule_require_a_fresh_preview(api) -> None:
    client, app = api
    registration = await _register(
        client,
        email="review-rule@example.com",
        tenant_name="Review Rule Evidence",
    )
    tenant_id = uuid.UUID(registration["tenant_id"])
    project = await client.post("/v1/projects", json={"name": "Review rules"})
    project_id = uuid.UUID(project.json()["id"])
    document_id_value, _ = await _upload_text(client, str(project_id))
    document_id = uuid.UUID(document_id_value)
    analyzed = await client.post(f"/v1/documents/{document_id}/analyze")
    assert analyzed.status_code == 202, analyzed.text

    async with app.state.database.sessions.begin() as session:
        block = await session.scalar(
            select(Block).where(
                Block.tenant_id == tenant_id,
                Block.document_id == document_id,
            )
        )
        assert block is not None and block.source_text
        block_id = block.id
        page_id = block.page_id
        source_text = block.source_text
        block.markdown = "A model-derived value that must be replaced."
        reviews = [
            ReviewItem(
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                page_id=block.page_id,
                block_id=block.id,
                severity="high",
                category="numeric_exactness",
                status="open",
                evidence={"message": f"Rule candidate {index}"},
            )
            for index in range(2)
        ]
        session.add_all(reviews)
        await session.flush()
        first_review_id = reviews[0].id
        second_review_id = reviews[1].id

    adopted = await client.post(
        f"/v1/review-items/{first_review_id}/resolve",
        headers={"Idempotency-Key": "review-adopt-source"},
        json={"action": "adopt_source", "note": "Use immutable source"},
    )
    assert adopted.status_code == 200, adopted.text
    async with app.state.database.sessions() as session:
        block = await session.get(Block, block_id)
    assert block is not None and block.markdown == source_text

    preview = await client.get(f"/v1/review-items/{second_review_id}/scope-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["item_count"] == 1
    stale_hash = preview.json()["preview_sha256"]

    async with app.state.database.sessions.begin() as session:
        session.add(
            ReviewItem(
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                page_id=page_id,
                block_id=block_id,
                severity="medium",
                category="numeric_exactness",
                status="open",
                evidence={"message": "Arrived after preview"},
            )
        )

    stale = await client.post(
        f"/v1/review-items/{second_review_id}/apply-rule",
        headers={"Idempotency-Key": "review-rule-stale"},
        json={"action": "accept", "preview_sha256": stale_hash},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "REVIEW_SCOPE_CHANGED"

    refreshed = await client.get(f"/v1/review-items/{second_review_id}/scope-preview")
    assert refreshed.status_code == 200
    assert refreshed.json()["item_count"] == 2
    applied = await client.post(
        f"/v1/review-items/{second_review_id}/apply-rule",
        headers={"Idempotency-Key": "review-rule-current"},
        json={
            "action": "accept",
            "preview_sha256": refreshed.json()["preview_sha256"],
            "note": "Approved matching document rule",
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["affected_count"] == 2
    async with app.state.database.sessions() as session:
        audits = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.action == "review.rule_applied",
                    )
                )
            ).all()
        )
    assert len(audits) == 2
    assert all(audit.metadata_json["preview_sha256"] for audit in audits)


async def test_model_promotion_rollback_and_retirement_are_atomic_and_audited(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = api
    registration = await _register(
        client,
        email="model-operator@example.com",
        tenant_name="Model Operations",
    )
    tenant_id = uuid.UUID(registration["tenant_id"])
    benchmark = "sha256:" + "c" * 64
    recipe = "sha256:" + "d" * 64
    async with app.state.database.sessions() as session:
        previous = ModelRegistry(
            endpoint="paddle_vl_operator",
            model_id="paddle-vl-stable",
            revision="a" * 40,
            runtime_image_digest="sha256:" + "1" * 64,
            adapter_version="parser-adapter-1.0.0",
            policy_version="router-model-ops",
            benchmark_report="benchmarks/stable.json",
            benchmark_sha256=benchmark,
            recipe_sha256=recipe,
            lifecycle_state="champion",
            enabled=True,
            canary_percent=100,
        )
        candidate = ModelRegistry(
            endpoint="paddle_vl_operator",
            model_id="paddle-vl-candidate",
            revision="b" * 40,
            runtime_image_digest="sha256:" + "2" * 64,
            adapter_version="parser-adapter-1.1.0",
            policy_version="router-model-ops",
            benchmark_report="benchmarks/candidate.json",
            lifecycle_state="candidate",
            enabled=False,
            canary_percent=0,
        )
        disposable = ModelRegistry(
            endpoint="paddle_fast_disposable",
            model_id="paddle-fast-disposable",
            revision="e" * 40,
            runtime_image_digest="sha256:" + "3" * 64,
            adapter_version="parser-adapter-1.0.0",
            policy_version="router-model-ops",
            benchmark_report="benchmarks/disposable.json",
            lifecycle_state="candidate",
            enabled=False,
            canary_percent=0,
        )
        session.add_all((previous, candidate, disposable))
        await session.commit()
        previous_id = previous.id
        candidate_id = candidate.id
        disposable_id = disposable.id

    promoted = await client.post(
        f"/v1/admin/models/{candidate_id}/promote",
        json={
            "expected_generation": 1,
            "approval_ref": "CAB-2026-0730",
            "benchmark_sha256": benchmark,
            "recipe_sha256": recipe,
            "reason": "Validated replacement after reviewed local evidence.",
        },
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["lifecycle_state"] == "champion"
    assert promoted.json()["generation"] == 2
    assert promoted.json()["promoted_from_id"] == str(previous_id)

    stale = await client.post(
        f"/v1/admin/models/{candidate_id}/promote",
        json={
            "expected_generation": 1,
            "approval_ref": "CAB-2026-0730",
            "benchmark_sha256": benchmark,
            "recipe_sha256": recipe,
            "reason": "A stale operator must not overwrite the reviewed change.",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "MODEL_GENERATION_CONFLICT"

    rolled_back = await client.post(
        f"/v1/admin/models/{candidate_id}/rollback",
        json={
            "expected_generation": 2,
            "approval_ref": "INC-2026-0730",
            "reason": "Restore the one-step fallback after a regression.",
        },
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["restored"]["id"] == str(previous_id)
    assert rolled_back.json()["restored"]["lifecycle_state"] == "champion"
    assert rolled_back.json()["rolled_back"]["lifecycle_state"] == "fallback"

    protected = await client.post(
        f"/v1/admin/models/{candidate_id}/retire",
        json={
            "expected_generation": 3,
            "approval_ref": "CAB-2026-0730",
            "reason": "Attempt to retire the active rollback target.",
        },
    )
    assert protected.status_code == 409
    assert protected.json()["error"]["code"] == "MODEL_REQUIRED_FOR_ROLLBACK"

    retired = await client.post(
        f"/v1/admin/models/{disposable_id}/retire",
        json={
            "expected_generation": 1,
            "approval_ref": "CAB-2026-0730",
            "reason": "Retire an unused candidate with no routing authority.",
        },
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["lifecycle_state"] == "retired"
    assert retired.json()["enabled"] is False

    async with app.state.database.sessions() as session:
        audit_actions = set(
            (
                await session.scalars(
                    select(AuditEvent.action).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.action.in_(
                            ("model.promoted", "model.rolled_back", "model.retired")
                        ),
                    )
                )
            ).all()
        )
    assert audit_actions == {
        "model.promoted",
        "model.rolled_back",
        "model.retired",
    }


def test_production_settings_fail_closed_without_durable_dependencies() -> None:
    with pytest.raises(ValueError, match="production requires PostgreSQL"):
        Settings(
            env="production",
            database_url="sqlite+aiosqlite:///:memory:",
            jwt_secret="a" * 48,
            local_background_tasks=False,
            object_store_driver="s3",
            clamav_enabled=True,
            allow_development_antivirus_bypass=False,
        )
