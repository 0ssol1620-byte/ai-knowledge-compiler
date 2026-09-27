"""Keep tenant source cursors outside the scheduler control-plane boundary.

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
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_scheduler') THEN "
            "REVOKE SELECT, INSERT, UPDATE ON TABLE source_cursors FROM akc_scheduler; "
            "END IF; END $$;"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'akc_scheduler') THEN "
            "GRANT SELECT, INSERT, UPDATE ON TABLE source_cursors TO akc_scheduler; "
            "END IF; END $$;"
        )
