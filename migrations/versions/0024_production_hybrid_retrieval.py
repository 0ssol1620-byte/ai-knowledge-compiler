"""Add the production PostgreSQL hybrid retrieval store.

Revision ID: 0024_production_hybrid_retrieval
Revises: 0023_v4_collections
Create Date: 2026-07-31

The application intentionally has no SQLite or in-memory production fallback.
Non-PostgreSQL migrations are a no-op so local contract suites can still walk
the full Alembic chain; production startup refuses a development-only store.
"""

from __future__ import annotations

from alembic import op

revision = "0024_production_hybrid_retrieval"
down_revision = "0023_v4_collections"
branch_labels = None
depends_on = None

_TABLES = (
    "knowledge_retrieval_records",
    "knowledge_retrieval_term_frequencies",
    "knowledge_retrieval_term_stats",
    "knowledge_retrieval_corpus_stats",
    "knowledge_retrieval_edges",
)


def _tenant_setting() -> str:
    return "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _user_setting() -> str:
    return "NULLIF(current_setting('app.user_id', true), '')::uuid"


def _tenant_role(*roles: str) -> str:
    values = ", ".join(f"'{role}'" for role in roles)
    return (
        "EXISTS ("  # noqa: S608 - migration-owned role literals only
        "SELECT 1 FROM memberships retrieval_tenant_membership "
        f"WHERE retrieval_tenant_membership.tenant_id = {_tenant_setting()} "
        f"AND retrieval_tenant_membership.user_id = {_user_setting()} "
        f"AND retrieval_tenant_membership.role IN ({values})"
        ")"
    )


def _project_access(project_expression: str, *, write: bool) -> str:
    roles = ("editor",) if write else ("editor", "reviewer", "viewer")
    role_values = ", ".join(f"'{role}'" for role in roles)
    explicit = (
        "EXISTS ("  # noqa: S608 - fixed migration identifiers and role literals only
        "SELECT 1 FROM project_memberships retrieval_project_membership "
        "JOIN memberships retrieval_access_membership "
        "ON retrieval_access_membership.tenant_id = "
        "retrieval_project_membership.tenant_id "
        "AND retrieval_access_membership.user_id = "
        "retrieval_project_membership.user_id "
        "WHERE retrieval_project_membership.tenant_id = "
        f"{_tenant_setting()} "
        "AND retrieval_project_membership.user_id = "
        f"{_user_setting()} "
        "AND retrieval_project_membership.project_id = "
        f"{project_expression} "
        f"AND retrieval_access_membership.role IN ({role_values}) "
        f"AND retrieval_project_membership.role IN ({role_values})"
        ")"
    )
    return f"({_tenant_role('owner', 'admin')} OR {explicit})"


def _create_tables() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE knowledge_retrieval_records (
            tenant_id uuid NOT NULL,
            project_id uuid NOT NULL,
            collection_id uuid NOT NULL,
            stable_id text NOT NULL,
            document_id uuid NOT NULL,
            media_kind text NOT NULL
                CHECK (media_kind IN ('text','image','table','formula')),
            source_hash character(64) NOT NULL
                CHECK (source_hash ~ '^[0-9a-f]{64}$'),
            evidence_block_ids uuid[] NOT NULL
                CHECK (cardinality(evidence_block_ids) BETWEEN 1 AND 100),
            model_id text NOT NULL,
            model_revision character varying(64) NOT NULL
                CHECK (model_revision ~ '^[0-9a-f]{40,64}$'),
            embedding vector(1024) NOT NULL,
            token_count integer NOT NULL CHECK (token_count > 0),
            statement text,
            concept text,
            period_start text,
            period_end text,
            instant text,
            current_prior text,
            consolidation text,
            unit text,
            currency text,
            entity_id text,
            source_type text,
            verification_state text NOT NULL CHECK (
                verification_state IN (
                    'verified','authority_verified','auto_repaired',
                    'verified_with_warning'
                )
            ),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            attested_payload jsonb NOT NULL,
            row_attestation character varying(128) NOT NULL CHECK (
                row_attestation ~ '^hmac-sha256:[A-Za-z0-9_-]{1,32}:[0-9a-f]{64}$'
            ),
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, stable_id),
            CONSTRAINT uq_retrieval_record_project_stable
                UNIQUE (tenant_id, project_id, stable_id),
            CONSTRAINT fk_retrieval_record_project FOREIGN KEY (tenant_id, project_id)
                REFERENCES projects (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_retrieval_record_collection FOREIGN KEY (tenant_id, collection_id)
                REFERENCES collections (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_retrieval_record_document FOREIGN KEY (tenant_id, document_id)
                REFERENCES documents (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT ck_retrieval_period CHECK (
                (instant IS NULL AND period_start IS NULL AND period_end IS NULL)
                OR (instant IS NOT NULL AND period_start IS NULL AND period_end IS NULL)
                OR (instant IS NULL AND period_start IS NOT NULL AND period_end IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE knowledge_retrieval_term_frequencies (
            tenant_id uuid NOT NULL,
            project_id uuid NOT NULL,
            stable_id text NOT NULL,
            term text NOT NULL CHECK (length(term) BETWEEN 1 AND 200),
            term_frequency integer NOT NULL CHECK (term_frequency > 0),
            PRIMARY KEY (tenant_id, project_id, stable_id, term),
            CONSTRAINT fk_retrieval_term_record
                FOREIGN KEY (tenant_id, project_id, stable_id)
                REFERENCES knowledge_retrieval_records (tenant_id, project_id, stable_id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE knowledge_retrieval_term_stats (
            tenant_id uuid NOT NULL,
            term text NOT NULL CHECK (length(term) BETWEEN 1 AND 200),
            document_frequency bigint NOT NULL CHECK (document_frequency > 0),
            PRIMARY KEY (tenant_id, term),
            CONSTRAINT fk_retrieval_term_stats_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE knowledge_retrieval_corpus_stats (
            tenant_id uuid PRIMARY KEY,
            document_count bigint NOT NULL CHECK (document_count > 0),
            average_token_count double precision NOT NULL CHECK (average_token_count > 0),
            updated_at timestamp with time zone NOT NULL DEFAULT now(),
            CONSTRAINT fk_retrieval_corpus_stats_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE knowledge_retrieval_edges (
            tenant_id uuid NOT NULL,
            project_id uuid NOT NULL,
            from_stable_id text NOT NULL,
            to_stable_id text NOT NULL,
            edge_weight double precision NOT NULL CHECK (edge_weight BETWEEN 0 AND 1),
            PRIMARY KEY (tenant_id, project_id, from_stable_id, to_stable_id),
            CONSTRAINT ck_retrieval_edge_not_self CHECK (from_stable_id <> to_stable_id),
            CONSTRAINT fk_retrieval_edge_from
                FOREIGN KEY (tenant_id, project_id, from_stable_id)
                REFERENCES knowledge_retrieval_records (tenant_id, project_id, stable_id)
                ON DELETE CASCADE,
            CONSTRAINT fk_retrieval_edge_to
                FOREIGN KEY (tenant_id, project_id, to_stable_id)
                REFERENCES knowledge_retrieval_records (tenant_id, project_id, stable_id)
                ON DELETE CASCADE
        )
        """
    )


def _create_indexes() -> None:
    statements = (
        "CREATE INDEX retrieval_records_embedding_hnsw_idx ON "
        "knowledge_retrieval_records USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)",
        "CREATE INDEX retrieval_records_document_idx ON knowledge_retrieval_records "
        "(tenant_id, project_id, collection_id, document_id)",
        "CREATE INDEX retrieval_records_concept_idx ON knowledge_retrieval_records "
        "(tenant_id, project_id, statement, concept)",
        "CREATE INDEX retrieval_records_period_idx ON knowledge_retrieval_records "
        "(tenant_id, project_id, period_start, period_end, instant)",
        "CREATE INDEX retrieval_records_entity_state_idx ON knowledge_retrieval_records "
        "(tenant_id, project_id, entity_id, verification_state)",
        "CREATE INDEX retrieval_records_context_idx ON knowledge_retrieval_records "
        "(tenant_id, project_id, current_prior, consolidation, unit, currency, source_type)",
        "CREATE INDEX retrieval_terms_lookup_idx ON knowledge_retrieval_term_frequencies "
        "(tenant_id, term, project_id, stable_id)",
        "CREATE INDEX retrieval_edges_from_idx ON knowledge_retrieval_edges "
        "(tenant_id, project_id, from_stable_id)",
        "CREATE INDEX retrieval_edges_to_idx ON knowledge_retrieval_edges "
        "(tenant_id, project_id, to_stable_id)",
    )
    for statement in statements:
        op.execute(statement)


def _enable_rls() -> None:
    for table in _TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        for operation in ("select", "insert", "update", "delete"):
            op.execute(
                f'DROP POLICY IF EXISTS "{table}_tenant_{operation}" ON "{table}"'
            )
        tenant = f'"{table}".tenant_id = {_tenant_setting()}'
        if table in {
            "knowledge_retrieval_records",
            "knowledge_retrieval_term_frequencies",
            "knowledge_retrieval_edges",
        }:
            project = f'"{table}".project_id'
            read = _project_access(project, write=False)
            write = _project_access(project, write=True)
        else:
            read = _tenant_role("owner", "admin", "editor", "reviewer", "viewer")
            write = _tenant_role("owner", "admin", "editor")
        op.execute(
            f'CREATE POLICY "{table}_tenant_select" ON "{table}" '
            f"AS RESTRICTIVE FOR SELECT USING ({tenant} AND {read})"
        )
        op.execute(
            f'CREATE POLICY "{table}_tenant_insert" ON "{table}" '
            f"AS RESTRICTIVE FOR INSERT WITH CHECK ({tenant} AND {write})"
        )
        op.execute(
            f'CREATE POLICY "{table}_tenant_update" ON "{table}" '
            f"AS RESTRICTIVE FOR UPDATE USING ({tenant} AND {write}) "
            f"WITH CHECK ({tenant} AND {write})"
        )
        op.execute(
            f'CREATE POLICY "{table}_tenant_delete" ON "{table}" '
            f"AS RESTRICTIVE FOR DELETE USING ({tenant} AND {write})"
        )
        op.execute(f'REVOKE ALL ON TABLE "{table}" FROM PUBLIC')


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _create_tables()
    _create_indexes()
    _enable_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in reversed(_TABLES):
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
