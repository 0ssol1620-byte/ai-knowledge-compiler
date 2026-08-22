"""Production wiring for attested collection semantic retrieval."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

import httpx
from akc_retrieval import (
    PRODUCTION_EMBEDDING_DIMENSION,
    EmbeddingRequest,
    EmbeddingResult,
    HmacSha256RowAttestor,
    MediaKind,
    PostgresHybridIndexer,
    PostgresHybridStore,
    ProviderAttestationError,
    RetrievalIndexBatch,
    RetrievalUnavailable,
    SQLAlchemyPostgreSQLExecutor,
    SQLAlchemyPostgreSQLMutationExecutor,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from akc_api.collection_semantic_runtime import (
    PreparedCollectionSemanticRuntime,
    RetrievalIndexExpectation,
    build_collection_retrieval_batch,
)

if TYPE_CHECKING:
    from akc_api.database import Database
    from akc_api.settings import Settings

_MAX_EMBEDDING_RESPONSE_BYTES = 1024 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_BEARER_TOKEN = re.compile(r"^[\x21-\x7e]{1,4096}$")


@runtime_checkable
class CollectionSemanticTextEmbeddingProvider(Protocol):
    """Pinned provider contract that includes the exact text being embedded."""

    @property
    def provider_id(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    @property
    def model_revision(self) -> str: ...

    async def embed_text(
        self,
        request: EmbeddingRequest,
        text: str,
    ) -> EmbeddingResult: ...


class HttpCollectionSemanticEmbeddingProvider:
    """Strict HTTP adapter for a revision-pinned text embedding service."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        api_key: str,
        provider_id: str,
        model_id: str,
        model_revision: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not endpoint_url or _BEARER_TOKEN.fullmatch(api_key) is None:
            raise ValueError("embedding endpoint and API key are required")
        if any(_IDENTIFIER.fullmatch(value) is None for value in (provider_id, model_id)):
            raise ValueError("embedding provider and model identifiers are required")
        if re.fullmatch(r"[0-9a-f]{40,64}", model_revision) is None:
            raise ValueError("embedding model revision must be a pinned hexadecimal digest")
        self._endpoint_url = endpoint_url
        self._provider_id = provider_id
        self._model_id = model_id
        self._model_revision = model_revision
        self._authorization = f"Bearer {api_key}"
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def model_revision(self) -> str:
        return self._model_revision

    async def embed_text(
        self,
        request: EmbeddingRequest,
        text: str,
    ) -> EmbeddingResult:
        if not text.strip():
            raise ValueError("embedding text must contain non-whitespace content")
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        try:
            response = await self._client.post(
                self._endpoint_url,
                headers={"Authorization": self._authorization},
                json={
                    "tenant_id": str(request.tenant_id),
                    "object_key": request.object_key,
                    "source_hash": request.source_hash,
                    "media_kind": request.media_kind.value,
                    "instruction_profile": request.instruction_profile,
                    "text": text,
                    "text_sha256": text_sha256,
                    "model_id": self._model_id,
                    "model_revision": self._model_revision,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RetrievalUnavailable("collection embedding provider request failed") from exc
        content_type = response.headers.get("content-type", "").lower()
        if not content_type.startswith("application/json"):
            raise ProviderAttestationError("embedding provider returned a non-JSON response")
        if len(response.content) > _MAX_EMBEDDING_RESPONSE_BYTES:
            raise ProviderAttestationError("embedding provider response exceeded its bound")
        try:
            result = EmbeddingResult.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise ProviderAttestationError("embedding provider response is malformed") from exc
        _validate_embedding_attestation(
            result,
            request=request,
            provider_id=self._provider_id,
            model_id=self._model_id,
            model_revision=self._model_revision,
        )
        return result

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _validate_embedding_attestation(
    result: EmbeddingResult,
    *,
    request: EmbeddingRequest,
    provider_id: str,
    model_id: str,
    model_revision: str,
) -> None:
    if (
        result.provider_id != provider_id
        or result.model_id != model_id
        or result.model_revision != model_revision
        or result.source_hash != request.source_hash
        or len(result.vector) != PRODUCTION_EMBEDDING_DIMENSION
    ):
        raise ProviderAttestationError("embedding provider attestation is invalid")


@dataclass(frozen=True, slots=True)
class CollectionSemanticRetrievalRuntime:
    """Concrete writer, reader, and embedding dependencies for one API process."""

    indexer: PostgresHybridIndexer
    store: PostgresHybridStore
    embedding_provider: HttpCollectionSemanticEmbeddingProvider
    embedding_concurrency: int

    def __post_init__(self) -> None:
        if not 1 <= self.embedding_concurrency <= 32:
            raise ValueError("embedding concurrency must be between 1 and 32")

    async def build_batch(
        self,
        prepared: PreparedCollectionSemanticRuntime,
    ) -> RetrievalIndexBatch:
        if not 1 <= len(prepared.index_expectations) <= 1000:
            raise RetrievalUnavailable(
                "collection retrieval batch must contain between 1 and 1000 sources"
            )
        semaphore = asyncio.Semaphore(self.embedding_concurrency)

        async def embed(
            expectation: RetrievalIndexExpectation,
        ) -> tuple[str, Sequence[float]]:
            request = EmbeddingRequest(
                tenant_id=prepared.compile_input.tenant_id,
                object_key=(
                    f"collection-index:{prepared.compile_input.collection_id}:"
                    f"{expectation.stable_id}"
                ),
                source_hash=expectation.source_hash,
                media_kind=MediaKind.TEXT,
                instruction_profile="collection_semantic_index_v1",
            )
            async with semaphore:
                result = await self.embedding_provider.embed_text(
                    request,
                    expectation.lexical_text,
                )
            _validate_embedding_attestation(
                result,
                request=request,
                provider_id=self.embedding_provider.provider_id,
                model_id=self.embedding_provider.model_id,
                model_revision=self.embedding_provider.model_revision,
            )
            return expectation.stable_id, result.vector

        embedded = await asyncio.gather(*(embed(item) for item in prepared.index_expectations))
        return build_collection_retrieval_batch(
            prepared,
            embeddings=dict(embedded),
            model_id=self.embedding_provider.model_id,
            model_revision=self.embedding_provider.model_revision,
        )

    async def aclose(self) -> None:
        await self.embedding_provider.aclose()


def _decode_secret(value: str, *, field_name: str) -> bytes:
    if value.startswith("base64:"):
        try:
            decoded = base64.b64decode(value.removeprefix("base64:"), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"{field_name} is not valid base64") from exc
    else:
        decoded = value.encode("utf-8")
    if len(decoded) < 32:
        raise ValueError(f"{field_name} must contain at least 32 bytes")
    return decoded


def build_collection_semantic_retrieval_runtime(
    settings: Settings,
    database: Database,
) -> CollectionSemanticRetrievalRuntime | None:
    """Build production dependencies or fail startup when enabled configuration drifts."""

    if not settings.collection_semantic_retrieval_enabled:
        return None
    if database.engine.dialect.name != "postgresql":
        raise RetrievalUnavailable("collection semantic retrieval requires PostgreSQL")
    row_secret = settings.collection_semantic_retrieval_row_hmac_secret
    api_key = settings.collection_semantic_retrieval_embedding_api_key
    endpoint_url = settings.collection_semantic_retrieval_embedding_endpoint_url
    if row_secret is None or api_key is None or endpoint_url is None:
        raise ValueError("enabled collection semantic retrieval is incompletely configured")
    row_attestor = HmacSha256RowAttestor(
        _decode_secret(
            row_secret.get_secret_value(),
            field_name="collection retrieval row HMAC secret",
        )
    )
    sessions = cast(async_sessionmaker[AsyncSession], database.sessions)
    mutation_executor = SQLAlchemyPostgreSQLMutationExecutor(
        engine=database.engine,
        sessions=sessions,
    )
    query_executor = SQLAlchemyPostgreSQLExecutor(
        engine=database.engine,
        sessions=sessions,
    )
    provider = HttpCollectionSemanticEmbeddingProvider(
        endpoint_url=endpoint_url,
        api_key=api_key.get_secret_value(),
        provider_id=settings.collection_semantic_retrieval_embedding_provider_id,
        model_id=settings.collection_semantic_retrieval_embedding_model_id,
        model_revision=settings.collection_semantic_retrieval_embedding_model_revision,
        timeout_seconds=settings.collection_semantic_retrieval_embedding_timeout_seconds,
    )
    return CollectionSemanticRetrievalRuntime(
        indexer=PostgresHybridIndexer(
            executor=mutation_executor,
            row_attestor=row_attestor,
        ),
        store=PostgresHybridStore(
            executor=query_executor,
            row_attestor=row_attestor,
        ),
        embedding_provider=provider,
        embedding_concurrency=(settings.collection_semantic_retrieval_embedding_concurrency),
    )


__all__ = [
    "CollectionSemanticRetrievalRuntime",
    "CollectionSemanticTextEmbeddingProvider",
    "HttpCollectionSemanticEmbeddingProvider",
    "build_collection_semantic_retrieval_runtime",
]
