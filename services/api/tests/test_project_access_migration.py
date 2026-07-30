"""Migration evidence for project membership and PostgreSQL ACL policies."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

from akc_api import models as _models  # noqa: F401
from akc_api.database import Base
from akc_api.project_access_models import ProjectMembership
from sqlalchemy import create_engine, inspect

MIGRATION = importlib.import_module("migrations.versions.0015_project_access")


class _SqliteOp:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def get_bind(self) -> Any:
        return self.connection

    def execute(self, statement: str) -> None:
        self.connection.exec_driver_sql(statement)


class _PostgresRecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def get_bind(self) -> Any:
        return self.bind

    def execute(self, statement: str) -> None:
        self.statements.append(str(statement))


def test_project_membership_sqlite_migration_up_down_up(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        ProjectMembership.__table__.drop(connection)
        monkeypatch.setattr(MIGRATION, "op", _SqliteOp(connection))

        MIGRATION.upgrade()
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("project_memberships")
        }
        assert columns == {
            "tenant_id",
            "project_id",
            "user_id",
            "role",
            "granted_by",
            "created_at",
            "updated_at",
        }

        MIGRATION.downgrade()
        assert "project_memberships" not in inspect(connection).get_table_names()

        MIGRATION.upgrade()
        assert "project_memberships" in inspect(connection).get_table_names()


def test_postgresql_policies_are_restrictive_intersections_and_reversible(
    monkeypatch: Any,
) -> None:
    recorder = _PostgresRecordingOp()
    protected_tables = {
        "project_memberships",
        "projects",
        *MIGRATION._DIRECT_PROJECT_TABLES,
        *MIGRATION._INDIRECT_PROJECT_SCOPES,
    }
    monkeypatch.setattr(MIGRATION, "op", recorder)
    monkeypatch.setattr(MIGRATION, "_tables", lambda: protected_tables)

    MIGRATION.upgrade()
    sql = "\n".join(recorder.statements)
    assert MIGRATION.revision == "0015_project_access"
    assert MIGRATION.down_revision == "0014_document_semantic_classification"
    assert "current_setting('app.tenant_id', true)" in sql
    assert "current_setting('app.user_id', true)" in sql
    assert "access_tenant_membership.role IN ('editor')" in sql
    assert "access_project_membership.role IN ('editor')" in sql
    assert (
        "access_tenant_membership.role IN ('editor', 'reviewer')" in sql
    )
    assert (
        "access_project_membership.role IN ('editor', 'reviewer')" in sql
    )
    assert "pg_current_xact_id()::text::xid" in sql
    assert "SECURITY DEFINER" in sql
    assert (
        "ALTER FUNCTION akc_is_current_project_creator(uuid, uuid, uuid) "
        "OWNER TO akc_dispatch_worker"
    ) in sql
    assert (
        'CREATE POLICY "projects_project_select" ON "projects" '
        "AS RESTRICTIVE FOR SELECT"
    ) in sql
    assert (
        'CREATE POLICY "documents_project_update" ON "documents" '
        "AS RESTRICTIVE FOR UPDATE"
    ) in sql
    assert (
        'CREATE POLICY "project_memberships_project_select" '
        'ON "project_memberships" FOR SELECT'
    ) in sql
    assert (
        'CREATE POLICY "project_memberships_project_select" '
        'ON "project_memberships" AS RESTRICTIVE'
    ) not in sql
    job_event_policy = next(
        statement
        for statement in recorder.statements
        if 'CREATE POLICY "job_events_project_select"' in statement
    )
    assert "scope_job.project_id" in job_event_policy
    assert "scope_document.project_id" not in job_event_policy
    gpu_attempt_policy = next(
        statement
        for statement in recorder.statements
        if 'CREATE POLICY "gpu_provider_attempts_project_select"' in statement
    )
    assert "scope_invocation.project_id" in gpu_attempt_policy
    assert "scope_document.project_id" not in gpu_attempt_policy

    recorder.statements.clear()
    monkeypatch.setattr(
        MIGRATION,
        "_tables",
        lambda: protected_tables - {"project_memberships"},
    )
    MIGRATION.downgrade()
    downgrade_sql = "\n".join(recorder.statements)
    for table in protected_tables - {"project_memberships"}:
        assert f'DROP POLICY IF EXISTS "{table}_project_select"' in downgrade_sql
        assert f'DROP POLICY IF EXISTS "{table}_project_insert"' in downgrade_sql
        assert f'DROP POLICY IF EXISTS "{table}_project_update"' in downgrade_sql
        assert f'DROP POLICY IF EXISTS "{table}_project_delete"' in downgrade_sql
