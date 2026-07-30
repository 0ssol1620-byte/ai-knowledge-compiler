from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest
from akc_retrieval import (
    InMemoryVectorStore,
    MediaKind,
    ProviderAttestationError,
    RerankRequest,
    RerankResult,
    RetrievalQuery,
    RetrievalService,
    RetrievalUnavailable,
    VectorCandidate,
    VectorRecord,
)

TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
PROJECT = uuid.uuid4()
OTHER_PROJECT = uuid.uuid4()
REVISION = "a" * 40


def _vector(first: float, dimension: int = 32) -> tuple[float, ...]:
    return (first, *(1.0 for _ in range(dimension - 1)))


def _record(
    stable_id: str,
    *,
    tenant_id: uuid.UUID = TENANT,
    project_id: uuid.UUID = PROJECT,
    first: float = 1.0,
    media_kind: MediaKind = MediaKind.TEXT,
    metadata: dict[str, str | int | float | bool | None] | None = None,
) -> VectorRecord:
    return VectorRecord(
        tenant_id=tenant_id,
        project_id=project_id,
        stable_id=stable_id,
        media_kind=media_kind,
        source_hash="b" * 64,
        evidence_block_ids=(uuid.uuid4(),),
        model_id="qwen3-embedding-0.6b",
        model_revision=REVISION,
        vector=_vector(first),
        metadata=metadata or {"page": 1},
    )


def _query(*, top_k: int = 5) -> RetrievalQuery:
    return RetrievalQuery(
        tenant_id=TENANT,
        project_ids=(PROJECT,),
        vector=_vector(1.0),
        candidate_k=30,
        top_k=top_k,
    )


async def test_store_filters_tenant_project_and_modality_before_ranking() -> None:
    store = InMemoryVectorStore(dimension=32)
    store.upsert(
        [
            _record("allowed"),
            _record("other-tenant", tenant_id=OTHER_TENANT, first=100.0),
            _record("other-project", project_id=OTHER_PROJECT, first=100.0),
            _record("image", media_kind=MediaKind.IMAGE),
        ]
    )
    query = _query().model_copy(update={"media_kinds": frozenset({MediaKind.TEXT})})

    candidates = await store.search(query)

    assert [candidate.record.stable_id for candidate in candidates] == ["allowed"]
    assert store.delete_project(tenant_id=TENANT, project_id=PROJECT) == 2
    assert await store.search(query) == []


class _Reranker:
    provider_id = "qwen3_reranker_0_6b"

    async def rerank(self, request: RerankRequest) -> RerankResult:
        ordered = tuple(reversed(request.candidate_ids[: request.top_k]))
        return RerankResult(
            provider_id=self.provider_id,
            model_revision=REVISION,
            ordered_candidate_ids=ordered,
            scores={stable_id: float(index) for index, stable_id in enumerate(ordered)},
        )


async def test_verified_reranker_controls_final_order_without_losing_evidence() -> None:
    store = InMemoryVectorStore(dimension=32)
    store.upsert([_record(f"note-{index:02d}", first=float(index + 1)) for index in range(8)])
    service = RetrievalService(
        vector_store=store,
        reranker=_Reranker(),
        expected_reranker_id="qwen3_reranker_0_6b",
        expected_reranker_revision=REVISION,
        feature_enabled=True,
        provider_ready=True,
    )

    hits = await service.search(_query(), query_fingerprint="h1_" + ("c" * 64))

    assert len(hits) == 5
    assert all(hit.evidence_block_ids for hit in hits)
    assert all(hit.source_hash == "b" * 64 for hit in hits)


async def test_disabled_or_unverified_lane_fails_closed() -> None:
    store = InMemoryVectorStore(dimension=32)
    service = RetrievalService(
        vector_store=store,
        reranker=None,
        expected_reranker_id=None,
        expected_reranker_revision=None,
        feature_enabled=False,
        provider_ready=False,
    )
    with pytest.raises(RetrievalUnavailable):
        await service.search(_query(), query_fingerprint="h1_" + ("c" * 64))


class _LeakyStore:
    async def search(self, query: RetrievalQuery) -> Sequence[VectorCandidate]:
        return [
            VectorCandidate(
                record=_record("leak", tenant_id=OTHER_TENANT),
                vector_score=1.0,
            )
        ]


async def test_acl_violation_from_store_is_rejected() -> None:
    service = RetrievalService(
        vector_store=_LeakyStore(),
        reranker=None,
        expected_reranker_id=None,
        expected_reranker_revision=None,
        feature_enabled=True,
        provider_ready=True,
    )
    with pytest.raises(ProviderAttestationError, match="ACL"):
        await service.search(_query(), query_fingerprint="h1_" + ("c" * 64))


class _WrongRevisionReranker(_Reranker):
    async def rerank(self, request: RerankRequest) -> RerankResult:
        result = await super().rerank(request)
        return result.model_copy(update={"model_revision": "d" * 40})


async def test_reranker_revision_mismatch_is_rejected() -> None:
    store = InMemoryVectorStore(dimension=32)
    store.upsert([_record(f"note-{index:02d}") for index in range(5)])
    service = RetrievalService(
        vector_store=store,
        reranker=_WrongRevisionReranker(),
        expected_reranker_id="qwen3_reranker_0_6b",
        expected_reranker_revision=REVISION,
        feature_enabled=True,
        provider_ready=True,
    )
    with pytest.raises(ProviderAttestationError, match="revision"):
        await service.search(_query(), query_fingerprint="h1_" + ("c" * 64))


def test_content_and_secret_metadata_are_rejected() -> None:
    with pytest.raises(ValueError, match="secret"):
        _record("unsafe", metadata={"content": "document body"})
