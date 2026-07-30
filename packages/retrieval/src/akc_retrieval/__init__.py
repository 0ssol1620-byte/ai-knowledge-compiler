"""Tenant-safe multimodal retrieval contracts and orchestration."""

from .engine import (
    EmbeddingProvider,
    InMemoryVectorStore,
    ProviderAttestationError,
    RerankerProvider,
    RetrievalService,
    RetrievalUnavailable,
    VectorStore,
    cosine_similarity,
)
from .models import (
    EmbeddingRequest,
    EmbeddingResult,
    EvidenceHit,
    MediaKind,
    RerankRequest,
    RerankResult,
    RetrievalQuery,
    VectorCandidate,
    VectorRecord,
)

__all__ = [
    "EmbeddingProvider",
    "EmbeddingRequest",
    "EmbeddingResult",
    "EvidenceHit",
    "InMemoryVectorStore",
    "MediaKind",
    "ProviderAttestationError",
    "RerankRequest",
    "RerankResult",
    "RerankerProvider",
    "RetrievalQuery",
    "RetrievalService",
    "RetrievalUnavailable",
    "VectorCandidate",
    "VectorRecord",
    "VectorStore",
    "cosine_similarity",
]
