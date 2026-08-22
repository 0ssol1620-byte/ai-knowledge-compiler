"""Repository-local v4 Collection API, isolation, and idempotency evidence."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from akc_api.collection_probe import (
    CollectionProbeReceipt,
    CollectionProbeRequest,
)
from akc_api.collection_probe import (
    canonical_json as probe_canonical_json,
)
from akc_api.main import create_app
from akc_api.models import (
    ArchitecturePlan,
    Block,
    Collection,
    CollectionEvent,
    CollectionFile,
    CollectionProcessingTaskBinding,
    CollectionRegion,
    CollectionSourceRoot,
    CostPredictionModel,
    CreditLedger,
    Document,
    DocumentCluster,
    Entity,
    EstimateRun,
    EstimateSample,
    FileContentHash,
    FileVersion,
    JobEvent,
    KnowledgeNote,
    OutboxEvent,
    PackageManifest,
    PackageValidation,
    Page,
    PageAsset,
    PageAttempt,
    PreflightFeatureRecord,
    ProcessingJob,
    Relation,
    ReviewItem,
    VerificationRecord,
)
from akc_api.settings import Settings
from akc_exporters import import_knowledge_package
from akc_retrieval import HmacSha256RowAttestor, PostgresHybridIndexer
from PIL import Image
from sqlalchemy import func, select

_SUPPORT_KEY = "v4-collection-test-support-key"
_PASSWORD = "correct horse battery staple"  # noqa: S105
_PROBE_KEY = b"collection-probe-test-key"


class _SignedProbeExecutor:
    async def execute(self, request: CollectionProbeRequest) -> CollectionProbeReceipt:
        output = request.source_bytes.decode("utf-8", errors="replace")
        output_sha = hashlib.sha256(output.encode()).hexdigest()
        receipt_id = uuid.uuid4()
        runtime = 0.025
        started = 1_000_000_000
        completed = 1_025_000_000
        artifact = {
            "execution_receipt_id": str(receipt_id),
            "source_page_input_sha256": request.source_page_input_sha256,
            "selected_route": request.predicted_route,
            "recovery_probability": 0.0,
            "parser_revision": "native-parser-test-v1",
            "model_revision": "native-model-test-v1",
            "provider_revision": "local-provider-test-v1",
            "runtime_image_digest": "sha256:" + "1" * 64,
            "output_sha256": output_sha,
            "output_length": len(output),
            "extracted_output": output,
        }
        artifact_sha = hashlib.sha256(probe_canonical_json(artifact)).hexdigest()
        attestation = {
            "schema_version": "1.0",
            "probe_kind": "native_parser",
            "probe_revision": "collection-parser-model-probe-v1",
            "execution_receipt_id": str(receipt_id),
            "source_sha256": request.source_sha256,
            "source_page_input_sha256": request.source_page_input_sha256,
            "page_index": request.page_index,
            "artifact_sha256": artifact_sha,
            "runtime_seconds": runtime,
            "output_tokens": max(1, len(output.split())),
            "parser_revision": "native-parser-test-v1",
            "model_revision": "native-model-test-v1",
            "provider_revision": "local-provider-test-v1",
            "runtime_image_digest": "sha256:" + "1" * 64,
            "output_sha256": output_sha,
            "output_length": len(output),
            "started_monotonic_ns": started,
            "completed_monotonic_ns": completed,
        }
        signature = hmac.new(
            _PROBE_KEY, probe_canonical_json(attestation), hashlib.sha256
        ).hexdigest()
        return CollectionProbeReceipt(
            probe_kind="native_parser",
            probe_revision="collection-parser-model-probe-v1",
            execution_receipt_id=receipt_id,
            source_sha256=request.source_sha256,
            source_page_input_sha256=request.source_page_input_sha256,
            page_index=request.page_index,
            selected_route=request.predicted_route,
            recovery_probability=0.0,
            parser_revision="native-parser-test-v1",
            model_revision="native-model-test-v1",
            provider_revision="local-provider-test-v1",
            runtime_image_digest="sha256:" + "1" * 64,
            started_monotonic_ns=started,
            completed_monotonic_ns=completed,
            runtime_seconds=runtime,
            output_sha256=output_sha,
            output_length=len(output),
            output_tokens=max(1, len(output.split())),
            artifact=artifact,
            artifact_sha256=artifact_sha,
            attestation=attestation,
            attestation_sha256=hashlib.sha256(probe_canonical_json(attestation)).hexdigest(),
            attestation_key_id="collection-probe-test-hmac-v1",
            attestation_signature=signature,
        )


class _SignedProbeVerifier:
    async def verify(self, *, key_id: str, attestation: bytes, signature: str) -> bool:
        expected = hmac.new(_PROBE_KEY, attestation, hashlib.sha256).hexdigest()
        return key_id == "collection-probe-test-hmac-v1" and hmac.compare_digest(
            expected, signature
        )


class _NoopPostgresMutationExecutor:
    dialect_name = "postgresql"

    async def execute_transaction(self, _mutations: Any) -> tuple[()]:
        return ()


@pytest_asyncio.fixture
async def collection_api(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'collections.db').as_posix()}",
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
        app.state.collection_probe_executor = _SignedProbeExecutor()
        app.state.collection_probe_attestation_verifier = _SignedProbeVerifier()
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
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
            "display_name": "Collection Owner",
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


async def _project(client: httpx.AsyncClient, *, key: str) -> str:
    response = await client.post(
        "/v1/projects",
        headers={"Idempotency-Key": key},
        json={"name": "Collection Project"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@pytest.mark.asyncio
async def test_admin_health_distinguishes_live_probe_from_configuration(
    collection_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _app = collection_api
    await _register(
        client,
        email="admin-health@example.com",
        tenant_name="Admin Health",
    )

    response = await client.get("/v1/admin/health")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["dependencies"]["database"]["detail"] == "query verified"
    assert payload["dependencies"]["object_store"] == {
        "status": "ok",
        "detail": "local",
        "evidence": "live adapter healthcheck",
    }
    assert payload["dependencies"]["scheduler"] == {
        "status": "not_observed",
        "evidence": "no durable heartbeat source configured",
    }


async def _legacy_upload(
    client: httpx.AsyncClient,
    *,
    project_id: str,
    content: bytes,
) -> dict[str, Any]:
    digest = hashlib.sha256(content).hexdigest()
    initiated = await client.post(
        "/v1/uploads/initiate",
        headers={"Idempotency-Key": "legacy-upload-initiate"},
        json={
            "project_id": project_id,
            "filename": "verified-source.txt",
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
        headers={"Idempotency-Key": "legacy-upload-complete"},
        json={"sha256": digest},
    )
    assert completed.status_code == 200, completed.text
    return {**target, **completed.json()}


async def _seed_verified_knowledge(
    app: Any,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
) -> None:
    async with app.state.database.sessions() as session:
        document = await session.get(Document, document_id)
        assert document is not None
        document.status = "COMPLETED"
        document.page_count = 1
        page = await session.scalar(
            select(Page).where(
                Page.tenant_id == tenant_id,
                Page.document_id == document.id,
                Page.page_number == 1,
            )
        )
        if page is None:
            page = Page(
                tenant_id=tenant_id,
                document_id=document.id,
                page_number=1,
                width_pt=612,
                height_pt=792,
            )
            session.add(page)
        page.status = "COMPLETED"
        page.route = "native"
        page.route_policy_version = "collection-test-v1"
        page.preflight_metrics = {
            "difficulty": 10.0,
            "native_quality": 0.95,
            "table_density": 0.0,
            "image_density": 0.0,
            "numeric_density": 0.05,
            "runtime_seconds": 0.1,
        }
        page.quality_metrics = {"passed": True}
        await session.flush()
        block = Block(
            tenant_id=tenant_id,
            document_id=document.id,
            page_id=page.id,
            block_order=0,
            block_type="paragraph",
            origin="native_text",
            bbox1000=[10, 10, 990, 100],
            polygon_norm=None,
            source_text="Verified collection evidence.",
            normalized_text="Verified collection evidence.",
            markdown="Verified collection evidence.",
            structured_content=None,
            engine="native",
            engine_revision="native-test-v1",
            confidence=1.0,
            content_hash=hashlib.sha256(b"Verified collection evidence.").hexdigest(),
        )
        session.add(block)
        await session.flush()
        session.add(
            PageAttempt(
                tenant_id=tenant_id,
                page_id=page.id,
                attempt_number=1,
                trigger="analysis",
                status="COMPLETED",
                route="native",
                route_profile="parse_balanced_v1",
                route_policy_version="collection-test-v1",
                max_attempts=1,
                completed_at=page.created_at,
            )
        )
        session.add(
            KnowledgeNote(
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document.id,
                document_version=document.active_version,
                stable_key="verified-note",
                title="Verified note",
                note_type="source_summary",
                content_markdown="Verified collection evidence.",
                metadata_json={"scope": "test"},
                evidence_block_ids=[str(block.id)],
                content_origin="source_explicit",
                review_status="verified",
                is_active=True,
            )
        )
        session.add(
            Relation(
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document.id,
                document_version=document.active_version,
                source_relation_key="verified-relation",
                subject_id="note:verified",
                predicate="supported_by",
                object_id=f"block:{block.id}",
                assertion_status="extracted",
                confidence=1.0,
                evidence_block_ids=[str(block.id)],
                review_status="verified",
                is_active=True,
            )
        )
        session.add(
            Entity(
                tenant_id=tenant_id,
                project_id=project_id,
                stable_key="collection-evidence-entity",
                entity_type="concept",
                label="Collection evidence",
                evidence_block_ids=[str(block.id)],
            )
        )
        session.add(
            Entity(
                tenant_id=tenant_id,
                project_id=project_id,
                stable_key="foreign-evidence-entity",
                entity_type="concept",
                label="Foreign evidence",
                evidence_block_ids=[str(uuid.uuid4())],
            )
        )
        session.add(
            ReviewItem(
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document.id,
                page_id=page.id,
                block_id=block.id,
                severity="medium",
                category="ambiguous_layout",
                status="open",
                evidence={"source": "test"},
            )
        )
        job = ProcessingJob(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=document.id,
            job_type="process_document",
            status="completed",
            progress={"pages": 1},
            cost_actual={"credits": 0},
            event_sequence=1,
            completed_at=page.created_at,
        )
        session.add(job)
        await session.flush()
        session.add(
            JobEvent(
                tenant_id=tenant_id,
                job_id=job.id,
                sequence=1,
                event_type="job.completed.v1",
                payload={"page_count": 1},
            )
        )
        await session.commit()


async def test_collection_vertical_slice_is_idempotent_partial_and_fail_closed(
    collection_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = collection_api
    owner = await _register(
        client,
        email="collection.owner@example.com",
        tenant_name="Collection Evidence Workspace",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    project_id = await _project(client, key="collection-project")

    missing_key = await client.post(
        "/v1/collections",
        json={"project_id": project_id, "name": "Missing idempotency"},
    )
    assert missing_key.status_code == 428
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    create_payload = {
        "project_id": project_id,
        "name": "Autonomous evidence collection",
        "profile": {"mode": "deterministic_existing_artifacts"},
    }
    created = await client.post(
        "/v1/collections",
        headers={"Idempotency-Key": "collection-create"},
        json=create_payload,
    )
    replayed_create = await client.post(
        "/v1/collections",
        headers={"Idempotency-Key": "collection-create"},
        json=create_payload,
    )
    assert created.status_code == replayed_create.status_code == 201
    assert created.json() == replayed_create.json()
    collection_id = created.json()["id"]

    source = await client.post(
        f"/v1/collections/{collection_id}/sources/local",
        headers={"Idempotency-Key": "collection-source"},
        json={
            "display_name": "Private local root",
            "source_fingerprint": hashlib.sha256(b"private-root").hexdigest(),
        },
    )
    assert source.status_code == 201, source.text
    source_root_id = source.json()["id"]

    content = b"Verified collection source content.\n"
    digest = hashlib.sha256(content).hexdigest()
    plan_payload = {
        "source_root_id": source_root_id,
        "files": [
            {
                "relative_path": "research/verified-source.txt",
                "display_name": "verified-source.txt",
                "size_bytes": len(content),
                "last_modified_ms": 1_785_469_200_000,
                "expected_mime": "text/plain",
                "sha256": digest,
                "quick_fingerprint": "quick:verified-source",
            },
            {
                "relative_path": "archive/verified-copy.txt",
                "display_name": "verified-copy.txt",
                "size_bytes": len(content),
                "last_modified_ms": 1_785_469_200_001,
                "expected_mime": "text/plain",
                "sha256": digest,
                "quick_fingerprint": "quick:verified-copy",
            },
            {
                "relative_path": "blocked/unsafe.exe",
                "display_name": "unsafe.exe",
                "size_bytes": 2,
                "last_modified_ms": 1_785_469_200_002,
                "expected_mime": "application/octet-stream",
                "sha256": hashlib.sha256(b"MZ").hexdigest(),
                "quick_fingerprint": "quick:unsafe-source",
            },
        ],
    }
    planned = await client.post(
        f"/v1/collections/{collection_id}/files/plan",
        headers={"Idempotency-Key": "collection-plan"},
        json=plan_payload,
    )
    replayed_plan = await client.post(
        f"/v1/collections/{collection_id}/files/plan",
        headers={"Idempotency-Key": "collection-plan"},
        json=plan_payload,
    )
    assert planned.status_code == replayed_plan.status_code == 201, planned.text
    assert planned.json() == replayed_plan.json()
    plan_body = planned.json()
    by_path = {row["relative_path"]: row for row in plan_body["files"]}
    assert by_path["research/verified-source.txt"]["status"] == "planned"
    assert by_path["archive/verified-copy.txt"]["status"] == "duplicate_pending"
    assert by_path["blocked/unsafe.exe"]["status"] == "unsupported"
    assert plan_body["upload"]["active_files"] == 2
    assert plan_body["upload"]["failed_files"] == 1
    assert source.json()["display_name"] == "Private local root"
    original_ciphertexts: dict[uuid.UUID, tuple[bytes, bytes]] = {}
    async with app.state.database.sessions() as session:
        root_row = await session.get(CollectionSourceRoot, uuid.UUID(source_root_id))
        stored_files = list(
            await session.scalars(
                select(CollectionFile).where(
                    CollectionFile.collection_id == uuid.UUID(collection_id)
                )
            )
        )
        assert root_row is not None
        assert "display_name" not in CollectionSourceRoot.__table__.c
        assert "relative_path" not in CollectionFile.__table__.c
        assert "display_name" not in CollectionFile.__table__.c
        assert b"Private local root" not in root_row.display_name_ciphertext
        assert (
            app.state.collection_metadata_codec.decrypt_source_root_display_name(
                root_row.display_name_ciphertext,
                key_id=root_row.metadata_key_id,
                tenant_id=root_row.tenant_id,
                collection_id=root_row.collection_id,
                source_root_id=root_row.id,
            )
            == "Private local root"
        )
        assert len(stored_files) == len(plan_payload["files"])
        requested_by_path = {item["relative_path"]: item for item in plan_payload["files"]}
        for file_row in stored_files:
            decrypted_path = app.state.collection_metadata_codec.decrypt_file_relative_path(
                file_row.relative_path_ciphertext,
                key_id=file_row.metadata_key_id,
                tenant_id=file_row.tenant_id,
                collection_id=file_row.collection_id,
                source_root_id=file_row.source_root_id,
                file_id=file_row.id,
            )
            decrypted_name = app.state.collection_metadata_codec.decrypt_file_display_name(
                file_row.display_name_ciphertext,
                key_id=file_row.metadata_key_id,
                tenant_id=file_row.tenant_id,
                collection_id=file_row.collection_id,
                source_root_id=file_row.source_root_id,
                file_id=file_row.id,
            )
            assert decrypted_name == requested_by_path[decrypted_path]["display_name"]
            assert decrypted_path.encode() not in file_row.relative_path_ciphertext
            assert decrypted_name.encode() not in file_row.display_name_ciphertext
            assert len(file_row.relative_path_blind_index) == 32
            original_ciphertexts[file_row.id] = (
                file_row.relative_path_ciphertext,
                file_row.display_name_ciphertext,
            )

    paused = await client.post(
        f"/v1/collections/{collection_id}/upload/control",
        headers={"Idempotency-Key": "collection-upload-pause"},
        json={"action": "pause"},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["collection"]["status"] == "PAUSED"
    invalid_resume = await client.post(
        f"/v1/collections/{collection_id}/upload/control",
        headers={"Idempotency-Key": "collection-upload-invalid-resume"},
        json={"action": "resume", "browser_resume_token": "x" * 32},
    )
    assert invalid_resume.status_code == 403
    assert invalid_resume.json()["error"]["code"] == "COLLECTION_RESUME_TOKEN_INVALID"
    resume_payload = {
        "action": "resume",
        "browser_resume_token": plan_body["browser_resume_token"],
    }
    resumed = await client.post(
        f"/v1/collections/{collection_id}/upload/control",
        headers={"Idempotency-Key": "collection-upload-resume"},
        json=resume_payload,
    )
    replayed_resume = await client.post(
        f"/v1/collections/{collection_id}/upload/control",
        headers={"Idempotency-Key": "collection-upload-resume"},
        json=resume_payload,
    )
    assert resumed.status_code == replayed_resume.status_code == 200
    assert resumed.json() == replayed_resume.json()
    assert resumed.json()["collection"]["status"] == "UPLOADING"
    assert resumed.json()["upload"]["resume_version"] == 2
    assert resumed.json()["browser_resume_token"] != plan_body["browser_resume_token"]

    legacy = await _legacy_upload(client, project_id=project_id, content=content)
    completed_payload = {
        "receipts": [
            {
                "file_id": by_path["research/verified-source.txt"]["id"],
                "outcome": "completed",
                "source_file_id": legacy["source_file_id"],
            }
        ]
    }
    completed = await client.post(
        f"/v1/collections/{collection_id}/upload/complete",
        headers={"Idempotency-Key": "collection-complete"},
        json=completed_payload,
    )
    replayed_complete = await client.post(
        f"/v1/collections/{collection_id}/upload/complete",
        headers={"Idempotency-Key": "collection-complete"},
        json=completed_payload,
    )
    assert completed.status_code == replayed_complete.status_code == 200, completed.text
    assert completed.json() == replayed_complete.json()
    assert completed.json()["collection"]["status"] == "PARTIAL"
    assert completed.json()["upload"] == {
        **completed.json()["upload"],
        "completed_files": 2,
        "active_files": 0,
        "failed_files": 1,
        "duplicate_files": 1,
    }

    await _seed_verified_knowledge(
        app,
        tenant_id=tenant_id,
        project_id=uuid.UUID(project_id),
        document_id=uuid.UUID(legacy["document_id"]),
    )
    preview_buffer = io.BytesIO()
    Image.new("RGB", (200, 300), (247, 244, 235)).save(preview_buffer, format="PNG")
    preview_bytes = preview_buffer.getvalue()
    proof_storage_key = f"proof-tests/{collection_id}/page-1.png"
    await app.state.object_store.put_derived(proof_storage_key, preview_bytes)
    async with app.state.database.sessions() as session:
        page = await session.scalar(
            select(Page).where(
                Page.tenant_id == tenant_id,
                Page.document_id == uuid.UUID(legacy["document_id"]),
                Page.page_number == 1,
            )
        )
        assert page is not None
        session.add(
            PageAsset(
                tenant_id=tenant_id,
                page_id=page.id,
                asset_type="preview",
                storage_key=proof_storage_key,
                sha256=hashlib.sha256(preview_bytes).hexdigest(),
                metadata_json={"size_bytes": len(preview_bytes)},
            )
        )
        region = CollectionRegion(
            tenant_id=tenant_id,
            collection_id=uuid.UUID(collection_id),
            collection_file_id=uuid.UUID(by_path["research/verified-source.txt"]["id"]),
            document_id=uuid.UUID(legacy["document_id"]),
            page_id=page.id,
            stable_key="proof-region-1",
            region_type="table_cell",
            bbox1000=[200, 250, 800, 750],
            status="verified",
        )
        session.add(region)
        await session.flush()
        proof = VerificationRecord(
            tenant_id=tenant_id,
            collection_id=uuid.UUID(collection_id),
            collection_file_id=uuid.UUID(by_path["research/verified-source.txt"]["id"]),
            region_id=region.id,
            status="verified",
            validator_revision="proof-crop-test-v1",
            evidence={"block_id": "identifier-only"},
        )
        session.add(proof)
        await session.commit()
        proof_id = proof.id

    proof_crop = await client.get(f"/v1/proofs/{proof_id}/crop")
    assert proof_crop.status_code == 200, proof_crop.text
    assert proof_crop.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert proof_crop.headers["cache-control"].startswith("private")
    assert proof_crop.headers["x-akc-proof-id"] == str(proof_id)
    preflight = await client.post(
        f"/v1/collections/{collection_id}/preflight",
        headers={"Idempotency-Key": "collection-preflight"},
    )
    assert preflight.status_code == 201, preflight.text
    assert preflight.json()["status"] == "partial"
    assert preflight.json()["estimate"]["status"] == "sampled_ready"
    assert preflight.json()["estimate"]["basis"] == "adaptive_sample_rules_quantile_v1"
    assert preflight.json()["estimate"]["known_pages"] == 1
    assert (
        preflight.json()["estimate"]["reserve_ceiling"]
        >= preflight.json()["estimate"]["p95_credits"]
    )
    assert (
        preflight.json()["estimate"]["p95_credits"] >= preflight.json()["estimate"]["p50_credits"]
    )
    predictor = preflight.json()["estimate"]["predictor_input"]
    assert predictor["knowledge_note_count"] == 1
    assert predictor["entity_count"] == 1
    assert predictor["relation_count"] == 1
    assert predictor["entity_relation_candidates"] == 2
    assert predictor["export_profiles"] == preflight.json()["estimate"]["export_profiles"]
    assert predictor["queue_delay_p50_seconds"] is None
    assert "QUEUE_DELAY_UNMEASURED" in predictor["warnings"]
    shadow = preflight.json()["estimate"]["learned_router_shadow"]
    assert shadow["authority"] == "zero"
    assert shadow["production_route_source"] == "deterministic_fallback"
    assert shadow["promotion_eligible"] is False
    assert len(preflight.json()["estimate"]["predictor_evidence_sha256"]) == 64
    serialized_preflight = json.dumps(preflight.json(), ensure_ascii=False)
    assert "research/verified-source.txt" not in serialized_preflight
    assert "archive/verified-copy.txt" not in serialized_preflight
    assert content.decode().strip() not in serialized_preflight
    assert "Private local root" not in serialized_preflight
    estimate = await client.get(f"/v1/collections/{collection_id}/estimate")
    assert estimate.status_code == 200
    assert estimate.json() == preflight.json()["estimate"]
    async with app.state.database.sessions() as session:
        assert int(await session.scalar(select(func.count(EstimateRun.id))) or 0) == 2
        assert int(await session.scalar(select(func.count(EstimateSample.id))) or 0) >= 1
        assert int(await session.scalar(select(func.count(PreflightFeatureRecord.id))) or 0) == 2
        persisted_clusters = list(await session.scalars(select(DocumentCluster)))
        persisted_features = list(await session.scalars(select(PreflightFeatureRecord)))
        assert persisted_clusters
        assert all(len(row.cluster_key) == 64 for row in persisted_clusters)
        assert all(len(row.cluster_key) == 64 for row in persisted_features)
        assert {row.cluster_key for row in persisted_features} <= {
            row.cluster_key for row in persisted_clusters
        }
        assert int(await session.scalar(select(func.count(CostPredictionModel.id))) or 0) == 2
        predictor_models = list(
            await session.scalars(
                select(CostPredictionModel).order_by(CostPredictionModel.model_type)
            )
        )
        assert {row.status for row in predictor_models} == {
            "active_snapshot",
            "shadow_snapshot",
        }
        learned_model = next(
            row for row in predictor_models if row.model_type == "learned_quantile"
        )
        assert learned_model.parameters["authority"] == "zero"
        assert learned_model.parameters["production_route_source"] == (
            "deterministic_fallback"
        )

    async with app.state.database.sessions() as session:
        credits_before = int(await session.scalar(select(func.count(CreditLedger.id))) or 0)
    compile_payload = {
        "approve_estimate": True,
        "mode": "deterministic_existing_artifacts",
    }
    compiled = await client.post(
        f"/v1/collections/{collection_id}/compile",
        headers={"Idempotency-Key": "collection-compile"},
        json=compile_payload,
    )
    replayed_compile = await client.post(
        f"/v1/collections/{collection_id}/compile",
        headers={"Idempotency-Key": "collection-compile"},
        json=compile_payload,
    )
    assert compiled.status_code == replayed_compile.status_code == 201, compiled.text
    assert compiled.json() == replayed_compile.json()
    assert compiled.json()["credits_consumed"] == "0.000000"
    assert compiled.json()["execution_scope"] == "existing_verified_artifacts_only"
    assert {row["module_key"] for row in compiled.json()["modules"]} == {
        "source_index",
        "document_catalog",
        "knowledge_notes",
        "entities",
        "relations",
        "integrity",
        "export_manifest",
    }
    async with app.state.database.sessions() as session:
        credits_after = int(await session.scalar(select(func.count(CreditLedger.id))) or 0)
        plans = int(await session.scalar(select(func.count(ArchitecturePlan.id))) or 0)
        isolated_review = await session.scalar(
            select(ReviewItem).where(ReviewItem.document_id == uuid.UUID(legacy["document_id"]))
        )
        isolated_verifications = list(
            await session.scalars(
                select(VerificationRecord).where(
                    VerificationRecord.collection_id == uuid.UUID(collection_id),
                    VerificationRecord.status == "unresolved",
                )
            )
        )
    assert credits_after == credits_before
    assert plans == 1
    assert isolated_review is not None and isolated_review.status == "resolved"
    assert isolated_review.resolution["strategy"] == "autonomous_isolation"
    assert isolated_verifications

    knowledge = await client.get(f"/v1/collections/{collection_id}/knowledge")
    assert knowledge.status_code == 200, knowledge.text
    assert knowledge.json()["ready_for_package"] is True
    assert knowledge.json()["note_count"] == 1
    assert knowledge.json()["entity_count"] == 1
    assert knowledge.json()["relation_count"] == 1

    scene = await client.get(f"/v1/collections/{collection_id}/scene")
    scene_replay = await client.get(f"/v1/collections/{collection_id}/scene")
    assert scene.status_code == scene_replay.status_code == 200, scene.text
    assert scene.json() == scene_replay.json()
    assert scene.json()["scene_hash"] == scene_replay.json()["scene_hash"]
    assert scene.json()["sequence"] >= 1
    assert scene.json()["projected_page_count"] <= 200
    assert scene.json()["knowledge"]["note_count"] == 1
    assert scene.json()["knowledge"]["entity_count"] == 1
    assert scene.json()["knowledge"]["relation_count"] == 1
    scene_wire = json.dumps(scene.json(), sort_keys=True)
    assert "storage_key" not in scene_wire
    assert "source_text" not in scene_wire
    assert "presigned" not in scene_wire

    exported = await client.post(
        f"/v1/collections/{collection_id}/exports",
        headers={"Idempotency-Key": "collection-manifest-export"},
        json={"profiles": ["collection_manifest_v1"]},
    )
    replayed_export = await client.post(
        f"/v1/collections/{collection_id}/exports",
        headers={"Idempotency-Key": "collection-manifest-export"},
        json={"profiles": ["collection_manifest_v1"]},
    )
    assert exported.status_code == replayed_export.status_code == 201, exported.text
    assert exported.json() == replayed_export.json()
    assert exported.json()["completion_scope"] == "repository_manifest_only"
    assert exported.json()["signature_status"] == "unsigned_external_key_required"
    downloaded = await client.get(exported.json()["download_url"])
    assert downloaded.status_code == 200, downloaded.text
    assert hashlib.sha256(downloaded.content).hexdigest() == exported.json()["sha256"]
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        names = set(archive.namelist())
        assert {
            "README.md",
            "manifest.json",
            "checksums.sha256",
            "source/collection-files.json",
            "architecture/plan.json",
            "knowledge/index.json",
            "integrity/summary.json",
            "provenance/collection-events.jsonl",
            "validation/limitations.json",
        } <= names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["completion_scope"] == "repository_manifest_only"
        assert manifest["signature_status"] == "unsigned_external_key_required"

    full_export = await client.post(
        f"/v1/collections/{collection_id}/exports",
        headers={"Idempotency-Key": "collection-full-export"},
        json={"profiles": ["complete_knowledge_v1"]},
    )
    replayed_full_export = await client.post(
        f"/v1/collections/{collection_id}/exports",
        headers={"Idempotency-Key": "collection-full-export"},
        json={"profiles": ["complete_knowledge_v1"]},
    )
    assert full_export.status_code == replayed_full_export.status_code == 201, full_export.text
    assert full_export.json() == replayed_full_export.json()
    assert full_export.json()["completion_scope"] == "complete_knowledge_package"
    assert full_export.json()["signature_status"] == "external_signer_required"
    full_download = await client.get(full_export.json()["download_url"])
    assert full_download.status_code == 200, full_download.text
    imported = import_knowledge_package(full_download.content, require_signature=False)
    assert imported.receipt.signature_status == "external_signer_required"
    assert imported.manifest["collection_id"] == collection_id
    assert {
        "canonical/model.json",
        "obsidian/Home.md",
        "ontology/knowledge.ttl",
        "graph/nodes.csv",
        "rag/chunks.jsonl",
        "provenance/activities.jsonl",
        "validation/report.json",
    } <= set(imported.files)
    async with app.state.database.sessions() as session:
        package_count = int(await session.scalar(select(func.count(PackageManifest.id))) or 0)
        package_validation_count = int(
            await session.scalar(select(func.count(PackageValidation.id))) or 0
        )
    assert package_count == 2
    assert package_validation_count == 1

    events = await client.get(f"/v1/collections/{collection_id}/events")
    assert events.status_code == 200, events.text
    event_body = events.json()
    utc_suffixes = ("Z", "+00:00")
    assert event_body["snapshot"]["upload"]["expires_at"].endswith(utc_suffixes)
    assert all(row["timestamp"].endswith(utc_suffixes) for row in event_body["events"])
    event_types = [row["event_type"] for row in event_body["events"]]
    assert event_types.count("collection.created.v1") == 1
    assert event_types.count("architecture.plan.compiled.v1") == 1
    assert event_types.count("processing.source_events.bridged.v1") == 1
    assert event_types.count("package.validated.v1") == 1
    assert event_types.count("collection.completed.v1") == 1
    assert event_types.count("collection.export.completed.v1") == 2
    compile_events = [
        row
        for row in event_body["events"]
        if row["event_type"]
        in {
            "note.created.v1",
            "entity.resolved.v1",
            "relation.created.v1",
            "architecture.plan.compiled.v1",
        }
    ]
    assert len(compile_events) == 4
    assert all(row["job_id"] is not None for row in compile_events)
    assert all(row["payload"]["processing_job_id"] == row["job_id"] for row in compile_events)
    package_events = [
        row
        for row in events.json()["events"]
        if row["event_type"]
        in {
            "export.started.v1",
            "export.ready.v1",
            "package.validated.v1",
            "collection.completed.v1",
        }
        or (
            row["event_type"] == "collection.export.completed.v1"
            and row["payload"].get("profile") == "complete_knowledge_v1"
        )
    ]
    assert len(package_events) == 5
    assert all(row["job_id"] is not None for row in package_events)
    assert all(row["payload"]["processing_job_id"] == row["job_id"] for row in package_events)
    event_wire = json.dumps(events.json(), sort_keys=True)
    assert "Private local root" not in event_wire
    assert "research/verified-source.txt" not in event_wire

    deleted = await client.delete(
        f"/v1/collections/{collection_id}",
        headers={"Idempotency-Key": "collection-delete"},
    )
    replayed_delete = await client.delete(
        f"/v1/collections/{collection_id}",
        headers={"Idempotency-Key": "collection-delete"},
    )
    assert deleted.status_code == replayed_delete.status_code == 200, deleted.text
    assert deleted.json() == replayed_delete.json()
    assert deleted.json()["status"] == "PURGED"
    assert deleted.json()["shared_source_objects_retained"] is True
    assert (await client.get(exported.json()["download_url"])).status_code == 404
    assert (await client.get(full_export.json()["download_url"])).status_code == 404
    assert (await client.get(f"/v1/collections/{collection_id}/upload")).status_code == 404
    async with app.state.database.sessions() as session:
        row = await session.get(Collection, uuid.UUID(collection_id))
        purged_root = await session.get(CollectionSourceRoot, uuid.UUID(source_root_id))
        purged_files = list(
            await session.scalars(
                select(CollectionFile).where(
                    CollectionFile.collection_id == uuid.UUID(collection_id)
                )
            )
        )
        assert row is not None
        assert row.status == "PURGED"
        assert row.name == "purged"
        assert purged_root is not None
        assert (
            app.state.collection_metadata_codec.decrypt_source_root_display_name(
                purged_root.display_name_ciphertext,
                key_id=purged_root.metadata_key_id,
                tenant_id=purged_root.tenant_id,
                collection_id=purged_root.collection_id,
                source_root_id=purged_root.id,
            )
            == "purged"
        )
        for purged_file in purged_files:
            purged_path = app.state.collection_metadata_codec.decrypt_file_relative_path(
                purged_file.relative_path_ciphertext,
                key_id=purged_file.metadata_key_id,
                tenant_id=purged_file.tenant_id,
                collection_id=purged_file.collection_id,
                source_root_id=purged_file.source_root_id,
                file_id=purged_file.id,
            )
            assert purged_path == f"purged/{purged_file.id.hex}"
            assert (
                purged_file.relative_path_ciphertext,
                purged_file.display_name_ciphertext,
            ) != original_ciphertexts[purged_file.id]
            assert b"purged" not in purged_file.relative_path_ciphertext
            assert b"purged" not in purged_file.display_name_ciphertext
        event_count = int(
            await session.scalar(
                select(func.count(CollectionEvent.id)).where(
                    CollectionEvent.collection_id == uuid.UUID(collection_id)
                )
            )
            or 0
        )
    assert event_count == events.json()["snapshot"]["latest_sequence"] + 2


async def test_runtime_zero_task_reuse_starts_durable_finalizer_with_zero_reserve(
    collection_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = collection_api
    owner = await _register(
        client,
        email="zero-task-runtime@example.com",
        tenant_name="Zero Task Runtime",
    )
    tenant_id = uuid.UUID(owner["tenant_id"])
    project_id = await _project(client, key="zero-task-project")
    created = await client.post(
        "/v1/collections",
        headers={"Idempotency-Key": "zero-task-collection"},
        json={"project_id": project_id, "name": "Completed result reuse"},
    )
    assert created.status_code == 201, created.text
    collection_id = created.json()["id"]
    source = await client.post(
        f"/v1/collections/{collection_id}/sources/local",
        headers={"Idempotency-Key": "zero-task-source"},
        json={
            "display_name": "Completed source root",
            "source_fingerprint": hashlib.sha256(b"zero-task-root").hexdigest(),
        },
    )
    assert source.status_code == 201, source.text
    content = b"A fully completed result must still use the durable finalizer.\n"
    digest = hashlib.sha256(content).hexdigest()
    planned = await client.post(
        f"/v1/collections/{collection_id}/files/plan",
        headers={"Idempotency-Key": "zero-task-files"},
        json={
            "source_root_id": source.json()["id"],
            "files": [
                {
                    "relative_path": "completed/result.txt",
                    "display_name": "result.txt",
                    "size_bytes": len(content),
                    "expected_mime": "text/plain",
                    "sha256": digest,
                    "quick_fingerprint": "quick:zero-task-result",
                }
            ],
        },
    )
    assert planned.status_code == 201, planned.text
    legacy = await _legacy_upload(client, project_id=project_id, content=content)
    completed = await client.post(
        f"/v1/collections/{collection_id}/upload/complete",
        headers={"Idempotency-Key": "zero-task-upload-complete"},
        json={
            "receipts": [
                {
                    "file_id": planned.json()["files"][0]["id"],
                    "outcome": "completed",
                    "source_file_id": legacy["source_file_id"],
                }
            ]
        },
    )
    assert completed.status_code == 200, completed.text
    await _seed_verified_knowledge(
        app,
        tenant_id=tenant_id,
        project_id=uuid.UUID(project_id),
        document_id=uuid.UUID(legacy["document_id"]),
    )
    preflight = await client.post(
        f"/v1/collections/{collection_id}/preflight",
        headers={"Idempotency-Key": "zero-task-preflight"},
    )
    assert preflight.status_code == 201, preflight.text
    assert preflight.json()["estimate"]["status"] == "sampled_ready"
    app.state.collection_semantic_retrieval_indexer = PostgresHybridIndexer(
        executor=_NoopPostgresMutationExecutor(),
        row_attestor=HmacSha256RowAttestor(b"z" * 32),
    )
    app.state.collection_semantic_retrieval_batch_factory = lambda _prepared: None
    compile_headers = {"Idempotency-Key": "zero-task-runtime-start"}
    started = await client.post(
        f"/v1/collections/{collection_id}/compile",
        headers=compile_headers,
        json={"approve_estimate": True},
    )
    replayed = await client.post(
        f"/v1/collections/{collection_id}/compile",
        headers=compile_headers,
        json={"approve_estimate": True},
    )
    assert started.status_code == replayed.status_code == 201, started.text
    assert started.json() == replayed.json()
    body = started.json()
    assert body["processing_status"] == "running"
    assert body["processing_resume_token"] is not None
    assert body["execution_scope"] == "collection_processing_runtime"
    assert body["credits_reserved"] == "0.000000"

    job_id = uuid.UUID(body["processing_job_id"])
    async with app.state.database.sessions() as session:
        collection = await session.get(Collection, uuid.UUID(collection_id))
        job = await session.get(ProcessingJob, job_id)
        bindings = int(
            await session.scalar(
                select(func.count())
                .select_from(CollectionProcessingTaskBinding)
                .where(CollectionProcessingTaskBinding.processing_job_id == job_id)
            )
            or 0
        )
        finalizer_events = list(
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == job_id,
                    OutboxEvent.event_type == "collection.semantic.compile.requested.v1",
                )
            )
        )
        credit_rows = int(
            await session.scalar(
                select(func.count(CreditLedger.id)).where(CreditLedger.job_id == job_id)
            )
            or 0
        )
    assert collection is not None and collection.status == "VERIFYING_OUTPUT"
    assert job is not None and job.progress["stage"] == "semantic_compile_queued"
    assert job.progress["total_tasks"] == 0
    assert bindings == 0
    assert credit_rows == 0
    assert len(finalizer_events) == 1
    assert finalizer_events[0].payload["actor_user_id"] == owner["user_id"]
    assert finalizer_events[0].payload["architecture_plan_id"] == body["id"]

    deleted = await client.delete(
        f"/v1/collections/{collection_id}",
        headers={"Idempotency-Key": "zero-task-delete-before-finalizer"},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "PURGED"
    async with app.state.database.sessions() as session:
        cancelled_job = await session.get(ProcessingJob, job_id)
        cancelled_event = await session.get(OutboxEvent, finalizer_events[0].id)
    assert cancelled_job is not None and cancelled_job.status == "cancelled"
    assert cancelled_job.progress["cancelled_finalizer_events"] == 1
    assert cancelled_event is not None and cancelled_event.published_at is not None
    assert cancelled_event.dead_lettered_at is not None


async def test_internal_collection_finalizer_rejects_signature_and_unknown_scope(
    collection_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = collection_api
    payload = {
        "event_id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "collection_id": str(uuid.uuid4()),
        "processing_job_id": str(uuid.uuid4()),
        "architecture_plan_id": str(uuid.uuid4()),
        "actor_user_id": str(uuid.uuid4()),
    }
    invalid = await client.post(
        "/v1/internal/collections/finalize",
        headers={"X-AKC-Collection-Finalizer-Signature": "sha256=" + "0" * 64},
        json=payload,
    )
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "COLLECTION_FINALIZER_SIGNATURE_INVALID"

    canonical_body = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    signature = (
        "sha256="
        + hmac.new(
            app.state.settings.effective_collection_finalizer_hmac_secret,
            canonical_body,
            hashlib.sha256,
        ).hexdigest()
    )
    unknown_scope = await client.post(
        "/v1/internal/collections/finalize",
        headers={"X-AKC-Collection-Finalizer-Signature": signature},
        json=payload,
    )
    assert unknown_scope.status_code == 409
    assert unknown_scope.json()["error"]["code"] == "COLLECTION_FINALIZER_SCOPE_INVALID"


async def test_collection_metadata_gate_prevents_plaintext_source_write(
    collection_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = collection_api
    owner = await _register(
        client,
        email="metadata-gate@example.com",
        tenant_name="Metadata Gate",
    )
    project_id = await _project(client, key="metadata-gate-project")
    created = await client.post(
        "/v1/collections",
        headers={"Idempotency-Key": "metadata-gate-collection"},
        json={"project_id": project_id, "name": "No plaintext fallback"},
    )
    assert created.status_code == 201, created.text

    codec = app.state.collection_metadata_codec
    app.state.collection_metadata_codec = None
    try:
        denied = await client.post(
            f"/v1/collections/{created.json()['id']}/sources/local",
            headers={"Idempotency-Key": "metadata-gate-source"},
            json={
                "display_name": "Must never persist",
                "source_fingerprint": hashlib.sha256(b"metadata-gate").hexdigest(),
            },
        )
    finally:
        app.state.collection_metadata_codec = codec
    assert denied.status_code == 503
    assert denied.json()["error"]["code"] == "COLLECTION_METADATA_ENCRYPTION_REQUIRED"
    async with app.state.database.sessions() as session:
        source_count = int(
            await session.scalar(
                select(func.count(CollectionSourceRoot.id)).where(
                    CollectionSourceRoot.tenant_id == uuid.UUID(owner["tenant_id"]),
                    CollectionSourceRoot.collection_id == uuid.UUID(created.json()["id"]),
                )
            )
            or 0
        )
    assert source_count == 0

    source_payload = {
        "display_name": "Encrypted replay source",
        "source_fingerprint": hashlib.sha256(b"encrypted-replay-source").hexdigest(),
    }
    accepted = await client.post(
        f"/v1/collections/{created.json()['id']}/sources/local",
        headers={"Idempotency-Key": "metadata-gate-encrypted-source"},
        json=source_payload,
    )
    assert accepted.status_code == 201, accepted.text
    app.state.collection_metadata_codec = None
    try:
        replay_denied = await client.post(
            f"/v1/collections/{created.json()['id']}/sources/local",
            headers={"Idempotency-Key": "metadata-gate-encrypted-source"},
            json=source_payload,
        )
    finally:
        app.state.collection_metadata_codec = codec
    assert replay_denied.status_code == 503
    assert replay_denied.json()["error"]["code"] == "COLLECTION_METADATA_ENCRYPTION_REQUIRED"


async def test_collection_preflight_materializes_verified_byte_features_without_model(
    collection_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = collection_api
    owner = await _register(
        client,
        email="collection.static@example.com",
        tenant_name="Static Preflight Workspace",
    )
    project_id = await _project(client, key="static-preflight-project")
    created = await client.post(
        "/v1/collections",
        headers={"Idempotency-Key": "static-preflight-collection"},
        json={"project_id": project_id, "name": "Static byte preflight"},
    )
    assert created.status_code == 201, created.text
    collection_id = created.json()["id"]
    source = await client.post(
        f"/v1/collections/{collection_id}/sources/local",
        headers={"Idempotency-Key": "static-preflight-source"},
        json={
            "display_name": "Static source",
            "source_fingerprint": hashlib.sha256(b"static-source").hexdigest(),
        },
    )
    assert source.status_code == 201, source.text
    content = b"Revenue 2026: 12345\nOperating margin: 42%\n"
    digest = hashlib.sha256(content).hexdigest()
    plan = await client.post(
        f"/v1/collections/{collection_id}/files/plan",
        headers={"Idempotency-Key": "static-preflight-plan"},
        json={
            "source_root_id": source.json()["id"],
            "files": [
                {
                    "relative_path": "reports/revenue.txt",
                    "display_name": "revenue.txt",
                    "size_bytes": len(content),
                    "last_modified_ms": 1_785_469_200_000,
                    "expected_mime": "text/plain",
                    "sha256": digest,
                    "quick_fingerprint": "quick:static-revenue",
                }
            ],
        },
    )
    assert plan.status_code == 201, plan.text
    legacy = await _legacy_upload(client, project_id=project_id, content=content)
    completed = await client.post(
        f"/v1/collections/{collection_id}/upload/complete",
        headers={"Idempotency-Key": "static-preflight-complete"},
        json={
            "receipts": [
                {
                    "file_id": plan.json()["files"][0]["id"],
                    "outcome": "completed",
                    "source_file_id": legacy["source_file_id"],
                }
            ]
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["collection"]["status"] == "INGESTED"

    delattr(app.state, "collection_probe_executor")
    delattr(app.state, "collection_probe_attestation_verifier")

    preflight = await client.post(
        f"/v1/collections/{collection_id}/preflight",
        headers={"Idempotency-Key": "static-preflight-run"},
    )
    assert preflight.status_code == 201, preflight.text
    body = preflight.json()
    assert body["status"] == "complete"
    assert body["known_pages"] == 1
    assert body["features"]["static_preflight"] == {
        "created_pages": 1,
        "inspected_sources": 1,
        "failures": {},
    }
    assert body["estimate"]["status"] == "fast_ready"
    assert body["estimate"]["sampled_pages"] == 0
    assert body["features"]["valid_probe_receipts"] == 0
    assert any("fast static estimate" in item for item in body["limitations"])
    async with app.state.database.sessions() as session:
        document = await session.get(Document, uuid.UUID(legacy["document_id"]))
        page = await session.scalar(
            select(Page).where(Page.document_id == uuid.UUID(legacy["document_id"]))
        )
        feature_count = int(
            await session.scalar(select(func.count(PreflightFeatureRecord.id))) or 0
        )
        hash_count = int(await session.scalar(select(func.count(FileContentHash.id))) or 0)
        version_count = int(await session.scalar(select(func.count(FileVersion.id))) or 0)
    assert document is not None and document.status == "PREFLIGHTED"
    assert document.page_count == 1
    assert page is not None and page.status == "PREFLIGHTED"
    assert page.preflight_metrics["feature_origin"] == "verified_source_bytes"
    assert page.preflight_metrics["static_only"] is True
    assert feature_count == hash_count == version_count == 1
    assert owner["tenant_id"] == str(document.tenant_id)


async def test_collection_cross_tenant_reads_are_not_disclosed(
    collection_api: tuple[httpx.AsyncClient, Any],
) -> None:
    owner_client, app = collection_api
    await _register(
        owner_client,
        email="collection.first@example.com",
        tenant_name="First Collection Tenant",
    )
    project_id = await _project(owner_client, key="first-project")
    created = await owner_client.post(
        "/v1/collections",
        headers={"Idempotency-Key": "first-collection"},
        json={"project_id": project_id, "name": "Private collection"},
    )
    assert created.status_code == 201
    collection_id = created.json()["id"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as other_client:
        await _register(
            other_client,
            email="collection.second@example.com",
            tenant_name="Second Collection Tenant",
        )
        assert (
            await other_client.get(f"/v1/collections/{collection_id}/upload")
        ).status_code == 404
        assert (
            await other_client.get(f"/v1/collections/{collection_id}/events")
        ).status_code == 404
        assert (
            await other_client.get(f"/v1/collections/{collection_id}/integrity")
        ).status_code == 404
        deletion = await other_client.delete(
            f"/v1/collections/{collection_id}",
            headers={"Idempotency-Key": "cross-tenant-delete"},
        )
        assert deletion.status_code == 404

    async with app.state.database.sessions() as session:
        row = await session.get(Collection, uuid.UUID(collection_id))
    assert row is not None
    assert row.status == "CREATED"
