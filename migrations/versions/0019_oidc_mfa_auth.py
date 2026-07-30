"""Add verified OIDC bindings/transactions and tenant-scoped MFA state.

Revision ID: 0019_oidc_mfa_auth
Revises: 0018_block_revision_base_value
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0019_oidc_mfa_auth"
down_revision = "0018_block_revision_base_value"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes(table)
        if index.get("name")
    }


def _create_oidc_identities() -> None:
    if "oidc_identities" in _tables():
        return
    op.create_table(
        "oidc_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email_at_binding", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "issuer",
            "subject",
            name="uq_oidc_identity_subject",
        ),
        sa.UniqueConstraint(
            "user_id",
            "issuer",
            name="uq_oidc_identity_user_issuer",
        ),
    )
    op.create_index(
        "oidc_identities_user_idx",
        "oidc_identities",
        ["user_id"],
        unique=False,
    )


def _create_oidc_transactions() -> None:
    if "oidc_login_transactions" in _tables():
        return
    op.create_table(
        "oidc_login_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("browser_binding_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("encrypted_secrets", sa.LargeBinary(), nullable=False),
        sa.Column("binding_user_id", sa.Uuid(), nullable=True),
        sa.Column("binding_tenant_id", sa.Uuid(), nullable=True),
        sa.Column("tenant_slug", sa.String(length=100), nullable=True),
        sa.Column("tenant_name", sa.String(length=200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('login','bind')",
            name="oidc_transaction_purpose_check",
        ),
        sa.ForeignKeyConstraint(
            ["binding_tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["binding_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index(
        "oidc_login_transactions_active_idx",
        "oidc_login_transactions",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("consumed_at IS NULL"),
        sqlite_where=sa.text("consumed_at IS NULL"),
    )


def _create_mfa_credentials() -> None:
    if "mfa_credentials" in _tables():
        return
    op.create_table(
        "mfa_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("encrypted_secret", sa.LargeBinary(), nullable=False),
        sa.Column("recovery_code_hashes", sa.JSON(), nullable=False),
        sa.Column("last_totp_step", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','active','disabled')",
            name="mfa_credential_status_check",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            name="uq_mfa_credential_tenant_user",
        ),
        sa.UniqueConstraint("tenant_id", "id"),
    )


def _create_mfa_challenges() -> None:
    if "mfa_challenges" in _tables():
        return
    op.create_table(
        "mfa_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('enroll','challenge')",
            name="mfa_challenge_purpose_check",
        ),
        sa.CheckConstraint(
            "failures BETWEEN 0 AND 5",
            name="mfa_challenge_failures_check",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index(
        "mfa_challenges_active_idx",
        "mfa_challenges",
        ["tenant_id", "user_id", "expires_at"],
        unique=False,
        postgresql_where=sa.text("consumed_at IS NULL"),
        sqlite_where=sa.text("consumed_at IS NULL"),
    )


def _ensure_indexes() -> None:
    if "oidc_identities" in _tables() and "oidc_identities_user_idx" not in _indexes(
        "oidc_identities"
    ):
        op.create_index(
            "oidc_identities_user_idx",
            "oidc_identities",
            ["user_id"],
            unique=False,
        )
    if (
        "oidc_login_transactions" in _tables()
        and "oidc_login_transactions_active_idx" not in _indexes("oidc_login_transactions")
    ):
        op.create_index(
            "oidc_login_transactions_active_idx",
            "oidc_login_transactions",
            ["expires_at"],
            unique=False,
            postgresql_where=sa.text("consumed_at IS NULL"),
            sqlite_where=sa.text("consumed_at IS NULL"),
        )
    if "mfa_challenges" in _tables() and "mfa_challenges_active_idx" not in _indexes(
        "mfa_challenges"
    ):
        op.create_index(
            "mfa_challenges_active_idx",
            "mfa_challenges",
            ["tenant_id", "user_id", "expires_at"],
            unique=False,
            postgresql_where=sa.text("consumed_at IS NULL"),
            sqlite_where=sa.text("consumed_at IS NULL"),
        )


def _enable_postgresql_security() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in ("mfa_credentials", "mfa_challenges"):
        policy = f"{table}_tenant_isolation"
        policies = {
            str(row[0])
            for row in op.get_bind().execute(
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
    # These global control-plane tables are intentionally not tenant-RLS
    # scoped: an OIDC subject is resolved before a tenant is selected.  Remove
    # ambient PUBLIC mutations; the owning application role retains access.
    op.execute("REVOKE ALL ON TABLE oidc_identities, oidc_login_transactions FROM PUBLIC")


def upgrade() -> None:
    _create_oidc_identities()
    _create_oidc_transactions()
    _create_mfa_credentials()
    _create_mfa_challenges()
    _ensure_indexes()
    _enable_postgresql_security()


def downgrade() -> None:
    tables = _tables()
    if op.get_bind().dialect.name == "postgresql":
        for table in ("mfa_challenges", "mfa_credentials"):
            if table in tables:
                op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    for table in (
        "mfa_challenges",
        "mfa_credentials",
        "oidc_login_transactions",
        "oidc_identities",
    ):
        if table in _tables():
            op.drop_table(table)
