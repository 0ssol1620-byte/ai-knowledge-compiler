"""Add verified-email and transactional free-tier abuse controls.

Revision ID: 0006_free_abuse_verification
Revises: 0005_analysis_sandbox
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0006_free_abuse_verification"
down_revision = "0005_analysis_sandbox"
branch_labels = None
depends_on = None

SCHEDULER_ROLE = "akc_scheduler"
ANALYSIS_ROLE = "akc_analysis_worker"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {
        str(column["name"])
        for column in inspect(op.get_bind()).get_columns(table)
    }


def _indexes(table: str) -> set[str]:
    return {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes(table)
    }


def _add_verified_state() -> None:
    if "email_verified_at" not in _columns("users"):
        op.add_column(
            "users",
            sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        )
        # Existing accounts retain access. New registrations are created only
        # after this migration and start unverified.
        op.execute(
            """
            UPDATE users
            SET email_verified_at = created_at
            WHERE email_verified_at IS NULL
            """
        )


def _create_verification_tables() -> None:
    tables = _tables()
    if "email_verification_tokens" not in tables:
        op.create_table(
            "email_verification_tokens",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True)),
            sa.Column("invalidated_at", sa.DateTime(timezone=True)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "user_id"],
                ["memberships.tenant_id", "memberships.user_id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uq_email_verification_token_hash"),
            sa.UniqueConstraint(
                "tenant_id",
                "id",
                name="uq_email_verification_token_tenant",
            ),
        )
    if (
        "email_verification_tokens_active_idx"
        not in _indexes("email_verification_tokens")
    ):
        op.create_index(
            "email_verification_tokens_active_idx",
            "email_verification_tokens",
            ["tenant_id", "user_id", "expires_at"],
            unique=False,
            postgresql_where=sa.text(
                "consumed_at IS NULL AND invalidated_at IS NULL"
            ),
            sqlite_where=sa.text(
                "consumed_at IS NULL AND invalidated_at IS NULL"
            ),
        )

    tables = _tables()
    if "email_verification_deliveries" not in tables:
        op.create_table(
            "email_verification_deliveries",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("recipient_pseudonym", sa.String(length=67), nullable=False),
            sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column(
                "status",
                sa.String(length=24),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_error_code", sa.String(length=80)),
            sa.Column("provider_message_id", sa.String(length=200)),
            sa.Column("delivered_at", sa.DateTime(timezone=True)),
            sa.Column("dead_lettered_at", sa.DateTime(timezone=True)),
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
                "status IN ('pending','retry','delivered','dead_letter')",
                name="email_verification_delivery_status_check",
            ),
            sa.CheckConstraint(
                "attempts >= 0",
                name="email_verification_delivery_attempts_check",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "user_id"],
                ["memberships.tenant_id", "memberships.user_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["token_hash"],
                ["email_verification_tokens.token_hash"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "id",
                name="uq_email_verification_delivery_tenant",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "token_hash",
                name="uq_email_verification_delivery_token",
            ),
        )
    if (
        "email_verification_deliveries_due_idx"
        not in _indexes("email_verification_deliveries")
    ):
        op.create_index(
            "email_verification_deliveries_due_idx",
            "email_verification_deliveries",
            ["available_at", "created_at", "id"],
            unique=False,
            postgresql_where=sa.text("status IN ('pending','retry')"),
            sqlite_where=sa.text("status IN ('pending','retry')"),
        )


def _create_free_usage_tables() -> None:
    tables = _tables()
    if "free_daily_usage" not in tables:
        op.create_table(
            "free_daily_usage",
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("usage_date", sa.Date(), nullable=False),
            sa.Column(
                "file_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "page_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "gpu_cost_usd",
                sa.Numeric(18, 6),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.CheckConstraint("file_count >= 0", name="free_daily_file_nonnegative"),
            sa.CheckConstraint("page_count >= 0", name="free_daily_page_nonnegative"),
            sa.CheckConstraint("gpu_cost_usd >= 0", name="free_daily_gpu_nonnegative"),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("tenant_id", "usage_date"),
        )
    tables = _tables()
    if "free_usage_reservations" not in tables:
        op.create_table(
            "free_usage_reservations",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("usage_date", sa.Date(), nullable=False),
            sa.Column("operation_key", sa.String(length=200), nullable=False),
            sa.Column(
                "file_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "page_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "gpu_cost_usd",
                sa.Numeric(18, 6),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.CheckConstraint(
                "file_count >= 0 AND page_count >= 0 AND gpu_cost_usd >= 0",
                name="free_usage_reservation_nonnegative",
            ),
            sa.CheckConstraint(
                "file_count > 0 OR page_count > 0 OR gpu_cost_usd > 0",
                name="free_usage_reservation_nonzero",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "usage_date"],
                ["free_daily_usage.tenant_id", "free_daily_usage.usage_date"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "operation_key",
                name="uq_free_usage_operation",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "id",
                name="uq_free_usage_reservation_tenant",
            ),
        )
    tables = _tables()
    if "free_processed_sources" not in tables:
        op.create_table(
            "free_processed_sources",
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("document_id", sa.Uuid(), nullable=False),
            sa.Column("source_file_id", sa.Uuid(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.CheckConstraint(
                "length(sha256) = 64",
                name="free_processed_source_digest_length",
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
            sa.PrimaryKeyConstraint("tenant_id", "sha256"),
        )


def _enable_rls() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in (
        "email_verification_tokens",
        "email_verification_deliveries",
        "free_daily_usage",
        "free_usage_reservations",
        "free_processed_sources",
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
        policy = f"{table}_tenant_isolation"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
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


def _grant_worker_access() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"""
        GRANT SELECT, DELETE ON TABLE
            email_verification_tokens,
            email_verification_deliveries
        TO {SCHEDULER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status, attempts, available_at, last_error_code,
            provider_message_id, delivered_at, dead_lettered_at, updated_at
        ) ON TABLE email_verification_deliveries TO {SCHEDULER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT SELECT ON TABLE
            tenants,
            free_daily_usage,
            free_usage_reservations
        TO {ANALYSIS_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT INSERT ON TABLE
            free_daily_usage,
            free_usage_reservations
        TO {ANALYSIS_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (page_count, updated_at)
        ON TABLE free_daily_usage TO {ANALYSIS_ROLE}
        """
    )


def upgrade() -> None:
    _add_verified_state()
    _create_verification_tables()
    _create_free_usage_tables()
    _enable_rls()
    _grant_worker_access()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "free_usage_reservations",
            "free_daily_usage",
            "tenants",
        ):
            op.execute(
                f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {ANALYSIS_ROLE}"
            )
        for table in (
            "email_verification_deliveries",
            "email_verification_tokens",
        ):
            op.execute(
                f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {SCHEDULER_ROLE}"
            )
    for table in (
        "free_processed_sources",
        "free_usage_reservations",
        "free_daily_usage",
        "email_verification_deliveries",
        "email_verification_tokens",
    ):
        if table in _tables():
            op.drop_table(table)
    if "email_verified_at" in _columns("users"):
        op.drop_column("users", "email_verified_at")
