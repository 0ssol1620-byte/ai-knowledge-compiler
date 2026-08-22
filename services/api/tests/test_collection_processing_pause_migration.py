"""Migration proof for the collection-only paused processing state."""

from __future__ import annotations

import importlib
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

MIGRATION = importlib.import_module(
    "migrations.versions.0029_collection_processing_paused_state"
)


def _operations(connection: Any) -> Operations:
    return Operations(MigrationContext.configure(connection))


def test_collection_processing_pause_migration_rewrites_legacy_state(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE processing_jobs ("
                "id INTEGER PRIMARY KEY, job_type TEXT NOT NULL, status TEXT NOT NULL, "
                "CONSTRAINT legacy_processing_status CHECK ("
                "status IN ('queued','running','waiting_review','completed','failed','cancelled')"
                "))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO processing_jobs (id, job_type, status) "
                "VALUES (1, 'collection_processing', 'waiting_review')"
            )
        )
        monkeypatch.setattr(MIGRATION, "op", _operations(connection))

        MIGRATION.upgrade()
        assert connection.execute(
            text("SELECT status FROM processing_jobs WHERE id = 1")
        ).scalar_one() == "paused"
        upgraded_checks = " ".join(
            str(row["sqltext"])
            for row in inspect(connection).get_check_constraints("processing_jobs")
        )
        assert "paused" in upgraded_checks

        MIGRATION.downgrade()
        assert connection.execute(
            text("SELECT status FROM processing_jobs WHERE id = 1")
        ).scalar_one() == "waiting_review"
        downgraded_checks = " ".join(
            str(row["sqltext"])
            for row in inspect(connection).get_check_constraints("processing_jobs")
        )
        assert "paused" not in downgraded_checks
        assert MIGRATION.down_revision == "0028_collection_integrity_decisions"
