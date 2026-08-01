"""Schema and PostgreSQL enforcement evidence for the v6 parallel runtime."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlalchemy as sa
from akc_api import models as _models  # noqa: F401
from akc_api.database import Base
from akc_api.parallel_models import (
    AcceptedBlock,
    AcceptedBlockInvalidation,
    ArbitrationDecision,
    AttemptValidation,
    ContinuityEdge,
    ParallelParseAttempt,
    ParallelParseShard,
    RecoveryTask,
    SemanticHealthEvent,
    WorkerHealth,
)
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

MIGRATION = importlib.import_module("migrations.versions.0031_parallel_pod_runtime")
MIGRATION_32 = importlib.import_module(
    "migrations.versions.0032_accepted_block_invalidations"
)

_MODELS = (
    ParallelParseShard,
    ParallelParseAttempt,
    AttemptValidation,
    WorkerHealth,
    SemanticHealthEvent,
    ContinuityEdge,
    AcceptedBlock,
    RecoveryTask,
    ArbitrationDecision,
    AcceptedBlockInvalidation,
)


def _operations(connection: Any) -> Operations:
    return Operations(MigrationContext.configure(connection))


def test_parallel_runtime_sqlite_up_down_up_and_orm_parity(monkeypatch: Any) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        Base.metadata.tables["accepted_block_invalidations"].drop(connection)
        for table in reversed(MIGRATION._TABLES):
            Base.metadata.tables[table].drop(connection)
        operations = _operations(connection)
        monkeypatch.setattr(MIGRATION, "op", operations)
        monkeypatch.setattr(MIGRATION_32, "op", operations)

        MIGRATION.upgrade()
        MIGRATION.upgrade()
        MIGRATION_32.upgrade()
        inspector = inspect(connection)
        assert set(MIGRATION._TABLES) <= set(inspector.get_table_names())
        for model in _MODELS:
            table = cast(sa.Table, model.__table__)
            migrated_columns = {str(column["name"]) for column in inspector.get_columns(table.name)}
            assert migrated_columns == set(table.c.keys())
            migrated_checks = {
                str(check["name"])
                for check in inspector.get_check_constraints(table.name)
                if check.get("name") is not None
            }
            orm_checks = {
                str(constraint.name)
                for constraint in table.constraints
                if isinstance(constraint, sa.CheckConstraint)
            }
            assert migrated_checks == orm_checks

        worker_foreign_keys = {
            (tuple(row["constrained_columns"]), str(row["referred_table"]))
            for row in inspector.get_foreign_keys("worker_health")
        }
        assert (("tenant_id",), "tenants") in worker_foreign_keys
        worker_checks = " ".join(
            str(row["sqltext"]) for row in inspector.get_check_constraints("worker_health")
        )
        assert "inflight <= capacity" in worker_checks

        MIGRATION_32.downgrade()
        MIGRATION.downgrade()
        assert set(MIGRATION._TABLES).isdisjoint(inspect(connection).get_table_names())
        MIGRATION.upgrade()
        MIGRATION_32.upgrade()
        assert set(MIGRATION._TABLES) <= set(inspect(connection).get_table_names())

    engine.dispose()


def test_parallel_runtime_refuses_to_skip_partial_table(monkeypatch: Any) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE parse_shards (id VARCHAR(36) PRIMARY KEY)")
        monkeypatch.setattr(MIGRATION, "op", _operations(connection))

        with pytest.raises(RuntimeError, match="refusing to skip partial v6 table"):
            MIGRATION._create_parse_shards()
    engine.dispose()


class _PostgresRecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def get_bind(self) -> Any:
        return self.bind

    def execute(self, statement: str) -> None:
        self.statements.append(str(statement))


def test_parallel_runtime_postgresql_is_append_only_and_least_privilege(
    monkeypatch: Any,
) -> None:
    recorder = _PostgresRecordingOp()
    monkeypatch.setattr(MIGRATION, "op", recorder)

    for table in MIGRATION._TABLES:
        MIGRATION._enable_rls(table)
    MIGRATION._install_postgresql_immutability()
    MIGRATION._configure_role_grants()
    sql = "\n".join(recorder.statements)

    for table in MIGRATION._APPEND_ONLY_TABLES:
        assert f'CREATE POLICY "{table}_select"' in sql
        assert f'CREATE POLICY "{table}_insert"' in sql
        assert f'CREATE POLICY "{table}_update"' not in sql
        assert f'CREATE POLICY "{table}_delete"' not in sql
        assert f'"trg_{table}_append_only"' in sql
    assert 'CREATE POLICY "parse_attempts_update"' in sql
    assert 'CREATE POLICY "parse_attempts_delete"' not in sql
    assert "OLD.output_summary::text" in sql
    assert "OLD.output_received_at IS NOT NULL" in sql
    assert "terminal v6 parse attempt" in sql
    assert 'BEFORE UPDATE OR DELETE ON "parse_attempts"' in sql

    assert MIGRATION._DISPATCH_ROLE == "akc_dispatch_worker"
    assert MIGRATION._GPU_WORKER_ROLE == "akc_gpu_worker"
    update_grants = [statement for statement in recorder.statements if "GRANT UPDATE" in statement]
    for table in MIGRATION._APPEND_ONLY_TABLES:
        assert all(f"ON TABLE {table}" not in statement for statement in update_grants)
    assert "GRANT UPDATE (status, priority, updated_at)" in sql
    assert "GRANT UPDATE (\n            state, worker_id" in sql
    assert "GRANT UPDATE (state, result_attempt_id, completed_at)" in sql
    for table in MIGRATION._TABLES:
        assert f'REVOKE ALL PRIVILEGES ON TABLE "{table}" FROM PUBLIC' in sql

    assert MIGRATION.revision == "0031_parallel_pod_runtime"
    assert MIGRATION.down_revision == "0030_collection_integrity_action_execution"
