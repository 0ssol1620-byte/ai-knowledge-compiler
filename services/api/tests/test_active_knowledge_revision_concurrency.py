"""Concurrency evidence for active knowledge revision admission."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
from akc_api.models import Document, DocumentSemanticClassification, ProcessingJob
from akc_api.providers import ProviderUnavailable
from akc_api.services import (
    _flush_active_knowledge_revisions,
    _lock_document_compile_revision,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _semantic_revision(
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    compile_input: str,
) -> DocumentSemanticClassification:
    return DocumentSemanticClassification(
        tenant_id=tenant_id,
        document_id=document_id,
        document_version=1,
        compile_input_sha256=compile_input,
        classification={"documentType": "research_note"},
        provenance={"invocations": []},
        provider_key="qwen3_5_4b",
        model_revision="a" * 40,
        runtime_image_digest="sha256:" + ("b" * 64),
        adapter_version="qwen-adapter-1.0.0",
        prompt_revision="sha256:" + ("c" * 64),
        schema_sha256="sha256:" + ("d" * 64),
        is_active=True,
    )


@pytest.mark.asyncio
async def test_partial_unique_index_fences_concurrent_active_revisions(
    tmp_path: Path,
) -> None:
    database_path = (tmp_path / "active-revision-race.db").as_posix()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"timeout": 10},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    async with engine.begin() as connection:
        await connection.run_sync(DocumentSemanticClassification.__table__.create)

    async def insert(compile_input: str) -> str:
        async with sessions() as session:
            session.add(
                _semantic_revision(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    compile_input=compile_input,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return "conflict"
            return "committed"

    outcomes = await asyncio.gather(insert("1" * 64), insert("2" * 64))
    assert sorted(outcomes) == ["committed", "conflict"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_service_document_revision_lock_uses_for_update() -> None:
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    job = ProcessingJob(
        tenant_id=tenant_id,
        project_id=project_id,
        document_id=document_id,
        job_type="compile",
        status="running",
        requested_options={"document_version": 1},
        cost_estimate={},
    )
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        project_id=project_id,
        title="Document",
        document_type="pdf",
        language_codes=[],
        status="READY",
        active_version=1,
    )

    class RecordingSession:
        statement: Any = None

        async def scalar(self, statement: Any) -> Document:
            self.statement = statement
            return document

    session = RecordingSession()
    result = await _lock_document_compile_revision(
        session,  # type: ignore[arg-type]
        job=job,
        document_id=document_id,
        document_version=1,
    )

    assert result is document
    sql = str(
        session.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "FOR UPDATE" in sql
    assert "documents.active_version = 1" in sql
    assert "documents.deletion_requested_at IS NULL" in sql


@pytest.mark.asyncio
async def test_service_maps_active_pointer_integrity_conflict() -> None:
    class ConflictingSession:
        async def flush(self) -> None:
            raise IntegrityError(
                "INSERT",
                {},
                RuntimeError(
                    "UNIQUE constraint failed: "
                    "document_semantic_classifications.tenant_id, "
                    "document_semantic_classifications.document_id, "
                    "document_semantic_classifications.document_version"
                ),
            )

    with pytest.raises(
        ProviderUnavailable,
        match="DURABLE_QWEN_ACTIVE_REVISION_CONFLICT",
    ):
        await _flush_active_knowledge_revisions(
            ConflictingSession(),  # type: ignore[arg-type]
        )
