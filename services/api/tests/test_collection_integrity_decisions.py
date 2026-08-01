"""Executable isolation, idempotency, and transition evidence for Integrity Console."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from akc_api.collection_api import _complete_knowledge_groups
from akc_api.collection_integrity_runtime import (
    IntegrityActionRejected,
    reconcile_integrity_retry_job,
    resolve_pinned_retry_binding,
)
from akc_api.collection_processing import reconcile_collection_analysis_task
from akc_api.main import create_app
from akc_api.models import (
    AnalysisTask,
    ArchitecturePlan,
    AuditEvent,
    Block,
    Collection,
    CollectionEvent,
    CollectionFile,
    CollectionIntegrityActionExecution,
    CollectionIntegrityDecision,
    Document,
    FileVersion,
    ModelRegistry,
    OutboxEvent,
    Page,
    PageAsset,
    PageAttempt,
    ProcessingJob,
    QuarantineItem,
    ReviewItem,
    SourceFile,
    utcnow,
)
from akc_api.routing_runtime import load_routing_runtime
from akc_api.settings import Settings
from akc_router import Route
from sqlalchemy import func, select

_SUPPORT_KEY = "integrity-console-test-support-key"
_PASSWORD = "correct horse battery staple"  # noqa: S105


@pytest_asyncio.fixture
async def integrity_api(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'integrity.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
        collection_metadata_encryption_enabled=True,
        test_support_key=_SUPPORT_KEY,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, app


async def _register(
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
            "display_name": "Integrity Owner",
            "tenant_name": tenant_name,
        },
    )
    assert registered.status_code == 201, registered.text
    captured = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _SUPPORT_KEY},
        json={"email": email},
    )
    assert captured.status_code == 200, captured.text
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": captured.json()["token"]},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def _project(client: httpx.AsyncClient, *, prefix: str) -> str:
    response = await client.post(
        "/v1/projects",
        headers={"Idempotency-Key": f"{prefix}-project"},
        json={"name": f"Integrity {prefix}"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _collection_file(
    client: httpx.AsyncClient,
    *,
    project_id: str,
    prefix: str,
    content: bytes,
) -> tuple[str, str]:
    collection = await client.post(
        "/v1/collections",
        headers={"Idempotency-Key": f"{prefix}-collection"},
        json={"project_id": project_id, "name": f"Integrity {prefix}"},
    )
    assert collection.status_code == 201, collection.text
    collection_id = str(collection.json()["id"])
    root = await client.post(
        f"/v1/collections/{collection_id}/sources/local",
        headers={"Idempotency-Key": f"{prefix}-root"},
        json={
            "display_name": f"{prefix} private root",
            "source_fingerprint": hashlib.sha256(prefix.encode()).hexdigest(),
        },
    )
    assert root.status_code == 201, root.text
    planned = await client.post(
        f"/v1/collections/{collection_id}/files/plan",
        headers={"Idempotency-Key": f"{prefix}-plan"},
        json={
            "source_root_id": root.json()["id"],
            "files": [
                {
                    "relative_path": f"evidence/{prefix}.txt",
                    "display_name": f"{prefix}.txt",
                    "size_bytes": len(content),
                    "last_modified_ms": 1_785_469_200_000,
                    "expected_mime": "text/plain",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "quick_fingerprint": f"quick:{prefix}:integrity",
                }
            ],
        },
    )
    assert planned.status_code == 201, planned.text
    return collection_id, str(planned.json()["files"][0]["id"])


async def _legacy_upload(
    client: httpx.AsyncClient,
    *,
    project_id: str,
    prefix: str,
    content: bytes,
) -> dict[str, Any]:
    digest = hashlib.sha256(content).hexdigest()
    initiated = await client.post(
        "/v1/uploads/initiate",
        headers={"Idempotency-Key": f"{prefix}-upload-init"},
        json={
            "project_id": project_id,
            "filename": f"{prefix}.txt",
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
        headers={"Idempotency-Key": f"{prefix}-upload-complete"},
        json={"sha256": digest},
    )
    assert completed.status_code == 200, completed.text
    return {**target, **completed.json()}


async def _quarantine_targets(
    app: Any,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    file_id: uuid.UUID,
    count: int,
    reason_code: str = "CUSTOMER_REVIEW_REQUIRED",
) -> list[uuid.UUID]:
    async with app.state.database.sessions() as session:
        collection = await session.get(Collection, collection_id)
        assert collection is not None
        collection.status = "QUARANTINED"
        targets = [
            QuarantineItem(
                tenant_id=tenant_id,
                collection_id=collection_id,
                collection_file_id=file_id,
                reason_code=reason_code,
                status="open",
                evidence={"finding_code": reason_code},
            )
            for _ in range(count)
        ]
        session.add_all(targets)
        await session.commit()
        return [target.id for target in targets]


async def test_integrity_decisions_are_idempotent_audited_and_tenant_isolated(
    integrity_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = integrity_api
    openapi = app.openapi()
    assert "/v1/collections/{collection_id}/integrity/findings" in openapi["paths"]
    assert "/v1/collections/{collection_id}/integrity/decisions" in openapi["paths"]
    finding_schema = openapi["components"]["schemas"]["CollectionIntegrityFindingResponse"]
    assert set(finding_schema["required"]) == {
        "target_type",
        "target_id",
        "status",
        "category",
        "severity",
        "reason_code",
        "allowed_actions",
        "created_at",
    }
    decision_list_schema = openapi["components"]["schemas"]["CollectionIntegrityDecisionList"]
    assert "collection_id" in decision_list_schema["required"]
    owner = await _register(
        client,
        email="integrity.owner@example.com",
        tenant_name="Integrity Owner Tenant",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    project_id = await _project(client, prefix="tenant-a")
    collection_id_raw, file_id_raw = await _collection_file(
        client,
        project_id=project_id,
        prefix="tenant-a",
        content=b"integrity evidence",
    )
    collection_id = uuid.UUID(collection_id_raw)
    target_ids = await _quarantine_targets(
        app,
        tenant_id=tenant_id,
        collection_id=collection_id,
        file_id=uuid.UUID(file_id_raw),
        count=3,
    )

    findings = await client.get(
        f"/v1/collections/{collection_id}/integrity/findings",
        params={"limit": 2},
    )
    assert findings.status_code == 200, findings.text
    findings_body = findings.json()
    assert findings_body["collection_id"] == str(collection_id)
    assert len(findings_body["items"]) == 2
    assert findings_body["next_cursor"] is not None
    assert all(
        set(item)
        == {
            "target_type",
            "target_id",
            "status",
            "category",
            "severity",
            "reason_code",
            "allowed_actions",
            "action_evidence",
            "created_at",
        }
        for item in findings_body["items"]
    )
    assert all("override" not in item["allowed_actions"] for item in findings_body["items"])
    assert all("provide_password" not in item["allowed_actions"] for item in findings_body["items"])
    assert all("retry_new_engine" not in item["allowed_actions"] for item in findings_body["items"])
    assert all("correct_source" not in item["allowed_actions"] for item in findings_body["items"])
    assert "private root" not in findings.text.casefold()
    assert "evidence/" not in findings.text.casefold()
    findings_next = await client.get(
        f"/v1/collections/{collection_id}/integrity/findings",
        params={"limit": 2, "cursor": findings_body["next_cursor"]},
    )
    assert findings_next.status_code == 200, findings_next.text
    assert len(findings_next.json()["items"]) == 1
    forged_cursor = await client.get(
        f"/v1/collections/{collection_id}/integrity/findings",
        params={"cursor": f"q:{uuid.uuid4()}"},
    )
    assert forged_cursor.status_code == 404, forged_cursor.text
    assert forged_cursor.json()["error"]["code"] == "INTEGRITY_FINDING_CURSOR_NOT_FOUND"

    exclude_payload = {
        "target_type": "quarantine_item",
        "target_id": str(target_ids[0]),
        "action": "exclude",
        "reason_code": "EXCLUDED_FROM_OUTPUT",
    }
    missing_key = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        json=exclude_payload,
    )
    assert missing_key.status_code == 428, missing_key.text

    first = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-exclude"},
        json=exclude_payload,
    )
    replay = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-exclude"},
        json=exclude_payload,
    )
    assert first.status_code == replay.status_code == 201, first.text
    assert first.json() == replay.json()
    assert first.json()["resulting_status"] == "rejected"

    conflict = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-exclude"},
        json={**exclude_payload, "target_id": str(target_ids[1])},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    unapproved_retry = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-retry-unapproved"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(target_ids[1]),
            "action": "retry_new_engine",
            "reason_code": "RETRY_WITH_APPROVED_ENGINE",
            "evidence_reference": {
                "kind": "engine_revision",
                "sha256": "f" * 64,
                "revision": "e" * 40,
            },
        },
    )
    assert unapproved_retry.status_code == 409, unapproved_retry.text
    assert unapproved_retry.json()["error"]["code"] == "INTEGRITY_ACTION_NOT_EXECUTABLE"

    retry = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-retry-engine"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(target_ids[1]),
            "action": "retry_new_engine",
            "reason_code": "RETRY_WITH_APPROVED_ENGINE",
            "evidence_reference": {
                "kind": "engine_revision",
                "sha256": "a" * 64,
                "revision": "e" * 40,
            },
        },
    )
    assert retry.status_code == 409, retry.text
    assert retry.json()["error"]["code"] == "INTEGRITY_ACTION_NOT_EXECUTABLE"

    kept = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-keep"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(target_ids[2]),
            "action": "keep_quarantined",
            "reason_code": "ACCEPTED_QUARANTINE",
        },
    )
    assert kept.status_code == 201, kept.text
    assert kept.json()["resulting_status"] == "resolved"
    closed_target = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-keep-again"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(target_ids[2]),
            "action": "keep_quarantined",
            "reason_code": "ACCEPTED_QUARANTINE",
        },
    )
    assert closed_target.status_code == 409, closed_target.text
    assert closed_target.json()["error"]["code"] == "INTEGRITY_FINDING_NOT_OPEN"

    listed = await client.get(
        f"/v1/collections/{collection_id}/integrity/decisions",
        params={"limit": 2},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["collection_id"] == str(collection_id)
    assert len(listed.json()["items"]) == 2
    assert listed.json()["next_cursor"] is None

    async with app.state.database.sessions() as session:
        assert (
            await session.scalar(
                select(func.count(CollectionIntegrityDecision.id)).where(
                    CollectionIntegrityDecision.tenant_id == tenant_id,
                    CollectionIntegrityDecision.collection_id == collection_id,
                )
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count(CollectionEvent.id)).where(
                    CollectionEvent.collection_id == collection_id,
                    CollectionEvent.event_type == "integrity.decision.recorded.v1",
                )
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action == "collection.integrity.decision.recorded",
                )
            )
            == 2
        )
        events = list(
            await session.scalars(
                select(CollectionEvent).where(
                    CollectionEvent.collection_id == collection_id,
                    CollectionEvent.event_type == "integrity.decision.recorded.v1",
                )
            )
        )
        assert all(
            set(event.payload)
            == {
                "collection_id",
                "decision_id",
                "target_type",
                "target_id",
                "action",
                "reason_code",
                "result_status",
                "evidence_reference_kind",
            }
            for event in events
        )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as other:
        await _register(
            other,
            email="integrity.other@example.com",
            tenant_name="Integrity Other Tenant",
        )
        cross_tenant = await other.post(
            f"/v1/collections/{collection_id}/integrity/decisions",
            headers={"Idempotency-Key": "integrity-exclude"},
            json=exclude_payload,
        )
        assert cross_tenant.status_code == 404, cross_tenant.text
        hidden = await other.get(f"/v1/collections/{collection_id}/integrity/decisions")
        assert hidden.status_code == 404, hidden.text
        hidden_findings = await other.get(f"/v1/collections/{collection_id}/integrity/findings")
        assert hidden_findings.status_code == 404, hidden_findings.text


async def test_review_override_and_collection_state_guards_fail_closed(
    integrity_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = integrity_api
    owner = await _register(
        client,
        email="integrity.override@example.com",
        tenant_name="Integrity Override Tenant",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    project_id_raw = await _project(client, prefix="override")
    project_id = uuid.UUID(project_id_raw)
    content = b"review target evidence"
    collection_id_raw, file_id_raw = await _collection_file(
        client,
        project_id=project_id_raw,
        prefix="override",
        content=content,
    )
    collection_id = uuid.UUID(collection_id_raw)
    file_id = uuid.UUID(file_id_raw)
    uploaded = await _legacy_upload(
        client,
        project_id=project_id_raw,
        prefix="override",
        content=content,
    )
    source_id = uuid.UUID(uploaded["source_file_id"])
    document_id = uuid.UUID(uploaded["document_id"])

    async with app.state.database.sessions() as session:
        collection = await session.get(Collection, collection_id)
        collection_file = await session.get(CollectionFile, file_id)
        source = await session.get(SourceFile, source_id)
        assert collection is not None and collection_file is not None and source is not None
        collection.status = "UNRESOLVED"
        collection_file.source_file_id = source.id
        source.antivirus_status = "clean"
        low = ReviewItem(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=document_id,
            severity="medium",
            category="ambiguous_layout",
            status="open",
            evidence={"finding_code": "AMBIGUOUS_LAYOUT"},
        )
        high = ReviewItem(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=document_id,
            severity="high",
            category="security_injection",
            status="open",
            evidence={"finding_code": "SECURITY_INJECTION"},
        )
        terminal_target = QuarantineItem(
            tenant_id=tenant_id,
            collection_id=collection_id,
            collection_file_id=file_id,
            reason_code="TERMINAL_GUARD",
            status="open",
            evidence={"finding_code": "TERMINAL_GUARD"},
        )
        session.add_all((low, high, terminal_target))
        await session.commit()
        low_id, high_id, terminal_id = low.id, high.id, terminal_target.id

    review_findings = await client.get(
        f"/v1/collections/{collection_id}/integrity/findings",
        params={"target_type": "review_item"},
    )
    assert review_findings.status_code == 200, review_findings.text
    by_id = {item["target_id"]: item for item in review_findings.json()["items"]}
    assert by_id[str(low_id)]["allowed_actions"] == ["exclude", "override"]
    assert by_id[str(high_id)]["allowed_actions"] == ["exclude"]
    assert by_id[str(low_id)]["category"] == "ambiguous_layout"
    assert by_id[str(high_id)]["severity"] == "high"
    assert "review target evidence" not in review_findings.text.casefold()

    unsupported_exclude = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-review-exclude-unavailable"},
        json={
            "target_type": "review_item",
            "target_id": str(low_id),
            "action": "exclude",
            "reason_code": "EXCLUDED_FROM_OUTPUT",
        },
    )
    assert unsupported_exclude.status_code == 201, unsupported_exclude.text
    assert unsupported_exclude.json()["execution"]["status"] == "completed"

    override = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-safe-override"},
        json={
            "target_type": "review_item",
            "target_id": str(low_id),
            "action": "override",
            "reason_code": "CUSTOMER_OVERRIDE_APPROVED",
            "acknowledge_override": True,
            "evidence_reference": {"kind": "artifact_sha256", "sha256": "b" * 64},
        },
    )
    assert override.status_code == 409, override.text
    assert override.json()["error"]["code"] == "INTEGRITY_FINDING_NOT_OPEN"

    unsafe_override = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-unsafe-override"},
        json={
            "target_type": "review_item",
            "target_id": str(high_id),
            "action": "override",
            "reason_code": "CUSTOMER_OVERRIDE_APPROVED",
            "acknowledge_override": True,
            "evidence_reference": {"kind": "artifact_sha256", "sha256": "c" * 64},
        },
    )
    assert unsafe_override.status_code == 403, unsafe_override.text
    assert unsafe_override.json()["error"]["code"] == "INTEGRITY_OVERRIDE_FORBIDDEN"

    async with app.state.database.sessions() as session:
        collection = await session.get(Collection, collection_id)
        assert collection is not None
        collection.status = "COMPLETED"
        await session.commit()
    terminal_findings = await client.get(
        f"/v1/collections/{collection_id}/integrity/findings",
        params={"target_type": "quarantine_item"},
    )
    assert terminal_findings.status_code == 200, terminal_findings.text
    terminal_finding = next(
        item for item in terminal_findings.json()["items"] if item["target_id"] == str(terminal_id)
    )
    assert terminal_finding["allowed_actions"] == []
    terminal = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-terminal-guard"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(terminal_id),
            "action": "exclude",
            "reason_code": "EXCLUDED_FROM_OUTPUT",
        },
    )
    assert terminal.status_code == 409, terminal.text
    assert terminal.json()["error"]["code"] == "COLLECTION_INTEGRITY_DECISION_UNSAFE_STATE"

    async with app.state.database.sessions() as session:
        collection = await session.get(Collection, collection_id)
        assert collection is not None
        collection.status = "QUARANTINED"
        job = ProcessingJob(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=None,
            job_type="collection_process",
            status="paused",
        )
        session.add(job)
        await session.flush()
        session.add(
            ArchitecturePlan(
                tenant_id=tenant_id,
                collection_id=collection_id,
                processing_job_id=job.id,
                plan_version=1,
                status="planned",
                input_integrity_sha256="d" * 64,
                plan={"scope": "active-state-guard"},
                created_by=uuid.UUID(owner["user_id"]),
            )
        )
        await session.commit()
        active_job_id = job.id

    active = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-active-guard"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(terminal_id),
            "action": "exclude",
            "reason_code": "EXCLUDED_FROM_OUTPUT",
        },
    )
    assert active.status_code == 409, active.text
    assert active.json()["error"]["code"] == "COLLECTION_INTEGRITY_PROCESSING_ACTIVE"

    async with app.state.database.sessions() as session:
        job = await session.get(ProcessingJob, active_job_id)
        assert job is not None
        job.status = "running"
        await session.commit()

    running = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-running-guard"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(terminal_id),
            "action": "exclude",
            "reason_code": "EXCLUDED_FROM_OUTPUT",
        },
    )
    assert running.status_code == 409, running.text
    assert running.json()["error"]["code"] == "COLLECTION_INTEGRITY_PROCESSING_ACTIVE"

    async with app.state.database.sessions() as session:
        high = await session.get(ReviewItem, high_id)
        terminal_target = await session.get(QuarantineItem, terminal_id)
        assert high is not None and high.status == "open"
        assert terminal_target is not None and terminal_target.status == "open"


async def test_review_decisions_are_collection_scoped_for_shared_sources(
    integrity_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = integrity_api
    owner = await _register(
        client,
        email="integrity.shared-review@example.com",
        tenant_name="Integrity Shared Review Tenant",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    project_id_raw = await _project(client, prefix="shared-review")
    project_id = uuid.UUID(project_id_raw)
    content = b"shared review evidence"
    collection_a_raw, file_a_raw = await _collection_file(
        client,
        project_id=project_id_raw,
        prefix="shared-review-a",
        content=content,
    )
    collection_b_raw, file_b_raw = await _collection_file(
        client,
        project_id=project_id_raw,
        prefix="shared-review-b",
        content=content,
    )
    uploaded = await _legacy_upload(
        client,
        project_id=project_id_raw,
        prefix="shared-review-source",
        content=content,
    )
    collection_a_id = uuid.UUID(collection_a_raw)
    collection_b_id = uuid.UUID(collection_b_raw)
    source_id = uuid.UUID(uploaded["source_file_id"])
    document_id = uuid.UUID(uploaded["document_id"])

    async with app.state.database.sessions() as session:
        collection_a = await session.get(Collection, collection_a_id)
        collection_b = await session.get(Collection, collection_b_id)
        file_a = await session.get(CollectionFile, uuid.UUID(file_a_raw))
        file_b = await session.get(CollectionFile, uuid.UUID(file_b_raw))
        source = await session.get(SourceFile, source_id)
        assert all(row is not None for row in (collection_a, collection_b, file_a, file_b, source))
        assert collection_a is not None and collection_b is not None
        assert file_a is not None and file_b is not None and source is not None
        collection_a.status = "UNRESOLVED"
        collection_b.status = "UNRESOLVED"
        file_a.source_file_id = source.id
        file_b.source_file_id = source.id
        source.antivirus_status = "clean"
        review = ReviewItem(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=document_id,
            severity="medium",
            category="ambiguous_layout",
            status="open",
            evidence={"finding_code": "AMBIGUOUS_LAYOUT"},
        )
        session.add(review)
        await session.commit()
        review_id = review.id

    for collection_id in (collection_a_id, collection_b_id):
        findings = await client.get(
            f"/v1/collections/{collection_id}/integrity/findings",
            params={"target_type": "review_item"},
        )
        assert findings.status_code == 200, findings.text
        assert [row["target_id"] for row in findings.json()["items"]] == [str(review_id)]

    payload = {
        "target_type": "review_item",
        "target_id": str(review_id),
        "action": "override",
        "reason_code": "CUSTOMER_OVERRIDE_APPROVED",
        "acknowledge_override": True,
        "evidence_reference": {"kind": "artifact_sha256", "sha256": "d" * 64},
    }
    async with app.state.database.sessions() as session:
        session.add(
            CollectionIntegrityDecision(
                tenant_id=tenant_id,
                collection_id=collection_a_id,
                review_item_id=review_id,
                action="override",
                reason_code="CUSTOMER_OVERRIDE_APPROVED",
                evidence_reference={"kind": "artifact_sha256", "sha256": "d" * 64},
                previous_status="open",
                resulting_status="resolved",
                override_applied=True,
                request_sha256="a" * 64,
                actor_id=uuid.UUID(owner["user_id"]),
            )
        )
        await session.commit()

    findings_a = await client.get(
        f"/v1/collections/{collection_a_id}/integrity/findings",
        params={"target_type": "review_item"},
    )
    findings_b = await client.get(
        f"/v1/collections/{collection_b_id}/integrity/findings",
        params={"target_type": "review_item"},
    )
    assert findings_a.status_code == findings_b.status_code == 200
    assert findings_a.json()["items"] == []
    assert [row["target_id"] for row in findings_b.json()["items"]] == [str(review_id)]

    duplicate_a = await client.post(
        f"/v1/collections/{collection_a_id}/integrity/decisions",
        headers={"Idempotency-Key": "shared-review-a-override-again"},
        json=payload,
    )
    assert duplicate_a.status_code == 409, duplicate_a.text
    assert duplicate_a.json()["error"]["code"] == "INTEGRITY_FINDING_NOT_OPEN"

    decided_b = await client.post(
        f"/v1/collections/{collection_b_id}/integrity/decisions",
        headers={"Idempotency-Key": "shared-review-b-override"},
        json=payload,
    )
    assert decided_b.status_code == 201, decided_b.text
    assert decided_b.json()["execution"]["result_code"] == "CUSTOMER_OVERRIDE_APPLIED"
    async with app.state.database.sessions() as session:
        review = await session.get(ReviewItem, review_id)
        assert review is not None
        assert review.status == "open"
        assert review.resolution is None
        decisions = list(
            await session.scalars(
                select(CollectionIntegrityDecision).where(
                    CollectionIntegrityDecision.tenant_id == tenant_id,
                    CollectionIntegrityDecision.review_item_id == review_id,
                )
            )
        )
        assert {row.collection_id for row in decisions} == {
            collection_a_id,
            collection_b_id,
        }
        await session.delete(review)
        await session.commit()

    # Projection refresh may replace ReviewItem rows.  Immutable customer
    # decisions retain the opaque target id until their collection is purged.
    retained = await client.get(
        f"/v1/collections/{collection_a_id}/integrity/decisions",
        params={"target_type": "review_item", "target_id": str(review_id)},
    )
    assert retained.status_code == 200, retained.text
    assert [row["target_id"] for row in retained.json()["items"]] == [str(review_id)]


async def test_unwired_password_and_corrected_source_actions_fail_closed(
    integrity_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = integrity_api
    owner = await _register(
        client,
        email="integrity.references@example.com",
        tenant_name="Integrity Reference Tenant",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    project_id_raw = await _project(client, prefix="references")
    content = b"corrected source"
    collection_id_raw, file_id_raw = await _collection_file(
        client,
        project_id=project_id_raw,
        prefix="references",
        content=content,
    )
    collection_id = uuid.UUID(collection_id_raw)
    file_id = uuid.UUID(file_id_raw)
    uploaded = await _legacy_upload(
        client,
        project_id=project_id_raw,
        prefix="references",
        content=content,
    )
    source_id = uuid.UUID(uploaded["source_file_id"])
    digest = hashlib.sha256(content).hexdigest()

    async with app.state.database.sessions() as session:
        collection = await session.get(Collection, collection_id)
        collection_file = await session.get(CollectionFile, file_id)
        source = await session.get(SourceFile, source_id)
        assert collection is not None and collection_file is not None and source is not None
        collection.status = "QUARANTINED"
        collection_file.source_file_id = source.id
        collection_file.status = "password_required"
        source.antivirus_status = "clean"
        password_target = QuarantineItem(
            tenant_id=tenant_id,
            collection_id=collection_id,
            collection_file_id=file_id,
            reason_code="PASSWORD_REQUIRED",
            status="open",
            evidence={"finding_code": "PASSWORD_REQUIRED"},
        )
        corrected_target = QuarantineItem(
            tenant_id=tenant_id,
            collection_id=collection_id,
            collection_file_id=file_id,
            reason_code="SOURCE_CORRECTION_REQUIRED",
            status="open",
            evidence={"finding_code": "SOURCE_CORRECTION_REQUIRED"},
        )
        session.add_all((password_target, corrected_target))
        await session.commit()
        password_id, corrected_id = password_target.id, corrected_target.id

    reference_findings = await client.get(
        f"/v1/collections/{collection_id}/integrity/findings",
        params={"target_type": "quarantine_item"},
    )
    assert reference_findings.status_code == 200, reference_findings.text
    reference_by_id = {item["target_id"]: item for item in reference_findings.json()["items"]}
    assert "provide_password" not in reference_by_id[str(password_id)]["allowed_actions"]
    assert "provide_password" not in reference_by_id[str(corrected_id)]["allowed_actions"]
    assert "correct_source" not in reference_by_id[str(corrected_id)]["allowed_actions"]

    password_payload = {
        "target_type": "quarantine_item",
        "target_id": str(password_id),
        "action": "provide_password",
        "reason_code": "ENCRYPTED_PDF_SECRET_SUBMITTED",
        "evidence_reference": {
            "kind": "analysis_task",
            "reference_id": str(uuid.uuid4()),
        },
    }
    supplied = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-password-unavailable"},
        json=password_payload,
    )
    assert supplied.status_code == 409, supplied.text
    assert supplied.json()["error"]["code"] == "INTEGRITY_ACTION_NOT_EXECUTABLE"

    corrected = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-corrected-source"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(corrected_id),
            "action": "correct_source",
            "reason_code": "CORRECTED_SOURCE_SUBMITTED",
            "evidence_reference": {
                "kind": "source_file",
                "reference_id": str(source_id),
                "sha256": digest,
            },
        },
    )
    assert corrected.status_code == 409, corrected.text
    assert corrected.json()["error"]["code"] == "INTEGRITY_ACTION_NOT_EXECUTABLE"

    invalid_reference = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-invalid-source"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(uuid.uuid4()),
            "action": "correct_source",
            "reason_code": "CORRECTED_SOURCE_SUBMITTED",
            "evidence_reference": {
                "kind": "source_file",
                "reference_id": str(source_id),
                "sha256": "0" * 64,
            },
        },
    )
    assert invalid_reference.status_code == 404, invalid_reference.text


async def test_retry_new_engine_is_bounded_pinned_and_reconciled(
    integrity_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = integrity_api
    owner = await _register(
        client,
        email="integrity.retry-runtime@example.com",
        tenant_name="Integrity Retry Runtime Tenant",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    project_id_raw = await _project(client, prefix="retry-runtime")
    project_id = uuid.UUID(project_id_raw)
    content = b"retry runtime source"
    collection_id_raw, file_id_raw = await _collection_file(
        client,
        project_id=project_id_raw,
        prefix="retry-runtime",
        content=content,
    )
    uploaded = await _legacy_upload(
        client,
        project_id=project_id_raw,
        prefix="retry-runtime",
        content=content,
    )
    collection_id = uuid.UUID(collection_id_raw)
    file_id = uuid.UUID(file_id_raw)
    source_id = uuid.UUID(uploaded["source_file_id"])
    document_id = uuid.UUID(uploaded["document_id"])

    async with app.state.database.sessions() as session:
        collection = await session.get(Collection, collection_id)
        collection_file = await session.get(CollectionFile, file_id)
        source = await session.get(SourceFile, source_id)
        document = await session.get(Document, document_id)
        assert all(row is not None for row in (collection, collection_file, source, document))
        assert collection is not None and collection_file is not None
        assert source is not None and document is not None
        collection.status = "QUARANTINED"
        collection_file.source_file_id = source.id
        collection_file.status = "quarantined"
        page = Page(
            tenant_id=tenant_id,
            document_id=document.id,
            page_number=1,
            status="NEEDS_REVIEW",
            route="paddle_vl",
            route_policy_version="integrity-old-policy",
            preflight_metrics={},
            quality_metrics={},
        )
        session.add(page)
        await session.flush()
        session.add(
            PageAsset(
                tenant_id=tenant_id,
                page_id=page.id,
                asset_type="inference_raster",
                storage_key=f"integrity/{page.id}/raster.png",
                sha256="9" * 64,
                metadata_json={"width_px": 1200, "height_px": 1600, "dpi": 200},
            )
        )
        registry = ModelRegistry(
            endpoint="paddle_vl_integrity",
            model_id="paddle.ocrvl.integrity",
            revision="1" * 40,
            runtime_image_digest=f"sha256:{'2' * 64}",
            adapter_version="adapter.v1",
            policy_version="integrity-policy-v1",
            benchmark_report="benchmark:integrity-retry-v1",
            benchmark_sha256=f"sha256:{'3' * 64}",
            recipe_sha256=f"sha256:{'4' * 64}",
            enabled=True,
            canary_percent=100,
            lifecycle_state="champion",
            generation=1,
        )
        target = QuarantineItem(
            tenant_id=tenant_id,
            collection_id=collection_id,
            collection_file_id=file_id,
            page_id=page.id,
            reason_code="CUSTOMER_REVIEW_REQUIRED",
            status="open",
            evidence={"finding_code": "CUSTOMER_REVIEW_REQUIRED"},
        )
        active_attempt = PageAttempt(
            tenant_id=tenant_id,
            page_id=page.id,
            attempt_number=1,
            trigger="analysis",
            status="OCR_RUNNING",
            route=Route.PADDLE_VL.value,
            route_profile="parse_balanced_v1",
            route_policy_version="integrity-old-policy",
            max_attempts=1,
        )
        session.add_all((registry, target, active_attempt))
        await session.commit()
        target_id = target.id
        registry_id = registry.id
        page_id = page.id
        active_attempt_id = active_attempt.id

    busy_findings = await client.get(
        f"/v1/collections/{collection_id}/integrity/findings",
        params={"target_type": "quarantine_item"},
    )
    assert busy_findings.status_code == 200, busy_findings.text
    busy_finding = next(
        row
        for row in busy_findings.json()["items"]
        if row["target_id"] == str(target_id)
    )
    assert "retry_new_engine" not in busy_finding["allowed_actions"]

    async with app.state.database.sessions() as session:
        active_attempt = await session.get(PageAttempt, active_attempt_id)
        assert active_attempt is not None
        active_attempt.status = "FAILED"
        active_attempt.completed_at = utcnow()
        await session.commit()

    findings = await client.get(
        f"/v1/collections/{collection_id}/integrity/findings",
        params={"target_type": "quarantine_item"},
    )
    assert findings.status_code == 200, findings.text
    finding = next(
        row for row in findings.json()["items"] if row["target_id"] == str(target_id)
    )
    assert "retry_new_engine" in finding["allowed_actions"]
    evidence = finding["action_evidence"]["retry_new_engine"][0]
    assert evidence["reference_id"] is None
    assert evidence["revision"] == "1" * 40

    queued = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-retry-runtime"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(target_id),
            "action": "retry_new_engine",
            "reason_code": "RETRY_WITH_APPROVED_ENGINE",
            "evidence_reference": evidence,
        },
    )
    assert queued.status_code == 201, queued.text
    queued_body = queued.json()
    assert queued_body["execution"]["status"] == "queued"
    assert queued_body["execution"]["registry_model_id"] == str(registry_id)
    job_id = uuid.UUID(queued_body["execution"]["processing_job_id"])

    async with app.state.database.sessions() as session:
        job = await session.get(ProcessingJob, job_id)
        execution = await session.get(
            CollectionIntegrityActionExecution,
            uuid.UUID(queued_body["execution"]["id"]),
        )
        assert job is not None and execution is not None
        assert job.status == "queued"
        assert job.job_type == "collection_integrity_retry"
        assert job.requested_options["page_ids"] == [str(page_id)]
        assert job.requested_options["bounded_retry_only"] is True
        assert job.requested_options["external_processing_consent"] is False
        assert job.cost_estimate["reserved"] == "0.000000"
        assert job.cost_estimate["hard_cap"] == "0.000000"
        assert job.cost_actual["credits"] == "0.000000"
        attempts = list(
            await session.scalars(
                select(PageAttempt).where(PageAttempt.job_id == job.id)
            )
        )
        assert len(attempts) == 1
        assert attempts[0].page_id == page_id
        assert attempts[0].max_attempts == 1
        assert attempts[0].route == Route.PADDLE_VL.value
        outbox = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == job.id,
                OutboxEvent.event_type == "job.dispatch.requested.v1",
            )
        )
        assert outbox is not None
        runtime = await load_routing_runtime(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            requested_route_profile="precision",
        )
        binding = await resolve_pinned_retry_binding(
            session,
            job=job,
            runtime=runtime,
            route=Route.PADDLE_VL,
        )
        assert binding.model_revision == "1" * 40

        job.status = "running"
        job.started_at = utcnow()
        await reconcile_integrity_retry_job(session, job_id=job.id)
        await session.refresh(execution)
        assert execution.status == "running"
        assert execution.result_code == "INTEGRITY_RETRY_RUNNING"

        registry = await session.get(ModelRegistry, registry_id)
        assert registry is not None
        registry.enabled = False
        await session.flush()
        drifted_runtime = await load_routing_runtime(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            requested_route_profile="precision",
        )
        with pytest.raises(IntegrityActionRejected, match="INTEGRITY_RETRY_REGISTRY_DRIFT"):
            await resolve_pinned_retry_binding(
                session,
                job=job,
                runtime=drifted_runtime,
                route=Route.PADDLE_VL,
            )

        job.status = "completed"
        job.started_at = job.started_at or utcnow()
        job.completed_at = utcnow()
        attempts[0].status = "COMPLETED"
        attempts[0].completed_at = utcnow()
        await reconcile_integrity_retry_job(session, job_id=job.id)

    async with app.state.database.sessions() as session:
        execution = await session.get(
            CollectionIntegrityActionExecution,
            uuid.UUID(queued_body["execution"]["id"]),
        )
        target = await session.get(QuarantineItem, target_id)
        collection = await session.get(Collection, collection_id)
        assert execution is not None and execution.status == "completed"
        assert execution.result_code == "INTEGRITY_RETRY_COMPLETED"
        assert execution.result["credits"] == "0.000000"
        assert target is not None and target.status == "resolved"
        assert collection is not None and collection.status == "PARTIAL"
        assert collection.status_reason == "INTEGRITY_RETRY_COMPLETED_RECOMPILE_REQUIRED"


async def test_password_action_requires_audited_task_binding_and_reconciles(
    integrity_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = integrity_api
    owner = await _register(
        client,
        email="integrity.password-runtime@example.com",
        tenant_name="Integrity Password Runtime Tenant",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    user_id = uuid.UUID(owner["user_id"])
    project_id_raw = await _project(client, prefix="password-runtime")
    project_id = uuid.UUID(project_id_raw)
    content = b"password-bound source"
    collection_id_raw, file_id_raw = await _collection_file(
        client,
        project_id=project_id_raw,
        prefix="password-runtime",
        content=content,
    )
    uploaded = await _legacy_upload(
        client,
        project_id=project_id_raw,
        prefix="password-runtime",
        content=content,
    )
    collection_id = uuid.UUID(collection_id_raw)
    file_id = uuid.UUID(file_id_raw)
    source_id = uuid.UUID(uploaded["source_file_id"])
    document_id = uuid.UUID(uploaded["document_id"])

    async with app.state.database.sessions() as session:
        collection = await session.get(Collection, collection_id)
        collection_file = await session.get(CollectionFile, file_id)
        source = await session.get(SourceFile, source_id)
        document = await session.get(Document, document_id)
        assert all(row is not None for row in (collection, collection_file, source, document))
        assert collection is not None and collection_file is not None
        assert source is not None and document is not None
        collection.status = "QUARANTINED"
        collection_file.source_file_id = source.id
        collection_file.status = "password_required"
        task = AnalysisTask(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=document.id,
            document_version=document.active_version,
            source_file_id=source.id,
            requested_by=user_id,
            status="queued",
        )
        target = QuarantineItem(
            tenant_id=tenant_id,
            collection_id=collection_id,
            collection_file_id=file_id,
            reason_code="PASSWORD_REQUIRED",
            status="open",
            evidence={"finding_code": "PASSWORD_REQUIRED"},
        )
        session.add_all((task, target))
        await session.flush()
        session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_id=user_id,
                action="document.pdf_password_submitted",
                target_type="document",
                target_id=str(document.id),
                metadata_json={"task_id": str(task.id), "source_sha256": source.sha256},
            )
        )
        await session.commit()
        task_id = task.id
        target_id = target.id

    findings = await client.get(
        f"/v1/collections/{collection_id}/integrity/findings",
        params={"target_type": "quarantine_item"},
    )
    assert findings.status_code == 200, findings.text
    finding = next(
        row for row in findings.json()["items"] if row["target_id"] == str(target_id)
    )
    assert "provide_password" in finding["allowed_actions"]
    assert finding["action_evidence"]["provide_password"] == [
        {"kind": "analysis_task", "reference_id": str(task_id), "sha256": None, "revision": None}
    ]

    wrong_binding = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-password-wrong-binding"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(target_id),
            "action": "provide_password",
            "reason_code": "ENCRYPTED_PDF_SECRET_SUBMITTED",
            "evidence_reference": {
                "kind": "analysis_task",
                "reference_id": str(uuid.uuid4()),
            },
        },
    )
    assert wrong_binding.status_code == 409, wrong_binding.text
    assert wrong_binding.json()["error"]["code"] == "INTEGRITY_PASSWORD_TASK_BINDING_INVALID"

    linked = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-password-runtime"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(target_id),
            "action": "provide_password",
            "reason_code": "ENCRYPTED_PDF_SECRET_SUBMITTED",
            "evidence_reference": {
                "kind": "analysis_task",
                "reference_id": str(task_id),
            },
        },
    )
    assert linked.status_code == 201, linked.text
    linked_body = linked.json()
    assert linked_body["execution"]["status"] == "queued"
    assert linked_body["execution"]["analysis_task_id"] == str(task_id)
    execution_id = uuid.UUID(linked_body["execution"]["id"])

    async with app.state.database.sessions() as session:
        task = await session.get(AnalysisTask, task_id)
        execution = await session.get(CollectionIntegrityActionExecution, execution_id)
        assert task is not None and execution is not None
        task.status = "running"
        task.started_at = utcnow()
        await reconcile_collection_analysis_task(session, task=task)
        await session.flush()
        assert execution.status == "running"
        assert execution.result_code == "INTEGRITY_PASSWORD_ANALYSIS_RUNNING"

        task.status = "completed"
        task.page_count = 2
        task.block_count = 7
        task.completed_at = utcnow()
        await reconcile_collection_analysis_task(session, task=task)
        await session.commit()

    async with app.state.database.sessions() as session:
        execution = await session.get(CollectionIntegrityActionExecution, execution_id)
        target = await session.get(QuarantineItem, target_id)
        collection = await session.get(Collection, collection_id)
        collection_file = await session.get(CollectionFile, file_id)
        assert execution is not None and execution.status == "completed"
        assert execution.result_code == "INTEGRITY_PASSWORD_ANALYSIS_COMPLETED"
        assert execution.result["page_count"] == 2
        assert execution.result["block_count"] == 7
        assert target is not None and target.status == "resolved"
        assert collection is not None and collection.status == "PARTIAL"
        assert collection_file is not None and collection_file.status == "verified"


async def test_correct_source_versions_only_the_target_collection_and_invalidates_outputs(
    integrity_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = integrity_api
    owner = await _register(
        client,
        email="integrity.correct-source@example.com",
        tenant_name="Integrity Correct Source Tenant",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    user_id = uuid.UUID(owner["user_id"])
    project_id_raw = await _project(client, prefix="correct-source")
    original = b"shared original source"
    replacement = b"clean corrected source"
    collection_a_raw, file_a_raw = await _collection_file(
        client,
        project_id=project_id_raw,
        prefix="correct-source-a",
        content=original,
    )
    collection_b_raw, file_b_raw = await _collection_file(
        client,
        project_id=project_id_raw,
        prefix="correct-source-b",
        content=original,
    )
    original_upload = await _legacy_upload(
        client,
        project_id=project_id_raw,
        prefix="correct-source-original",
        content=original,
    )
    replacement_upload = await _legacy_upload(
        client,
        project_id=project_id_raw,
        prefix="correct-source-replacement",
        content=replacement,
    )
    other_project_raw = await _project(client, prefix="correct-source-other-project")
    other_upload = await _legacy_upload(
        client,
        project_id=other_project_raw,
        prefix="correct-source-other-project",
        content=b"other project clean source",
    )
    collection_a_id = uuid.UUID(collection_a_raw)
    collection_b_id = uuid.UUID(collection_b_raw)
    file_a_id = uuid.UUID(file_a_raw)
    file_b_id = uuid.UUID(file_b_raw)
    original_source_id = uuid.UUID(original_upload["source_file_id"])
    original_document_id = uuid.UUID(original_upload["document_id"])
    replacement_source_id = uuid.UUID(replacement_upload["source_file_id"])
    replacement_sha = hashlib.sha256(replacement).hexdigest()
    other_source_id = uuid.UUID(other_upload["source_file_id"])
    other_sha = hashlib.sha256(b"other project clean source").hexdigest()

    async with app.state.database.sessions() as session:
        collection_a = await session.get(Collection, collection_a_id)
        collection_b = await session.get(Collection, collection_b_id)
        file_a = await session.get(CollectionFile, file_a_id)
        file_b = await session.get(CollectionFile, file_b_id)
        source = await session.get(SourceFile, original_source_id)
        replacement_source = await session.get(SourceFile, replacement_source_id)
        other_source = await session.get(SourceFile, other_source_id)
        assert all(
            row is not None
            for row in (
                collection_a,
                collection_b,
                file_a,
                file_b,
                source,
                replacement_source,
                other_source,
            )
        )
        assert collection_a is not None and collection_b is not None
        assert file_a is not None and file_b is not None and source is not None
        assert replacement_source is not None and other_source is not None
        collection_a.status = "QUARANTINED"
        collection_b.status = "INGESTED"
        replacement_source.antivirus_status = "clean"
        other_source.antivirus_status = "clean"
        file_a.source_file_id = source.id
        file_a.status = "quarantined"
        file_b.source_file_id = source.id
        file_b.status = "verified"
        versions = list(
            await session.scalars(
                select(FileVersion).where(FileVersion.collection_file_id == file_a.id)
            )
        )
        assert len(versions) == 1
        versions[0].status = "active"
        plan = ArchitecturePlan(
            tenant_id=tenant_id,
            collection_id=collection_a.id,
            plan_version=1,
            status="planned",
            input_integrity_sha256="8" * 64,
            plan={"scope": "correct-source-invalidation"},
            created_by=user_id,
        )
        target = QuarantineItem(
            tenant_id=tenant_id,
            collection_id=collection_a.id,
            collection_file_id=file_a.id,
            reason_code="SOURCE_CORRECTION_REQUIRED",
            status="open",
            evidence={"finding_code": "SOURCE_CORRECTION_REQUIRED"},
        )
        session.add_all((plan, target))
        original_manifest_revision = collection_a.manifest_revision
        await session.commit()
        target_id = target.id
        plan_id = plan.id

    findings = await client.get(
        f"/v1/collections/{collection_a_id}/integrity/findings",
        params={"target_type": "quarantine_item"},
    )
    assert findings.status_code == 200, findings.text
    finding = next(
        row for row in findings.json()["items"] if row["target_id"] == str(target_id)
    )
    assert "correct_source" in finding["allowed_actions"]
    candidate_ids = {
        row["reference_id"] for row in finding["action_evidence"]["correct_source"]
    }
    assert str(replacement_source_id) in candidate_ids
    assert str(other_source_id) not in candidate_ids

    cross_project = await client.post(
        f"/v1/collections/{collection_a_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-correct-source-cross-project"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(target_id),
            "action": "correct_source",
            "reason_code": "CORRECTED_SOURCE_SUBMITTED",
            "evidence_reference": {
                "kind": "source_file",
                "reference_id": str(other_source_id),
                "sha256": other_sha,
            },
        },
    )
    assert cross_project.status_code == 409, cross_project.text
    assert cross_project.json()["error"]["code"] == "INTEGRITY_CORRECTED_SOURCE_INVALID"

    corrected = await client.post(
        f"/v1/collections/{collection_a_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-correct-source-runtime"},
        json={
            "target_type": "quarantine_item",
            "target_id": str(target_id),
            "action": "correct_source",
            "reason_code": "CORRECTED_SOURCE_SUBMITTED",
            "evidence_reference": {
                "kind": "source_file",
                "reference_id": str(replacement_source_id),
                "sha256": replacement_sha,
            },
        },
    )
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["execution"]["status"] == "completed"
    assert corrected.json()["execution"]["result_code"] == "CORRECTED_SOURCE_APPLIED"

    async with app.state.database.sessions() as session:
        collection_a = await session.get(Collection, collection_a_id)
        file_a = await session.get(CollectionFile, file_a_id)
        file_b = await session.get(CollectionFile, file_b_id)
        original_source = await session.get(SourceFile, original_source_id)
        original_document = await session.get(Document, original_document_id)
        plan = await session.get(ArchitecturePlan, plan_id)
        versions = list(
            await session.scalars(
                select(FileVersion)
                .where(FileVersion.collection_file_id == file_a_id)
                .order_by(FileVersion.version_number)
            )
        )
        assert collection_a is not None and collection_a.status == "PARTIAL"
        assert collection_a.manifest_revision == original_manifest_revision + 1
        assert file_a is not None and file_a.source_file_id == replacement_source_id
        assert file_a.sha256 == replacement_sha
        assert file_a.status == "verified"
        assert [row.status for row in versions] == ["superseded", "active"]
        assert versions[-1].source_sha256 == replacement_sha
        assert plan is not None and plan.status == "stale"
        assert original_source is not None
        assert original_document is not None
        assert original_document.source_file_id == original_source_id
        assert file_b is not None and file_b.source_file_id == original_source_id


async def test_completed_exclusion_is_applied_to_direct_package_materialization(
    integrity_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = integrity_api
    owner = await _register(
        client,
        email="integrity.package-projection@example.com",
        tenant_name="Integrity Package Projection Tenant",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    user_id = uuid.UUID(owner["user_id"])
    project_id_raw = await _project(client, prefix="package-projection")
    content = b"package projection source"
    collection_id_raw, file_id_raw = await _collection_file(
        client,
        project_id=project_id_raw,
        prefix="package-projection",
        content=content,
    )
    uploaded = await _legacy_upload(
        client,
        project_id=project_id_raw,
        prefix="package-projection",
        content=content,
    )
    collection_id = uuid.UUID(collection_id_raw)
    file_id = uuid.UUID(file_id_raw)
    source_id = uuid.UUID(uploaded["source_file_id"])
    document_id = uuid.UUID(uploaded["document_id"])

    async with app.state.database.sessions() as session:
        collection = await session.get(Collection, collection_id)
        collection_file = await session.get(CollectionFile, file_id)
        source = await session.get(SourceFile, source_id)
        document = await session.get(Document, document_id)
        assert all(row is not None for row in (collection, collection_file, source, document))
        assert collection is not None and collection_file is not None
        assert source is not None and document is not None
        collection.status = "UNRESOLVED"
        collection_file.source_file_id = source.id
        collection_file.status = "verified"
        document.status = "COMPLETED"
        document.page_count = 1
        page = Page(
            tenant_id=tenant_id,
            document_id=document.id,
            page_number=1,
            width_pt=612,
            height_pt=792,
            status="COMPLETED",
            route="native",
            route_policy_version="package-projection-v1",
        )
        session.add(page)
        await session.flush()
        block = Block(
            tenant_id=tenant_id,
            document_id=document.id,
            page_id=page.id,
            block_order=0,
            block_type="paragraph",
            origin="native_text",
            bbox1000=[10, 10, 990, 100],
            source_text="Package projection evidence.",
            normalized_text="Package projection evidence.",
            markdown="Package projection evidence.",
            engine="native",
            engine_revision="package-projection-v1",
            confidence=1.0,
            content_hash=hashlib.sha256(b"Package projection evidence.").hexdigest(),
        )
        session.add(block)
        await session.flush()
        review = ReviewItem(
            tenant_id=tenant_id,
            project_id=uuid.UUID(project_id_raw),
            document_id=document.id,
            page_id=page.id,
            block_id=block.id,
            severity="medium",
            category="ambiguous_layout",
            status="open",
            evidence={"finding_code": "AMBIGUOUS_LAYOUT"},
        )
        plan = ArchitecturePlan(
            tenant_id=tenant_id,
            collection_id=collection.id,
            plan_version=1,
            status="planned",
            input_integrity_sha256="7" * 64,
            plan={"scope": "direct-package-projection"},
            created_by=user_id,
        )
        session.add_all((review, plan))
        await session.commit()
        review_id = review.id
        plan_id = plan.id
        block_id = block.id

    excluded = await client.post(
        f"/v1/collections/{collection_id}/integrity/decisions",
        headers={"Idempotency-Key": "integrity-package-exclude"},
        json={
            "target_type": "review_item",
            "target_id": str(review_id),
            "action": "exclude",
            "reason_code": "EXCLUDED_FROM_OUTPUT",
        },
    )
    assert excluded.status_code == 201, excluded.text
    assert excluded.json()["execution"]["status"] == "completed"

    async with app.state.database.sessions() as session:
        collection = await session.get(Collection, collection_id)
        collection_file = await session.get(CollectionFile, file_id)
        plan = await session.get(ArchitecturePlan, plan_id)
        assert collection is not None and collection_file is not None and plan is not None
        events = list(
            await session.scalars(
                select(CollectionEvent)
                .where(CollectionEvent.collection_id == collection.id)
                .order_by(CollectionEvent.sequence)
            )
        )
        groups, counts = await _complete_knowledge_groups(
            session,
            codec=app.state.collection_metadata_codec,
            collection=collection,
            plan=plan,
            collection_files=[collection_file],
            event_rows=events,
            integrity={
                "integrity_sha256": "6" * 64,
                "verification_status_counts": {"verified": 1},
            },
        )
        review = await session.get(ReviewItem, review_id)

    canonical = json.loads(groups["canonical"]["model.json"])
    decision_receipt = json.loads(groups["provenance"]["integrity-decisions.json"])
    validation = json.loads(groups["validation"]["report.json"])
    assert counts["blocks"] == 0
    assert canonical["blocks"] == []
    assert all(row["id"] != str(block_id) for row in canonical["blocks"])
    assert canonical["integrity_decisions"][0]["action"] == "exclude"
    assert decision_receipt["decisions"] == canonical["integrity_decisions"]
    assert decision_receipt["decision_set_sha256"] == canonical[
        "integrity_decision_set_sha256"
    ]
    assert validation["checks"]["integrity_decisions_applied"] is True
    assert review is not None and review.status == "open"
