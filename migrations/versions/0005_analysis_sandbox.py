"""Add durable sandboxed document-analysis queue and worker ACL.

Revision ID: 0005_analysis_sandbox
Revises: 0004_deletion_lifecycle
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0005_analysis_sandbox"
down_revision = "0004_deletion_lifecycle"
branch_labels = None
depends_on = None

ANALYSIS_ROLE = "akc_analysis_worker"
DELETION_ROLE = "akc_deletion_worker"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes(table)
    }


def _create_analysis_table() -> None:
    if "analysis_tasks" not in _tables():
        op.create_table(
            "analysis_tasks",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("document_id", sa.Uuid(), nullable=False),
            sa.Column("source_file_id", sa.Uuid(), nullable=False),
            sa.Column("requested_by", sa.Uuid(), nullable=False),
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
                server_default="3",
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
            sa.Column(
                "page_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "block_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "preview_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
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
                "('queued','running','completed','failed','dead_letter')",
                name="analysis_tasks_status_check",
            ),
            sa.CheckConstraint(
                "attempt_count >= 0",
                name="analysis_tasks_attempt_nonnegative",
            ),
            sa.CheckConstraint(
                "max_attempts BETWEEN 1 AND 10",
                name="analysis_tasks_max_attempts_check",
            ),
            sa.CheckConstraint(
                "attempt_count <= max_attempts",
                name="analysis_tasks_attempt_bound",
            ),
            sa.CheckConstraint(
                "page_count >= 0 AND block_count >= 0 AND preview_count >= 0",
                name="analysis_tasks_result_counts_check",
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
                ["tenant_id", "source_file_id"],
                ["source_files.tenant_id", "source_files.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["requested_by"],
                ["users.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "document_id",
                "source_file_id",
                name="uq_analysis_task_source",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "id",
                name="uq_analysis_task_tenant_id",
            ),
        )
    if "analysis_tasks_due_idx" not in _indexes("analysis_tasks"):
        op.create_index(
            "analysis_tasks_due_idx",
            "analysis_tasks",
            ["available_at", "created_at", "id"],
            unique=False,
            postgresql_where=sa.text("status IN ('queued','running')"),
            sqlite_where=sa.text("status IN ('queued','running')"),
        )
    if "outbox_analysis_pending_idx" not in _indexes("outbox_events"):
        op.create_index(
            "outbox_analysis_pending_idx",
            "outbox_events",
            ["available_at", "created_at", "id"],
            unique=False,
            postgresql_where=sa.text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type = 'document.analysis.requested.v1'"
            ),
            sqlite_where=sa.text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type = 'document.analysis.requested.v1'"
            ),
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
                WHERE schemaname = 'public' AND tablename = 'analysis_tasks'
                """
            )
        )
    }
    op.execute("ALTER TABLE analysis_tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE analysis_tasks FORCE ROW LEVEL SECURITY")
    if "analysis_tasks_tenant_isolation" not in policies:
        op.execute(
            """
            CREATE POLICY analysis_tasks_tenant_isolation ON analysis_tasks
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
                SELECT 1 FROM pg_roles WHERE rolname = '{ANALYSIS_ROLE}'
            ) THEN
                CREATE ROLE {ANALYSIS_ROLE}
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            ELSE
                ALTER ROLE {ANALYSIS_ROLE}
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ANALYSIS_ROLE}")
    op.execute(
        f"""
        GRANT SELECT ON TABLE
            analysis_tasks,
            outbox_events,
            projects,
            documents,
            source_files,
            pages,
            page_assets,
            blocks,
            review_items
        TO {ANALYSIS_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT INSERT, DELETE ON TABLE
            pages,
            page_assets,
            blocks,
            review_items
        TO {ANALYSIS_ROLE}
        """
    )
    op.execute(f"GRANT INSERT ON TABLE audit_events TO {ANALYSIS_ROLE}")
    op.execute(
        f"""
        GRANT UPDATE (
            status, attempt_count, available_at, lease_expires_at, lease_token,
            last_error_code, page_count, block_count, preview_count,
            started_at, completed_at, updated_at
        ) ON TABLE analysis_tasks TO {ANALYSIS_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            available_at, published_at, dead_lettered_at, attempts, last_error
        ) ON TABLE outbox_events TO {ANALYSIS_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (document_type, page_count, status, updated_at)
        ON TABLE documents TO {ANALYSIS_ROLE}
        """
    )
    # Deletion owns the terminal fence for any in-flight analysis task.
    op.execute(f"GRANT SELECT ON TABLE analysis_tasks TO {DELETION_ROLE}")
    op.execute(
        f"""
        GRANT UPDATE (
            status, lease_expires_at, lease_token, last_error_code,
            completed_at, updated_at
        ) ON TABLE analysis_tasks TO {DELETION_ROLE}
        """
    )


def upgrade() -> None:
    _create_analysis_table()
    _enable_rls()
    _provision_roles()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f"""
            REVOKE UPDATE (
                status, lease_expires_at, lease_token, last_error_code,
                completed_at, updated_at
            ) ON analysis_tasks FROM {DELETION_ROLE}
            """
        )
        op.execute(
            f"REVOKE ALL PRIVILEGES ON analysis_tasks FROM {DELETION_ROLE}"
        )
        for table in (
            "audit_events",
            "review_items",
            "blocks",
            "page_assets",
            "pages",
            "source_files",
            "documents",
            "projects",
            "outbox_events",
            "analysis_tasks",
        ):
            op.execute(
                f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {ANALYSIS_ROLE}"
            )
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ANALYSIS_ROLE}")
        op.execute(
            f"""
            ALTER ROLE {ANALYSIS_ROLE}
                NOBYPASSRLS NOINHERIT NOLOGIN
                NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
            """
        )
        op.execute(
            "DROP POLICY IF EXISTS analysis_tasks_tenant_isolation "
            "ON analysis_tasks"
        )
    if "outbox_analysis_pending_idx" in _indexes("outbox_events"):
        op.drop_index(
            "outbox_analysis_pending_idx",
            table_name="outbox_events",
        )
    if "analysis_tasks" in _tables():
        op.drop_table("analysis_tasks")
