"""Tenant-bound vector shortlist and exact-attestation reranking."""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from .models import (
    EmbeddingRequest,
    EmbeddingResult,
    EvidenceHit,
    RerankRequest,
    RerankResult,
    RetrievalQuery,
    RetrievalScoreBreakdown,
    Vector,
    VectorCandidate,
    VectorRecord,
)


class RetrievalUnavailable(RuntimeError):
    """The lane is disabled or lacks verified provider evidence."""


class ProviderAttestationError(RuntimeError):
    """A provider result does not match the pinned model contract."""


def cosine_similarity(left: Vector, right: Vector) -> float:
    if len(left) != len(right):
        raise ValueError("vector dimensions do not match")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0 or right_norm <= 0:
        raise ValueError("vector norm must be positive")
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult: ...


@runtime_checkable
class RerankerProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def rerank(self, request: RerankRequest) -> RerankResult: ...


@runtime_checkable
class VectorStore(Protocol):
    async def search(self, query: RetrievalQuery) -> Sequence[VectorCandidate]: ...


class InMemoryVectorStore:
    """Deterministic test/development store; never a production persistence claim."""

    development_only = True

    def __init__(self, *, dimension: int) -> None:
        if not 32 <= dimension <= 4096:
            raise ValueError("dimension must be between 32 and 4096")
        self._dimension = dimension
        self._records: dict[tuple[uuid.UUID, str], VectorRecord] = {}

    def upsert(self, records: Iterable[VectorRecord]) -> None:
        for record in records:
            if len(record.vector) != self._dimension:
                raise ValueError("record dimension does not match the index")
            self._records[(record.tenant_id, record.stable_id)] = record

    def delete_project(self, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> int:
        keys = [
            key
            for key, record in self._records.items()
            if record.tenant_id == tenant_id and record.project_id == project_id
        ]
        for key in keys:
            del self._records[key]
        return len(keys)

    async def search(self, query: RetrievalQuery) -> Sequence[VectorCandidate]:
        if len(query.vector) != self._dimension:
            raise ValueError("query dimension does not match the index")
        allowed_projects = set(query.project_ids)
        candidates = [
            VectorCandidate(
                record=record,
                vector_score=max(-1.0, min(1.0, cosine_similarity(query.vector, record.vector))),
            )
            for record in self._records.values()
            if record.tenant_id == query.tenant_id
            and record.project_id in allowed_projects
            and record.media_kind in query.media_kinds
            and _matches_filters(record, query)
        ]
        return sorted(
            candidates,
            key=lambda candidate: (-candidate.vector_score, candidate.record.stable_id),
        )[: query.candidate_k]


def _matches_filters(record: VectorRecord, query: RetrievalQuery) -> bool:
    filters = query.filters
    metadata = record.metadata
    if filters.collection_ids and str(metadata.get("collection_id")) not in {
        str(collection_id) for collection_id in filters.collection_ids
    }:
        return False
    if filters.document_ids and str(metadata.get("document_id")) not in filters.document_ids:
        return False
    exact_fields = {
        "statement": filters.statement,
        "concept": filters.concept,
        "period_start": filters.period_start,
        "period_end": filters.period_end,
        "instant": filters.instant,
        "current_prior": filters.current_prior,
        "consolidation": filters.consolidation,
        "unit": filters.unit,
        "currency": filters.currency,
        "entity_id": filters.entity_id,
        "source_type": filters.source_type,
    }
    if any(
        expected is not None and str(metadata.get(name)) != expected
        for name, expected in exact_fields.items()
    ):
        return False
    return not filters.verification_states or str(metadata.get("verification_state")) in {
        state.value for state in filters.verification_states
    }


class RetrievalService:
    """Validates ACLs and provider attestations around vector and rerank calls."""

    def __init__(
        self,
        *,
        vector_store: VectorStore,
        reranker: RerankerProvider | None,
        expected_reranker_id: str | None,
        expected_reranker_revision: str | None,
        feature_enabled: bool,
        provider_ready: bool,
        production_mode: bool = False,
    ) -> None:
        if production_mode and bool(getattr(vector_store, "development_only", False)):
            raise RetrievalUnavailable("development-only vector store cannot serve production")
        self._vector_store = vector_store
        self._reranker = reranker
        self._expected_reranker_id = expected_reranker_id
        self._expected_reranker_revision = expected_reranker_revision
        self._feature_enabled = feature_enabled
        self._provider_ready = provider_ready

    async def search(
        self,
        query: RetrievalQuery,
        *,
        query_fingerprint: str,
    ) -> tuple[EvidenceHit, ...]:
        if not self._feature_enabled or not self._provider_ready:
            raise RetrievalUnavailable("multimodal retrieval is not enabled and verified")
        candidates = tuple(await self._vector_store.search(query))
        allowed_projects = set(query.project_ids)
        if any(
            candidate.record.tenant_id != query.tenant_id
            or candidate.record.project_id not in allowed_projects
            for candidate in candidates
        ):
            raise ProviderAttestationError("vector store returned an ACL-violating candidate")
        if len({candidate.record.stable_id for candidate in candidates}) != len(candidates):
            raise ProviderAttestationError("vector store returned duplicate candidate ids")

        ordered = list(candidates)
        rerank_scores: dict[str, float] = {}
        if self._reranker is not None and len(candidates) >= 5:
            result = await self._reranker.rerank(
                RerankRequest(
                    tenant_id=query.tenant_id,
                    query_fingerprint=query_fingerprint,
                    candidate_ids=tuple(candidate.record.stable_id for candidate in candidates),
                    candidate_scores={
                        candidate.record.stable_id: RetrievalScoreBreakdown(
                            vector_score=candidate.vector_score,
                            bm25_score=candidate.bm25_score,
                            graph_score=candidate.graph_score,
                            hybrid_score=candidate.hybrid_score,
                        )
                        for candidate in candidates
                    },
                    top_k=query.top_k,
                )
            )
            if (
                result.provider_id != self._expected_reranker_id
                or result.model_revision != self._expected_reranker_revision
            ):
                raise ProviderAttestationError("reranker identity or revision mismatch")
            expected_ids = {candidate.record.stable_id for candidate in candidates}
            ordered_ids = result.ordered_candidate_ids
            if (
                len(ordered_ids) != len(set(ordered_ids))
                or len(ordered_ids) > query.top_k
                or not set(ordered_ids).issubset(expected_ids)
                or set(result.scores) != set(ordered_ids)
            ):
                raise ProviderAttestationError("reranker result set is malformed")
            by_id = {candidate.record.stable_id: candidate for candidate in candidates}
            ordered = [by_id[stable_id] for stable_id in ordered_ids]
            rerank_scores = result.scores

        hits = [
            EvidenceHit(
                stable_id=candidate.record.stable_id,
                project_id=candidate.record.project_id,
                media_kind=candidate.record.media_kind,
                score=rerank_scores.get(
                    candidate.record.stable_id,
                    candidate.hybrid_score
                    if candidate.hybrid_score is not None
                    else candidate.vector_score,
                ),
                vector_score=candidate.vector_score,
                bm25_score=candidate.bm25_score,
                graph_score=candidate.graph_score,
                hybrid_score=candidate.hybrid_score,
                evidence_block_ids=candidate.record.evidence_block_ids,
                source_hash=candidate.record.source_hash,
                metadata=dict(candidate.record.metadata),
            )
            for candidate in ordered[: query.top_k]
        ]
        return tuple(hits)
