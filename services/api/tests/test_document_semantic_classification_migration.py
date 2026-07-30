"""Migration evidence for semantic classification and compile revisions."""

from __future__ import annotations

import importlib
from typing import Any

from akc_api import models as _models  # noqa: F401
from akc_api.database import Base
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

MIGRATION = importlib.import_module("migrations.versions.0014_document_semantic_classification")
ACTIVE_POINTER_MIGRATION = importlib.import_module(
    "migrations.versions.0017_active_revision_pointers"
)

_NOTE_REVISION_COLUMNS = {
    "document_id",
    "document_version",
    "compile_input_sha256",
    "pipeline_schema_sha256",
    "model_revision",
    "compile_provenance",
    "is_active",
}
_RELATION_REVISION_COLUMNS = {
    *_NOTE_REVISION_COLUMNS,
    "source_relation_key",
}


def _column_names(connection: Any, table: str) -> set[str]:
    return {str(column["name"]) for column in inspect(connection).get_columns(table)}


def test_semantic_classification_sqlite_migration_up_down_up(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        operations = Operations(
            MigrationContext.configure(
                connection,
                opts={"render_as_batch": True},
            )
        )
        monkeypatch.setattr(MIGRATION, "op", operations)
        monkeypatch.setattr(ACTIVE_POINTER_MIGRATION, "op", operations)

        ACTIVE_POINTER_MIGRATION.downgrade()
        MIGRATION.downgrade()
        assert "document_semantic_classifications" not in inspect(connection).get_table_names()
        assert not (_NOTE_REVISION_COLUMNS & _column_names(connection, "knowledge_notes"))
        assert not (_RELATION_REVISION_COLUMNS & _column_names(connection, "relations"))

        MIGRATION.upgrade()
        ACTIVE_POINTER_MIGRATION.upgrade()
        semantic_columns = _column_names(
            connection,
            "document_semantic_classifications",
        )
        assert {
            "compile_input_sha256",
            "classification",
            "provenance",
            "model_revision",
            "schema_sha256",
            "is_active",
        } <= semantic_columns
        assert (
            _column_names(
                connection,
                "knowledge_notes",
            )
            >= _NOTE_REVISION_COLUMNS
        )
        assert (
            _column_names(
                connection,
                "relations",
            )
            >= _RELATION_REVISION_COLUMNS
        )

        ACTIVE_POINTER_MIGRATION.downgrade()
        MIGRATION.downgrade()
        MIGRATION.upgrade()
        ACTIVE_POINTER_MIGRATION.upgrade()
        assert "document_semantic_classifications" in inspect(connection).get_table_names()
