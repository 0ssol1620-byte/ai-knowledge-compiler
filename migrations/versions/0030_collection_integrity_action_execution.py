"""Execute collection integrity decisions through bounded durable work.

Revision ID: 0030_collection_integrity_action_execution
Revises: 0029_collection_processing_paused_state
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0030_collection_integrity_action_execution"
down_revision = "0029_collection_processing_paused_state"
branch_labels = None
depends_on = None

_TABLE = "collection_integrity_action_executions"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _tenant_setting() -> str:
    return "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _user_setting() -> str:
    return "NULLIF(current_setting('app.user_id', true), '')::uuid"


def _tenant_role(*roles: str) -> str:
    values = ", ".join(f"'{role}'" for role in roles)
    return (
        "EXISTS ("  # noqa: S608 - migration-owned identifiers and roles.
        "SELECT 1 FROM memberships integrity_execution_membership "
        f"WHERE integrity_execution_membership.tenant_id = {_tenant_setting()} "
        f"AND integrity_execution_membership.user_id = {_user_setting()} "
        f"AND integrity_execution_membership.role IN ({values})"
        ")"
    )


def _project_access(*, write: bool) -> str:
    roles = ("editor",) if write else ("editor", "reviewer", "viewer")
    values = ", ".join(f"'{role}'" for role in roles)
    explicit = (
        "EXISTS ("  # noqa: S608 - migration-owned identifiers and roles.
        "SELECT 1 FROM project_memberships integrity_execution_project "
        "JOIN memberships integrity_execution_access "
        "ON integrity_execution_access.tenant_id = integrity_execution_project.tenant_id "
        "AND integrity_execution_access.user_id = integrity_execution_project.user_id "
        f"WHERE integrity_execution_project.tenant_id = {_tenant_setting()} "
        f"AND integrity_execution_project.user_id = {_user_setting()} "
        "AND integrity_execution_project.project_id = integrity_execution_collection.project_id "
        f"AND integrity_execution_access.role IN ({values}) "
        f"AND integrity_execution_project.role IN ({values})"
        ")"
    )
    return f"({_tenant_role('owner', 'admin')} OR {explicit})"


def _create_table() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("execution_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("processing_job_id", sa.Uuid(), nullable=True),
        sa.Column("analysis_task_id", sa.Uuid(), nullable=True),
        sa.Column("registry_model_id", sa.Uuid(), nullable=True),
        sa.Column("target_scope", sa.JSON(), nullable=False),
        sa.Column("execution_receipt_sha256", sa.String(length=64), nullable=False),
        sa.Column("result_code", sa.String(length=120), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "collection_id"],
            ["collections.tenant_id", "collections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decision_id"],
            ["collection_integrity_decisions.tenant_id", "collection_integrity_decisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "processing_job_id"],
            ["processing_jobs.tenant_id", "processing_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "analysis_task_id"],
            ["analysis_tasks.tenant_id", "analysis_tasks.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["registry_model_id"],
            ["model_registry.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint(
            "decision_id",
            name="uq_collection_integrity_action_decision",
        ),
        sa.CheckConstraint(
            "execution_kind IN ('synchronous','compile_retry','password_analysis')",
            name="ck_collection_integrity_action_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed')",
            name="ck_collection_integrity_action_status",
        ),
        sa.CheckConstraint(
            "length(execution_receipt_sha256) = 64",
            name="ck_collection_integrity_action_receipt_sha",
        ),
        sa.CheckConstraint(
            "(execution_kind = 'synchronous' AND processing_job_id IS NULL "
            "AND analysis_task_id IS NULL AND registry_model_id IS NULL) OR "
            "(execution_kind = 'compile_retry' AND processing_job_id IS NOT NULL "
            "AND analysis_task_id IS NULL AND registry_model_id IS NOT NULL) OR "
            "(execution_kind = 'password_analysis' AND processing_job_id IS NULL "
            "AND analysis_task_id IS NOT NULL AND registry_model_id IS NULL)",
            name="ck_collection_integrity_action_binding",
        ),
        sa.CheckConstraint(
            "(status IN ('queued','running') AND completed_at IS NULL) OR "
            "(status IN ('completed','failed') AND completed_at IS NOT NULL)",
            name="ck_collection_integrity_action_terminal",
        ),
    )
    op.create_index(
        "collection_integrity_action_collection_idx",
        _TABLE,
        ["collection_id", "status", "created_at"],
    )
    op.create_index(
        "collection_integrity_action_job_idx",
        _TABLE,
        ["tenant_id", "processing_job_id"],
    )
    op.create_index(
        "collection_integrity_action_task_idx",
        _TABLE,
        ["tenant_id", "analysis_task_id"],
    )


def _enable_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY')
    tenant_scope = f'"{_TABLE}".tenant_id = {_tenant_setting()}'
    read_scope = (
        "EXISTS (SELECT 1 FROM collections integrity_execution_collection "  # noqa: S608
        f"WHERE integrity_execution_collection.tenant_id = \"{_TABLE}\".tenant_id "
        f"AND integrity_execution_collection.id = \"{_TABLE}\".collection_id "
        f"AND {_project_access(write=False)})"
    )
    write_scope = (
        "EXISTS (SELECT 1 FROM collections integrity_execution_collection "  # noqa: S608
        f"WHERE integrity_execution_collection.tenant_id = \"{_TABLE}\".tenant_id "
        f"AND integrity_execution_collection.id = \"{_TABLE}\".collection_id "
        f"AND {_project_access(write=True)})"
    )
    for operation in ("select", "insert", "update", "delete"):
        op.execute(f'DROP POLICY IF EXISTS "{_TABLE}_{operation}" ON "{_TABLE}"')
    op.execute(
        f'CREATE POLICY "{_TABLE}_select" ON "{_TABLE}" '
        f"FOR SELECT USING ({tenant_scope} AND {read_scope})"
    )
    op.execute(
        f'CREATE POLICY "{_TABLE}_insert" ON "{_TABLE}" '
        f"FOR INSERT WITH CHECK ({tenant_scope} AND {write_scope})"
    )
    op.execute(
        f'CREATE POLICY "{_TABLE}_update" ON "{_TABLE}" '
        f"FOR UPDATE USING ({tenant_scope} AND {write_scope}) "
        f"WITH CHECK ({tenant_scope} AND {write_scope})"
    )
    dispatch_scope = (
        "processing_job_id IS NOT NULL AND EXISTS ("  # noqa: S608
        "SELECT 1 FROM processing_jobs integrity_execution_job "
        f"WHERE integrity_execution_job.tenant_id = \"{_TABLE}\".tenant_id "
        f"AND integrity_execution_job.id = \"{_TABLE}\".processing_job_id))"
    )
    analysis_scope = (
        "analysis_task_id IS NOT NULL AND EXISTS ("  # noqa: S608
        "SELECT 1 FROM analysis_tasks integrity_execution_task "
        f"WHERE integrity_execution_task.tenant_id = \"{_TABLE}\".tenant_id "
        f"AND integrity_execution_task.id = \"{_TABLE}\".analysis_task_id))"
    )
    for role, scope in (
        ("akc_dispatch_worker", dispatch_scope),
        ("akc_analysis_worker", analysis_scope),
    ):
        op.execute(
            f'CREATE POLICY "{_TABLE}_{role}_select" ON "{_TABLE}" '
            f"FOR SELECT TO {role} USING ({scope})"
        )
        op.execute(
            f'CREATE POLICY "{_TABLE}_{role}_update" ON "{_TABLE}" '
            f"FOR UPDATE TO {role} USING ({scope}) WITH CHECK ({scope})"
        )
    op.execute(
        f"GRANT SELECT, UPDATE (status, result_code, result, started_at, completed_at, "
        f"updated_at) ON TABLE {_TABLE} TO akc_dispatch_worker, akc_analysis_worker"
    )


def upgrade() -> None:
    _create_table()
    _enable_rls()


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_table(_TABLE)
