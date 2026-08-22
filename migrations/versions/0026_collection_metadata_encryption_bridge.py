"""Add the write-fenced collection metadata encryption bridge.

Revision ID: 0026_collection_metadata_encryption_bridge
Revises: 0025_collection_processing_runtime
Create Date: 2026-08-01

This revision is deliberately non-destructive. Existing deployments upgrade
to this revision, stop collection metadata writes, run the application-owned
backfill/verifier, and only then apply the finalizing revision that removes the
legacy plaintext columns.
"""

from __future__ import annotations

from typing import Any, cast

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0026_collection_metadata_encryption_bridge"
down_revision = "0025_collection_processing_runtime"
branch_labels = None
depends_on = None

_ROOT_TABLE = "collection_source_roots"
_FILE_TABLE = "collection_files"
_BLIND_INDEX_NAME = "uq_collection_file_relative_path_blind_index"
_ROOT_ROTATION_INDEX = "collection_source_roots_metadata_key_idx"
_FILE_ROTATION_INDEX = "collection_files_metadata_key_idx"
_CHECKPOINT_TABLE = "collection_metadata_backfill_checkpoints"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> dict[str, dict[str, Any]]:
    return {
        str(column["name"]): cast(dict[str, Any], column)
        for column in inspect(op.get_bind()).get_columns(table)
    }


def _index_names(table: str) -> set[str]:
    return {
        str(row["name"]) for row in inspect(op.get_bind()).get_indexes(table) if row.get("name")
    }


def _add_bridge_columns() -> None:
    if _ROOT_TABLE not in _tables() or _FILE_TABLE not in _tables():
        return
    root_columns = _columns(_ROOT_TABLE)
    for column in (
        sa.Column("display_name_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("metadata_key_id", sa.String(length=64), nullable=True),
    ):
        if column.name not in root_columns:
            op.add_column(_ROOT_TABLE, column)

    file_columns = _columns(_FILE_TABLE)
    for column in (
        sa.Column("relative_path_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("display_name_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("metadata_key_id", sa.String(length=64), nullable=True),
        sa.Column("relative_path_blind_index", sa.LargeBinary(length=32), nullable=True),
        sa.Column(
            "relative_path_blind_index_key_id",
            sa.String(length=64),
            nullable=True,
        ),
    ):
        if column.name not in file_columns:
            op.add_column(_FILE_TABLE, column)


def _allow_ciphertext_only_writes() -> None:
    root_columns = _columns(_ROOT_TABLE)
    file_columns = _columns(_FILE_TABLE)
    if op.get_bind().dialect.name == "sqlite":
        if "display_name" in root_columns and not bool(root_columns["display_name"]["nullable"]):
            with op.batch_alter_table(_ROOT_TABLE) as batch:
                batch.alter_column(
                    "display_name",
                    existing_type=sa.String(length=500),
                    nullable=True,
                )
        if any(
            name in file_columns and not bool(file_columns[name]["nullable"])
            for name in ("relative_path", "display_name")
        ):
            with op.batch_alter_table(_FILE_TABLE) as batch:
                if "relative_path" in file_columns and not bool(
                    file_columns["relative_path"]["nullable"]
                ):
                    batch.alter_column(
                        "relative_path",
                        existing_type=sa.String(length=2_000),
                        nullable=True,
                    )
                if "display_name" in file_columns and not bool(
                    file_columns["display_name"]["nullable"]
                ):
                    batch.alter_column(
                        "display_name",
                        existing_type=sa.String(length=500),
                        nullable=True,
                    )
        return
    if "display_name" in root_columns and not bool(root_columns["display_name"]["nullable"]):
        op.alter_column(
            _ROOT_TABLE,
            "display_name",
            existing_type=sa.String(length=500),
            nullable=True,
        )
    for name, column_type in (
        ("relative_path", sa.String(length=2_000)),
        ("display_name", sa.String(length=500)),
    ):
        if name in file_columns and not bool(file_columns[name]["nullable"]):
            op.alter_column(
                _FILE_TABLE,
                name,
                existing_type=column_type,
                nullable=True,
            )


def _add_bridge_indexes() -> None:
    root_indexes = _index_names(_ROOT_TABLE)
    if _ROOT_ROTATION_INDEX not in root_indexes:
        op.create_index(
            _ROOT_ROTATION_INDEX,
            _ROOT_TABLE,
            ["tenant_id", "metadata_key_id", "id"],
        )
    file_indexes = _index_names(_FILE_TABLE)
    if _FILE_ROTATION_INDEX not in file_indexes:
        op.create_index(
            _FILE_ROTATION_INDEX,
            _FILE_TABLE,
            ["tenant_id", "metadata_key_id", "id"],
        )
    if _BLIND_INDEX_NAME not in file_indexes:
        op.create_index(
            _BLIND_INDEX_NAME,
            _FILE_TABLE,
            [
                "tenant_id",
                "collection_id",
                "source_root_id",
                "relative_path_blind_index",
            ],
            unique=True,
        )


def _add_checkpoint_table() -> None:
    if _CHECKPOINT_TABLE in _tables():
        return
    op.create_table(
        _CHECKPOINT_TABLE,
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("active_key_id", sa.String(length=64), nullable=False),
        sa.Column("blind_index_key_id", sa.String(length=64), nullable=False),
        sa.Column("last_root_id", sa.Uuid(), nullable=True),
        sa.Column("last_file_id", sa.Uuid(), nullable=True),
        sa.Column("roots_completed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("files_completed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','applying','verified','failed')",
            name="ck_collection_metadata_backfill_status",
        ),
        sa.CheckConstraint(
            "roots_completed >= 0 AND files_completed >= 0",
            name="ck_collection_metadata_backfill_counts",
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("REVOKE ALL ON TABLE collection_metadata_backfill_checkpoints FROM PUBLIC")


def _encrypted_rows() -> int:
    if _ROOT_TABLE not in _tables() or _FILE_TABLE not in _tables():
        return 0
    root_columns = _columns(_ROOT_TABLE)
    if "display_name_ciphertext" not in root_columns:
        return 0
    if "display_name" in root_columns:
        root_query = sa.text(
            "SELECT COUNT(*) FROM collection_source_roots "
            "WHERE display_name_ciphertext IS NOT NULL OR display_name IS NULL"
        )
    else:
        # A database created from the final ORM metadata can already be
        # ciphertext-only when Alembic stamps/replays this bridge revision.
        root_query = sa.text("SELECT COUNT(*) FROM collection_source_roots")
    file_columns = _columns(_FILE_TABLE)
    if "relative_path" in file_columns and "display_name" in file_columns:
        file_query = sa.text(
            "SELECT COUNT(*) FROM collection_files "
            "WHERE relative_path_ciphertext IS NOT NULL "
            "OR display_name_ciphertext IS NOT NULL "
            "OR relative_path_blind_index IS NOT NULL "
            "OR relative_path IS NULL OR display_name IS NULL"
        )
    else:
        file_query = sa.text("SELECT COUNT(*) FROM collection_files")
    root_count = op.get_bind().execute(root_query).scalar_one()
    file_count = op.get_bind().execute(file_query).scalar_one()
    return int(root_count) + int(file_count)


def upgrade() -> None:
    if _ROOT_TABLE not in _tables() or _FILE_TABLE not in _tables():
        return
    _add_bridge_columns()
    _allow_ciphertext_only_writes()
    _add_bridge_indexes()
    _add_checkpoint_table()


def downgrade() -> None:
    if _ROOT_TABLE not in _tables() or _FILE_TABLE not in _tables():
        return
    if _encrypted_rows() > 0:
        raise RuntimeError(
            "cannot downgrade collection metadata bridge while encrypted "
            "or ciphertext-only rows exist"
        )
    for name in (_BLIND_INDEX_NAME, _FILE_ROTATION_INDEX):
        if name in _index_names(_FILE_TABLE):
            op.drop_index(name, table_name=_FILE_TABLE)
    if _ROOT_ROTATION_INDEX in _index_names(_ROOT_TABLE):
        op.drop_index(_ROOT_ROTATION_INDEX, table_name=_ROOT_TABLE)
    if _CHECKPOINT_TABLE in _tables():
        op.drop_table(_CHECKPOINT_TABLE)
    file_columns = _columns(_FILE_TABLE)
    root_columns = _columns(_ROOT_TABLE)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(_FILE_TABLE) as batch:
            for name in (
                "relative_path_blind_index_key_id",
                "relative_path_blind_index",
                "metadata_key_id",
                "display_name_ciphertext",
                "relative_path_ciphertext",
            ):
                if name in file_columns:
                    batch.drop_column(name)
            if "relative_path" in file_columns:
                batch.alter_column(
                    "relative_path",
                    existing_type=sa.String(length=2_000),
                    nullable=False,
                )
            if "display_name" in file_columns:
                batch.alter_column(
                    "display_name",
                    existing_type=sa.String(length=500),
                    nullable=False,
                )
        with op.batch_alter_table(_ROOT_TABLE) as batch:
            for name in ("metadata_key_id", "display_name_ciphertext"):
                if name in root_columns:
                    batch.drop_column(name)
            if "display_name" in root_columns:
                batch.alter_column(
                    "display_name",
                    existing_type=sa.String(length=500),
                    nullable=False,
                )
        return
    for name in (
        "relative_path_blind_index_key_id",
        "relative_path_blind_index",
        "metadata_key_id",
        "display_name_ciphertext",
        "relative_path_ciphertext",
    ):
        if name in file_columns:
            op.drop_column(_FILE_TABLE, name)
    for name in ("metadata_key_id", "display_name_ciphertext"):
        if name in root_columns:
            op.drop_column(_ROOT_TABLE, name)
    op.alter_column(
        _FILE_TABLE,
        "relative_path",
        existing_type=sa.String(length=2_000),
        nullable=False,
    )
    op.alter_column(
        _FILE_TABLE,
        "display_name",
        existing_type=sa.String(length=500),
        nullable=False,
    )
    op.alter_column(
        _ROOT_TABLE,
        "display_name",
        existing_type=sa.String(length=500),
        nullable=False,
    )
