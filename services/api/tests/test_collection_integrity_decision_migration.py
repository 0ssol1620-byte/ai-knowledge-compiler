"""Schema and PostgreSQL RLS contract evidence for integrity decisions."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from akc_api import models as _models  # noqa: F401
from akc_api.database import Base
from akc_api.models import CollectionIntegrityDecision
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

MIGRATION = importlib.import_module("migrations.versions.0028_collection_integrity_decisions")


def _operations(connection: Any) -> Operations:
    return Operations(MigrationContext.configure(connection))


def test_integrity_decision_orm_is_append_only_and_content_free() -> None:
    columns = set(CollectionIntegrityDecision.__table__.c.keys())
    assert {
        "tenant_id",
        "collection_id",
        "quarantine_item_id",
        "review_item_id",
        "action",
        "reason_code",
        "evidence_reference",
        "previous_status",
        "resulting_status",
        "override_applied",
        "request_sha256",
        "actor_id",
        "created_at",
    } <= columns
    assert {
        "content",
        "note",
        "filename",
        "path",
        "password",
        "secret",
        "updated_at",
        "deleted_at",
    }.isdisjoint(columns)
    constraints = {
        constraint.name for constraint in CollectionIntegrityDecision.__table__.constraints
    }
    assert "ck_collection_integrity_decisions_target" in constraints
    assert "ck_collection_integrity_decisions_action" in constraints
    assert "ck_collection_integrity_decisions_override" in constraints


def test_integrity_decision_migration_creates_current_sqlite_schema(monkeypatch: Any) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        CollectionIntegrityDecision.__table__.drop(connection)
        monkeypatch.setattr(MIGRATION, "op", _operations(connection))

        MIGRATION.upgrade()
        MIGRATION.upgrade()
        inspector = inspect(connection)
        columns = {row["name"] for row in inspector.get_columns(MIGRATION._TABLE)}
        assert {
            "quarantine_item_id",
            "review_item_id",
            "evidence_reference",
            "request_sha256",
        } <= columns
        indexes = {row["name"] for row in inspector.get_indexes(MIGRATION._TABLE)}
        assert {
            "collection_integrity_decisions_collection_idx",
            "collection_integrity_decisions_quarantine_idx",
            "collection_integrity_decisions_review_idx",
        } <= indexes
        checks = " ".join(
            str(row["sqltext"]) for row in inspector.get_check_constraints(MIGRATION._TABLE)
        )
        assert "keep_quarantined" in checks
        assert "override_applied" in checks
        assert MIGRATION.revision == "0028_collection_integrity_decisions"
        assert MIGRATION.down_revision == "0027_finalize_collection_metadata_encryption"
        foreign_keys = {
            tuple(row["referred_columns"]) for row in inspector.get_foreign_keys(MIGRATION._TABLE)
        }
        assert ("id",) in foreign_keys
        assert ("tenant_id", "id") in foreign_keys
        assert all(
            row["referred_table"] not in {"review_items", "quarantine_items"}
            for row in inspector.get_foreign_keys(MIGRATION._TABLE)
        )

        MIGRATION.downgrade()
        assert MIGRATION._TABLE not in inspect(connection).get_table_names()
    engine.dispose()


def test_integrity_decision_rls_requires_tenant_actor_and_project_access() -> None:
    read = MIGRATION._project_access(write=False)
    write = MIGRATION._project_access(write=True)
    for clause in (read, write):
        assert "current_setting('app.tenant_id', true)" in clause
        assert "current_setting('app.user_id', true)" in clause
        assert "project_memberships" in clause
        assert "integrity_collection.project_id" in clause
    assert "viewer" in read
    assert "viewer" not in write
    source = Path(MIGRATION.__file__).read_text(encoding="utf-8")
    assert "FOR SELECT USING" in source
    assert "FOR INSERT WITH CHECK" in source
    assert "AS RESTRICTIVE" not in source
    assert "integrity_quarantine.collection_id" in source
    assert "integrity_file.collection_id" in source
    assert "integrity_document.source_file_id" in source
    assert 'CREATE POLICY "{_TABLE}_update"' not in source
    assert 'CREATE POLICY "{_TABLE}_delete"' not in source
