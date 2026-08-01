"""Add the tenant-safe v4 collection control-plane vertical slice.

Revision ID: 0023_v4_collections
Revises: 0022_cdr_derivative_lineage
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from akc_api.models import (
    ArchitecturePlan,
    AssetRegistry,
    AuthorityFact,
    AuthorityMapping,
    BlueprintModule,
    Collection,
    CollectionEvent,
    CollectionFile,
    CollectionPreflight,
    CollectionRegion,
    CollectionRegionAttempt,
    CollectionSourceRoot,
    CollectionUploadSession,
    CostPredictionModel,
    DocumentCluster,
    EstimateRun,
    EstimateSample,
    FileContentHash,
    FileVersion,
    KnowledgeCompileRun,
    PackageFile,
    PackageManifest,
    PackageValidation,
    PageFingerprint,
    PreflightFeatureRecord,
    QuarantineItem,
    RouteAttempt,
    UploadFileSession,
    UploadPart,
    VerificationRecord,
)
from alembic import op
from sqlalchemy import inspect

revision = "0023_v4_collections"
down_revision = "0022_cdr_derivative_lineage"
branch_labels = None
depends_on = None

_COLLECTION_TABLES = (
    Collection.__table__,
    CollectionSourceRoot.__table__,
    CollectionFile.__table__,
    CollectionUploadSession.__table__,
    UploadFileSession.__table__,
    UploadPart.__table__,
    FileContentHash.__table__,
    FileVersion.__table__,
    CollectionPreflight.__table__,
    DocumentCluster.__table__,
    PageFingerprint.__table__,
    PreflightFeatureRecord.__table__,
    EstimateRun.__table__,
    EstimateSample.__table__,
    CostPredictionModel.__table__,
    CollectionRegion.__table__,
    CollectionRegionAttempt.__table__,
    RouteAttempt.__table__,
    QuarantineItem.__table__,
    VerificationRecord.__table__,
    AuthorityFact.__table__,
    AuthorityMapping.__table__,
    ArchitecturePlan.__table__,
    BlueprintModule.__table__,
    KnowledgeCompileRun.__table__,
    PackageManifest.__table__,
    PackageFile.__table__,
    PackageValidation.__table__,
    AssetRegistry.__table__,
    CollectionEvent.__table__,
)

_PAGE_STATUS_OLD = (
    "status IN ("
    "'UPLOADED','SECURITY_SCANNING','SECURITY_VERIFIED','PREFLIGHTING',"
    "'PREFLIGHTED','NATIVE_EXTRACTING','OCR_QUEUED','OCR_RUNNING',"
    "'NORMALIZING','VALIDATING','COMPLETED','NEEDS_REVIEW',"
    "'RETRY_SCHEDULED','FAILED')"
)
_PAGE_STATUS_NEW = (
    "status IN ("
    "'UPLOADED','SECURITY_SCANNING','SECURITY_VERIFIED','PREFLIGHTING',"
    "'PREFLIGHTED','NATIVE_EXTRACTING','OCR_QUEUED','OCR_RUNNING',"
    "'NORMALIZING','VALIDATING','COMPLETED','NEEDS_REVIEW',"
    "'UNRESOLVED','QUARANTINED','RETRY_SCHEDULED','FAILED')"
)
_PAGE_TERMINAL_OLD = "('COMPLETED','NEEDS_REVIEW','FAILED')"
_PAGE_TERMINAL_NEW = "('COMPLETED','NEEDS_REVIEW','UNRESOLVED','QUARANTINED','FAILED')"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _create_collection_tables() -> None:
    bind = op.get_bind()
    existing = _tables()
    for table in _COLLECTION_TABLES:
        if table.name not in existing:
            table.create(bind=bind)
            existing.add(table.name)


def _status_checks() -> list[dict[str, object]]:
    if "page_attempts" not in _tables():
        return []
    return [
        check
        for check in inspect(op.get_bind()).get_check_constraints("page_attempts")
        if "status" in str(check.get("sqltext", "")).casefold()
        and "needs_review" in str(check.get("sqltext", "")).casefold()
    ]


def _replace_page_attempt_status(*, include_autonomous_terminals: bool) -> None:
    if "page_attempts" not in _tables():
        return
    checks = _status_checks()
    target_has_new = include_autonomous_terminals
    if checks and all(
        ("unresolved" in str(check.get("sqltext", "")).casefold()) == target_has_new
        and ("quarantined" in str(check.get("sqltext", "")).casefold()) == target_has_new
        for check in checks
    ):
        return

    bind = op.get_bind()
    target = _PAGE_STATUS_NEW if include_autonomous_terminals else _PAGE_STATUS_OLD
    if not include_autonomous_terminals:
        incompatible = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM page_attempts WHERE status IN ('UNRESOLVED','QUARANTINED')"
            )
        ).scalar_one()
        if int(incompatible) > 0:
            raise RuntimeError(
                "cannot downgrade page-attempt status while autonomous terminal rows exist"
            )

    if bind.dialect.name == "sqlite":
        # Alembic does not reflect legacy unnamed SQLite CHECK constraints into
        # batch mode. Recreating the table therefore drops the old unnamed
        # status check while preserving every named/non-status constraint.
        with op.batch_alter_table(
            "page_attempts",
            recreate="always",
            naming_convention={"ck": "ck_%(table_name)s_%(column_0_name)s"},
        ) as batch:
            for check in checks:
                name = check.get("name")
                if name:
                    batch.drop_constraint(str(name), type_="check")
            batch.create_check_constraint("ck_page_attempts_status", target)
        return

    for check in checks:
        name = check.get("name")
        if name:
            op.drop_constraint(str(name), "page_attempts", type_="check")
    op.create_check_constraint("ck_page_attempts_status", "page_attempts", target)


def _replace_page_attempt_active_index(*, include_autonomous_terminals: bool) -> None:
    if "page_attempts" not in _tables():
        return
    names = {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes("page_attempts")
        if index.get("name")
    }
    if "page_attempts_one_active_idx" in names:
        op.drop_index("page_attempts_one_active_idx", table_name="page_attempts")
    terminal = _PAGE_TERMINAL_NEW if include_autonomous_terminals else _PAGE_TERMINAL_OLD
    predicate = sa.text(f"status NOT IN {terminal}")
    op.create_index(
        "page_attempts_one_active_idx",
        "page_attempts",
        ["page_id"],
        unique=True,
        postgresql_where=predicate,
        sqlite_where=predicate,
    )


def _replace_page_attempt_guard(*, include_autonomous_terminals: bool) -> None:
    if op.get_bind().dialect.name != "postgresql" or "page_attempts" not in _tables():
        return
    terminal = _PAGE_TERMINAL_NEW if include_autonomous_terminals else _PAGE_TERMINAL_OLD
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION akc_page_attempt_immutable_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status IN {terminal} THEN
                RAISE EXCEPTION 'terminal page attempt is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.page_id IS DISTINCT FROM OLD.page_id
               OR NEW.job_id IS DISTINCT FROM OLD.job_id
               OR NEW.analysis_task_id IS DISTINCT FROM OLD.analysis_task_id
               OR NEW.attempt_number IS DISTINCT FROM OLD.attempt_number
               OR NEW.trigger IS DISTINCT FROM OLD.trigger
               OR NEW.route IS DISTINCT FROM OLD.route
               OR NEW.route_profile IS DISTINCT FROM OLD.route_profile
               OR NEW.route_policy_version IS DISTINCT FROM OLD.route_policy_version
               OR NEW.max_attempts IS DISTINCT FROM OLD.max_attempts
            THEN
                RAISE EXCEPTION 'page attempt identity and routing are immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )


def _tenant_setting() -> str:
    return "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _user_setting() -> str:
    return "NULLIF(current_setting('app.user_id', true), '')::uuid"


def _tenant_role(*roles: str) -> str:
    values = ", ".join(f"'{role}'" for role in roles)
    return (
        "EXISTS ("  # noqa: S608 - roles come only from fixed migration tuples.
        "SELECT 1 FROM memberships collection_tenant_membership "
        f"WHERE collection_tenant_membership.tenant_id = {_tenant_setting()} "
        f"AND collection_tenant_membership.user_id = {_user_setting()} "
        f"AND collection_tenant_membership.role IN ({values})"
        ")"
    )


def _project_access(project_expression: str, *, write: bool) -> str:
    tenant_roles = ("editor",) if write else ("editor", "reviewer", "viewer")
    project_roles = tenant_roles
    tenant_values = ", ".join(f"'{role}'" for role in tenant_roles)
    project_values = ", ".join(f"'{role}'" for role in project_roles)
    explicit = (
        "EXISTS ("  # noqa: S608 - expressions are fixed migration identifiers.
        "SELECT 1 FROM project_memberships collection_project_membership "
        "JOIN memberships collection_access_membership "
        "ON collection_access_membership.tenant_id = "
        "collection_project_membership.tenant_id "
        "AND collection_access_membership.user_id = "
        "collection_project_membership.user_id "
        "WHERE collection_project_membership.tenant_id = "
        f"{_tenant_setting()} "
        "AND collection_project_membership.user_id = "
        f"{_user_setting()} "
        "AND collection_project_membership.project_id = "
        f"{project_expression} "
        f"AND collection_access_membership.role IN ({tenant_values}) "
        f"AND collection_project_membership.role IN ({project_values})"
        ")"
    )
    return f"({_tenant_role('owner', 'admin')} OR {explicit})"


def _collection_scope(table: str, *, write: bool) -> str:
    if table == "collections":
        return _project_access('"collections".project_id', write=write)
    access = _project_access("collection_scope.project_id", write=write)
    return (
        "EXISTS ("  # noqa: S608 - table is drawn only from _COLLECTION_TABLES.
        "SELECT 1 FROM collections collection_scope "
        f'WHERE collection_scope.tenant_id = "{table}".tenant_id '
        f'AND collection_scope.id = "{table}".collection_id '
        f"AND {access}"
        ")"
    )


def _drop_collection_policies(table: str) -> None:
    for operation in ("select", "insert", "update", "delete"):
        op.execute(f'DROP POLICY IF EXISTS "{table}_collection_{operation}" ON "{table}"')


def _enable_collection_policies() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_obj in _COLLECTION_TABLES:
        table = table_obj.name
        tenant = f'"{table}".tenant_id = {_tenant_setting()}'
        read = _collection_scope(table, write=False)
        write = _collection_scope(table, write=True)
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        _drop_collection_policies(table)
        op.execute(
            f'CREATE POLICY "{table}_collection_select" ON "{table}" '
            "AS RESTRICTIVE FOR SELECT "
            f"USING ({tenant} AND {read})"
        )
        op.execute(
            f'CREATE POLICY "{table}_collection_insert" ON "{table}" '
            "AS RESTRICTIVE FOR INSERT "
            f"WITH CHECK ({tenant} AND {write})"
        )
        if table != "collection_events":
            op.execute(
                f'CREATE POLICY "{table}_collection_update" ON "{table}" '
                "AS RESTRICTIVE FOR UPDATE "
                f"USING ({tenant} AND {write}) WITH CHECK ({tenant} AND {write})"
            )
            op.execute(
                f'CREATE POLICY "{table}_collection_delete" ON "{table}" '
                "AS RESTRICTIVE FOR DELETE "
                f"USING ({tenant} AND {write})"
            )
    op.execute("REVOKE UPDATE, DELETE ON collection_events FROM PUBLIC")


def upgrade() -> None:
    _replace_page_attempt_status(include_autonomous_terminals=True)
    _replace_page_attempt_active_index(include_autonomous_terminals=True)
    _replace_page_attempt_guard(include_autonomous_terminals=True)
    _create_collection_tables()
    _enable_collection_policies()


def downgrade() -> None:
    bind = op.get_bind()
    existing = _tables()
    if bind.dialect.name == "postgresql":
        for table in reversed(_COLLECTION_TABLES):
            if table.name in existing:
                _drop_collection_policies(table.name)
    for table in reversed(_COLLECTION_TABLES):
        if table.name in existing:
            table.drop(bind=bind)
    _replace_page_attempt_status(include_autonomous_terminals=False)
    _replace_page_attempt_active_index(include_autonomous_terminals=False)
    _replace_page_attempt_guard(include_autonomous_terminals=False)
