"""Schema, binding, and worker-RLS evidence for integrity action execution."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from akc_api import models as _models  # noqa: F401
from akc_api.database import Base
from akc_api.models import CollectionIntegrityActionExecution
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

MIGRATION = importlib.import_module(
    "migrations.versions.0030_collection_integrity_action_execution"
)


def _operations(connection: Any) -> Operations:
    return Operations(MigrationContext.configure(connection))


def test_integrity_action_execution_orm_is_content_and_secret_free() -> None:
    columns = set(CollectionIntegrityActionExecution.__table__.c.keys())
    assert {
        "tenant_id",
        "collection_id",
        "decision_id",
        "execution_kind",
        "status",
        "processing_job_id",
        "analysis_task_id",
        "registry_model_id",
        "target_scope",
        "execution_receipt_sha256",
        "result_code",
        "result",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    } <= columns
    assert {
        "content",
        "filename",
        "path",
        "password",
        "secret",
        "signed_url",
    }.isdisjoint(columns)
    constraints = {
        constraint.name
        for constraint in CollectionIntegrityActionExecution.__table__.constraints
    }
    assert "ck_collection_integrity_action_binding" in constraints
    assert "ck_collection_integrity_action_terminal" in constraints
    assert "uq_collection_integrity_action_decision" in constraints


def test_integrity_action_execution_migration_round_trips_sqlite(monkeypatch: Any) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        CollectionIntegrityActionExecution.__table__.drop(connection)
        monkeypatch.setattr(MIGRATION, "op", _operations(connection))

        MIGRATION.upgrade()
        MIGRATION.upgrade()
        inspector = inspect(connection)
        columns = {row["name"] for row in inspector.get_columns(MIGRATION._TABLE)}
        assert {
            "decision_id",
            "processing_job_id",
            "analysis_task_id",
            "registry_model_id",
            "execution_receipt_sha256",
        } <= columns
        indexes = {row["name"] for row in inspector.get_indexes(MIGRATION._TABLE)}
        assert {
            "collection_integrity_action_collection_idx",
            "collection_integrity_action_job_idx",
            "collection_integrity_action_task_idx",
        } <= indexes
        checks = " ".join(
            str(row["sqltext"])
            for row in inspector.get_check_constraints(MIGRATION._TABLE)
        )
        assert "compile_retry" in checks
        assert "password_analysis" in checks
        assert "completed_at IS NOT NULL" in checks
        assert MIGRATION.revision == "0030_collection_integrity_action_execution"
        assert MIGRATION.down_revision == "0029_collection_processing_paused_state"

        MIGRATION.downgrade()
        assert MIGRATION._TABLE not in inspect(connection).get_table_names()
    engine.dispose()


def test_integrity_action_execution_rls_is_project_and_worker_bound() -> None:
    source = Path(MIGRATION.__file__).read_text(encoding="utf-8")
    assert "current_setting('app.tenant_id', true)" in source
    assert "current_setting('app.user_id', true)" in source
    assert "project_memberships" in source
    assert "FOR INSERT WITH CHECK" in source
    assert "akc_dispatch_worker" in source
    assert "akc_analysis_worker" in source
    assert "processing_job_id IS NOT NULL" in source
    assert "analysis_task_id IS NOT NULL" in source
    assert "GRANT SELECT, UPDATE (status, result_code, result" in source
    columns = {column.name for column in CollectionIntegrityActionExecution.__table__.c}
    assert "password" not in columns
