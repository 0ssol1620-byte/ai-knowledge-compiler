from __future__ import annotations

from pathlib import Path

MIGRATION = Path("migrations/versions/0024_production_hybrid_retrieval.py")


def test_production_retrieval_migration_is_pgvector_rls_and_filter_complete() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for required in (
        "CREATE EXTENSION IF NOT EXISTS vector",
        "embedding vector(1024)",
        "USING hnsw",
        "vector_cosine_ops",
        "knowledge_retrieval_term_frequencies",
        "knowledge_retrieval_term_stats",
        "knowledge_retrieval_corpus_stats",
        "knowledge_retrieval_edges",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "collection_id uuid NOT NULL",
        "verification_state",
        "statement",
        "concept",
        "period_start",
        "period_end",
        "current_prior",
        "consolidation",
        "unit",
        "currency",
        "entity_id",
        "source_type",
    ):
        assert required in source


def test_production_retrieval_migration_has_no_sqlite_or_in_memory_store() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'if op.get_bind().dialect.name != "postgresql"' in source
    assert "InMemoryVectorStore" not in source
    assert "sqlite" in source.casefold()
