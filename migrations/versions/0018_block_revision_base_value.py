"""Preserve exact base text for deterministic three-way block merges.

Revision ID: 0018_block_revision_base_value
Revises: 0017_active_revision_pointers
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0018_block_revision_base_value"
down_revision = "0017_active_revision_pointers"
branch_labels = None
depends_on = None


def _column_names() -> set[str]:
    return {str(column["name"]) for column in inspect(op.get_bind()).get_columns("block_revisions")}


def upgrade() -> None:
    if "base_value" not in _column_names():
        with op.batch_alter_table("block_revisions") as batch:
            batch.add_column(sa.Column("base_value", sa.Text(), nullable=True))


def downgrade() -> None:
    if "base_value" in _column_names():
        with op.batch_alter_table("block_revisions") as batch:
            batch.drop_column("base_value")
