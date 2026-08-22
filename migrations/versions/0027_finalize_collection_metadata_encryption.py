"""Remove collection filename/path plaintext after the verified backfill.

Revision ID: 0027_finalize_collection_metadata_encryption
Revises: 0026_collection_metadata_encryption_bridge
Create Date: 2026-08-01

Existing databases must not upgrade to this revision until the bridge
backfill/verifier reports complete ciphertext coverage and no blind-index
collision. The migration fails closed instead of encrypting with a migration
process credential or retaining a plaintext fallback.
"""

from __future__ import annotations

from typing import Any, cast

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0027_finalize_collection_metadata_encryption"
down_revision = "0026_collection_metadata_encryption_bridge"
branch_labels = None
depends_on = None

_ROOT_TABLE = "collection_source_roots"
_FILE_TABLE = "collection_files"
_CHECKPOINT_TABLE = "collection_metadata_backfill_checkpoints"
_LEGACY_UNIQUE = "uq_collection_file_relative_path"
_ROOT_KEY_CHECK = "ck_collection_source_roots_metadata_key"
_ROOT_CIPHERTEXT_CHECK = "ck_collection_source_roots_metadata_ciphertext"
_FILE_KEY_CHECK = "ck_collection_files_metadata_key"
_FILE_PATH_CIPHERTEXT_CHECK = "ck_collection_files_path_ciphertext"
_FILE_NAME_CIPHERTEXT_CHECK = "ck_collection_files_name_ciphertext"
_FILE_BLIND_CHECK = "ck_collection_files_path_blind_index"
_FILE_BLIND_KEY_CHECK = "ck_collection_files_path_blind_index_key"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> dict[str, dict[str, Any]]:
    return {
        str(column["name"]): cast(dict[str, Any], column)
        for column in inspect(op.get_bind()).get_columns(table)
    }


def _check_names(table: str) -> set[str]:
    return {
        str(row["name"])
        for row in inspect(op.get_bind()).get_check_constraints(table)
        if row.get("name")
    }


def _unique_names(table: str) -> set[str]:
    return {
        str(row["name"])
        for row in inspect(op.get_bind()).get_unique_constraints(table)
        if row.get("name")
    }


def _assert_backfill_complete() -> None:
    root_columns = _columns(_ROOT_TABLE)
    file_columns = _columns(_FILE_TABLE)
    required_root = {"display_name_ciphertext", "metadata_key_id"}
    required_file = {
        "relative_path_ciphertext",
        "display_name_ciphertext",
        "metadata_key_id",
        "relative_path_blind_index",
        "relative_path_blind_index_key_id",
    }
    if not required_root <= set(root_columns) or not required_file <= set(file_columns):
        raise RuntimeError("collection metadata encryption bridge columns are missing")
    missing_root = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM collection_source_roots "
                "WHERE display_name_ciphertext IS NULL OR metadata_key_id IS NULL"
            )
        )
        .scalar_one()
    )
    missing_file = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM collection_files "
                "WHERE relative_path_ciphertext IS NULL "
                "OR display_name_ciphertext IS NULL OR metadata_key_id IS NULL "
                "OR relative_path_blind_index IS NULL "
                "OR relative_path_blind_index_key_id IS NULL"
            )
        )
        .scalar_one()
    )
    invalid_ciphertext = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT (SELECT COUNT(*) FROM collection_source_roots "
                "WHERE length(display_name_ciphertext) NOT BETWEEN 29 AND 2028) + "
                "(SELECT COUNT(*) FROM collection_files "
                "WHERE length(relative_path_ciphertext) NOT BETWEEN 29 AND 8028 "
                "OR length(display_name_ciphertext) NOT BETWEEN 29 AND 2028 "
                "OR length(relative_path_blind_index) <> 32)"
            )
        )
        .scalar_one()
    )
    if int(missing_root) or int(missing_file) or int(invalid_ciphertext):
        raise RuntimeError(
            "collection metadata plaintext removal requires a complete verified backfill"
        )
    data_rows = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT (SELECT COUNT(*) FROM collection_source_roots) + "
                "(SELECT COUNT(*) FROM collection_files)"
            )
        )
        .scalar_one()
    )
    if not int(data_rows):
        return
    if _CHECKPOINT_TABLE not in _tables():
        raise RuntimeError(
            "collection metadata plaintext removal requires verified tenant checkpoints"
        )
    invalid_tenants = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM ("
                "SELECT tenant_id FROM collection_source_roots "
                "UNION SELECT tenant_id FROM collection_files"
                ") AS data_tenants "
                "LEFT JOIN collection_metadata_backfill_checkpoints AS checkpoints "
                "ON checkpoints.tenant_id = data_tenants.tenant_id "
                "WHERE checkpoints.tenant_id IS NULL "
                "OR checkpoints.status <> 'verified' "
                "OR checkpoints.completed_at IS NULL "
                "OR checkpoints.roots_completed <> ("
                "SELECT COUNT(*) FROM collection_source_roots AS roots "
                "WHERE roots.tenant_id = data_tenants.tenant_id"
                ") OR checkpoints.files_completed <> ("
                "SELECT COUNT(*) FROM collection_files AS files "
                "WHERE files.tenant_id = data_tenants.tenant_id"
                ")"
            )
        )
        .scalar_one()
    )
    root_key_mismatches = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM collection_source_roots AS roots "
                "JOIN collection_metadata_backfill_checkpoints AS checkpoints "
                "ON checkpoints.tenant_id = roots.tenant_id "
                "WHERE roots.metadata_key_id <> checkpoints.active_key_id"
            )
        )
        .scalar_one()
    )
    file_key_mismatches = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM collection_files AS files "
                "JOIN collection_metadata_backfill_checkpoints AS checkpoints "
                "ON checkpoints.tenant_id = files.tenant_id "
                "WHERE files.metadata_key_id <> checkpoints.active_key_id "
                "OR files.relative_path_blind_index_key_id "
                "<> checkpoints.blind_index_key_id"
            )
        )
        .scalar_one()
    )
    if int(invalid_tenants) or int(root_key_mismatches) or int(file_key_mismatches):
        raise RuntimeError(
            "collection metadata plaintext removal requires verified tenant checkpoints"
        )


def _finalize_postgresql() -> None:
    if _LEGACY_UNIQUE in _unique_names(_FILE_TABLE):
        op.drop_constraint(_LEGACY_UNIQUE, _FILE_TABLE, type_="unique")
    root_columns = _columns(_ROOT_TABLE)
    file_columns = _columns(_FILE_TABLE)
    if "display_name" in root_columns:
        op.drop_column(_ROOT_TABLE, "display_name")
    for name in ("relative_path", "display_name"):
        if name in file_columns:
            op.drop_column(_FILE_TABLE, name)
    op.alter_column(
        _ROOT_TABLE,
        "display_name_ciphertext",
        existing_type=sa.LargeBinary(),
        nullable=False,
    )
    op.alter_column(
        _ROOT_TABLE,
        "metadata_key_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    for name, column_type in (
        ("relative_path_ciphertext", sa.LargeBinary()),
        ("display_name_ciphertext", sa.LargeBinary()),
        ("metadata_key_id", sa.String(length=64)),
        ("relative_path_blind_index", sa.LargeBinary(length=32)),
        ("relative_path_blind_index_key_id", sa.String(length=64)),
    ):
        op.alter_column(
            _FILE_TABLE,
            name,
            existing_type=column_type,
            nullable=False,
        )


def _finalize_sqlite() -> None:
    root_columns = _columns(_ROOT_TABLE)
    file_columns = _columns(_FILE_TABLE)
    file_unique_names = _unique_names(_FILE_TABLE)
    with op.batch_alter_table(_ROOT_TABLE) as batch:
        if "display_name" in root_columns:
            batch.drop_column("display_name")
        batch.alter_column(
            "display_name_ciphertext",
            existing_type=sa.LargeBinary(),
            nullable=False,
        )
        batch.alter_column(
            "metadata_key_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
    with op.batch_alter_table(_FILE_TABLE) as batch:
        if _LEGACY_UNIQUE in file_unique_names:
            batch.drop_constraint(_LEGACY_UNIQUE, type_="unique")
        for name in ("relative_path", "display_name"):
            if name in file_columns:
                batch.drop_column(name)
        for name, column_type in (
            ("relative_path_ciphertext", sa.LargeBinary()),
            ("display_name_ciphertext", sa.LargeBinary()),
            ("metadata_key_id", sa.String(length=64)),
            ("relative_path_blind_index", sa.LargeBinary(length=32)),
            ("relative_path_blind_index_key_id", sa.String(length=64)),
        ):
            batch.alter_column(
                name,
                existing_type=column_type,
                nullable=False,
            )


def _add_checks() -> None:
    root_checks = _check_names(_ROOT_TABLE)
    file_checks = _check_names(_FILE_TABLE)
    root_contracts = (
        (
            _ROOT_KEY_CHECK,
            "length(metadata_key_id) BETWEEN 1 AND 64",
        ),
        (
            _ROOT_CIPHERTEXT_CHECK,
            "length(display_name_ciphertext) BETWEEN 29 AND 2028",
        ),
    )
    file_contracts = (
        (_FILE_KEY_CHECK, "length(metadata_key_id) BETWEEN 1 AND 64"),
        (
            _FILE_PATH_CIPHERTEXT_CHECK,
            "length(relative_path_ciphertext) BETWEEN 29 AND 8028",
        ),
        (
            _FILE_NAME_CIPHERTEXT_CHECK,
            "length(display_name_ciphertext) BETWEEN 29 AND 2028",
        ),
        (_FILE_BLIND_CHECK, "length(relative_path_blind_index) = 32"),
        (
            _FILE_BLIND_KEY_CHECK,
            "length(relative_path_blind_index_key_id) BETWEEN 1 AND 64",
        ),
    )
    if op.get_bind().dialect.name == "sqlite":
        missing_root = [item for item in root_contracts if item[0] not in root_checks]
        if missing_root:
            with op.batch_alter_table(_ROOT_TABLE) as batch:
                for name, expression in missing_root:
                    batch.create_check_constraint(name, expression)
        missing_file = [item for item in file_contracts if item[0] not in file_checks]
        if missing_file:
            with op.batch_alter_table(_FILE_TABLE) as batch:
                for name, expression in missing_file:
                    batch.create_check_constraint(name, expression)
        return
    for name, expression in root_contracts:
        if name not in root_checks:
            op.create_check_constraint(name, _ROOT_TABLE, expression)
    for name, expression in file_contracts:
        if name not in file_checks:
            op.create_check_constraint(name, _FILE_TABLE, expression)


def _drop_final_checks() -> None:
    root_contracts = (_ROOT_KEY_CHECK, _ROOT_CIPHERTEXT_CHECK)
    file_contracts = (
        _FILE_KEY_CHECK,
        _FILE_PATH_CIPHERTEXT_CHECK,
        _FILE_NAME_CIPHERTEXT_CHECK,
        _FILE_BLIND_CHECK,
        _FILE_BLIND_KEY_CHECK,
    )
    root_checks = _check_names(_ROOT_TABLE)
    file_checks = _check_names(_FILE_TABLE)
    if op.get_bind().dialect.name == "sqlite":
        removable_root = [name for name in root_contracts if name in root_checks]
        if removable_root:
            with op.batch_alter_table(_ROOT_TABLE) as batch:
                for name in removable_root:
                    batch.drop_constraint(name, type_="check")
        removable_file = [name for name in file_contracts if name in file_checks]
        if removable_file:
            with op.batch_alter_table(_FILE_TABLE) as batch:
                for name in removable_file:
                    batch.drop_constraint(name, type_="check")
        return
    for name in root_contracts:
        if name in root_checks:
            op.drop_constraint(name, _ROOT_TABLE, type_="check")
    for name in file_contracts:
        if name in file_checks:
            op.drop_constraint(name, _FILE_TABLE, type_="check")


def upgrade() -> None:
    if _ROOT_TABLE not in _tables() or _FILE_TABLE not in _tables():
        return
    _assert_backfill_complete()
    root_columns = _columns(_ROOT_TABLE)
    file_columns = _columns(_FILE_TABLE)
    already_final = (
        "display_name" not in root_columns
        and "relative_path" not in file_columns
        and "display_name" not in file_columns
        and all(
            not bool(root_columns[name]["nullable"])
            for name in ("display_name_ciphertext", "metadata_key_id")
        )
        and all(
            not bool(file_columns[name]["nullable"])
            for name in (
                "relative_path_ciphertext",
                "display_name_ciphertext",
                "metadata_key_id",
                "relative_path_blind_index",
                "relative_path_blind_index_key_id",
            )
        )
    )
    if not already_final:
        if op.get_bind().dialect.name == "sqlite":
            _finalize_sqlite()
        else:
            _finalize_postgresql()
    _add_checks()


def downgrade() -> None:
    if _ROOT_TABLE not in _tables() or _FILE_TABLE not in _tables():
        return
    # These constraints are owned by this finalization revision. Remove them
    # before the bridge downgrade removes their ciphertext columns.
    _drop_final_checks()
    root_columns = _columns(_ROOT_TABLE)
    file_columns = _columns(_FILE_TABLE)
    if "display_name" not in root_columns:
        op.add_column(
            _ROOT_TABLE,
            sa.Column("display_name", sa.String(length=500), nullable=True),
        )
    if "relative_path" not in file_columns:
        op.add_column(
            _FILE_TABLE,
            sa.Column("relative_path", sa.String(length=2_000), nullable=True),
        )
    if "display_name" not in file_columns:
        op.add_column(
            _FILE_TABLE,
            sa.Column("display_name", sa.String(length=500), nullable=True),
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(_ROOT_TABLE) as batch:
            for name, column_type in (
                ("display_name_ciphertext", sa.LargeBinary()),
                ("metadata_key_id", sa.String(length=64)),
            ):
                batch.alter_column(name, existing_type=column_type, nullable=True)
        with op.batch_alter_table(_FILE_TABLE) as batch:
            for name, column_type in (
                ("relative_path_ciphertext", sa.LargeBinary()),
                ("display_name_ciphertext", sa.LargeBinary()),
                ("metadata_key_id", sa.String(length=64)),
                ("relative_path_blind_index", sa.LargeBinary(length=32)),
                ("relative_path_blind_index_key_id", sa.String(length=64)),
            ):
                batch.alter_column(name, existing_type=column_type, nullable=True)
            if _LEGACY_UNIQUE not in _unique_names(_FILE_TABLE):
                batch.create_unique_constraint(
                    _LEGACY_UNIQUE,
                    ["collection_id", "source_root_id", "relative_path"],
                )
        return
    op.alter_column(
        _ROOT_TABLE,
        "display_name_ciphertext",
        existing_type=sa.LargeBinary(),
        nullable=True,
    )
    op.alter_column(
        _ROOT_TABLE,
        "metadata_key_id",
        existing_type=sa.String(length=64),
        nullable=True,
    )
    for name, column_type in (
        ("relative_path_ciphertext", sa.LargeBinary()),
        ("display_name_ciphertext", sa.LargeBinary()),
        ("metadata_key_id", sa.String(length=64)),
        ("relative_path_blind_index", sa.LargeBinary(length=32)),
        ("relative_path_blind_index_key_id", sa.String(length=64)),
    ):
        op.alter_column(
            _FILE_TABLE,
            name,
            existing_type=column_type,
            nullable=True,
        )
    if _LEGACY_UNIQUE not in _unique_names(_FILE_TABLE):
        op.create_unique_constraint(
            _LEGACY_UNIQUE,
            _FILE_TABLE,
            ["collection_id", "source_root_id", "relative_path"],
        )
