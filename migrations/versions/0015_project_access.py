"""Add project-level membership and restrictive PostgreSQL ACL policies.

Revision ID: 0015_project_access
Revises: 0014_document_semantic_classification
Create Date: 2026-07-30
"""

from __future__ import annotations

from akc_api import models as _models  # noqa: F401
from akc_api.project_access_models import ProjectMembership
from alembic import op
from sqlalchemy import inspect

revision = "0015_project_access"
down_revision = "0014_document_semantic_classification"
branch_labels = None
depends_on = None

_DISPATCH_ROLE = "akc_dispatch_worker"
_CREATOR_FUNCTION = "akc_is_current_project_creator"

_DIRECT_PROJECT_TABLES: dict[str, str] = {
    "analysis_tasks": "project_id",
    "documents": "project_id",
    "entities": "project_id",
    "exports": "project_id",
    "gpu_provider_invocations": "project_id",
    "knowledge_notes": "project_id",
    "processing_jobs": "project_id",
    "relations": "project_id",
    "review_items": "project_id",
    "source_files": "project_id",
    "upload_sessions": "project_id",
    "url_fetch_tasks": "project_id",
}

_INDIRECT_PROJECT_SCOPES: dict[str, tuple[str, str]] = {
    "blocks": (
        "documents scope_document",
        'scope_document.tenant_id = "blocks".tenant_id '
        'AND scope_document.id = "blocks".document_id',
    ),
    "document_semantic_classifications": (
        "documents scope_document",
        "scope_document.tenant_id = "
        '"document_semantic_classifications".tenant_id '
        "AND scope_document.id = "
        '"document_semantic_classifications".document_id',
    ),
    "document_versions": (
        "documents scope_document",
        'scope_document.tenant_id = "document_versions".tenant_id '
        'AND scope_document.id = "document_versions".document_id',
    ),
    "pages": (
        "documents scope_document",
        'scope_document.tenant_id = "pages".tenant_id '
        'AND scope_document.id = "pages".document_id',
    ),
    "block_revisions": (
        "blocks scope_block "
        "JOIN documents scope_document "
        "ON scope_document.tenant_id = scope_block.tenant_id "
        "AND scope_document.id = scope_block.document_id",
        'scope_block.tenant_id = "block_revisions".tenant_id '
        'AND scope_block.id = "block_revisions".block_id',
    ),
    "page_assets": (
        "pages scope_page "
        "JOIN documents scope_document "
        "ON scope_document.tenant_id = scope_page.tenant_id "
        "AND scope_document.id = scope_page.document_id",
        'scope_page.tenant_id = "page_assets".tenant_id '
        'AND scope_page.id = "page_assets".page_id',
    ),
    "page_attempts": (
        "pages scope_page "
        "JOIN documents scope_document "
        "ON scope_document.tenant_id = scope_page.tenant_id "
        "AND scope_document.id = scope_page.document_id",
        'scope_page.tenant_id = "page_attempts".tenant_id '
        'AND scope_page.id = "page_attempts".page_id',
    ),
    "page_attempt_transition_events": (
        "page_attempts scope_attempt "
        "JOIN pages scope_page "
        "ON scope_page.tenant_id = scope_attempt.tenant_id "
        "AND scope_page.id = scope_attempt.page_id "
        "JOIN documents scope_document "
        "ON scope_document.tenant_id = scope_page.tenant_id "
        "AND scope_document.id = scope_page.document_id",
        'scope_attempt.tenant_id = "page_attempt_transition_events".tenant_id '
        'AND scope_attempt.id = "page_attempt_transition_events".attempt_id',
    ),
    "job_events": (
        "processing_jobs scope_job",
        'scope_job.tenant_id = "job_events".tenant_id '
        'AND scope_job.id = "job_events".job_id',
    ),
    "gpu_provider_attempts": (
        "gpu_provider_invocations scope_invocation",
        'scope_invocation.tenant_id = "gpu_provider_attempts".tenant_id '
        'AND scope_invocation.id = "gpu_provider_attempts".invocation_id',
    ),
    "gpu_invocation_events": (
        "gpu_provider_invocations scope_invocation",
        'scope_invocation.tenant_id = "gpu_invocation_events".tenant_id '
        'AND scope_invocation.id = "gpu_invocation_events".invocation_id',
    ),
}


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _tenant_setting() -> str:
    return "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _user_setting() -> str:
    return "NULLIF(current_setting('app.user_id', true), '')::uuid"


def _tenant_role(*roles: str) -> str:
    values = ", ".join(f"'{role}'" for role in roles)
    return (
        "EXISTS ("  # noqa: S608
        "SELECT 1 FROM memberships access_tenant_membership "
        f"WHERE access_tenant_membership.tenant_id = {_tenant_setting()} "
        f"AND access_tenant_membership.user_id = {_user_setting()} "
        f"AND access_tenant_membership.role IN ({values})"
        ")"
    )


def _admin_access() -> str:
    return _tenant_role("owner", "admin")


def _explicit_access(
    project_expression: str,
    *,
    tenant_roles: tuple[str, ...],
    project_roles: tuple[str, ...],
) -> str:
    tenant_values = ", ".join(f"'{role}'" for role in tenant_roles)
    project_values = ", ".join(f"'{role}'" for role in project_roles)
    return (
        "EXISTS ("  # noqa: S608
        "SELECT 1 "
        "FROM project_memberships access_project_membership "
        "JOIN memberships access_tenant_membership "
        "ON access_tenant_membership.tenant_id = "
        "access_project_membership.tenant_id "
        "AND access_tenant_membership.user_id = "
        "access_project_membership.user_id "
        "WHERE access_project_membership.tenant_id = "
        f"{_tenant_setting()} "
        "AND access_project_membership.user_id = "
        f"{_user_setting()} "
        "AND access_project_membership.project_id = "
        f"{project_expression} "
        f"AND access_tenant_membership.role IN ({tenant_values}) "
        f"AND access_project_membership.role IN ({project_values})"
        ")"
    )


def _read_access(project_expression: str) -> str:
    explicit = _explicit_access(
        project_expression,
        tenant_roles=("editor", "reviewer", "viewer"),
        project_roles=("editor", "reviewer", "viewer"),
    )
    return (
        f"({_admin_access()} OR "
        f"{explicit})"
    )


def _review_access(project_expression: str) -> str:
    explicit = _explicit_access(
        project_expression,
        tenant_roles=("editor", "reviewer"),
        project_roles=("editor", "reviewer"),
    )
    return (
        f"({_admin_access()} OR "
        f"{explicit})"
    )


def _write_access(project_expression: str) -> str:
    explicit = _explicit_access(
        project_expression,
        tenant_roles=("editor",),
        project_roles=("editor",),
    )
    return f"({_admin_access()} OR {explicit})"


def _creator_current_transaction(project_expression: str) -> str:
    return (
        f"{_CREATOR_FUNCTION}("
        f"{project_expression}, "
        f"{_user_setting()}, "
        f"{_tenant_setting()}"
        ")"
    )


def _scope_access(
    from_clause: str,
    correlation: str,
    access_builder: str,
) -> str:
    access = {
        "read": _read_access,
        "review": _review_access,
        "write": _write_access,
    }[access_builder]("scope_document.project_id")
    return (
        "EXISTS ("  # noqa: S608
        f"SELECT 1 FROM {from_clause} "
        f"WHERE {correlation} AND {access}"
        ")"
    )


def _drop_project_policies(table: str) -> None:
    for operation in ("select", "insert", "update", "delete"):
        op.execute(
            f'DROP POLICY IF EXISTS "{table}_project_{operation}" '
            f'ON "{table}"'
        )


def _create_creator_function() -> None:
    # The function owner is the existing NOLOGIN/BYPASSRLS dispatch role so
    # this narrowly-scoped bootstrap check does not recurse through the
    # projects policy while the creator membership is being inserted.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION akc_is_current_project_creator(
            requested_project_id uuid,
            requested_user_id uuid,
            requested_tenant_id uuid
        )
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
            SELECT EXISTS (
                SELECT 1
                FROM public.projects checked_project
                WHERE checked_project.id = requested_project_id
                  AND checked_project.tenant_id = requested_tenant_id
                  AND checked_project.created_by = requested_user_id
                  AND checked_project.xmin =
                      pg_current_xact_id()::text::xid
            )
        $function$
        """
    )
    op.execute(
        f"ALTER FUNCTION {_CREATOR_FUNCTION}(uuid, uuid, uuid) "
        f"OWNER TO {_DISPATCH_ROLE}"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION "
        f"{_CREATOR_FUNCTION}(uuid, uuid, uuid) TO PUBLIC"
    )


def _create_project_policies(
    table: str,
    *,
    read_access: str,
    review_access: str,
    write_access: str,
) -> None:
    tenant_check = f'"{table}".tenant_id = {_tenant_setting()}'
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    _drop_project_policies(table)
    op.execute(
        f'CREATE POLICY "{table}_project_select" ON "{table}" '
        "AS RESTRICTIVE FOR SELECT "
        f"USING ({tenant_check} AND {read_access})"
    )
    op.execute(
        f'CREATE POLICY "{table}_project_insert" ON "{table}" '
        "AS RESTRICTIVE FOR INSERT "
        f"WITH CHECK ({tenant_check} AND {write_access})"
    )
    op.execute(
        f'CREATE POLICY "{table}_project_update" ON "{table}" '
        "AS RESTRICTIVE FOR UPDATE "
        f"USING ({tenant_check} AND {review_access}) "
        f"WITH CHECK ({tenant_check} AND {review_access})"
    )
    op.execute(
        f'CREATE POLICY "{table}_project_delete" ON "{table}" '
        "AS RESTRICTIVE FOR DELETE "
        f"USING ({tenant_check} AND {write_access})"
    )


def _create_project_table_policies() -> None:
    table = "projects"
    tenant_check = f'"{table}".tenant_id = {_tenant_setting()}'
    project_expression = '"projects".id'
    creator_bootstrap = (
        f'("projects".created_by = {_user_setting()} '
        'AND "projects".xmin = pg_current_xact_id()::text::xid)'
    )
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    _drop_project_policies(table)
    op.execute(
        f'CREATE POLICY "{table}_project_select" ON "{table}" '
        "AS RESTRICTIVE FOR SELECT "
        f"USING ({tenant_check} AND "
        f"({_read_access(project_expression)} OR {creator_bootstrap}))"
    )
    op.execute(
        f'CREATE POLICY "{table}_project_insert" ON "{table}" '
        "AS RESTRICTIVE FOR INSERT "
        f"WITH CHECK ({tenant_check} "
        f'AND "projects".created_by = {_user_setting()} '
        f"AND {_tenant_role('owner', 'admin', 'editor')})"
    )
    op.execute(
        f'CREATE POLICY "{table}_project_update" ON "{table}" '
        "AS RESTRICTIVE FOR UPDATE "
        f"USING ({tenant_check} AND {_write_access(project_expression)}) "
        f"WITH CHECK ({tenant_check} AND {_write_access(project_expression)})"
    )
    op.execute(
        f'CREATE POLICY "{table}_project_delete" ON "{table}" '
        "AS RESTRICTIVE FOR DELETE "
        f"USING ({tenant_check} AND {_write_access(project_expression)})"
    )


def _create_membership_policies() -> None:
    table = "project_memberships"
    tenant_check = f'"{table}".tenant_id = {_tenant_setting()}'
    self_check = f'"{table}".user_id = {_user_setting()}'
    bootstrap = (
        f"{self_check} "
        f'AND "project_memberships".granted_by = {_user_setting()} '
        "AND \"project_memberships\".role = 'editor' "
        "AND "
        f"{_creator_current_transaction('\"project_memberships\".project_id')}"
    )
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    _drop_project_policies(table)
    op.execute(
        f'CREATE POLICY "{table}_project_select" ON "{table}" '
        "FOR SELECT "
        f"USING ({tenant_check} AND ({self_check} OR {_admin_access()}))"
    )
    op.execute(
        f'CREATE POLICY "{table}_project_insert" ON "{table}" '
        "FOR INSERT "
        f"WITH CHECK ({tenant_check} AND ({_admin_access()} OR ({bootstrap})))"
    )
    op.execute(
        f'CREATE POLICY "{table}_project_update" ON "{table}" '
        "FOR UPDATE "
        f"USING ({tenant_check} AND {_admin_access()}) "
        f"WITH CHECK ({tenant_check} AND {_admin_access()})"
    )
    op.execute(
        f'CREATE POLICY "{table}_project_delete" ON "{table}" '
        "FOR DELETE "
        f"USING ({tenant_check} AND {_admin_access()})"
    )


def upgrade() -> None:
    bind = op.get_bind()
    if "project_memberships" not in _tables():
        ProjectMembership.__table__.create(bind=bind)
    if bind.dialect.name != "postgresql":
        return

    tables = _tables()
    _create_creator_function()
    _create_membership_policies()
    if "projects" in tables:
        _create_project_table_policies()
    for table, column in _DIRECT_PROJECT_TABLES.items():
        if table not in tables:
            continue
        project_expression = f'"{table}"."{column}"'
        _create_project_policies(
            table,
            read_access=_read_access(project_expression),
            review_access=(
                _review_access(project_expression)
                if table == "review_items"
                else _write_access(project_expression)
            ),
            write_access=_write_access(project_expression),
        )
    for table, (from_clause, correlation) in _INDIRECT_PROJECT_SCOPES.items():
        if table not in tables:
            continue
        review_builder = "review" if table == "blocks" else "write"
        write_builder = "review" if table == "block_revisions" else "write"
        _create_project_policies(
            table,
            read_access=_scope_access(from_clause, correlation, "read"),
            review_access=_scope_access(from_clause, correlation, review_builder),
            write_access=_scope_access(from_clause, correlation, write_builder),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables()
    if bind.dialect.name == "postgresql":
        protected_tables = {
            "projects",
            *_DIRECT_PROJECT_TABLES,
            *_INDIRECT_PROJECT_SCOPES,
            "project_memberships",
        }
        for table in sorted(protected_tables, reverse=True):
            if table in tables:
                _drop_project_policies(table)
        op.execute(
            f"DROP FUNCTION IF EXISTS "
            f"{_CREATOR_FUNCTION}(uuid, uuid, uuid)"
        )
    if "project_memberships" in tables:
        ProjectMembership.__table__.drop(bind=bind)
