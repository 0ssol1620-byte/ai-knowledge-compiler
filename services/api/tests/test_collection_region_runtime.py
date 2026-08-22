from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from akc_api.collection_region_runtime import (
    RegionOutputCandidate,
    RegionPromotionError,
    promoted_region_text_by_block,
    record_region_output_attempt,
)
from akc_api.database import Database
from akc_api.models import (
    Block,
    Collection,
    CollectionFile,
    CollectionRegion,
    CollectionRegionAttempt,
    CollectionSourceRoot,
    Document,
    Page,
    PageAttempt,
    Project,
    Tenant,
    User,
    VerificationRecord,
)
from akc_api.settings import Settings
from akc_quality import RecoveryStage
from sqlalchemy import func, select


async def _seed_region(database: Database) -> dict[str, uuid.UUID | str]:
    original = "Revenue was 1,234.50 KRW."
    content_hash = hashlib.sha256(original.encode()).hexdigest()
    async with database.sessions() as session:
        tenant = Tenant(slug=f"region-{uuid.uuid4().hex}", name="Region Tenant")
        user = User(
            email=f"region-{uuid.uuid4().hex}@example.com",
            password_hash="not-used",  # noqa: S106 - inert ORM fixture.
            display_name="Region Operator",
        )
        session.add_all((tenant, user))
        await session.flush()
        project = Project(
            tenant_id=tenant.id,
            name="Region Project",
            description=None,
            created_by=user.id,
        )
        session.add(project)
        await session.flush()
        collection = Collection(
            tenant_id=tenant.id,
            project_id=project.id,
            name="Region Collection",
            description=None,
            created_by=user.id,
        )
        document = Document(
            tenant_id=tenant.id,
            project_id=project.id,
            source_file_id=None,
            title="Region source",
            document_type="pdf",
            page_count=1,
            status="COMPLETED",
        )
        session.add_all((collection, document))
        await session.flush()
        root = CollectionSourceRoot(
            tenant_id=tenant.id,
            collection_id=collection.id,
            display_name_ciphertext=b"x" * 29,
            metadata_key_id="test-key",
            source_fingerprint="1" * 64,
            created_by=user.id,
        )
        session.add(root)
        await session.flush()
        collection_file = CollectionFile(
            tenant_id=tenant.id,
            collection_id=collection.id,
            source_root_id=root.id,
            source_file_id=None,
            relative_path_ciphertext=b"y" * 29,
            display_name_ciphertext=b"z" * 29,
            metadata_key_id="test-key",
            relative_path_blind_index=b"b" * 32,
            relative_path_blind_index_key_id="test-key",
            size_bytes=100,
            expected_mime="application/pdf",
            sha256="2" * 64,
            status="verified",
        )
        page = Page(
            tenant_id=tenant.id,
            document_id=document.id,
            page_number=1,
            status="COMPLETED",
            route="paddle_fast",
        )
        session.add_all((collection_file, page))
        await session.flush()
        block = Block(
            tenant_id=tenant.id,
            document_id=document.id,
            page_id=page.id,
            block_order=0,
            block_type="paragraph",
            origin="ocr",
            bbox1000=[10, 10, 900, 100],
            source_text=original,
            normalized_text=original,
            content_hash=content_hash,
        )
        page_attempt = PageAttempt(
            tenant_id=tenant.id,
            page_id=page.id,
            attempt_number=1,
            trigger="analysis",
            status="COMPLETED",
            route="paddle_fast",
            route_profile="default",
            route_policy_version="v4-test",
            completed_at=page.updated_at,
        )
        session.add_all((block, page_attempt))
        await session.flush()
        region = CollectionRegion(
            tenant_id=tenant.id,
            collection_id=collection.id,
            collection_file_id=collection_file.id,
            document_id=document.id,
            page_id=page.id,
            stable_key=f"block:{block.id}",
            region_type="paragraph",
            bbox1000=block.bbox1000,
            status="discovered",
        )
        session.add(region)
        await session.commit()
        return {
            "tenant_id": tenant.id,
            "collection_id": collection.id,
            "region_id": region.id,
            "block_id": block.id,
            "page_id": page.id,
            "page_attempt_id": page_attempt.id,
            "content_hash": content_hash,
            "original": original,
        }


def _candidate(scope: dict[str, uuid.UUID | str]) -> RegionOutputCandidate:
    output = "Revenue was 1,234.50 KRW. Restored omitted row."
    return RegionOutputCandidate(
        attempt_id=uuid.uuid4(),
        route="mineru_overlap_tile",
        status="auto_repaired",
        source_block_id=scope["block_id"],
        source_block_content_hash=scope["content_hash"],
        source_page_attempt_id=scope["page_attempt_id"],
        output_text=output,
        output_sha256=hashlib.sha256(output.encode()).hexdigest(),
        recovery_stage=RecoveryStage.OVERLAPPING_TILE,
        independent_signal_count=2,
        parser_revision="mineru-region@3.4",
        model_revision="mineru-vlm@3.4",
        provider_revision="local-test-provider@1",
        attestation_sha256="a" * 64,
    )


@pytest.mark.asyncio
async def test_region_output_promotes_without_overwriting_page_or_block(tmp_path: Path) -> None:
    database = Database(
        Settings(
            env="test",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'region.db').as_posix()}",
            data_dir=tmp_path / "data",
        )
    )
    await database.create_schema()
    scope = await _seed_region(database)
    candidate = _candidate(scope)
    try:
        async with database.sessions() as session:
            attempt = await record_region_output_attempt(
                session,
                tenant_id=scope["tenant_id"],
                collection_id=scope["collection_id"],
                region_id=scope["region_id"],
                candidate=candidate,
            )
            await session.commit()
            assert attempt.attempt_number == 1
        async with database.sessions() as session:
            repeated = await record_region_output_attempt(
                session,
                tenant_id=scope["tenant_id"],
                collection_id=scope["collection_id"],
                region_id=scope["region_id"],
                candidate=candidate,
            )
            await session.commit()
            block = await session.get(Block, scope["block_id"])
            page = await session.get(Page, scope["page_id"])
            region = await session.get(CollectionRegion, scope["region_id"])
            attempts = list(await session.scalars(select(CollectionRegionAttempt)))
            assert repeated.id == candidate.attempt_id
            assert await session.scalar(select(func.count(CollectionRegionAttempt.id))) == 1
            assert await session.scalar(select(func.count(VerificationRecord.id))) == 1
            assert block is not None and block.normalized_text == scope["original"]
            assert block.content_hash == scope["content_hash"]
            assert block.revision == 1
            assert page is not None and page.route == "paddle_fast"
            assert region is not None and region.status == "auto_repaired"
            page_attempt = await session.get(PageAttempt, scope["page_attempt_id"])
            assert page_attempt is not None
            assert promoted_region_text_by_block((region,), attempts) == {
                scope["block_id"]: candidate.output_text
            }
            assert promoted_region_text_by_block(
                (region,),
                attempts,
                blocks=(block,),
                latest_page_attempts={page.id: page_attempt},
            ) == {scope["block_id"]: candidate.output_text}
            block.content_hash = "3" * 64
            assert (
                promoted_region_text_by_block(
                    (region,),
                    attempts,
                    blocks=(block,),
                    latest_page_attempts={page.id: page_attempt},
                )
                == {}
            )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_region_promotion_rejects_stale_page_attempt(tmp_path: Path) -> None:
    database = Database(
        Settings(
            env="test",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'stale.db').as_posix()}",
            data_dir=tmp_path / "data",
        )
    )
    await database.create_schema()
    scope = await _seed_region(database)
    try:
        async with database.sessions() as session:
            session.add(
                PageAttempt(
                    tenant_id=scope["tenant_id"],
                    page_id=scope["page_id"],
                    attempt_number=2,
                    trigger="user_retry",
                    status="COMPLETED",
                    route="paddle_vl",
                    route_profile="recovery",
                    route_policy_version="v4-test",
                )
            )
            await session.commit()
        async with database.sessions() as session:
            with pytest.raises(RegionPromotionError, match="stale"):
                await record_region_output_attempt(
                    session,
                    tenant_id=scope["tenant_id"],
                    collection_id=scope["collection_id"],
                    region_id=scope["region_id"],
                    candidate=_candidate(scope),
                )
            assert await session.scalar(select(func.count(CollectionRegionAttempt.id))) == 0
    finally:
        await database.dispose()
