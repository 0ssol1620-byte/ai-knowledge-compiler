from __future__ import annotations

import importlib
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

MIGRATION = importlib.import_module(
    "migrations.versions.0026_collection_metadata_encryption_bridge"
)
FINAL_MIGRATION = importlib.import_module(
    "migrations.versions.0027_finalize_collection_metadata_encryption"
)


def _operations(connection: Any) -> Operations:
    return Operations(MigrationContext.configure(connection))


def _legacy_schema(connection: Any) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "collection_source_roots",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(500), nullable=False),
    )
    sa.Table(
        "collection_files",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("source_root_id", sa.Uuid(), nullable=False),
        sa.Column("relative_path", sa.String(2_000), nullable=False),
        sa.Column("display_name", sa.String(500), nullable=False),
        sa.UniqueConstraint(
            "collection_id",
            "source_root_id",
            "relative_path",
            name="uq_collection_file_relative_path",
        ),
    )
    metadata.create_all(connection)


def test_collection_metadata_bridge_is_sqlite_safe_and_enforces_blind_uniqueness(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _legacy_schema(connection)
        monkeypatch.setattr(MIGRATION, "op", _operations(connection))

        MIGRATION.upgrade()
        MIGRATION.upgrade()

        inspector = inspect(connection)
        root_columns = {
            row["name"]: row for row in inspector.get_columns("collection_source_roots")
        }
        file_columns = {row["name"]: row for row in inspector.get_columns("collection_files")}
        assert root_columns["display_name"]["nullable"] is True
        assert file_columns["relative_path"]["nullable"] is True
        assert file_columns["display_name"]["nullable"] is True
        assert {"display_name_ciphertext", "metadata_key_id"} <= set(root_columns)
        assert {
            "relative_path_ciphertext",
            "display_name_ciphertext",
            "metadata_key_id",
            "relative_path_blind_index",
            "relative_path_blind_index_key_id",
        } <= set(file_columns)
        indexes = {row["name"]: row for row in inspector.get_indexes("collection_files")}
        assert indexes["uq_collection_file_relative_path_blind_index"]["unique"] == 1

        tenant_id = uuid.uuid4()
        collection_id = uuid.uuid4()
        root_id = uuid.uuid4()
        connection.execute(
            sa.text(
                "INSERT INTO collection_source_roots "
                "(id, tenant_id, collection_id, display_name, display_name_ciphertext, "
                "metadata_key_id) VALUES (:id, :tenant, :collection, NULL, :ciphertext, :key_id)"
            ),
            {
                "id": root_id.hex,
                "tenant": tenant_id.hex,
                "collection": collection_id.hex,
                "ciphertext": b"ciphertext",
                "key_id": "metadata-v1",
            },
        )
        file_values = {
            "tenant": tenant_id.hex,
            "collection": collection_id.hex,
            "root": root_id.hex,
            "path_ciphertext": b"path-ciphertext",
            "name_ciphertext": b"name-ciphertext",
            "key_id": "metadata-v1",
            "blind": b"b" * 32,
            "blind_key_id": "path-index-v1",
        }
        statement = sa.text(
            "INSERT INTO collection_files "
            "(id, tenant_id, collection_id, source_root_id, relative_path, display_name, "
            "relative_path_ciphertext, display_name_ciphertext, metadata_key_id, "
            "relative_path_blind_index, relative_path_blind_index_key_id) "
            "VALUES (:id, :tenant, :collection, :root, NULL, NULL, :path_ciphertext, "
            ":name_ciphertext, :key_id, :blind, :blind_key_id)"
        )
        connection.execute(statement, {**file_values, "id": uuid.uuid4().hex})
        with pytest.raises(IntegrityError):
            connection.execute(statement, {**file_values, "id": uuid.uuid4().hex})

        with pytest.raises(RuntimeError, match="cannot downgrade"):
            MIGRATION.downgrade()

    engine.dispose()


def test_collection_metadata_bridge_empty_sqlite_round_trips(monkeypatch: Any) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _legacy_schema(connection)
        monkeypatch.setattr(MIGRATION, "op", _operations(connection))

        MIGRATION.upgrade()
        MIGRATION.downgrade()

        inspector = inspect(connection)
        root_columns = {
            row["name"]: row for row in inspector.get_columns("collection_source_roots")
        }
        file_columns = {row["name"]: row for row in inspector.get_columns("collection_files")}
        assert set(root_columns) == {"id", "tenant_id", "collection_id", "display_name"}
        assert set(file_columns) == {
            "id",
            "tenant_id",
            "collection_id",
            "source_root_id",
            "relative_path",
            "display_name",
        }
        assert root_columns["display_name"]["nullable"] is False
        assert file_columns["relative_path"]["nullable"] is False
        assert file_columns["display_name"]["nullable"] is False

    engine.dispose()


def test_collection_metadata_empty_sqlite_full_chain_round_trips(monkeypatch: Any) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _legacy_schema(connection)
        operations = _operations(connection)
        monkeypatch.setattr(MIGRATION, "op", operations)
        monkeypatch.setattr(FINAL_MIGRATION, "op", operations)

        MIGRATION.upgrade()
        FINAL_MIGRATION.upgrade()
        FINAL_MIGRATION.downgrade()
        MIGRATION.downgrade()

        inspector = inspect(connection)
        assert {row["name"] for row in inspector.get_columns("collection_source_roots")} == {
            "id",
            "tenant_id",
            "collection_id",
            "display_name",
        }
        assert {row["name"] for row in inspector.get_columns("collection_files")} == {
            "id",
            "tenant_id",
            "collection_id",
            "source_root_id",
            "relative_path",
            "display_name",
        }

    engine.dispose()


def _insert_encrypted_bridge_rows(
    connection: Any,
    *,
    verified_checkpoint: bool = True,
) -> dict[str, Any]:
    tenant_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    root_id = uuid.uuid4()
    connection.execute(
        sa.text(
            "INSERT INTO collection_source_roots "
            "(id, tenant_id, collection_id, display_name, display_name_ciphertext, "
            "metadata_key_id) VALUES (:id, :tenant, :collection, :display_name, "
            ":ciphertext, :key_id)"
        ),
        {
            "id": root_id.hex,
            "tenant": tenant_id.hex,
            "collection": collection_id.hex,
            "display_name": "legacy root",
            "ciphertext": b"r" * 29,
            "key_id": "metadata-v1",
        },
    )
    values = {
        "id": uuid.uuid4().hex,
        "tenant": tenant_id.hex,
        "collection": collection_id.hex,
        "root": root_id.hex,
        "relative_path": "legacy/path.pdf",
        "display_name": "path.pdf",
        "path_ciphertext": b"p" * 29,
        "name_ciphertext": b"n" * 29,
        "key_id": "metadata-v1",
        "blind": b"b" * 32,
        "blind_key_id": "path-index-v1",
    }
    connection.execute(
        sa.text(
            "INSERT INTO collection_files "
            "(id, tenant_id, collection_id, source_root_id, relative_path, display_name, "
            "relative_path_ciphertext, display_name_ciphertext, metadata_key_id, "
            "relative_path_blind_index, relative_path_blind_index_key_id) VALUES "
            "(:id, :tenant, :collection, :root, :relative_path, :display_name, "
            ":path_ciphertext, :name_ciphertext, :key_id, :blind, :blind_key_id)"
        ),
        values,
    )
    if verified_checkpoint:
        # Raw SQLite migration fixtures use the database wire representation;
        # passing datetime objects would invoke Python 3.12's deprecated
        # sqlite3 adapter and obscure real migration warnings.
        now = datetime.now(UTC).isoformat()
        connection.execute(
            sa.text(
                "INSERT INTO collection_metadata_backfill_checkpoints "
                "(tenant_id, active_key_id, blind_index_key_id, roots_completed, "
                "files_completed, status, started_at, updated_at, completed_at) VALUES "
                "(:tenant, :active_key, :blind_key, 1, 1, 'verified', :started, "
                ":updated, :completed)"
            ),
            {
                "tenant": tenant_id.hex,
                "active_key": "metadata-v1",
                "blind_key": "path-index-v1",
                "started": now,
                "updated": now,
                "completed": now,
            },
        )
    return values


def test_collection_metadata_finalization_removes_plaintext_and_round_trips_bridge(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _legacy_schema(connection)
        operations = _operations(connection)
        monkeypatch.setattr(MIGRATION, "op", operations)
        monkeypatch.setattr(FINAL_MIGRATION, "op", operations)
        MIGRATION.upgrade()
        values = _insert_encrypted_bridge_rows(connection)

        FINAL_MIGRATION.upgrade()
        FINAL_MIGRATION.upgrade()

        inspector = inspect(connection)
        root_columns = {
            row["name"]: row for row in inspector.get_columns("collection_source_roots")
        }
        file_columns = {row["name"]: row for row in inspector.get_columns("collection_files")}
        assert "display_name" not in root_columns
        assert "relative_path" not in file_columns
        assert "display_name" not in file_columns
        assert root_columns["display_name_ciphertext"]["nullable"] is False
        assert file_columns["relative_path_ciphertext"]["nullable"] is False
        assert file_columns["relative_path_blind_index"]["nullable"] is False

        duplicate = {**values, "id": uuid.uuid4().hex}
        with pytest.raises(IntegrityError):
            connection.execute(
                sa.text(
                    "INSERT INTO collection_files "
                    "(id, tenant_id, collection_id, source_root_id, "
                    "relative_path_ciphertext, display_name_ciphertext, metadata_key_id, "
                    "relative_path_blind_index, relative_path_blind_index_key_id) VALUES "
                    "(:id, :tenant, :collection, :root, :path_ciphertext, "
                    ":name_ciphertext, :key_id, :blind, :blind_key_id)"
                ),
                duplicate,
            )

        FINAL_MIGRATION.downgrade()
        inspector = inspect(connection)
        root_columns = {
            row["name"]: row for row in inspector.get_columns("collection_source_roots")
        }
        file_columns = {row["name"]: row for row in inspector.get_columns("collection_files")}
        assert root_columns["display_name"]["nullable"] is True
        assert file_columns["relative_path"]["nullable"] is True
        assert file_columns["display_name"]["nullable"] is True
        assert root_columns["display_name_ciphertext"]["nullable"] is True

    engine.dispose()


def test_collection_metadata_finalization_rejects_incomplete_backfill(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _legacy_schema(connection)
        operations = _operations(connection)
        monkeypatch.setattr(MIGRATION, "op", operations)
        monkeypatch.setattr(FINAL_MIGRATION, "op", operations)
        MIGRATION.upgrade()
        connection.execute(
            sa.text(
                "INSERT INTO collection_source_roots "
                "(id, tenant_id, collection_id, display_name) "
                "VALUES (:id, :tenant, :collection, :display_name)"
            ),
            {
                "id": uuid.uuid4().hex,
                "tenant": uuid.uuid4().hex,
                "collection": uuid.uuid4().hex,
                "display_name": "not backfilled",
            },
        )

        with pytest.raises(RuntimeError, match="complete verified backfill"):
            FINAL_MIGRATION.upgrade()

        assert "display_name" in {
            row["name"] for row in inspect(connection).get_columns("collection_source_roots")
        }

    engine.dispose()


def test_collection_metadata_finalization_rejects_nonnull_rows_without_verified_checkpoint(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _legacy_schema(connection)
        operations = _operations(connection)
        monkeypatch.setattr(MIGRATION, "op", operations)
        monkeypatch.setattr(FINAL_MIGRATION, "op", operations)
        MIGRATION.upgrade()
        _insert_encrypted_bridge_rows(connection, verified_checkpoint=False)

        with pytest.raises(RuntimeError, match="verified tenant checkpoints"):
            FINAL_MIGRATION.upgrade()

        assert "display_name" in {
            row["name"] for row in inspect(connection).get_columns("collection_source_roots")
        }

    engine.dispose()


def test_collection_metadata_finalization_rejects_checkpoint_key_mismatch(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _legacy_schema(connection)
        operations = _operations(connection)
        monkeypatch.setattr(MIGRATION, "op", operations)
        monkeypatch.setattr(FINAL_MIGRATION, "op", operations)
        MIGRATION.upgrade()
        _insert_encrypted_bridge_rows(connection)
        connection.execute(
            sa.text("UPDATE collection_files SET metadata_key_id = 'unexpected-key'")
        )

        with pytest.raises(RuntimeError, match="verified tenant checkpoints"):
            FINAL_MIGRATION.upgrade()

    engine.dispose()


def test_collection_metadata_finalization_rejects_garbage_ciphertext_with_checkpoint(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _legacy_schema(connection)
        operations = _operations(connection)
        monkeypatch.setattr(MIGRATION, "op", operations)
        monkeypatch.setattr(FINAL_MIGRATION, "op", operations)
        MIGRATION.upgrade()
        _insert_encrypted_bridge_rows(connection)
        connection.execute(
            sa.text("UPDATE collection_source_roots SET display_name_ciphertext = :garbage"),
            {"garbage": b"not-a-valid-aead-envelope"},
        )

        with pytest.raises(RuntimeError, match="complete verified backfill"):
            FINAL_MIGRATION.upgrade()

    engine.dispose()
