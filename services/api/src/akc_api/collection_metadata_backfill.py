"""Resumable, tenant-scoped bridge backfill for protected collection metadata."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from akc_api.collection_metadata import (
    CollectionMetadataCodec,
    CollectionMetadataIntegrityError,
)

_ROOT_TABLE = "collection_source_roots"
_FILE_TABLE = "collection_files"
_CHECKPOINT_TABLE = "collection_metadata_backfill_checkpoints"
_REQUIRED_ROOT_COLUMNS = frozenset(
    {"id", "tenant_id", "collection_id", "display_name_ciphertext", "metadata_key_id"}
)
_REQUIRED_FILE_COLUMNS = frozenset(
    {
        "id",
        "tenant_id",
        "collection_id",
        "source_root_id",
        "relative_path_ciphertext",
        "display_name_ciphertext",
        "metadata_key_id",
        "relative_path_blind_index",
        "relative_path_blind_index_key_id",
    }
)


class CollectionMetadataBackfillError(RuntimeError):
    """Fail-closed operator error that never includes protected values."""


@dataclass(frozen=True, slots=True)
class CollectionMetadataBackfillReport:
    mode: Literal["dry-run", "apply", "verify"]
    tenant_id: uuid.UUID
    active_key_id: str
    blind_index_key_id: str
    root_rows: int
    file_rows: int
    plaintext_root_rows: int
    plaintext_file_rows: int
    rows_rewritten: int
    collision_count: int
    finalization_ready: bool
    checkpoint_status: str

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tenant_id"] = str(self.tenant_id)
        return payload


@dataclass(slots=True)
class _Scan:
    root_rows: int = 0
    file_rows: int = 0
    plaintext_root_rows: int = 0
    plaintext_file_rows: int = 0
    noncurrent_rows: int = 0
    collision_count: int = 0


def _uuid(value: object, *, label: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise CollectionMetadataBackfillError(f"{label} identity is invalid") from exc


def _bytes(value: object, *, label: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    raise CollectionMetadataBackfillError(f"{label} ciphertext is unavailable")


class CollectionMetadataBackfill:
    """Scan, backfill, rotate, and verify one tenant without logging plaintext."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        codec: CollectionMetadataCodec,
        batch_size: int = 200,
    ) -> None:
        if batch_size < 1 or batch_size > 1_000:
            raise ValueError("collection metadata backfill batch size must be 1..1000")
        self._engine = engine
        self._codec = codec
        self._batch_size = batch_size
        self._metadata = sa.MetaData()
        self._root: sa.Table | None = None
        self._file: sa.Table | None = None
        self._checkpoint: sa.Table | None = None

    async def _initialize(self) -> None:
        async with self._engine.connect() as connection:
            await connection.run_sync(
                lambda sync_connection: self._metadata.reflect(
                    bind=sync_connection,
                    only=[_ROOT_TABLE, _FILE_TABLE, _CHECKPOINT_TABLE],
                )
            )
        tables = self._metadata.tables
        missing_tables = {
            name for name in (_ROOT_TABLE, _FILE_TABLE, _CHECKPOINT_TABLE) if name not in tables
        }
        if missing_tables:
            raise CollectionMetadataBackfillError(
                "collection metadata bridge/checkpoint schema is not installed"
            )
        self._root = tables[_ROOT_TABLE]
        self._file = tables[_FILE_TABLE]
        self._checkpoint = tables[_CHECKPOINT_TABLE]
        if not set(self._root.c.keys()) >= _REQUIRED_ROOT_COLUMNS:
            raise CollectionMetadataBackfillError(
                "collection source-root encryption bridge columns are incomplete"
            )
        if not set(self._file.c.keys()) >= _REQUIRED_FILE_COLUMNS:
            raise CollectionMetadataBackfillError(
                "collection file encryption bridge columns are incomplete"
            )

    @property
    def _root_table(self) -> sa.Table:
        if self._root is None:
            raise RuntimeError("collection metadata backfill is not initialized")
        return self._root

    @property
    def _file_table(self) -> sa.Table:
        if self._file is None:
            raise RuntimeError("collection metadata backfill is not initialized")
        return self._file

    @property
    def _checkpoint_table(self) -> sa.Table:
        if self._checkpoint is None:
            raise RuntimeError("collection metadata backfill is not initialized")
        return self._checkpoint

    def _bound_uuid(self, value: uuid.UUID) -> uuid.UUID | str:
        # SQLite reflection exposes UUID columns as CHAR(32), while PostgreSQL
        # retains the native UUID type and driver adaptation.
        return value.hex if self._engine.dialect.name == "sqlite" else value

    async def _pages(
        self,
        table: sa.Table,
        *,
        tenant_id: uuid.UUID,
        start_after: uuid.UUID | None = None,
    ) -> AsyncIterator[list[Mapping[str, Any]]]:
        cursor = start_after
        while True:
            statement = (
                sa.select(table)
                .where(table.c.tenant_id == self._bound_uuid(tenant_id))
                .order_by(table.c.id)
                .limit(self._batch_size)
            )
            if cursor is not None:
                statement = statement.where(table.c.id > self._bound_uuid(cursor))
            async with self._engine.connect() as connection:
                rows = [
                    cast(Mapping[str, Any], dict(row))
                    for row in (await connection.execute(statement)).mappings()
                ]
            if not rows:
                return
            yield rows
            cursor = _uuid(rows[-1]["id"], label="collection metadata row")

    def _root_plaintext(
        self,
        row: Mapping[str, Any],
        *,
        validate_existing: bool,
    ) -> str:
        tenant_id = _uuid(row["tenant_id"], label="tenant")
        collection_id = _uuid(row["collection_id"], label="collection")
        root_id = _uuid(row["id"], label="source root")
        legacy = row.get("display_name")
        ciphertext = row.get("display_name_ciphertext")
        key_id = row.get("metadata_key_id")
        decrypted: str | None = None
        if ciphertext is not None and isinstance(key_id, str) and key_id:
            try:
                decrypted = self._codec.decrypt_source_root_display_name(
                    _bytes(ciphertext, label="source-root display-name"),
                    key_id=key_id,
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    source_root_id=root_id,
                )
            except CollectionMetadataIntegrityError:
                if legacy is None or validate_existing:
                    raise CollectionMetadataBackfillError(
                        "source-root ciphertext failed authenticated verification"
                    ) from None
        if legacy is not None:
            plaintext = str(legacy)
            if validate_existing and decrypted is not None and decrypted != plaintext:
                raise CollectionMetadataBackfillError(
                    "source-root plaintext/ciphertext verification mismatch"
                )
            return plaintext
        if decrypted is None:
            raise CollectionMetadataBackfillError(
                "source-root row has neither recoverable plaintext nor ciphertext"
            )
        return decrypted

    def _file_plaintexts(
        self,
        row: Mapping[str, Any],
        *,
        validate_existing: bool,
    ) -> tuple[str, str]:
        tenant_id = _uuid(row["tenant_id"], label="tenant")
        collection_id = _uuid(row["collection_id"], label="collection")
        root_id = _uuid(row["source_root_id"], label="source root")
        file_id = _uuid(row["id"], label="collection file")
        key_id = row.get("metadata_key_id")
        legacy_path = row.get("relative_path")
        legacy_name = row.get("display_name")
        decrypted_path: str | None = None
        decrypted_name: str | None = None
        if isinstance(key_id, str) and key_id:
            try:
                if row.get("relative_path_ciphertext") is not None:
                    decrypted_path = self._codec.decrypt_file_relative_path(
                        _bytes(
                            row["relative_path_ciphertext"],
                            label="file relative-path",
                        ),
                        key_id=key_id,
                        tenant_id=tenant_id,
                        collection_id=collection_id,
                        source_root_id=root_id,
                        file_id=file_id,
                    )
                if row.get("display_name_ciphertext") is not None:
                    decrypted_name = self._codec.decrypt_file_display_name(
                        _bytes(
                            row["display_name_ciphertext"],
                            label="file display-name",
                        ),
                        key_id=key_id,
                        tenant_id=tenant_id,
                        collection_id=collection_id,
                        source_root_id=root_id,
                        file_id=file_id,
                    )
            except CollectionMetadataIntegrityError:
                if legacy_path is None or legacy_name is None or validate_existing:
                    raise CollectionMetadataBackfillError(
                        "file ciphertext failed authenticated verification"
                    ) from None
        path = str(legacy_path) if legacy_path is not None else decrypted_path
        name = str(legacy_name) if legacy_name is not None else decrypted_name
        if path is None or name is None:
            raise CollectionMetadataBackfillError(
                "file row has neither recoverable plaintext nor ciphertext"
            )
        if validate_existing and decrypted_path is not None and decrypted_path != path:
            raise CollectionMetadataBackfillError(
                "file relative-path plaintext/ciphertext verification mismatch"
            )
        if validate_existing and decrypted_name is not None and decrypted_name != name:
            raise CollectionMetadataBackfillError(
                "file display-name plaintext/ciphertext verification mismatch"
            )
        return path, name

    def _file_index(
        self,
        row: Mapping[str, Any],
        relative_path: str,
    ) -> bytes:
        return self._codec.relative_path_blind_index(
            relative_path,
            tenant_id=_uuid(row["tenant_id"], label="tenant"),
            collection_id=_uuid(row["collection_id"], label="collection"),
            source_root_id=_uuid(row["source_root_id"], label="source root"),
        ).digest

    async def _scan(
        self,
        *,
        tenant_id: uuid.UUID,
        validate_existing: bool,
        require_current_keys: bool,
    ) -> _Scan:
        scan = _Scan()
        collision_owner: dict[tuple[uuid.UUID, uuid.UUID, bytes], uuid.UUID] = {}
        async for rows in self._pages(self._root_table, tenant_id=tenant_id):
            for row in rows:
                self._root_plaintext(row, validate_existing=validate_existing)
                scan.root_rows += 1
                scan.plaintext_root_rows += int(row.get("display_name") is not None)
                current = (
                    row.get("display_name_ciphertext") is not None
                    and row.get("metadata_key_id") == self._codec.active_key_id
                )
                scan.noncurrent_rows += int(not current)
        async for rows in self._pages(self._file_table, tenant_id=tenant_id):
            for row in rows:
                path, _ = self._file_plaintexts(
                    row,
                    validate_existing=validate_existing,
                )
                expected_index = self._file_index(row, path)
                collection_id = _uuid(row["collection_id"], label="collection")
                root_id = _uuid(row["source_root_id"], label="source root")
                file_id = _uuid(row["id"], label="collection file")
                collision_key = (collection_id, root_id, expected_index)
                owner = collision_owner.setdefault(collision_key, file_id)
                if owner != file_id:
                    scan.collision_count += 1
                scan.file_rows += 1
                scan.plaintext_file_rows += int(
                    row.get("relative_path") is not None or row.get("display_name") is not None
                )
                stored_index = row.get("relative_path_blind_index")
                current = (
                    row.get("relative_path_ciphertext") is not None
                    and row.get("display_name_ciphertext") is not None
                    and row.get("metadata_key_id") == self._codec.active_key_id
                    and stored_index is not None
                    and _bytes(stored_index, label="relative-path blind-index") == expected_index
                    and row.get("relative_path_blind_index_key_id")
                    == self._codec.blind_index_key_id
                )
                scan.noncurrent_rows += int(not current)
        if scan.collision_count:
            raise CollectionMetadataBackfillError(
                "normalized relative-path blind-index collision detected"
            )
        if require_current_keys and scan.noncurrent_rows:
            raise CollectionMetadataBackfillError(
                "collection metadata verification found incomplete or noncurrent rows"
            )
        return scan

    async def _checkpoint_row(
        self,
        connection: AsyncConnection,
        tenant_id: uuid.UUID,
    ) -> Mapping[str, Any] | None:
        row = (
            (
                await connection.execute(
                    sa.select(self._checkpoint_table).where(
                        self._checkpoint_table.c.tenant_id == self._bound_uuid(tenant_id)
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return cast(Mapping[str, Any] | None, row)

    async def _reset_checkpoint(self, tenant_id: uuid.UUID) -> None:
        now = datetime.now(UTC)
        async with self._engine.begin() as connection:
            existing = await self._checkpoint_row(connection, tenant_id)
            values = {
                "active_key_id": self._codec.active_key_id,
                "blind_index_key_id": self._codec.blind_index_key_id,
                "last_root_id": None,
                "last_file_id": None,
                "roots_completed": 0,
                "files_completed": 0,
                "status": "applying",
                "started_at": now,
                "updated_at": now,
                "completed_at": None,
            }
            if existing is None:
                await connection.execute(
                    sa.insert(self._checkpoint_table).values(
                        tenant_id=self._bound_uuid(tenant_id),
                        **values,
                    )
                )
            else:
                await connection.execute(
                    sa.update(self._checkpoint_table)
                    .where(self._checkpoint_table.c.tenant_id == self._bound_uuid(tenant_id))
                    .values(**values)
                )

    async def _checkpoint_can_resume(self, tenant_id: uuid.UUID) -> bool:
        async with self._engine.connect() as connection:
            checkpoint = await self._checkpoint_row(connection, tenant_id)
        return bool(
            checkpoint is not None
            and checkpoint.get("status") == "applying"
            and checkpoint.get("active_key_id") == self._codec.active_key_id
            and checkpoint.get("blind_index_key_id") == self._codec.blind_index_key_id
        )

    async def _mark_failed(self, tenant_id: uuid.UUID) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                sa.update(self._checkpoint_table)
                .where(self._checkpoint_table.c.tenant_id == self._bound_uuid(tenant_id))
                .values(status="failed", updated_at=datetime.now(UTC))
            )

    async def _rewrite_roots(self, tenant_id: uuid.UUID) -> int:
        rewritten = 0
        while True:
            async with self._engine.begin() as connection:
                checkpoint = await self._checkpoint_row(connection, tenant_id)
                if checkpoint is None:
                    raise CollectionMetadataBackfillError("backfill checkpoint disappeared")
                cursor_value = checkpoint.get("last_root_id")
                statement = (
                    sa.select(self._root_table)
                    .where(self._root_table.c.tenant_id == self._bound_uuid(tenant_id))
                    .order_by(self._root_table.c.id)
                    .limit(self._batch_size)
                )
                if cursor_value is not None:
                    statement = statement.where(self._root_table.c.id > cursor_value)
                rows = [dict(row) for row in (await connection.execute(statement)).mappings()]
                if not rows:
                    return rewritten
                for row in rows:
                    root_id = _uuid(row["id"], label="source root")
                    protected = self._codec.encrypt_source_root_display_name(
                        self._root_plaintext(row, validate_existing=False),
                        tenant_id=tenant_id,
                        collection_id=_uuid(row["collection_id"], label="collection"),
                        source_root_id=root_id,
                    )
                    await connection.execute(
                        sa.update(self._root_table)
                        .where(
                            self._root_table.c.tenant_id == self._bound_uuid(tenant_id),
                            self._root_table.c.id == self._bound_uuid(root_id),
                        )
                        .values(
                            display_name_ciphertext=protected.ciphertext,
                            metadata_key_id=protected.key_id,
                        )
                    )
                rewritten += len(rows)
                await connection.execute(
                    sa.update(self._checkpoint_table)
                    .where(self._checkpoint_table.c.tenant_id == self._bound_uuid(tenant_id))
                    .values(
                        last_root_id=rows[-1]["id"],
                        roots_completed=self._checkpoint_table.c.roots_completed + len(rows),
                        updated_at=datetime.now(UTC),
                    )
                )

    async def _rewrite_files(self, tenant_id: uuid.UUID) -> int:
        rewritten = 0
        while True:
            async with self._engine.begin() as connection:
                checkpoint = await self._checkpoint_row(connection, tenant_id)
                if checkpoint is None:
                    raise CollectionMetadataBackfillError("backfill checkpoint disappeared")
                cursor_value = checkpoint.get("last_file_id")
                statement = (
                    sa.select(self._file_table)
                    .where(self._file_table.c.tenant_id == self._bound_uuid(tenant_id))
                    .order_by(self._file_table.c.id)
                    .limit(self._batch_size)
                )
                if cursor_value is not None:
                    statement = statement.where(self._file_table.c.id > cursor_value)
                rows = [dict(row) for row in (await connection.execute(statement)).mappings()]
                if not rows:
                    return rewritten
                for row in rows:
                    collection_id = _uuid(row["collection_id"], label="collection")
                    root_id = _uuid(row["source_root_id"], label="source root")
                    file_id = _uuid(row["id"], label="collection file")
                    path, name = self._file_plaintexts(row, validate_existing=False)
                    protected_path = self._codec.encrypt_file_relative_path(
                        path,
                        tenant_id=tenant_id,
                        collection_id=collection_id,
                        source_root_id=root_id,
                        file_id=file_id,
                    )
                    protected_name = self._codec.encrypt_file_display_name(
                        name,
                        tenant_id=tenant_id,
                        collection_id=collection_id,
                        source_root_id=root_id,
                        file_id=file_id,
                    )
                    blind_index = self._codec.relative_path_blind_index(
                        path,
                        tenant_id=tenant_id,
                        collection_id=collection_id,
                        source_root_id=root_id,
                    )
                    await connection.execute(
                        sa.update(self._file_table)
                        .where(
                            self._file_table.c.tenant_id == self._bound_uuid(tenant_id),
                            self._file_table.c.id == self._bound_uuid(file_id),
                        )
                        .values(
                            relative_path_ciphertext=protected_path.ciphertext,
                            display_name_ciphertext=protected_name.ciphertext,
                            metadata_key_id=protected_path.key_id,
                            relative_path_blind_index=blind_index.digest,
                            relative_path_blind_index_key_id=blind_index.key_id,
                        )
                    )
                rewritten += len(rows)
                await connection.execute(
                    sa.update(self._checkpoint_table)
                    .where(self._checkpoint_table.c.tenant_id == self._bound_uuid(tenant_id))
                    .values(
                        last_file_id=rows[-1]["id"],
                        files_completed=self._checkpoint_table.c.files_completed + len(rows),
                        updated_at=datetime.now(UTC),
                    )
                )

    async def _mark_verified(
        self,
        *,
        tenant_id: uuid.UUID,
        scan: _Scan,
    ) -> None:
        now = datetime.now(UTC)
        async with self._engine.begin() as connection:
            existing = await self._checkpoint_row(connection, tenant_id)
            values = {
                "active_key_id": self._codec.active_key_id,
                "blind_index_key_id": self._codec.blind_index_key_id,
                "roots_completed": scan.root_rows,
                "files_completed": scan.file_rows,
                "status": "verified",
                "updated_at": now,
                "completed_at": now,
            }
            if existing is None:
                await connection.execute(
                    sa.insert(self._checkpoint_table).values(
                        tenant_id=self._bound_uuid(tenant_id),
                        last_root_id=None,
                        last_file_id=None,
                        started_at=now,
                        **values,
                    )
                )
            else:
                await connection.execute(
                    sa.update(self._checkpoint_table)
                    .where(self._checkpoint_table.c.tenant_id == self._bound_uuid(tenant_id))
                    .values(**values)
                )

    async def _advisory_lock(self, connection: AsyncConnection, tenant_id: uuid.UUID) -> int:
        digest = hashlib.sha256(b"akc.collection-metadata-backfill.v1\0" + tenant_id.bytes).digest()
        lock_key = int.from_bytes(digest[:8], "big", signed=True)
        if connection.dialect.name == "postgresql":
            await connection.execute(
                sa.text("SELECT pg_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
        return lock_key

    async def _advisory_unlock(self, connection: AsyncConnection, lock_key: int) -> None:
        if connection.dialect.name == "postgresql":
            await connection.execute(
                sa.text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": lock_key},
            )

    async def run(
        self,
        *,
        mode: Literal["dry-run", "apply", "verify"],
        tenant_id: uuid.UUID,
    ) -> CollectionMetadataBackfillReport:
        await self._initialize()
        rows_rewritten = 0
        checkpoint_status = "not_written"
        async with self._engine.connect() as lock_connection:
            lock_key = await self._advisory_lock(lock_connection, tenant_id)
            try:
                if mode == "dry-run":
                    scan = await self._scan(
                        tenant_id=tenant_id,
                        validate_existing=True,
                        require_current_keys=False,
                    )
                    ready = scan.noncurrent_rows == 0
                elif mode == "verify":
                    scan = await self._scan(
                        tenant_id=tenant_id,
                        validate_existing=True,
                        require_current_keys=True,
                    )
                    await self._mark_verified(tenant_id=tenant_id, scan=scan)
                    ready = True
                    checkpoint_status = "verified"
                else:
                    try:
                        scan = await self._scan(
                            tenant_id=tenant_id,
                            validate_existing=True,
                            require_current_keys=True,
                        )
                    except CollectionMetadataBackfillError:
                        await self._scan(
                            tenant_id=tenant_id,
                            validate_existing=False,
                            require_current_keys=False,
                        )
                        if not await self._checkpoint_can_resume(tenant_id):
                            await self._reset_checkpoint(tenant_id)
                        rows_rewritten += await self._rewrite_roots(tenant_id)
                        rows_rewritten += await self._rewrite_files(tenant_id)
                        try:
                            scan = await self._scan(
                                tenant_id=tenant_id,
                                validate_existing=True,
                                require_current_keys=True,
                            )
                        except CollectionMetadataBackfillError:
                            await self._mark_failed(tenant_id)
                            raise
                    await self._mark_verified(tenant_id=tenant_id, scan=scan)
                    ready = True
                    checkpoint_status = "verified"
            finally:
                await self._advisory_unlock(lock_connection, lock_key)
        return CollectionMetadataBackfillReport(
            mode=mode,
            tenant_id=tenant_id,
            active_key_id=self._codec.active_key_id,
            blind_index_key_id=self._codec.blind_index_key_id,
            root_rows=scan.root_rows,
            file_rows=scan.file_rows,
            plaintext_root_rows=scan.plaintext_root_rows,
            plaintext_file_rows=scan.plaintext_file_rows,
            rows_rewritten=rows_rewritten,
            collision_count=scan.collision_count,
            finalization_ready=ready,
            checkpoint_status=checkpoint_status,
        )


__all__ = [
    "CollectionMetadataBackfill",
    "CollectionMetadataBackfillError",
    "CollectionMetadataBackfillReport",
]
