"""Add durable, attested serverless GPU invocation state.

Revision ID: 0011_durable_gpu_provider_jobs
Revises: 0010_durable_url_ingestion
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0011_durable_gpu_provider_jobs"
down_revision = "0010_durable_url_ingestion"
branch_labels = None
depends_on = None

GPU_WORKER_ROLE = "akc_gpu_worker"
DELETION_ROLE = "akc_deletion_worker"
DISPATCH_ROLE = "akc_dispatch_worker"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {str(index["name"]) for index in inspect(op.get_bind()).get_indexes(table)}


def _create_invocations() -> None:
    if "gpu_provider_invocations" not in _tables():
        op.create_table(
            "gpu_provider_invocations",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("job_id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("document_id", sa.Uuid(), nullable=False),
            sa.Column("document_version_id", sa.String(length=160), nullable=False),
            sa.Column("page_id", sa.Uuid()),
            sa.Column("provider", sa.String(length=40), nullable=False, server_default="runpod"),
            sa.Column("provider_key", sa.String(length=80), nullable=False),
            sa.Column("endpoint_id", sa.String(length=80), nullable=False),
            sa.Column("idempotency_key", sa.String(length=160), nullable=False),
            sa.Column("request_manifest_sha256", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
            sa.Column("input_bucket", sa.String(length=16), nullable=False),
            sa.Column("input_object_key", sa.String(length=500), nullable=False),
            sa.Column("input_sha256", sa.String(length=64), nullable=False),
            sa.Column("output_object_key", sa.String(length=500), nullable=False),
            sa.Column("options", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("model_revision", sa.String(length=64), nullable=False),
            sa.Column("runtime_image_digest", sa.String(length=71), nullable=False),
            sa.Column("adapter_version", sa.String(length=160), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "cancel_attempt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
            sa.Column("lease_token", sa.Uuid()),
            sa.Column("provider_job_id", sa.String(length=160)),
            sa.Column("provider_status", sa.String(length=32)),
            sa.Column("provider_callback_id", sa.String(length=160)),
            sa.Column("provider_callback_sha256", sa.String(length=64)),
            sa.Column("provider_deadline_at", sa.DateTime(timezone=True)),
            sa.Column("object_grant_expires_at", sa.DateTime(timezone=True)),
            sa.Column("cancellation_reason", sa.String(length=40)),
            sa.Column("last_error_code", sa.String(length=120)),
            sa.Column("result_manifest", sa.JSON()),
            sa.Column("result_manifest_sha256", sa.String(length=64)),
            sa.Column("completion_source", sa.String(length=16)),
            sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0"),
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
                "status IN ("
                "'queued','submitting','submitted','running','retry',"
                "'cancel_requested','cancelling','completed','failed',"
                "'dead_letter','cancelled')",
                name="gpu_provider_invocations_status_check",
            ),
            sa.CheckConstraint(
                "input_bucket IN ('source','derived')",
                name="gpu_provider_invocations_input_bucket_check",
            ),
            sa.CheckConstraint(
                "length(input_sha256) = 64",
                name="gpu_provider_invocations_input_sha_check",
            ),
            sa.CheckConstraint(
                "length(request_manifest_sha256) = 64",
                name="gpu_provider_invocations_request_sha_check",
            ),
            sa.CheckConstraint(
                "length(model_revision) BETWEEN 40 AND 64",
                name="gpu_provider_invocations_model_revision_check",
            ),
            sa.CheckConstraint(
                "length(runtime_image_digest) = 71",
                name="gpu_provider_invocations_image_digest_check",
            ),
            sa.CheckConstraint(
                "attempt_count >= 0",
                name="gpu_provider_invocations_attempt_nonnegative",
            ),
            sa.CheckConstraint(
                "cancel_attempt_count >= 0",
                name="gpu_provider_invocations_cancel_attempt_nonnegative",
            ),
            sa.CheckConstraint(
                "max_attempts BETWEEN 1 AND 10",
                name="gpu_provider_invocations_max_attempts_check",
            ),
            sa.CheckConstraint(
                "attempt_count <= max_attempts",
                name="gpu_provider_invocations_attempt_bound",
            ),
            sa.CheckConstraint(
                "event_sequence >= 0",
                name="gpu_provider_invocations_event_sequence_check",
            ),
            sa.CheckConstraint(
                "result_manifest_sha256 IS NULL OR length(result_manifest_sha256) = 64",
                name="gpu_provider_invocations_result_sha_check",
            ),
            sa.CheckConstraint(
                "provider_callback_sha256 IS NULL OR length(provider_callback_sha256) = 64",
                name="gpu_provider_invocations_callback_sha_check",
            ),
            sa.CheckConstraint(
                "completion_source IS NULL OR completion_source IN ('poll','callback')",
                name="gpu_provider_invocations_completion_source_check",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "job_id"],
                ["processing_jobs.tenant_id", "processing_jobs.id"],
                ondelete="CASCADE",
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
                ["tenant_id", "page_id"],
                ["pages.tenant_id", "pages.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "id", name="uq_gpu_provider_invocations_tenant_id"),
            sa.UniqueConstraint(
                "tenant_id",
                "idempotency_key",
                name="uq_gpu_provider_invocations_idempotency",
            ),
            sa.UniqueConstraint(
                "provider",
                "provider_callback_id",
                name="uq_gpu_provider_invocations_callback",
            ),
        )
    indexes = _indexes("gpu_provider_invocations")
    if "gpu_provider_invocations_due_idx" not in indexes:
        op.create_index(
            "gpu_provider_invocations_due_idx",
            "gpu_provider_invocations",
            ["available_at", "created_at", "id"],
            postgresql_where=sa.text(
                "status IN ("
                "'queued','submitting','submitted','running','retry',"
                "'cancel_requested','cancelling')"
            ),
            sqlite_where=sa.text(
                "status IN ("
                "'queued','submitting','submitted','running','retry',"
                "'cancel_requested','cancelling')"
            ),
        )
    if "gpu_provider_invocations_job_idx" not in indexes:
        op.create_index(
            "gpu_provider_invocations_job_idx",
            "gpu_provider_invocations",
            ["tenant_id", "job_id", "created_at"],
        )


def _create_attempts() -> None:
    if "gpu_provider_attempts" not in _tables():
        op.create_table(
            "gpu_provider_attempts",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("invocation_id", sa.Uuid(), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=24),
                nullable=False,
                server_default="submitting",
            ),
            sa.Column("request_manifest_sha256", sa.String(length=64), nullable=False),
            sa.Column("provider_job_id", sa.String(length=160)),
            sa.Column("provider_response_sha256", sa.String(length=71)),
            sa.Column("result_manifest_sha256", sa.String(length=64)),
            sa.Column("error_code", sa.String(length=120)),
            sa.Column("retryable", sa.Boolean()),
            sa.Column("submitted_at", sa.DateTime(timezone=True)),
            sa.Column("last_polled_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.CheckConstraint(
                "attempt_number BETWEEN 1 AND 10",
                name="gpu_provider_attempts_number_check",
            ),
            sa.CheckConstraint(
                "status IN ("
                "'submitting','submitted','running','retry','completed',"
                "'failed','cancelled','timed_out')",
                name="gpu_provider_attempts_status_check",
            ),
            sa.CheckConstraint(
                "length(request_manifest_sha256) = 64",
                name="gpu_provider_attempts_request_sha_check",
            ),
            sa.CheckConstraint(
                "provider_response_sha256 IS NULL OR length(provider_response_sha256) = 71",
                name="gpu_provider_attempts_response_sha_check",
            ),
            sa.CheckConstraint(
                "result_manifest_sha256 IS NULL OR length(result_manifest_sha256) = 64",
                name="gpu_provider_attempts_result_sha_check",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "invocation_id"],
                ["gpu_provider_invocations.tenant_id", "gpu_provider_invocations.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "id", name="uq_gpu_provider_attempts_tenant_id"),
            sa.UniqueConstraint(
                "invocation_id",
                "attempt_number",
                name="uq_gpu_provider_attempt_number",
            ),
        )
    if "gpu_provider_attempts_invocation_idx" not in _indexes("gpu_provider_attempts"):
        op.create_index(
            "gpu_provider_attempts_invocation_idx",
            "gpu_provider_attempts",
            ["invocation_id", "attempt_number"],
        )


def _create_events() -> None:
    if "gpu_invocation_events" not in _tables():
        op.create_table(
            "gpu_invocation_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("invocation_id", sa.Uuid(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=100), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column(
                "occurred_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.CheckConstraint("sequence >= 1", name="gpu_invocation_events_sequence_check"),
            sa.ForeignKeyConstraint(
                ["tenant_id", "invocation_id"],
                ["gpu_provider_invocations.tenant_id", "gpu_provider_invocations.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "id", name="uq_gpu_invocation_events_tenant_id"),
            sa.UniqueConstraint(
                "invocation_id",
                "sequence",
                name="uq_gpu_invocation_event_sequence",
            ),
        )
    if "gpu_invocation_events_stream_idx" not in _indexes("gpu_invocation_events"):
        op.create_index(
            "gpu_invocation_events_stream_idx",
            "gpu_invocation_events",
            ["invocation_id", "sequence"],
        )


def _enable_rls() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in (
        "gpu_provider_invocations",
        "gpu_provider_attempts",
        "gpu_invocation_events",
    ):
        policies = {
            str(row[0])
            for row in bind.execute(
                sa.text(
                    """
                    SELECT policyname
                    FROM pg_policies
                    WHERE schemaname = 'public' AND tablename = :table
                    """
                ),
                {"table": table},
            )
        }
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        policy = f"{table}_tenant_isolation"
        if policy not in policies:
            op.execute(
                f"""
                CREATE POLICY {policy} ON {table}
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
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'akc_gpu_worker'
            ) THEN
                CREATE ROLE akc_gpu_worker
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            ELSE
                ALTER ROLE akc_gpu_worker
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {GPU_WORKER_ROLE}")
    op.execute(
        f"""
        GRANT SELECT ON TABLE
            gpu_provider_invocations,
            gpu_provider_attempts,
            gpu_invocation_events,
            processing_jobs,
            projects,
            documents
        TO {GPU_WORKER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT INSERT ON TABLE
            gpu_provider_attempts,
            gpu_invocation_events,
            outbox_events
        TO {GPU_WORKER_ROLE}
        """
    )
    op.execute(f"GRANT SELECT ON TABLE outbox_events TO {GPU_WORKER_ROLE}")
    op.execute(
        f"""
        GRANT SELECT, INSERT ON TABLE
            gpu_provider_invocations,
            gpu_invocation_events,
            relations
        TO {DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status, attempt_count, cancel_attempt_count, available_at,
            lease_expires_at, lease_token,
            provider_job_id, provider_status, provider_deadline_at,
            object_grant_expires_at,
            provider_callback_id, provider_callback_sha256,
            cancellation_reason, last_error_code, result_manifest,
            result_manifest_sha256, completion_source, event_sequence,
            started_at, completed_at,
            updated_at
        ) ON TABLE gpu_provider_invocations TO {GPU_WORKER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status, provider_job_id, provider_response_sha256,
            result_manifest_sha256, error_code, retryable, submitted_at,
            last_polled_at, completed_at
        ) ON TABLE gpu_provider_attempts TO {GPU_WORKER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT SELECT ON TABLE gpu_provider_invocations TO {DELETION_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status, available_at, lease_expires_at, lease_token,
            cancellation_reason, last_error_code, completed_at, updated_at
        ) ON TABLE gpu_provider_invocations TO {DELETION_ROLE}
        """
    )


def upgrade() -> None:
    _create_invocations()
    _create_attempts()
    _create_events()
    _enable_rls()
    _provision_roles()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"REVOKE ALL PRIVILEGES ON gpu_provider_invocations FROM {DELETION_ROLE}")
        for table in (
            "relations",
            "gpu_invocation_events",
            "gpu_provider_invocations",
        ):
            op.execute(f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {DISPATCH_ROLE}")
        for table in (
            "outbox_events",
            "processing_jobs",
            "projects",
            "documents",
            "gpu_invocation_events",
            "gpu_provider_attempts",
            "gpu_provider_invocations",
        ):
            op.execute(f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {GPU_WORKER_ROLE}")
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {GPU_WORKER_ROLE}")
        op.execute(
            f"""
            ALTER ROLE {GPU_WORKER_ROLE}
                NOBYPASSRLS NOINHERIT NOLOGIN
                NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
            """
        )
        for table in (
            "gpu_invocation_events",
            "gpu_provider_attempts",
            "gpu_provider_invocations",
        ):
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    for table in (
        "gpu_invocation_events",
        "gpu_provider_attempts",
        "gpu_provider_invocations",
    ):
        if table in _tables():
            op.drop_table(table)
