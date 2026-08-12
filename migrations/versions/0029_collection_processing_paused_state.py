"""Give collection processing a first-class paused state.

Revision ID: 0029_collection_processing_paused_state
Revises: 0028_collection_integrity_decisions
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0029_collection_processing_paused_state"
down_revision = "0028_collection_integrity_decisions"
branch_labels = None
depends_on = None

_TABLE = "processing_jobs"
_OLD_STATUS = (
    "status IN ('queued','running','waiting_review','completed','failed','cancelled')"
)
_NEW_STATUS = (
    "status IN ("
    "'queued','running','paused','waiting_review','completed','failed','cancelled'"
    ")"
)


def _replace_status_check(*, include_paused: bool) -> None:
    bind = op.get_bind()
    if _TABLE not in inspect(bind).get_table_names():
        return
    checks = [
        row
        for row in inspect(bind).get_check_constraints(_TABLE)
        if "status" in str(row.get("sqltext", "")).casefold()
        and "waiting_review" in str(row.get("sqltext", "")).casefold()
    ]
    if checks and all(
        ("paused" in str(row.get("sqltext", "")).casefold()) is include_paused
        for row in checks
    ):
        return
    target = _NEW_STATUS if include_paused else _OLD_STATUS
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            _TABLE,
            recreate="always",
            naming_convention={"ck": "ck_%(table_name)s_%(column_0_name)s"},
        ) as batch:
            for check in checks:
                name = check.get("name")
                if name:
                    batch.drop_constraint(str(name), type_="check")
            batch.create_check_constraint("ck_processing_jobs_status", target)
        return
    for check in checks:
        name = check.get("name")
        if name:
            op.drop_constraint(str(name), _TABLE, type_="check")
    op.create_check_constraint("ck_processing_jobs_status", _TABLE, target)


def upgrade() -> None:
    _replace_status_check(include_paused=True)
    if _TABLE in inspect(op.get_bind()).get_table_names():
        op.get_bind().execute(
            sa.text(
                "UPDATE processing_jobs SET status = 'paused' "
                "WHERE job_type = 'collection_processing' AND status = 'waiting_review'"
            )
        )


def downgrade() -> None:
    if _TABLE in inspect(op.get_bind()).get_table_names():
        op.get_bind().execute(
            sa.text(
                "UPDATE processing_jobs SET status = 'waiting_review' "
                "WHERE job_type = 'collection_processing' AND status = 'paused'"
            )
        )
    _replace_status_check(include_paused=False)
