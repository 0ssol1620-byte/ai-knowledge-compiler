"""Contract, privacy, and tenant-isolation tests for product analytics."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import (
    AuditEvent,
    Block,
    BlockRevision,
    Document,
    DocumentVersion,
    Export,
    KnowledgeNote,
    Page,
    ProcessingJob,
    Project,
    ReviewItem,
    utcnow,
)
from akc_api.settings import Settings
from sqlalchemy import func, select

_SUPPORT_KEY = "product-analytics-test-support-key"
_PASSWORD = "correct horse battery staple"  # noqa: S105


@pytest_asyncio.fixture
async def analytics_api(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'analytics.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
        test_support_key=_SUPPORT_KEY,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client, app


async def _capture_token(client: httpx.AsyncClient, email: str) -> str:
    response = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _SUPPORT_KEY},
        json={"email": email},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


async def _register_verified(
    client: httpx.AsyncClient,
    *,
    email: str,
    tenant_name: str,
) -> dict[str, Any]:
    registered = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "display_name": email.split("@", 1)[0],
            "tenant_name": tenant_name,
        },
    )
    assert registered.status_code == 201, registered.text
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": await _capture_token(client, email)},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def _seed_measured_project(
    app: Any,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    suffix: str,
) -> dict[str, uuid.UUID]:
    now = utcnow()
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    page_one_id = uuid.uuid4()
    page_two_id = uuid.uuid4()
    table_block_id = uuid.uuid4()
    plain_block_id = uuid.uuid4()
    job_id = uuid.uuid4()
    async with app.state.database.sessions() as session:
        session.add(
            Project(
                id=project_id,
                tenant_id=tenant_id,
                name=f"Measured {suffix}",
                description=None,
                output_profile={},
                classification="general",
                created_by=user_id,
                created_at=now - timedelta(days=3),
                updated_at=now - timedelta(days=1),
            )
        )
        await session.flush()
        session.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                project_id=project_id,
                source_file_id=None,
                title=f"Document {suffix}",
                document_type="pdf",
                language_codes=["en"],
                page_count=2,
                status="COMPLETED",
                created_at=now - timedelta(days=3),
                updated_at=now - timedelta(days=1),
            )
        )
        await session.flush()
        session.add(
            DocumentVersion(
                tenant_id=tenant_id,
                document_id=document_id,
                version=1,
                cir_object_key=None,
                policy_version="policy-2026-07",
                model_revision="deterministic-v1",
                prompt_revision=None,
                created_at=now - timedelta(days=3),
            )
        )
        await session.flush()
        session.add_all(
            [
                Page(
                    id=page_one_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    page_number=1,
                    status="COMPLETED",
                    route="native",
                    quality_metrics={"state": "verified"},
                    created_at=now - timedelta(days=2),
                    updated_at=now - timedelta(days=2),
                ),
                Page(
                    id=page_two_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    page_number=2,
                    status="COMPLETED",
                    route="mistral_fallback",
                    quality_metrics={"state": "warning"},
                    created_at=now - timedelta(days=2),
                    updated_at=now - timedelta(days=2),
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                Block(
                    id=table_block_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    page_id=page_two_id,
                    block_order=1,
                    block_type="table",
                    origin="direct",
                    source_text="source evidence that must never leave aggregation",
                    normalized_text="normalized",
                    markdown="table",
                    created_at=now - timedelta(days=2),
                    updated_at=now - timedelta(days=1),
                ),
                Block(
                    id=plain_block_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    page_id=page_one_id,
                    block_order=2,
                    block_type="paragraph",
                    origin="ai_summarized",
                    source_text=None,
                    normalized_text="unsupported output",
                    markdown="unsupported output",
                    created_at=now - timedelta(days=2),
                    updated_at=now - timedelta(days=2),
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
                job_type="compile",
                status="completed",
                progress={"done": 2, "total": 2},
                cost_actual={"credits": "2", "provider": "deterministic"},
                started_at=now - timedelta(days=2, minutes=5),
                completed_at=now - timedelta(days=2),
                created_at=now - timedelta(days=2, minutes=10),
            )
        )
        await session.flush()
        review_id = uuid.uuid4()
        session.add(
            ReviewItem(
                id=review_id,
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                page_id=page_two_id,
                block_id=table_block_id,
                severity="high",
                category="quality_critical",
                status="resolved",
                evidence={
                    "quality_findings": [
                        {"code": "numeric.token_mismatch", "message": "not exported"}
                    ]
                },
                resolution={"action": "replace"},
                resolved_by=user_id,
                resolved_at=now - timedelta(days=1),
                created_at=now - timedelta(days=1, hours=2),
            )
        )
        await session.flush()
        session.add(
            BlockRevision(
                tenant_id=tenant_id,
                block_id=table_block_id,
                base_revision=1,
                new_revision=2,
                operation="resolve_review_replace",
                value="corrected private content",
                actor_id=user_id,
                created_at=now - timedelta(days=1),
            )
        )
        session.add(
            KnowledgeNote(
                tenant_id=tenant_id,
                project_id=project_id,
                stable_key=f"unsupported-{suffix}",
                title="Unsupported",
                note_type="summary",
                content_markdown="private note content",
                metadata_json={},
                evidence_block_ids=[],
                content_origin="ai_summarized",
                review_status="unreviewed",
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
            )
        )
        session.add(
            Export(
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                export_type="portable",
                status="completed",
                options={},
                storage_key=f"exports/{suffix}.zip",
                sha256="a" * 64,
                size_bytes=100,
                created_by=user_id,
                created_at=now - timedelta(hours=13),
                completed_at=now - timedelta(hours=12),
            )
        )
        await session.commit()
    return {
        "project_id": project_id,
        "document_id": document_id,
        "job_id": job_id,
    }


async def test_snapshot_has_exact_denominators_and_is_tenant_isolated(
    analytics_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = analytics_api
    owner = await _register_verified(
        client,
        email="analytics-owner@example.com",
        tenant_name="Analytics A",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    user_id = uuid.UUID(owner["user_id"])
    target = await _seed_measured_project(
        app,
        tenant_id=tenant_id,
        user_id=user_id,
        suffix="tenant-a",
    )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as other:
        intruder = await _register_verified(
            other,
            email="analytics-other@example.com",
            tenant_name="Analytics B",
        )
        await _seed_measured_project(
            app,
            tenant_id=uuid.UUID(intruder["tenant_id"]),
            user_id=uuid.UUID(intruder["user_id"]),
            suffix="tenant-b",
        )

    response = await client.get("/v1/analytics?window=7d")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["window"]["key"] == "7d"
    start = payload["window"]["start_at"]
    end = payload["window"]["end_at"]
    assert start < end
    assert payload["window"]["boundary"] == "start_inclusive_end_exclusive"
    assert payload["north_star"]["value"] == 1
    assert payload["product"]["job_completion_rate"]["numerator"] == 1
    assert payload["product"]["job_completion_rate"]["denominator"] == 1
    assert payload["product"]["export_rate"]["value"] == 1
    assert payload["product"]["review_items_per_page"]["value"] == 0.5
    assert payload["product"]["edits_per_block"]["value"] == 0.5
    assert payload["quality"]["accepted_without_review_rate"]["value"] == 0.5
    assert payload["quality"]["fallback_rate"]["value"] == 0.5
    assert payload["quality"]["source_coverage_rate"]["value"] == 0.5
    assert payload["quality"]["unsupported_claim_rate"]["value"] == 1
    assert payload["quality"]["numeric_mismatch_rate"]["value"] == 1
    assert payload["quality"]["table_correction_rate"]["value"] == 1
    assert payload["economics"]["credit_cost_per_page"]["value"] == 1
    assert payload["economics"]["gross_margin_rate"]["value"] is None
    assert payload["economics"]["gross_margin_rate"]["status"] == "insufficient_evidence"
    assert payload["refunds_by_currency"] == []

    serialized = response.text
    assert str(target["project_id"]) not in serialized
    assert str(target["document_id"]) not in serialized
    assert "source evidence" not in serialized
    assert "private note content" not in serialized
    assert "analytics-other@example.com" not in serialized


async def test_opt_out_private_mode_and_event_payload_are_fail_closed(
    analytics_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = analytics_api
    owner = await _register_verified(
        client,
        email="privacy-owner@example.com",
        tenant_name="Analytics Privacy",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    user_id = uuid.UUID(owner["user_id"])
    target = await _seed_measured_project(
        app,
        tenant_id=tenant_id,
        user_id=user_id,
        suffix="privacy",
    )

    private_event = await client.post(
        "/v1/analytics/events",
        headers={"Idempotency-Key": "private-result-view"},
        json={
            "event_type": "result_first_viewed",
            "job_id": str(target["job_id"]),
        },
    )
    assert private_event.status_code == 202
    assert private_event.json()["accepted"] is False
    assert private_event.json()["reason"] == "private_mode"

    enabled = await client.patch(
        "/v1/privacy",
        headers={"Idempotency-Key": "enable-local-product-events"},
        json={"private_mode": False, "product_analytics_enabled": True},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["product_analytics_enabled"] is True

    invalid = await client.post(
        "/v1/analytics/events",
        json={
            "event_type": "result_first_viewed",
            "job_id": str(target["job_id"]),
            "free_text": "customer@example.com secret source.pdf",
        },
    )
    assert invalid.status_code == 422

    stored = await client.post(
        "/v1/analytics/events",
        headers={"Idempotency-Key": "stored-result-view"},
        json={
            "event_type": "result_first_viewed",
            "job_id": str(target["job_id"]),
        },
    )
    replay = await client.post(
        "/v1/analytics/events",
        headers={"Idempotency-Key": "stored-result-view"},
        json={
            "event_type": "result_first_viewed",
            "job_id": str(target["job_id"]),
        },
    )
    assert stored.status_code == replay.status_code == 202
    assert stored.json() == replay.json()
    assert stored.json()["accepted"] is True

    async with app.state.database.sessions() as session:
        rows = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action == "product.result_first_viewed",
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].metadata_json == {
            "schema_version": 1,
            "model_revision": "deterministic-v1",
            "policy_version": "policy-2026-07",
        }
        assert "email" not in repr(rows[0].metadata_json)

    opted_out = await client.patch(
        "/v1/settings",
        headers={"Idempotency-Key": "disable-product-analytics"},
        json={"product_analytics_enabled": False},
    )
    assert opted_out.status_code == 200
    assert opted_out.json()["product_analytics_enabled"] is False
    settings = await client.get("/v1/settings")
    assert settings.status_code == 200
    assert settings.json()["product_analytics_enabled"] is False

    ignored = await client.post(
        "/v1/analytics/events",
        json={
            "event_type": "result_first_viewed",
            "job_id": str(target["job_id"]),
        },
    )
    assert ignored.status_code == 202
    assert ignored.json()["reason"] == "analytics_disabled"
    disabled_snapshot = await client.get("/v1/analytics")
    assert disabled_snapshot.status_code == 200
    assert disabled_snapshot.json()["privacy"]["collection_mode"] == "disabled"
    assert disabled_snapshot.json()["north_star"]["status"] == "disabled"

    async with app.state.database.sessions() as session:
        assert (
            await session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action == "product.result_first_viewed",
                )
            )
            == 1
        )


async def test_empty_denominators_are_null_not_zero(
    analytics_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _ = analytics_api
    await _register_verified(
        client,
        email="empty-analytics@example.com",
        tenant_name="Empty Analytics",
    )

    response = await client.get("/v1/analytics?window=30d")
    assert response.status_code == 200, response.text
    payload = response.json()
    metric = payload["quality"]["accepted_without_review_rate"]
    assert metric["numerator"] == 0
    assert metric["denominator"] == 0
    assert metric["value"] is None
    assert metric["status"] == "empty_denominator"
    assert payload["privacy"]["collection_mode"] == "private_operational_only"
    assert payload["economics"]["support_minutes_per_job"]["status"] == "not_instrumented"
