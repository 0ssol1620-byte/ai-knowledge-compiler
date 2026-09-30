"""Remove unused cursor control-plane authority and admit tenant-bound API reads.

Revision ID: 0041_source_cursor_acl
Revises: 0040_source_cursor_tenancy
"""

from alembic import op

revision = "0041_source_cursor_acl"
down_revision = "0040_source_cursor_tenancy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # No scheduler cursor writer exists. Keep the scheduler's approved table
    # surface unchanged instead of expanding its startup capability allowlist.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_scheduler') THEN
                REVOKE ALL PRIVILEGES ON TABLE source_cursors FROM akc_scheduler;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_api_plane') THEN
                DROP POLICY IF EXISTS source_cursors_api_read ON source_cursors;
                CREATE POLICY source_cursors_api_read ON source_cursors
                    AS PERMISSIVE FOR SELECT TO akc_api_plane
                    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS source_cursors_api_read ON source_cursors")
    # Restore the previous revision's exact privilege shape on explicit rollback.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_scheduler') THEN
                GRANT SELECT, INSERT, UPDATE ON TABLE source_cursors TO akc_scheduler;
            END IF;
        END $$;
        """
    )
