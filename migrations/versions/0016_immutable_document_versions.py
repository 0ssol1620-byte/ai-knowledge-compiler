"""Make source uploads append-only document versions with immutable snapshots.

Revision ID: 0016_immutable_document_versions
Revises: 0015_project_access
Create Date: 2026-07-30
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0016_immutable_document_versions"
down_revision = "0015_project_access"
branch_labels = None
depends_on = None

_ACTIVE_UPLOAD_INDEX = "upload_sessions_one_active_document_version_idx"
_SOURCE_INDEX = "document_versions_source_idx"
_SOURCE_FK = "fk_document_versions_source_file"
_ANALYSIS_VERSION_UNIQUE = "uq_analysis_tasks_tenant_id_document_id_document_version"
_ANALYSIS_LEGACY_UNIQUE = "uq_analysis_tasks_tenant_id_document_id_source_file_id"


def _columns(table: str) -> set[str]:
    return {str(item["name"]) for item in inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {
        str(item["name"]) for item in inspect(op.get_bind()).get_indexes(table) if item.get("name")
    }


def _check_constraints(table: str) -> set[str]:
    return {
        str(item["name"])
        for item in inspect(op.get_bind()).get_check_constraints(table)
        if item.get("name")
    }


def _drop_legacy_upload_unique() -> None:
    bind = op.get_bind()
    match = next(
        (
            item
            for item in inspect(bind).get_unique_constraints("upload_sessions")
            if set(item.get("column_names") or ()) == {"tenant_id", "document_id"}
        ),
        None,
    )
    if match is None:
        return
    name = match.get("name")
    if bind.dialect.name == "sqlite":
        naming = {
            "uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s",
        }
        with op.batch_alter_table("upload_sessions", naming_convention=naming) as batch:
            batch.drop_constraint(
                str(name or "uq_upload_sessions_tenant_id_document_id"),
                type_="unique",
            )
        return
    if not name:
        raise RuntimeError("legacy upload unique constraint has no database name")
    op.drop_constraint(str(name), "upload_sessions", type_="unique")


def _unique_constraint(
    table: str,
    columns: tuple[str, ...],
) -> dict[str, object] | None:
    return next(
        (
            item
            for item in inspect(op.get_bind()).get_unique_constraints(table)
            if tuple(item.get("column_names") or ()) == columns
        ),
        None,
    )


def _drop_unique(
    table: str,
    columns: tuple[str, ...],
    *,
    fallback_name: str,
) -> None:
    match = _unique_constraint(table, columns)
    if match is None:
        return
    bind = op.get_bind()
    name = match.get("name")
    if bind.dialect.name == "sqlite":
        naming = {
            "uq": ("uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s_%(column_2_name)s"),
        }
        with op.batch_alter_table(
            table,
            naming_convention=naming,
        ) as batch:
            batch.drop_constraint(
                str(name or fallback_name),
                type_="unique",
            )
        return
    if not name:
        raise RuntimeError(f"{table} unique constraint has no database name")
    op.drop_constraint(str(name), table, type_="unique")


def _create_unique(
    table: str,
    columns: tuple[str, ...],
    *,
    name: str,
) -> None:
    if _unique_constraint(table, columns) is not None:
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.create_unique_constraint(name, list(columns))
        return
    op.create_unique_constraint(name, table, list(columns))


def _add_columns() -> None:
    upload_columns = _columns("upload_sessions")
    if "document_version" not in upload_columns:
        op.add_column(
            "upload_sessions",
            sa.Column(
                "document_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )
    analysis_columns = _columns("analysis_tasks")
    if "document_version" not in analysis_columns:
        op.add_column(
            "analysis_tasks",
            sa.Column(
                "document_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )

    version_columns = _columns("document_versions")
    additions = (
        sa.Column("source_file_id", sa.Uuid(), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_filename", sa.String(length=500), nullable=True),
        sa.Column("source_mime_type", sa.String(length=160), nullable=True),
        sa.Column("source_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("cir_snapshot_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "archived_objects",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("input_revision_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "normalization_revision",
            sa.String(length=120),
            nullable=True,
        ),
        sa.Column(
            "akmp_schema_version",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'1.0'"),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'source_verified'"),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in additions:
        if column.name not in version_columns:
            op.add_column("document_versions", column)


def _backfill_versions() -> None:
    bind = op.get_bind()
    sources = {
        row.id: row
        for row in bind.execute(
            sa.text(
                "SELECT id, tenant_id, safe_filename, mime_type, size_bytes, sha256 "
                "FROM source_files"
            )
        ).mappings()
    }
    existing = {
        (row.document_id, int(row.version)): row
        for row in bind.execute(
            sa.text(
                "SELECT id, document_id, version, cir_object_key, source_file_id "
                "FROM document_versions"
            )
        ).mappings()
    }
    now = datetime.now(UTC)
    documents = list(
        bind.execute(
            sa.text(
                "SELECT id, tenant_id, source_file_id, active_version "
                "FROM documents WHERE source_file_id IS NOT NULL"
            )
        ).mappings()
    )
    for document in documents:
        key = (document.id, int(document.active_version))
        source = sources.get(document.source_file_id)
        if source is None:
            raise RuntimeError(f"document {document.id} has no immutable source row")
        current = existing.get(key)
        values = {
            "source_file_id": source.id,
            "source_sha256": source.sha256,
            "source_filename": source.safe_filename,
            "source_mime_type": source.mime_type,
            "source_size_bytes": source.size_bytes,
        }
        if current is None:
            bind.execute(
                sa.text(
                    "INSERT INTO document_versions "
                    "(id, tenant_id, document_id, version, source_file_id, "
                    "source_sha256, source_filename, source_mime_type, "
                    "source_size_bytes, cir_object_key, cir_snapshot_sha256, "
                    "input_revision_hash, policy_version, model_revision, "
                    "prompt_revision, status, archived_at, created_at) "
                    "VALUES (:id, :tenant_id, :document_id, :version, "
                    ":source_file_id, :source_sha256, :source_filename, "
                    ":source_mime_type, :source_size_bytes, NULL, NULL, NULL, "
                    "'unprocessed-upload-v1', 'unprocessed', NULL, "
                    "'source_verified', NULL, :created_at)"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": document.tenant_id,
                    "document_id": document.id,
                    "version": int(document.active_version),
                    **values,
                    "created_at": now,
                },
            )
            continue
        bind.execute(
            sa.text(
                "UPDATE document_versions SET "
                "source_file_id=:source_file_id, source_sha256=:source_sha256, "
                "source_filename=:source_filename, source_mime_type=:source_mime_type, "
                "source_size_bytes=:source_size_bytes, "
                "status=CASE WHEN cir_object_key IS NULL THEN 'source_verified' "
                "ELSE 'processed' END WHERE id=:id"
            ),
            {**values, "id": current.id},
        )

    for row in bind.execute(
        sa.text(
            "SELECT dv.id FROM document_versions dv "
            "JOIN documents d ON d.id=dv.document_id AND d.tenant_id=dv.tenant_id "
            "WHERE dv.version < d.active_version"
        )
    ).mappings():
        bind.execute(
            sa.text(
                "UPDATE document_versions SET status='archived', archived_at=:now WHERE id=:id"
            ),
            {"id": row.id, "now": now},
        )


def _add_constraints_and_indexes() -> None:
    bind = op.get_bind()
    _drop_legacy_upload_unique()
    _drop_unique(
        "analysis_tasks",
        ("tenant_id", "document_id", "source_file_id"),
        fallback_name=_ANALYSIS_LEGACY_UNIQUE,
    )
    _create_unique(
        "analysis_tasks",
        ("tenant_id", "document_id", "document_version"),
        name=_ANALYSIS_VERSION_UNIQUE,
    )
    if _ACTIVE_UPLOAD_INDEX not in _indexes("upload_sessions"):
        op.create_index(
            _ACTIVE_UPLOAD_INDEX,
            "upload_sessions",
            ["tenant_id", "document_id", "document_version"],
            unique=True,
            postgresql_where=sa.text("status IN ('initiated','uploaded')"),
            sqlite_where=sa.text("status IN ('initiated','uploaded')"),
        )
    if _SOURCE_INDEX not in _indexes("document_versions"):
        op.create_index(
            _SOURCE_INDEX,
            "document_versions",
            ["tenant_id", "source_file_id"],
            unique=False,
        )
    foreign_keys = inspect(bind).get_foreign_keys("document_versions")
    if not any(
        tuple(item.get("constrained_columns") or ()) == ("tenant_id", "source_file_id")
        for item in foreign_keys
    ):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("document_versions") as batch:
                batch.create_foreign_key(
                    _SOURCE_FK,
                    "source_files",
                    ["tenant_id", "source_file_id"],
                    ["tenant_id", "id"],
                    ondelete="RESTRICT",
                )
        else:
            op.create_foreign_key(
                _SOURCE_FK,
                "document_versions",
                "source_files",
                ["tenant_id", "source_file_id"],
                ["tenant_id", "id"],
                ondelete="RESTRICT",
            )


def upgrade() -> None:
    _add_columns()
    _backfill_versions()
    _add_constraints_and_indexes()


def _drop_source_foreign_key() -> None:
    bind = op.get_bind()
    match = next(
        (
            item
            for item in inspect(bind).get_foreign_keys("document_versions")
            if tuple(item.get("constrained_columns") or ()) == ("tenant_id", "source_file_id")
        ),
        None,
    )
    if match is None:
        return
    name = match.get("name")
    if bind.dialect.name == "sqlite":
        naming = {
            "fk": ("fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"),
        }
        with op.batch_alter_table(
            "document_versions",
            naming_convention=naming,
        ) as batch:
            batch.drop_constraint(
                str(name or "fk_document_versions_tenant_id_source_files"),
                type_="foreignkey",
            )
        return
    if not name:
        raise RuntimeError("document version source foreign key has no database name")
    op.drop_constraint(str(name), "document_versions", type_="foreignkey")


def downgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            "SELECT tenant_id, document_id, COUNT(*) AS count_rows "
            "FROM upload_sessions GROUP BY tenant_id, document_id HAVING COUNT(*) > 1"
        )
    ).first()
    if duplicates is not None:
        raise RuntimeError(
            "cannot downgrade immutable document versions with multi-version uploads"
        )
    analysis_duplicates = bind.execute(
        sa.text(
            "SELECT tenant_id, document_id, source_file_id, COUNT(*) AS count_rows "
            "FROM analysis_tasks "
            "GROUP BY tenant_id, document_id, source_file_id "
            "HAVING COUNT(*) > 1"
        )
    ).first()
    if analysis_duplicates is not None:
        raise RuntimeError("cannot downgrade analysis revisions that reuse one source")
    if _ACTIVE_UPLOAD_INDEX in _indexes("upload_sessions"):
        op.drop_index(_ACTIVE_UPLOAD_INDEX, table_name="upload_sessions")
    if _SOURCE_INDEX in _indexes("document_versions"):
        op.drop_index(_SOURCE_INDEX, table_name="document_versions")
    _drop_source_foreign_key()
    if "ck_document_versions_status" in _check_constraints("document_versions"):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("document_versions") as batch:
                batch.drop_constraint(
                    "ck_document_versions_status",
                    type_="check",
                )
        else:
            op.drop_constraint(
                "ck_document_versions_status",
                "document_versions",
                type_="check",
            )
    version_columns = _columns("document_versions")
    removable = (
        "archived_at",
        "status",
        "input_revision_hash",
        "akmp_schema_version",
        "normalization_revision",
        "cir_snapshot_sha256",
        "archived_objects",
        "source_size_bytes",
        "source_mime_type",
        "source_filename",
        "source_sha256",
        "source_file_id",
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("document_versions") as batch:
            for name in removable:
                if name in version_columns:
                    batch.drop_column(name)
    else:
        for name in removable:
            if name in version_columns:
                op.drop_column("document_versions", name)
    if "document_version" in _columns("upload_sessions"):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("upload_sessions") as batch:
                batch.drop_column("document_version")
        else:
            op.drop_column("upload_sessions", "document_version")
    if "document_version" in _columns("analysis_tasks"):
        _drop_unique(
            "analysis_tasks",
            ("tenant_id", "document_id", "document_version"),
            fallback_name=_ANALYSIS_VERSION_UNIQUE,
        )
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("analysis_tasks") as batch:
                batch.drop_column("document_version")
        else:
            op.drop_column("analysis_tasks", "document_version")
        _create_unique(
            "analysis_tasks",
            ("tenant_id", "document_id", "source_file_id"),
            name=_ANALYSIS_LEGACY_UNIQUE,
        )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "upload_sessions",
            naming_convention={
                "uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s",
            },
        ) as batch:
            batch.create_unique_constraint(
                "uq_upload_sessions_tenant_id_document_id",
                ["tenant_id", "document_id"],
            )
    else:
        op.create_unique_constraint(
            "uq_upload_sessions_tenant_id_document_id",
            "upload_sessions",
            ["tenant_id", "document_id"],
        )
