"""Strict wire models for multimodal embedding and reranking."""

from __future__ import annotations

import math
import uuid
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_REVISION_PATTERN = r"^[0-9a-f]{40,64}$"
_HASH_PATTERN = r"^[0-9a-f]{64}$"


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MediaKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    FORMULA = "formula"


type Vector = tuple[float, ...]


def _validated_vector(value: Vector) -> Vector:
    if not 32 <= len(value) <= 4096:
        raise ValueError("vector dimension must be between 32 and 4096")
    if any(not math.isfinite(component) for component in value):
        raise ValueError("vector components must be finite")
    norm_squared = sum(component * component for component in value)
    if norm_squared <= 0:
        raise ValueError("vector norm must be positive")
    return value


class VectorRecord(WireModel):
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    stable_id: Annotated[str, Field(min_length=1, max_length=240)]
    media_kind: MediaKind
    source_hash: Annotated[str, Field(pattern=_HASH_PATTERN)]
    evidence_block_ids: tuple[uuid.UUID, ...]
    model_id: Annotated[str, Field(min_length=1, max_length=200)]
    model_revision: Annotated[str, Field(pattern=_REVISION_PATTERN)]
    vector: Vector
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("vector")
    @classmethod
    def validate_vector(cls, value: Vector) -> Vector:
        return _validated_vector(value)

    @field_validator("evidence_block_ids")
    @classmethod
    def validate_evidence(
        cls,
        value: tuple[uuid.UUID, ...],
    ) -> tuple[uuid.UUID, ...]:
        if not value or len(value) > 100 or len(value) != len(set(value)):
            raise ValueError("evidence block ids must be unique and contain 1..100 entries")
        return value

    @field_validator("metadata")
    @classmethod
    def prevent_sensitive_metadata(
        cls,
        value: dict[str, str | int | float | bool | None],
    ) -> dict[str, str | int | float | bool | None]:
        forbidden = {"content", "text", "token", "secret", "password", "api_key", "url"}
        if any(key.casefold() in forbidden for key in value):
            raise ValueError("retrieval metadata cannot contain content or secret fields")
        return value


class RetrievalQuery(WireModel):
    tenant_id: uuid.UUID
    project_ids: tuple[uuid.UUID, ...]
    vector: Vector
    media_kinds: frozenset[MediaKind] = frozenset(MediaKind)
    candidate_k: Annotated[int, Field(ge=30, le=100)] = 50
    top_k: Annotated[int, Field(ge=5, le=15)] = 10

    @field_validator("vector")
    @classmethod
    def validate_vector(cls, value: Vector) -> Vector:
        return _validated_vector(value)

    @field_validator("project_ids")
    @classmethod
    def validate_projects(
        cls,
        value: tuple[uuid.UUID, ...],
    ) -> tuple[uuid.UUID, ...]:
        if not value or len(value) > 50 or len(value) != len(set(value)):
            raise ValueError("project ids must be unique and contain 1..50 entries")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> RetrievalQuery:
        if self.top_k > self.candidate_k:
            raise ValueError("top_k cannot exceed candidate_k")
        if not self.media_kinds:
            raise ValueError("at least one media kind is required")
        return self


class VectorCandidate(WireModel):
    record: VectorRecord
    vector_score: Annotated[float, Field(ge=-1, le=1)]


class RerankRequest(WireModel):
    tenant_id: uuid.UUID
    query_fingerprint: Annotated[str, Field(pattern=r"^h1_[0-9a-f]{64}$")]
    candidate_ids: tuple[str, ...]
    top_k: Annotated[int, Field(ge=5, le=15)]

    @field_validator("candidate_ids")
    @classmethod
    def validate_candidates(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not 5 <= len(value) <= 100 or len(value) != len(set(value)):
            raise ValueError("candidate ids must be unique and contain 5..100 entries")
        return value


class RerankResult(WireModel):
    provider_id: str
    model_revision: Annotated[str, Field(pattern=_REVISION_PATTERN)]
    ordered_candidate_ids: tuple[str, ...]
    scores: dict[str, float]

    @field_validator("scores")
    @classmethod
    def validate_scores(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(score) for score in value.values()):
            raise ValueError("reranker scores must be finite")
        return value


class EvidenceHit(WireModel):
    stable_id: str
    project_id: uuid.UUID
    media_kind: MediaKind
    score: float
    vector_score: float
    evidence_block_ids: tuple[uuid.UUID, ...]
    source_hash: str
    metadata: dict[str, Any]


class EmbeddingRequest(WireModel):
    tenant_id: uuid.UUID
    object_key: Annotated[str, Field(min_length=1, max_length=500)]
    source_hash: Annotated[str, Field(pattern=_HASH_PATTERN)]
    media_kind: MediaKind
    instruction_profile: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")]


class EmbeddingResult(WireModel):
    provider_id: str
    model_id: str
    model_revision: Annotated[str, Field(pattern=_REVISION_PATTERN)]
    source_hash: Annotated[str, Field(pattern=_HASH_PATTERN)]
    vector: Vector

    @field_validator("vector")
    @classmethod
    def validate_vector(cls, value: Vector) -> Vector:
        return _validated_vector(value)
