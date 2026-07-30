from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pytest
from akc_api.database import Base
from akc_api.knowledge_gpu import (
    KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT,
    StageAResult,
    canonical_json_bytes,
)
from akc_api.knowledge_pipeline import build_stage_a_input, build_stage_b_inputs
from akc_api.models import (
    Block,
    CreditAccount,
    CreditLedger,
    Document,
    DocumentSemanticClassification,
    GpuProviderInvocation,
    KnowledgeNote,
    Page,
    ProcessingJob,
    Project,
    Tenant,
    User,
)
from akc_api.services import run_compile_job
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

MODEL_REVISION = "a" * 40
IMAGE_DIGEST = "sha256:" + ("b" * 64)
PROMPT_REVISION = "sha256:" + ("c" * 64)
SCHEMA_REVISION = "sha256:" + ("d" * 64)


@dataclass(frozen=True)
class QwenSettings:
    env: Literal["test"] = "test"
    knowledge_provider: Literal["qwen_durable"] = "qwen_durable"
    private_mode: bool = True
    external_ocr_enabled: bool = False
    qwen_endpoint_id: str = "knowledge-qwen"
    qwen_provider_key: str = "qwen3_5_4b"
    qwen_model_revision: str = MODEL_REVISION
    qwen_runtime_image_digest: str = IMAGE_DIGEST
    qwen_adapter_version: str = "qwen-adapter-1.0.0"
    qwen_prompt_revision: str = PROMPT_REVISION
    qwen_knowledge_schema_sha256: str = SCHEMA_REVISION
    qwen_max_attempts: int = 3


class MemoryDerivedStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_derived(self, object_key: str, data: bytes) -> None:
        self.objects[object_key] = data

    async def read_derived(self, object_key: str) -> bytes:
        return self.objects[object_key]


@dataclass(frozen=True)
class FixtureIds:
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID
    page_id: uuid.UUID
    block_ids: tuple[uuid.UUID, ...]
    job_id: uuid.UUID


async def _seed(
    sessions: async_sessionmaker[AsyncSession],
    *,
    block_texts: tuple[str, ...] = ("A fact grounded in the source.",),
) -> FixtureIds:
    ids = FixtureIds(
        tenant_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        page_id=uuid.uuid4(),
        block_ids=tuple(uuid.uuid4() for _ in block_texts),
        job_id=uuid.uuid4(),
    )
    user_id = uuid.uuid4()
    async with sessions() as session:
        session.add_all(
            [
                Tenant(
                    id=ids.tenant_id,
                    slug=f"t-{ids.tenant_id.hex[:8]}",
                    name="Tenant",
                ),
                User(
                    id=user_id,
                    email=f"{user_id.hex}@example.com",
                    password_hash="unused",  # noqa: S106
                    display_name="Owner",
                ),
                Project(
                    id=ids.project_id,
                    tenant_id=ids.tenant_id,
                    name="Project",
                    created_by=user_id,
                ),
                Document(
                    id=ids.document_id,
                    tenant_id=ids.tenant_id,
                    project_id=ids.project_id,
                    title="Grounded text",
                    document_type="txt",
                    language_codes=[],
                    status="READY",
                    active_version=1,
                ),
                Page(
                    id=ids.page_id,
                    tenant_id=ids.tenant_id,
                    document_id=ids.document_id,
                    page_number=1,
                    status="PREFLIGHTED",
                    route="native",
                    route_policy_version="test-policy-1",
                    preflight_metrics={},
                    quality_metrics={"schema_valid": True},
                ),
                CreditAccount(
                    tenant_id=ids.tenant_id,
                    balance=Decimal("10"),
                    reserved=Decimal("1"),
                ),
                ProcessingJob(
                    id=ids.job_id,
                    tenant_id=ids.tenant_id,
                    project_id=ids.project_id,
                    document_id=ids.document_id,
                    job_type="compile",
                    status="queued",
                    requested_options={},
                    cost_estimate={"reserved": "1", "expected": "0.5"},
                ),
            ]
        )
        session.add_all(
            Block(
                id=block_id,
                tenant_id=ids.tenant_id,
                document_id=ids.document_id,
                page_id=ids.page_id,
                block_order=index,
                block_type="heading" if index % 2 == 0 else "paragraph",
                origin="native_extracted",
                bbox1000=[0, 0, 1000, 1000],
                source_text=text,
                normalized_text=text,
                markdown=text,
                confidence=1.0,
                revision=1,
            )
            for index, (block_id, text) in enumerate(
                zip(ids.block_ids, block_texts, strict=True)
            )
        )
        await session.commit()
    return ids


def _stage_result(
    stage_input: dict[str, Any],
    *,
    separate_sections: bool = False,
    summary_suffix: str = "",
) -> dict[str, Any]:
    stage = stage_input["stage"]
    base: dict[str, Any] = {
        "schemaVersion": "knowledge-pipeline-result-1.0.0",
        "stage": stage,
        "unitId": stage_input["unit_id"],
    }
    if stage == "A":
        block_ids = [block["block_id"] for block in stage_input["blocks"]]
        sections = (
            [
                {
                    "sectionId": f"section.{index}",
                    "title": f"Section {index}",
                    "blockIds": [block_id],
                }
                for index, block_id in enumerate(block_ids)
            ]
            if separate_sections
            else [
                {
                    "sectionId": "section.document",
                    "title": stage_input["title"],
                    "blockIds": block_ids,
                }
            ]
        )
        base.update(
            {
                "classification": {
                    "documentType": "research_note",
                    "secondaryTypes": ["technical"],
                    "language": "ko-KR",
                    "languages": ["ko-KR"],
                    "topics": ["knowledge compilation"],
                    "domain": ["software engineering"],
                    "structureProfile": "sectioned",
                    "riskTier": "low",
                    "contains": {
                        "tables": False,
                        "formulas": False,
                        "figures": False,
                        "citations": False,
                        "personalData": False,
                    },
                    "evidenceBlockIds": [block_ids[0]],
                    "confidence": 0.95,
                },
                "sections": sections,
            }
        )
    elif stage == "B":
        evidence = list(
            dict.fromkeys(
                fragment["evidence_block_id"]
                for fragment in stage_input["fragments"]
            )
        )
        base.update(
            {
                "sectionId": stage_input["section_id"],
                "notes": [
                    {
                        "noteId": "grounded.summary",
                        "title": stage_input["section_title"],
                        "noteType": "document",
                        "contentOrigin": "ai_summarized",
                        "evidenceBlockIds": evidence,
                        "summary": f"Evidence-bound summary{summary_suffix}.",
                        "claims": [],
                        "aliases": [],
                        "tags": ["grounded"],
                        "relatedNoteCandidates": [],
                        "reviewStatus": "pending",
                    }
                ],
                "relations": [],
                "conflicts": [],
            }
        )
    elif stage == "C":
        base["mergeGroups"] = [
            {
                "groupId": f"group.{index}",
                "canonicalCandidateId": candidate["candidate_id"],
                "memberCandidateIds": [candidate["candidate_id"]],
                "comparedCandidateIds": [candidate["candidate_id"]],
                "evidenceBlockIds": candidate["evidence_block_ids"],
                "reason": "Kept separate because no equivalent semantic descriptor exists.",
            }
            for index, candidate in enumerate(stage_input["candidates"])
        ]
    else:
        base.update(
            {
                "retrievalStatus": stage_input["retrieval_status"],
                "links": [],
            }
        )
    return base


async def _queued(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    stage: str | None = None,
) -> list[GpuProviderInvocation]:
    rows = list(
        (
            await session.scalars(
                select(GpuProviderInvocation)
                .where(GpuProviderInvocation.job_id == job_id)
                .order_by(GpuProviderInvocation.created_at, GpuProviderInvocation.id)
            )
        ).all()
    )
    return [
        row
        for row in rows
        if stage is None or row.options.get("knowledge_stage") == stage
    ]


async def _complete_stage(
    sessions: async_sessionmaker[AsyncSession],
    store: MemoryDerivedStore,
    job_id: uuid.UUID,
    stage: str,
    *,
    separate_sections: bool = False,
    summary_suffix: str = "",
) -> None:
    async with sessions() as session:
        rows = await _queued(session, job_id, stage=stage)
        assert rows
        for invocation in rows:
            stage_input = json.loads(store.objects[invocation.input_object_key])
            result = _stage_result(
                stage_input,
                separate_sections=separate_sections,
                summary_suffix=summary_suffix,
            )
            output_payload = {
                "ok": True,
                "schema_version": "1.0",
                "worker_kind": "knowledge",
                "knowledge_stage_result": result,
                "warnings": [],
                "provider_metrics": {
                    "prompt_sha256": PROMPT_REVISION,
                    "knowledge_schema_sha256": SCHEMA_REVISION,
                    "knowledge_stage": stage,
                    "knowledge_unit_id": stage_input["unit_id"],
                    "unsupported_claim_count": 0,
                },
            }
            output_body = json.dumps(
                output_payload,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            store.objects[invocation.output_object_key] = output_body
            output_sha = hashlib.sha256(output_body).hexdigest()
            invocation.status = "completed"
            invocation.result_manifest_sha256 = hashlib.sha256(
                f"manifest:{invocation.id}:{output_sha}".encode()
            ).hexdigest()
            invocation.result_manifest = {
                "output_object_key": invocation.output_object_key,
                "output_sha256": f"sha256:{output_sha}",
                "knowledge_attestation": {
                    "artifact_contract": KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT,
                    "prompt_revision": PROMPT_REVISION,
                    "knowledge_schema_sha256": SCHEMA_REVISION,
                    "knowledge_stage": stage,
                    "knowledge_unit_id": stage_input["unit_id"],
                    "unsupported_claim_count": 0,
                },
            }
            assert (
                hashlib.sha256(store.objects[invocation.input_object_key]).hexdigest()
                == invocation.input_sha256
            )
        await session.commit()


async def _run(
    sessions: async_sessionmaker[AsyncSession],
    store: MemoryDerivedStore,
    job_id: uuid.UUID,
) -> None:
    async with sessions() as session:
        await run_compile_job(
            session=session,
            job_id=job_id,
            settings=QwenSettings(),
            object_store=store,  # type: ignore[arg-type]
        )


async def _drive_pipeline(
    sessions: async_sessionmaker[AsyncSession],
    store: MemoryDerivedStore,
    job_id: uuid.UUID,
    *,
    summary_suffix: str = "",
) -> None:
    await _run(sessions, store, job_id)
    for stage in ("A", "B", "C", "D"):
        async with sessions() as session:
            before = len(await _queued(session, job_id))
        await _run(sessions, store, job_id)
        async with sessions() as session:
            assert len(await _queued(session, job_id)) == before
        await _complete_stage(
            sessions,
            store,
            job_id,
            stage,
            summary_suffix=summary_suffix,
        )
        await _run(sessions, store, job_id)


@pytest.mark.asyncio
async def test_staged_qwen_resumes_without_whole_document_or_double_charge(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'durable-qwen.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    ids = await _seed(sessions)
    store = MemoryDerivedStore()
    await _drive_pipeline(sessions, store, ids.job_id)
    await _run(sessions, store, ids.job_id)

    async with sessions() as session:
        job = await session.get(ProcessingJob, ids.job_id)
        document = await session.get(Document, ids.document_id)
        invocations = await _queued(session, ids.job_id)
        assert job is not None and job.status == "completed"
        assert [row.options["knowledge_stage"] for row in invocations] == [
            "A",
            "B",
            "C",
            "D",
        ]
        assert all(
            row.options["artifact_contract"]
            == KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT
            for row in invocations
        )
        assert all(
            "A fact grounded" not in json.dumps(row.options)
            for row in invocations
        )
        stage_inputs = {
            row.options["knowledge_stage"]: json.loads(
                store.objects[row.input_object_key]
            )
            for row in invocations
        }
        assert stage_inputs["A"]["blocks"][0]["preview"]
        assert "text" not in stage_inputs["A"]["blocks"][0]
        assert "A fact grounded" in stage_inputs["B"]["fragments"][0]["text"]
        assert "fragments" not in stage_inputs["C"]
        assert "source_text" not in json.dumps(stage_inputs["C"])
        assert stage_inputs["D"]["retrieval_status"] == "provider_unverified"
        assert stage_inputs["D"]["retrieval_candidates"] == []
        classification = await session.scalar(
            select(DocumentSemanticClassification).where(
                DocumentSemanticClassification.document_id == ids.document_id
            )
        )
        assert classification is not None
        assert classification.classification["documentType"] == "research_note"
        assert classification.provenance["invocations"][0]["stage"] == "A"
        assert document is not None
        assert document.document_type == "txt"
        assert document.language_codes == ["ko-KR"]
        notes = list(
            await session.scalars(
                select(KnowledgeNote).where(
                    KnowledgeNote.document_id == ids.document_id,
                    KnowledgeNote.is_active.is_(True),
                )
            )
        )
        assert len(notes) == 1
        assert notes[0].compile_provenance["invocations"]
        assert (
            await session.scalar(
                select(func.count(CreditLedger.id)).where(
                    CreditLedger.tenant_id == ids.tenant_id,
                    CreditLedger.entry_type == "consume",
                )
            )
            == 1
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_recompile_preserves_old_note_and_activates_new_revision(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'recompile.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    ids = await _seed(sessions)
    store = MemoryDerivedStore()
    await _drive_pipeline(sessions, store, ids.job_id, summary_suffix=" v1")

    next_job = uuid.uuid4()
    async with sessions() as session:
        block = await session.get(Block, ids.block_ids[0])
        account = await session.get(CreditAccount, ids.tenant_id)
        assert block is not None and account is not None
        block.source_text = "A user-edited fact."
        block.normalized_text = "A user-edited fact."
        block.markdown = "A user-edited fact."
        block.revision += 1
        account.reserved = Decimal(account.reserved) + Decimal("1")
        session.add(
            ProcessingJob(
                id=next_job,
                tenant_id=ids.tenant_id,
                project_id=ids.project_id,
                document_id=ids.document_id,
                job_type="compile",
                status="queued",
                requested_options={},
                cost_estimate={"reserved": "1", "expected": "0.5"},
            )
        )
        await session.commit()
    await _drive_pipeline(sessions, store, next_job, summary_suffix=" v2")
    await _run(sessions, store, next_job)

    async with sessions() as session:
        notes = list(
            (
                await session.scalars(
                    select(KnowledgeNote)
                    .where(KnowledgeNote.document_id == ids.document_id)
                    .order_by(KnowledgeNote.created_at, KnowledgeNote.id)
                )
            ).all()
        )
        assert len(notes) == 2
        assert notes[0].is_active is False
        assert notes[1].is_active is True
        assert notes[0].compile_input_sha256 != notes[1].compile_input_sha256
        assert "v1" in notes[0].content_markdown
        assert "v2" in notes[1].content_markdown
        assert (
            await session.scalar(
                select(func.count(CreditLedger.id)).where(
                    CreditLedger.tenant_id == ids.tenant_id,
                    CreditLedger.entry_type == "consume",
                )
            )
            == 2
        )
    await engine.dispose()


def test_large_multisection_document_is_bounded_per_b_unit() -> None:
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    page_id = uuid.uuid4()
    texts = tuple(
        f"Section {index} " + " ".join(f"term-{index}-{item}" for item in range(350))
        for index in range(24)
    )
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        project_id=project_id,
        title="Large document",
        document_type="txt",
        language_codes=[],
        status="READY",
        active_version=1,
    )
    page = Page(
        id=page_id,
        tenant_id=tenant_id,
        document_id=document_id,
        page_number=1,
        status="PREFLIGHTED",
        route="native",
        route_policy_version="test-policy-1",
        preflight_metrics={},
        quality_metrics={"schema_valid": True},
    )
    blocks = [
        Block(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            document_id=document_id,
            page_id=page_id,
            block_order=index,
            block_type="heading",
            origin="native_extracted",
            bbox1000=[0, 0, 1000, 1000],
            source_text=text,
            normalized_text=text,
            markdown=text,
            confidence=1.0,
            revision=1,
        )
        for index, text in enumerate(texts)
    ]
    stage_a = build_stage_a_input(
        document=document,
        blocks=blocks,
        pages=[page],
    )
    section_map = StageAResult.model_validate(
        _stage_result(
            stage_a.model_dump(mode="json"),
            separate_sections=True,
        )
    )
    stage_b = build_stage_b_inputs(
        document=document,
        blocks=blocks,
        pages=[page],
        section_map=section_map,
    )

    assert len(stage_b) >= len(texts)
    assert len(canonical_json_bytes(stage_a)) < 8 * 1024 * 1024
    assert {value.section_id for value in stage_b} == {
        f"section.{index}" for index in range(len(texts))
    }
    for value in stage_b:
        body = canonical_json_bytes(value)
        assert len(body) <= 1024 * 1024
        assert len(value.fragments) <= 32
        assert sum(len(fragment.text.encode()) for fragment in value.fragments) <= (
            512 * 1024
        )
