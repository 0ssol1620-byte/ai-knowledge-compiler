"""Bind collection estimates, processing jobs, probe receipts, and event jobs.

Revision ID: 0025_collection_processing_runtime
Revises: 0024_production_hybrid_retrieval
Create Date: 2026-08-01
"""

from __future__ import annotations

from typing import Any, cast

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0025_collection_processing_runtime"
down_revision = "0024_production_hybrid_retrieval"
branch_labels = None
depends_on = None

_ZERO_SHA = "0" * 64
_DISPATCH_ROLE = "akc_dispatch_worker"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _create_binding_table() -> None:
    if "collection_processing_task_bindings" in _tables():
        return
    op.create_table(
        "collection_processing_task_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("processing_job_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_task_id", sa.Uuid(), nullable=False),
        sa.Column("collection_file_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("billing_disposition", sa.String(length=24), nullable=False),
        sa.Column("billing_owner_job_id", sa.Uuid(), nullable=True),
        sa.Column("billing_basis_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "collection_id"],
            ["collections.tenant_id", "collections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "processing_job_id"],
            ["processing_jobs.tenant_id", "processing_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "billing_owner_job_id"],
            ["processing_jobs.tenant_id", "processing_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "analysis_task_id"],
            ["analysis_tasks.tenant_id", "analysis_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "collection_id", "collection_file_id"],
            [
                "collection_files.tenant_id",
                "collection_files.collection_id",
                "collection_files.id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint(
            "processing_job_id",
            "analysis_task_id",
            name="uq_collection_processing_job_task",
        ),
        sa.CheckConstraint(
            "status IN ('active','paused','settled','detached')",
            name="ck_collection_processing_task_binding_status",
        ),
        sa.CheckConstraint(
            "billing_disposition IN ('new_billable','reuse_unbillable')",
            name="ck_collection_processing_task_binding_billing",
        ),
        sa.CheckConstraint(
            "length(billing_basis_sha256) = 64",
            name="ck_collection_processing_task_binding_basis_sha",
        ),
    )
    op.create_index(
        "collection_processing_task_lookup_idx",
        "collection_processing_task_bindings",
        ["tenant_id", "analysis_task_id", "status"],
    )
    op.create_index(
        "collection_processing_one_billing_owner_idx",
        "collection_processing_task_bindings",
        ["tenant_id", "analysis_task_id", "billing_basis_sha256"],
        unique=True,
        postgresql_where=sa.text("billing_disposition = 'new_billable'"),
        sqlite_where=sa.text("billing_disposition = 'new_billable'"),
    )


def _columns(table: str) -> dict[str, dict[str, Any]]:
    return {
        str(column["name"]): cast(dict[str, Any], column)
        for column in inspect(op.get_bind()).get_columns(table)
    }


def _constraint_names(table: str, kind: str) -> set[str]:
    inspector = inspect(op.get_bind())
    rows = (
        inspector.get_foreign_keys(table)
        if kind == "foreignkey"
        else inspector.get_check_constraints(table)
    )
    return {str(row["name"]) for row in rows if row.get("name")}


def _index_names(table: str) -> set[str]:
    return {
        str(row["name"]) for row in inspect(op.get_bind()).get_indexes(table) if row.get("name")
    }


def _has_foreign_key(
    table: str,
    *,
    constrained_columns: tuple[str, ...],
    referred_table: str,
) -> bool:
    return any(
        tuple(row.get("constrained_columns") or ()) == constrained_columns
        and row.get("referred_table") == referred_table
        for row in inspect(op.get_bind()).get_foreign_keys(table)
    )


def _add_columns() -> None:
    if "processing_job_id" not in _columns("architecture_plans"):
        op.add_column(
            "architecture_plans",
            sa.Column("processing_job_id", sa.Uuid(), nullable=True),
        )
    if "job_id" not in _columns("collection_events"):
        op.add_column(
            "collection_events",
            sa.Column("job_id", sa.Uuid(), nullable=True),
        )
    if "estimate_sha256" not in _columns("estimate_runs"):
        op.add_column(
            "estimate_runs",
            sa.Column(
                "estimate_sha256",
                sa.String(length=64),
                nullable=False,
                server_default=_ZERO_SHA,
            ),
        )

    sample_columns = _columns("estimate_samples")
    additions = (
        sa.Column(
            "probe_revision",
            sa.String(length=120),
            nullable=False,
            server_default="legacy-unattested-v0",
        ),
        sa.Column(
            "probe_artifact_sha256",
            sa.String(length=64),
            nullable=False,
            server_default=_ZERO_SHA,
        ),
        sa.Column(
            "attestation_sha256",
            sa.String(length=64),
            nullable=False,
            server_default=_ZERO_SHA,
        ),
        sa.Column(
            "attestation",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "attestation_key_id",
            sa.String(length=160),
            nullable=False,
            server_default="legacy-unverified",
        ),
        sa.Column(
            "attestation_signature",
            sa.String(length=4096),
            nullable=False,
            server_default="legacy-unverified",
        ),
    )
    for column in additions:
        if column.name not in sample_columns:
            op.add_column("estimate_samples", column)
    op.execute(
        "UPDATE estimate_samples SET runtime_seconds = 0.000001 "
        "WHERE runtime_seconds IS NULL OR runtime_seconds <= 0"
    )


def _add_constraints_and_indexes() -> None:
    dialect = op.get_bind().dialect.name
    architecture_has_job_fk = _has_foreign_key(
        "architecture_plans",
        constrained_columns=("tenant_id", "processing_job_id"),
        referred_table="processing_jobs",
    )
    event_has_job_fk = _has_foreign_key(
        "collection_events",
        constrained_columns=("tenant_id", "job_id"),
        referred_table="processing_jobs",
    )
    estimate_checks = _constraint_names("estimate_runs", "check")
    sample_checks = _constraint_names("estimate_samples", "check")

    context = op.batch_alter_table if dialect == "sqlite" else None
    if dialect == "sqlite":
        assert context is not None
        with context("architecture_plans") as batch:
            if not architecture_has_job_fk:
                batch.create_foreign_key(
                    "fk_architecture_plans_processing_job",
                    "processing_jobs",
                    ["tenant_id", "processing_job_id"],
                    ["tenant_id", "id"],
                    ondelete="RESTRICT",
                )
        with context("collection_events") as batch:
            if not event_has_job_fk:
                batch.create_foreign_key(
                    "fk_collection_events_processing_job",
                    "processing_jobs",
                    ["tenant_id", "job_id"],
                    ["tenant_id", "id"],
                    ondelete="SET NULL",
                )
        with context("estimate_runs") as batch:
            if "ck_estimate_runs_estimate_sha" not in estimate_checks:
                batch.create_check_constraint(
                    "ck_estimate_runs_estimate_sha", "length(estimate_sha256) = 64"
                )
        with context("estimate_samples") as batch:
            batch.alter_column(
                "runtime_seconds",
                existing_type=sa.Numeric(12, 3),
                type_=sa.Numeric(12, 6),
                nullable=False,
            )
            if "ck_estimate_samples_attestation_hashes" not in sample_checks:
                batch.create_check_constraint(
                    "ck_estimate_samples_attestation_hashes",
                    "length(probe_artifact_sha256) = 64 AND length(attestation_sha256) = 64",
                )
            if "ck_estimate_samples_runtime" not in sample_checks:
                batch.create_check_constraint("ck_estimate_samples_runtime", "runtime_seconds > 0")
    else:
        if not architecture_has_job_fk:
            op.create_foreign_key(
                "fk_architecture_plans_processing_job",
                "architecture_plans",
                "processing_jobs",
                ["tenant_id", "processing_job_id"],
                ["tenant_id", "id"],
                ondelete="RESTRICT",
            )
        if not event_has_job_fk:
            op.create_foreign_key(
                "fk_collection_events_processing_job",
                "collection_events",
                "processing_jobs",
                ["tenant_id", "job_id"],
                ["tenant_id", "id"],
                ondelete="SET NULL",
            )
        if "ck_estimate_runs_estimate_sha" not in estimate_checks:
            op.create_check_constraint(
                "ck_estimate_runs_estimate_sha",
                "estimate_runs",
                "length(estimate_sha256) = 64",
            )
        op.alter_column(
            "estimate_samples",
            "runtime_seconds",
            existing_type=sa.Numeric(12, 3),
            type_=sa.Numeric(12, 6),
            nullable=False,
        )
        if "ck_estimate_samples_attestation_hashes" not in sample_checks:
            op.create_check_constraint(
                "ck_estimate_samples_attestation_hashes",
                "estimate_samples",
                "length(probe_artifact_sha256) = 64 AND length(attestation_sha256) = 64",
            )
        if "ck_estimate_samples_runtime" not in sample_checks:
            op.create_check_constraint(
                "ck_estimate_samples_runtime",
                "estimate_samples",
                "runtime_seconds > 0",
            )

    if "collection_events_job_idx" not in _index_names("collection_events"):
        op.create_index(
            "collection_events_job_idx",
            "collection_events",
            ["tenant_id", "job_id", "sequence"],
        )
    binding_indexes = _index_names("collection_processing_task_bindings")
    if "collection_processing_one_billing_owner_idx" not in binding_indexes:
        op.create_index(
            "collection_processing_one_billing_owner_idx",
            "collection_processing_task_bindings",
            ["tenant_id", "analysis_task_id", "billing_basis_sha256"],
            unique=True,
            postgresql_where=sa.text("billing_disposition = 'new_billable'"),
            sqlite_where=sa.text("billing_disposition = 'new_billable'"),
        )
    outbox_indexes = _index_names("outbox_events")
    if "outbox_collection_finalizer_pending_idx" not in outbox_indexes:
        op.create_index(
            "outbox_collection_finalizer_pending_idx",
            "outbox_events",
            ["available_at", "created_at", "id"],
            postgresql_where=sa.text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type = 'collection.semantic.compile.requested.v1'"
            ),
            sqlite_where=sa.text(
                "published_at IS NULL AND dead_lettered_at IS NULL "
                "AND event_type = 'collection.semantic.compile.requested.v1'"
            ),
        )


def _replace_page_links() -> None:
    for table in ("page_fingerprints", "preflight_feature_records", "estimate_samples"):
        columns = _columns(table)
        page_foreign_key: dict[str, Any] | None = next(
            (
                cast(dict[str, Any], row)
                for row in inspect(op.get_bind()).get_foreign_keys(table)
                if row.get("referred_table") == "pages"
                and list(row.get("constrained_columns") or []) == ["tenant_id", "page_id"]
            ),
            None,
        )
        ondelete = str(((page_foreign_key or {}).get("options") or {}).get("ondelete", "")).upper()
        needs_nullable = not bool(columns["page_id"].get("nullable"))
        needs_set_null = page_foreign_key is not None and ondelete != "SET NULL"
        if needs_nullable or needs_set_null:
            if op.get_bind().dialect.name == "sqlite":
                naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
                reflected_name = (
                    str(page_foreign_key.get("name"))
                    if page_foreign_key is not None and page_foreign_key.get("name")
                    else f"fk_{table}_tenant_id_pages"
                )
                with op.batch_alter_table(
                    table, recreate="always", naming_convention=naming
                ) as batch:
                    batch.alter_column("page_id", existing_type=sa.Uuid(), nullable=True)
                    if needs_set_null:
                        batch.drop_constraint(reflected_name, type_="foreignkey")
                        batch.create_foreign_key(
                            f"fk_{table}_page_set_null",
                            "pages",
                            ["tenant_id", "page_id"],
                            ["tenant_id", "id"],
                            ondelete="SET NULL",
                        )
            else:
                if needs_nullable:
                    op.alter_column(table, "page_id", existing_type=sa.Uuid(), nullable=True)
                if needs_set_null:
                    foreign_key_name = (page_foreign_key or {}).get("name")
                    if not foreign_key_name:
                        raise RuntimeError(f"cannot replace unnamed PostgreSQL page FK: {table}")
                    op.drop_constraint(str(foreign_key_name), table, type_="foreignkey")
                    op.create_foreign_key(
                        f"fk_{table}_page_set_null",
                        table,
                        "pages",
                        ["tenant_id", "page_id"],
                        ["tenant_id", "id"],
                        ondelete="SET NULL",
                    )


def _tenant_setting() -> str:
    return "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _user_setting() -> str:
    return "NULLIF(current_setting('app.user_id', true), '')::uuid"


def _tenant_role(*roles: str) -> str:
    values = ", ".join(f"'{role}'" for role in roles)
    return (
        "EXISTS ("  # noqa: S608 - roles are fixed migration-owned literals.
        "SELECT 1 FROM memberships binding_tenant_membership "
        f"WHERE binding_tenant_membership.tenant_id = {_tenant_setting()} "
        f"AND binding_tenant_membership.user_id = {_user_setting()} "
        f"AND binding_tenant_membership.role IN ({values})"
        ")"
    )


def _project_access(*, write: bool) -> str:
    roles = ("editor",) if write else ("editor", "reviewer", "viewer")
    values = ", ".join(f"'{role}'" for role in roles)
    explicit = (
        "EXISTS ("  # noqa: S608 - identifiers and roles are fixed here.
        "SELECT 1 FROM project_memberships binding_project_membership "
        "JOIN memberships binding_access_membership "
        "ON binding_access_membership.tenant_id = binding_project_membership.tenant_id "
        "AND binding_access_membership.user_id = binding_project_membership.user_id "
        f"WHERE binding_project_membership.tenant_id = {_tenant_setting()} "
        f"AND binding_project_membership.user_id = {_user_setting()} "
        "AND binding_project_membership.project_id = collection_scope.project_id "
        f"AND binding_access_membership.role IN ({values}) "
        f"AND binding_project_membership.role IN ({values})"
        ")"
    )
    return f"({_tenant_role('owner', 'admin')} OR {explicit})"


def _refresh_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in (
        "architecture_plans",
        "estimate_runs",
        "estimate_samples",
        "page_fingerprints",
        "preflight_feature_records",
        "collection_events",
        "collection_processing_task_bindings",
    ):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    tenant = f'"collection_processing_task_bindings".tenant_id = {_tenant_setting()}'
    read_scope = (
        "EXISTS (SELECT 1 FROM collections collection_scope "  # noqa: S608
        "WHERE collection_scope.tenant_id = "
        '"collection_processing_task_bindings".tenant_id '
        "AND collection_scope.id = "
        '"collection_processing_task_bindings".collection_id '
        f"AND {_project_access(write=False)})"
    )
    write_scope = (
        "EXISTS (SELECT 1 FROM collections collection_scope "  # noqa: S608
        "WHERE collection_scope.tenant_id = "
        '"collection_processing_task_bindings".tenant_id '
        "AND collection_scope.id = "
        '"collection_processing_task_bindings".collection_id '
        f"AND {_project_access(write=True)})"
    )
    for operation in ("select", "insert", "update", "delete"):
        op.execute(
            'DROP POLICY IF EXISTS "collection_processing_task_bindings_collection_'
            f'{operation}" ON "collection_processing_task_bindings"'
        )
    op.execute(
        'CREATE POLICY "collection_processing_task_bindings_collection_select" '
        'ON "collection_processing_task_bindings" AS RESTRICTIVE FOR SELECT '
        f"USING ({tenant} AND {read_scope})"
    )
    op.execute(
        'CREATE POLICY "collection_processing_task_bindings_collection_insert" '
        'ON "collection_processing_task_bindings" AS RESTRICTIVE FOR INSERT '
        f"WITH CHECK ({tenant} AND {write_scope})"
    )
    op.execute(
        'CREATE POLICY "collection_processing_task_bindings_collection_update" '
        'ON "collection_processing_task_bindings" AS RESTRICTIVE FOR UPDATE '
        f"USING ({tenant} AND {write_scope}) WITH CHECK ({tenant} AND {write_scope})"
    )
    op.execute(
        'CREATE POLICY "collection_processing_task_bindings_collection_delete" '
        'ON "collection_processing_task_bindings" AS RESTRICTIVE FOR DELETE '
        f"USING ({tenant} AND {write_scope})"
    )
    op.execute("REVOKE UPDATE, DELETE ON collection_events FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT ON TABLE collection_events TO {_DISPATCH_ROLE}")
    op.execute(f"GRANT SELECT ON TABLE collections TO {_DISPATCH_ROLE}")
    op.execute(
        "GRANT UPDATE (status, status_reason, event_sequence, updated_at) "
        f"ON TABLE collections TO {_DISPATCH_ROLE}"
    )


def upgrade() -> None:
    _create_binding_table()
    _add_columns()
    _replace_page_links()
    _add_constraints_and_indexes()
    _refresh_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM page_fingerprints WHERE page_id IS NULL) "
            "OR EXISTS (SELECT 1 FROM preflight_feature_records WHERE page_id IS NULL) "
            "OR EXISTS (SELECT 1 FROM estimate_samples WHERE page_id IS NULL) THEN "
            "RAISE EXCEPTION 'cannot downgrade while detached preflight page evidence exists'; "
            "END IF; END $$;"
        )
    # Both indexes are introduced by this revision.  The finalizer predicate
    # references ``outbox_events.dead_lettered_at`` (owned by 0002), so leaving
    # it behind would make SQLite reject 0002's later column downgrade.
    if "outbox_collection_finalizer_pending_idx" in _index_names("outbox_events"):
        op.drop_index(
            "outbox_collection_finalizer_pending_idx",
            table_name="outbox_events",
        )
    if "collection_events_job_idx" in _index_names("collection_events"):
        op.drop_index("collection_events_job_idx", table_name="collection_events")
    for table, constraint, kind in (
        ("collection_events", "fk_collection_events_processing_job", "foreignkey"),
        ("architecture_plans", "fk_architecture_plans_processing_job", "foreignkey"),
        ("estimate_runs", "ck_estimate_runs_estimate_sha", "check"),
        ("estimate_samples", "ck_estimate_samples_attestation_hashes", "check"),
    ):
        if constraint not in _constraint_names(table, kind):
            continue
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(table) as batch:
                batch.drop_constraint(constraint, type_=kind)
        else:
            op.drop_constraint(constraint, table, type_=kind)
    sample_columns = tuple(
        column
        for column in (
            "attestation_signature",
            "attestation_key_id",
            "attestation",
            "attestation_sha256",
            "probe_artifact_sha256",
            "probe_revision",
        )
        if column in _columns("estimate_samples")
    )
    if op.get_bind().dialect.name == "sqlite":
        # SQLite's native DROP COLUMN leaves reflected unnamed foreign keys in
        # the table definition. Force a batch rebuild so columns and their
        # dependent FKs disappear together without weakening other links.
        if sample_columns:
            with op.batch_alter_table("estimate_samples", recreate="always") as batch:
                for column in sample_columns:
                    batch.drop_column(column)
        if "estimate_sha256" in _columns("estimate_runs"):
            with op.batch_alter_table("estimate_runs", recreate="always") as batch:
                batch.drop_column("estimate_sha256")
        if "job_id" in _columns("collection_events"):
            with op.batch_alter_table("collection_events", recreate="always") as batch:
                batch.drop_column("job_id")
        if "processing_job_id" in _columns("architecture_plans"):
            with op.batch_alter_table("architecture_plans", recreate="always") as batch:
                batch.drop_column("processing_job_id")
    else:
        for column in sample_columns:
            op.drop_column("estimate_samples", column)
        if "estimate_sha256" in _columns("estimate_runs"):
            op.drop_column("estimate_runs", "estimate_sha256")
        if "job_id" in _columns("collection_events"):
            op.drop_column("collection_events", "job_id")
        if "processing_job_id" in _columns("architecture_plans"):
            op.drop_column("architecture_plans", "processing_job_id")
    if "collection_processing_task_bindings" in _tables():
        op.drop_table("collection_processing_task_bindings")
