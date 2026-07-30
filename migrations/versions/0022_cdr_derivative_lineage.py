"""Add immutable CDR derivative lineage to source files.

Revision ID: 0022_cdr_derivative_lineage
Revises: 0021_model_lifecycle
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0022_cdr_derivative_lineage"
down_revision = "0021_model_lifecycle"
branch_labels = None
depends_on = None

TABLE = "source_files"


def _column_names() -> list[str]:
    return [str(column["name"]) for column in inspect(op.get_bind()).get_columns(TABLE)]


def upgrade() -> None:
    columns: tuple[tuple[str, sa.Column[object]], ...] = (
        (
            "cdr_status",
            sa.Column(
                "cdr_status",
                sa.String(length=32),
                nullable=False,
                server_default="not_requested",
            ),
        ),
        ("cdr_provider", sa.Column("cdr_provider", sa.String(length=80))),
        ("cdr_revision", sa.Column("cdr_revision", sa.String(length=160))),
        (
            "sanitized_storage_key",
            sa.Column("sanitized_storage_key", sa.String(length=500)),
        ),
        (
            "sanitized_sha256",
            sa.Column("sanitized_sha256", sa.String(length=64)),
        ),
        (
            "sanitized_size_bytes",
            sa.Column("sanitized_size_bytes", sa.Integer()),
        ),
    )
    existing_columns = set(_column_names())
    for name, column in columns:
        if name not in existing_columns:
            op.add_column(TABLE, column)

    inspector = inspect(op.get_bind())
    unique_names = {
        str(item["name"]) for item in inspector.get_unique_constraints(TABLE) if item.get("name")
    }
    check_names = {
        str(item["name"]) for item in inspector.get_check_constraints(TABLE) if item.get("name")
    }
    missing_unique = "uq_source_files_sanitized_storage_key" not in unique_names
    missing_status = "ck_source_files_cdr_status" not in check_names
    missing_shape = "ck_source_files_cdr_derivative_shape" not in check_names
    if missing_unique or missing_status or missing_shape:
        with op.batch_alter_table(
            TABLE,
            partial_reordering=[tuple(_column_names())],
        ) as batch:
            if missing_unique:
                batch.create_unique_constraint(
                    "uq_source_files_sanitized_storage_key",
                    ["sanitized_storage_key"],
                )
            if missing_status:
                batch.create_check_constraint(
                    "ck_source_files_cdr_status",
                    "cdr_status IN "
                    "('not_requested','sanitized','unsupported',"
                    "'unavailable','rejected')",
                )
            if missing_shape:
                batch.create_check_constraint(
                    "ck_source_files_cdr_derivative_shape",
                    "(cdr_status = 'sanitized' "
                    "AND sanitized_storage_key IS NOT NULL "
                    "AND sanitized_sha256 IS NOT NULL "
                    "AND length(sanitized_sha256) = 64 "
                    "AND sanitized_size_bytes > 0 "
                    "AND cdr_provider IS NOT NULL "
                    "AND cdr_revision IS NOT NULL) OR "
                    "(cdr_status <> 'sanitized' "
                    "AND sanitized_storage_key IS NULL "
                    "AND sanitized_sha256 IS NULL "
                    "AND sanitized_size_bytes IS NULL)",
                )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    unique_names = {
        str(item["name"]) for item in inspector.get_unique_constraints(TABLE) if item.get("name")
    }
    check_names = {
        str(item["name"]) for item in inspector.get_check_constraints(TABLE) if item.get("name")
    }
    with op.batch_alter_table(
        TABLE,
        partial_reordering=[tuple(_column_names())],
    ) as batch:
        if "ck_source_files_cdr_derivative_shape" in check_names:
            batch.drop_constraint(
                "ck_source_files_cdr_derivative_shape",
                type_="check",
            )
        if "ck_source_files_cdr_status" in check_names:
            batch.drop_constraint("ck_source_files_cdr_status", type_="check")
        if "uq_source_files_sanitized_storage_key" in unique_names:
            batch.drop_constraint(
                "uq_source_files_sanitized_storage_key",
                type_="unique",
            )

    existing_columns = set(_column_names())
    for column in (
        "sanitized_size_bytes",
        "sanitized_sha256",
        "sanitized_storage_key",
        "cdr_revision",
        "cdr_provider",
        "cdr_status",
    ):
        if column in existing_columns:
            op.drop_column(TABLE, column)
