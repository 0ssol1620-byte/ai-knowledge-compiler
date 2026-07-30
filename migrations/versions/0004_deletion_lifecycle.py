"""Add durable tombstone, manifest, purge evidence, and deletion worker ACL.

Revision ID: 0004_deletion_lifecycle
Revises: 0003_browser_multipart
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0004_deletion_lifecycle"
down_revision = "0003_browser_multipart"
branch_labels = None
depends_on = None

DELETION_ROLE = "akc_deletion_worker"


def _columns(table: str) -> set[str]:
    return {
        str(column["name"])
        for column in inspect(op.get_bind()).get_columns(table)
    }


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _add_tombstones() -> None:
    if "deletion_requested_at" not in _columns("projects"):
        op.add_column(
            "projects",
            sa.Column(
                "deletion_requested_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
    if "deletion_requested_at" not in _columns("documents"):
        op.add_column(
            "documents",
            sa.Column(
                "deletion_requested_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
    project_indexes = {
        str(index["name"]) for index in inspect(op.get_bind()).get_indexes("projects")
    }
    if "projects_active_idx" not in project_indexes:
        op.create_index(
            "projects_active_idx",
            "projects",
            ["tenant_id", "updated_at", "id"],
            unique=False,
            postgresql_where=sa.text("deletion_requested_at IS NULL"),
            sqlite_where=sa.text("deletion_requested_at IS NULL"),
        )
    document_indexes = {
        str(index["name"]) for index in inspect(op.get_bind()).get_indexes("documents")
    }
    if "documents_active_idx" not in document_indexes:
        op.create_index(
            "documents_active_idx",
            "documents",
            ["tenant_id", "project_id", "id"],
            unique=False,
            postgresql_where=sa.text("deletion_requested_at IS NULL"),
            sqlite_where=sa.text("deletion_requested_at IS NULL"),
        )


def _create_deletion_tables() -> None:
    tables = _tables()
    if "deletion_requests" not in tables:
        op.create_table(
            "deletion_requests",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("target_type", sa.String(length=32), nullable=False),
            sa.Column("target_id", sa.Uuid(), nullable=False),
            sa.Column("target_id_hash", sa.String(length=64), nullable=False),
            sa.Column("requested_by", sa.Uuid(), nullable=True),
            sa.Column(
                "state",
                sa.String(length=24),
                nullable=False,
                server_default="requested",
            ),
            sa.Column("manifest", sa.JSON(), nullable=False),
            sa.Column("manifest_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "object_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "deleted_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error_code", sa.String(length=120), nullable=True),
            sa.Column("lease_token", sa.Uuid(), nullable=True),
            sa.Column(
                "lease_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "requested_at",
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
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "target_type IN ('document','project')",
                name="ck_deletion_requests_target_type",
            ),
            sa.CheckConstraint(
                "state IN ('requested','purging','retry','purged','dead_letter')",
                name="ck_deletion_requests_state",
            ),
            sa.CheckConstraint(
                "object_count >= 0",
                name="ck_deletion_requests_object_count",
            ),
            sa.CheckConstraint(
                "deleted_count >= 0 AND deleted_count <= object_count",
                name="ck_deletion_requests_deleted_count",
            ),
            sa.CheckConstraint(
                "attempts >= 0",
                name="ck_deletion_requests_attempts",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "id"),
            sa.UniqueConstraint(
                "tenant_id",
                "target_type",
                "target_id",
                name="uq_deletion_requests_target",
            ),
        )
        op.create_index(
            "deletion_requests_pending_idx",
            "deletion_requests",
            ["state", "lease_expires_at", "requested_at", "id"],
        )

    tables = _tables()
    if "deletion_objects" not in tables:
        op.create_table(
            "deletion_objects",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("deletion_request_id", sa.Uuid(), nullable=False),
            sa.Column(
                "operation",
                sa.String(length=24),
                nullable=False,
                server_default="delete",
            ),
            sa.Column("bucket", sa.String(length=24), nullable=False),
            sa.Column("object_key", sa.String(length=500), nullable=False),
            sa.Column("object_key_hash", sa.String(length=64), nullable=False),
            sa.Column("provider_upload_id", sa.String(length=512), nullable=True),
            sa.Column(
                "state",
                sa.String(length=16),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error_code", sa.String(length=120), nullable=True),
            sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "operation IN ('delete','abort_multipart')",
                name="ck_deletion_objects_operation",
            ),
            sa.CheckConstraint(
                "bucket IN "
                "('quarantine','source','working','derived','exports','audit')",
                name="ck_deletion_objects_bucket",
            ),
            sa.CheckConstraint(
                "state IN ('pending','purged')",
                name="ck_deletion_objects_state",
            ),
            sa.CheckConstraint(
                "attempts >= 0",
                name="ck_deletion_objects_attempts",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "deletion_request_id"],
                ["deletion_requests.tenant_id", "deletion_requests.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "id"),
            sa.UniqueConstraint(
                "deletion_request_id",
                "operation",
                "bucket",
                "object_key",
                name="uq_deletion_objects_manifest_entry",
            ),
        )
        op.create_index(
            "deletion_objects_pending_idx",
            "deletion_objects",
            ["deletion_request_id", "state", "id"],
        )

    tables = _tables()
    if "deletion_attempts" not in tables:
        op.create_table(
            "deletion_attempts",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("deletion_request_id", sa.Uuid(), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False),
            sa.Column(
                "outcome",
                sa.String(length=24),
                nullable=False,
                server_default="started",
            ),
            sa.Column(
                "failure_hashes",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("error_code", sa.String(length=120), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "attempt_number >= 1",
                name="ck_deletion_attempts_number",
            ),
            sa.CheckConstraint(
                "outcome IN ('started','retry','purged','dead_letter')",
                name="ck_deletion_attempts_outcome",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "deletion_request_id"],
                ["deletion_requests.tenant_id", "deletion_requests.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "id"),
            sa.UniqueConstraint(
                "deletion_request_id",
                "attempt_number",
                name="uq_deletion_attempt_number",
            ),
        )

    outbox_indexes = {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes("outbox_events")
    }
    if "outbox_deletion_pending_idx" not in outbox_indexes:
        op.create_index(
            "outbox_deletion_pending_idx",
            "outbox_events",
            ["available_at", "created_at", "id"],
            postgresql_where=sa.text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type IN "
                "('deletion.purge.requested.v1','deletion.retry.requested.v1')"
            ),
            sqlite_where=sa.text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type IN "
                "('deletion.purge.requested.v1','deletion.retry.requested.v1')"
            ),
        )


def _enable_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in ("deletion_requests", "deletion_objects", "deletion_attempts"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            "USING (tenant_id = "
            "NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = "
            "NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
    op.execute("REVOKE UPDATE, DELETE ON deletion_attempts FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON deletion_requests FROM PUBLIC")


def _provision_role() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'akc_deletion_worker'
            ) THEN
                CREATE ROLE akc_deletion_worker
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            ELSE
                ALTER ROLE akc_deletion_worker
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {DELETION_ROLE}")
    op.execute(
        f"""
        GRANT SELECT ON TABLE
            tenants,
            projects,
            documents,
            document_versions,
            pages,
            page_assets,
            blocks,
            block_revisions,
            upload_sessions,
            source_files,
            processing_jobs,
            job_events,
            review_items,
            knowledge_notes,
            entities,
            relations,
            exports,
            credit_accounts,
            credit_ledger,
            outbox_events,
            deletion_requests,
            deletion_objects,
            deletion_attempts,
            deletion_receipts
        TO {DELETION_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT INSERT ON TABLE
            credit_accounts,
            credit_ledger,
            job_events,
            outbox_events,
            audit_events,
            deletion_requests,
            deletion_objects,
            deletion_attempts,
            deletion_receipts
        TO {DELETION_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT DELETE ON TABLE
            projects,
            documents,
            source_files,
            upload_sessions,
            knowledge_notes
        TO {DELETION_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (deletion_requested_at, updated_at)
        ON TABLE projects TO {DELETION_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (status, deletion_requested_at, updated_at)
        ON TABLE documents TO {DELETION_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status, completed_at, event_sequence, error
        ) ON TABLE processing_jobs TO {DELETION_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            balance, reserved, version, updated_at
        ) ON TABLE credit_accounts TO {DELETION_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            available_at, published_at, dead_lettered_at, attempts, last_error
        ) ON TABLE outbox_events TO {DELETION_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            state, deleted_count, attempts, last_error_code, lease_token,
            lease_expires_at, updated_at, completed_at
        ) ON TABLE deletion_requests TO {DELETION_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (state, attempts, last_error_code, purged_at)
        ON TABLE deletion_objects TO {DELETION_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (outcome, failure_hashes, error_code, completed_at)
        ON TABLE deletion_attempts TO {DELETION_ROLE}
        """
    )


def upgrade() -> None:
    _add_tombstones()
    _create_deletion_tables()
    _enable_rls()
    _provision_role()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in (
            "deletion_attempts",
            "deletion_objects",
            "deletion_requests",
            "deletion_receipts",
            "audit_events",
            "outbox_events",
            "credit_ledger",
            "credit_accounts",
            "job_events",
            "processing_jobs",
            "knowledge_notes",
            "upload_sessions",
            "source_files",
            "documents",
            "projects",
            "exports",
            "relations",
            "entities",
            "review_items",
            "block_revisions",
            "blocks",
            "page_assets",
            "pages",
            "document_versions",
            "tenants",
        ):
            op.execute(
                f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {DELETION_ROLE}"
            )
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {DELETION_ROLE}")
        op.execute(
            f"""
            ALTER ROLE {DELETION_ROLE}
                NOBYPASSRLS NOINHERIT NOLOGIN
                NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
            """
        )
    if "outbox_deletion_pending_idx" in {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes("outbox_events")
    }:
        op.drop_index("outbox_deletion_pending_idx", table_name="outbox_events")
    for table in ("deletion_attempts", "deletion_objects", "deletion_requests"):
        if table in _tables():
            op.drop_table(table)
    for table, index in (
        ("documents", "documents_active_idx"),
        ("projects", "projects_active_idx"),
    ):
        if index in {
            str(value["name"])
            for value in inspect(op.get_bind()).get_indexes(table)
        }:
            op.drop_index(index, table_name=table)
    if "deletion_requested_at" in _columns("documents"):
        with op.batch_alter_table("documents") as batch:
            batch.drop_column("deletion_requested_at")
    if "deletion_requested_at" in _columns("projects"):
        with op.batch_alter_table("projects") as batch:
            batch.drop_column("deletion_requested_at")
