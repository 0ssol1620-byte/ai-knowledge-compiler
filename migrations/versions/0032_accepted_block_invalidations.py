"""Add generation-scoped accepted-block invalidation and refund evidence.

Revision ID: 0032_accepted_block_invalidations
Revises: 0031_parallel_pod_runtime
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0032_accepted_block_invalidations"
down_revision = "0031_parallel_pod_runtime"
branch_labels = None
depends_on = None

_TABLE = "accepted_block_invalidations"
_DISPATCH_ROLE = "akc_dispatch_worker"
_GPU_WORKER_ROLE = "akc_gpu_worker"
_LEGACY_ACCEPTED_ATTEMPT_INDEX = "parse_attempts_one_accepted_idx"
_NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
}


def _dialect() -> str:
    return str(op.get_bind().dialect.name)


def _indexes(table: str) -> set[str]:
    return {
        str(row["name"])
        for row in inspect(op.get_bind()).get_indexes(table)
        if row.get("name") is not None
    }


def _allow_historical_accepted_attempts() -> None:
    """Keep terminal attempt evidence while a later recovery generation wins."""

    if _LEGACY_ACCEPTED_ATTEMPT_INDEX in _indexes("parse_attempts"):
        op.drop_index(_LEGACY_ACCEPTED_ATTEMPT_INDEX, table_name="parse_attempts")


def _restore_legacy_single_accepted_attempt() -> None:
    if _LEGACY_ACCEPTED_ATTEMPT_INDEX in _indexes("parse_attempts"):
        return
    op.create_index(
        _LEGACY_ACCEPTED_ATTEMPT_INDEX,
        "parse_attempts",
        ["shard_id"],
        unique=True,
        postgresql_where=sa.text("state = 'ACCEPTED'"),
        sqlite_where=sa.text("state = 'ACCEPTED'"),
    )


def _unique_constraints(table: str) -> dict[tuple[str, ...], str | None]:
    return {
        tuple(str(column) for column in row["column_names"]): (
            str(row["name"]) if row.get("name") is not None else None
        )
        for row in inspect(op.get_bind()).get_unique_constraints(table)
    }


def _foreign_key_scopes(table: str) -> set[tuple[tuple[str, ...], str]]:
    return {
        (
            tuple(str(column) for column in row["constrained_columns"]),
            str(row["referred_table"]),
        )
        for row in inspect(op.get_bind()).get_foreign_keys(table)
    }


def _foreign_key_name(
    table: str,
    columns: Sequence[str],
    referred_table: str,
) -> str | None:
    for row in inspect(op.get_bind()).get_foreign_keys(table):
        if (
            tuple(str(column) for column in row["constrained_columns"])
            == tuple(columns)
            and str(row["referred_table"]) == referred_table
        ):
            return str(row["name"]) if row.get("name") is not None else None
    return None


def _drop_foreign_key(
    batch: Any,
    table: str,
    columns: Sequence[str],
    referred_table: str,
) -> None:
    name = _foreign_key_name(table, columns, referred_table)
    if name is None:
        if (tuple(columns), referred_table) not in _foreign_key_scopes(table):
            return
        if _dialect() != "sqlite":
            raise RuntimeError(
                f"cannot identify foreign key on {table}{tuple(columns)!r}"
            )
        name = f"fk_{table}_{'_'.join(columns)}_{referred_table}"
    batch.drop_constraint(name, type_="foreignkey")


def _checks(table: str) -> set[str]:
    return {
        str(row["name"])
        for row in inspect(op.get_bind()).get_check_constraints(table)
        if row.get("name") is not None
    }


def _unique_name(table: str, columns: Sequence[str]) -> str | None:
    return _unique_constraints(table).get(tuple(columns))


def _anonymous_unique_name(table: str, columns: Sequence[str]) -> str:
    return f"uq_{table}_{'_'.join(columns)}"


def _drop_unique(batch: Any, table: str, columns: Sequence[str]) -> None:
    name = _unique_name(table, columns)
    if name is None:
        if tuple(columns) not in _unique_constraints(table):
            return
        if _dialect() != "sqlite":
            raise RuntimeError(f"cannot identify unique constraint on {table}{tuple(columns)!r}")
        name = _anonymous_unique_name(table, columns)
    batch.drop_constraint(name, type_="unique")


def _batch(table: str) -> Any:
    return op.batch_alter_table(
        table,
        recreate="always" if _dialect() == "sqlite" else "auto",
        naming_convention=_NAMING_CONVENTION,
    )


def _assert_no_row(sql: str, message: str) -> None:
    if op.get_bind().execute(sa.text(sql)).first() is not None:
        raise RuntimeError(message)


def _suspend_scope_hardening() -> None:
    if _dialect() != "postgresql":
        return
    op.execute('ALTER TABLE "parse_shards" DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "accepted_blocks" DISABLE ROW LEVEL SECURITY')
    op.execute(
        'ALTER TABLE "accepted_blocks" DISABLE TRIGGER "trg_accepted_blocks_append_only"'
    )


def _restore_scope_hardening() -> None:
    if _dialect() != "postgresql":
        return
    for table in ("parse_shards", "accepted_blocks"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        'ALTER TABLE "accepted_blocks" ENABLE TRIGGER "trg_accepted_blocks_append_only"'
    )


def _add_scope_columns() -> None:
    parse_columns = {
        str(row["name"]) for row in inspect(op.get_bind()).get_columns("parse_shards")
    }
    if "document_version_id" not in parse_columns:
        op.add_column(
            "parse_shards",
            sa.Column("document_version_id", sa.String(length=160), nullable=True),
        )
    if _dialect() == "postgresql":
        op.execute(
            """
            UPDATE parse_shards
            SET document_version_id = context ->> 'document_version_id'
            WHERE document_version_id IS NULL
            """
        )
    else:
        op.execute(
            """
            UPDATE parse_shards
            SET document_version_id = json_extract(context, '$.document_version_id')
            WHERE document_version_id IS NULL
            """
        )
    _assert_no_row(
        """
        SELECT 1 FROM parse_shards
        WHERE processing_job_id IS NULL
           OR document_version_id IS NULL
           OR length(document_version_id) < 1
           OR length(document_version_id) > 160
        LIMIT 1
        """,
        "0032 requires every v6 parse shard to have a processing job and opaque "
        "document-version identity",
    )

    if "parse_shards_job_idx" in _indexes("parse_shards"):
        op.drop_index("parse_shards_job_idx", table_name="parse_shards")
    old_shard_unique = ("document_id", "shard_key", "plan_version")
    shard_uniques = _unique_constraints("parse_shards")
    with _batch("parse_shards") as batch:
        batch.alter_column(
            "processing_job_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
        batch.alter_column(
            "document_version_id",
            existing_type=sa.String(length=160),
            nullable=False,
        )
        if old_shard_unique in shard_uniques:
            _drop_unique(batch, "parse_shards", old_shard_unique)
        if (
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "shard_key",
            "plan_version",
        ) not in shard_uniques:
            batch.create_unique_constraint(
                "uq_parse_shards_generation_key",
                [
                    "tenant_id",
                    "document_id",
                    "processing_job_id",
                    "document_version_id",
                    "shard_key",
                    "plan_version",
                ],
            )
        if (
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "id",
        ) not in shard_uniques:
            batch.create_unique_constraint(
                "uq_parse_shards_acceptance_scope",
                [
                    "tenant_id",
                    "document_id",
                    "processing_job_id",
                    "document_version_id",
                    "id",
                ],
            )
    op.create_index(
        "parse_shards_job_idx",
        "parse_shards",
        ["tenant_id", "processing_job_id", "document_version_id", "status"],
    )

    attempt_scope = ("tenant_id", "shard_id", "id")
    if attempt_scope not in _unique_constraints("parse_attempts"):
        with _batch("parse_attempts") as batch:
            batch.create_unique_constraint(
                "uq_parse_attempts_shard_scope",
                list(attempt_scope),
            )

    recovery_scope = ("tenant_id", "document_id", "shard_id", "id")
    if recovery_scope not in _unique_constraints("recovery_tasks"):
        with _batch("recovery_tasks") as batch:
            batch.create_unique_constraint(
                "uq_recovery_tasks_invalidation_scope",
                list(recovery_scope),
            )

    ledger_scope = ("tenant_id", "job_id", "id", "operation_key")
    if ledger_scope not in _unique_constraints("credit_ledger"):
        with _batch("credit_ledger") as batch:
            batch.create_unique_constraint(
                "uq_credit_ledger_refund_binding",
                list(ledger_scope),
            )


def _add_arbitration_contract() -> None:
    columns = {
        str(row["name"])
        for row in inspect(op.get_bind()).get_columns("arbitration_decisions")
    }
    required = {
        "logical_unit_key",
        "logical_unit_sha256",
        "priced_credit_amount",
    }
    if required <= columns:
        return
    _assert_no_row(
        "SELECT 1 FROM arbitration_decisions LIMIT 1",
        "0032 cannot derive content-bound logical-unit pricing for a legacy arbitration row",
    )
    additions = (
        sa.Column("logical_unit_key", sa.String(length=200), nullable=True),
        sa.Column("logical_unit_sha256", sa.String(length=64), nullable=True),
        sa.Column("priced_credit_amount", sa.Numeric(18, 6), nullable=True),
    )
    for column in additions:
        if str(column.name) not in columns:
            op.add_column("arbitration_decisions", column)
    with _batch("arbitration_decisions") as batch:
        batch.alter_column(
            "logical_unit_key",
            existing_type=sa.String(length=200),
            nullable=False,
        )
        batch.alter_column(
            "logical_unit_sha256",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch.alter_column(
            "priced_credit_amount",
            existing_type=sa.Numeric(18, 6),
            nullable=False,
        )
        batch.create_check_constraint(
            "ck_arbitration_decisions_logical_unit_sha",
            "length(logical_unit_sha256) = 64",
        )
        batch.create_check_constraint(
            "ck_arbitration_decisions_priced_credit",
            "(decision = 'selected' AND priced_credit_amount > 0) OR "
            "(decision <> 'selected' AND priced_credit_amount = 0)",
        )


def _add_accepted_block_generation() -> None:
    columns = {
        str(row["name"]) for row in inspect(op.get_bind()).get_columns("accepted_blocks")
    }
    uniques = _unique_constraints("accepted_blocks")
    foreign_keys = _foreign_key_scopes("accepted_blocks")
    if (
        {"processing_job_id", "document_version_id", "generation", "arbitration_id"}
        <= columns
        and (
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "logical_block_key",
            "generation",
        )
        in uniques
        and ("tenant_id", "arbitration_id") in uniques
        and "ck_accepted_blocks_generation" in _checks("accepted_blocks")
        and (("tenant_id", "arbitration_id"), "arbitration_decisions")
        in foreign_keys
        and "accepted_blocks_document_idx" in _indexes("accepted_blocks")
    ):
        return
    _assert_no_row(
        "SELECT 1 FROM accepted_blocks LIMIT 1",
        "0032 cannot derive typed arbitration identity for a legacy accepted block",
    )
    additions = (
        sa.Column("processing_job_id", sa.Uuid(), nullable=True),
        sa.Column("document_version_id", sa.String(length=160), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=True),
        sa.Column("arbitration_id", sa.Uuid(), nullable=True),
    )
    for column in additions:
        if str(column.name) not in columns:
            op.add_column("accepted_blocks", column)
    if _dialect() == "postgresql":
        op.execute(
            """
            UPDATE accepted_blocks AS accepted
            SET processing_job_id = shard.processing_job_id,
                document_version_id = shard.document_version_id,
                generation = 1
            FROM parse_shards AS shard
            WHERE accepted.tenant_id = shard.tenant_id
              AND accepted.shard_id = shard.id
              AND (accepted.processing_job_id IS NULL
                   OR accepted.document_version_id IS NULL
                   OR accepted.generation IS NULL)
            """
        )
    else:
        op.execute(
            """
            UPDATE accepted_blocks
            SET processing_job_id = (
                    SELECT shard.processing_job_id
                    FROM parse_shards AS shard
                    WHERE shard.tenant_id = accepted_blocks.tenant_id
                      AND shard.id = accepted_blocks.shard_id
                ),
                document_version_id = (
                    SELECT shard.document_version_id
                    FROM parse_shards AS shard
                    WHERE shard.tenant_id = accepted_blocks.tenant_id
                      AND shard.id = accepted_blocks.shard_id
                ),
                generation = 1
            WHERE processing_job_id IS NULL
               OR document_version_id IS NULL
               OR generation IS NULL
            """
        )
    _assert_no_row(
        """
        SELECT 1 FROM accepted_blocks
        WHERE processing_job_id IS NULL
           OR document_version_id IS NULL
           OR length(document_version_id) < 1
           OR length(document_version_id) > 160
           OR generation IS NULL
           OR arbitration_id IS NULL
           OR generation < 1
        LIMIT 1
        """,
        "0032 cannot bind a legacy accepted block to its job/version/generation scope",
    )
    _assert_no_row(
        """
        SELECT 1
        FROM accepted_blocks AS accepted
        LEFT JOIN parse_shards AS shard
          ON shard.tenant_id = accepted.tenant_id
         AND shard.document_id = accepted.document_id
         AND shard.processing_job_id = accepted.processing_job_id
         AND shard.document_version_id = accepted.document_version_id
         AND shard.id = accepted.shard_id
        LEFT JOIN parse_attempts AS attempt
          ON attempt.tenant_id = accepted.tenant_id
         AND attempt.shard_id = accepted.shard_id
         AND attempt.id = accepted.attempt_id
        WHERE shard.id IS NULL OR attempt.id IS NULL
        LIMIT 1
        """,
        "0032 found an accepted block outside its shard/attempt lineage",
    )

    if "accepted_blocks_document_idx" in _indexes("accepted_blocks"):
        op.drop_index("accepted_blocks_document_idx", table_name="accepted_blocks")
    old_document_unique = ("document_id", "logical_block_key")
    uniques = _unique_constraints("accepted_blocks")
    foreign_keys = _foreign_key_scopes("accepted_blocks")
    with _batch("accepted_blocks") as batch:
        batch.alter_column(
            "processing_job_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
        batch.alter_column(
            "document_version_id",
            existing_type=sa.String(length=160),
            nullable=False,
        )
        batch.alter_column("generation", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("arbitration_id", existing_type=sa.Uuid(), nullable=False)
        if old_document_unique in uniques:
            _drop_unique(batch, "accepted_blocks", old_document_unique)
        if (("tenant_id", "shard_id"), "parse_shards") in foreign_keys:
            _drop_foreign_key(
                batch,
                "accepted_blocks",
                ("tenant_id", "shard_id"),
                "parse_shards",
            )
        if (("tenant_id", "attempt_id"), "parse_attempts") in foreign_keys:
            _drop_foreign_key(
                batch,
                "accepted_blocks",
                ("tenant_id", "attempt_id"),
                "parse_attempts",
            )
        batch.create_unique_constraint(
            "uq_accepted_blocks_generation_key",
            [
                "tenant_id",
                "document_id",
                "processing_job_id",
                "document_version_id",
                "logical_block_key",
                "generation",
            ],
        )
        batch.create_unique_constraint(
            "uq_accepted_blocks_invalidation_scope",
            [
                "tenant_id",
                "document_id",
                "processing_job_id",
                "document_version_id",
                "generation",
                "shard_id",
                "attempt_id",
                "id",
            ],
        )
        batch.create_unique_constraint(
            "uq_accepted_blocks_arbitration",
            ["tenant_id", "arbitration_id"],
        )
        batch.create_check_constraint("ck_accepted_blocks_generation", "generation >= 1")
        batch.create_foreign_key(
            "fk_accepted_blocks_processing_job_scope",
            "processing_jobs",
            ["tenant_id", "processing_job_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_accepted_blocks_shard_scope",
            "parse_shards",
            [
                "tenant_id",
                "document_id",
                "processing_job_id",
                "document_version_id",
                "shard_id",
            ],
            [
                "tenant_id",
                "document_id",
                "processing_job_id",
                "document_version_id",
                "id",
            ],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_accepted_blocks_attempt_scope",
            "parse_attempts",
            ["tenant_id", "shard_id", "attempt_id"],
            ["tenant_id", "shard_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_accepted_blocks_arbitration",
            "arbitration_decisions",
            ["tenant_id", "arbitration_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "accepted_blocks_document_idx",
        "accepted_blocks",
        [
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "generation",
            "final_state",
            "accepted_at",
        ],
    )


def _create_invalidation_table() -> None:
    if _TABLE in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("processing_job_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.String(length=160), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("shard_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("accepted_block_id", sa.Uuid(), nullable=False),
        sa.Column("recovery_task_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=120), nullable=False),
        sa.Column("operation_key", sa.String(length=200), nullable=False),
        sa.Column("operation_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("refund_settlement_key", sa.String(length=200), nullable=True),
        sa.Column("refund_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("refund_ledger_id", sa.Uuid(), nullable=True),
        sa.Column(
            "invalidated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "document_id",
                "processing_job_id",
                "document_version_id",
                "generation",
                "shard_id",
                "attempt_id",
                "accepted_block_id",
            ],
            [
                "accepted_blocks.tenant_id",
                "accepted_blocks.document_id",
                "accepted_blocks.processing_job_id",
                "accepted_blocks.document_version_id",
                "accepted_blocks.generation",
                "accepted_blocks.shard_id",
                "accepted_blocks.attempt_id",
                "accepted_blocks.id",
            ],
            name="fk_accepted_block_invalidations_block_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id", "shard_id", "recovery_task_id"],
            [
                "recovery_tasks.tenant_id",
                "recovery_tasks.document_id",
                "recovery_tasks.shard_id",
                "recovery_tasks.id",
            ],
            name="fk_accepted_block_invalidations_recovery_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "processing_job_id",
                "refund_ledger_id",
                "refund_settlement_key",
            ],
            [
                "credit_ledger.tenant_id",
                "credit_ledger.job_id",
                "credit_ledger.id",
                "credit_ledger.operation_key",
            ],
            name="fk_accepted_block_invalidations_refund_ledger",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "accepted_block_id"),
        sa.UniqueConstraint("tenant_id", "operation_key"),
        sa.UniqueConstraint("tenant_id", "operation_sha256"),
        sa.UniqueConstraint("tenant_id", "refund_settlement_key"),
        sa.CheckConstraint(
            "action IN ('invalidated','revoked')",
            name="ck_accepted_block_invalidations_action",
        ),
        sa.CheckConstraint(
            "length(reason_code) BETWEEN 1 AND 120",
            name="ck_accepted_block_invalidations_reason",
        ),
        sa.CheckConstraint(
            "length(operation_sha256) = 64",
            name="ck_accepted_block_invalidations_operation_sha",
        ),
        sa.CheckConstraint(
            "length(evidence_sha256) = 64",
            name="ck_accepted_block_invalidations_evidence_sha",
        ),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_accepted_block_invalidations_generation",
        ),
        sa.CheckConstraint(
            "(refund_ledger_id IS NULL AND refund_settlement_key IS NULL "
            "AND refund_amount = 0) OR "
            "(refund_ledger_id IS NOT NULL AND refund_settlement_key IS NOT NULL "
            "AND refund_amount > 0)",
            name="ck_accepted_block_invalidations_refund_shape",
        ),
    )
    op.create_index(
        "accepted_block_invalidations_active_lookup_idx",
        _TABLE,
        [
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "generation",
            "accepted_block_id",
        ],
    )
    op.create_index(
        "accepted_block_invalidations_recovery_idx",
        _TABLE,
        ["tenant_id", "recovery_task_id"],
    )


def _enable_rls() -> None:
    if _dialect() != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    scope = f'"{_TABLE}".tenant_id = {tenant}'
    op.execute(f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY')
    for operation in ("select", "insert", "update", "delete"):
        op.execute(f'DROP POLICY IF EXISTS "{_TABLE}_{operation}" ON "{_TABLE}"')
    op.execute(f'CREATE POLICY "{_TABLE}_select" ON "{_TABLE}" FOR SELECT USING ({scope})')
    op.execute(
        f'CREATE POLICY "{_TABLE}_insert" ON "{_TABLE}" FOR INSERT WITH CHECK ({scope})'
    )


def _install_postgresql_hardening() -> None:
    if _dialect() != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION akc_parallel_reject_invalidation_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'accepted-block invalidation evidence is append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        f'DROP TRIGGER IF EXISTS "trg_{_TABLE}_append_only" ON "{_TABLE}"'
    )
    op.execute(
        f"""
        CREATE TRIGGER "trg_{_TABLE}_append_only"
        BEFORE UPDATE OR DELETE ON "{_TABLE}"
        FOR EACH ROW
        EXECUTE FUNCTION akc_parallel_reject_invalidation_mutation()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION akc_parallel_guard_invalidation_refund()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.refund_ledger_id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                FROM credit_ledger AS ledger
                WHERE ledger.tenant_id = NEW.tenant_id
                  AND ledger.job_id = NEW.processing_job_id
                  AND ledger.id = NEW.refund_ledger_id
                  AND ledger.operation_key = NEW.refund_settlement_key
                  AND ledger.entry_type = 'refund'
                  AND ledger.credits = NEW.refund_amount
            ) THEN
                RAISE EXCEPTION
                    'accepted-block invalidation refund ledger binding is invalid'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f'DROP TRIGGER IF EXISTS "trg_{_TABLE}_refund_guard" ON "{_TABLE}"'
    )
    op.execute(
        f"""
        CREATE TRIGGER "trg_{_TABLE}_refund_guard"
        BEFORE INSERT ON "{_TABLE}"
        FOR EACH ROW
        EXECUTE FUNCTION akc_parallel_guard_invalidation_refund()
        """
    )


def _configure_role_grants() -> None:
    if _dialect() != "postgresql":
        return
    for role in (_DISPATCH_ROLE, _GPU_WORKER_ROLE):
        op.execute(f'REVOKE ALL PRIVILEGES ON TABLE "{_TABLE}" FROM {role}')
    op.execute(f'REVOKE ALL PRIVILEGES ON TABLE "{_TABLE}" FROM PUBLIC')
    op.execute(f'GRANT SELECT, INSERT ON TABLE "{_TABLE}" TO {_DISPATCH_ROLE}')


def _remove_postgresql_hardening() -> None:
    if _dialect() != "postgresql":
        return
    for role in (_DISPATCH_ROLE, _GPU_WORKER_ROLE):
        op.execute(f'REVOKE ALL PRIVILEGES ON TABLE "{_TABLE}" FROM {role}')
    op.execute("DROP FUNCTION IF EXISTS akc_parallel_guard_invalidation_refund() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS akc_parallel_reject_invalidation_mutation() CASCADE")


def upgrade() -> None:
    _suspend_scope_hardening()
    try:
        _add_scope_columns()
        _add_arbitration_contract()
        _add_accepted_block_generation()
    finally:
        _restore_scope_hardening()
    _create_invalidation_table()
    _allow_historical_accepted_attempts()
    _enable_rls()
    _install_postgresql_hardening()
    _configure_role_grants()


def _assert_downgrade_safe() -> None:
    if _TABLE in inspect(op.get_bind()).get_table_names():
        _assert_no_row(
            'SELECT 1 FROM "accepted_block_invalidations" LIMIT 1',
            "refusing to downgrade non-empty append-only invalidation evidence",
        )
    _assert_no_row(
        """
        SELECT 1 FROM accepted_blocks
        WHERE generation <> 1
        LIMIT 1
        """,
        "refusing to downgrade accepted-block generations beyond the legacy schema",
    )
    _assert_no_row(
        """
        SELECT 1
        FROM accepted_blocks
        GROUP BY document_id, logical_block_key
        HAVING count(*) > 1
        LIMIT 1
        """,
        "refusing to restore document-global accepted-block uniqueness with duplicate history",
    )
    _assert_no_row(
        """
        SELECT 1
        FROM parse_attempts
        WHERE state = 'ACCEPTED'
        GROUP BY shard_id
        HAVING count(*) > 1
        LIMIT 1
        """,
        "refusing to restore legacy single-accepted-attempt index with accepted history",
    )


def _drop_generation_scope() -> None:
    if "accepted_blocks_document_idx" in _indexes("accepted_blocks"):
        op.drop_index("accepted_blocks_document_idx", table_name="accepted_blocks")
    with _batch("accepted_blocks") as batch:
        for name in (
            "fk_accepted_blocks_arbitration",
            "fk_accepted_blocks_attempt_scope",
            "fk_accepted_blocks_shard_scope",
            "fk_accepted_blocks_processing_job_scope",
        ):
            batch.drop_constraint(name, type_="foreignkey")
        batch.drop_constraint("uq_accepted_blocks_arbitration", type_="unique")
        batch.drop_constraint("uq_accepted_blocks_invalidation_scope", type_="unique")
        batch.drop_constraint("uq_accepted_blocks_generation_key", type_="unique")
        batch.drop_constraint("ck_accepted_blocks_generation", type_="check")
        batch.create_unique_constraint(
            "uq_accepted_blocks_document_id_logical_block_key",
            ["document_id", "logical_block_key"],
        )
        batch.create_foreign_key(
            "fk_accepted_blocks_tenant_id_shard_id_parse_shards",
            "parse_shards",
            ["tenant_id", "shard_id"],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_accepted_blocks_tenant_id_attempt_id_parse_attempts",
            "parse_attempts",
            ["tenant_id", "attempt_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.drop_column("generation")
        batch.drop_column("document_version_id")
        batch.drop_column("processing_job_id")
        batch.drop_column("arbitration_id")
    op.create_index(
        "accepted_blocks_document_idx",
        "accepted_blocks",
        ["document_id", "final_state", "accepted_at"],
    )

    with _batch("recovery_tasks") as batch:
        batch.drop_constraint("uq_recovery_tasks_invalidation_scope", type_="unique")
    with _batch("parse_attempts") as batch:
        batch.drop_constraint("uq_parse_attempts_shard_scope", type_="unique")

    if "parse_shards_job_idx" in _indexes("parse_shards"):
        op.drop_index("parse_shards_job_idx", table_name="parse_shards")
    with _batch("parse_shards") as batch:
        batch.drop_constraint("uq_parse_shards_acceptance_scope", type_="unique")
        batch.drop_constraint("uq_parse_shards_generation_key", type_="unique")
        batch.create_unique_constraint(
            "uq_parse_shards_document_id_shard_key_plan_version",
            ["document_id", "shard_key", "plan_version"],
        )
        batch.alter_column(
            "processing_job_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )
        batch.drop_column("document_version_id")
    op.create_index(
        "parse_shards_job_idx",
        "parse_shards",
        ["tenant_id", "processing_job_id", "status"],
    )

    if (
        "tenant_id",
        "job_id",
        "id",
        "operation_key",
    ) in _unique_constraints("credit_ledger"):
        with _batch("credit_ledger") as batch:
            batch.drop_constraint("uq_credit_ledger_refund_binding", type_="unique")

    with _batch("arbitration_decisions") as batch:
        batch.drop_constraint("ck_arbitration_decisions_priced_credit", type_="check")
        batch.drop_constraint("ck_arbitration_decisions_logical_unit_sha", type_="check")
        batch.drop_column("priced_credit_amount")
        batch.drop_column("logical_unit_sha256")
        batch.drop_column("logical_unit_key")


def downgrade() -> None:
    _assert_downgrade_safe()
    _remove_postgresql_hardening()
    if _TABLE in inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
    _drop_generation_scope()
    _restore_legacy_single_accepted_attempt()
