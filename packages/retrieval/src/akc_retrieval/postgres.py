"""Production PostgreSQL/pgvector hybrid retrieval.

The store deliberately has no development fallback.  Its SQL starts from a
materialized, tenant-bound and structurally filtered relation.  Vector, BM25,
and graph-neighbour scores are computed only from that relation, and every row
is independently checked against a keyed ingestion attestation before it can
become a retrieval candidate.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import unicodedata
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import TextClause

from .engine import ProviderAttestationError, RetrievalUnavailable, cosine_similarity
from .models import (
    MediaKind,
    RetrievalQuery,
    VectorCandidate,
    VectorRecord,
    VerificationState,
)

_HASH_PATTERN = r"^[0-9a-f]{64}$"
_REVISION_PATTERN = r"^[0-9a-f]{40,64}$"
_ATTESTATION_ALGORITHM = "hmac-sha256"
_KEY_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
PRODUCTION_EMBEDDING_DIMENSION = 1024


POSTGRES_HYBRID_SEARCH_SQL = """
WITH query_terms AS MATERIALIZED (
    SELECT DISTINCT lexeme AS term
    FROM unnest(
        tsvector_to_array(to_tsvector('simple', CAST(:lexical_query AS text)))
    ) AS query_lexemes(lexeme)
    WHERE CAST(:has_lexical_query AS boolean)
),
filtered AS MATERIALIZED (
    SELECT
        record.tenant_id,
        record.project_id,
        record.collection_id,
        record.stable_id,
        record.document_id,
        record.media_kind,
        record.source_hash,
        record.evidence_block_ids,
        record.model_id,
        record.model_revision,
        record.embedding,
        record.token_count,
        record.statement,
        record.concept,
        record.period_start,
        record.period_end,
        record.instant,
        record.current_prior,
        record.consolidation,
        record.unit,
        record.currency,
        record.entity_id,
        record.source_type,
        record.verification_state,
        record.metadata,
        record.attested_payload,
        record.row_attestation
    FROM knowledge_retrieval_records AS record
    WHERE record.tenant_id = CAST(:tenant_id AS uuid)
      AND record.project_id = ANY(CAST(:project_ids AS uuid[]))
      AND CASE WHEN CAST(:has_collection_ids AS boolean)
          THEN record.collection_id = ANY(CAST(:collection_ids AS uuid[])) ELSE TRUE END
      AND record.media_kind = ANY(CAST(:media_kinds AS text[]))
      AND record.verification_state = ANY(CAST(:verification_states AS text[]))
      AND CASE WHEN CAST(:has_document_ids AS boolean)
          THEN record.document_id::text = ANY(CAST(:document_ids AS text[])) ELSE TRUE END
      AND CASE WHEN CAST(:has_statement AS boolean)
          THEN record.statement = CAST(:statement AS text) ELSE TRUE END
      AND CASE WHEN CAST(:has_concept AS boolean)
          THEN record.concept = CAST(:concept AS text) ELSE TRUE END
      AND CASE WHEN CAST(:has_period_start AS boolean)
          THEN record.period_start = CAST(:period_start AS text) ELSE TRUE END
      AND CASE WHEN CAST(:has_period_end AS boolean)
          THEN record.period_end = CAST(:period_end AS text) ELSE TRUE END
      AND CASE WHEN CAST(:has_instant AS boolean)
          THEN record.instant = CAST(:instant AS text) ELSE TRUE END
      AND CASE WHEN CAST(:has_current_prior AS boolean)
          THEN record.current_prior = CAST(:current_prior AS text) ELSE TRUE END
      AND CASE WHEN CAST(:has_consolidation AS boolean)
          THEN record.consolidation = CAST(:consolidation AS text) ELSE TRUE END
      AND CASE WHEN CAST(:has_unit AS boolean)
          THEN record.unit = CAST(:unit AS text) ELSE TRUE END
      AND CASE WHEN CAST(:has_currency AS boolean)
          THEN record.currency = CAST(:currency AS text) ELSE TRUE END
      AND CASE WHEN CAST(:has_entity_id AS boolean)
          THEN record.entity_id = CAST(:entity_id AS text) ELSE TRUE END
      AND CASE WHEN CAST(:has_source_type AS boolean)
          THEN record.source_type = CAST(:source_type AS text) ELSE TRUE END
),
vector_candidates AS MATERIALIZED (
    SELECT
        filtered.project_id,
        filtered.stable_id,
        greatest(
            -1.0,
            least(1.0, 1.0 - (filtered.embedding <=> CAST(:query_vector AS vector)))
        )::double precision AS raw_vector_score
    FROM filtered
    ORDER BY
        filtered.embedding <=> CAST(:query_vector AS vector),
        filtered.project_id,
        filtered.stable_id
    LIMIT CAST(:candidate_k AS integer)
),
bm25_candidates AS MATERIALIZED (
    SELECT
        filtered.project_id,
        filtered.stable_id,
        sum(
            ln(
                1.0 + (
                    corpus.document_count - term_stats.document_frequency + 0.5
                ) / (term_stats.document_frequency + 0.5)
            ) * (
                frequencies.term_frequency * (CAST(:bm25_k1 AS double precision) + 1.0)
            ) / nullif(
                frequencies.term_frequency
                + CAST(:bm25_k1 AS double precision) * (
                    1.0 - CAST(:bm25_b AS double precision)
                    + CAST(:bm25_b AS double precision) * filtered.token_count
                      / nullif(corpus.average_token_count, 0.0)
                ),
                0.0
            )
        )::double precision AS raw_bm25_score
    FROM filtered
    JOIN knowledge_retrieval_term_frequencies AS frequencies
      ON frequencies.tenant_id = filtered.tenant_id
     AND frequencies.project_id = filtered.project_id
     AND frequencies.stable_id = filtered.stable_id
    JOIN query_terms ON query_terms.term = frequencies.term
    JOIN knowledge_retrieval_term_stats AS term_stats
      ON term_stats.tenant_id = filtered.tenant_id
     AND term_stats.term = frequencies.term
    JOIN knowledge_retrieval_corpus_stats AS corpus
      ON corpus.tenant_id = filtered.tenant_id
    GROUP BY filtered.project_id, filtered.stable_id
    ORDER BY raw_bm25_score DESC, filtered.project_id, filtered.stable_id
    LIMIT CAST(:candidate_k AS integer)
),
graph_neighbours AS MATERIALIZED (
    SELECT edge.project_id, edge.to_stable_id AS stable_id, edge.edge_weight
    FROM knowledge_retrieval_edges AS edge
    WHERE CAST(:has_graph_seeds AS boolean)
      AND edge.tenant_id = CAST(:tenant_id AS uuid)
      AND edge.project_id = ANY(CAST(:project_ids AS uuid[]))
      AND edge.from_stable_id = ANY(CAST(:graph_seed_ids AS text[]))
    UNION ALL
    SELECT edge.project_id, edge.from_stable_id AS stable_id, edge.edge_weight
    FROM knowledge_retrieval_edges AS edge
    WHERE CAST(:has_graph_seeds AS boolean)
      AND edge.tenant_id = CAST(:tenant_id AS uuid)
      AND edge.project_id = ANY(CAST(:project_ids AS uuid[]))
      AND edge.to_stable_id = ANY(CAST(:graph_seed_ids AS text[]))
),
graph_candidates AS MATERIALIZED (
    SELECT
        filtered.project_id,
        filtered.stable_id,
        sum(graph_neighbours.edge_weight)::double precision AS raw_graph_score
    FROM filtered
    JOIN graph_neighbours
      ON graph_neighbours.project_id = filtered.project_id
     AND graph_neighbours.stable_id = filtered.stable_id
    GROUP BY filtered.project_id, filtered.stable_id
    ORDER BY raw_graph_score DESC, filtered.project_id, filtered.stable_id
    LIMIT CAST(:candidate_k AS integer)
),
candidate_pool AS MATERIALIZED (
    SELECT project_id, stable_id FROM vector_candidates
    UNION
    SELECT project_id, stable_id FROM bm25_candidates
    UNION
    SELECT project_id, stable_id FROM graph_candidates
),
normalised AS (
    SELECT
        filtered.*,
        greatest(
            -1.0,
            least(1.0, 1.0 - (filtered.embedding <=> CAST(:query_vector AS vector)))
        )::double precision AS vector_score,
        CASE WHEN coalesce(max(bm25_candidates.raw_bm25_score) OVER (), 0.0) > 0.0
          THEN coalesce(bm25_candidates.raw_bm25_score, 0.0)
             / max(bm25_candidates.raw_bm25_score) OVER ()
          ELSE 0.0 END AS bm25_score,
        CASE WHEN coalesce(max(graph_candidates.raw_graph_score) OVER (), 0.0) > 0.0
          THEN coalesce(graph_candidates.raw_graph_score, 0.0)
             / max(graph_candidates.raw_graph_score) OVER ()
          ELSE 0.0 END AS graph_score
    FROM candidate_pool
    JOIN filtered
      ON filtered.project_id = candidate_pool.project_id
     AND filtered.stable_id = candidate_pool.stable_id
    LEFT JOIN bm25_candidates
      ON bm25_candidates.project_id = candidate_pool.project_id
     AND bm25_candidates.stable_id = candidate_pool.stable_id
    LEFT JOIN graph_candidates
      ON graph_candidates.project_id = candidate_pool.project_id
     AND graph_candidates.stable_id = candidate_pool.stable_id
),
ranked AS (
    SELECT
        normalised.*,
        greatest(
            0.0,
            least(
                1.0,
                CAST(:vector_weight AS double precision) * ((normalised.vector_score + 1.0) / 2.0)
                + CAST(:bm25_weight AS double precision) * normalised.bm25_score
                + CAST(:graph_weight AS double precision) * normalised.graph_score
            )
        )::double precision AS hybrid_score
    FROM normalised
)
SELECT
    ranked.tenant_id,
    ranked.project_id,
    ranked.collection_id,
    ranked.stable_id,
    ranked.document_id,
    ranked.media_kind,
    ranked.source_hash,
    ranked.evidence_block_ids,
    ranked.model_id,
    ranked.model_revision,
    ranked.embedding::text AS embedding_text,
    ranked.statement,
    ranked.concept,
    ranked.period_start,
    ranked.period_end,
    ranked.instant,
    ranked.current_prior,
    ranked.consolidation,
    ranked.unit,
    ranked.currency,
    ranked.entity_id,
    ranked.source_type,
    ranked.verification_state,
    ranked.metadata,
    ranked.attested_payload,
    ranked.row_attestation,
    ranked.vector_score,
    ranked.bm25_score,
    ranked.graph_score,
    ranked.hybrid_score
FROM ranked
ORDER BY ranked.hybrid_score DESC, ranked.project_id, ranked.stable_id
LIMIT CAST(:candidate_k AS integer)
""".strip()

POSTGRES_HYBRID_SEARCH_STATEMENT = text(POSTGRES_HYBRID_SEARCH_SQL)


class RetrievalRowAttestationError(ProviderAttestationError):
    """A persisted retrieval row is malformed, altered, or outside the query scope."""


class AttestedRetrievalPayload(BaseModel):
    """Canonical immutable values covered by an ingestion-time row attestation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["akc.retrieval.row.v1"] = "akc.retrieval.row.v1"
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    collection_id: uuid.UUID
    stable_id: Annotated[str, Field(min_length=1, max_length=240)]
    document_id: uuid.UUID
    media_kind: MediaKind
    source_hash: Annotated[str, Field(pattern=_HASH_PATTERN)]
    evidence_block_ids: tuple[uuid.UUID, ...]
    model_id: Annotated[str, Field(min_length=1, max_length=200)]
    model_revision: Annotated[str, Field(pattern=_REVISION_PATTERN)]
    vector: tuple[float, ...]
    statement: str | None = None
    concept: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    instant: str | None = None
    current_prior: str | None = None
    consolidation: str | None = None
    unit: str | None = None
    currency: str | None = None
    entity_id: str | None = None
    source_type: str | None = None
    verification_state: VerificationState
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("evidence_block_ids")
    @classmethod
    def validate_evidence_ids(
        cls,
        value: tuple[uuid.UUID, ...],
    ) -> tuple[uuid.UUID, ...]:
        if not value or len(value) > 100 or len(value) != len(set(value)):
            raise ValueError("evidence block ids must be unique and contain 1..100 entries")
        return value

    @field_validator("vector")
    @classmethod
    def validate_vector(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if len(value) != PRODUCTION_EMBEDDING_DIMENSION:
            raise ValueError(
                f"production retrieval vector dimension must be {PRODUCTION_EMBEDDING_DIMENSION}"
            )
        if any(not math.isfinite(component) for component in value):
            raise ValueError("vector components must be finite")
        if sum(component * component for component in value) <= 0:
            raise ValueError("vector norm must be positive")
        return value

    def as_vector_record(self) -> VectorRecord:
        metadata = dict(self.metadata)
        structured = {
            "collection_id": str(self.collection_id),
            "document_id": str(self.document_id),
            "statement": self.statement,
            "concept": self.concept,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "instant": self.instant,
            "current_prior": self.current_prior,
            "consolidation": self.consolidation,
            "unit": self.unit,
            "currency": self.currency,
            "entity_id": self.entity_id,
            "source_type": self.source_type,
            "verification_state": self.verification_state.value,
        }
        for key, value in structured.items():
            if value is None:
                continue
            if key in metadata and str(metadata[key]) != str(value):
                raise RetrievalRowAttestationError(
                    f"attested metadata conflicts with structured field {key}"
                )
            metadata[key] = value
        return VectorRecord(
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            stable_id=self.stable_id,
            media_kind=self.media_kind,
            source_hash=self.source_hash,
            evidence_block_ids=self.evidence_block_ids,
            model_id=self.model_id,
            model_revision=self.model_revision,
            vector=self.vector,
            metadata=metadata,
        )


class RetrievalIndexDocument(BaseModel):
    """Transient indexing input; lexical source text is never persisted verbatim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payload: AttestedRetrievalPayload
    lexical_text: Annotated[str, Field(min_length=1, max_length=2_000_000)]


class RetrievalIndexEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: uuid.UUID
    from_stable_id: Annotated[str, Field(min_length=1, max_length=240)]
    to_stable_id: Annotated[str, Field(min_length=1, max_length=240)]
    edge_weight: Annotated[float, Field(gt=0, le=1)]

    @model_validator(mode="after")
    def reject_self_edge(self) -> RetrievalIndexEdge:
        if self.from_stable_id == self.to_stable_id:
            raise ValueError("retrieval graph edges cannot be self-referential")
        return self


class RetrievalIndexBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: uuid.UUID
    documents: Annotated[tuple[RetrievalIndexDocument, ...], Field(min_length=1, max_length=1000)]
    edges: Annotated[tuple[RetrievalIndexEdge, ...], Field(max_length=10_000)] = ()

    @model_validator(mode="after")
    def validate_scope_and_identity(self) -> RetrievalIndexBatch:
        stable_keys = [
            (document.payload.project_id, document.payload.stable_id) for document in self.documents
        ]
        if len(stable_keys) != len(set(stable_keys)):
            raise ValueError("retrieval index documents must have unique stable ids")
        if any(document.payload.tenant_id != self.tenant_id for document in self.documents):
            raise ValueError("retrieval index documents must share the batch tenant")
        project_ids = {document.payload.project_id for document in self.documents}
        if any(edge.project_id not in project_ids for edge in self.edges):
            raise ValueError("retrieval edges must belong to an indexed project scope")
        edge_keys = [
            (edge.project_id, edge.from_stable_id, edge.to_stable_id) for edge in self.edges
        ]
        if len(edge_keys) != len(set(edge_keys)):
            raise ValueError("retrieval graph edges must be unique")
        return self


class RetrievalIndexReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: uuid.UUID
    indexed_records: Annotated[int, Field(ge=1, le=1000)]
    indexed_terms: Annotated[int, Field(ge=1)]
    indexed_edges: Annotated[int, Field(ge=0, le=10_000)]
    batch_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    raw_text_persisted: Literal[False] = False


@dataclass(frozen=True, slots=True)
class PostgreSQLMutation:
    statement: TextClause
    parameters: Mapping[str, Any]
    requires_returned_row: bool = False


@runtime_checkable
class PostgreSQLMutationExecutor(Protocol):
    @property
    def dialect_name(self) -> str: ...

    async def execute_transaction(
        self,
        mutations: Sequence[PostgreSQLMutation],
    ) -> Sequence[str | None]: ...


class SQLAlchemyPostgreSQLMutationExecutor:
    """Execute a complete index batch in one application-owned transaction."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        if engine.dialect.name != "postgresql":
            raise RetrievalUnavailable("hybrid retrieval indexing requires PostgreSQL")
        self._sessions = sessions

    @property
    def dialect_name(self) -> str:
        return "postgresql"

    async def execute_transaction(
        self,
        mutations: Sequence[PostgreSQLMutation],
    ) -> Sequence[str | None]:
        returned: list[str | None] = []
        async with self._sessions() as session, session.begin():
            for mutation in mutations:
                result = await session.execute(
                    mutation.statement,
                    dict(mutation.parameters),
                )
                returned.append(
                    cast(str | None, result.scalar_one_or_none())
                    if mutation.requires_returned_row
                    else None
                )
        return tuple(returned)


_UPSERT_RETRIEVAL_RECORD = text(
    """
    INSERT INTO knowledge_retrieval_records (
        tenant_id, project_id, collection_id, stable_id, document_id,
        media_kind, source_hash, evidence_block_ids, model_id, model_revision,
        embedding, token_count, statement, concept, period_start, period_end,
        instant, current_prior, consolidation, unit, currency, entity_id,
        source_type, verification_state, metadata, attested_payload, row_attestation
    ) VALUES (
        CAST(:tenant_id AS uuid), CAST(:project_id AS uuid), CAST(:collection_id AS uuid),
        CAST(:stable_id AS text), CAST(:document_id AS uuid), CAST(:media_kind AS text),
        CAST(:source_hash AS text), CAST(:evidence_block_ids AS uuid[]),
        CAST(:model_id AS text), CAST(:model_revision AS text),
        CAST(:embedding AS vector), CAST(:token_count AS integer),
        CAST(:statement AS text), CAST(:concept AS text), CAST(:period_start AS text),
        CAST(:period_end AS text), CAST(:instant AS text), CAST(:current_prior AS text),
        CAST(:consolidation AS text), CAST(:unit AS text), CAST(:currency AS text),
        CAST(:entity_id AS text), CAST(:source_type AS text),
        CAST(:verification_state AS text), CAST(:metadata AS jsonb),
        CAST(:attested_payload AS jsonb), CAST(:row_attestation AS text)
    )
    ON CONFLICT (tenant_id, stable_id) DO UPDATE SET
        collection_id = EXCLUDED.collection_id,
        document_id = EXCLUDED.document_id,
        media_kind = EXCLUDED.media_kind,
        source_hash = EXCLUDED.source_hash,
        evidence_block_ids = EXCLUDED.evidence_block_ids,
        model_id = EXCLUDED.model_id,
        model_revision = EXCLUDED.model_revision,
        embedding = EXCLUDED.embedding,
        token_count = EXCLUDED.token_count,
        statement = EXCLUDED.statement,
        concept = EXCLUDED.concept,
        period_start = EXCLUDED.period_start,
        period_end = EXCLUDED.period_end,
        instant = EXCLUDED.instant,
        current_prior = EXCLUDED.current_prior,
        consolidation = EXCLUDED.consolidation,
        unit = EXCLUDED.unit,
        currency = EXCLUDED.currency,
        entity_id = EXCLUDED.entity_id,
        source_type = EXCLUDED.source_type,
        verification_state = EXCLUDED.verification_state,
        metadata = EXCLUDED.metadata,
        attested_payload = EXCLUDED.attested_payload,
        row_attestation = EXCLUDED.row_attestation,
        updated_at = now()
    WHERE knowledge_retrieval_records.project_id = EXCLUDED.project_id
    RETURNING stable_id
    """
)
_LOCK_TENANT_INDEX = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(CAST(:tenant_id AS text), 0))"
)
_DELETE_RECORD_TERMS = text(
    """
    DELETE FROM knowledge_retrieval_term_frequencies
    WHERE tenant_id = CAST(:tenant_id AS uuid)
      AND project_id = CAST(:project_id AS uuid)
      AND stable_id = CAST(:stable_id AS text)
    """
)
_INSERT_RECORD_TERMS = text(
    """
    INSERT INTO knowledge_retrieval_term_frequencies (
        tenant_id, project_id, stable_id, term, term_frequency
    )
    SELECT
        CAST(:tenant_id AS uuid), CAST(:project_id AS uuid), CAST(:stable_id AS text),
        input.term, input.term_frequency
    FROM unnest(
        CAST(:terms AS text[]), CAST(:term_frequencies AS integer[])
    ) AS input(term, term_frequency)
    """
)
_UPSERT_RETRIEVAL_EDGE = text(
    """
    INSERT INTO knowledge_retrieval_edges (
        tenant_id, project_id, from_stable_id, to_stable_id, edge_weight
    ) VALUES (
        CAST(:tenant_id AS uuid), CAST(:project_id AS uuid),
        CAST(:from_stable_id AS text), CAST(:to_stable_id AS text),
        CAST(:edge_weight AS double precision)
    )
    ON CONFLICT (tenant_id, project_id, from_stable_id, to_stable_id)
    DO UPDATE SET edge_weight = EXCLUDED.edge_weight
    RETURNING from_stable_id
    """
)
_DELETE_TERM_STATS = text(
    "DELETE FROM knowledge_retrieval_term_stats WHERE tenant_id = CAST(:tenant_id AS uuid)"
)
_REBUILD_TERM_STATS = text(
    """
    INSERT INTO knowledge_retrieval_term_stats (tenant_id, term, document_frequency)
    SELECT tenant_id, term, count(*)
    FROM knowledge_retrieval_term_frequencies
    WHERE tenant_id = CAST(:tenant_id AS uuid)
    GROUP BY tenant_id, term
    """
)
_UPSERT_CORPUS_STATS = text(
    """
    INSERT INTO knowledge_retrieval_corpus_stats (
        tenant_id, document_count, average_token_count, updated_at
    )
    SELECT tenant_id, count(*), avg(token_count), now()
    FROM knowledge_retrieval_records
    WHERE tenant_id = CAST(:tenant_id AS uuid)
    GROUP BY tenant_id
    ON CONFLICT (tenant_id) DO UPDATE SET
        document_count = EXCLUDED.document_count,
        average_token_count = EXCLUDED.average_token_count,
        updated_at = EXCLUDED.updated_at
    RETURNING tenant_id::text
    """
)


def _lexical_frequencies(value: str) -> Counter[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    terms = re.findall(r"[\w]{1,200}", normalized, flags=re.UNICODE)
    if not terms:
        raise ValueError("retrieval lexical text contains no indexable terms")
    frequencies: Counter[str] = Counter(terms)
    if len(frequencies) > 20_000:
        raise ValueError("retrieval lexical text exceeds the unique-term boundary")
    return frequencies


def _index_batch_digest(batch: RetrievalIndexBatch) -> str:
    material = {
        "tenant_id": str(batch.tenant_id),
        "documents": [
            {
                "payload": document.payload.model_dump(mode="json"),
                "lexical_sha256": hashlib.sha256(document.lexical_text.encode("utf-8")).hexdigest(),
            }
            for document in batch.documents
        ],
        "edges": [edge.model_dump(mode="json") for edge in batch.edges],
    }
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def build_index_mutations(
    batch: RetrievalIndexBatch,
    row_attestor: HmacSha256RowAttestor,
) -> tuple[tuple[PostgreSQLMutation, ...], int]:
    mutations: list[PostgreSQLMutation] = [
        PostgreSQLMutation(
            statement=_LOCK_TENANT_INDEX,
            parameters={"tenant_id": str(batch.tenant_id)},
        )
    ]
    indexed_terms = 0
    for document in batch.documents:
        payload = document.payload
        frequencies = _lexical_frequencies(document.lexical_text)
        indexed_terms += len(frequencies)
        dumped = payload.model_dump(mode="json")
        mutations.append(
            PostgreSQLMutation(
                statement=_UPSERT_RETRIEVAL_RECORD,
                parameters={
                    **dumped,
                    "evidence_block_ids": [str(item) for item in payload.evidence_block_ids],
                    "embedding": json.dumps(list(payload.vector), separators=(",", ":")),
                    "token_count": sum(frequencies.values()),
                    "metadata": json.dumps(payload.metadata, separators=(",", ":")),
                    "attested_payload": canonical_attestation_payload(payload).decode("utf-8"),
                    "row_attestation": row_attestor.sign(payload),
                },
                requires_returned_row=True,
            )
        )
        scope = {
            "tenant_id": str(batch.tenant_id),
            "project_id": str(payload.project_id),
            "stable_id": payload.stable_id,
        }
        mutations.append(PostgreSQLMutation(statement=_DELETE_RECORD_TERMS, parameters=scope))
        ordered_terms = sorted(frequencies)
        mutations.append(
            PostgreSQLMutation(
                statement=_INSERT_RECORD_TERMS,
                parameters={
                    **scope,
                    "terms": ordered_terms,
                    "term_frequencies": [frequencies[term] for term in ordered_terms],
                },
            )
        )
    for edge in batch.edges:
        mutations.append(
            PostgreSQLMutation(
                statement=_UPSERT_RETRIEVAL_EDGE,
                parameters={
                    "tenant_id": str(batch.tenant_id),
                    **edge.model_dump(mode="json"),
                },
                requires_returned_row=True,
            )
        )
    tenant = {"tenant_id": str(batch.tenant_id)}
    mutations.extend(
        (
            PostgreSQLMutation(statement=_DELETE_TERM_STATS, parameters=tenant),
            PostgreSQLMutation(statement=_REBUILD_TERM_STATS, parameters=tenant),
            PostgreSQLMutation(
                statement=_UPSERT_CORPUS_STATS,
                parameters=tenant,
                requires_returned_row=True,
            ),
        )
    )
    return tuple(mutations), indexed_terms


class PostgresHybridIndexer:
    """Atomic production writer paired with :class:`PostgresHybridStore`."""

    def __init__(
        self,
        *,
        executor: PostgreSQLMutationExecutor,
        row_attestor: HmacSha256RowAttestor,
    ) -> None:
        if executor.dialect_name != "postgresql":
            raise RetrievalUnavailable("hybrid retrieval indexing requires PostgreSQL")
        self._executor = executor
        self._row_attestor = row_attestor

    async def index(self, batch: RetrievalIndexBatch) -> RetrievalIndexReceipt:
        mutations, indexed_terms = build_index_mutations(batch, self._row_attestor)
        try:
            results = await self._executor.execute_transaction(mutations)
        except Exception as exc:
            raise RetrievalUnavailable("PostgreSQL hybrid indexing failed closed") from exc
        if len(results) != len(mutations):
            raise RetrievalUnavailable("PostgreSQL hybrid indexing returned an invalid receipt")
        for mutation, result in zip(mutations, results, strict=True):
            if mutation.requires_returned_row and result is None:
                raise RetrievalRowAttestationError(
                    "retrieval indexing rejected a scope collision or missing aggregate"
                )
        return RetrievalIndexReceipt(
            tenant_id=batch.tenant_id,
            indexed_records=len(batch.documents),
            indexed_terms=indexed_terms,
            indexed_edges=len(batch.edges),
            batch_sha256=_index_batch_digest(batch),
        )


def canonical_attestation_payload(payload: AttestedRetrievalPayload) -> bytes:
    """Return the only byte representation accepted for row signatures."""

    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class HmacSha256RowAttestor:
    """Signs and verifies retrieval rows with a rotatable server-side key."""

    def __init__(
        self,
        key: bytes,
        *,
        key_id: str = "primary",
        verification_keys: Mapping[str, bytes] | None = None,
    ) -> None:
        if len(key) < 32:
            raise ValueError("retrieval row attestation key must contain at least 32 bytes")
        if _KEY_ID.fullmatch(key_id) is None:
            raise ValueError("retrieval row attestation key id is invalid")
        keys = dict(verification_keys or {})
        keys[key_id] = key
        if any(_KEY_ID.fullmatch(candidate) is None for candidate in keys):
            raise ValueError("retrieval row attestation key id is invalid")
        if any(len(candidate) < 32 for candidate in keys.values()):
            raise ValueError("retrieval row attestation key must contain at least 32 bytes")
        self._key_id = key_id
        self._keys = keys

    def sign(self, payload: AttestedRetrievalPayload) -> str:
        digest = hmac.new(
            self._keys[self._key_id],
            canonical_attestation_payload(payload),
            hashlib.sha256,
        ).hexdigest()
        return f"{_ATTESTATION_ALGORITHM}:{self._key_id}:{digest}"

    def verify(self, payload: AttestedRetrievalPayload, attestation: str) -> bool:
        parts = attestation.split(":")
        if len(parts) != 3 or parts[0] != _ATTESTATION_ALGORITHM:
            return False
        _, key_id, supplied = parts
        if len(supplied) != 64:
            return False
        key = self._keys.get(key_id)
        if key is None:
            return False
        expected = hmac.new(
            key,
            canonical_attestation_payload(payload),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(supplied, expected)


@dataclass(frozen=True, slots=True)
class HybridWeights:
    vector: float = 0.55
    bm25: float = 0.30
    graph: float = 0.15

    def __post_init__(self) -> None:
        values = (self.vector, self.bm25, self.graph)
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("hybrid weights must be finite and non-negative")
        if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("hybrid weights must sum to one")


DEFAULT_HYBRID_WEIGHTS = HybridWeights()


@runtime_checkable
class PostgreSQLExecutor(Protocol):
    """Narrow read contract so transactions stay owned by the host service."""

    @property
    def dialect_name(self) -> str: ...

    async def fetch_all(
        self,
        statement: TextClause,
        parameters: Mapping[str, Any],
    ) -> Sequence[Mapping[str, Any]]: ...


class SQLAlchemyPostgreSQLExecutor:
    """Production executor for an application-owned SQLAlchemy session factory."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        if engine.dialect.name != "postgresql":
            raise RetrievalUnavailable("hybrid retrieval requires PostgreSQL")
        self._sessions = sessions

    @property
    def dialect_name(self) -> str:
        return "postgresql"

    async def fetch_all(
        self,
        statement: TextClause,
        parameters: Mapping[str, Any],
    ) -> Sequence[Mapping[str, Any]]:
        async with self._sessions() as session:
            result = await session.execute(statement, dict(parameters))
            return tuple(cast(Mapping[str, Any], row) for row in result.mappings().all())


class PostgresHybridStore:
    """Fail-closed pgvector/BM25/graph store suitable for production use."""

    development_only = False

    def __init__(
        self,
        *,
        executor: PostgreSQLExecutor,
        row_attestor: HmacSha256RowAttestor,
        dimension: int = PRODUCTION_EMBEDDING_DIMENSION,
        weights: HybridWeights = DEFAULT_HYBRID_WEIGHTS,
        bm25_k1: float = 1.2,
        bm25_b: float = 0.75,
    ) -> None:
        if executor.dialect_name != "postgresql":
            raise RetrievalUnavailable("hybrid retrieval requires PostgreSQL")
        if dimension != PRODUCTION_EMBEDDING_DIMENSION:
            raise ValueError(
                f"production pgvector dimension must be {PRODUCTION_EMBEDDING_DIMENSION}"
            )
        if not math.isfinite(bm25_k1) or bm25_k1 <= 0:
            raise ValueError("BM25 k1 must be positive and finite")
        if not math.isfinite(bm25_b) or not 0 <= bm25_b <= 1:
            raise ValueError("BM25 b must be finite and between zero and one")
        self._executor = executor
        self._row_attestor = row_attestor
        self._dimension = dimension
        self._weights = weights
        self._bm25_k1 = bm25_k1
        self._bm25_b = bm25_b

    async def search(self, query: RetrievalQuery) -> Sequence[VectorCandidate]:
        if len(query.vector) != self._dimension:
            raise ValueError("query dimension does not match the pgvector index")
        parameters = _query_parameters(
            query,
            weights=self._weights,
            bm25_k1=self._bm25_k1,
            bm25_b=self._bm25_b,
        )
        try:
            rows = await self._executor.fetch_all(
                POSTGRES_HYBRID_SEARCH_STATEMENT,
                parameters,
            )
        except RetrievalRowAttestationError:
            raise
        except Exception as exc:
            raise RetrievalUnavailable("PostgreSQL hybrid retrieval failed closed") from exc

        if len(rows) > query.candidate_k:
            raise RetrievalRowAttestationError("PostgreSQL exceeded the bounded candidate window")

        candidates: list[VectorCandidate] = []
        seen: set[str] = set()
        for row in rows:
            candidate = self._validated_candidate(row, query)
            if candidate.record.stable_id in seen:
                raise RetrievalRowAttestationError("PostgreSQL returned duplicate stable ids")
            seen.add(candidate.record.stable_id)
            candidates.append(candidate)
        return tuple(candidates)

    def _validated_candidate(
        self,
        row: Mapping[str, Any],
        query: RetrievalQuery,
    ) -> VectorCandidate:
        try:
            raw_payload = row["attested_payload"]
            if isinstance(raw_payload, str):
                raw_payload = json.loads(raw_payload)
            payload = AttestedRetrievalPayload.model_validate(raw_payload)
            attestation = str(row["row_attestation"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RetrievalRowAttestationError("malformed retrieval row attestation") from exc
        if not self._row_attestor.verify(payload, attestation):
            raise RetrievalRowAttestationError("retrieval row attestation mismatch")
        if len(payload.vector) != self._dimension:
            raise RetrievalRowAttestationError("attested embedding dimension mismatch")
        _validate_row_matches_payload(row, payload)
        _validate_payload_matches_query(payload, query)

        try:
            vector_score = _bounded_score(row["vector_score"], lower=-1.0, upper=1.0)
            bm25_score = _bounded_score(row["bm25_score"], lower=0.0, upper=1.0)
            graph_score = _bounded_score(row["graph_score"], lower=0.0, upper=1.0)
            hybrid_score = _bounded_score(row["hybrid_score"], lower=0.0, upper=1.0)
        except (KeyError, TypeError, ValueError) as exc:
            raise RetrievalRowAttestationError("invalid hybrid score attestation") from exc
        expected_vector_score = cosine_similarity(query.vector, payload.vector)
        if not math.isclose(vector_score, expected_vector_score, rel_tol=0.0, abs_tol=1e-6):
            raise RetrievalRowAttestationError("vector score differs from the attested embedding")
        expected_hybrid_score = (
            self._weights.vector * ((vector_score + 1.0) / 2.0)
            + self._weights.bm25 * bm25_score
            + self._weights.graph * graph_score
        )
        if not math.isclose(hybrid_score, expected_hybrid_score, rel_tol=0.0, abs_tol=1e-9):
            raise RetrievalRowAttestationError("hybrid score differs from component scores")
        return VectorCandidate(
            record=payload.as_vector_record(),
            vector_score=vector_score,
            bm25_score=bm25_score,
            graph_score=graph_score,
            hybrid_score=hybrid_score,
        )


def _query_parameters(
    query: RetrievalQuery,
    *,
    weights: HybridWeights,
    bm25_k1: float,
    bm25_b: float,
) -> dict[str, Any]:
    filters = query.filters
    verification_states = filters.verification_states or frozenset(VerificationState)
    exact = {
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
    parameters: dict[str, Any] = {
        "tenant_id": str(query.tenant_id),
        "project_ids": [str(project_id) for project_id in query.project_ids],
        "collection_ids": sorted(str(item) for item in filters.collection_ids),
        "has_collection_ids": bool(filters.collection_ids),
        "media_kinds": sorted(media_kind.value for media_kind in query.media_kinds),
        "verification_states": sorted(state.value for state in verification_states),
        "document_ids": sorted(filters.document_ids),
        "has_document_ids": bool(filters.document_ids),
        "lexical_query": query.lexical_query,
        "has_lexical_query": bool(query.lexical_query.strip()),
        "graph_seed_ids": list(query.graph_seed_ids),
        "has_graph_seeds": bool(query.graph_seed_ids),
        "query_vector": "[" + ",".join(format(value, ".17g") for value in query.vector) + "]",
        "candidate_k": query.candidate_k,
        "bm25_k1": bm25_k1,
        "bm25_b": bm25_b,
        "vector_weight": weights.vector,
        "bm25_weight": weights.bm25,
        "graph_weight": weights.graph,
    }
    for name, value in exact.items():
        parameters[name] = value
        parameters[f"has_{name}"] = value is not None
    return parameters


def _validate_row_matches_payload(
    row: Mapping[str, Any],
    payload: AttestedRetrievalPayload,
) -> None:
    expected: dict[str, Any] = {
        "tenant_id": payload.tenant_id,
        "project_id": payload.project_id,
        "collection_id": payload.collection_id,
        "stable_id": payload.stable_id,
        "document_id": payload.document_id,
        "media_kind": payload.media_kind.value,
        "source_hash": payload.source_hash,
        "evidence_block_ids": payload.evidence_block_ids,
        "model_id": payload.model_id,
        "model_revision": payload.model_revision,
        "statement": payload.statement,
        "concept": payload.concept,
        "period_start": payload.period_start,
        "period_end": payload.period_end,
        "instant": payload.instant,
        "current_prior": payload.current_prior,
        "consolidation": payload.consolidation,
        "unit": payload.unit,
        "currency": payload.currency,
        "entity_id": payload.entity_id,
        "source_type": payload.source_type,
        "verification_state": payload.verification_state.value,
        "metadata": payload.metadata,
    }
    for name, value in expected.items():
        if name not in row or _normalise_db_value(row[name]) != _normalise_db_value(value):
            raise RetrievalRowAttestationError(f"retrieval row differs from attested {name}")
    embedding = _parse_embedding(row.get("embedding_text"))
    if embedding != payload.vector:
        raise RetrievalRowAttestationError("retrieval embedding differs from attested vector")


def _validate_payload_matches_query(
    payload: AttestedRetrievalPayload,
    query: RetrievalQuery,
) -> None:
    if payload.tenant_id != query.tenant_id or payload.project_id not in query.project_ids:
        raise RetrievalRowAttestationError("retrieval row violates tenant or project scope")
    if payload.media_kind not in query.media_kinds:
        raise RetrievalRowAttestationError("retrieval row violates media scope")
    filters = query.filters
    if filters.collection_ids and payload.collection_id not in filters.collection_ids:
        raise RetrievalRowAttestationError("retrieval row violates collection scope")
    if filters.document_ids and str(payload.document_id) not in filters.document_ids:
        raise RetrievalRowAttestationError("retrieval row violates document scope")
    exact = {
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
    for name, expected in exact.items():
        if expected is not None and getattr(payload, name) != expected:
            raise RetrievalRowAttestationError(f"retrieval row violates {name} filter")
    allowed_states = filters.verification_states or frozenset(VerificationState)
    if payload.verification_state not in allowed_states:
        raise RetrievalRowAttestationError("retrieval row violates verification filter")


def _normalise_db_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _normalise_db_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_normalise_db_value(item) for item in value)
    if isinstance(value, VerificationState | MediaKind):
        return value.value
    return value


def _parse_embedding(value: Any) -> tuple[float, ...]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RetrievalRowAttestationError("invalid pgvector text representation") from exc
    else:
        parsed = value
    if not isinstance(parsed, Sequence) or isinstance(parsed, (str, bytes, bytearray)):
        raise RetrievalRowAttestationError("invalid pgvector row value")
    try:
        vector = tuple(float(item) for item in parsed)
    except (TypeError, ValueError) as exc:
        raise RetrievalRowAttestationError("invalid pgvector row value") from exc
    if any(not math.isfinite(item) for item in vector):
        raise RetrievalRowAttestationError("pgvector row contains non-finite values")
    return vector


def _bounded_score(value: Any, *, lower: float, upper: float) -> float:
    score = float(value)
    if not math.isfinite(score) or not lower <= score <= upper:
        raise ValueError("score is outside its attested bounds")
    return score
