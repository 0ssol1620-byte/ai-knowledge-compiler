from __future__ import annotations

import hashlib
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from akc_api.collection_authority import (
    AuthorityFactPayload,
    AuthorityIngestionError,
    VerifiedAuthorityReceipt,
    ingest_verified_authority,
    materialize_authority_geometry,
)
from akc_api.database import Database
from akc_api.models import (
    AuditEvent,
    AuthorityFact,
    AuthorityMapping,
    Collection,
    CollectionFile,
    CollectionRegion,
    CollectionSourceRoot,
    Document,
    Page,
    Project,
    Tenant,
    User,
    VerificationRecord,
)
from akc_api.settings import Settings
from akc_cir import BBox1000
from akc_quality import (
    GeometrySource,
    GeometryWord,
    GeometryWordRole,
    NumericCellKey,
    ParserNumericCell,
)
from sqlalchemy import func, select


class _DartAdapter:
    adapter_id = "opendart-xbrl"

    def __init__(self, source: bytes, *, value: str = "1234.50") -> None:
        self.source = source
        self.value = value

    async def fetch(self, *, collection_id: uuid.UUID) -> VerifiedAuthorityReceipt:
        del collection_id
        return VerifiedAuthorityReceipt(
            source_kind="dart",
            source_revision="receipt-20260731000001",
            source_bytes=self.source,
            source_sha256=hashlib.sha256(self.source).hexdigest(),
            adapter_id=self.adapter_id,
            adapter_revision="opendart-adapter@1.0.0",
            verification_status="source_bytes_verified",
            facts=(
                AuthorityFactPayload(
                    stable_key="revenue|2026-06-30|KRW",
                    normalized_value=self.value,
                    unit="KRW",
                    currency="KRW",
                    period="2026-Q2",
                    context={
                        "entity_id": "corp-001",
                        "statement": "income_statement",
                        "concept": "Revenue",
                        "xbrl_label": "Revenue",
                        "instant": "2026-06-30",
                        "scale": 1,
                        "dimensions": {},
                        "page": 1,
                        "row_key": "Revenue",
                        "column_key": "2026-Q2",
                    },
                    source_locator={
                        "receipt_number": "20260731000001",
                        "report_code": "11012",
                        "xml_fact_id": "fact-revenue",
                        "xml_document_uri": "https://dart.fss.or.kr/filing.xml",
                        "pdf_document_uri": "https://dart.fss.or.kr/filing.pdf",
                    },
                ),
            ),
        )


async def _scope(database: Database) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with database.sessions() as session:
        tenant = Tenant(slug=f"authority-{uuid.uuid4().hex}", name="Authority Tenant")
        user = User(
            email=f"authority-{uuid.uuid4().hex}@example.com",
            password_hash="not-used",  # noqa: S106 - inert ORM fixture, never authenticated.
            display_name="Authority Operator",
        )
        session.add_all((tenant, user))
        await session.flush()
        project = Project(
            tenant_id=tenant.id,
            name="Authority Project",
            description=None,
            created_by=user.id,
        )
        session.add(project)
        await session.flush()
        collection = Collection(
            tenant_id=tenant.id,
            project_id=project.id,
            name="Authority Collection",
            description=None,
            created_by=user.id,
        )
        session.add(collection)
        await session.commit()
        return tenant.id, user.id, collection.id


async def _verified_region(
    database: Database,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
) -> uuid.UUID:
    async with database.sessions() as session:
        collection = await session.scalar(
            select(Collection).where(
                Collection.tenant_id == tenant_id,
                Collection.id == collection_id,
            )
        )
        assert collection is not None
        document = Document(
            tenant_id=tenant_id,
            project_id=collection.project_id,
            source_file_id=None,
            title="Authority filing",
            document_type="pdf",
            page_count=1,
            status="COMPLETED",
        )
        root = CollectionSourceRoot(
            tenant_id=tenant_id,
            collection_id=collection_id,
            display_name_ciphertext=b"x" * 29,
            metadata_key_id="test-key",
            source_fingerprint="3" * 64,
            created_by=collection.created_by,
        )
        session.add_all((document, root))
        await session.flush()
        collection_file = CollectionFile(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_root_id=root.id,
            source_file_id=None,
            relative_path_ciphertext=b"y" * 29,
            display_name_ciphertext=b"z" * 29,
            metadata_key_id="test-key",
            relative_path_blind_index=b"b" * 32,
            relative_path_blind_index_key_id="test-key",
            size_bytes=100,
            expected_mime="application/pdf",
            sha256="4" * 64,
            status="verified",
        )
        page = Page(
            tenant_id=tenant_id,
            document_id=document.id,
            page_number=1,
            status="COMPLETED",
            route="native",
        )
        session.add_all((collection_file, page))
        await session.flush()
        region = CollectionRegion(
            tenant_id=tenant_id,
            collection_id=collection_id,
            collection_file_id=collection_file.id,
            document_id=document.id,
            page_id=page.id,
            stable_key="table:revenue:2026-q2",
            region_type="table",
            bbox1000=[100, 100, 900, 600],
            status="verified",
        )
        session.add(region)
        await session.commit()
        return region.id


def _parser_cell(*, value: str = "1234.50") -> ParserNumericCell:
    key = NumericCellKey(
        entity_id="corp-001",
        statement="income_statement",
        concept="Revenue",
        instant=date(2026, 6, 30),
        unit="KRW",
        scale=1,
        page=1,
        row_key="Revenue",
        column_key="2026-Q2",
    )
    return ParserNumericCell(
        parser_cell_id="cell-revenue-2026-q2",
        key=key,
        geometry_source=GeometrySource.PDF_CELL,
        source_document_uri="https://dart.fss.or.kr/filing.pdf",
        label="Revenue",
        row_header="Revenue",
        column_header="2026-Q2",
        original_parser_number=value,
        parser_value=Decimal(value),
        bbox1000=BBox1000((600, 200, 800, 250)),
        words=(
            GeometryWord(
                text="Revenue",
                bbox1000=BBox1000((100, 200, 300, 250)),
                role=GeometryWordRole.ROW_HEADER,
            ),
            GeometryWord(
                text=value,
                bbox1000=BBox1000((620, 205, 780, 245)),
                role=GeometryWordRole.VALUE,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_verified_authority_upsert_is_idempotent_and_audited(tmp_path: Path) -> None:
    database = Database(
        Settings(
            env="test",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'authority.db').as_posix()}",
            data_dir=tmp_path / "data",
        )
    )
    await database.create_schema()
    tenant_id, user_id, collection_id = await _scope(database)
    adapter = _DartAdapter(b"<xbrl><Revenue>1234.50</Revenue></xbrl>")
    try:
        async with database.sessions() as session:
            first = await ingest_verified_authority(
                session,
                tenant_id=tenant_id,
                collection_id=collection_id,
                actor_id=user_id,
                adapter=adapter,
            )
            await session.commit()
        async with database.sessions() as session:
            second = await ingest_verified_authority(
                session,
                tenant_id=tenant_id,
                collection_id=collection_id,
                actor_id=user_id,
                adapter=adapter,
            )
            await session.commit()
            assert await session.scalar(select(func.count(AuthorityFact.id))) == 1
            assert await session.scalar(select(func.count(AuditEvent.id))) == 1
        assert first.inserted_count == 1
        assert first.reused_count == 0
        assert second.inserted_count == 0
        assert second.reused_count == 1
        assert second.fact_ids == first.fact_ids
        assert second.audit_event_id == first.audit_event_id
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_authority_geometry_is_idempotent_and_failed_batch_revokes_stale_match(
    tmp_path: Path,
) -> None:
    database = Database(
        Settings(
            env="test",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'geometry.db').as_posix()}",
            data_dir=tmp_path / "data",
        )
    )
    await database.create_schema()
    tenant_id, user_id, collection_id = await _scope(database)
    region_id = await _verified_region(
        database,
        tenant_id=tenant_id,
        collection_id=collection_id,
    )
    adapter = _DartAdapter(b"<xbrl><Revenue>1234.50</Revenue></xbrl>")
    cell = _parser_cell()
    try:
        async with database.sessions() as session:
            await ingest_verified_authority(
                session,
                tenant_id=tenant_id,
                collection_id=collection_id,
                actor_id=user_id,
                adapter=adapter,
            )
            first = await materialize_authority_geometry(
                session,
                tenant_id=tenant_id,
                collection_id=collection_id,
                actor_id=user_id,
                parser_cells=(cell,),
                region_ids_by_parser_cell_id={cell.parser_cell_id: region_id},
            )
            await session.commit()
        async with database.sessions() as session:
            second = await materialize_authority_geometry(
                session,
                tenant_id=tenant_id,
                collection_id=collection_id,
                actor_id=user_id,
                parser_cells=(cell,),
                region_ids_by_parser_cell_id={cell.parser_cell_id: region_id},
            )
            await session.commit()
            assert await session.scalar(select(func.count(AuthorityMapping.id))) == 1
            assert await session.scalar(select(func.count(VerificationRecord.id))) == 1
        assert first.state == "authority_verified"
        assert first.matched_count == 1
        assert second.state == "authority_verified"
        assert second.mapping_ids == first.mapping_ids
        assert second.audit_event_id == first.audit_event_id

        bad_cell = _parser_cell(value="9999.00")
        async with database.sessions() as session:
            failed = await materialize_authority_geometry(
                session,
                tenant_id=tenant_id,
                collection_id=collection_id,
                actor_id=user_id,
                parser_cells=(bad_cell,),
                region_ids_by_parser_cell_id={bad_cell.parser_cell_id: region_id},
            )
            await session.commit()
            mapping = await session.scalar(select(AuthorityMapping))
            assert mapping is not None
            assert mapping.mapping_status == "rejected"
            verification = await session.scalar(select(VerificationRecord))
            assert verification is not None
            assert verification.status == "rejected"
        assert failed.state == "unresolved"
        assert failed.matched_count == 0
        assert failed.rejected_count == 1
        assert failed.numeric_result.hard_gate.critical_numeric_mismatch == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_authority_geometry_rejects_unverified_region(tmp_path: Path) -> None:
    database = Database(
        Settings(
            env="test",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'region-scope.db').as_posix()}",
            data_dir=tmp_path / "data",
        )
    )
    await database.create_schema()
    tenant_id, user_id, collection_id = await _scope(database)
    region_id = await _verified_region(
        database,
        tenant_id=tenant_id,
        collection_id=collection_id,
    )
    cell = _parser_cell()
    try:
        async with database.sessions() as session:
            await ingest_verified_authority(
                session,
                tenant_id=tenant_id,
                collection_id=collection_id,
                actor_id=user_id,
                adapter=_DartAdapter(b"<xbrl><Revenue>1234.50</Revenue></xbrl>"),
            )
            region = await session.get(CollectionRegion, region_id)
            assert region is not None
            region.status = "unresolved"
            with pytest.raises(AuthorityIngestionError, match="verified regions"):
                await materialize_authority_geometry(
                    session,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    actor_id=user_id,
                    parser_cells=(cell,),
                    region_ids_by_parser_cell_id={cell.parser_cell_id: region_id},
                )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_authority_ingestion_rejects_nondeterministic_fact_for_same_source(
    tmp_path: Path,
) -> None:
    database = Database(
        Settings(
            env="test",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'conflict.db').as_posix()}",
            data_dir=tmp_path / "data",
        )
    )
    await database.create_schema()
    tenant_id, user_id, collection_id = await _scope(database)
    source = b"<xbrl><Revenue>1234.50</Revenue></xbrl>"
    try:
        async with database.sessions() as session:
            await ingest_verified_authority(
                session,
                tenant_id=tenant_id,
                collection_id=collection_id,
                actor_id=user_id,
                adapter=_DartAdapter(source),
            )
            await session.commit()
        async with database.sessions() as session:
            with pytest.raises(AuthorityIngestionError, match="non-deterministic"):
                await ingest_verified_authority(
                    session,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    actor_id=user_id,
                    adapter=_DartAdapter(source, value="9999.00"),
                )
    finally:
        await database.dispose()


def test_authority_receipt_rejects_unverified_source_bytes() -> None:
    with pytest.raises(ValueError, match="digest mismatch"):
        VerifiedAuthorityReceipt(
            source_kind="sec",
            source_revision="accession-1",
            source_bytes=b"actual",
            source_sha256="0" * 64,
            adapter_id="sec-inline-xbrl",
            adapter_revision="1.0.0",
            verification_status="source_bytes_verified",
            facts=(
                AuthorityFactPayload(
                    stable_key="fact-1",
                    normalized_value="1",
                    context={},
                    source_locator={},
                ),
            ),
        )
