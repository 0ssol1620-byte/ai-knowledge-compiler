from __future__ import annotations

import importlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from akc_api.collection_metadata import CollectionMetadataCodec
from akc_api.collection_metadata_backfill import CollectionMetadataBackfill
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.asyncio import create_async_engine

BRIDGE = importlib.import_module("migrations.versions.0026_collection_metadata_encryption_bridge")
FINAL = importlib.import_module("migrations.versions.0027_finalize_collection_metadata_encryption")


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


def _insert_legacy_rows(
    connection: Any,
    *,
    tenant_id: uuid.UUID,
    count: int = 2,
) -> tuple[uuid.UUID, list[uuid.UUID], list[uuid.UUID]]:
    identity_base = tenant_id.int * 1_000
    collection_id = uuid.UUID(int=identity_base + 10)
    root_ids: list[uuid.UUID] = []
    file_ids: list[uuid.UUID] = []
    for index in range(1, count + 1):
        root_id = uuid.UUID(int=identity_base + index)
        file_id = uuid.UUID(int=identity_base + 500 + index)
        root_ids.append(root_id)
        file_ids.append(file_id)
        connection.execute(
            sa.text(
                "INSERT INTO collection_source_roots "
                "(id, tenant_id, collection_id, display_name) "
                "VALUES (:id, :tenant, :collection, :display_name)"
            ),
            {
                "id": root_id.hex,
                "tenant": tenant_id.hex,
                "collection": collection_id.hex,
                "display_name": f"Confidential root {index}",
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO collection_files "
                "(id, tenant_id, collection_id, source_root_id, relative_path, display_name) "
                "VALUES (:id, :tenant, :collection, :root, :path, :display_name)"
            ),
            {
                "id": file_id.hex,
                "tenant": tenant_id.hex,
                "collection": collection_id.hex,
                "root": root_id.hex,
                "path": f"private/{index}/report.txt",
                "display_name": "report.txt",
            },
        )
    return collection_id, root_ids, file_ids


def _codec() -> CollectionMetadataCodec:
    return CollectionMetadataCodec(
        active_key_id="metadata-v2",
        keyring={"metadata-v1": b"1" * 32, "metadata-v2": b"2" * 32},
        blind_index_key_id="path-index-v2",
        blind_index_key=b"i" * 32,
    )


@pytest.mark.asyncio
async def test_backfill_is_tenant_scoped_resumable_and_finalization_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "metadata-backfill.db"
    sync_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    tenant_id = uuid.UUID(int=20)
    with sync_engine.begin() as connection:
        _legacy_schema(connection)
        monkeypatch.setattr(BRIDGE, "op", _operations(connection))
        BRIDGE.upgrade()
        _, root_ids, _ = _insert_legacy_rows(connection, tenant_id=tenant_id)
    sync_engine.dispose()

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    codec = _codec()
    backfill = CollectionMetadataBackfill(engine=async_engine, codec=codec, batch_size=1)
    dry_run = await backfill.run(mode="dry-run", tenant_id=tenant_id)
    assert dry_run.finalization_ready is False
    assert dry_run.root_rows == dry_run.file_rows == 2
    assert dry_run.rows_rewritten == 0
    assert "Confidential" not in json.dumps(dry_run.public_dict())
    assert "private/" not in json.dumps(dry_run.public_dict())

    original_encrypt = codec.encrypt_source_root_display_name
    calls = 0

    def interrupt_second_root(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated operator interruption")
        return original_encrypt(*args, **kwargs)

    monkeypatch.setattr(codec, "encrypt_source_root_display_name", interrupt_second_root)
    with pytest.raises(RuntimeError, match="operator interruption"):
        await backfill.run(mode="apply", tenant_id=tenant_id)
    monkeypatch.setattr(codec, "encrypt_source_root_display_name", original_encrypt)

    applied = await backfill.run(mode="apply", tenant_id=tenant_id)
    assert applied.finalization_ready is True
    # The first root committed with its checkpoint before interruption; resume
    # rewrites only the second root and the two file rows.
    assert applied.rows_rewritten == 3
    assert applied.checkpoint_status == "verified"
    repeated = await backfill.run(mode="apply", tenant_id=tenant_id)
    assert repeated.rows_rewritten == 0
    verified = await backfill.run(mode="verify", tenant_id=tenant_id)
    assert verified.finalization_ready is True

    async with async_engine.connect() as connection:
        checkpoint = (
            (
                await connection.execute(
                    sa.text(
                        "SELECT status, roots_completed, files_completed "
                        "FROM collection_metadata_backfill_checkpoints "
                        "WHERE tenant_id = :tenant"
                    ),
                    {"tenant": tenant_id.hex},
                )
            )
            .mappings()
            .one()
        )
        root_rows = (
            (
                await connection.execute(
                    sa.text(
                        "SELECT id, display_name, display_name_ciphertext, metadata_key_id "
                        "FROM collection_source_roots WHERE tenant_id = :tenant ORDER BY id"
                    ),
                    {"tenant": tenant_id.hex},
                )
            )
            .mappings()
            .all()
        )
    assert checkpoint == {"status": "verified", "roots_completed": 2, "files_completed": 2}
    assert [uuid.UUID(row["id"]) for row in root_rows] == root_ids
    assert all(row["display_name"] is not None for row in root_rows)
    assert all(row["display_name_ciphertext"] is not None for row in root_rows)
    assert all(row["metadata_key_id"] == "metadata-v2" for row in root_rows)
    await async_engine.dispose()

    sync_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with sync_engine.begin() as connection:
        monkeypatch.setattr(FINAL, "op", _operations(connection))
        FINAL.upgrade()
        root_columns = {
            row["name"] for row in inspect(connection).get_columns("collection_source_roots")
        }
        file_columns = {row["name"] for row in inspect(connection).get_columns("collection_files")}
        assert "display_name" not in root_columns
        assert "relative_path" not in file_columns
        assert "display_name" not in file_columns
    sync_engine.dispose()


@pytest.mark.asyncio
async def test_backfill_does_not_cross_tenant_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "tenant-scope.db"
    sync_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    target_tenant = uuid.UUID(int=30)
    other_tenant = uuid.UUID(int=31)
    with sync_engine.begin() as connection:
        _legacy_schema(connection)
        monkeypatch.setattr(BRIDGE, "op", _operations(connection))
        BRIDGE.upgrade()
        _insert_legacy_rows(connection, tenant_id=target_tenant, count=1)
        _insert_legacy_rows(connection, tenant_id=other_tenant, count=1)
    sync_engine.dispose()

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    report = await CollectionMetadataBackfill(
        engine=async_engine,
        codec=_codec(),
        batch_size=1,
    ).run(mode="apply", tenant_id=target_tenant)
    assert report.root_rows == report.file_rows == 1
    async with async_engine.connect() as connection:
        target_ciphertext = await connection.scalar(
            sa.text(
                "SELECT display_name_ciphertext FROM collection_source_roots "
                "WHERE tenant_id = :tenant"
            ),
            {"tenant": target_tenant.hex},
        )
        other_ciphertext = await connection.scalar(
            sa.text(
                "SELECT display_name_ciphertext FROM collection_source_roots "
                "WHERE tenant_id = :tenant"
            ),
            {"tenant": other_tenant.hex},
        )
    assert target_ciphertext is not None
    assert other_ciphertext is None
    await async_engine.dispose()


@pytest.mark.asyncio
async def test_backfill_postgresql_contract_uses_session_advisory_lock() -> None:
    statements: list[str] = []

    class _Dialect:
        name = "postgresql"

    class _Connection:
        dialect = _Dialect()

        async def execute(self, statement: Any, parameters: Any) -> None:
            del parameters
            statements.append(str(statement))

    backfill = CollectionMetadataBackfill(
        engine=Any,  # type: ignore[arg-type]
        codec=_codec(),
    )
    connection = _Connection()
    lock_key = await backfill._advisory_lock(connection, uuid.UUID(int=40))  # type: ignore[arg-type]
    await backfill._advisory_unlock(connection, lock_key)  # type: ignore[arg-type]
    assert statements == [
        "SELECT pg_advisory_lock(:lock_key)",
        "SELECT pg_advisory_unlock(:lock_key)",
    ]


def test_bridge_revokes_public_checkpoint_table_access() -> None:
    bridge_source = Path(
        "migrations/versions/0026_collection_metadata_encryption_bridge.py"
    ).read_text(encoding="utf-8")
    assert (
        "REVOKE ALL ON TABLE collection_metadata_backfill_checkpoints FROM PUBLIC" in bridge_source
    )
