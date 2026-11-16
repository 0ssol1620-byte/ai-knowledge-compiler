from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from akc_retrieval import (
    InMemoryVectorStore,
    ProviderAttestationError,
    RetrievalQuery,
    RetrievalService,
    VectorCandidate,
    VectorRecord,
    admit,
)
from pydantic import ValidationError

TENANT = uuid.uuid4()
PROJECT = uuid.uuid4()
CUT = datetime(2026, 3, 1, tzinfo=UTC)


def _vec() -> tuple[float, ...]:
    return (1.0,) * 32


def _record(stable_id: str, **metadata: str) -> VectorRecord:
    return VectorRecord(
        tenant_id=TENANT,
        project_id=PROJECT,
        stable_id=stable_id,
        media_kind="text",
        source_hash="b" * 64,
        evidence_block_ids=(uuid.uuid4(),),
        model_id="m",
        model_revision="a" * 40,
        vector=_vec(),
        metadata=dict(metadata),
    )


def _query(**cut: object) -> RetrievalQuery:
    return RetrievalQuery(tenant_id=TENANT, project_ids=(PROJECT,), vector=_vec(), **cut)  # type: ignore[arg-type]


def _service(store: object) -> RetrievalService:
    return RetrievalService(
        vector_store=store,  # type: ignore[arg-type]
        reranker=None,
        expected_reranker_id=None,
        expected_reranker_revision=None,
        feature_enabled=True,
        provider_ready=True,
    )


async def _ids(*records: VectorRecord, **cut: object) -> set[str]:
    store = InMemoryVectorStore(dimension=32)
    store.upsert(records)
    return {c.record.stable_id for c in await store.search(_query(**cut))}


@pytest.mark.asyncio
async def test_known_at_excludes_a_row_recorded_later() -> None:
    rows = (
        _record("old", recorded_at="2026-02-01T00:00:00+00:00"),
        _record("new", recorded_at="2026-04-01T00:00:00+00:00"),
    )
    assert await _ids(*rows, known_at=CUT) == {"old"}
    assert admit(rows[1].metadata, _query(known_at=CUT)).reason == "excluded_known_after"


@pytest.mark.asyncio
async def test_known_at_excludes_a_row_with_no_recorded_at() -> None:
    row = _record("x", page="1")
    assert await _ids(row, known_at=CUT) == set()
    assert admit(row.metadata, _query(known_at=CUT)).reason == "excluded_unrecorded"


@pytest.mark.asyncio
async def test_available_at_excludes_a_row_published_later() -> None:
    row = _record("x", available_at="2026-04-01T00:00:00+00:00")
    assert await _ids(row, available_at=CUT) == set()
    assert admit(row.metadata, _query(available_at=CUT)).reason == "excluded_available_after"


@pytest.mark.asyncio
async def test_available_at_excludes_a_row_with_unknown_availability() -> None:
    row = _record("x", recorded_at="2026-01-01T00:00:00+00:00")
    assert await _ids(row, available_at=CUT) == set()
    assert admit(row.metadata, _query(available_at=CUT)).reason == "excluded_unavailable"


@pytest.mark.asyncio
async def test_valid_at_excludes_an_expired_row() -> None:
    row = _record("x", valid_from="2025-01-01T00:00:00+00:00", valid_to="2026-01-01T00:00:00+00:00")
    assert await _ids(row, valid_at=CUT) == set()
    assert admit(row.metadata, _query(valid_at=CUT)).reason == "excluded_not_valid"


@pytest.mark.asyncio
async def test_unknown_validity_is_excluded_unless_included_explicitly() -> None:
    row = _record("x", page="1")
    assert await _ids(row, valid_at=CUT) == set()
    assert admit(row.metadata, _query(valid_at=CUT)).reason == "excluded_unknown_validity"
    assert await _ids(row, valid_at=CUT, include_unknown_validity=True) == {"x"}


@pytest.mark.asyncio
async def test_no_cut_keeps_current_behaviour() -> None:
    rows = (_record("a"), _record("b", recorded_at="garbage", valid_from="garbage"))
    assert await _ids(*rows) == {"a", "b"}


def test_a_naive_query_moment_is_rejected_by_the_model() -> None:
    with pytest.raises(ValidationError):
        _query(known_at=datetime(2026, 3, 1))


@pytest.mark.asyncio
async def test_a_store_that_ignores_the_cut_is_rejected_after_ranking() -> None:
    class Leaky:
        async def search(self, query: RetrievalQuery) -> list[VectorCandidate]:
            return [
                VectorCandidate(
                    record=_record("future", recorded_at="2026-04-01T00:00:00+00:00"),
                    vector_score=0.5,
                )
            ]

    with pytest.raises(ProviderAttestationError, match="temporal cut"):
        await _service(Leaky()).search(_query(known_at=CUT), query_fingerprint="f" * 64)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["not a date", "2026-01-01T00:00:00"])
async def test_unparsable_temporal_metadata_fails_closed(bad: str) -> None:
    with pytest.raises(ProviderAttestationError):
        await _ids(_record("x", recorded_at=bad), known_at=CUT)
