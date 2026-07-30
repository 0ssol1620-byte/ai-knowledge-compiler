"""Enforce one active semantic, note, and relation revision.

Revision ID: 0017_active_revision_pointers
Revises: 0016_immutable_document_versions
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0017_active_revision_pointers"
down_revision = "0016_immutable_document_versions"
branch_labels = None
depends_on = None

SEMANTIC_TABLE = "document_semantic_classifications"
NOTE_TABLE = "knowledge_notes"
RELATION_TABLE = "relations"

SEMANTIC_INDEX = "document_semantic_classifications_one_active_idx"
NOTE_INDEX = "knowledge_notes_one_active_revision_idx"
RELATION_INDEX = "relations_one_active_revision_idx"


def _index_names(table: str) -> set[str]:
    return {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes(table)
        if index.get("name")
    }


def _assert_no_duplicate_active_pointers(
    *,
    table: str,
    pointer_columns: tuple[str, ...],
    where_sql: str,
    error_code: str,
) -> None:
    columns = ", ".join(pointer_columns)
    query = f"""
        SELECT {columns}, COUNT(*) AS active_count
        FROM {table}
        WHERE {where_sql}
        GROUP BY {columns}
        HAVING COUNT(*) > 1
        LIMIT 1
        """  # noqa: S608 -- identifiers are closed migration constants.
    duplicate = op.get_bind().execute(sa.text(query)).mappings().first()
    if duplicate is not None:
        values = ",".join(f"{column}={duplicate[column]!s}" for column in pointer_columns)
        raise RuntimeError(f"{error_code}:{values}")


def _create_partial_unique_index(
    *,
    name: str,
    table: str,
    columns: tuple[str, ...],
    postgresql_where: str,
    sqlite_where: str,
) -> None:
    if name in _index_names(table):
        return
    dialect = op.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError(f"active_knowledge_revision_pointer_dialect_unsupported:{dialect}")
    kwargs: dict[str, object] = {"unique": True}
    if dialect == "postgresql":
        kwargs["postgresql_where"] = sa.text(postgresql_where)
    else:
        kwargs["sqlite_where"] = sa.text(sqlite_where)
    op.create_index(name, table, list(columns), **kwargs)


def upgrade() -> None:
    _assert_no_duplicate_active_pointers(
        table=SEMANTIC_TABLE,
        pointer_columns=("tenant_id", "document_id", "document_version"),
        where_sql="is_active",
        error_code="duplicate_active_document_semantic_classification",
    )
    _assert_no_duplicate_active_pointers(
        table=NOTE_TABLE,
        pointer_columns=(
            "tenant_id",
            "project_id",
            "document_id",
            "document_version",
            "stable_key",
        ),
        where_sql="is_active AND document_id IS NOT NULL",
        error_code="duplicate_active_knowledge_note_revision",
    )
    _assert_no_duplicate_active_pointers(
        table=RELATION_TABLE,
        pointer_columns=(
            "tenant_id",
            "project_id",
            "document_id",
            "document_version",
            "source_relation_key",
        ),
        where_sql=("is_active AND document_id IS NOT NULL AND source_relation_key IS NOT NULL"),
        error_code="duplicate_active_relation_revision",
    )

    _create_partial_unique_index(
        name=SEMANTIC_INDEX,
        table=SEMANTIC_TABLE,
        columns=("tenant_id", "document_id", "document_version"),
        postgresql_where="is_active",
        sqlite_where="is_active = 1",
    )
    _create_partial_unique_index(
        name=NOTE_INDEX,
        table=NOTE_TABLE,
        columns=(
            "tenant_id",
            "project_id",
            "document_id",
            "document_version",
            "stable_key",
        ),
        postgresql_where="is_active AND document_id IS NOT NULL",
        sqlite_where="is_active = 1 AND document_id IS NOT NULL",
    )
    _create_partial_unique_index(
        name=RELATION_INDEX,
        table=RELATION_TABLE,
        columns=(
            "tenant_id",
            "project_id",
            "document_id",
            "document_version",
            "source_relation_key",
        ),
        postgresql_where=(
            "is_active AND document_id IS NOT NULL AND source_relation_key IS NOT NULL"
        ),
        sqlite_where=(
            "is_active = 1 AND document_id IS NOT NULL AND source_relation_key IS NOT NULL"
        ),
    )


def downgrade() -> None:
    for table, name in (
        (RELATION_TABLE, RELATION_INDEX),
        (NOTE_TABLE, NOTE_INDEX),
        (SEMANTIC_TABLE, SEMANTIC_INDEX),
    ):
        if name in _index_names(table):
            op.drop_index(name, table_name=table)
