"""Read-only Knowledge API profiles, provenance, usage, and cost views."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from akc_cir import DocumentClassification
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.database import get_session
from akc_api.models import (
    Block,
    CreditAccount,
    CreditLedger,
    Document,
    DocumentSemanticClassification,
    DocumentVersion,
    KnowledgeNote,
    Page,
    ProcessingJob,
    Project,
    Relation,
    SourceFile,
)
from akc_api.project_access import (
    project_access_predicate,
    require_project_access,
)
from akc_api.security import Principal, get_principal

router = APIRouter(prefix="/v1")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]

_MAX_WINDOW = timedelta(days=366)


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SchemaProfile(WireModel):
    id: str
    kind: Literal["route", "knowledge", "export", "contract"]
    version: str
    description: str
    stable: bool


class SchemaProfilesResponse(WireModel):
    profiles: list[SchemaProfile]


class ProvenanceSource(WireModel):
    source_file_id: uuid.UUID
    sha256: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    original_filename: str


class ProvenanceBlock(WireModel):
    block_id: uuid.UUID
    page_id: uuid.UUID | None
    page_number: int | None = Field(default=None, ge=1)
    block_order: int
    block_type: str
    origin: str
    bbox1000: list[int] | None
    polygon_norm: list[list[float]] | None
    content_hash: str | None
    engine: str | None
    engine_revision: str | None
    confidence: float | None
    revision: int = Field(ge=1)


class ProvenanceKnowledgeNote(WireModel):
    note_id: uuid.UUID
    stable_key: str
    content_origin: str
    review_status: str
    evidence_block_ids: list[uuid.UUID]
    compile_provenance: dict[str, Any] = Field(default_factory=dict)


class ProvenanceRelation(WireModel):
    relation_id: uuid.UUID
    source_relation_key: str | None
    subject_id: str
    predicate: str
    object_id: str
    evidence_block_ids: list[uuid.UUID]
    compile_provenance: dict[str, Any] = Field(default_factory=dict)


class ProvenanceResponse(WireModel):
    document_id: uuid.UUID
    project_id: uuid.UUID
    cir_schema_version: str
    active_version: int
    version_policy: str | None
    model_revision: str | None
    prompt_revision: str | None
    source: ProvenanceSource
    blocks: list[ProvenanceBlock]
    knowledge_notes: list[ProvenanceKnowledgeNote]
    relations: list[ProvenanceRelation]
    source_coverage_ratio: float = Field(ge=0, le=1)


class KnowledgeNoteResponse(WireModel):
    id: uuid.UUID
    stable_key: str
    title: str
    note_type: str
    content_markdown: str
    metadata: dict[str, Any]
    evidence_block_ids: list[str]
    content_origin: str
    review_status: str
    document_id: uuid.UUID | None
    document_version: int | None
    compile_provenance: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class KnowledgeInvocationProvenance(WireModel):
    invocation_id: uuid.UUID
    stage: Literal["A", "B", "C", "D"]
    unit_id: str
    input_sha256: str = Field(pattern=r"^(?:sha256:)?[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^(?:sha256:)?[0-9a-f]{64}$")
    request_manifest_sha256: str = Field(pattern=r"^(?:sha256:)?[0-9a-f]{64}$")
    result_manifest_sha256: str = Field(pattern=r"^(?:sha256:)?[0-9a-f]{64}$")


class SemanticModelAttestation(WireModel):
    provider_key: str
    model_revision: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    runtime_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    adapter_version: str
    prompt_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    schema_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class SemanticClassificationResponse(WireModel):
    document_id: uuid.UUID
    document_version: int = Field(ge=1)
    semantic_type: str
    languages: list[str]
    topics: list[str]
    domains: list[str]
    evidence_block_ids: list[str]
    classification: DocumentClassification
    model_attestation: SemanticModelAttestation
    invocation_provenance: list[KnowledgeInvocationProvenance] = Field(min_length=1)
    created_at: datetime


class UsageLedgerEntry(WireModel):
    id: uuid.UUID
    job_id: uuid.UUID | None
    entry_type: str
    credits: Decimal
    balance_after: Decimal
    reserved_after: Decimal
    created_at: datetime


class UsageResponse(WireModel):
    from_time: datetime
    to_time: datetime
    balance: Decimal
    reserved: Decimal
    available: Decimal
    totals_by_entry_type: dict[str, Decimal]
    entries: list[UsageLedgerEntry]


class JobCostResponse(WireModel):
    job_id: uuid.UUID
    document_id: uuid.UUID | None
    job_type: str
    status: str
    provider: str | None
    credits: Decimal
    released: Decimal
    raw_cost: dict[str, Any]
    completed_at: datetime | None


class CostsResponse(WireModel):
    from_time: datetime
    to_time: datetime
    completed_jobs: int = Field(ge=0)
    total_credits: Decimal
    total_released: Decimal
    jobs: list[JobCostResponse]


def _window(
    from_time: datetime | None,
    to_time: datetime | None,
) -> tuple[datetime, datetime]:
    end = to_time or datetime.now(UTC)
    start = from_time or (end - timedelta(days=30))
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail={"code": "TIMEZONE_REQUIRED"})
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    if start >= end:
        raise HTTPException(status_code=422, detail={"code": "TIME_WINDOW_INVALID"})
    if end - start > _MAX_WINDOW:
        raise HTTPException(status_code=422, detail={"code": "TIME_WINDOW_TOO_LARGE"})
    return start, end


@router.get("/schema-profiles", response_model=SchemaProfilesResponse)
async def schema_profiles(_principal: PrincipalDep) -> SchemaProfilesResponse:
    profiles = [
        SchemaProfile(
            id="cir",
            kind="contract",
            version="1.0",
            description="Canonical Intermediate Representation",
            stable=True,
        ),
        SchemaProfile(
            id="akmp",
            kind="contract",
            version="1.0",
            description="AI Knowledge Markdown Package",
            stable=True,
        ),
        *[
            SchemaProfile(
                id=profile,
                kind="route",
                version="1",
                description=description,
                stable=True,
            )
            for profile, description in (
                ("parse_fast_v1", "Native-first low-latency parsing"),
                ("parse_balanced_v1", "Quality and cost balanced parsing"),
                ("parse_precision_v1", "Precision parsing with stricter review gates"),
                ("parse_private_v1", "No external document transfer"),
                ("parse_long_v1", "Bounded long-document routing"),
            )
        ],
        SchemaProfile(
            id="knowledge_standard_v1",
            kind="knowledge",
            version="1",
            description="Evidence-bound document knowledge notes",
            stable=True,
        ),
        SchemaProfile(
            id="knowledge_precision_v1",
            kind="knowledge",
            version="1",
            description="Multi-document relation and conflict verification",
            stable=False,
        ),
        *[
            SchemaProfile(
                id=profile,
                kind="export",
                version="1",
                description=description,
                stable=True,
            )
            for profile, description in (
                ("portable_markdown_v1", "Portable Markdown and source map"),
                ("obsidian_vault_v1", "Obsidian vault with deterministic Wikilinks"),
                ("rag_jsonl_v1", "Evidence-preserving RAG chunks"),
                ("jsonld_v1", "AKMP JSON-LD graph"),
            )
        ],
    ]
    return SchemaProfilesResponse(profiles=profiles)


@router.get(
    "/documents/{document_id}/semantic-classification",
    response_model=SemanticClassificationResponse,
)
async def document_semantic_classification(
    document_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> SemanticClassificationResponse:
    row = (
        await session.execute(
            select(Document, DocumentSemanticClassification)
            .join(
                DocumentSemanticClassification,
                (DocumentSemanticClassification.tenant_id == Document.tenant_id)
                & (DocumentSemanticClassification.document_id == Document.id)
                & (DocumentSemanticClassification.document_version == Document.active_version)
                & DocumentSemanticClassification.is_active.is_(True),
            )
            .where(
                Document.tenant_id == principal.tenant_id,
                Document.id == document_id,
                Document.deletion_requested_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "SEMANTIC_CLASSIFICATION_NOT_FOUND"},
        )
    document, stored = row
    await require_project_access(
        session,
        principal=principal,
        project_id=document.project_id,
        capability="read",
    )
    try:
        classification = DocumentClassification.model_validate(stored.classification)
        provenance = stored.provenance
        invocations = provenance["invocations"]
        if (
            provenance.get("artifact_contract") != "akc-knowledge-pipeline-stage-1.0.0"
            or not isinstance(invocations, list)
            or not invocations
        ):
            raise ValueError
        invocation_provenance = [
            KnowledgeInvocationProvenance.model_validate(value) for value in invocations
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "SEMANTIC_CLASSIFICATION_PROVENANCE_INVALID"},
        ) from exc
    languages = list(classification.languages or (classification.language,))
    return SemanticClassificationResponse(
        document_id=document.id,
        document_version=stored.document_version,
        semantic_type=classification.document_type,
        languages=languages,
        topics=list(classification.topics),
        domains=list(classification.domain),
        evidence_block_ids=list(classification.evidence_block_ids),
        classification=classification,
        model_attestation=SemanticModelAttestation(
            provider_key=stored.provider_key,
            model_revision=stored.model_revision,
            runtime_image_digest=stored.runtime_image_digest,
            adapter_version=stored.adapter_version,
            prompt_revision=stored.prompt_revision,
            schema_sha256=stored.schema_sha256,
        ),
        invocation_provenance=invocation_provenance,
        created_at=stored.created_at,
    )


@router.get(
    "/documents/{document_id}/provenance",
    response_model=ProvenanceResponse,
)
async def document_provenance(
    document_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> ProvenanceResponse:
    row = (
        await session.execute(
            select(Document, SourceFile)
            .join(
                SourceFile,
                (SourceFile.tenant_id == Document.tenant_id)
                & (SourceFile.id == Document.source_file_id),
            )
            .where(
                Document.tenant_id == principal.tenant_id,
                Document.id == document_id,
                Document.deletion_requested_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND"})
    document, source = row
    await require_project_access(
        session,
        principal=principal,
        project_id=document.project_id,
        capability="read",
    )
    version = await session.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.tenant_id == principal.tenant_id,
            DocumentVersion.document_id == document.id,
            DocumentVersion.version == document.active_version,
        )
        .limit(1)
    )
    pages = list(
        await session.scalars(
            select(Page)
            .where(
                Page.tenant_id == principal.tenant_id,
                Page.document_id == document.id,
            )
            .order_by(Page.page_number, Page.id)
        )
    )
    page_numbers = {page.id: page.page_number for page in pages}
    blocks = list(
        await session.scalars(
            select(Block)
            .where(
                Block.tenant_id == principal.tenant_id,
                Block.document_id == document.id,
            )
            .order_by(Block.block_order, Block.id)
        )
    )
    block_ids = {str(block.id) for block in blocks}
    notes = list(
        await session.scalars(
            select(KnowledgeNote)
            .where(
                KnowledgeNote.tenant_id == principal.tenant_id,
                KnowledgeNote.project_id == document.project_id,
                KnowledgeNote.is_active.is_(True),
                or_(
                    KnowledgeNote.document_id == document.id,
                    KnowledgeNote.document_id.is_(None),
                ),
                or_(
                    KnowledgeNote.document_version == document.active_version,
                    KnowledgeNote.document_version.is_(None),
                ),
            )
            .order_by(KnowledgeNote.stable_key, KnowledgeNote.id)
        )
    )
    linked_notes: list[ProvenanceKnowledgeNote] = []
    for note in notes:
        evidence = [
            uuid.UUID(block_id) for block_id in note.evidence_block_ids if block_id in block_ids
        ]
        if evidence:
            linked_notes.append(
                ProvenanceKnowledgeNote(
                    note_id=note.id,
                    stable_key=note.stable_key,
                    content_origin=note.content_origin,
                    review_status=note.review_status,
                    evidence_block_ids=evidence,
                    compile_provenance=note.compile_provenance,
                )
            )
    relation_rows = list(
        await session.scalars(
            select(Relation)
            .where(
                Relation.tenant_id == principal.tenant_id,
                Relation.project_id == document.project_id,
                Relation.is_active.is_(True),
                or_(
                    Relation.document_id == document.id,
                    Relation.document_id.is_(None),
                ),
                or_(
                    Relation.document_version == document.active_version,
                    Relation.document_version.is_(None),
                ),
            )
            .order_by(Relation.id)
        )
    )
    linked_relations = [
        ProvenanceRelation(
            relation_id=relation.id,
            source_relation_key=relation.source_relation_key,
            subject_id=relation.subject_id,
            predicate=relation.predicate,
            object_id=relation.object_id,
            evidence_block_ids=[
                uuid.UUID(block_id)
                for block_id in relation.evidence_block_ids
                if block_id in block_ids
            ],
            compile_provenance=relation.compile_provenance,
        )
        for relation in relation_rows
        if any(block_id in block_ids for block_id in relation.evidence_block_ids)
    ]
    located = sum(block.page_id in page_numbers for block in blocks)
    return ProvenanceResponse(
        document_id=document.id,
        project_id=document.project_id,
        cir_schema_version=document.cir_schema_version,
        active_version=document.active_version,
        version_policy=version.policy_version if version is not None else None,
        model_revision=version.model_revision if version is not None else None,
        prompt_revision=version.prompt_revision if version is not None else None,
        source=ProvenanceSource(
            source_file_id=source.id,
            sha256=source.sha256,
            mime_type=source.mime_type,
            size_bytes=source.size_bytes,
            original_filename=source.original_filename,
        ),
        blocks=[
            ProvenanceBlock(
                block_id=block.id,
                page_id=block.page_id,
                page_number=(
                    page_numbers.get(block.page_id) if block.page_id is not None else None
                ),
                block_order=block.block_order,
                block_type=block.block_type,
                origin=block.origin,
                bbox1000=block.bbox1000,
                polygon_norm=block.polygon_norm,
                content_hash=block.content_hash,
                engine=block.engine,
                engine_revision=block.engine_revision,
                confidence=block.confidence,
                revision=block.revision,
            )
            for block in blocks
        ],
        knowledge_notes=linked_notes,
        relations=linked_relations,
        source_coverage_ratio=located / max(1, len(blocks)),
    )


@router.get(
    "/projects/{project_id}/knowledge",
    response_model=list[KnowledgeNoteResponse],
)
async def project_knowledge(
    project_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[KnowledgeNoteResponse]:
    project = await session.scalar(
        select(Project.id).where(
            Project.tenant_id == principal.tenant_id,
            Project.id == project_id,
            Project.deletion_requested_at.is_(None),
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
    await require_project_access(
        session,
        principal=principal,
        project_id=project_id,
        capability="read",
    )
    notes = list(
        await session.scalars(
            select(KnowledgeNote)
            .where(
                KnowledgeNote.tenant_id == principal.tenant_id,
                KnowledgeNote.project_id == project_id,
                KnowledgeNote.is_active.is_(True),
            )
            .order_by(KnowledgeNote.updated_at.desc(), KnowledgeNote.id.desc())
            .limit(limit)
        )
    )
    return [
        KnowledgeNoteResponse(
            id=note.id,
            stable_key=note.stable_key,
            title=note.title,
            note_type=note.note_type,
            content_markdown=note.content_markdown,
            metadata=note.metadata_json,
            evidence_block_ids=note.evidence_block_ids,
            content_origin=note.content_origin,
            review_status=note.review_status,
            document_id=note.document_id,
            document_version=note.document_version,
            compile_provenance=note.compile_provenance,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )
        for note in notes
    ]


@router.get("/usage", response_model=UsageResponse)
async def usage(
    principal: PrincipalDep,
    session: SessionDep,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> UsageResponse:
    start, end = _window(from_time, to_time)
    account = await session.get(CreditAccount, principal.tenant_id)
    if account is None:
        raise HTTPException(status_code=409, detail={"code": "CREDIT_ACCOUNT_MISSING"})
    ledger = list(
        await session.scalars(
            select(CreditLedger)
            .outerjoin(
                ProcessingJob,
                (ProcessingJob.tenant_id == CreditLedger.tenant_id)
                & (ProcessingJob.id == CreditLedger.job_id),
            )
            .where(
                CreditLedger.tenant_id == principal.tenant_id,
                CreditLedger.created_at >= start,
                CreditLedger.created_at < end,
                or_(
                    CreditLedger.job_id.is_(None),
                    project_access_predicate(
                        principal,
                        ProcessingJob.project_id,
                        "read",
                    ),
                ),
            )
            .order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc())
        )
    )
    totals: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for entry in ledger:
        totals[entry.entry_type] += entry.credits
    return UsageResponse(
        from_time=start,
        to_time=end,
        balance=account.balance,
        reserved=account.reserved,
        available=account.balance - account.reserved,
        totals_by_entry_type=dict(sorted(totals.items())),
        entries=[
            UsageLedgerEntry(
                id=entry.id,
                job_id=entry.job_id,
                entry_type=entry.entry_type,
                credits=entry.credits,
                balance_after=entry.balance_after,
                reserved_after=entry.reserved_after,
                created_at=entry.created_at,
            )
            for entry in ledger[:limit]
        ],
    )


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


@router.get("/costs", response_model=CostsResponse)
async def costs(
    principal: PrincipalDep,
    session: SessionDep,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> CostsResponse:
    start, end = _window(from_time, to_time)
    jobs = list(
        await session.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.tenant_id == principal.tenant_id,
                ProcessingJob.created_at >= start,
                ProcessingJob.created_at < end,
                project_access_predicate(
                    principal,
                    ProcessingJob.project_id,
                    "read",
                ),
            )
            .order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc())
            .limit(limit)
        )
    )
    items: list[JobCostResponse] = []
    for job in jobs:
        actual = dict(job.cost_actual)
        items.append(
            JobCostResponse(
                job_id=job.id,
                document_id=job.document_id,
                job_type=job.job_type,
                status=job.status,
                provider=(str(actual["provider"]) if actual.get("provider") is not None else None),
                credits=_decimal(actual.get("credits")),
                released=_decimal(actual.get("released")),
                raw_cost=actual,
                completed_at=job.completed_at,
            )
        )
    return CostsResponse(
        from_time=start,
        to_time=end,
        completed_jobs=sum(item.status == "completed" for item in items),
        total_credits=sum((item.credits for item in items), Decimal("0")),
        total_released=sum((item.released for item in items), Decimal("0")),
        jobs=items,
    )
