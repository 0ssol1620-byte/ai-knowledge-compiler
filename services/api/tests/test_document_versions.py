from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_api.database import Database
from akc_api.document_versions import (
    archive_active_document_version,
    clear_active_document_projection,
    document_version_diff,
    read_public_document_version_snapshot,
)
from akc_api.models import (
    Block,
    BlockRevision,
    Document,
    DocumentSemanticClassification,
    DocumentVersion,
    KnowledgeNote,
    Membership,
    Page,
    PageAsset,
    Project,
    Relation,
    ReviewItem,
    SourceFile,
    Tenant,
    UploadSession,
    User,
)
from akc_api.settings import Settings
from akc_api.storage import LocalObjectStore
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_document_version_snapshot_is_immutable_and_projection_is_replaceable(
    tmp_path: Path,
) -> None:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'versions.db').as_posix()}",
        data_dir=tmp_path / "data",
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
    )
    database = Database(settings)
    await database.create_schema()
    store = LocalObjectStore(settings)
    now = datetime(2026, 7, 29, tzinfo=UTC)
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    source_id = uuid.uuid4()
    document_id = uuid.uuid4()
    page_id = uuid.uuid4()
    block_id = uuid.uuid4()
    password_digest = f"bounded-test-{uuid.uuid4().hex}"
    try:
        async with database.sessions() as session:
            session.add_all(
                [
                    Tenant(id=tenant_id, slug="versions", name="Versions"),
                    User(
                        id=user_id,
                        email="versions@example.com",
                        password_hash=password_digest,
                        display_name="Version Owner",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Membership(tenant_id=tenant_id, user_id=user_id, role="owner"),
                    Project(
                        id=project_id,
                        tenant_id=tenant_id,
                        name="Versioned Project",
                        created_by=user_id,
                    ),
                ]
            )
            await session.flush()
            upload = UploadSession(
                id=upload_id,
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                document_version=1,
                created_by=user_id,
                original_filename="source.pdf",
                safe_filename="source.pdf",
                expected_mime="application/pdf",
                expected_size=128,
                expected_sha256="a" * 64,
                object_key="tenants/t/uploads/source",
                status="completed",
                expires_at=now,
                completed_at=now,
            )
            session.add(upload)
            await session.flush()
            source = SourceFile(
                id=source_id,
                tenant_id=tenant_id,
                project_id=project_id,
                upload_id=upload_id,
                original_filename="source.pdf",
                safe_filename="source.pdf",
                mime_type="application/pdf",
                size_bytes=128,
                sha256="a" * 64,
                storage_key="tenants/t/sources/source",
                antivirus_status="clean",
                uploaded_by=user_id,
            )
            session.add(source)
            await session.flush()
            document = Document(
                id=document_id,
                tenant_id=tenant_id,
                project_id=project_id,
                source_file_id=source_id,
                title="Immutable source",
                document_type="pdf",
                language_codes=["en"],
                page_count=1,
                active_version=1,
                cir_schema_version="cir-1.0.0",
                status="COMPLETED",
            )
            version = DocumentVersion(
                tenant_id=tenant_id,
                document_id=document_id,
                version=1,
                source_file_id=source_id,
                source_sha256="a" * 64,
                source_filename="source.pdf",
                source_mime_type="application/pdf",
                source_size_bytes=128,
                policy_version="route-v1",
                model_revision="model-v1",
                prompt_revision="prompt-v1",
                input_revision_hash="b" * 64,
                status="processed",
            )
            page = Page(
                id=page_id,
                tenant_id=tenant_id,
                document_id=document_id,
                page_number=1,
                width_pt=612,
                height_pt=792,
                status="COMPLETED",
                route="native",
                route_policy_version="route-v1",
                preflight_metrics={"source_coverage": 1.0},
                quality_metrics={"overall_score": 1.0},
            )
            session.add_all([document, version, page])
            await session.flush()
            session.add(
                PageAsset(
                    tenant_id=tenant_id,
                    page_id=page_id,
                    asset_type="preview",
                    storage_key="tenants/t/derived/preview.png",
                    sha256="c" * 64,
                    metadata_json={
                        "content_type": "image/png",
                        "size_bytes": 8,
                        "width": 1,
                        "height": 1,
                    },
                )
            )
            block = Block(
                id=block_id,
                tenant_id=tenant_id,
                document_id=document_id,
                page_id=page_id,
                block_order=0,
                block_type="paragraph",
                origin="user_edited",
                bbox1000=[1, 1, 999, 999],
                source_text="Source",
                normalized_text="Source",
                markdown="Verified source",
                engine="native",
                engine_revision="native-v1",
                confidence=1.0,
                content_hash="d" * 64,
                user_locked=True,
                revision=2,
            )
            session.add(block)
            await session.flush()
            session.add_all(
                [
                    BlockRevision(
                        tenant_id=tenant_id,
                        block_id=block_id,
                        base_revision=1,
                        new_revision=2,
                        operation="replace",
                        value="Verified source",
                        actor_id=user_id,
                    ),
                    ReviewItem(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        document_id=document_id,
                        page_id=page_id,
                        block_id=block_id,
                        severity="low",
                        category="manual_check",
                        status="resolved",
                        evidence={"code": "bounded_fixture"},
                        resolution={"action": "replace"},
                        resolved_by=user_id,
                        resolved_at=now,
                    ),
                    DocumentSemanticClassification(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        document_version=1,
                        compile_input_sha256="e" * 64,
                        classification={"semantic_type": "manual"},
                        provenance={"evidence_block_ids": [str(block_id)]},
                        provider_key="fixture",
                        model_revision="f" * 40,
                        runtime_image_digest="sha256:" + "1" * 64,
                        adapter_version="fixture-1",
                        prompt_revision="sha256:" + "2" * 64,
                        schema_sha256="sha256:" + "3" * 64,
                        is_active=True,
                    ),
                    KnowledgeNote(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        document_id=document_id,
                        document_version=1,
                        stable_key="fixture-note",
                        title="Fixture note",
                        note_type="summary",
                        content_markdown="Evidence-bound note.",
                        evidence_block_ids=[str(block_id)],
                        content_origin="derived",
                        compile_input_sha256="e" * 64,
                        pipeline_schema_sha256="sha256:" + "3" * 64,
                        model_revision="f" * 40,
                        compile_provenance={"stage": "B"},
                        is_active=True,
                    ),
                    Relation(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        document_id=document_id,
                        document_version=1,
                        source_relation_key="fixture-relation",
                        subject_id="subject",
                        predicate="supports",
                        object_id="object",
                        assertion_status="candidate",
                        confidence=0.9,
                        evidence_block_ids=[str(block_id)],
                        compile_input_sha256="e" * 64,
                        pipeline_schema_sha256="sha256:" + "3" * 64,
                        model_revision="f" * 40,
                        compile_provenance={"stage": "C"},
                        is_active=True,
                    ),
                ]
            )
            await session.commit()

        async with database.sessions() as session:
            document = await session.get(Document, document_id)
            assert document is not None
            snapshot = await archive_active_document_version(
                session,
                store=store,
                document=document,
                now=now,
            )
            version = await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.version == 1,
                )
            )
            assert version is not None
            assert version.cir_object_key is not None
            persisted = await store.read_derived(version.cir_object_key)
            assert persisted == snapshot.payload
            assert hashlib.sha256(persisted).hexdigest() == version.cir_snapshot_sha256
            decoded = json.loads(persisted)
            assert decoded["blocks"][0]["markdown"] == "Verified source"
            assert decoded["block_revisions"][0]["new_revision"] == 2
            assert decoded["review_items"][0]["status"] == "resolved"
            assert decoded["semantic_classifications"][0]["is_active"] is True
            assert decoded["knowledge_notes"][0]["stable_key"] == "fixture-note"
            assert decoded["relations"][0]["predicate"] == "supports"
            public_snapshot = await read_public_document_version_snapshot(
                store=store,
                version=version,
            )
            assert "storage_key" not in public_snapshot["source"]
            assert all("storage_key" not in asset for asset in public_snapshot["page_assets"])

            repeated = await archive_active_document_version(
                session,
                store=store,
                document=document,
                now=now,
            )
            assert repeated == snapshot
            await clear_active_document_projection(
                session,
                tenant_id=tenant_id,
                document_id=document_id,
            )
            await session.commit()

        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(Block).where(Block.document_id == document_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(DocumentSemanticClassification.is_active).where(
                        DocumentSemanticClassification.document_id == document_id
                    )
                )
                is False
            )
            assert (
                await session.scalar(
                    select(KnowledgeNote.is_active).where(KnowledgeNote.document_id == document_id)
                )
                is False
            )
            assert (
                await session.scalar(
                    select(Relation.is_active).where(Relation.document_id == document_id)
                )
                is False
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(Page).where(Page.document_id == document_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ReviewItem)
                    .where(ReviewItem.document_id == document_id)
                )
                == 0
            )

            older = await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.version == 1,
                )
            )
            assert older is not None
            newer = DocumentVersion(
                tenant_id=tenant_id,
                document_id=document_id,
                version=2,
                source_file_id=source_id,
                source_sha256="e" * 64,
                policy_version="route-v2",
                model_revision="model-v2",
                status="source_verified",
            )
            diff = document_version_diff(older, newer)
            assert diff["from_version"] == 1
            assert diff["to_version"] == 2
            assert set(diff["changes"]) >= {
                "source_sha256",
                "policy_version",
                "model_revision",
            }
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_document_version_snapshot_detects_object_tampering(tmp_path: Path) -> None:
    """The full lifecycle test covers data shape; this guards the object integrity branch."""

    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'tamper.db').as_posix()}",
        data_dir=tmp_path / "data",
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
    )
    database = Database(settings)
    await database.create_schema()
    store = LocalObjectStore(settings)
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    source_id = uuid.uuid4()
    document_id = uuid.uuid4()
    now = datetime(2026, 7, 29, tzinfo=UTC)
    password_digest = f"bounded-test-{uuid.uuid4().hex}"
    try:
        async with database.sessions() as session:
            session.add_all(
                [
                    Tenant(id=tenant_id, slug="tamper", name="Tamper"),
                    User(
                        id=user_id,
                        email="tamper@example.com",
                        password_hash=password_digest,
                        display_name="Tamper Owner",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Membership(tenant_id=tenant_id, user_id=user_id, role="owner"),
                    Project(
                        id=project_id,
                        tenant_id=tenant_id,
                        name="Tamper",
                        created_by=user_id,
                    ),
                ]
            )
            await session.flush()
            session.add(
                UploadSession(
                    id=upload_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_id=document_id,
                    document_version=1,
                    created_by=user_id,
                    original_filename="source.pdf",
                    safe_filename="source.pdf",
                    expected_mime="application/pdf",
                    expected_size=1,
                    expected_sha256="a" * 64,
                    object_key="tamper-upload",
                    status="completed",
                    expires_at=now,
                    completed_at=now,
                )
            )
            await session.flush()
            session.add(
                SourceFile(
                    id=source_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    upload_id=upload_id,
                    original_filename="source.pdf",
                    safe_filename="source.pdf",
                    mime_type="application/pdf",
                    size_bytes=1,
                    sha256="a" * 64,
                    storage_key="tamper-source",
                    antivirus_status="clean",
                    uploaded_by=user_id,
                )
            )
            await session.flush()
            session.add_all(
                [
                    Document(
                        id=document_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_file_id=source_id,
                        title="Tamper",
                        document_type="pdf",
                        active_version=1,
                        status="COMPLETED",
                    ),
                    DocumentVersion(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        version=1,
                        source_file_id=source_id,
                        source_sha256="a" * 64,
                        policy_version="route-v1",
                        model_revision="model-v1",
                        status="processed",
                    ),
                ]
            )
            await session.commit()

        async with database.sessions() as session:
            document = await session.get(Document, document_id)
            assert document is not None
            await archive_active_document_version(
                session,
                store=store,
                document=document,
                now=now,
            )
            version = await session.scalar(
                select(DocumentVersion).where(DocumentVersion.document_id == document_id)
            )
            assert version is not None and version.cir_object_key is not None
            await store.put_derived(version.cir_object_key, b"tampered")
            with pytest.raises(ValueError, match="integrity mismatch"):
                await read_public_document_version_snapshot(
                    store=store,
                    version=version,
                )
            with pytest.raises(ValueError, match="integrity mismatch"):
                await archive_active_document_version(
                    session,
                    store=store,
                    document=document,
                    now=now,
                )
    finally:
        await database.dispose()
