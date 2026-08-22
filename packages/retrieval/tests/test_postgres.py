from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from akc_retrieval import (
    POSTGRES_HYBRID_SEARCH_SQL,
    PRODUCTION_EMBEDDING_DIMENSION,
    AttestedRetrievalPayload,
    HmacSha256RowAttestor,
    MediaKind,
    PostgresHybridIndexer,
    PostgresHybridStore,
    PostgreSQLMutation,
    RetrievalFilters,
    RetrievalIndexBatch,
    RetrievalIndexDocument,
    RetrievalIndexEdge,
    RetrievalQuery,
    RetrievalRowAttestationError,
    RetrievalUnavailable,
    VerificationState,
    build_index_mutations,
)
from sqlalchemy.sql.elements import TextClause

TENANT_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()
COLLECTION_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()
EVIDENCE_ID = uuid.uuid4()
REVISION = "a" * 40
KEY = bytes(range(32))


def _vector() -> tuple[float, ...]:
    return tuple(float(index + 1) / 10_000 for index in range(PRODUCTION_EMBEDDING_DIMENSION))


def _payload(
    *,
    tenant_id: uuid.UUID = TENANT_ID,
    project_id: uuid.UUID = PROJECT_ID,
    collection_id: uuid.UUID = COLLECTION_ID,
) -> AttestedRetrievalPayload:
    return AttestedRetrievalPayload(
        tenant_id=tenant_id,
        project_id=project_id,
        collection_id=collection_id,
        stable_id="fact/revenue/2025",
        document_id=DOCUMENT_ID,
        media_kind=MediaKind.TABLE,
        source_hash="b" * 64,
        evidence_block_ids=(EVIDENCE_ID,),
        model_id="qwen3-embedding-0.6b",
        model_revision=REVISION,
        vector=_vector(),
        statement="INCOME_STATEMENT",
        concept="Revenue",
        period_start="2025-01-01",
        period_end="2025-12-31",
        current_prior="current",
        consolidation="consolidated",
        unit="KRW",
        currency="KRW",
        entity_id="corp-001",
        source_type="dart_xbrl",
        verification_state=VerificationState.AUTHORITY_VERIFIED,
        metadata={"page": 7},
    )


def _row(
    payload: AttestedRetrievalPayload,
    attestor: HmacSha256RowAttestor,
) -> dict[str, Any]:
    dumped = payload.model_dump(mode="json")
    return {
        **{
            key: dumped[key]
            for key in (
                "tenant_id",
                "project_id",
                "collection_id",
                "stable_id",
                "document_id",
                "media_kind",
                "source_hash",
                "evidence_block_ids",
                "model_id",
                "model_revision",
                "statement",
                "concept",
                "period_start",
                "period_end",
                "instant",
                "current_prior",
                "consolidation",
                "unit",
                "currency",
                "entity_id",
                "source_type",
                "verification_state",
                "metadata",
            )
        },
        "embedding_text": json.dumps(list(payload.vector)),
        "attested_payload": dumped,
        "row_attestation": attestor.sign(payload),
        "vector_score": 1.0,
        "bm25_score": 0.7,
        "graph_score": 0.6,
        "hybrid_score": 0.85,
    }


def _query(*, lexical_query: str = "revenue") -> RetrievalQuery:
    return RetrievalQuery(
        tenant_id=TENANT_ID,
        project_ids=(PROJECT_ID,),
        vector=_vector(),
        lexical_query=lexical_query,
        graph_seed_ids=("entity/corp-001",),
        media_kinds=frozenset({MediaKind.TABLE}),
        filters=RetrievalFilters(
            collection_ids=frozenset({COLLECTION_ID}),
            document_ids=frozenset({str(DOCUMENT_ID)}),
            statement="INCOME_STATEMENT",
            concept="Revenue",
            period_start="2025-01-01",
            period_end="2025-12-31",
            current_prior="current",
            consolidation="consolidated",
            unit="KRW",
            currency="KRW",
            entity_id="corp-001",
            source_type="dart_xbrl",
            verification_states=frozenset({VerificationState.AUTHORITY_VERIFIED}),
        ),
        candidate_k=30,
        top_k=5,
    )


class _Executor:
    dialect_name = "postgresql"

    def __init__(self, rows: Sequence[Mapping[str, Any]] = ()) -> None:
        self.rows = rows
        self.statement: TextClause | None = None
        self.parameters: Mapping[str, Any] | None = None

    async def fetch_all(
        self,
        statement: TextClause,
        parameters: Mapping[str, Any],
    ) -> Sequence[Mapping[str, Any]]:
        self.statement = statement
        self.parameters = parameters
        return self.rows


class _FailingExecutor(_Executor):
    async def fetch_all(
        self,
        statement: TextClause,
        parameters: Mapping[str, Any],
    ) -> Sequence[Mapping[str, Any]]:
        raise RuntimeError("database unavailable")


class _MutationExecutor:
    dialect_name = "postgresql"

    def __init__(self, *, reject_returning_index: int | None = None) -> None:
        self.mutations: tuple[PostgreSQLMutation, ...] = ()
        self.reject_returning_index = reject_returning_index

    async def execute_transaction(
        self,
        mutations: Sequence[PostgreSQLMutation],
    ) -> Sequence[str | None]:
        self.mutations = tuple(mutations)
        return tuple(
            None
            if not mutation.requires_returned_row or index == self.reject_returning_index
            else "indexed"
            for index, mutation in enumerate(mutations)
        )


class _FailingMutationExecutor(_MutationExecutor):
    async def execute_transaction(
        self,
        mutations: Sequence[PostgreSQLMutation],
    ) -> Sequence[str | None]:
        raise RuntimeError("database unavailable")


def _store(executor: _Executor, attestor: HmacSha256RowAttestor) -> PostgresHybridStore:
    return PostgresHybridStore(executor=executor, row_attestor=attestor)


async def test_sql_is_parameterised_and_filters_materialise_before_all_ranking() -> None:
    attack = "revenue'); DROP TABLE knowledge_retrieval_records; --"
    executor = _Executor()
    store = _store(executor, HmacSha256RowAttestor(KEY))

    assert await store.search(_query(lexical_query=attack)) == ()

    assert executor.statement is not None
    assert executor.parameters is not None
    sql = str(executor.statement)
    assert attack not in sql
    assert executor.parameters["lexical_query"] == attack
    assert ":lexical_query" in sql
    assert sql.index("filtered AS MATERIALIZED") < sql.index("vector_candidates")
    assert sql.index("filtered AS MATERIALIZED") < sql.index("bm25_candidates")
    assert sql.index("filtered AS MATERIALIZED") < sql.index("graph_candidates")
    assert "record.tenant_id = CAST(:tenant_id AS uuid)" in sql
    assert "record.project_id = ANY(CAST(:project_ids AS uuid[]))" in sql
    assert "record.collection_id = ANY(CAST(:collection_ids AS uuid[]))" in sql
    assert "record.document_id::text = ANY(CAST(:document_ids AS text[]))" in sql
    assert executor.parameters["verification_states"] == ["authority_verified"]


async def test_signed_row_returns_individual_and_hybrid_scores() -> None:
    attestor = HmacSha256RowAttestor(KEY)
    payload = _payload()
    store = _store(_Executor((_row(payload, attestor),)), attestor)

    candidates = await store.search(_query())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.record.stable_id == payload.stable_id
    assert candidate.vector_score == 1.0
    assert candidate.bm25_score == 0.7
    assert candidate.graph_score == 0.6
    assert candidate.hybrid_score == 0.85
    assert candidate.record.metadata["verification_state"] == "authority_verified"
    assert candidate.record.metadata["document_id"] == str(DOCUMENT_ID)


@pytest.mark.parametrize("field", ["source_hash", "document_id", "verification_state"])
async def test_attested_row_column_tampering_fails_closed(field: str) -> None:
    attestor = HmacSha256RowAttestor(KEY)
    row = _row(_payload(), attestor)
    row[field] = "tampered"

    with pytest.raises(RetrievalRowAttestationError, match="differs from attested"):
        await _store(_Executor((row,)), attestor).search(_query())


async def test_invalid_signature_fails_closed() -> None:
    attestor = HmacSha256RowAttestor(KEY)
    row = _row(_payload(), attestor)
    row["row_attestation"] = "hmac-sha256:primary:" + ("0" * 64)

    with pytest.raises(RetrievalRowAttestationError, match="attestation mismatch"):
        await _store(_Executor((row,)), attestor).search(_query())


async def test_validly_signed_cross_tenant_row_is_still_rejected() -> None:
    attestor = HmacSha256RowAttestor(KEY)
    payload = _payload(tenant_id=uuid.uuid4())

    with pytest.raises(RetrievalRowAttestationError, match="tenant or project"):
        await _store(_Executor((_row(payload, attestor),)), attestor).search(_query())


async def test_validly_signed_cross_collection_row_is_still_rejected() -> None:
    attestor = HmacSha256RowAttestor(KEY)
    payload = _payload(collection_id=uuid.uuid4())

    with pytest.raises(RetrievalRowAttestationError, match="collection scope"):
        await _store(_Executor((_row(payload, attestor),)), attestor).search(_query())


async def test_out_of_range_database_score_fails_closed() -> None:
    attestor = HmacSha256RowAttestor(KEY)
    row = _row(_payload(), attestor)
    row["hybrid_score"] = 1.01

    with pytest.raises(RetrievalRowAttestationError, match="score"):
        await _store(_Executor((row,)), attestor).search(_query())


async def test_database_error_has_no_in_memory_fallback() -> None:
    store = _store(_FailingExecutor(), HmacSha256RowAttestor(KEY))

    with pytest.raises(RetrievalUnavailable, match="failed closed"):
        await store.search(_query())


def test_non_postgresql_executor_and_weak_attestation_key_are_rejected() -> None:
    executor = _Executor()
    executor.dialect_name = "sqlite"
    with pytest.raises(RetrievalUnavailable, match="PostgreSQL"):
        _store(executor, HmacSha256RowAttestor(KEY))
    with pytest.raises(ValueError, match="at least 32"):
        HmacSha256RowAttestor(b"short")
    with pytest.raises(ValueError, match="dimension must be 1024"):
        PostgresHybridStore(
            executor=_Executor(),
            row_attestor=HmacSha256RowAttestor(KEY),
            dimension=32,
        )


def test_attestation_key_rotation_accepts_pinned_previous_key() -> None:
    previous_key = bytes(range(1, 33))
    payload = _payload()
    previous = HmacSha256RowAttestor(previous_key, key_id="2026q2")
    current = HmacSha256RowAttestor(
        KEY,
        key_id="2026q3",
        verification_keys={"2026q2": previous_key},
    )

    assert current.verify(payload, previous.sign(payload))
    assert current.sign(payload).startswith("hmac-sha256:2026q3:")


def test_query_bounds_graph_seeds_and_lexical_input() -> None:
    with pytest.raises(ValueError, match="graph seed ids"):
        RetrievalQuery(
            tenant_id=TENANT_ID,
            project_ids=(PROJECT_ID,),
            vector=_vector(),
            graph_seed_ids=("same", "same"),
        )
    with pytest.raises(ValueError, match="at most 2000"):
        RetrievalQuery(
            tenant_id=TENANT_ID,
            project_ids=(PROJECT_ID,),
            vector=_vector(),
            lexical_query="x" * 2_001,
        )


def test_sql_contract_contains_true_bm25_and_bidirectional_graph_neighbourhood() -> None:
    assert "term_frequency" in POSTGRES_HYBRID_SEARCH_SQL
    assert "document_frequency" in POSTGRES_HYBRID_SEARCH_SQL
    assert "average_token_count" in POSTGRES_HYBRID_SEARCH_SQL
    assert "from_stable_id = ANY" in POSTGRES_HYBRID_SEARCH_SQL
    assert "to_stable_id = ANY" in POSTGRES_HYBRID_SEARCH_SQL


async def test_production_indexer_writes_attested_records_terms_edges_and_stats_atomically() -> (
    None
):
    executor = _MutationExecutor()
    attestor = HmacSha256RowAttestor(KEY, key_id="2026q3")
    payload = _payload()
    edge_target = payload.model_copy(update={"stable_id": "entity/corp-001"})
    batch = RetrievalIndexBatch(
        tenant_id=TENANT_ID,
        documents=(
            RetrievalIndexDocument(
                payload=payload,
                lexical_text="Revenue revenue increased for the current reporting period.",
            ),
            RetrievalIndexDocument(
                payload=edge_target,
                lexical_text="Corporate entity and reporting identity.",
            ),
        ),
        edges=(
            RetrievalIndexEdge(
                project_id=PROJECT_ID,
                from_stable_id=payload.stable_id,
                to_stable_id=edge_target.stable_id,
                edge_weight=0.9,
            ),
        ),
    )

    receipt = await PostgresHybridIndexer(
        executor=executor,
        row_attestor=attestor,
    ).index(batch)

    assert receipt.indexed_records == 2
    assert receipt.indexed_edges == 1
    assert receipt.indexed_terms == 12
    assert receipt.batch_sha256.startswith("sha256:")
    assert receipt.raw_text_persisted is False
    assert len(executor.mutations) == 11
    assert "pg_advisory_xact_lock" in str(executor.mutations[0].statement)
    upsert = executor.mutations[1]
    assert "ON CONFLICT" in str(upsert.statement)
    assert upsert.parameters["document_id"] == str(DOCUMENT_ID)
    assert str(upsert.parameters["row_attestation"]).startswith("hmac-sha256:2026q3:")
    assert "lexical_text" not in upsert.parameters
    assert "Revenue revenue increased" not in json.dumps(
        [dict(mutation.parameters) for mutation in executor.mutations],
        default=str,
    )
    term_mutation = executor.mutations[3]
    assert term_mutation.parameters["terms"] == [
        "current",
        "for",
        "increased",
        "period",
        "reporting",
        "revenue",
        "the",
    ]
    assert term_mutation.parameters["term_frequencies"][-2] == 2


async def test_indexer_fails_closed_on_scope_collision_or_database_failure() -> None:
    batch = RetrievalIndexBatch(
        tenant_id=TENANT_ID,
        documents=(RetrievalIndexDocument(payload=_payload(), lexical_text="revenue"),),
    )
    attestor = HmacSha256RowAttestor(KEY)
    with pytest.raises(RetrievalRowAttestationError, match="scope collision"):
        await PostgresHybridIndexer(
            executor=_MutationExecutor(reject_returning_index=1),
            row_attestor=attestor,
        ).index(batch)
    with pytest.raises(RetrievalUnavailable, match="indexing failed closed"):
        await PostgresHybridIndexer(
            executor=_FailingMutationExecutor(),
            row_attestor=attestor,
        ).index(batch)


def test_index_batch_rejects_cross_tenant_duplicate_or_nonlexical_inputs() -> None:
    document = RetrievalIndexDocument(payload=_payload(), lexical_text="revenue")
    with pytest.raises(ValueError, match="batch tenant"):
        RetrievalIndexBatch(
            tenant_id=uuid.uuid4(),
            documents=(document,),
        )
    with pytest.raises(ValueError, match="unique stable ids"):
        RetrievalIndexBatch(
            tenant_id=TENANT_ID,
            documents=(document, document),
        )
    with pytest.raises(ValueError, match="no indexable terms"):
        build_index_mutations(
            RetrievalIndexBatch(
                tenant_id=TENANT_ID,
                documents=(RetrievalIndexDocument(payload=_payload(), lexical_text="---"),),
            ),
            HmacSha256RowAttestor(KEY),
        )
