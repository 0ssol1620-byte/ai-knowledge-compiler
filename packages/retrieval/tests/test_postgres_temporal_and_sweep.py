from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from akc_retrieval import (
    HmacSha256RowAttestor,
    PostgresHybridIndexer,
    PostgreSQLMutation,
    RetrievalRowAttestationError,
    RetrievalUnavailable,
)

from .test_postgres import (
    COLLECTION_ID,
    KEY,
    PROJECT_ID,
    TENANT_ID,
    _Executor,
    _MutationExecutor,
    _payload,
    _query,
    _row,
    _store,
)

KNOWN = datetime(2026, 1, 1, tzinfo=UTC)
KEEP = "c" * 64


def _row_with(metadata: dict[str, str | int | float | bool | None]) -> dict[str, object]:
    attestor = HmacSha256RowAttestor(KEY)
    payload = _payload().model_copy(update={"metadata": metadata})
    return _row(payload, attestor)


def _filtered_cte(sql: str) -> str:
    return sql[sql.index("filtered AS MATERIALIZED") : sql.index("vector_candidates")]


async def test_known_at_predicate_runs_inside_the_filtered_cte_before_ranking() -> None:
    executor = _Executor()
    query = _query().model_copy(
        update={"known_at": KNOWN, "valid_at": KNOWN, "available_at": KNOWN}
    )
    await _store(executor, HmacSha256RowAttestor(KEY)).search(query)

    assert executor.parameters is not None
    cte = _filtered_cte(str(executor.statement))
    assert "record.metadata->>'recorded_at'" in cte
    assert "CAST(:known_at AS timestamptz)" in cte
    assert "record.metadata->>'available_at'" in cte
    assert "record.metadata->>'valid_from'" in cte
    assert "record.metadata->>'valid_to'" in cte
    assert executor.parameters["has_known_at"] is True
    assert executor.parameters["known_at"] == KNOWN.isoformat()
    assert executor.parameters["has_valid_at"] is True
    assert executor.parameters["has_available_at"] is True
    assert executor.parameters["include_unknown_validity"] is False


async def test_no_cut_sends_the_same_parameters_as_before() -> None:
    executor = _Executor()
    await _store(executor, HmacSha256RowAttestor(KEY)).search(_query())

    p = executor.parameters
    assert p is not None
    for name in ("valid_at", "known_at", "available_at"):
        assert p[f"has_{name}"] is False
        assert p[name] is None


async def test_a_returned_row_outside_the_cut_is_rejected() -> None:
    row = _row_with({"recorded_at": "2026-06-01T00:00:00+00:00"})
    store = _store(_Executor([row]), HmacSha256RowAttestor(KEY))
    query = _query().model_copy(update={"known_at": KNOWN})
    with pytest.raises(RetrievalRowAttestationError, match="temporal cut"):
        await store.search(query)


async def test_a_returned_row_inside_the_cut_is_accepted() -> None:
    row = _row_with({"recorded_at": "2025-06-01T00:00:00+00:00"})
    store = _store(_Executor([row]), HmacSha256RowAttestor(KEY))
    query = _query().model_copy(update={"known_at": KNOWN})
    assert len(await store.search(query)) == 1


class _CountingExecutor(_MutationExecutor):
    async def execute_transaction(
        self, mutations: Sequence[PostgreSQLMutation]
    ) -> Sequence[str | None]:
        self.mutations = tuple(mutations)
        return tuple("3" if m.requires_returned_row else None for m in mutations)


def _indexer(executor: _MutationExecutor) -> PostgresHybridIndexer:
    return PostgresHybridIndexer(executor=executor, row_attestor=HmacSha256RowAttestor(KEY))


async def _sweep(executor: _MutationExecutor) -> int:
    return await _indexer(executor).sweep_superseded(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        collection_id=COLLECTION_ID,
        keep_canonical_model_sha256=KEEP,
    )


async def test_sweep_deletes_terms_edges_and_records_of_the_superseded_model_only() -> None:
    executor = _CountingExecutor()
    assert await _sweep(executor) == 3
    sql = [str(m.statement) for m in executor.mutations]
    assert "pg_advisory_xact_lock" in sql[0]
    assert "knowledge_retrieval_term_frequencies" in sql[1]
    assert "knowledge_retrieval_edges" in sql[2]
    assert "DELETE FROM knowledge_retrieval_records" in sql[3]
    for statement in sql[1:4]:
        assert "IS DISTINCT FROM CAST(:keep_sha256 AS text)" in statement
    assert executor.mutations[3].parameters["keep_sha256"] == KEEP


async def test_sweep_is_scoped_to_tenant_project_and_collection() -> None:
    executor = _CountingExecutor()
    await _sweep(executor)
    for mutation in executor.mutations[1:4]:
        statement = str(mutation.statement)
        assert "tenant_id = CAST(:tenant_id AS uuid)" in statement
        assert "project_id = CAST(:project_id AS uuid)" in statement
        assert mutation.parameters["tenant_id"] == str(TENANT_ID)
        assert mutation.parameters["project_id"] == str(PROJECT_ID)
    for mutation in (executor.mutations[1], executor.mutations[3]):
        assert "collection_id = CAST(:collection_id AS uuid)" in str(mutation.statement)
        assert mutation.parameters["collection_id"] == str(COLLECTION_ID)


async def test_sweep_rebuilds_term_and_corpus_stats() -> None:
    executor = _CountingExecutor()
    await _sweep(executor)
    tail = [str(m.statement) for m in executor.mutations[4:]]
    assert "DELETE FROM knowledge_retrieval_term_stats" in tail[0]
    assert "INSERT INTO knowledge_retrieval_term_stats" in tail[1]
    assert "INSERT INTO knowledge_retrieval_corpus_stats" in tail[2]


async def test_sweep_failure_raises_and_reports_nothing_removed() -> None:
    class _Failing(_MutationExecutor):
        async def execute_transaction(
            self, mutations: Sequence[PostgreSQLMutation]
        ) -> Sequence[str | None]:
            raise RuntimeError("database unavailable")

    with pytest.raises(RetrievalUnavailable):
        await _sweep(_Failing())


async def test_sweep_rejects_a_malformed_keep_digest() -> None:
    with pytest.raises(ValueError):
        await _indexer(_CountingExecutor()).sweep_superseded(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            collection_id=uuid.uuid4(),
            keep_canonical_model_sha256="not-a-digest",
        )
