"""Execute bounded JobEvent hot retention with the scheduler role.

Revision ID: 0007_job_event_retention
Revises: 0006_free_abuse_verification
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "0007_job_event_retention"
down_revision = "0006_free_abuse_verification"
branch_labels = None
depends_on = None

SCHEDULER_ROLE = "akc_scheduler"


def _indexes(table: str) -> set[str]:
    return {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes(table)
    }


def upgrade() -> None:
    if "job_events_retention_idx" not in _indexes("job_events"):
        op.create_index(
            "job_events_retention_idx",
            "job_events",
            ["occurred_at", "id"],
        )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            f"GRANT SELECT, DELETE ON TABLE job_events TO {SCHEDULER_ROLE}"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            f"REVOKE SELECT, DELETE ON TABLE job_events FROM {SCHEDULER_ROLE}"
        )
    if "job_events_retention_idx" in _indexes("job_events"):
        op.drop_index("job_events_retention_idx", table_name="job_events")
