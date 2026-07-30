"""Add tenant-safe team invitations and encrypted delivery outbox.

Revision ID: 0012_team_collaboration
Revises: 0011_durable_gpu_provider_jobs
Create Date: 2026-07-30
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

from akc_api.team_models import TeamInvitation, TeamInvitationDelivery

revision = "0012_team_collaboration"
down_revision = "0011_durable_gpu_provider_jobs"
branch_labels = None
depends_on = None

_TENANT_TABLES = (
    "team_invitations",
    "team_invitation_deliveries",
)


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    if "team_invitations" not in _tables():
        TeamInvitation.__table__.create(bind=bind)
    if "team_invitation_deliveries" not in _tables():
        TeamInvitationDelivery.__table__.create(bind=bind)
    if bind.dialect.name != "postgresql":
        return
    for table in _TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            "USING (tenant_id = "
            "NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = "
            "NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables()
    if bind.dialect.name == "postgresql":
        for table in reversed(_TENANT_TABLES):
            if table in tables:
                op.execute(
                    f'DROP POLICY IF EXISTS "{table}_tenant_isolation" '
                    f'ON "{table}"'
                )
    if "team_invitation_deliveries" in tables:
        TeamInvitationDelivery.__table__.drop(bind=bind)
    if "team_invitations" in tables:
        TeamInvitation.__table__.drop(bind=bind)
