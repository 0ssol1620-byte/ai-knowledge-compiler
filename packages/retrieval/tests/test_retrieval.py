from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

import pytest
from akc_retrieval import (
    InMemoryVectorStore,
    MediaKind,
    NumericAnswerState,
    NumericAuthorityFact,
    NumericFactKey,
    ProviderAttestationError,
    RerankRequest,
    RerankResult,
    RetrievalFilters,
    RetrievalQuery,
    RetrievalService,
    RetrievalUnavailable,
    VectorCandidate,
    VectorRecord,
    VerificationState,
    verify_numeric_answer,
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
        assert set(request.candidate_scores) == set(request.candidate_ids)
        assert all(
            score.vector_score <= 1 and score.bm25_score >= 0
            for score in request.candidate_scores.values()
        )
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


def test_in_memory_store_cannot_be_wired_in_production_mode() -> None:
    with pytest.raises(RetrievalUnavailable, match="development-only"):
        RetrievalService(
            vector_store=InMemoryVectorStore(dimension=32),
            reranker=None,
            expected_reranker_id=None,
            expected_reranker_revision=None,
            feature_enabled=True,
            provider_ready=True,
            production_mode=True,
        )


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


async def test_structured_filters_run_before_vector_ranking() -> None:
    store = InMemoryVectorStore(dimension=32)
    collection_id = uuid.uuid4()
    verified: dict[str, str | int | float | bool | None] = {
        "collection_id": str(collection_id),
        "document_id": "doc-a",
        "statement": "INCOME_STATEMENT",
        "concept": "Revenue",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "unit": "KRW",
        "currency": "KRW",
        "verification_state": "authority_verified",
    }
    store.upsert(
        [
            _record("exact", first=0.5, metadata=verified),
            _record(
                "wrong-collection",
                first=100.0,
                metadata={**verified, "collection_id": str(uuid.uuid4())},
            ),
            _record("wrong-period", first=100.0, metadata={**verified, "period_end": "2024-12-31"}),
            _record(
                "unresolved",
                first=100.0,
                metadata={**verified, "verification_state": "unresolved"},
            ),
        ]
    )
    query = _query().model_copy(
        update={
            "filters": RetrievalFilters(
                collection_ids=frozenset({collection_id}),
                document_ids=frozenset({"doc-a"}),
                statement="INCOME_STATEMENT",
                concept="Revenue",
                period_start="2025-01-01",
                period_end="2025-12-31",
                unit="KRW",
                currency="KRW",
                verification_states=frozenset({VerificationState.AUTHORITY_VERIFIED}),
            )
        }
    )
    assert [item.record.stable_id for item in await store.search(query)] == ["exact"]


def _fact_key() -> NumericFactKey:
    return NumericFactKey(
        entity_id="corp-001",
        statement="INCOME_STATEMENT",
        concept="Revenue",
        period_start="2025-01-01",
        period_end="2025-12-31",
        unit="KRW",
        currency="KRW",
        scale=1_000_000,
        dimensions_hash="c" * 64,
    )


def test_numeric_answer_requires_exact_authority_value_context_and_source() -> None:
    fact = NumericAuthorityFact(
        stable_id="fact-001",
        key=_fact_key(),
        value=Decimal("1234"),
        source_block_ids=("block-001",),
        source_hash="d" * 64,
        authority_type="xbrl",
        verification_state=VerificationState.AUTHORITY_VERIFIED,
    )
    result = verify_numeric_answer("1,234,000,000", expected_key=_fact_key(), facts=[fact])
    assert result.state == NumericAnswerState.VERIFIED
    assert result.emit_answer
    assert result.authority_fact_id == "fact-001"

    mismatch = verify_numeric_answer("1,234", expected_key=_fact_key(), facts=[fact])
    assert mismatch.state == NumericAnswerState.UNRESOLVED
    assert not mismatch.emit_answer
    assert mismatch.reason_codes == ("numeric_value_mismatch",)


def test_numeric_answer_fails_closed_on_missing_or_conflicting_authority() -> None:
    missing = verify_numeric_answer("100", expected_key=_fact_key(), facts=[])
    assert missing.state == NumericAnswerState.UNRESOLVED
    assert not missing.emit_answer

    facts = [
        NumericAuthorityFact(
            stable_id=f"fact-{value}",
            key=_fact_key(),
            value=Decimal(value),
            source_block_ids=(f"block-{value}",),
            source_hash="e" * 64,
            authority_type="official_api",
            verification_state=VerificationState.AUTHORITY_VERIFIED,
        )
        for value in ("100", "101")
    ]
    ambiguous = verify_numeric_answer("100000000", expected_key=_fact_key(), facts=facts)
    assert ambiguous.state == NumericAnswerState.UNRESOLVED
    assert ambiguous.reason_codes == ("authority_fact_ambiguous",)
