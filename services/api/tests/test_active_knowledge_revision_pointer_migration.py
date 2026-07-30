"""Migration evidence for fail-closed active knowledge revision pointers."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
)

MIGRATION = importlib.import_module("migrations.versions.0017_active_revision_pointers")

_INDEXES = {
    "document_semantic_classifications": ("document_semantic_classifications_one_active_idx"),
    "knowledge_notes": "knowledge_notes_one_active_revision_idx",
    "relations": "relations_one_active_revision_idx",
}


def _minimal_revision_tables(metadata: MetaData) -> None:
    Table(
        "document_semantic_classifications",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("tenant_id", String(36), nullable=False),
        Column("document_id", String(36), nullable=False),
        Column("document_version", Integer, nullable=False),
        Column("is_active", Boolean, nullable=False),
    )
    Table(
        "knowledge_notes",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("tenant_id", String(36), nullable=False),
        Column("project_id", String(36), nullable=False),
        Column("document_id", String(36)),
        Column("document_version", Integer),
        Column("stable_key", String(128), nullable=False),
        Column("is_active", Boolean, nullable=False),
    )
    Table(
        "relations",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("tenant_id", String(36), nullable=False),
        Column("project_id", String(36), nullable=False),
        Column("document_id", String(36)),
        Column("document_version", Integer),
        Column("source_relation_key", String(256)),
        Column("is_active", Boolean, nullable=False),
    )


def _migration_operations(connection: Any) -> Operations:
    return Operations(
        MigrationContext.configure(
            connection,
            opts={"render_as_batch": True},
        )
    )


def _assert_unique_partial_indexes(connection: Any) -> None:
    inspector = inspect(connection)
    for table, index_name in _INDEXES.items():
        indexes = {
            str(index["name"]): index for index in inspector.get_indexes(table) if index.get("name")
        }
        index = indexes[index_name]
        assert index["unique"] == 1
        predicate = str(index["dialect_options"]["sqlite_where"])
        assert "is_active" in predicate
        if table != "document_semantic_classifications":
            assert "document_id IS NOT NULL" in predicate
        if table == "relations":
            assert "source_relation_key IS NOT NULL" in predicate


def test_active_pointer_migration_sqlite_up_down_up(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    metadata = MetaData()
    _minimal_revision_tables(metadata)
    with engine.begin() as connection:
        metadata.create_all(connection)
        monkeypatch.setattr(MIGRATION, "op", _migration_operations(connection))

        MIGRATION.upgrade()
        _assert_unique_partial_indexes(connection)

        MIGRATION.downgrade()
        for table, index_name in _INDEXES.items():
            assert index_name not in {
                str(index["name"])
                for index in inspect(connection).get_indexes(table)
                if index.get("name")
            }

        MIGRATION.upgrade()
        _assert_unique_partial_indexes(connection)


def test_active_pointer_migration_rejects_ambiguous_existing_state(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    metadata = MetaData()
    _minimal_revision_tables(metadata)
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(
            metadata.tables["document_semantic_classifications"].insert(),
            [
                {
                    "id": "semantic-a",
                    "tenant_id": "tenant",
                    "document_id": "document",
                    "document_version": 1,
                    "is_active": True,
                },
                {
                    "id": "semantic-b",
                    "tenant_id": "tenant",
                    "document_id": "document",
                    "document_version": 1,
                    "is_active": True,
                },
            ],
        )
        monkeypatch.setattr(MIGRATION, "op", _migration_operations(connection))

        with pytest.raises(
            RuntimeError,
            match="duplicate_active_document_semantic_classification",
        ):
            MIGRATION.upgrade()

        for table, index_name in _INDEXES.items():
            assert index_name not in {
                str(index["name"])
                for index in inspect(connection).get_indexes(table)
                if index.get("name")
            }
