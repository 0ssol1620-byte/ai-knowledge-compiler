"""Add immutable customer decisions for collection integrity findings.

Revision ID: 0028_collection_integrity_decisions
Revises: 0027_finalize_collection_metadata_encryption
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0028_collection_integrity_decisions"
down_revision = "0027_finalize_collection_metadata_encryption"
branch_labels = None
depends_on = None

_TABLE = "collection_integrity_decisions"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _tenant_setting() -> str:
    return "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _user_setting() -> str:
    return "NULLIF(current_setting('app.user_id', true), '')::uuid"


def _tenant_role(*roles: str) -> str:
    values = ", ".join(f"'{role}'" for role in roles)
    return (
        "EXISTS ("  # noqa: S608 - fixed migration-owned identifiers and roles.
        "SELECT 1 FROM memberships integrity_tenant_membership "
        f"WHERE integrity_tenant_membership.tenant_id = {_tenant_setting()} "
        f"AND integrity_tenant_membership.user_id = {_user_setting()} "
        f"AND integrity_tenant_membership.role IN ({values})"
        ")"
    )


def _project_access(*, write: bool) -> str:
    roles = ("editor",) if write else ("editor", "reviewer", "viewer")
    values = ", ".join(f"'{role}'" for role in roles)
    explicit = (
        "EXISTS ("  # noqa: S608 - fixed migration-owned identifiers and roles.
        "SELECT 1 FROM project_memberships integrity_project_membership "
        "JOIN memberships integrity_access_membership "
        "ON integrity_access_membership.tenant_id = integrity_project_membership.tenant_id "
        "AND integrity_access_membership.user_id = integrity_project_membership.user_id "
        f"WHERE integrity_project_membership.tenant_id = {_tenant_setting()} "
        f"AND integrity_project_membership.user_id = {_user_setting()} "
        "AND integrity_project_membership.project_id = integrity_collection.project_id "
        f"AND integrity_access_membership.role IN ({values}) "
        f"AND integrity_project_membership.role IN ({values})"
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
        sa.Column("quarantine_item_id", sa.Uuid(), nullable=True),
        sa.Column("review_item_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("evidence_reference", sa.JSON(), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=False),
        sa.Column("resulting_status", sa.String(length=32), nullable=False),
        sa.Column(
            "override_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "collection_id"],
            ["collections.tenant_id", "collections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.CheckConstraint(
            "(quarantine_item_id IS NOT NULL AND review_item_id IS NULL) OR "
            "(quarantine_item_id IS NULL AND review_item_id IS NOT NULL)",
            name="ck_collection_integrity_decisions_target",
        ),
        sa.CheckConstraint(
            "action IN ('keep_quarantined','exclude','retry_new_engine',"
            "'provide_password','correct_source','override')",
            name="ck_collection_integrity_decisions_action",
        ),
        sa.CheckConstraint(
            "length(reason_code) BETWEEN 3 AND 80",
            name="ck_collection_integrity_decisions_reason",
        ),
        sa.CheckConstraint(
            "length(request_sha256) = 64",
            name="ck_collection_integrity_decisions_request_sha",
        ),
        sa.CheckConstraint(
            "(action = 'override' AND override_applied) OR "
            "(action <> 'override' AND NOT override_applied)",
            name="ck_collection_integrity_decisions_override",
        ),
    )
    op.create_index(
        "collection_integrity_decisions_collection_idx",
        _TABLE,
        ["collection_id", "created_at", "id"],
    )
    op.create_index(
        "collection_integrity_decisions_quarantine_idx",
        _TABLE,
        ["tenant_id", "quarantine_item_id", "created_at"],
    )
    op.create_index(
        "collection_integrity_decisions_review_idx",
        _TABLE,
        ["tenant_id", "review_item_id", "created_at"],
    )


def _enable_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY')
    tenant_scope = f'"{_TABLE}".tenant_id = {_tenant_setting()}'
    read_scope = (
        "EXISTS (SELECT 1 FROM collections integrity_collection "  # noqa: S608
        f"WHERE integrity_collection.tenant_id = \"{_TABLE}\".tenant_id "
        f"AND integrity_collection.id = \"{_TABLE}\".collection_id "
        f"AND {_project_access(write=False)})"
    )
    write_scope = (
        "EXISTS (SELECT 1 FROM collections integrity_collection "  # noqa: S608
        f"WHERE integrity_collection.tenant_id = \"{_TABLE}\".tenant_id "
        f"AND integrity_collection.id = \"{_TABLE}\".collection_id "
        f"AND {_project_access(write=True)})"
    )
    target_scope = (
        "((quarantine_item_id IS NOT NULL AND EXISTS ("  # noqa: S608
        "SELECT 1 FROM quarantine_items integrity_quarantine "
        f"WHERE integrity_quarantine.tenant_id = \"{_TABLE}\".tenant_id "
        f"AND integrity_quarantine.id = \"{_TABLE}\".quarantine_item_id "
        f"AND integrity_quarantine.collection_id = \"{_TABLE}\".collection_id)) "
        "OR (review_item_id IS NOT NULL AND EXISTS ("
        "SELECT 1 FROM review_items integrity_review "
        "JOIN documents integrity_document "
        "ON integrity_document.tenant_id = integrity_review.tenant_id "
        "AND integrity_document.id = integrity_review.document_id "
        "JOIN collection_files integrity_file "
        "ON integrity_file.tenant_id = integrity_document.tenant_id "
        "AND integrity_file.source_file_id = integrity_document.source_file_id "
        "JOIN collections integrity_target_collection "
        "ON integrity_target_collection.tenant_id = integrity_file.tenant_id "
        "AND integrity_target_collection.id = integrity_file.collection_id "
        f"WHERE integrity_review.tenant_id = \"{_TABLE}\".tenant_id "
        f"AND integrity_review.id = \"{_TABLE}\".review_item_id "
        f"AND integrity_file.collection_id = \"{_TABLE}\".collection_id "
        "AND integrity_review.project_id = integrity_target_collection.project_id "
        "AND integrity_document.project_id = integrity_target_collection.project_id)))"
    )
    for operation in ("select", "insert", "update", "delete"):
        op.execute(
            f'DROP POLICY IF EXISTS "{_TABLE}_{operation}" ON "{_TABLE}"'
        )
    op.execute(
        f'CREATE POLICY "{_TABLE}_select" ON "{_TABLE}" '
        f"FOR SELECT USING ({tenant_scope} AND {read_scope})"
    )
    op.execute(
        f'CREATE POLICY "{_TABLE}_insert" ON "{_TABLE}" '
        "FOR INSERT WITH CHECK ("
        f"{tenant_scope} AND actor_id = {_user_setting()} "
        f"AND {write_scope} AND {target_scope})"
    )
    # Decisions are append-only. FORCE RLS plus the deliberate absence of
    # UPDATE and DELETE policies makes mutation fail closed for the API role.


def upgrade() -> None:
    _create_table()
    _enable_rls()


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_table(_TABLE)
