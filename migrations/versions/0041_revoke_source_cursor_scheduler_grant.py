"""Keep source cursors out of the scheduler and admit tenant-scoped API reads.

Apply this migration before deploying the scheduler image that rejects its old
grant. A downgrade likewise requires rolling back that image in the same
release; the runtime capability check intentionally fails closed on mismatch.

Revision ID: 0041_revoke_source_cursor_scheduler_grant
Revises: 0040_source_cursor_tenancy
"""

from __future__ import annotations

from alembic import op

revision = "0041_revoke_source_cursor_scheduler_grant"
down_revision = "0040_source_cursor_tenancy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # 0040 added tenant restrictions but no permissive entry policy. Without
        # one, the API's tenant-scoped SELECT silently returns zero rows.
        # Repeat the tenant predicate here as defense in depth: a later edit to
        # the restrictive policy must not turn this admission policy into a
        # blanket cross-tenant read.
        op.execute("DROP POLICY IF EXISTS source_cursors_api_select ON source_cursors")
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_api_plane') THEN "
            "CREATE POLICY source_cursors_api_select ON source_cursors "
            "AS PERMISSIVE FOR SELECT TO akc_api_plane "
            "USING (source_cursors.tenant_id = "
            "NULLIF(current_setting('app.tenant_id', true), '')::uuid); "
            "END IF; END $$;"
        )
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_scheduler') THEN "
            "REVOKE SELECT, INSERT, UPDATE ON TABLE source_cursors FROM akc_scheduler; "
            "END IF; END $$;"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS source_cursors_api_select ON source_cursors")
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_scheduler') THEN "
            "GRANT SELECT, INSERT, UPDATE ON TABLE source_cursors TO akc_scheduler; "
            "END IF; END $$;"
        )
