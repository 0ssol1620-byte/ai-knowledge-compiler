"""Add reviewed model promotion, rollback, and retirement state.

Revision ID: 0021_model_lifecycle
Revises: 0020_gpu_invocation_transitions
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0021_model_lifecycle"
down_revision = "0020_gpu_invocation_transitions"
branch_labels = None
depends_on = None

TABLE = "model_registry"


def _columns() -> set[str]:
    return {str(column["name"]) for column in inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    columns = _columns()
    additions: tuple[tuple[str, sa.Column[object]], ...] = (
        (
            "lifecycle_state",
            sa.Column(
                "lifecycle_state",
                sa.String(length=24),
                nullable=False,
                server_default="candidate",
            ),
        ),
        (
            "generation",
            sa.Column(
                "generation",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        ),
        (
            "promoted_from_id",
            sa.Column("promoted_from_id", sa.Uuid(), nullable=True),
        ),
        (
            "benchmark_sha256",
            sa.Column("benchmark_sha256", sa.String(length=71), nullable=True),
        ),
        (
            "recipe_sha256",
            sa.Column("recipe_sha256", sa.String(length=71), nullable=True),
        ),
        (
            "approval_ref",
            sa.Column("approval_ref", sa.String(length=160), nullable=True),
        ),
        (
            "retired_at",
            sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        ),
        (
            "updated_at",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        ),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column(TABLE, column)

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE model_registry SET lifecycle_state = "
            "CASE WHEN enabled THEN 'champion' ELSE 'candidate' END "
            "WHERE lifecycle_state = 'candidate'"
        )
    )
    foreign_keys = {
        str(item["name"]) for item in inspect(bind).get_foreign_keys(TABLE) if item.get("name")
    }
    if "fk_model_registry_promoted_from" not in foreign_keys:
        with op.batch_alter_table(TABLE) as batch:
            batch.create_foreign_key(
                "fk_model_registry_promoted_from",
                TABLE,
                ["promoted_from_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        foreign_keys = {
            str(item["name"])
            for item in inspect(op.get_bind()).get_foreign_keys(TABLE)
            if item.get("name")
        }
        if "fk_model_registry_promoted_from" in foreign_keys:
            batch.drop_constraint("fk_model_registry_promoted_from", type_="foreignkey")
        for name in (
            "updated_at",
            "retired_at",
            "approval_ref",
            "recipe_sha256",
            "benchmark_sha256",
            "promoted_from_id",
            "generation",
            "lifecycle_state",
        ):
            if name in _columns():
                batch.drop_column(name)
