"""API evidence for immutable source replacement and archived version access."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
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
    DocumentVersion,
    Page,
    ProcessingJob,
    ReviewItem,
    Tenant,
    UploadSession,
)
from akc_api.services import credit_entry, run_compile_job
from akc_api.settings import Settings
from sqlalchemy import func, select

_SUPPORT_KEY = "document-version-api-test-support-key"
_PASSWORD = "correct horse battery staple"  # noqa: S105


@pytest_asyncio.fixture
async def version_api(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'document-versions.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=True,
        local_analysis_worker_enabled=True,
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


async def _capture_verification_token(
    client: httpx.AsyncClient,
    email: str,
) -> str:
    captured = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _SUPPORT_KEY},
        json={"email": email},
    )
    assert captured.status_code == 200, captured.text
    return str(captured.json()["token"])


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
            "display_name": "Version Evidence Owner",
            "tenant_name": tenant_name,
        },
    )
    assert registered.status_code == 201, registered.text
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": await _capture_verification_token(client, email)},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def _create_project(client: httpx.AsyncClient, name: str) -> str:
    response = await client.post(
        "/v1/projects",
        headers={"Idempotency-Key": f"project-{uuid.uuid4()}"},
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _upload_payload(
    content: bytes,
    *,
    filename: str,
    project_id: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "filename": filename,
        "size": len(content),
        "content_type": "text/plain",
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    if project_id is not None:
        payload["project_id"] = project_id
    if document_id is not None:
        payload["document_id"] = document_id
    return payload


async def _initiate_upload(
    client: httpx.AsyncClient,
    content: bytes,
    *,
    filename: str,
    project_id: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    initiated = await client.post(
        "/v1/uploads/initiate",
        headers={"Idempotency-Key": f"initiate-{uuid.uuid4()}"},
        json=_upload_payload(
            content,
            filename=filename,
            project_id=project_id,
            document_id=document_id,
        ),
    )
    assert initiated.status_code == 201, initiated.text
    target = initiated.json()
    uploaded = await client.put(
        target["upload_url"],
        content=content,
        headers=target["headers"],
    )
    assert uploaded.status_code == 204, uploaded.text
    return target


async def _complete_upload(
    client: httpx.AsyncClient,
    target: dict[str, Any],
    content: bytes,
) -> dict[str, Any]:
    completed = await client.post(
        f"/v1/uploads/{target['upload_id']}/complete",
        headers={"Idempotency-Key": f"complete-{target['upload_id']}"},
        json={"sha256": hashlib.sha256(content).hexdigest()},
    )
    assert completed.status_code == 200, completed.text
    return completed.json()


async def _upload_source(
    client: httpx.AsyncClient,
    content: bytes,
    *,
    filename: str,
    project_id: str | None = None,
    document_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = await _initiate_upload(
        client,
        content,
        filename=filename,
        project_id=project_id,
        document_id=document_id,
    )
    return target, await _complete_upload(client, target, content)


async def _make_team_plan(app: Any, tenant_id: str) -> None:
    async with app.state.database.sessions.begin() as session:
        tenant = await session.get(Tenant, uuid.UUID(tenant_id))
        assert tenant is not None
        tenant.plan_code = "team"


async def _assert_v1_projection(
    client: httpx.AsyncClient,
    document_id: str,
    *,
    expected_markdown: str,
) -> None:
    document = await client.get(f"/v1/documents/{document_id}")
    assert document.status_code == 200, document.text
    assert document.json()["active_version"] == 1
    blocks = await client.get(f"/v1/documents/{document_id}/blocks")
    assert blocks.status_code == 200, blocks.text
    assert [block["markdown"] for block in blocks.json()] == [expected_markdown]


@pytest.mark.integration
async def test_v2_replacement_archives_exact_v1_and_clears_current_projection(
    version_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = version_api
    owner = await _register(
        client,
        email="version-owner@example.com",
        tenant_name="Immutable Version Evidence",
    )
    await _make_team_plan(app, owner["tenant_id"])
    project_id = await _create_project(client, "Immutable source revisions")
    v1_content = (
        b"# Version one\n\n"
        b"The first source is analyzed and then changed only in the mutable projection.\n"
        b"Every generated knowledge claim preserves an immutable source block reference.\n"
        b"Deterministic native extraction keeps this version suitable for compilation.\n"
    )
    v1_target, v1_completed = await _upload_source(
        client,
        v1_content,
        filename="version-one.txt",
        project_id=project_id,
    )
    document_id = str(v1_target["document_id"])
    assert v1_target["document_version"] == 1
    assert v1_completed["document_version"] == 1

    analyzed = await client.post(f"/v1/documents/{document_id}/analyze")
    assert analyzed.status_code == 202, analyzed.text
    analysis = await client.get(f"/v1/documents/{document_id}/analysis")
    assert analysis.status_code == 200, analysis.text
    assert analysis.json()["status"] == "completed"
    compiled = await client.post(
        f"/v1/documents/{document_id}/compile",
        headers={"Idempotency-Key": "compile-version-one"},
        json={
            "route_profile": "parse_balanced_v1",
            "max_credits": 10,
            "external_processing_consent": False,
            "output_profiles": ["portable"],
        },
    )
    assert compiled.status_code == 202, compiled.text
    version_one_job_id = str(compiled.json()["job_id"])
    active_job_snapshot = await client.get(f"/v1/jobs/{version_one_job_id}")
    assert active_job_snapshot.status_code == 200, active_job_snapshot.text
    job_events = await client.get(f"/v1/jobs/{version_one_job_id}/events/replay")
    assert active_job_snapshot.json()["status"] == "completed", [
        (event["event_type"], event["payload"]) for event in job_events.json()[-4:]
    ]
    assert active_job_snapshot.json()["document_version"] == 1
    assert active_job_snapshot.json()["document"]["version"] == 1

    blocks_response = await client.get(f"/v1/documents/{document_id}/blocks")
    assert blocks_response.status_code == 200, blocks_response.text
    assert len(blocks_response.json()) == 1
    block_id = blocks_response.json()[0]["id"]
    edited_markdown = "Owner-edited version one projection."
    edited = await client.patch(
        f"/v1/blocks/{block_id}",
        headers={
            "If-Match": '"revision-1"',
            "Idempotency-Key": "edit-version-one",
        },
        json={"markdown": edited_markdown, "user_locked": True},
    )
    assert edited.status_code == 200, edited.text

    async with app.state.database.sessions.begin() as session:
        block = await session.get(Block, uuid.UUID(block_id))
        assert block is not None
        review = ReviewItem(
            tenant_id=uuid.UUID(owner["tenant_id"]),
            project_id=uuid.UUID(project_id),
            document_id=uuid.UUID(document_id),
            page_id=block.page_id,
            block_id=block.id,
            severity="high",
            category="source_fidelity",
            status="open",
            evidence={"rule": "manual_version_evidence"},
        )
        session.add(review)
        await session.flush()
        review_id = review.id
    resolved_markdown = "Reviewer-approved version one projection."
    resolved = await client.post(
        f"/v1/review-items/{review_id}/resolve",
        headers={"Idempotency-Key": "resolve-version-one"},
        json={
            "action": "replace",
            "value": resolved_markdown,
            "note": "Validated against the immutable source.",
        },
    )
    assert resolved.status_code == 200, resolved.text
    await _assert_v1_projection(
        client,
        document_id,
        expected_markdown=resolved_markdown,
    )
    v2_content = (
        b"# Version two\n\n"
        b"The replacement source is different and must not mutate version one in place.\n"
    )
    v2_target = await _initiate_upload(
        client,
        v2_content,
        filename="version-two.txt",
        document_id=document_id,
    )
    assert v2_target["document_id"] == document_id
    assert v2_target["document_version"] == 2
    # A staged replacement has no authority over the active projection.
    await _assert_v1_projection(
        client,
        document_id,
        expected_markdown=resolved_markdown,
    )

    v2_completed = await _complete_upload(client, v2_target, v2_content)
    assert v2_completed["document_version"] == 2
    current = await client.get(f"/v1/documents/{document_id}")
    assert current.status_code == 200, current.text
    assert current.json()["active_version"] == 2
    assert current.json()["page_count"] is None
    assert current.json()["status"] == "SECURITY_VERIFIED"
    assert (await client.get(f"/v1/documents/{document_id}/blocks")).json() == []

    versions_response = await client.get(f"/v1/documents/{document_id}/versions")
    assert versions_response.status_code == 200, versions_response.text
    versions_body = versions_response.json()
    assert versions_body["active_version"] == 2
    assert [item["version"] for item in versions_body["versions"]] == [1, 2]
    assert [item["status"] for item in versions_body["versions"]] == [
        "archived",
        "source_verified",
    ]
    serialized_versions = json.dumps(versions_body, sort_keys=True)
    assert "cir_object_key" not in serialized_versions
    assert "storage_key" not in serialized_versions
    assert "archived_objects" not in serialized_versions

    v1_detail = await client.get(f"/v1/documents/{document_id}/versions/1")
    v2_detail = await client.get(f"/v1/documents/{document_id}/versions/2")
    assert v1_detail.status_code == v2_detail.status_code == 200
    assert v1_detail.json()["source_sha256"] == hashlib.sha256(v1_content).hexdigest()
    assert v2_detail.json()["source_sha256"] == hashlib.sha256(v2_content).hexdigest()
    assert v1_detail.json()["cir_snapshot_sha256"] is not None
    assert v2_detail.json()["cir_snapshot_sha256"] is None

    diff = await client.get(
        f"/v1/documents/{document_id}/versions/1/diff",
        params={"to_version": 2},
    )
    assert diff.status_code == 200, diff.text
    assert diff.json()["from_version"] == 1
    assert diff.json()["to_version"] == 2
    assert diff.json()["changes"]["source_sha256"] == {
        "from": hashlib.sha256(v1_content).hexdigest(),
        "to": hashlib.sha256(v2_content).hexdigest(),
    }
    reverse_diff = await client.get(
        f"/v1/documents/{document_id}/versions/2/diff",
        params={"to_version": 1},
    )
    assert reverse_diff.status_code == 422
    assert reverse_diff.json()["error"]["code"] == "DOCUMENT_VERSION_DIFF_ORDER_INVALID"

    snapshot_response = await client.get(f"/v1/documents/{document_id}/versions/1/snapshot")
    assert snapshot_response.status_code == 200, snapshot_response.text
    assert snapshot_response.headers["cache-control"] == "private, no-store"
    snapshot = snapshot_response.json()
    assert snapshot["document_id"] == document_id
    assert snapshot["document_version"] == 1
    assert snapshot["source"]["sha256"] == hashlib.sha256(v1_content).hexdigest()
    assert snapshot["blocks"][0]["markdown"] == resolved_markdown
    archived_review = next(
        item for item in snapshot["review_items"] if item["id"] == str(review_id)
    )
    assert archived_review["status"] == "resolved"
    assert archived_review["resolution"]["value"] == resolved_markdown
    serialized_snapshot = json.dumps(snapshot, sort_keys=True)
    assert "storage_key" not in serialized_snapshot
    assert "thumbnail_key" not in serialized_snapshot
    assert "render_key" not in serialized_snapshot

    # Historical job results remain pinned to v1 after the mutable projection
    # advances to v2; they must never silently render the new active source.
    archived_job_snapshot = await client.get(f"/v1/jobs/{version_one_job_id}")
    assert archived_job_snapshot.status_code == 200, archived_job_snapshot.text
    archived_job = archived_job_snapshot.json()
    assert archived_job["document_version"] == 1
    assert archived_job["document"]["version"] == 1
    assert archived_job["document"]["filename"] == "version-one.txt"
    assert archived_job["pages"][0]["blocks"][0]["markdown"] == resolved_markdown
    assert archived_job["summary"]["completed_pages"] == 1
    assert archived_job["summary"]["knowledge_notes"] == 1

    async with app.state.database.sessions() as session:
        persisted_versions = list(
            (
                await session.scalars(
                    select(DocumentVersion)
                    .where(DocumentVersion.document_id == uuid.UUID(document_id))
                    .order_by(DocumentVersion.version)
                )
            ).all()
        )
        assert len(persisted_versions) == 2
        assert persisted_versions[0].source_file_id != persisted_versions[1].source_file_id
        assert (
            await session.scalar(
                select(func.count(Page.id)).where(Page.document_id == uuid.UUID(document_id))
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count(Block.id)).where(Block.document_id == uuid.UUID(document_id))
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count(ReviewItem.id)).where(
                    ReviewItem.document_id == uuid.UUID(document_id)
                )
            )
            == 0
        )
        archived_object_key = persisted_versions[0].cir_object_key
    assert archived_object_key is not None
    await app.state.object_store.put_derived(archived_object_key, b'{"tampered":true}\n')
    tampered = await client.get(f"/v1/documents/{document_id}/versions/1/snapshot")
    assert tampered.status_code == 409
    assert tampered.json()["error"]["code"] == "DOCUMENT_VERSION_SNAPSHOT_UNAVAILABLE"


@pytest.mark.integration
async def test_stale_compile_worker_is_fenced_and_releases_reserved_credit(
    version_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = version_api
    owner = await _register(
        client,
        email="stale-worker@example.com",
        tenant_name="Stale Worker Fence",
    )
    await _make_team_plan(app, owner["tenant_id"])
    project_id = await _create_project(client, "Version-fenced workers")
    v1_content = (
        b"Version one contains enough deterministic source text for a durable record. "
        b"It will be replaced before the deliberately delayed compile worker starts.\n"
    )
    v1_target, _ = await _upload_source(
        client,
        v1_content,
        filename="stale-worker-v1.txt",
        project_id=project_id,
    )
    document_id = str(v1_target["document_id"])
    v2_content = (
        b"Version two is the only active source and stale workers have no authority "
        b"to mutate its projection or consume the previous version's reservation.\n"
    )
    await _upload_source(
        client,
        v2_content,
        filename="stale-worker-v2.txt",
        document_id=document_id,
    )

    tenant_id = uuid.UUID(owner["tenant_id"])
    async with app.state.database.sessions() as session:
        stale_job = ProcessingJob(
            tenant_id=tenant_id,
            project_id=uuid.UUID(project_id),
            document_id=uuid.UUID(document_id),
            job_type="compile",
            requested_options={
                "document_version": 1,
                "document_version_id": f"{document_id}:v1",
                "route_profile": "parse_balanced_v1",
            },
            cost_estimate={
                "expected": "1",
                "upper_bound": "1",
                "reserved": "1",
            },
            progress={"done": 0, "total": 1},
        )
        session.add(stale_job)
        await session.flush()
        stale_job_id = stale_job.id
        await credit_entry(
            session,
            tenant_id=tenant_id,
            operation_key=f"job:{stale_job.id}:attempt:0:reserve",
            entry_type="reserve",
            credits=Decimal("1"),
            job_id=stale_job.id,
        )
        await session.commit()

    async with app.state.database.sessions() as session:
        await run_compile_job(
            session=session,
            job_id=stale_job_id,
            settings=app.state.settings,
            object_store=app.state.object_store,
        )

    async with app.state.database.sessions() as session:
        persisted = await session.get(ProcessingJob, stale_job_id)
        ledger = list(
            (
                await session.scalars(
                    select(CreditLedger)
                    .where(CreditLedger.job_id == stale_job_id)
                    .order_by(CreditLedger.created_at, CreditLedger.id)
                )
            ).all()
        )
        document = await session.get(Document, uuid.UUID(document_id))
    assert persisted is not None
    assert persisted.status == "failed"
    assert persisted.error == {
        "code": "STALE_DOCUMENT_VERSION",
        "retryable": False,
    }
    assert [entry.entry_type for entry in ledger] == ["reserve", "release"]
    assert document is not None
    assert document.active_version == 2
    assert document.status == "SECURITY_VERIFIED"


@pytest.mark.integration
async def test_invalid_rejected_and_aborted_v2_leave_v1_untouched(
    version_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = version_api
    owner = await _register(
        client,
        email="version-failure@example.com",
        tenant_name="Version Failure Isolation",
    )
    await _make_team_plan(app, owner["tenant_id"])
    project_id = await _create_project(client, "Replacement failure isolation")
    v1_content = b"Authoritative version one remains active.\n"
    v1_target, _ = await _upload_source(
        client,
        v1_content,
        filename="authoritative-v1.txt",
        project_id=project_id,
    )
    document_id = str(v1_target["document_id"])
    assert (await client.post(f"/v1/documents/{document_id}/analyze")).status_code == 202
    blocks = (await client.get(f"/v1/documents/{document_id}/blocks")).json()
    assert len(blocks) == 1
    original_markdown = blocks[0]["markdown"]

    wrong_complete_content = b"Valid replacement bytes, wrong final digest.\n"
    wrong_target = await _initiate_upload(
        client,
        wrong_complete_content,
        filename="wrong-final-digest.txt",
        document_id=document_id,
    )
    invalid = await client.post(
        f"/v1/uploads/{wrong_target['upload_id']}/complete",
        headers={"Idempotency-Key": "invalid-v2-checksum"},
        json={"sha256": "0" * 64},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "CHECKSUM_MISMATCH"
    await _assert_v1_projection(
        client,
        document_id,
        expected_markdown=original_markdown,
    )
    assert (
        await client.post(
            f"/v1/uploads/{wrong_target['upload_id']}/abort",
            headers={"Idempotency-Key": "abort-invalid-v2"},
        )
    ).status_code == 204

    rejected_content = b"\xff\xfe\x00\x00not-utf8"
    rejected_target = await _initiate_upload(
        client,
        rejected_content,
        filename="security-rejected-v2.txt",
        document_id=document_id,
    )
    rejected = await client.post(
        f"/v1/uploads/{rejected_target['upload_id']}/complete",
        headers={"Idempotency-Key": "security-reject-v2"},
        json={"sha256": hashlib.sha256(rejected_content).hexdigest()},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "file_signature_mismatch"
    await _assert_v1_projection(
        client,
        document_id,
        expected_markdown=original_markdown,
    )

    aborted_content = b"Replacement explicitly aborted by the owner.\n"
    aborted_target = await _initiate_upload(
        client,
        aborted_content,
        filename="aborted-v2.txt",
        document_id=document_id,
    )
    aborted = await client.post(
        f"/v1/uploads/{aborted_target['upload_id']}/abort",
        headers={"Idempotency-Key": "abort-clean-v2"},
    )
    assert aborted.status_code == 204, aborted.text
    await _assert_v1_projection(
        client,
        document_id,
        expected_markdown=original_markdown,
    )

    async with app.state.database.sessions() as session:
        document = await session.get(Document, uuid.UUID(document_id))
        assert document is not None
        assert document.active_version == 1
        assert document.source_file_id is not None
        versions = list(
            await session.scalars(
                select(DocumentVersion).where(DocumentVersion.document_id == uuid.UUID(document_id))
            )
        )
        uploads = list(
            await session.scalars(
                select(UploadSession)
                .where(UploadSession.document_id == uuid.UUID(document_id))
                .order_by(UploadSession.created_at)
            )
        )
    assert len(versions) == 1
    assert versions[0].version == 1
    assert versions[0].status == "processed"
    assert [upload.status for upload in uploads] == [
        "completed",
        "aborted",
        "aborted",
        "aborted",
    ]


@pytest.mark.integration
async def test_unchanged_source_and_concurrent_target_version_are_rejected(
    version_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = version_api
    owner = await _register(
        client,
        email="version-race@example.com",
        tenant_name="Version Race Evidence",
    )
    project_id = await _create_project(client, "Version admission")
    v1_content = b"The unchanged source cannot mint another version.\n"
    v1_target, _ = await _upload_source(
        client,
        v1_content,
        filename="same-source-v1.txt",
        project_id=project_id,
    )
    document_id = str(v1_target["document_id"])
    unchanged = await client.post(
        "/v1/uploads/initiate",
        headers={"Idempotency-Key": "unchanged-v2"},
        json=_upload_payload(
            v1_content,
            filename="renamed-but-identical.txt",
            document_id=document_id,
        ),
    )
    assert unchanged.status_code == 409, unchanged.text
    assert unchanged.json()["error"]["code"] == "SOURCE_VERSION_UNCHANGED"

    await _make_team_plan(app, owner["tenant_id"])
    paid_unchanged = await client.post(
        "/v1/uploads/initiate",
        headers={"Idempotency-Key": "unchanged-v2-team"},
        json=_upload_payload(
            v1_content,
            filename="paid-renamed-but-identical.txt",
            document_id=document_id,
        ),
    )
    assert paid_unchanged.status_code == 409, paid_unchanged.text
    assert paid_unchanged.json()["error"]["code"] == "SOURCE_VERSION_UNCHANGED"

    first_content = b"Concurrent replacement candidate A.\n"
    second_content = b"Concurrent replacement candidate B.\n"

    async def initiate_candidate(content: bytes, suffix: str) -> httpx.Response:
        return await client.post(
            "/v1/uploads/initiate",
            headers={"Idempotency-Key": f"concurrent-v2-{suffix}"},
            json=_upload_payload(
                content,
                filename=f"candidate-{suffix}.txt",
                document_id=document_id,
            ),
        )

    first, second = await asyncio.gather(
        initiate_candidate(first_content, "a"),
        initiate_candidate(second_content, "b"),
    )
    winner, loser = (first, second) if first.status_code == 201 else (second, first)
    assert winner.status_code == 201, winner.text
    assert loser.status_code == 409, loser.text
    assert loser.json()["error"]["code"] in {
        "DOCUMENT_VERSION_UPLOAD_ACTIVE",
        "DOCUMENT_VERSION_UPLOAD_CONFLICT",
    }
    assert winner.json()["document_version"] == 2
    if "document_version" in loser.json()["error"]:
        assert loser.json()["error"]["document_version"] == 2
    assert (
        await client.post(
            f"/v1/uploads/{winner.json()['upload_id']}/abort",
            headers={"Idempotency-Key": "abort-concurrent-winner"},
        )
    ).status_code == 204

    async with app.state.database.sessions() as session:
        active = list(
            await session.scalars(
                select(UploadSession).where(
                    UploadSession.document_id == uuid.UUID(document_id),
                    UploadSession.document_version == 2,
                    UploadSession.status.in_(("initiated", "uploaded")),
                )
            )
        )
        document = await session.get(Document, uuid.UUID(document_id))
    assert active == []
    assert document is not None
    assert document.active_version == 1


@pytest.mark.integration
async def test_reprocess_creates_same_source_processing_revision_with_version_diff(
    version_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = version_api
    owner = await _register(
        client,
        email="version-reprocess@example.com",
        tenant_name="Processing Revision Evidence",
    )
    await _make_team_plan(app, owner["tenant_id"])
    project_id = await _create_project(client, "Same-source processing revisions")
    source = b"One immutable source can be processed by multiple pipeline revisions.\n"
    v1_target, v1_completed = await _upload_source(
        client,
        source,
        filename="reprocess-source.txt",
        project_id=project_id,
    )
    document_id = str(v1_target["document_id"])
    analyzed_v1 = await client.post(f"/v1/documents/{document_id}/analyze")
    assert analyzed_v1.status_code == 202, analyzed_v1.text
    v1_task_id = analyzed_v1.json()["task_id"]
    v1_analysis = await client.get(f"/v1/documents/{document_id}/analysis")
    assert v1_analysis.status_code == 200, v1_analysis.text
    assert v1_analysis.json()["status"] == "completed"

    # This row represents a version produced by the immediately preceding
    # pipeline release. Reprocessing must preserve it and report all processing
    # revision changes even though the source object itself is unchanged.
    previous_processing = {
        "policy_version": "router-previous-release",
        "model_revision": "akc-native-parsers/0.9.0",
        "normalization_revision": "akc-normalization-0.9.0",
        "akmp_schema_version": "0.9",
    }
    async with app.state.database.sessions.begin() as session:
        v1 = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == uuid.UUID(document_id),
                DocumentVersion.version == 1,
            )
        )
        assert v1 is not None
        assert v1.status == "processed"
        assert v1.source_file_id == uuid.UUID(v1_completed["source_file_id"])
        v1.policy_version = previous_processing["policy_version"]
        v1.model_revision = previous_processing["model_revision"]
        v1.normalization_revision = previous_processing["normalization_revision"]
        v1.akmp_schema_version = previous_processing["akmp_schema_version"]

    reprocessed = await client.post(
        f"/v1/documents/{document_id}/reprocess",
        headers={"Idempotency-Key": "reprocess-source-v1"},
        json={
            "expected_active_version": 1,
            "reason": "pipeline_release_upgrade",
        },
    )
    assert reprocessed.status_code == 202, reprocessed.text
    assert reprocessed.json()["task_id"] != v1_task_id
    v2_task_id = reprocessed.json()["task_id"]
    current_analysis = await client.get(f"/v1/documents/{document_id}/analysis")
    assert current_analysis.status_code == 200, current_analysis.text
    assert current_analysis.json()["task_id"] == v2_task_id
    assert current_analysis.json()["status"] == "completed"
    current_document = await client.get(f"/v1/documents/{document_id}")
    assert current_document.status_code == 200, current_document.text
    assert current_document.json()["active_version"] == 2
    assert current_document.json()["status"] == "COMPLETED"

    versions = await client.get(f"/v1/documents/{document_id}/versions")
    assert versions.status_code == 200, versions.text
    older, newer = versions.json()["versions"]
    expected_source_sha256 = hashlib.sha256(source).hexdigest()
    assert older["source_sha256"] == newer["source_sha256"] == expected_source_sha256
    assert older["source_file_id"] == newer["source_file_id"]
    assert older["status"] == "archived"
    assert newer["status"] == "processed"
    assert older["cir_snapshot_sha256"] is not None
    assert newer["cir_snapshot_sha256"] is None
    assert newer["policy_version"] != "pending-reprocess-v1"
    assert newer["model_revision"].startswith("akc-native-parsers/")
    assert newer["normalization_revision"].startswith("akc-normalization-")
    assert newer["akmp_schema_version"] == "1.0"

    snapshot = await client.get(f"/v1/documents/{document_id}/versions/1/snapshot")
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["source"]["sha256"] == expected_source_sha256
    assert snapshot.json()["processing"] == {
        **previous_processing,
        "prompt_revision": None,
        "input_revision_hash": older["input_revision_hash"],
    }

    diff = await client.get(
        f"/v1/documents/{document_id}/versions/1/diff",
        params={"to_version": 2},
    )
    assert diff.status_code == 200, diff.text
    changes = diff.json()["changes"]
    for field in (
        "policy_version",
        "model_revision",
        "normalization_revision",
        "akmp_schema_version",
    ):
        assert changes[field] == {
            "from": previous_processing[field],
            "to": newer[field],
        }
    assert "source_sha256" not in changes

    stale = await client.post(
        f"/v1/documents/{document_id}/reprocess",
        headers={"Idempotency-Key": "stale-reprocess-source-v1"},
        json={
            "expected_active_version": 1,
            "reason": "stale_client",
        },
    )
    assert stale.status_code == 409, stale.text
    stale_error = stale.json()["error"]
    assert stale_error["code"] == "SOURCE_VERSION_CHANGED"
    assert (
        stale_error.get("active_version", stale_error.get("details", {}).get("active_version")) == 2
    )

    async with app.state.database.sessions() as session:
        tasks = list(
            (
                await session.scalars(
                    select(AnalysisTask)
                    .where(AnalysisTask.document_id == uuid.UUID(document_id))
                    .order_by(AnalysisTask.document_version)
                )
            ).all()
        )
    assert [(task.document_version, task.status) for task in tasks] == [
        (1, "completed"),
        (2, "completed"),
    ]


@pytest.mark.integration
async def test_version_history_obeys_project_and_tenant_acl(
    version_api: tuple[httpx.AsyncClient, Any],
) -> None:
    owner_client, app = version_api
    owner = await _register(
        owner_client,
        email="version-acl-owner@example.com",
        tenant_name="Version ACL Workspace",
    )
    project_id = await _create_project(owner_client, "Version ACL project")
    v1_target, _ = await _upload_source(
        owner_client,
        b"Version history must remain project scoped.\n",
        filename="acl-v1.txt",
        project_id=project_id,
    )
    document_id = str(v1_target["document_id"])
    await _upload_source(
        owner_client,
        b"Version two creates the archived ACL snapshot.\n",
        filename="acl-v2.txt",
        document_id=document_id,
    )

    invitation = await owner_client.post(
        "/v1/team/invitations",
        headers={"Idempotency-Key": "invite-version-acl-member"},
        json={"email": "version-acl-member@example.com", "role": "editor"},
    )
    assert invitation.status_code == 201, invitation.text
    member_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    )
    try:
        accepted = await member_client.post(
            "/v1/team/invitations/accept",
            json={
                "token": await _capture_verification_token(
                    owner_client,
                    "version-acl-member@example.com",
                ),
                "email": "version-acl-member@example.com",
                "password": _PASSWORD,
                "display_name": "Version ACL Member",
            },
        )
        assert accepted.status_code == 200, accepted.text
        member_id = accepted.json()["user_id"]
        for suffix in (
            "versions",
            "versions/1",
            "versions/1/diff?to_version=2",
            "versions/1/snapshot",
        ):
            hidden = await member_client.get(f"/v1/documents/{document_id}/{suffix}")
            assert hidden.status_code == 404, hidden.text

        granted = await owner_client.post(
            f"/v1/projects/{project_id}/members",
            headers={"Idempotency-Key": "grant-version-history-viewer"},
            json={"user_id": member_id, "role": "viewer"},
        )
        assert granted.status_code == 201, granted.text
        assert (await member_client.get(f"/v1/documents/{document_id}/versions")).status_code == 200
        assert (
            await member_client.get(f"/v1/documents/{document_id}/versions/1")
        ).status_code == 200
        assert (
            await member_client.get(
                f"/v1/documents/{document_id}/versions/1/diff",
                params={"to_version": 2},
            )
        ).status_code == 200
        assert (
            await member_client.get(f"/v1/documents/{document_id}/versions/1/snapshot")
        ).status_code == 200
        viewer_write = await member_client.post(
            "/v1/uploads/initiate",
            headers={"Idempotency-Key": "viewer-cannot-replace-source"},
            json=_upload_payload(
                b"Viewer cannot create version three.\n",
                filename="viewer-v3.txt",
                document_id=document_id,
            ),
        )
        assert viewer_write.status_code == 403
        assert viewer_write.json()["error"]["code"] == "PROJECT_PERMISSION_DENIED"
    finally:
        await member_client.aclose()

    other_tenant_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    )
    try:
        other = await _register(
            other_tenant_client,
            email="version-other-tenant@example.com",
            tenant_name="Other Version Tenant",
        )
        assert other["tenant_id"] != owner["tenant_id"]
        for suffix in (
            "versions",
            "versions/1",
            "versions/1/diff?to_version=2",
            "versions/1/snapshot",
        ):
            hidden = await other_tenant_client.get(f"/v1/documents/{document_id}/{suffix}")
            assert hidden.status_code == 404, hidden.text
    finally:
        await other_tenant_client.aclose()
