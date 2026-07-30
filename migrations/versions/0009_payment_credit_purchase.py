"""Add provider-neutral payment and credit-purchase evidence.

Revision ID: 0009_payment_credit_purchase
Revises: 0008_global_mutation_idempotency
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0009_payment_credit_purchase"
down_revision = "0008_global_mutation_idempotency"
branch_labels = None
depends_on = None

PAYMENT_ROLE = "akc_payment_worker"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {str(index["name"]) for index in inspect(op.get_bind()).get_indexes(table)}


def _create_checkout() -> None:
    if "payment_checkouts" not in _tables():
        op.create_table(
            "payment_checkouts",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("created_by", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("provider_checkout_id", sa.String(length=200)),
            sa.Column("pack_code", sa.String(length=80), nullable=False),
            sa.Column("amount_minor", sa.BigInteger(), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("credits", sa.Numeric(18, 6), nullable=False),
            sa.Column(
                "status",
                sa.String(length=24),
                nullable=False,
                server_default="requested",
            ),
            sa.Column("checkout_url", sa.String(length=2000)),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
            sa.CheckConstraint("amount_minor > 0"),
            sa.CheckConstraint("credits > 0"),
            sa.CheckConstraint("length(currency) = 3 AND currency = upper(currency)"),
            sa.CheckConstraint(
                "status IN "
                "('requested','provider_pending','open','completed','expired','cancelled')"
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["users.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "provider_checkout_id"),
            sa.UniqueConstraint("tenant_id", "id"),
        )
    if "payment_checkouts_tenant_created_idx" not in _indexes("payment_checkouts"):
        op.create_index(
            "payment_checkouts_tenant_created_idx",
            "payment_checkouts",
            ["tenant_id", "created_at", "id"],
        )


def _create_payments() -> None:
    if "payments" not in _tables():
        op.create_table(
            "payments",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("checkout_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("provider_payment_id", sa.String(length=200), nullable=False),
            sa.Column("amount_minor", sa.BigInteger(), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("credits", sa.Numeric(18, 6), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("paid_at", sa.DateTime(timezone=True)),
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
            sa.CheckConstraint("amount_minor > 0"),
            sa.CheckConstraint("credits > 0"),
            sa.CheckConstraint("length(currency) = 3 AND currency = upper(currency)"),
            sa.CheckConstraint(
                "status IN "
                "('pending','succeeded','partially_refunded','refunded','disputed',"
                "'charged_back','failed','cancelled')"
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "checkout_id"],
                ["payment_checkouts.tenant_id", "payment_checkouts.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "provider_payment_id"),
            sa.UniqueConstraint("tenant_id", "checkout_id"),
            sa.UniqueConstraint("tenant_id", "id"),
        )
    if "payments_tenant_created_idx" not in _indexes("payments"):
        op.create_index(
            "payments_tenant_created_idx",
            "payments",
            ["tenant_id", "created_at", "id"],
        )


def _create_event_inbox() -> None:
    if "payment_events" not in _tables():
        op.create_table(
            "payment_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("provider_event_id", sa.String(length=200), nullable=False),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_sha256", sa.String(length=64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
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
                "next_attempt_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("last_error_code", sa.String(length=120)),
            sa.Column("processed_at", sa.DateTime(timezone=True)),
            sa.Column("dead_lettered_at", sa.DateTime(timezone=True)),
            sa.Column(
                "received_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.CheckConstraint("length(payload_sha256) = 64"),
            sa.CheckConstraint("attempts >= 0"),
            sa.CheckConstraint(
                "status IN ('pending','retry','processed','ignored','dead_letter')"
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "provider_event_id"),
            sa.UniqueConstraint("tenant_id", "id"),
        )
    indexes = _indexes("payment_events")
    if "payment_events_due_idx" not in indexes:
        op.create_index(
            "payment_events_due_idx",
            "payment_events",
            ["next_attempt_at", "received_at", "id"],
            postgresql_where=sa.text("status IN ('pending','retry')"),
            sqlite_where=sa.text("status IN ('pending','retry')"),
        )
    if "payment_events_tenant_received_idx" not in indexes:
        op.create_index(
            "payment_events_tenant_received_idx",
            "payment_events",
            ["tenant_id", "received_at", "id"],
        )


def _create_credit_grants() -> None:
    if "credit_grants" in _tables():
        return
    op.create_table(
        "credit_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("credit_ledger_id", sa.Uuid(), nullable=False),
        sa.Column("operation_key", sa.String(length=200), nullable=False),
        sa.Column("credits", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("credits > 0"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["payments.tenant_id", "payments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "credit_ledger_id"],
            ["credit_ledger.tenant_id", "credit_ledger.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "payment_id"),
        sa.UniqueConstraint("tenant_id", "credit_ledger_id"),
        sa.UniqueConstraint("tenant_id", "operation_key"),
        sa.UniqueConstraint("tenant_id", "id"),
    )


def _create_refunds() -> None:
    if "payment_refunds" in _tables():
        return
    op.create_table(
        "payment_refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("payment_event_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_refund_id", sa.String(length=200), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="succeeded",
        ),
        sa.Column(
            "credits_requested",
            sa.Numeric(18, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("credit_adjusted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("amount_minor > 0"),
        sa.CheckConstraint("credits_requested >= 0"),
        sa.CheckConstraint("length(currency) = 3 AND currency = upper(currency)"),
        sa.CheckConstraint("status IN ('pending','succeeded','failed')"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["payments.tenant_id", "payments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_event_id"],
            ["payment_events.tenant_id", "payment_events.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_refund_id"),
        sa.UniqueConstraint("tenant_id", "payment_event_id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )


def _create_disputes() -> None:
    if "payment_disputes" in _tables():
        return
    op.create_table(
        "payment_disputes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_dispute_id", sa.String(length=200), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "requested_credits",
            sa.Numeric(18, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "held_credits",
            sa.Numeric(18, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "reversed_credits",
            sa.Numeric(18, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "outstanding_credits",
            sa.Numeric(18, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint("amount_minor > 0"),
        sa.CheckConstraint(
            "requested_credits >= 0 AND held_credits >= 0 "
            "AND reversed_credits >= 0 AND outstanding_credits >= 0"
        ),
        sa.CheckConstraint("length(currency) = 3 AND currency = upper(currency)"),
        sa.CheckConstraint("status IN ('open','won','lost','closed')"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["payments.tenant_id", "payments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_dispute_id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )


def _create_reversals() -> None:
    if "credit_reversals" not in _tables():
        op.create_table(
            "credit_reversals",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("payment_id", sa.Uuid(), nullable=False),
            sa.Column("refund_id", sa.Uuid()),
            sa.Column("dispute_id", sa.Uuid()),
            sa.Column("payment_event_id", sa.Uuid()),
            sa.Column("credit_ledger_id", sa.Uuid()),
            sa.Column("operation_key", sa.String(length=200), nullable=False),
            sa.Column("action", sa.String(length=24), nullable=False),
            sa.Column("requested_credits", sa.Numeric(18, 6), nullable=False),
            sa.Column("applied_credits", sa.Numeric(18, 6), nullable=False),
            sa.Column("unrecovered_after", sa.Numeric(18, 6), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.CheckConstraint(
                "requested_credits >= 0 AND applied_credits >= 0 "
                "AND unrecovered_after >= 0"
            ),
            sa.CheckConstraint(
                "action IN "
                "('refund','hold','unhold','chargeback','debt_recovery')"
            ),
            sa.CheckConstraint(
                "(refund_id IS NOT NULL AND dispute_id IS NULL) "
                "OR (refund_id IS NULL AND dispute_id IS NOT NULL)"
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "payment_id"],
                ["payments.tenant_id", "payments.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "refund_id"],
                ["payment_refunds.tenant_id", "payment_refunds.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "dispute_id"],
                ["payment_disputes.tenant_id", "payment_disputes.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "payment_event_id"],
                ["payment_events.tenant_id", "payment_events.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "credit_ledger_id"],
                ["credit_ledger.tenant_id", "credit_ledger.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "operation_key"),
            sa.UniqueConstraint("tenant_id", "id"),
        )
    if "credit_reversals_payment_idx" not in _indexes("credit_reversals"):
        op.create_index(
            "credit_reversals_payment_idx",
            "credit_reversals",
            ["tenant_id", "payment_id", "created_at"],
        )


def _create_reconciliations() -> None:
    if "payment_reconciliations" not in _tables():
        op.create_table(
            "payment_reconciliations",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="running",
            ),
            sa.Column(
                "events_scanned",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "events_processed",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "events_retried",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "events_dead_lettered",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "mismatches",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "repaired",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "outstanding_credits",
                sa.Numeric(18, 6),
                nullable=False,
                server_default="0",
            ),
            sa.Column("last_error_code", sa.String(length=120)),
            sa.Column("created_by", sa.Uuid()),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.CheckConstraint(
                "events_scanned >= 0 AND events_processed >= 0 "
                "AND events_retried >= 0 AND events_dead_lettered >= 0 "
                "AND mismatches >= 0 AND repaired >= 0 "
                "AND outstanding_credits >= 0"
            ),
            sa.CheckConstraint("status IN ('running','completed','failed')"),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["users.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "id"),
        )
    if (
        "payment_reconciliations_tenant_started_idx"
        not in _indexes("payment_reconciliations")
    ):
        op.create_index(
            "payment_reconciliations_tenant_started_idx",
            "payment_reconciliations",
            ["tenant_id", "started_at", "id"],
        )


def _append_only_guards() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION akc_reject_financial_evidence_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'financial evidence is append-only';
            END;
            $$
            """
        )
        for table in ("credit_grants", "credit_reversals"):
            op.execute(
                f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}"
            )
            op.execute(
                f"""
                CREATE TRIGGER {table}_append_only
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION akc_reject_financial_evidence_mutation()
                """
            )
        return
    if bind.dialect.name == "sqlite":
        for table in ("credit_grants", "credit_reversals"):
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS {table}_append_only_update
                BEFORE UPDATE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'financial evidence is append-only');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS {table}_append_only_delete
                BEFORE DELETE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'financial evidence is append-only');
                END
                """
            )


def _enable_rls_and_role() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant_tables = (
        "payment_checkouts",
        "payments",
        "payment_events",
        "credit_grants",
        "payment_refunds",
        "payment_disputes",
        "credit_reversals",
        "payment_reconciliations",
    )
    for table in tenant_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}"
        )
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
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

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{PAYMENT_ROLE}'
            ) THEN
                CREATE ROLE {PAYMENT_ROLE}
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            ELSE
                ALTER ROLE {PAYMENT_ROLE}
                    NOLOGIN NOINHERIT BYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PAYMENT_ROLE}")
    op.execute(
        f"""
        GRANT SELECT ON TABLE
            tenants,
            payment_checkouts,
            payments,
            payment_events,
            credit_grants,
            payment_refunds,
            payment_disputes,
            credit_reversals,
            payment_reconciliations,
            credit_accounts,
            credit_ledger
        TO {PAYMENT_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT INSERT ON TABLE
            payments,
            payment_events,
            credit_grants,
            payment_refunds,
            payment_disputes,
            credit_reversals,
            payment_reconciliations,
            credit_accounts,
            credit_ledger,
            audit_events
        TO {PAYMENT_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status, completed_at, updated_at
        ) ON TABLE payment_checkouts TO {PAYMENT_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status, paid_at, updated_at
        ) ON TABLE payments TO {PAYMENT_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status, attempts, next_attempt_at, last_error_code,
            processed_at, dead_lettered_at
        ) ON TABLE payment_events TO {PAYMENT_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status, credits_requested, credit_adjusted_at
        ) ON TABLE payment_refunds TO {PAYMENT_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status, requested_credits, held_credits, reversed_credits,
            outstanding_credits, last_event_created_at, resolved_at, updated_at
        ) ON TABLE payment_disputes TO {PAYMENT_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            status, events_scanned, events_processed, events_retried,
            events_dead_lettered, mismatches, repaired, outstanding_credits,
            last_error_code, completed_at
        ) ON TABLE payment_reconciliations TO {PAYMENT_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            balance, reserved, version, updated_at
        ) ON TABLE credit_accounts TO {PAYMENT_ROLE}
        """
    )
    op.execute("REVOKE UPDATE, DELETE ON credit_grants FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON credit_reversals FROM PUBLIC")


def upgrade() -> None:
    _create_checkout()
    _create_payments()
    _create_event_inbox()
    _create_credit_grants()
    _create_refunds()
    _create_disputes()
    _create_reversals()
    _create_reconciliations()
    _append_only_guards()
    _enable_rls_and_role()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in (
            "audit_events",
            "credit_ledger",
            "credit_accounts",
            "payment_reconciliations",
            "credit_reversals",
            "payment_disputes",
            "payment_refunds",
            "credit_grants",
            "payment_events",
            "payments",
            "payment_checkouts",
            "tenants",
        ):
            op.execute(
                f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {PAYMENT_ROLE}"
            )
        for table in ("credit_grants", "credit_reversals"):
            op.execute(
                f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}"
            )
        op.execute(
            "DROP FUNCTION IF EXISTS akc_reject_financial_evidence_mutation()"
        )
    elif bind.dialect.name == "sqlite":
        for table in ("credit_grants", "credit_reversals"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_delete")
    for table in (
        "payment_reconciliations",
        "credit_reversals",
        "payment_disputes",
        "payment_refunds",
        "credit_grants",
        "payment_events",
        "payments",
        "payment_checkouts",
    ):
        if table in _tables():
            op.drop_table(table)
