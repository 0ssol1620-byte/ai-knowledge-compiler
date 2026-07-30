"""Add encrypted durable URL-ingestion tasks and restricted worker ACL.

Revision ID: 0010_durable_url_ingestion
Revises: 0009_payment_credit_purchase
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0010_durable_url_ingestion"
down_revision = "0009_payment_credit_purchase"
branch_labels = None
depends_on = None

URL_FETCHER_ROLE = "akc_url_fetcher"
DELETION_ROLE = "akc_deletion_worker"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {str(index["name"]) for index in inspect(op.get_bind()).get_indexes(table)}


def _create_url_fetch_tasks() -> None:
    if "url_fetch_tasks" not in _tables():
        op.create_table(
            "url_fetch_tasks",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("document_id", sa.Uuid(), nullable=False),
            sa.Column("requested_by", sa.Uuid(), nullable=False),
            sa.Column("encrypted_url", sa.LargeBinary(), nullable=False),
            sa.Column("canonical_url", sa.String(length=2048), nullable=False),
            sa.Column("query_hmac", sa.String(length=64)),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="queued",
            ),
            sa.Column(
                "attempt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "max_attempts",
                sa.Integer(),
                nullable=False,
                server_default="5",
            ),
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
            sa.Column("lease_token", sa.Uuid()),
            sa.Column("last_error_code", sa.String(length=80)),
            sa.Column("content_type", sa.String(length=160)),
            sa.Column("size_bytes", sa.Integer()),
            sa.Column("source_sha256", sa.String(length=64)),
            sa.Column("source_file_id", sa.Uuid()),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("cancelled_at", sa.DateTime(timezone=True)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.CheckConstraint(
                "status IN "
                "('queued','running','retry','completed','failed',"
                "'dead_letter','cancelled')",
                name="url_fetch_tasks_status_check",
            ),
            sa.CheckConstraint(
                "attempt_count >= 0",
                name="url_fetch_tasks_attempt_nonnegative",
            ),
            sa.CheckConstraint(
                "max_attempts BETWEEN 1 AND 10",
                name="url_fetch_tasks_max_attempts_check",
            ),
            sa.CheckConstraint(
                "attempt_count <= max_attempts",
                name="url_fetch_tasks_attempt_bound",
            ),
            sa.CheckConstraint(
                "size_bytes IS NULL OR size_bytes >= 0",
                name="url_fetch_tasks_size_nonnegative",
            ),
            sa.CheckConstraint(
                "query_hmac IS NULL OR length(query_hmac) = 64",
                name="url_fetch_tasks_query_hmac_shape",
            ),
            sa.CheckConstraint(
                "source_sha256 IS NULL OR length(source_sha256) = 64",
                name="url_fetch_tasks_source_sha_shape",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "project_id"],
                ["projects.tenant_id", "projects.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "document_id"],
                ["documents.tenant_id", "documents.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["requested_by"],
                ["users.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "source_file_id"],
                ["source_files.tenant_id", "source_files.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "id",
                name="uq_url_fetch_tasks_tenant_id",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "document_id",
                name="uq_url_fetch_tasks_document",
            ),
        )
    indexes = _indexes("url_fetch_tasks")
    if "url_fetch_tasks_due_idx" not in indexes:
        op.create_index(
            "url_fetch_tasks_due_idx",
            "url_fetch_tasks",
            ["available_at", "created_at", "id"],
            postgresql_where=sa.text("status IN ('queued','retry','running')"),
            sqlite_where=sa.text("status IN ('queued','retry','running')"),
        )
    if "url_fetch_tasks_tenant_created_idx" not in indexes:
        op.create_index(
            "url_fetch_tasks_tenant_created_idx",
            "url_fetch_tasks",
            ["tenant_id", "created_at", "id"],
        )


def _enable_rls() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    policies = {
        str(row[0])
        for row in bind.execute(
            sa.text(
                """
                SELECT policyname
                FROM pg_policies
                WHERE schemaname = 'public' AND tablename = 'url_fetch_tasks'
                """
            )
        )
    }
    op.execute("ALTER TABLE url_fetch_tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE url_fetch_tasks FORCE ROW LEVEL SECURITY")
    if "url_fetch_tasks_tenant_isolation" not in policies:
        op.execute(
            """
            CREATE POLICY url_fetch_tasks_tenant_isolation ON url_fetch_tasks
            USING (
                tenant_id =
                NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            WITH CHECK (
                tenant_id =
                NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            """
        )


def _provision_roles() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{URL_FETCHER_ROLE}'
            ) THEN
                CREATE ROLE {URL_FETCHER_ROLE}
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            ELSE
                ALTER ROLE {URL_FETCHER_ROLE}
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {URL_FETCHER_ROLE}")
    op.execute(
        f"""
        GRANT SELECT ON TABLE
            url_fetch_tasks,
            projects,
            documents,
            source_files,
            upload_sessions,
            document_versions
        TO {URL_FETCHER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT INSERT ON TABLE
            source_files,
            upload_sessions,
            document_versions
        TO {URL_FETCHER_ROLE}
        """
    )
    op.execute(f"GRANT INSERT ON TABLE audit_events TO {URL_FETCHER_ROLE}")
    op.execute(
        f"""
        GRANT UPDATE (
            status, attempt_count, available_at, lease_expires_at, lease_token,
            last_error_code, content_type, size_bytes, source_sha256,
            source_file_id, started_at, completed_at, cancelled_at, updated_at
        ) ON TABLE url_fetch_tasks TO {URL_FETCHER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (source_file_id, document_type, status, updated_at)
        ON TABLE documents TO {URL_FETCHER_ROLE}
        """
    )
    op.execute(f"GRANT SELECT ON TABLE url_fetch_tasks TO {DELETION_ROLE}")
    op.execute(
        f"""
        GRANT UPDATE (
            status, available_at, lease_expires_at, lease_token,
            last_error_code, completed_at, cancelled_at, updated_at
        ) ON TABLE url_fetch_tasks TO {DELETION_ROLE}
        """
    )


def upgrade() -> None:
    _create_url_fetch_tasks()
    _enable_rls()
    _provision_roles()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f"""
            REVOKE UPDATE (
                status, available_at, lease_expires_at, lease_token,
                last_error_code, completed_at, cancelled_at, updated_at
            ) ON url_fetch_tasks FROM {DELETION_ROLE}
            """
        )
        op.execute(
            f"REVOKE ALL PRIVILEGES ON url_fetch_tasks FROM {DELETION_ROLE}"
        )
        for table in (
            "audit_events",
            "document_versions",
            "upload_sessions",
            "source_files",
            "documents",
            "projects",
            "url_fetch_tasks",
        ):
            op.execute(
                f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {URL_FETCHER_ROLE}"
            )
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {URL_FETCHER_ROLE}")
        op.execute(
            f"""
            ALTER ROLE {URL_FETCHER_ROLE}
                NOBYPASSRLS NOINHERIT NOLOGIN
                NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
            """
        )
        op.execute(
            "DROP POLICY IF EXISTS url_fetch_tasks_tenant_isolation "
            "ON url_fetch_tasks"
        )
    if "url_fetch_tasks" in _tables():
        op.drop_table("url_fetch_tasks")
