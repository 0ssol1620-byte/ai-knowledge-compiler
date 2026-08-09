"""Anonymous trial ingest: system trial tenant and trial sessions.

ADR-006. The hero on the marketing surface may accept a document from a visitor
with no account. Tenant scoping is preserved rather than excepted: the visitor's
document belongs to a reserved system tenant, and the session that owns it is an
ordinary project under that tenant. Nothing here creates a tenant-less row and
nothing weakens the row-level policies that make `postgres-rls-and-role-boundaries`
meaningful.

The system user exists because `projects.created_by` is a non-null FK to
`users.id`. It is `is_active = false`, so every principal lookup in the API —
which filters on `is_active` — refuses it, and its password hash is the Unix
locked-account sentinel, which no verifier accepts.

Revision ID: 0023_trial_ingest
Revises: 0022_cdr_derivative_lineage
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0023_trial_ingest"
down_revision = "0022_cdr_derivative_lineage"
branch_labels = None
depends_on = None

# Reserved, deterministic identifiers. They are constants rather than generated
# values so every environment resolves the trial tenant identically and a
# migration re-run cannot create a second one.
TRIAL_TENANT_ID = uuid.UUID("00000000-0000-4000-a000-000000000b01")
TRIAL_USER_ID = uuid.UUID("00000000-0000-4000-a000-000000000b02")
TRIAL_TENANT_SLUG = "system-trial"

# RFC 2606 reserves .invalid, so this address can never be registered or
# delivered to.
TRIAL_USER_EMAIL = "trial-service@system.invalid"

# The Unix convention for an account that exists but cannot authenticate. It is
# not a valid hash in any supported scheme, so verification fails rather than
# comparing against something.
LOCKED_ACCOUNT_HASH = "!"

TABLE = "trial_sessions"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """Create the table if it is missing, then always apply policy and seeds.

    The three steps are separate because they can be in different states.
    0001_full_domain runs ``Base.metadata.create_all``, so on a database built
    that way this table already exists when this revision runs — but 0001's RLS
    loop iterates a hardcoded TENANT_TABLES list that does not include it, so
    the policy would still be missing. Returning early on "table exists" would
    leave the one anonymous-writable table without row-level security, which is
    the opposite of what this migration is for.
    """
    if TABLE not in _tables():
        _create_table()
    _apply_row_level_security()
    _seed_system_rows()


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        # The project that holds the visitor's document. One per session.
        sa.Column("project_id", sa.Uuid(), nullable=False),
        # Pseudonymised client identity from the existing IdentityHasher. Never
        # a raw address: the limiter and this row see the same opaque subject.
        sa.Column("client_subject", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            # CURRENT_TIMESTAMP rather than now(): the same DDL has to apply on
            # SQLite, which the migration tests run against.
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        # ADR-006 caps the lifetime at one hour. Stored rather than computed so
        # the retention sweep does not depend on the policy constant staying
        # the same as when the row was written.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("adopted_tenant_id", sa.Uuid(), nullable=True),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("project_id"),
        sa.CheckConstraint("expires_at > created_at", name="trial_sessions_ttl_forward"),
    )

    # The table was just created, so neither index can exist yet.
    #
    # The sweep reads by expiry among rows not already retired.
    op.create_index(
        "trial_sessions_expiry_idx",
        TABLE,
        ["expires_at"],
        postgresql_where=sa.text("deletion_requested_at IS NULL"),
    )
    # The limiter counts live sessions per pseudonymised client.
    op.create_index(
        "trial_sessions_client_idx",
        TABLE,
        ["client_subject", "created_at"],
    )


def _apply_row_level_security() -> None:
    """Same isolation shape as every other tenant table (0001_full_domain).

    Idempotent, and skipped outside PostgreSQL — SQLite is the deterministic
    development adapter and has no row-level security, which is also why
    ``set_rls_context`` is a no-op there.
    """
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f'ALTER TABLE "{TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{TABLE}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS "{TABLE}_tenant_isolation" ON "{TABLE}"')
    op.execute(
        f'CREATE POLICY "{TABLE}_tenant_isolation" ON "{TABLE}" '
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def _seed_system_rows() -> None:
    """Insert the reserved tenant and its service user, idempotently.

    Written in portable SQL — CURRENT_TIMESTAMP and bound booleans rather than
    now() and literal true/false. The first draft used the Postgres spellings
    and failed on SQLite, which is the deterministic development adapter and
    the one this repository actually runs migrations against in tests.

    Private mode is on and external transfer is off, so a trial document can
    never be sent to an external provider regardless of later configuration —
    ADR-003 makes private mode override tenant flags, and this sets both.
    Retention is zero days: the sweep owns the lifetime, and nothing here should
    survive a nightly retention pass either.
    """
    op.execute(
        sa.text(
            """
            INSERT INTO tenants (
                id, slug, name, plan_code, region, data_retention_days,
                private_mode, external_transfer_allowed, training_opt_in,
                preview_pii_masking, created_at, updated_at
            )
            VALUES (
                :id, :slug, 'System trial', 'trial', 'ap-northeast', 0,
                :yes, :no, :no, :yes, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(
            id=TRIAL_TENANT_ID, slug=TRIAL_TENANT_SLUG, yes=True, no=False
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO users (
                id, email, password_hash, display_name, is_active,
                email_verified_at, created_at
            )
            VALUES (
                :id, :email, :hash, 'Trial ingest service', :inactive, NULL,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(
            id=TRIAL_USER_ID,
            email=TRIAL_USER_EMAIL,
            hash=LOCKED_ACCOUNT_HASH,
            inactive=False,
        )
    )


def downgrade() -> None:
    if TABLE not in _tables():
        return
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f'DROP POLICY IF EXISTS "{TABLE}_tenant_isolation" ON "{TABLE}"')
    # Dropping the table takes its indexes with it, and naming them explicitly
    # fails where upgrade stopped after create_table.
    op.drop_table(TABLE)
    # The seeded rows are left in place. Dropping the tenant would cascade to
    # any project and document still referencing it, which is a data-destroying
    # side effect a schema downgrade should not perform.
