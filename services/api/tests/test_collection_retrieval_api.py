from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from akc_api.collection_retrieval_api import (
    CollectionRetrievalSearchRequest,
    search_collection_retrieval,
)
from akc_api.models import ArchitecturePlan, Collection, KnowledgeCompileRun, OutboxEvent
from akc_api.security import Principal
from akc_cir import canonical_json, sha256_digest
from akc_retrieval import (
    EmbeddingRequest,
    EmbeddingResult,
    HmacSha256RowAttestor,
    PostgresHybridStore,
    VectorCandidate,
    VectorRecord,
)
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

TENANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
PROJECT_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
COLLECTION_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("40000000-0000-0000-0000-000000000001")
PLAN_ID = uuid.UUID("50000000-0000-0000-0000-000000000001")
MODEL_ID = "Qwen3-Embedding-0.6B"
MODEL_REVISION = "a" * 40
PLAN_PAYLOAD = {
    "schema_version": "1.0",
    "collection_id": str(COLLECTION_ID),
    "project_id": str(PROJECT_ID),
}


class CollectionSession:
    def __init__(self, *, completion_receipt: bool = True) -> None:
        self.calls = 0
        self.collection = Collection(
            id=COLLECTION_ID,
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Verified collection",
            status="COMPLETED",
            created_by=USER_ID,
        )
        self.completion_receipt = (
            OutboxEvent(
                tenant_id=TENANT_ID,
                aggregate_type="collection",
                aggregate_id=COLLECTION_ID,
                event_type="collection.retrieval.indexed.v1",
                payload={
                    "collection_id": str(COLLECTION_ID),
                    "project_id": str(PROJECT_ID),
                    "architecture_plan_id": str(PLAN_ID),
                    "architecture_plan_sha256": sha256_digest(canonical_json(PLAN_PAYLOAD)),
                    "canonical_model_sha256": "sha256:" + "c" * 64,
                    "retrieval_batch_sha256": "sha256:" + "d" * 64,
                    "indexed_records": 1,
                    "raw_text_persisted": False,
                },
            )
            if completion_receipt
            else None
        )
        self.plan = ArchitecturePlan(
            id=PLAN_ID,
            tenant_id=TENANT_ID,
            collection_id=COLLECTION_ID,
            plan_version=1,
            status="compiled",
            input_integrity_sha256="a" * 64,
            plan=PLAN_PAYLOAD,
            created_by=USER_ID,
        )
        self.compile_run = KnowledgeCompileRun(
            tenant_id=TENANT_ID,
            collection_id=COLLECTION_ID,
            architecture_plan_id=PLAN_ID,
            input_integrity_sha256="b" * 64,
            compiler_revision="collection-semantic-runtime-v1",
            mode="collection_processing_runtime",
            status="completed",
            note_count=1,
            relation_count=0,
            output_sha256="c" * 64,
        )

    async def scalar(
        self, _statement: Any
    ) -> Collection | OutboxEvent | ArchitecturePlan | KnowledgeCompileRun | None:
        self.calls += 1
        values = (
            self.collection,
            self.completion_receipt,
            self.plan,
            self.compile_run,
        )
        return values[self.calls - 1] if self.calls <= len(values) else None


class QueryEmbeddingProvider:
    provider_id = "qwen-attested"
    model_id = MODEL_ID

    def __init__(self, *, model_revision: str = MODEL_REVISION) -> None:
        self.model_revision = model_revision
        self.requests: list[EmbeddingRequest] = []
        self.texts: list[str] = []

    async def embed_text(
        self,
        request: EmbeddingRequest,
        text: str,
    ) -> EmbeddingResult:
        self.requests.append(request)
        self.texts.append(text)
        return EmbeddingResult(
            provider_id=self.provider_id,
            model_id=MODEL_ID,
            model_revision=self.model_revision,
            source_hash=request.source_hash,
            vector=(1.0, *(0.0 for _ in range(1023))),
        )


class RecordingSearchExecutor:
    dialect_name = "postgresql"

    def __init__(self) -> None:
        self.parameters: dict[str, Any] | None = None

    async def fetch_all(self, _statement: Any, parameters: Any) -> tuple[()]:
        self.parameters = dict(parameters)
        return ()


class StaleCandidateStore(PostgresHybridStore):
    async def search(self, _query: Any) -> tuple[VectorCandidate, ...]:
        return (
            VectorCandidate(
                record=VectorRecord(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    stable_id="note:stale",
                    media_kind="text",
                    source_hash="d" * 64,
                    evidence_block_ids=(uuid.uuid4(),),
                    model_id=MODEL_ID,
                    model_revision=MODEL_REVISION,
                    vector=(1.0, *(0.0 for _ in range(1023))),
                    metadata={
                        "collection_id": str(COLLECTION_ID),
                        "canonical_model_sha256": "sha256:" + "e" * 64,
                    },
                ),
                vector_score=1.0,
                bm25_score=0.0,
                graph_score=0.0,
                hybrid_score=1.0,
            ),
        )


def _principal() -> Principal:
    return Principal(
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        roles=frozenset({"owner"}),
        scopes=frozenset({"api:read"}),
        auth_type="api_key",
    )


def _request(
    *,
    provider: QueryEmbeddingProvider | None,
    store: PostgresHybridStore | None,
    expected_revision: str = MODEL_REVISION,
) -> Request:
    state = SimpleNamespace(
        collection_semantic_retrieval_store=store,
        collection_semantic_query_embedding_provider=provider,
        collection_semantic_query_embedding_model_id=MODEL_ID,
        collection_semantic_query_embedding_model_revision=expected_revision,
    )
    return cast(Request, SimpleNamespace(app=SimpleNamespace(state=state)))


@pytest.mark.asyncio
async def test_retrieval_api_forces_authenticated_tenant_project_collection_scope() -> None:
    provider = QueryEmbeddingProvider()
    executor = RecordingSearchExecutor()
    store = PostgresHybridStore(
        executor=executor,
        row_attestor=HmacSha256RowAttestor(b"r" * 32),
    )
    query = "verified evidence"

    response = await search_collection_retrieval(
        COLLECTION_ID,
        CollectionRetrievalSearchRequest(query=query),
        _request(provider=provider, store=store),
        _principal(),
        cast(AsyncSession, CollectionSession()),
    )

    assert response.collection_id == COLLECTION_ID
    assert response.project_id == PROJECT_ID
    assert response.hits == ()
    assert (
        response.query_fingerprint == "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()
    )
    assert len(provider.requests) == 1
    assert provider.requests[0].tenant_id == TENANT_ID
    assert provider.texts == [query]
    assert executor.parameters is not None
    assert executor.parameters["tenant_id"] == str(TENANT_ID)
    assert executor.parameters["project_ids"] == [str(PROJECT_ID)]
    assert executor.parameters["collection_ids"] == [str(COLLECTION_ID)]
    assert executor.parameters["verification_states"] == [
        "authority_verified",
        "auto_repaired",
        "verified",
        "verified_with_warning",
    ]


@pytest.mark.asyncio
async def test_retrieval_api_fails_closed_without_production_store() -> None:
    with pytest.raises(HTTPException) as raised:
        await search_collection_retrieval(
            COLLECTION_ID,
            CollectionRetrievalSearchRequest(query="evidence"),
            _request(provider=QueryEmbeddingProvider(), store=None),
            _principal(),
            cast(AsyncSession, CollectionSession()),
        )

    assert raised.value.status_code == 503
    assert raised.value.detail == {"code": "COLLECTION_RETRIEVAL_STORE_UNAVAILABLE"}


@pytest.mark.asyncio
async def test_retrieval_api_hides_orphan_index_without_completion_outbox() -> None:
    executor = RecordingSearchExecutor()
    store = PostgresHybridStore(
        executor=executor,
        row_attestor=HmacSha256RowAttestor(b"r" * 32),
    )

    with pytest.raises(HTTPException) as raised:
        await search_collection_retrieval(
            COLLECTION_ID,
            CollectionRetrievalSearchRequest(query="evidence"),
            _request(provider=QueryEmbeddingProvider(), store=store),
            _principal(),
            cast(AsyncSession, CollectionSession(completion_receipt=False)),
        )

    assert raised.value.status_code == 409
    assert raised.value.detail == {"code": "COLLECTION_RETRIEVAL_NOT_READY"}
    assert executor.parameters is None


@pytest.mark.asyncio
async def test_retrieval_api_rejects_unpinned_embedding_revision_before_search() -> None:
    provider = QueryEmbeddingProvider(model_revision="b" * 40)
    executor = RecordingSearchExecutor()
    store = PostgresHybridStore(
        executor=executor,
        row_attestor=HmacSha256RowAttestor(b"r" * 32),
    )

    with pytest.raises(HTTPException) as raised:
        await search_collection_retrieval(
            COLLECTION_ID,
            CollectionRetrievalSearchRequest(query="evidence"),
            _request(provider=provider, store=store),
            _principal(),
            cast(AsyncSession, CollectionSession()),
        )

    assert raised.value.status_code == 503
    assert raised.value.detail == {"code": "COLLECTION_RETRIEVAL_EMBEDDING_ATTESTATION_INVALID"}
    assert executor.parameters is None


@pytest.mark.asyncio
async def test_retrieval_api_rejects_receipt_that_drifted_from_stored_plan() -> None:
    session = CollectionSession()
    assert session.completion_receipt is not None
    session.completion_receipt.payload = {
        **session.completion_receipt.payload,
        "architecture_plan_sha256": "sha256:" + "f" * 64,
    }
    executor = RecordingSearchExecutor()
    store = PostgresHybridStore(
        executor=executor,
        row_attestor=HmacSha256RowAttestor(b"r" * 32),
    )

    with pytest.raises(HTTPException) as raised:
        await search_collection_retrieval(
            COLLECTION_ID,
            CollectionRetrievalSearchRequest(query="evidence"),
            _request(provider=QueryEmbeddingProvider(), store=store),
            _principal(),
            cast(AsyncSession, session),
        )

    assert raised.value.status_code == 409
    assert raised.value.detail == {"code": "COLLECTION_RETRIEVAL_NOT_READY"}
    assert executor.parameters is None


@pytest.mark.asyncio
async def test_retrieval_api_rejects_stale_rows_from_an_older_canonical_model() -> None:
    store = StaleCandidateStore(
        executor=RecordingSearchExecutor(),
        row_attestor=HmacSha256RowAttestor(b"r" * 32),
    )

    with pytest.raises(HTTPException) as raised:
        await search_collection_retrieval(
            COLLECTION_ID,
            CollectionRetrievalSearchRequest(query="evidence"),
            _request(provider=QueryEmbeddingProvider(), store=store),
            _principal(),
            cast(AsyncSession, CollectionSession()),
        )

    assert raised.value.status_code == 503
    assert raised.value.detail == {"code": "COLLECTION_RETRIEVAL_RECEIPT_MISMATCH"}
