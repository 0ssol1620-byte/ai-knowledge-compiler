"""Keep connector cursors in the tenant-scoped API plane.

Revision ID: 0041_source_cursor_plane_boundary
Revises: 0040_source_cursor_tenancy

Revision 0040 granted the BYPASSRLS scheduler role SELECT, INSERT, and UPDATE
on source_cursors even though no scheduler path uses the table. That silently
expanded the approved control-plane table boundary and made the exact ACL gate
fail. The API freshness dashboard is the current reader. Give that reader a
tenant-matching permissive SELECT policy alongside 0040's restrictive tenant
policy, and remove the scheduler's unused cross-tenant grant.
"""

from __future__ import annotations

from alembic import op

revision = "0041_source_cursor_plane_boundary"
down_revision = "0040_source_cursor_tenancy"
branch_labels = None
depends_on = None

TABLE = "source_cursors"
POLICY = "source_cursors_api_select"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_scheduler') THEN "
        'REVOKE SELECT, INSERT, UPDATE ON TABLE "source_cursors" FROM akc_scheduler; '
        "END IF; END $$;"
    )
    op.execute(
        f'CREATE POLICY "{POLICY}" ON "{TABLE}" '
        "AS PERMISSIVE FOR SELECT TO akc_api_plane "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f'DROP POLICY "{POLICY}" ON "{TABLE}"')
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_scheduler') THEN "
        'GRANT SELECT, INSERT, UPDATE ON TABLE "source_cursors" TO akc_scheduler; '
        "END IF; END $$;"
    )
