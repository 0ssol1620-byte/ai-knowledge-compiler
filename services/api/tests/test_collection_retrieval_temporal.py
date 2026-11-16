from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from akc_api.collection_retrieval_api import router
from akc_api.collection_semantic_runtime import (
    PreparedCollectionSemanticRuntime,
    RetrievalIndexExpectation,
    build_collection_retrieval_batch,
    commit_then_sweep_superseded,
    search_collection_semantic_runtime,
)
from akc_api.database import get_session
from akc_api.models import ArchitecturePlan, Collection, KnowledgeCompileRun, OutboxEvent
from akc_api.security import Principal, get_principal
from akc_cir import canonical_json, sha256_digest
from akc_retrieval import (
    EmbeddingRequest,
    EmbeddingResult,
    HmacSha256RowAttestor,
    PostgresHybridIndexer,
    PostgresHybridStore,
    PostgreSQLMutation,
    ProviderAttestationError,
    RetrievalIndexBatch,
    RetrievalQuery,
    VectorCandidate,
    VerificationState,
    admit,
)
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

TENANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
PROJECT_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
COLLECTION_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("40000000-0000-0000-0000-000000000001")
PLAN_ID = uuid.UUID("50000000-0000-0000-0000-000000000001")
DOCUMENT_ID = uuid.UUID("60000000-0000-0000-0000-000000000001")
BLOCK_ID = uuid.UUID("70000000-0000-0000-0000-000000000001")
MODEL_ID = "Qwen3-Embedding-0.6B"
MODEL_REVISION = "a" * 40
CANONICAL = "sha256:" + "c" * 64
COMPILED_AT = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
PLAN_PAYLOAD = {"schema_version": "1.0", "collection_id": str(COLLECTION_ID)}
VECTOR = (1.0, *(0.0 for _ in range(1023)))


def _prepared() -> PreparedCollectionSemanticRuntime:
    expectation = RetrievalIndexExpectation(
        stable_id="note:one",
        document_id=DOCUMENT_ID,
        source_hash="b" * 64,
        evidence_block_ids=(BLOCK_ID,),
        lexical_text="First canonical note.",
        verification_state=VerificationState.VERIFIED,
    )
    return cast(
        PreparedCollectionSemanticRuntime,
        SimpleNamespace(
            compile_input=SimpleNamespace(
                tenant_id=TENANT_ID, project_id=PROJECT_ID, collection_id=COLLECTION_ID
            ),
            index_expectations=(expectation,),
            graph_edges=(),
            canonical_model_sha256=CANONICAL,
        ),
    )


def _batch(recorded_at: datetime = COMPILED_AT) -> RetrievalIndexBatch:
    return build_collection_retrieval_batch(
        _prepared(),
        embeddings={"note:one": VECTOR},
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        recorded_at=recorded_at,
    )


def test_indexed_rows_carry_an_aware_recorded_at() -> None:
    local = datetime(2026, 11, 16, 18, 0, tzinfo=timezone(timedelta(hours=9)))
    for document in _batch(local).documents:
        stored = datetime.fromisoformat(str(document.payload.metadata["recorded_at"]))
        assert stored.utcoffset() is not None
        assert stored == local
        assert document.payload.as_vector_record().metadata["recorded_at"] == local.isoformat()


def test_a_naive_recorded_at_is_refused_at_batch_build() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _batch(datetime(2026, 11, 16, 9, 0))


class _RowStore(PostgresHybridStore):
    """Serves the batch rows through the reference temporal predicate (not SQL)."""

    def __init__(self, batch: RetrievalIndexBatch) -> None:
        self._records = [item.payload.as_vector_record() for item in batch.documents]
        self.queries: list[RetrievalQuery] = []

    async def search(self, query: RetrievalQuery) -> Sequence[VectorCandidate]:
        self.queries.append(query)
        return tuple(
            VectorCandidate(
                record=record,
                vector_score=1.0,
                bm25_score=0.0,
                graph_score=0.0,
                hybrid_score=1.0,
            )
            for record in self._records
            if admit(record.metadata, query).admitted
        )


async def _search(
    store: PostgresHybridStore,
    *,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
    available_at: datetime | None = None,
) -> tuple[VectorCandidate, ...]:
    return await search_collection_semantic_runtime(
        store,
        tenant_id=TENANT_ID,
        allowed_project_ids=(PROJECT_ID,),
        collection_id=COLLECTION_ID,
        vector=VECTOR,
        lexical_query="canonical",
        valid_at=valid_at,
        known_at=known_at,
        available_at=available_at,
    )


async def test_known_at_before_the_compile_returns_no_hits() -> None:
    store = _RowStore(_batch())
    assert await _search(store, known_at=COMPILED_AT - timedelta(seconds=1)) == ()
    assert len(await _search(store, known_at=COMPILED_AT)) == 1
    assert len(await _search(store)) == 1  # no cut: current mode, unchanged


async def test_rows_without_declared_dates_abstain_under_valid_and_available_cuts() -> None:
    store = _RowStore(_batch())
    assert await _search(store, available_at=COMPILED_AT) == ()
    assert await _search(store, valid_at=COMPILED_AT) == ()


# --- HTTP surface -----------------------------------------------------------------------


class _Session:
    def __init__(self) -> None:
        self.calls = 0
        self.collection = Collection(
            id=COLLECTION_ID,
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            name="Verified collection",
            status="COMPLETED",
            created_by=USER_ID,
        )
        self.values: tuple[Any, ...] = (
            self.collection,
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
                    "canonical_model_sha256": CANONICAL,
                    "retrieval_batch_sha256": "sha256:" + "d" * 64,
                    "indexed_records": 1,
                    "raw_text_persisted": False,
                },
            ),
            ArchitecturePlan(
                id=PLAN_ID,
                tenant_id=TENANT_ID,
                collection_id=COLLECTION_ID,
                plan_version=1,
                status="compiled",
                input_integrity_sha256="a" * 64,
                plan=PLAN_PAYLOAD,
                created_by=USER_ID,
            ),
            KnowledgeCompileRun(
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
            ),
        )

    async def scalar(self, _statement: Any) -> Any:
        self.calls += 1
        return self.values[self.calls - 1] if self.calls <= len(self.values) else None


class _Provider:
    provider_id = "qwen-attested"
    model_id = MODEL_ID
    model_revision = MODEL_REVISION

    async def embed_text(self, request: EmbeddingRequest, text: str) -> EmbeddingResult:
        return EmbeddingResult(
            provider_id=self.provider_id,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            source_hash=request.source_hash,
            vector=VECTOR,
        )


class _Executor:
    dialect_name = "postgresql"

    def __init__(self) -> None:
        self.parameters: dict[str, Any] | None = None

    async def fetch_all(self, _statement: Any, parameters: Any) -> tuple[()]:
        self.parameters = dict(parameters)
        return ()


class _RaisingStore(PostgresHybridStore):
    async def search(self, _query: Any) -> tuple[VectorCandidate, ...]:
        raise ProviderAttestationError("temporal metadata 'recorded_at' is malformed")


def _client(store: PostgresHybridStore) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(router)
    app.state.collection_semantic_retrieval_store = store
    app.state.collection_semantic_query_embedding_provider = _Provider()
    app.state.collection_semantic_query_embedding_model_id = MODEL_ID
    app.state.collection_semantic_query_embedding_model_revision = MODEL_REVISION
    app.dependency_overrides[get_session] = lambda: _Session()
    app.dependency_overrides[get_principal] = lambda: Principal(
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        roles=frozenset({"owner"}),
        scopes=frozenset({"api:read"}),
        auth_type="api_key",
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


_URL = f"/v1/collections/{COLLECTION_ID}/retrieval/search"


@pytest.mark.parametrize("field", ["validAt", "knownAt", "availableAt"])
async def test_a_naive_cut_is_a_422(field: str) -> None:
    executor = _Executor()
    store = PostgresHybridStore(executor=executor, row_attestor=HmacSha256RowAttestor(b"r" * 32))
    async with _client(store) as client:
        response = await client.post(_URL, json={"query": "evidence", field: "2026-11-16T09:00:00"})
    assert response.status_code == 422
    assert executor.parameters is None


async def test_an_aware_cut_reaches_the_store_query() -> None:
    executor = _Executor()
    store = PostgresHybridStore(executor=executor, row_attestor=HmacSha256RowAttestor(b"r" * 32))
    async with _client(store) as client:
        response = await client.post(
            _URL,
            json={"query": "evidence", "knownAt": "2026-11-16T18:00:00+09:00"},
        )
    assert response.status_code == 200, response.text
    assert executor.parameters is not None
    assert executor.parameters["has_known_at"] is True
    assert datetime.fromisoformat(executor.parameters["known_at"]) == COMPILED_AT
    assert executor.parameters["has_valid_at"] is False
    assert executor.parameters["has_available_at"] is False


async def test_response_states_which_temporal_cuts_abstained() -> None:
    executor = _Executor()
    store = PostgresHybridStore(executor=executor, row_attestor=HmacSha256RowAttestor(b"r" * 32))
    async with _client(store) as client:
        plain = await client.post(_URL, json={"query": "evidence"})
        cut = await client.post(
            _URL,
            json={
                "query": "evidence",
                "knownAt": "2026-11-16T09:00:00Z",
                "validAt": "2026-11-16T09:00:00Z",
                "availableAt": "2026-11-16T09:00:00Z",
            },
        )
    assert plain.json()["temporal_coverage"] == {
        "row_temporal_fields": ["recorded_at"],
        "abstained_cuts": [],
    }
    assert cut.status_code == 200, cut.text
    assert cut.json()["hits"] == []
    assert cut.json()["temporal_coverage"] == {
        "row_temporal_fields": ["recorded_at"],
        "abstained_cuts": ["valid_at", "available_at"],
    }


async def test_a_temporal_attestation_failure_is_a_closed_503() -> None:
    store = _RaisingStore(executor=_Executor(), row_attestor=HmacSha256RowAttestor(b"r" * 32))
    async with _client(store) as client:
        response = await client.post(
            _URL, json={"query": "evidence", "knownAt": "2026-11-16T09:00:00Z"}
        )
    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "COLLECTION_RETRIEVAL_FAILED_CLOSED"}


# --- sweep after the completion receipt -------------------------------------------------


class _Journal:
    def __init__(self) -> None:
        self.events: list[str] = []


class _CommitSession:
    def __init__(self, journal: _Journal, *, fail: bool = False) -> None:
        self._journal = journal
        self._fail = fail

    async def commit(self) -> None:
        if self._fail:
            raise RuntimeError("commit failed")
        self._journal.events.append("commit")


class _SweepExecutor:
    dialect_name = "postgresql"

    def __init__(self, journal: _Journal, removed: Sequence[str], *, fail_first: int = 0) -> None:
        self._journal = journal
        self._removed = list(removed)
        self._fail_first = fail_first
        self.keep: list[str] = []

    async def execute_transaction(
        self, mutations: Sequence[PostgreSQLMutation]
    ) -> Sequence[str | None]:
        self._journal.events.append("sweep")
        if self._fail_first:
            self._fail_first -= 1
            raise RuntimeError("database unavailable")
        self.keep.append(mutations[1].parameters["keep_sha256"])
        removed = self._removed.pop(0)
        return tuple(removed if m.requires_returned_row else None for m in mutations)


async def _commit_and_sweep(session: _CommitSession, executor: _SweepExecutor) -> int | None:
    return await commit_then_sweep_superseded(
        cast(AsyncSession, session),
        PostgresHybridIndexer(executor=executor, row_attestor=HmacSha256RowAttestor(b"r" * 32)),
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        collection_id=COLLECTION_ID,
        canonical_model_sha256=CANONICAL,
    )


async def test_sweep_runs_after_the_completion_receipt_and_is_idempotent() -> None:
    journal = _Journal()
    executor = _SweepExecutor(journal, ["4", "0"])
    session = _CommitSession(journal)
    assert await _commit_and_sweep(session, executor) == 4
    assert await _commit_and_sweep(session, executor) == 0  # redelivery removes nothing
    assert journal.events == ["commit", "sweep", "commit", "sweep"]
    assert executor.keep == [CANONICAL, CANONICAL]


async def test_a_failed_commit_never_sweeps() -> None:
    journal = _Journal()
    with pytest.raises(RuntimeError, match="commit failed"):
        await _commit_and_sweep(_CommitSession(journal, fail=True), _SweepExecutor(journal, ["1"]))
    assert journal.events == []


async def test_sweep_failure_does_not_mark_the_compile_failed_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    journal = _Journal()
    executor = _SweepExecutor(journal, ["2"], fail_first=1)
    with caplog.at_level(logging.ERROR):
        assert await _commit_and_sweep(_CommitSession(journal), executor) == 2  # retried once
    failures = [r for r in caplog.records if r.getMessage() == "COLLECTION_RETRIEVAL_SWEEP_FAILED"]
    assert len(failures) == 1
    assert failures[0].__dict__["code"] == "COLLECTION_RETRIEVAL_SWEEP_FAILED"
    assert journal.events == ["commit", "sweep", "sweep"]

    caplog.clear()
    journal = _Journal()
    with caplog.at_level(logging.ERROR):
        result = await _commit_and_sweep(
            _CommitSession(journal), _SweepExecutor(journal, [], fail_first=2)
        )
    assert result is None  # the compile stays committed; the failure is reported, not hidden
    assert journal.events == ["commit", "sweep", "sweep"]
    assert sum(r.getMessage() == "COLLECTION_RETRIEVAL_SWEEP_FAILED" for r in caplog.records) == 2
