"""Structural evidence for generation-scoped accepted-block invalidation."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any, cast

import sqlalchemy as sa
from akc_api import models as _models  # noqa: F401
from akc_api.database import Base
from akc_api.parallel_models import (
    AcceptedBlock,
    AcceptedBlockInvalidation,
    ArbitrationDecision,
    ParallelParseAttempt,
    ParallelParseShard,
    RecoveryTask,
)
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

MIGRATION_31 = importlib.import_module("migrations.versions.0031_parallel_pod_runtime")
MIGRATION = importlib.import_module(
    "migrations.versions.0032_accepted_block_invalidations"
)


def _operations(connection: Any) -> Operations:
    return Operations(MigrationContext.configure(connection))


def _unique_columns(inspector: sa.Inspector, table: str) -> set[tuple[str, ...]]:
    return {
        tuple(str(column) for column in row["column_names"])
        for row in inspector.get_unique_constraints(table)
    }


def _foreign_keys(
    inspector: sa.Inspector, table: str
) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    return {
        (
            tuple(str(column) for column in row["constrained_columns"]),
            str(row["referred_table"]),
            tuple(str(column) for column in row["referred_columns"]),
        )
        for row in inspector.get_foreign_keys(table)
    }


def _orm_foreign_keys(
    model: type[Any],
) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    table = cast(sa.Table, model.__table__)
    return {
        (
            tuple(str(element.parent.name) for element in constraint.elements),
            str(constraint.elements[0].column.table.name),
            tuple(str(element.column.name) for element in constraint.elements),
        )
        for constraint in table.foreign_key_constraints
    }


def _recreate_0031_schema(connection: Any, monkeypatch: Any) -> None:
    Base.metadata.create_all(connection)
    Base.metadata.tables["accepted_block_invalidations"].drop(connection)
    for table in reversed(MIGRATION_31._TABLES):
        Base.metadata.tables[table].drop(connection)
    operations = _operations(connection)
    monkeypatch.setattr(MIGRATION_31, "op", operations)
    monkeypatch.setattr(MIGRATION, "op", operations)
    MIGRATION_31.upgrade()


def test_0032_sqlite_up_down_up_and_orm_parity(monkeypatch: Any) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _recreate_0031_schema(connection, monkeypatch)
        before = inspect(connection)
        assert "document_version_id" not in {
            str(row["name"]) for row in before.get_columns("parse_shards")
        }
        assert "accepted_block_invalidations" not in before.get_table_names()

        MIGRATION.upgrade()
        inspector = inspect(connection)
        assert "accepted_block_invalidations" in inspector.get_table_names()
        for model in (
            ParallelParseShard,
            ParallelParseAttempt,
            ArbitrationDecision,
            AcceptedBlock,
            RecoveryTask,
            AcceptedBlockInvalidation,
        ):
            table = cast(sa.Table, model.__table__)
            migrated_columns = {
                str(column["name"]) for column in inspector.get_columns(table.name)
            }
            assert migrated_columns == set(table.c.keys())

        shard_columns = {
            str(row["name"]): row for row in inspector.get_columns("parse_shards")
        }
        assert shard_columns["processing_job_id"]["nullable"] is False
        assert shard_columns["document_version_id"]["nullable"] is False
        assert (
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "shard_key",
            "plan_version",
        ) in _unique_columns(inspector, "parse_shards")
        assert ("document_id", "shard_key", "plan_version") not in _unique_columns(
            inspector, "parse_shards"
        )
        assert ("tenant_id", "shard_id", "id") in _unique_columns(
            inspector, "parse_attempts"
        )
        assert "parse_attempts_one_accepted_idx" not in {
            str(row["name"]) for row in inspector.get_indexes("parse_attempts")
        }

        accepted_uniques = _unique_columns(inspector, "accepted_blocks")
        assert ("document_id", "logical_block_key") not in accepted_uniques
        assert (
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "logical_block_key",
            "generation",
        ) in accepted_uniques
        assert ("tenant_id", "arbitration_id") in accepted_uniques
        accepted_foreign_keys = _foreign_keys(inspector, "accepted_blocks")
        assert accepted_foreign_keys == _orm_foreign_keys(AcceptedBlock)
        assert (
            ("tenant_id", "shard_id", "attempt_id"),
            "parse_attempts",
            ("tenant_id", "shard_id", "id"),
        ) in accepted_foreign_keys
        assert (
            ("tenant_id", "arbitration_id"),
            "arbitration_decisions",
            ("tenant_id", "id"),
        ) in accepted_foreign_keys

        invalidation_foreign_keys = _foreign_keys(
            inspector, "accepted_block_invalidations"
        )
        assert invalidation_foreign_keys == _orm_foreign_keys(
            AcceptedBlockInvalidation
        )
        assert any(
            referred == "accepted_blocks" and len(local) == 8
            for local, referred, _remote in invalidation_foreign_keys
        )
        assert any(
            referred == "credit_ledger" and len(local) == 4
            for local, referred, _remote in invalidation_foreign_keys
        )
        assert any(
            referred == "recovery_tasks" and len(local) == 4
            for local, referred, _remote in invalidation_foreign_keys
        )
        invalidation_checks = {
            str(row["name"])
            for row in inspector.get_check_constraints("accepted_block_invalidations")
        }
        assert {
            "ck_accepted_block_invalidations_action",
            "ck_accepted_block_invalidations_operation_sha",
            "ck_accepted_block_invalidations_evidence_sha",
            "ck_accepted_block_invalidations_refund_shape",
        } <= invalidation_checks

        arbitration_checks = {
            str(row["name"])
            for row in inspector.get_check_constraints("arbitration_decisions")
        }
        assert {
            "ck_arbitration_decisions_logical_unit_sha",
            "ck_arbitration_decisions_priced_credit",
        } <= arbitration_checks

        MIGRATION.downgrade()
        downgraded = inspect(connection)
        assert "accepted_block_invalidations" not in downgraded.get_table_names()
        assert "document_version_id" not in {
            str(row["name"]) for row in downgraded.get_columns("parse_shards")
        }
        assert ("document_id", "logical_block_key") in _unique_columns(
            downgraded, "accepted_blocks"
        )
        downgraded_attempt_indexes = {
            str(row["name"]): row for row in downgraded.get_indexes("parse_attempts")
        }
        assert downgraded_attempt_indexes["parse_attempts_one_accepted_idx"]["unique"] == 1
        assert downgraded.get_columns("parse_shards")[4]["nullable"] is True

        MIGRATION.upgrade()
        upgraded = inspect(connection)
        assert "accepted_block_invalidations" in upgraded.get_table_names()
        assert "parse_attempts_one_accepted_idx" not in {
            str(row["name"]) for row in upgraded.get_indexes("parse_attempts")
        }
    engine.dispose()


def test_0031_bootstrap_accepts_the_evolved_0032_orm_contract(monkeypatch: Any) -> None:
    """Revision 0001 bootstraps current metadata before historical revisions run."""

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        monkeypatch.setattr(MIGRATION_31, "op", _operations(connection))
        for table in MIGRATION_31._TABLES:
            assert MIGRATION_31._existing_table_is_complete(table) is True
    engine.dispose()


class _PostgresRecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def get_bind(self) -> Any:
        return self.bind

    def execute(self, statement: str) -> None:
        self.statements.append(str(statement))


def test_0032_postgresql_is_append_only_tenant_safe_and_least_privilege(
    monkeypatch: Any,
) -> None:
    recorder = _PostgresRecordingOp()
    monkeypatch.setattr(MIGRATION, "op", recorder)

    MIGRATION._enable_rls()
    MIGRATION._install_postgresql_hardening()
    MIGRATION._configure_role_grants()
    sql = "\n".join(recorder.statements)

    assert 'CREATE POLICY "accepted_block_invalidations_select"' in sql
    assert 'CREATE POLICY "accepted_block_invalidations_insert"' in sql
    assert 'CREATE POLICY "accepted_block_invalidations_update"' not in sql
    assert 'CREATE POLICY "accepted_block_invalidations_delete"' not in sql
    assert '"trg_accepted_block_invalidations_append_only"' in sql
    assert 'BEFORE UPDATE OR DELETE ON "accepted_block_invalidations"' in sql
    assert '"trg_accepted_block_invalidations_refund_guard"' in sql
    assert "ledger.entry_type = 'refund'" in sql
    assert "ledger.credits = NEW.refund_amount" in sql
    assert (
        'REVOKE ALL PRIVILEGES ON TABLE "accepted_block_invalidations" FROM PUBLIC'
        in sql
    )
    assert (
        'GRANT SELECT, INSERT ON TABLE "accepted_block_invalidations" '
        "TO akc_dispatch_worker" in sql
    )
    assert "GRANT" not in "\n".join(
        statement
        for statement in recorder.statements
        if "akc_gpu_worker" in statement and "REVOKE" not in statement
    )

    assert MIGRATION.revision == "0032_accepted_block_invalidations"
    assert MIGRATION.down_revision == "0031_parallel_pod_runtime"
