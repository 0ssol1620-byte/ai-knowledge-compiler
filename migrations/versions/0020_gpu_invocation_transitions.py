"""Add immutable, lineage-aware GPU fallback and escalation transitions.

Revision ID: 0020_gpu_invocation_transitions
Revises: 0019_oidc_mfa_auth
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0020_gpu_invocation_transitions"
down_revision = "0019_oidc_mfa_auth"
branch_labels = None
depends_on = None

TABLE = "gpu_provider_invocations"
GPU_WORKER_ROLE = "akc_gpu_worker"


def _columns() -> set[str]:
    return {str(column["name"]) for column in inspect(op.get_bind()).get_columns(TABLE)}


def _indexes() -> set[str]:
    return {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes(TABLE)
        if index.get("name")
    }


def _foreign_keys() -> set[str]:
    return {
        str(foreign_key["name"])
        for foreign_key in inspect(op.get_bind()).get_foreign_keys(TABLE)
        if foreign_key.get("name")
    }


def _checks() -> set[str]:
    return {
        str(check["name"])
        for check in inspect(op.get_bind()).get_check_constraints(TABLE)
        if check.get("name")
    }


def _grant_gpu_worker_transition_access() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("GRANT SELECT ON TABLE model_registry TO akc_gpu_worker")
    op.execute("GRANT INSERT ON TABLE audit_events, job_events TO akc_gpu_worker")
    op.execute("GRANT UPDATE (progress, event_sequence) ON TABLE processing_jobs TO akc_gpu_worker")


def upgrade() -> None:
    columns = _columns()
    additions = (
        sa.Column(
            "transition_policy",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("parent_invocation_id", sa.Uuid(), nullable=True),
        sa.Column("lineage_root_invocation_id", sa.Uuid(), nullable=True),
        sa.Column("transition_category", sa.String(length=32), nullable=True),
        sa.Column("transition_strategy", sa.String(length=32), nullable=True),
        sa.Column("transition_action", sa.String(length=24), nullable=True),
        sa.Column(
            "transition_attempt",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    with op.batch_alter_table(TABLE) as batch:
        for column in additions:
            if column.name not in columns:
                batch.add_column(column)

    foreign_keys = _foreign_keys()
    checks = _checks()
    with op.batch_alter_table(TABLE) as batch:
        if "fk_gpu_invocation_parent" not in foreign_keys:
            batch.create_foreign_key(
                "fk_gpu_invocation_parent",
                TABLE,
                ["tenant_id", "parent_invocation_id"],
                ["tenant_id", "id"],
                ondelete="CASCADE",
            )
        if "fk_gpu_invocation_lineage_root" not in foreign_keys:
            batch.create_foreign_key(
                "fk_gpu_invocation_lineage_root",
                TABLE,
                ["tenant_id", "lineage_root_invocation_id"],
                ["tenant_id", "id"],
                ondelete="CASCADE",
            )
        if "gpu_invocation_transition_metadata_check" not in checks:
            batch.create_check_constraint(
                "gpu_invocation_transition_metadata_check",
                """
                (
                    parent_invocation_id IS NULL
                    AND lineage_root_invocation_id IS NULL
                    AND transition_category IS NULL
                    AND transition_strategy IS NULL
                    AND transition_action IS NULL
                    AND transition_attempt = 0
                ) OR (
                    parent_invocation_id IS NOT NULL
                    AND lineage_root_invocation_id IS NOT NULL
                    AND transition_category IN ('gpu_oom','invalid_output')
                    AND transition_strategy IN ('reduce_or_escalate','fallback')
                    AND transition_action IN ('reduce','escalate','fallback')
                    AND transition_attempt BETWEEN 1 AND 10
                )
                """,
            )
        if "gpu_invocation_parent_not_self_check" not in checks:
            batch.create_check_constraint(
                "gpu_invocation_parent_not_self_check",
                "parent_invocation_id IS NULL OR parent_invocation_id <> id",
            )

    indexes = _indexes()
    if "gpu_provider_invocations_parent_idx" not in indexes:
        op.create_index(
            "gpu_provider_invocations_parent_idx",
            TABLE,
            ["tenant_id", "parent_invocation_id"],
        )
    if "gpu_provider_invocations_lineage_idx" not in indexes:
        op.create_index(
            "gpu_provider_invocations_lineage_idx",
            TABLE,
            ["tenant_id", "lineage_root_invocation_id", "created_at"],
        )
    _grant_gpu_worker_transition_access()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "REVOKE UPDATE (progress, event_sequence) ON TABLE processing_jobs FROM akc_gpu_worker"
        )
        op.execute("REVOKE INSERT ON TABLE audit_events, job_events FROM akc_gpu_worker")
        op.execute("REVOKE SELECT ON TABLE model_registry FROM akc_gpu_worker")
    indexes = _indexes()
    for name in (
        "gpu_provider_invocations_lineage_idx",
        "gpu_provider_invocations_parent_idx",
    ):
        if name in indexes:
            op.drop_index(name, table_name=TABLE)
    foreign_keys = _foreign_keys()
    checks = _checks()
    with op.batch_alter_table(TABLE) as batch:
        for name in (
            "fk_gpu_invocation_lineage_root",
            "fk_gpu_invocation_parent",
        ):
            if name in foreign_keys:
                batch.drop_constraint(name, type_="foreignkey")
        for name in (
            "gpu_invocation_parent_not_self_check",
            "gpu_invocation_transition_metadata_check",
        ):
            if name in checks:
                batch.drop_constraint(name, type_="check")
    columns = _columns()
    with op.batch_alter_table(TABLE) as batch:
        for name in (
            "transition_attempt",
            "transition_action",
            "transition_strategy",
            "transition_category",
            "lineage_root_invocation_id",
            "parent_invocation_id",
            "transition_policy",
        ):
            if name in columns:
                batch.drop_column(name)
