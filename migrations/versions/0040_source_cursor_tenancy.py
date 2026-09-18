"""Give source cursor rows a tenant, a failure streak, and a retry plan.

The ``source_cursors`` table from 0039 was shaped for exactly one writer and
one reader: the adapter poll loop. The freshness dashboard turns those rows
into an operator-facing API, and three things were missing for that surface:

* **``tenant_id``** — a cursor row is a tenant's operational data like any
  other. Without ownership on the row, the dashboard endpoint could only show
  every connector to everybody. The column is NOT NULL because the table ships
  in the same unreleased build as its first writers: any row that predates
  tenancy would be unattributable, and inventing a default tenant would be
  worse than failing loudly.
* **``failure_streak`` / ``next_retry_at``** — consecutive poll failures and
  the projected next attempt. The dashboard must distinguish "fresh because
  healthy" from "fresh-looking because the poller gave up three hours ago";
  without a streak counter those two are indistinguishable.

Row-level security follows the tenant-scoped tables (RESTRICTIVE policies on
``app.tenant_id``), with the control plane granted the writes its pollers need
and the human plane read-only access. Like 0038/0039 this migration is
PostgreSQL-only; the SQLite development database is created from the ORM
models, which already carry the full shape.

Revision ID: 0040_source_cursor_tenancy
Revises: 0039_source_adapter_cursors
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_source_cursor_tenancy"
down_revision = "0039_source_adapter_cursors"
branch_labels = None
depends_on = None

TABLE = "source_cursors"

_API_PLANE_ROLE = "akc_api_plane"
_CONTROL_PLANE_ROLE = "akc_scheduler"


def _tenant_setting() -> str:
    return "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _add_columns() -> None:
    columns = {
        name: name in _column_names()
        for name in ("tenant_id", "failure_streak", "next_retry_at")
    }
    if not columns["tenant_id"]:
        op.add_column(
            TABLE,
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
        )
    if not columns["failure_streak"]:
        op.add_column(
            TABLE,
            sa.Column(
                "failure_streak",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if not columns["next_retry_at"]:
        op.add_column(
            TABLE,
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        )


def _column_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(TABLE)}


def _enable_rls() -> None:
    op.execute(f'ALTER TABLE "{TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{TABLE}" FORCE ROW LEVEL SECURITY')
    tenant_scope = f'"{TABLE}".tenant_id = {_tenant_setting()}'
    for operation in ("select", "insert", "update", "delete"):
        op.execute(f'DROP POLICY IF EXISTS "{TABLE}_tenant_{operation}" ON "{TABLE}"')
        op.execute(
            f'CREATE POLICY "{TABLE}_tenant_{operation}" ON "{TABLE}" '
            f"AS RESTRICTIVE FOR {operation.upper()} "
            + (
                f"USING ({tenant_scope}) WITH CHECK ({tenant_scope})"
                if operation == "update"
                else f"WITH CHECK ({tenant_scope})"
                if operation == "insert"
                else f"USING ({tenant_scope})"
            )
        )


def _grant_planes() -> None:
    """Human plane reads the dashboard; control plane polls write cursors."""

    def _grant_if_role_exists(role: str, privileges: str) -> None:
        # Every identifier below is migration-owned and static; no statement
        # text originates from external input.
        op.execute(
            "DO $$ BEGIN\n"  # noqa: S608 - fixed migration-owned identifiers, no external input.
            "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '" + role + "') THEN\n"
            f"EXECUTE 'GRANT {privileges} ON TABLE \"{TABLE}\" TO {role}';\n"
            "END IF;\n"
            "END $$;"
        )

    _grant_if_role_exists(_API_PLANE_ROLE, "SELECT")
    _grant_if_role_exists(_CONTROL_PLANE_ROLE, "SELECT, INSERT, UPDATE")


def _existing_indexes() -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(TABLE)}


def upgrade() -> None:
    # The columns and the model's own tenant index apply on every dialect. The
    # docstring above assumed SQLite only ever gets this table from 0001's
    # ``create_all``, but 0039 creates it too -- on a downgrade/upgrade cycle
    # that left the SQLite shape one migration behind the ORM, which
    # ``alembic check`` reports as drift. Both steps are guarded, so on a
    # create_all-built database they are no-ops.
    _add_columns()
    if "ix_source_cursors_tenant_id" not in _existing_indexes():
        op.create_index("ix_source_cursors_tenant_id", TABLE, ["tenant_id"])
    if op.get_bind().dialect.name != "postgresql":
        return
    if "source_cursors_tenant_idx" not in _existing_indexes():
        op.create_index(
            "source_cursors_tenant_idx",
            TABLE,
            ["tenant_id", "updated_at"],
            unique=False,
        )
    _enable_rls()
    _grant_planes()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        _drop_tenancy_columns()
        return
    for operation in ("select", "insert", "update", "delete"):
        op.execute(f'DROP POLICY IF EXISTS "{TABLE}_tenant_{operation}" ON "{TABLE}"')
    op.execute(f'ALTER TABLE "{TABLE}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{TABLE}" DISABLE ROW LEVEL SECURITY')
    existing_indexes = {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes(TABLE)
    }
    if "source_cursors_tenant_idx" in existing_indexes:
        op.drop_index("source_cursors_tenant_idx", table_name=TABLE)
    _drop_tenancy_columns()


def _drop_tenancy_columns() -> None:
    if "ix_source_cursors_tenant_id" in _existing_indexes():
        op.drop_index("ix_source_cursors_tenant_id", table_name=TABLE)
    existing_columns = _column_names()
    for name in ("next_retry_at", "failure_streak", "tenant_id"):
        if name in existing_columns:
            op.drop_column(TABLE, name)
