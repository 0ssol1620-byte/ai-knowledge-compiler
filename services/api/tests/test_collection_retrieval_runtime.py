from __future__ import annotations

import base64
import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from akc_api.collection_retrieval_runtime import (
    CollectionSemanticRetrievalRuntime,
    HttpCollectionSemanticEmbeddingProvider,
    build_collection_semantic_retrieval_runtime,
)
from akc_api.collection_semantic_runtime import (
    PreparedCollectionSemanticRuntime,
    RetrievalIndexExpectation,
)
from akc_api.database import Database
from akc_api.main import create_app
from akc_api.settings import Settings
from akc_retrieval import (
    EmbeddingRequest,
    HmacSha256RowAttestor,
    MediaKind,
    PostgresHybridIndexer,
    PostgresHybridStore,
    ProviderAttestationError,
    VerificationState,
)

TENANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
PROJECT_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
COLLECTION_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
DOCUMENT_ID = uuid.UUID("40000000-0000-0000-0000-000000000001")
BLOCK_ID = uuid.UUID("50000000-0000-0000-0000-000000000001")
MODEL_ID = "Qwen3-Embedding-0.6B"
MODEL_REVISION = "a" * 40
VECTOR = (1.0, *(0.0 for _ in range(1023)))


def _embedding_request(text: str) -> EmbeddingRequest:
    return EmbeddingRequest(
        tenant_id=TENANT_ID,
        object_key="collection-query:test",
        source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        media_kind=MediaKind.TEXT,
        instruction_profile="collection_semantic_query_v1",
    )


def _embedding_response(*, source_hash: str, revision: str = MODEL_REVISION) -> dict[str, Any]:
    return {
        "provider_id": "qwen-attested",
        "model_id": MODEL_ID,
        "model_revision": revision,
        "source_hash": source_hash,
        "vector": VECTOR,
    }


def _provider(client: httpx.AsyncClient) -> HttpCollectionSemanticEmbeddingProvider:
    return HttpCollectionSemanticEmbeddingProvider(
        endpoint_url="https://embeddings.example.test/v1/embed",
        api_key="provider-secret",
        provider_id="qwen-attested",
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        timeout_seconds=5.0,
        client=client,
    )


@pytest.mark.asyncio
async def test_http_embedding_provider_sends_exact_text_and_validates_attestation() -> None:
    text = "exact verified evidence"
    request_model = _embedding_request(text)
    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json=_embedding_response(source_hash=request_model.source_hash),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _provider(client).embed_text(request_model, text)

    assert captured["text"] == text
    assert captured["text_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert captured["source_hash"] == request_model.source_hash
    assert captured["model_id"] == MODEL_ID
    assert captured["model_revision"] == MODEL_REVISION
    assert captured["authorization"] == "Bearer provider-secret"
    assert result.vector == VECTOR


@pytest.mark.asyncio
async def test_http_embedding_provider_rejects_unpinned_revision() -> None:
    text = "verified evidence"
    request_model = _embedding_request(text)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_embedding_response(
                source_hash=request_model.source_hash,
                revision="b" * 40,
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttestationError, match="attestation"):
            await _provider(client).embed_text(request_model, text)


class MutationExecutor:
    dialect_name = "postgresql"

    async def execute_transaction(self, _mutations: Any) -> tuple[()]:
        return ()


class QueryExecutor:
    dialect_name = "postgresql"

    async def fetch_all(self, _statement: Any, _parameters: Any) -> tuple[()]:
        return ()


@pytest.mark.asyncio
async def test_runtime_batch_factory_embeds_every_exact_canonical_source() -> None:
    texts = ("First canonical note.", "Second canonical note.")
    expectations = tuple(
        RetrievalIndexExpectation(
            stable_id=f"note:test-{index}",
            document_id=DOCUMENT_ID,
            source_hash=hashlib.sha256(f"canonical-object:{text}".encode()).hexdigest(),
            evidence_block_ids=(BLOCK_ID,),
            lexical_text=text,
            verification_state=VerificationState.VERIFIED,
        )
        for index, text in enumerate(texts)
    )
    seen_texts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_texts.append(str(body["text"]))
        return httpx.Response(
            200,
            json=_embedding_response(source_hash=str(body["source_hash"])),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attestor = HmacSha256RowAttestor(b"r" * 32)
        runtime = CollectionSemanticRetrievalRuntime(
            indexer=PostgresHybridIndexer(
                executor=MutationExecutor(),
                row_attestor=attestor,
            ),
            store=PostgresHybridStore(
                executor=QueryExecutor(),
                row_attestor=attestor,
            ),
            embedding_provider=_provider(client),
            embedding_concurrency=2,
        )
        prepared = cast(
            PreparedCollectionSemanticRuntime,
            SimpleNamespace(
                compile_input=SimpleNamespace(
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    collection_id=COLLECTION_ID,
                ),
                index_expectations=expectations,
                graph_edges=(),
                canonical_model_sha256="sha256:" + "c" * 64,
            ),
        )
        batch = await runtime.build_batch(prepared)

    assert sorted(seen_texts) == sorted(texts)
    assert {item.payload.stable_id for item in batch.documents} == {
        item.stable_id for item in expectations
    }
    assert all(len(item.payload.vector) == 1024 for item in batch.documents)
    assert all(item.payload.model_revision == MODEL_REVISION for item in batch.documents)


def _enabled_settings() -> Settings:
    return Settings(
        env="test",
        database_url="postgresql+asyncpg://user:password@localhost/akc",
        collection_metadata_encryption_enabled=True,
        collection_semantic_retrieval_enabled=True,
        collection_semantic_retrieval_row_hmac_secret=(
            "base64:" + base64.b64encode(b"r" * 32).decode("ascii")
        ),
        collection_semantic_retrieval_embedding_endpoint_url=(
            "https://embeddings.example.test/v1/embed"
        ),
        collection_semantic_retrieval_embedding_api_key="provider-secret",
        collection_semantic_retrieval_embedding_provider_id="qwen-attested",
        collection_semantic_retrieval_embedding_model_id=MODEL_ID,
        collection_semantic_retrieval_embedding_model_revision=MODEL_REVISION,
    )


def test_enabled_settings_reject_sqlite_before_runtime_creation() -> None:
    with pytest.raises(ValueError, match="requires PostgreSQL"):
        Settings(
            env="test",
            database_url="sqlite+aiosqlite:///:memory:",
            collection_metadata_encryption_enabled=True,
            collection_semantic_retrieval_enabled=True,
            collection_semantic_retrieval_row_hmac_secret="r" * 32,
            collection_semantic_retrieval_embedding_endpoint_url=(
                "https://embeddings.example.test/v1/embed"
            ),
            collection_semantic_retrieval_embedding_api_key="provider-secret",
            collection_semantic_retrieval_embedding_provider_id="qwen-attested",
            collection_semantic_retrieval_embedding_model_id=MODEL_ID,
            collection_semantic_retrieval_embedding_model_revision=MODEL_REVISION,
        )


def test_enabled_settings_require_external_secret_credentials() -> None:
    with pytest.raises(ValueError, match="Secret-backed credentials"):
        Settings(
            env="test",
            database_url="postgresql+asyncpg://user:password@localhost/akc",
            collection_metadata_encryption_enabled=True,
            collection_semantic_retrieval_enabled=True,
            collection_semantic_retrieval_embedding_endpoint_url=(
                "https://embeddings.example.test/v1/embed"
            ),
            collection_semantic_retrieval_embedding_provider_id="qwen-attested",
            collection_semantic_retrieval_embedding_model_id=MODEL_ID,
            collection_semantic_retrieval_embedding_model_revision=MODEL_REVISION,
        )


def test_production_embedding_endpoint_requires_https() -> None:
    with pytest.raises(ValueError, match="credential-free HTTPS"):
        Settings(
            env="production",
            database_url="postgresql+asyncpg://user:password@localhost/akc",
            collection_finalizer_hmac_secret="f" * 32,
            collection_metadata_encryption_enabled=True,
            collection_metadata_active_key_id="metadata-test-v1",
            collection_metadata_keyring=json.dumps(
                {"metadata-test-v1": ("base64:" + base64.b64encode(b"m" * 32).decode("ascii"))}
            ),
            collection_metadata_blind_index_key_id="path-index-test-v1",
            collection_metadata_blind_index_key=(
                "base64:" + base64.b64encode(b"i" * 32).decode("ascii")
            ),
            collection_semantic_retrieval_enabled=True,
            collection_semantic_retrieval_row_hmac_secret="r" * 32,
            collection_semantic_retrieval_embedding_endpoint_url=("http://localhost:8001/v1/embed"),
            collection_semantic_retrieval_embedding_api_key="provider-secret",
            collection_semantic_retrieval_embedding_provider_id="qwen-attested",
            collection_semantic_retrieval_embedding_model_id=MODEL_ID,
            collection_semantic_retrieval_embedding_model_revision=MODEL_REVISION,
        )


@pytest.mark.asyncio
async def test_factory_constructs_concrete_postgres_runtime_without_claiming_live_health() -> None:
    settings = _enabled_settings()
    database = Database(settings)
    runtime = build_collection_semantic_retrieval_runtime(settings, database)
    assert runtime is not None
    assert isinstance(runtime.indexer, PostgresHybridIndexer)
    assert isinstance(runtime.store, PostgresHybridStore)
    assert runtime.embedding_provider.model_revision == MODEL_REVISION
    await runtime.aclose()
    await database.dispose()


@pytest.mark.asyncio
async def test_create_app_wires_enabled_runtime_without_claiming_live_health(
    tmp_path: Path,
) -> None:
    settings = _enabled_settings().model_copy(
        update={"data_dir": tmp_path / "data"},
    )
    app = create_app(settings)
    assert isinstance(app.state.collection_semantic_retrieval_indexer, PostgresHybridIndexer)
    assert isinstance(app.state.collection_semantic_retrieval_store, PostgresHybridStore)
    assert callable(app.state.collection_semantic_retrieval_batch_factory)
    provider = app.state.collection_semantic_query_embedding_provider
    assert isinstance(provider, HttpCollectionSemanticEmbeddingProvider)
    assert app.state.collection_semantic_query_embedding_model_id == MODEL_ID
    assert app.state.collection_semantic_query_embedding_model_revision == MODEL_REVISION
    await provider.aclose()
    await app.state.database.dispose()


@pytest.mark.asyncio
async def test_create_app_exposes_disabled_fail_closed_state(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            env="test",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'runtime.db').as_posix()}",
            data_dir=tmp_path / "data",
            local_background_tasks=False,
        )
    )
    async with app.router.lifespan_context(app):
        assert app.state.collection_semantic_retrieval_indexer is None
        assert app.state.collection_semantic_retrieval_batch_factory is None
        assert app.state.collection_semantic_retrieval_store is None
        assert app.state.collection_semantic_query_embedding_provider is None
        assert app.state.collection_semantic_query_embedding_model_id is None
        assert app.state.collection_semantic_query_embedding_model_revision is None
