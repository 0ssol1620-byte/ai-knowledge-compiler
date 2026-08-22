"""Tenant-scoped collection retrieval over the attested PostgreSQL store."""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Annotated, Any

from akc_cir import canonical_json, sha256_digest
from akc_retrieval import (
    EmbeddingRequest,
    EmbeddingResult,
    MediaKind,
    PostgresHybridStore,
    ProviderAttestationError,
    RetrievalUnavailable,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.collection_retrieval_runtime import (
    CollectionSemanticTextEmbeddingProvider,
)
from akc_api.collection_semantic_runtime import search_collection_semantic_runtime
from akc_api.database import get_session
from akc_api.models import ArchitecturePlan, Collection, KnowledgeCompileRun, OutboxEvent
from akc_api.project_access import require_project_access
from akc_api.security import Principal, get_principal

router = APIRouter(prefix="/v1", tags=["collection-retrieval"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]

_MODEL_REVISION = r"^[0-9a-f]{40,64}$"


class _WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CollectionRetrievalSearchRequest(_WireModel):
    query: Annotated[str, Field(min_length=1, max_length=2_000)]
    graph_seed_ids: tuple[Annotated[str, Field(min_length=1, max_length=240)], ...] = ()
    candidate_k: Annotated[int, Field(ge=30, le=100)] = 50
    top_k: Annotated[int, Field(ge=5, le=15)] = 10

    @field_validator("query")
    @classmethod
    def require_non_whitespace_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("retrieval query must contain non-whitespace text")
        return value

    @field_validator("graph_seed_ids")
    @classmethod
    def unique_graph_seeds(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 100 or len(value) != len(set(value)):
            raise ValueError("graph seed ids must be unique and contain at most 100 values")
        return value


class CollectionRetrievalEmbeddingReceipt(_WireModel):
    provider_id: Annotated[str, Field(min_length=1, max_length=200)]
    model_id: Annotated[str, Field(min_length=1, max_length=200)]
    model_revision: Annotated[str, Field(pattern=_MODEL_REVISION)]
    source_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CollectionRetrievalHit(_WireModel):
    stable_id: Annotated[str, Field(min_length=1, max_length=240)]
    project_id: uuid.UUID
    media_kind: MediaKind
    score: float
    vector_score: Annotated[float, Field(ge=-1, le=1)]
    bm25_score: Annotated[float, Field(ge=0, le=1)]
    graph_score: Annotated[float, Field(ge=0, le=1)]
    hybrid_score: Annotated[float, Field(ge=0, le=1)] | None
    evidence_block_ids: tuple[uuid.UUID, ...]
    source_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    metadata: dict[str, Any]


class CollectionRetrievalSearchResponse(_WireModel):
    collection_id: uuid.UUID
    project_id: uuid.UUID
    query_fingerprint: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    embedding: CollectionRetrievalEmbeddingReceipt
    hits: tuple[CollectionRetrievalHit, ...]


def _runtime_unavailable(code: str) -> HTTPException:
    return HTTPException(status_code=503, detail={"code": code})


def _valid_completion_receipt(
    event: OutboxEvent | None,
    *,
    collection: Collection,
    plan: ArchitecturePlan | None,
    compile_run: KnowledgeCompileRun | None,
) -> bool:
    if event is None or plan is None or compile_run is None:
        return False
    payload = event.payload
    try:
        indexed_records = int(payload["indexed_records"])
    except (KeyError, TypeError, ValueError):
        return False
    canonical_sha256 = payload.get("canonical_model_sha256")
    architecture_plan_sha256 = payload.get("architecture_plan_sha256")
    batch_sha256 = payload.get("retrieval_batch_sha256")
    return bool(
        event.tenant_id == collection.tenant_id
        and event.aggregate_type == "collection"
        and event.aggregate_id == collection.id
        and event.event_type == "collection.retrieval.indexed.v1"
        and payload.get("collection_id") == str(collection.id)
        and payload.get("project_id") == str(collection.project_id)
        and payload.get("architecture_plan_id") == str(plan.id)
        and plan.tenant_id == collection.tenant_id
        and plan.collection_id == collection.id
        and plan.status == "compiled"
        and architecture_plan_sha256 == sha256_digest(canonical_json(plan.plan))
        and compile_run.tenant_id == collection.tenant_id
        and compile_run.collection_id == collection.id
        and compile_run.architecture_plan_id == plan.id
        and compile_run.compiler_revision == "collection-semantic-runtime-v1"
        and compile_run.status == "completed"
        and compile_run.output_sha256 is not None
        and isinstance(canonical_sha256, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", canonical_sha256) is not None
        and canonical_sha256 == "sha256:" + compile_run.output_sha256
        and isinstance(architecture_plan_sha256, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", architecture_plan_sha256) is not None
        and isinstance(batch_sha256, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", batch_sha256) is not None
        and indexed_records >= 1
        and payload.get("raw_text_persisted") is False
    )


@router.post(
    "/collections/{collection_id}/retrieval/search",
    response_model=CollectionRetrievalSearchResponse,
)
async def search_collection_retrieval(
    collection_id: uuid.UUID,
    payload: CollectionRetrievalSearchRequest,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> CollectionRetrievalSearchResponse:
    """Search only the authenticated tenant's attested collection rows."""

    collection = await session.scalar(
        select(Collection).where(
            Collection.tenant_id == principal.tenant_id,
            Collection.id == collection_id,
            Collection.status != "PURGED",
        )
    )
    if collection is None:
        raise HTTPException(status_code=404, detail={"code": "COLLECTION_NOT_FOUND"})
    await require_project_access(
        session,
        principal=principal,
        project_id=collection.project_id,
        capability="read",
    )
    completion_receipt = await session.scalar(
        select(OutboxEvent)
        .where(
            OutboxEvent.tenant_id == principal.tenant_id,
            OutboxEvent.aggregate_type == "collection",
            OutboxEvent.aggregate_id == collection.id,
            OutboxEvent.event_type == "collection.retrieval.indexed.v1",
        )
        .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
        .limit(1)
    )
    try:
        receipt_plan_id = (
            uuid.UUID(str(completion_receipt.payload["architecture_plan_id"]))
            if completion_receipt is not None
            else None
        )
    except (KeyError, TypeError, ValueError):
        receipt_plan_id = None
    plan = (
        await session.scalar(
            select(ArchitecturePlan).where(
                ArchitecturePlan.tenant_id == principal.tenant_id,
                ArchitecturePlan.collection_id == collection.id,
                ArchitecturePlan.id == receipt_plan_id,
                ArchitecturePlan.status == "compiled",
            )
        )
        if receipt_plan_id is not None
        else None
    )
    compile_run = (
        await session.scalar(
            select(KnowledgeCompileRun)
            .where(
                KnowledgeCompileRun.tenant_id == principal.tenant_id,
                KnowledgeCompileRun.collection_id == collection.id,
                KnowledgeCompileRun.architecture_plan_id == receipt_plan_id,
                KnowledgeCompileRun.compiler_revision == "collection-semantic-runtime-v1",
                KnowledgeCompileRun.status == "completed",
            )
            .order_by(KnowledgeCompileRun.started_at.desc(), KnowledgeCompileRun.id.desc())
            .limit(1)
        )
        if receipt_plan_id is not None
        else None
    )
    if not _valid_completion_receipt(
        completion_receipt,
        collection=collection,
        plan=plan,
        compile_run=compile_run,
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_RETRIEVAL_NOT_READY"},
        )
    if completion_receipt is None:  # Defensive type narrowing after receipt validation.
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_RETRIEVAL_NOT_READY"},
        )

    store = getattr(request.app.state, "collection_semantic_retrieval_store", None)
    provider = getattr(
        request.app.state,
        "collection_semantic_query_embedding_provider",
        None,
    )
    expected_model_id = getattr(
        request.app.state,
        "collection_semantic_query_embedding_model_id",
        None,
    )
    expected_model_revision = getattr(
        request.app.state,
        "collection_semantic_query_embedding_model_revision",
        None,
    )
    if not isinstance(store, PostgresHybridStore):
        raise _runtime_unavailable("COLLECTION_RETRIEVAL_STORE_UNAVAILABLE")
    if not isinstance(provider, CollectionSemanticTextEmbeddingProvider):
        raise _runtime_unavailable("COLLECTION_RETRIEVAL_EMBEDDING_UNAVAILABLE")
    if not isinstance(expected_model_id, str) or not isinstance(expected_model_revision, str):
        raise _runtime_unavailable("COLLECTION_RETRIEVAL_EMBEDDING_CONTRACT_MISSING")

    query_bytes = payload.query.encode("utf-8")
    source_sha256 = hashlib.sha256(query_bytes).hexdigest()
    embedding_request = EmbeddingRequest(
        tenant_id=principal.tenant_id,
        object_key=f"collection-query:{collection.id}:{source_sha256}",
        source_hash=source_sha256,
        media_kind=MediaKind.TEXT,
        instruction_profile="collection_semantic_query_v1",
    )
    try:
        embedding = EmbeddingResult.model_validate(
            await provider.embed_text(embedding_request, payload.query)
        )
    except Exception as exc:
        raise _runtime_unavailable("COLLECTION_RETRIEVAL_EMBEDDING_FAILED") from exc
    if (
        embedding.provider_id != provider.provider_id
        or embedding.model_id != expected_model_id
        or embedding.model_revision != expected_model_revision
        or embedding.source_hash != source_sha256
        or len(embedding.vector) != 1024
    ):
        raise _runtime_unavailable("COLLECTION_RETRIEVAL_EMBEDDING_ATTESTATION_INVALID")

    try:
        candidates = await search_collection_semantic_runtime(
            store,
            tenant_id=principal.tenant_id,
            allowed_project_ids=(collection.project_id,),
            collection_id=collection.id,
            vector=embedding.vector,
            lexical_query=payload.query,
            graph_seed_ids=payload.graph_seed_ids,
            candidate_k=payload.candidate_k,
            top_k=payload.top_k,
        )
    except (ProviderAttestationError, RetrievalUnavailable, ValueError) as exc:
        raise _runtime_unavailable("COLLECTION_RETRIEVAL_FAILED_CLOSED") from exc
    expected_canonical_sha256 = str(completion_receipt.payload["canonical_model_sha256"])
    if any(
        candidate.record.metadata.get("canonical_model_sha256") != expected_canonical_sha256
        or candidate.record.model_id != expected_model_id
        or candidate.record.model_revision != expected_model_revision
        for candidate in candidates
    ):
        raise _runtime_unavailable("COLLECTION_RETRIEVAL_RECEIPT_MISMATCH")

    return CollectionRetrievalSearchResponse(
        collection_id=collection.id,
        project_id=collection.project_id,
        query_fingerprint="sha256:" + source_sha256,
        embedding=CollectionRetrievalEmbeddingReceipt(
            provider_id=embedding.provider_id,
            model_id=embedding.model_id,
            model_revision=embedding.model_revision,
            source_sha256=embedding.source_hash,
        ),
        hits=tuple(
            CollectionRetrievalHit(
                stable_id=candidate.record.stable_id,
                project_id=candidate.record.project_id,
                media_kind=candidate.record.media_kind,
                score=(
                    candidate.hybrid_score
                    if candidate.hybrid_score is not None
                    else candidate.vector_score
                ),
                vector_score=candidate.vector_score,
                bm25_score=candidate.bm25_score,
                graph_score=candidate.graph_score,
                hybrid_score=candidate.hybrid_score,
                evidence_block_ids=candidate.record.evidence_block_ids,
                source_hash=candidate.record.source_hash,
                metadata=dict(candidate.record.metadata),
            )
            for candidate in candidates
        ),
    )


__all__ = [
    "CollectionRetrievalSearchRequest",
    "CollectionRetrievalSearchResponse",
    "router",
    "search_collection_retrieval",
]
