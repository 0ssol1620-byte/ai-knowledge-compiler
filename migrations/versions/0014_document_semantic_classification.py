"""Persist semantic classification and immutable knowledge compile revisions.

Revision ID: 0014_document_semantic_classification
Revises: 0013_page_attempts
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from akc_api.models import DocumentSemanticClassification
from alembic import op
from sqlalchemy import inspect

revision = "0014_document_semantic_classification"
down_revision = "0013_page_attempts"
branch_labels = None
depends_on = None

DISPATCH_ROLE = "akc_dispatch_worker"
TABLE = "document_semantic_classifications"
NOTE_TABLE = "knowledge_notes"
RELATION_TABLE = "relations"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {
        str(column["name"])
        for column in inspect(op.get_bind()).get_columns(table)
    }


def _unique_name(table: str, columns: set[str]) -> str | None:
    for constraint in inspect(op.get_bind()).get_unique_constraints(table):
        if set(constraint.get("column_names") or ()) == columns:
            name = constraint.get("name")
            return str(name) if name else None
    return None


def _index_names(table: str) -> set[str]:
    return {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes(table)
        if index.get("name")
    }


def _create_unique_constraint(
    name: str,
    table: str,
    columns: list[str],
) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.create_unique_constraint(name, columns)
        return
    op.create_unique_constraint(name, table, columns)


def _add_compile_revision_columns() -> None:
    note_columns = {
        "document_id": sa.Column("document_id", sa.Uuid(), nullable=True),
        "document_version": sa.Column("document_version", sa.Integer(), nullable=True),
        "compile_input_sha256": sa.Column(
            "compile_input_sha256", sa.String(length=64), nullable=True
        ),
        "pipeline_schema_sha256": sa.Column(
            "pipeline_schema_sha256", sa.String(length=71), nullable=True
        ),
        "model_revision": sa.Column(
            "model_revision", sa.String(length=64), nullable=True
        ),
        "compile_provenance": sa.Column(
            "compile_provenance",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        "is_active": sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    }
    relation_columns = {
        "document_id": sa.Column("document_id", sa.Uuid(), nullable=True),
        "document_version": sa.Column("document_version", sa.Integer(), nullable=True),
        "source_relation_key": sa.Column(
            "source_relation_key", sa.String(length=256), nullable=True
        ),
        "compile_input_sha256": sa.Column(
            "compile_input_sha256", sa.String(length=64), nullable=True
        ),
        "pipeline_schema_sha256": sa.Column(
            "pipeline_schema_sha256", sa.String(length=71), nullable=True
        ),
        "model_revision": sa.Column(
            "model_revision", sa.String(length=64), nullable=True
        ),
        "compile_provenance": sa.Column(
            "compile_provenance",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        "is_active": sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    }
    existing_notes = _columns(NOTE_TABLE)
    for name, column in note_columns.items():
        if name not in existing_notes:
            op.add_column(NOTE_TABLE, column)
    existing_relations = _columns(RELATION_TABLE)
    for name, column in relation_columns.items():
        if name not in existing_relations:
            op.add_column(RELATION_TABLE, column)

    legacy_unique = _unique_name(
        NOTE_TABLE,
        {"tenant_id", "project_id", "stable_key"},
    )
    if legacy_unique:
        with op.batch_alter_table(NOTE_TABLE) as batch:
            batch.drop_constraint(legacy_unique, type_="unique")
    if _unique_name(
        NOTE_TABLE,
        {
            "tenant_id",
            "project_id",
            "stable_key",
            "document_version",
            "compile_input_sha256",
            "pipeline_schema_sha256",
            "model_revision",
        },
    ) is None:
        _create_unique_constraint(
            "uq_knowledge_note_compile_revision",
            NOTE_TABLE,
            [
                "tenant_id",
                "project_id",
                "stable_key",
                "document_version",
                "compile_input_sha256",
                "pipeline_schema_sha256",
                "model_revision",
            ],
        )
    if _unique_name(
        RELATION_TABLE,
        {
            "tenant_id",
            "project_id",
            "document_id",
            "source_relation_key",
            "document_version",
            "compile_input_sha256",
            "pipeline_schema_sha256",
            "model_revision",
        },
    ) is None:
        _create_unique_constraint(
            "uq_relation_compile_revision",
            RELATION_TABLE,
            [
                "tenant_id",
                "project_id",
                "document_id",
                "source_relation_key",
                "document_version",
                "compile_input_sha256",
                "pipeline_schema_sha256",
                "model_revision",
            ],
        )
    if "knowledge_notes_active_document_idx" not in _index_names(NOTE_TABLE):
        op.create_index(
            "knowledge_notes_active_document_idx",
            NOTE_TABLE,
            [
                "tenant_id",
                "project_id",
                "document_id",
                "document_version",
                "stable_key",
            ],
            postgresql_where=sa.text("is_active"),
            sqlite_where=sa.text("is_active = 1"),
        )
    if "relations_active_document_idx" not in _index_names(RELATION_TABLE):
        op.create_index(
            "relations_active_document_idx",
            RELATION_TABLE,
            ["tenant_id", "project_id", "document_id", "document_version"],
            postgresql_where=sa.text("is_active"),
            sqlite_where=sa.text("is_active = 1"),
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Alembic creates version_num as VARCHAR(32), but descriptive revision
        # identifiers from this migration onward intentionally exceed 32 bytes.
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=128),
            existing_nullable=False,
        )
    if TABLE not in _tables():
        DocumentSemanticClassification.__table__.create(bind=bind)
    elif "provenance" not in _columns(TABLE):
        op.add_column(
            TABLE,
            sa.Column(
                "provenance",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )
    _add_compile_revision_columns()
    if bind.dialect.name != "postgresql":
        return
    policies = {
        str(row[0])
        for row in bind.execute(
            sa.text(
                """
            SELECT policyname
            FROM pg_policies
            WHERE schemaname = 'public' AND tablename = :table
            """
            ),
            {"table": TABLE},
        )
    }
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    policy = f"{TABLE}_tenant_isolation"
    if policy not in policies:
        op.execute(
            f"""
            CREATE POLICY {policy} ON {TABLE}
            USING (
                tenant_id =
                NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            WITH CHECK (
                tenant_id =
                NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            """
        )
    op.execute(
        f"GRANT SELECT, INSERT ON TABLE {TABLE} TO {DISPATCH_ROLE}"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and TABLE in _tables():
        op.execute(f"REVOKE ALL PRIVILEGES ON TABLE {TABLE} FROM {DISPATCH_ROLE}")
        op.execute(
            f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}"
        )
    if TABLE in _tables():
        op.drop_table(TABLE)
    if "relations_active_document_idx" in _index_names(RELATION_TABLE):
        op.drop_index("relations_active_document_idx", table_name=RELATION_TABLE)
    if "knowledge_notes_active_document_idx" in _index_names(NOTE_TABLE):
        op.drop_index("knowledge_notes_active_document_idx", table_name=NOTE_TABLE)
    relation_unique = _unique_name(
        RELATION_TABLE,
        {
            "tenant_id",
            "project_id",
            "document_id",
            "source_relation_key",
            "document_version",
            "compile_input_sha256",
            "pipeline_schema_sha256",
            "model_revision",
        },
    )
    if relation_unique:
        with op.batch_alter_table(RELATION_TABLE) as batch:
            batch.drop_constraint(relation_unique, type_="unique")
    note_unique = _unique_name(
        NOTE_TABLE,
        {
            "tenant_id",
            "project_id",
            "stable_key",
            "document_version",
            "compile_input_sha256",
            "pipeline_schema_sha256",
            "model_revision",
        },
    )
    if note_unique:
        with op.batch_alter_table(NOTE_TABLE) as batch:
            batch.drop_constraint(note_unique, type_="unique")
    with op.batch_alter_table(NOTE_TABLE) as batch:
        for column in (
            "is_active",
            "compile_provenance",
            "model_revision",
            "pipeline_schema_sha256",
            "compile_input_sha256",
            "document_version",
            "document_id",
        ):
            if column in _columns(NOTE_TABLE):
                batch.drop_column(column)
        if _unique_name(
            NOTE_TABLE,
            {"tenant_id", "project_id", "stable_key"},
        ) is None:
            batch.create_unique_constraint(
                "uq_knowledge_notes_project_stable_key",
                ["tenant_id", "project_id", "stable_key"],
            )
    with op.batch_alter_table(RELATION_TABLE) as batch:
        for column in (
            "is_active",
            "compile_provenance",
            "model_revision",
            "pipeline_schema_sha256",
            "compile_input_sha256",
            "source_relation_key",
            "document_version",
            "document_id",
        ):
            if column in _columns(RELATION_TABLE):
                batch.drop_column(column)
