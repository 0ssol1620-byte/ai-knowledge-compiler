"""Harden scheduler RLS access, retention fields, and polling indexes.

Revision ID: 0002_scheduler_hardening
Revises: 0001_full_domain
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0002_scheduler_hardening"
down_revision = "0001_full_domain"
branch_labels = None
depends_on = None

SCHEDULER_ROLE = "akc_scheduler"
DISPATCH_ROLE = "akc_dispatch_worker"


def _column_names(table: str) -> set[str]:
    return {
        str(column["name"])
        for column in inspect(op.get_bind()).get_columns(table)
    }


def _index_names(table: str) -> set[str]:
    return {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes(table)
    }


def _add_delivery_retention_columns() -> None:
    columns = _column_names("webhook_deliveries")
    if "dead_lettered_at" not in columns:
        op.add_column(
            "webhook_deliveries",
            sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "created_at" not in columns:
        op.add_column(
            "webhook_deliveries",
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
    if "updated_at" not in columns:
        op.add_column(
            "webhook_deliveries",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )


def _add_outbox_terminal_column() -> None:
    columns = _column_names("outbox_events")
    if "dead_lettered_at" not in columns:
        op.add_column(
            "outbox_events",
            sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        )


def _create_scheduler_indexes() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS outbox_pending_idx")
        op.execute(
            """
            CREATE INDEX outbox_pending_idx
            ON outbox_events (available_at, created_at, id)
            WHERE published_at IS NULL
              AND event_type IN (
                  'job.completed.v1',
                  'job.failed.v1',
                  'export.completed.v1'
              )
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS outbox_dispatch_pending_idx
            ON outbox_events (available_at, created_at, id)
            WHERE published_at IS NULL
              AND dead_lettered_at IS NULL
              AND event_type = 'job.dispatch.requested.v1'
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS outbox_dead_retention_idx
            ON outbox_events (dead_lettered_at, id)
            WHERE dead_lettered_at IS NOT NULL
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS outbox_published_retention_idx
            ON outbox_events (published_at, id)
            WHERE published_at IS NOT NULL
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS webhook_deliveries_due_idx
            ON webhook_deliveries (next_attempt_at, id)
            WHERE status IN ('pending', 'retry')
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS webhook_deliveries_dead_retention_idx
            ON webhook_deliveries (dead_lettered_at, id)
            WHERE status = 'dead_letter'
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS webhook_deliveries_delivered_retention_idx
            ON webhook_deliveries (delivered_at, id)
            WHERE status = 'delivered'
            """
        )
        return

    indexes = _index_names("outbox_events")
    if "outbox_dispatch_pending_idx" not in indexes:
        op.create_index(
            "outbox_dispatch_pending_idx",
            "outbox_events",
            ["available_at", "created_at", "id"],
            sqlite_where=sa.text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type = 'job.dispatch.requested.v1'"
            ),
        )
    if "outbox_dead_retention_idx" not in indexes:
        op.create_index(
            "outbox_dead_retention_idx",
            "outbox_events",
            ["dead_lettered_at", "id"],
            sqlite_where=sa.text("dead_lettered_at IS NOT NULL"),
        )
    if "outbox_published_retention_idx" not in indexes:
        op.create_index(
            "outbox_published_retention_idx",
            "outbox_events",
            ["published_at", "id"],
            sqlite_where=sa.text("published_at IS NOT NULL"),
        )
    delivery_indexes = _index_names("webhook_deliveries")
    if "webhook_deliveries_due_idx" not in delivery_indexes:
        op.create_index(
            "webhook_deliveries_due_idx",
            "webhook_deliveries",
            ["next_attempt_at", "id"],
            sqlite_where=sa.text("status IN ('pending','retry')"),
        )
    if "webhook_deliveries_dead_retention_idx" not in delivery_indexes:
        op.create_index(
            "webhook_deliveries_dead_retention_idx",
            "webhook_deliveries",
            ["dead_lettered_at", "id"],
            sqlite_where=sa.text("status = 'dead_letter'"),
        )
    if "webhook_deliveries_delivered_retention_idx" not in delivery_indexes:
        op.create_index(
            "webhook_deliveries_delivered_retention_idx",
            "webhook_deliveries",
            ["delivered_at", "id"],
            sqlite_where=sa.text("status = 'delivered'"),
        )


def _provision_scheduler_role() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{SCHEDULER_ROLE}'
            ) THEN
                CREATE ROLE {SCHEDULER_ROLE}
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            ELSE
                ALTER ROLE {SCHEDULER_ROLE}
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {SCHEDULER_ROLE}")
    op.execute(
        f"GRANT SELECT, DELETE ON TABLE outbox_events TO {SCHEDULER_ROLE}"
    )
    op.execute(
        f"""
        GRANT UPDATE (published_at, attempts, last_error)
        ON TABLE outbox_events TO {SCHEDULER_ROLE}
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{DISPATCH_ROLE}'
            ) THEN
                CREATE ROLE {DISPATCH_ROLE}
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            ELSE
                ALTER ROLE {DISPATCH_ROLE}
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {DISPATCH_ROLE}")
    op.execute(
        f"""
        GRANT SELECT, INSERT ON TABLE outbox_events TO {DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            available_at,
            published_at,
            dead_lettered_at,
            attempts,
            last_error
        ) ON TABLE outbox_events TO {DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT SELECT ON TABLE
            processing_jobs,
            documents,
            blocks,
            pages,
            knowledge_notes,
            credit_accounts,
            credit_ledger
        TO {DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT INSERT ON TABLE
            job_events,
            knowledge_notes,
            credit_accounts,
            credit_ledger
        TO {DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status,
            started_at,
            completed_at,
            progress,
            cost_actual,
            event_sequence,
            error
        ) ON TABLE processing_jobs TO {DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (status, updated_at)
        ON TABLE pages TO {DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (balance, reserved, version, updated_at)
        ON TABLE credit_accounts TO {DISPATCH_ROLE}
        """
    )
    op.execute(
        f"GRANT SELECT ON TABLE webhook_endpoints TO {SCHEDULER_ROLE}"
    )
    op.execute(
        f"""
        GRANT SELECT, INSERT, DELETE
        ON TABLE webhook_deliveries TO {SCHEDULER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status,
            attempts,
            next_attempt_at,
            last_status_code,
            last_error,
            delivered_at,
            dead_lettered_at,
            updated_at
        )
        ON TABLE webhook_deliveries TO {SCHEDULER_ROLE}
        """
    )


def upgrade() -> None:
    _add_delivery_retention_columns()
    _add_outbox_terminal_column()
    _create_scheduler_indexes()
    _provision_scheduler_role()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f"""
            REVOKE UPDATE (
                balance, reserved, version, updated_at
            ) ON credit_accounts FROM {DISPATCH_ROLE}
            """
        )
        op.execute(
            f"""
            REVOKE UPDATE (status, updated_at)
            ON pages FROM {DISPATCH_ROLE}
            """
        )
        op.execute(
            f"""
            REVOKE UPDATE (
                status,
                started_at,
                completed_at,
                progress,
                cost_actual,
                event_sequence,
                error
            ) ON processing_jobs FROM {DISPATCH_ROLE}
            """
        )
        op.execute(
            f"""
            REVOKE UPDATE (
                available_at,
                published_at,
                dead_lettered_at,
                attempts,
                last_error
            ) ON outbox_events FROM {DISPATCH_ROLE}
            """
        )
        for table in (
            "credit_ledger",
            "credit_accounts",
            "knowledge_notes",
            "job_events",
            "pages",
            "blocks",
            "documents",
            "processing_jobs",
            "outbox_events",
        ):
            op.execute(
                f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {DISPATCH_ROLE}"
            )
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {DISPATCH_ROLE}")
        op.execute(
            f"""
            ALTER ROLE {DISPATCH_ROLE}
                NOBYPASSRLS NOINHERIT NOLOGIN
                NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
            """
        )
        op.execute(
            f"""
            REVOKE UPDATE (
                status,
                attempts,
                next_attempt_at,
                last_status_code,
                last_error,
                delivered_at,
                dead_lettered_at,
                updated_at
            ) ON webhook_deliveries FROM {SCHEDULER_ROLE}
            """
        )
        op.execute(
            f"""
            REVOKE UPDATE (published_at, attempts, last_error)
            ON outbox_events FROM {SCHEDULER_ROLE}
            """
        )
        op.execute(f"REVOKE ALL PRIVILEGES ON webhook_deliveries FROM {SCHEDULER_ROLE}")
        op.execute(f"REVOKE ALL PRIVILEGES ON webhook_endpoints FROM {SCHEDULER_ROLE}")
        op.execute(f"REVOKE ALL PRIVILEGES ON outbox_events FROM {SCHEDULER_ROLE}")
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {SCHEDULER_ROLE}")
        op.execute(
            f"""
            ALTER ROLE {SCHEDULER_ROLE}
                NOBYPASSRLS NOINHERIT NOLOGIN
                NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
            """
        )
    for table, index_name in (
        ("webhook_deliveries", "webhook_deliveries_delivered_retention_idx"),
        ("webhook_deliveries", "webhook_deliveries_dead_retention_idx"),
        ("webhook_deliveries", "webhook_deliveries_due_idx"),
        ("outbox_events", "outbox_dead_retention_idx"),
        ("outbox_events", "outbox_dispatch_pending_idx"),
        ("outbox_events", "outbox_published_retention_idx"),
    ):
        if index_name in _index_names(table):
            op.drop_index(index_name, table_name=table)
    columns = _column_names("webhook_deliveries")
    for column_name in ("updated_at", "created_at", "dead_lettered_at"):
        if column_name in columns:
            op.drop_column("webhook_deliveries", column_name)
    if "dead_lettered_at" in _column_names("outbox_events"):
        op.drop_column("outbox_events", "dead_lettered_at")
