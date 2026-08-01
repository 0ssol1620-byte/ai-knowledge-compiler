"""Migration evidence for the v4 tenant-safe Collection control plane."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

from akc_api import models as _models  # noqa: F401
from akc_api.database import Base
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

MIGRATION = importlib.import_module("migrations.versions.0023_v4_collections")

_MASTERPLAN_REQUIRED_TABLES = {
    "collections",
    "collection_source_roots",
    "collection_files",
    "collection_upload_sessions",
    "upload_file_sessions",
    "upload_parts",
    "file_content_hashes",
    "file_versions",
    "page_fingerprints",
    "document_clusters",
    "preflight_feature_records",
    "estimate_runs",
    "estimate_samples",
    "cost_prediction_models",
    "route_attempts",
    "region_attempts",
    "verification_records",
    "authority_facts",
    "authority_mappings",
    "quarantine_items",
    "architecture_plans",
    "blueprint_modules",
    "knowledge_compile_runs",
    "export_packages",
    "package_validations",
    "asset_registry",
}


def _operations(connection: Any) -> Operations:
    return Operations(MigrationContext.configure(connection))


def test_v4_collection_migration_sqlite_up_down_up(monkeypatch: Any) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        for table in reversed(MIGRATION._COLLECTION_TABLES):
            table.drop(bind=connection)
        monkeypatch.setattr(MIGRATION, "op", _operations(connection))

        MIGRATION.upgrade()
        table_names = set(inspect(connection).get_table_names())
        expected = {table.name for table in MIGRATION._COLLECTION_TABLES}
        assert expected <= table_names
        assert expected >= _MASTERPLAN_REQUIRED_TABLES
        for table in expected - {"collections"}:
            columns = {column["name"] for column in inspect(connection).get_columns(table)}
            assert {"tenant_id", "collection_id"} <= columns
        status_sql = " ".join(
            str(item["sqltext"])
            for item in inspect(connection).get_check_constraints("page_attempts")
        )
        assert "UNRESOLVED" in status_sql
        assert "QUARANTINED" in status_sql

        MIGRATION.downgrade()
        table_names = set(inspect(connection).get_table_names())
        assert expected.isdisjoint(table_names)
        downgraded_status = " ".join(
            str(item["sqltext"])
            for item in inspect(connection).get_check_constraints("page_attempts")
        )
        assert "UNRESOLVED" not in downgraded_status
        assert "QUARANTINED" not in downgraded_status

        MIGRATION.upgrade()
        assert expected <= set(inspect(connection).get_table_names())


class _PostgresRecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def get_bind(self) -> Any:
        return self.bind

    def execute(self, statement: str) -> None:
        self.statements.append(str(statement))


def test_v4_collection_postgresql_policies_are_tenant_project_intersections(
    monkeypatch: Any,
) -> None:
    recorder = _PostgresRecordingOp()
    monkeypatch.setattr(MIGRATION, "op", recorder)

    MIGRATION._enable_collection_policies()
    sql = "\n".join(recorder.statements)
    assert "current_setting('app.tenant_id', true)" in sql
    assert "current_setting('app.user_id', true)" in sql
    assert "project_memberships" in sql
    assert "collection_scope.project_id" in sql
    assert (
        'CREATE POLICY "collections_collection_insert" ON "collections" AS RESTRICTIVE FOR INSERT'
    ) in sql
    assert (
        'CREATE POLICY "collection_files_collection_select" ON "collection_files" '
        "AS RESTRICTIVE FOR SELECT"
    ) in sql
    assert "REVOKE UPDATE, DELETE ON collection_events FROM PUBLIC" in sql
    assert 'CREATE POLICY "collection_events_collection_update"' not in sql
    assert MIGRATION.revision == "0023_v4_collections"
    assert MIGRATION.down_revision == "0022_cdr_derivative_lineage"
