"""Add v6 parallel-pod parsing, validation, recovery, and continuity ledgers.

Revision ID: 0031_parallel_pod_runtime
Revises: 0030_collection_integrity_action_execution
Create Date: 2026-08-01
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0031_parallel_pod_runtime"
down_revision = "0030_collection_integrity_action_execution"
branch_labels = None
depends_on = None

_TABLES = (
    "parse_shards",
    "parse_attempts",
    "attempt_validations",
    "worker_health",
    "semantic_health_events",
    "continuity_edges",
    "accepted_blocks",
    "recovery_tasks",
    "arbitration_decisions",
)

_APPEND_ONLY_TABLES = frozenset(
    {
        "attempt_validations",
        "semantic_health_events",
        "continuity_edges",
        "accepted_blocks",
        "arbitration_decisions",
    }
)
_DISPATCH_ROLE = "akc_dispatch_worker"
_GPU_WORKER_ROLE = "akc_gpu_worker"

_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "parse_shards": frozenset(
        {
            "id",
            "tenant_id",
            "collection_id",
            "document_id",
            "processing_job_id",
            "parent_shard_id",
            "shard_key",
            "shard_kind",
            "ordinal",
            "page_start",
            "page_end",
            "region",
            "context",
            "overlap",
            "ownership",
            "route_class",
            "priority",
            "size_units",
            "plan_version",
            "input_sha256",
            "status",
            "dispatch_idempotency_key",
            "created_at",
            "updated_at",
        }
    ),
    "parse_attempts": frozenset(
        {
            "id",
            "tenant_id",
            "shard_id",
            "parent_attempt_id",
            "provider_invocation_id",
            "attempt_number",
            "attempt_kind",
            "state",
            "pool_key",
            "worker_id",
            "model_id",
            "model_revision",
            "runtime_identity",
            "route_policy_version",
            "idempotency_key",
            "request_sha256",
            "output_artifact_key",
            "output_sha256",
            "output_summary",
            "failure_domain",
            "failure_code",
            "billing_disposition",
            "gpu_milliseconds",
            "cost_usd",
            "started_at",
            "output_received_at",
            "completed_at",
            "created_at",
        }
    ),
    "attempt_validations": frozenset(
        {
            "id",
            "tenant_id",
            "attempt_id",
            "level",
            "validator_key",
            "validator_revision",
            "status",
            "score",
            "hard_fail",
            "reason_codes",
            "findings",
            "evidence",
            "evidence_sha256",
            "created_at",
        }
    ),
    "worker_health": frozenset(
        {
            "id",
            "tenant_id",
            "worker_id",
            "pool_key",
            "model_id",
            "runtime_identity",
            "region",
            "state",
            "infrastructure_status",
            "semantic_status",
            "infrastructure_score",
            "semantic_score",
            "inflight",
            "capacity",
            "consecutive_semantic_failures",
            "metrics",
            "drain_reason",
            "last_heartbeat_at",
            "last_canary_at",
            "updated_at",
        }
    ),
    "semantic_health_events": frozenset(
        {
            "id",
            "tenant_id",
            "worker_health_id",
            "event_type",
            "previous_state",
            "current_state",
            "semantic_score",
            "reason_codes",
            "impacted_attempt_ids",
            "evidence",
            "evidence_sha256",
            "occurred_at",
        }
    ),
    "continuity_edges": frozenset(
        {
            "id",
            "tenant_id",
            "document_id",
            "source_shard_id",
            "target_shard_id",
            "edge_type",
            "confidence",
            "authority",
            "evidence",
            "evidence_sha256",
            "merge_revision",
            "status",
            "created_at",
        }
    ),
    "accepted_blocks": frozenset(
        {
            "id",
            "tenant_id",
            "document_id",
            "shard_id",
            "attempt_id",
            "logical_block_key",
            "final_state",
            "artifact_key",
            "artifact_sha256",
            "provenance",
            "acceptance_idempotency_key",
            "credit_settlement_key",
            "billable",
            "credit_amount",
            "accepted_at",
        }
    ),
    "recovery_tasks": frozenset(
        {
            "id",
            "tenant_id",
            "document_id",
            "shard_id",
            "source_attempt_id",
            "recovery_level",
            "reason_code",
            "target",
            "preprocessing_variants",
            "route_candidates",
            "state",
            "idempotency_key",
            "result_attempt_id",
            "created_at",
            "completed_at",
        }
    ),
    "arbitration_decisions": frozenset(
        {
            "id",
            "tenant_id",
            "document_id",
            "shard_id",
            "decision_key",
            "candidate_attempt_ids",
            "excluded_attempt_ids",
            "selected_attempt_id",
            "decision",
            "authority_tier",
            "reason_codes",
            "evidence",
            "evidence_sha256",
            "policy_version",
            "created_at",
        }
    ),
}

_REQUIRED_INDEXES: dict[str, frozenset[str]] = {
    "parse_shards": frozenset({"parse_shards_document_queue_idx", "parse_shards_job_idx"}),
    "parse_attempts": frozenset(
        {
            "parse_attempts_shard_state_idx",
            "parse_attempts_worker_idx",
        }
    ),
    "attempt_validations": frozenset({"attempt_validations_attempt_idx"}),
    "worker_health": frozenset({"worker_health_pool_idx"}),
    "semantic_health_events": frozenset({"semantic_health_events_worker_idx"}),
    "continuity_edges": frozenset({"continuity_edges_document_idx"}),
    "accepted_blocks": frozenset({"accepted_blocks_document_idx"}),
    "recovery_tasks": frozenset({"recovery_tasks_document_idx"}),
    "arbitration_decisions": frozenset({"arbitration_decisions_shard_idx"}),
}

_REQUIRED_CHECKS: dict[str, frozenset[str]] = {
    "parse_shards": frozenset(
        {
            "ck_parse_shards_kind",
            "ck_parse_shards_ordinal",
            "ck_parse_shards_page_range",
            "ck_parse_shards_priority",
            "ck_parse_shards_size_units",
            "ck_parse_shards_input_sha",
            "ck_parse_shards_status",
        }
    ),
    "parse_attempts": frozenset(
        {
            "ck_parse_attempts_number",
            "ck_parse_attempts_kind",
            "ck_parse_attempts_state",
            "ck_parse_attempts_failure_domain",
            "ck_parse_attempts_billing",
            "ck_parse_attempts_gpu_ms",
            "ck_parse_attempts_cost",
            "ck_parse_attempts_request_sha",
            "ck_parse_attempts_output_sha",
            "ck_parse_attempts_output_shape",
        }
    ),
    "attempt_validations": frozenset(
        {
            "ck_attempt_validations_level",
            "ck_attempt_validations_status",
            "ck_attempt_validations_score",
            "ck_attempt_validations_evidence_sha",
        }
    ),
    "worker_health": frozenset(
        {
            "ck_worker_health_state",
            "ck_worker_health_infra_status",
            "ck_worker_health_semantic_status",
            "ck_worker_health_infra_score",
            "ck_worker_health_semantic_score",
            "ck_worker_health_inflight",
            "ck_worker_health_capacity",
            "ck_worker_health_inflight_capacity",
            "ck_worker_health_semantic_failures",
        }
    ),
    "semantic_health_events": frozenset(
        {
            "ck_semantic_health_events_type",
            "ck_semantic_health_events_previous",
            "ck_semantic_health_events_current",
            "ck_semantic_health_events_score",
            "ck_semantic_health_events_evidence_sha",
        }
    ),
    "continuity_edges": frozenset(
        {
            "ck_continuity_edges_distinct",
            "ck_continuity_edges_type",
            "ck_continuity_edges_confidence",
            "ck_continuity_edges_authority",
            "ck_continuity_edges_status",
            "ck_continuity_edges_evidence_sha",
        }
    ),
    "accepted_blocks": frozenset(
        {
            "ck_accepted_blocks_state",
            "ck_accepted_blocks_artifact_sha",
            "ck_accepted_blocks_credit",
            "ck_accepted_blocks_billing_shape",
        }
    ),
    "recovery_tasks": frozenset(
        {
            "ck_recovery_tasks_level",
            "ck_recovery_tasks_state",
            "ck_recovery_tasks_terminal",
        }
    ),
    "arbitration_decisions": frozenset(
        {
            "ck_arbitration_decisions_decision",
            "ck_arbitration_decisions_authority",
            "ck_arbitration_decisions_selection",
            "ck_arbitration_decisions_evidence_sha",
        }
    ),
}

_REQUIRED_UNIQUES: dict[str, frozenset[frozenset[str]]] = {
    "parse_shards": frozenset(
        {
            frozenset({"tenant_id", "id"}),
            frozenset({"document_id", "shard_key", "plan_version"}),
            frozenset({"tenant_id", "dispatch_idempotency_key"}),
        }
    ),
    "parse_attempts": frozenset(
        {
            frozenset({"tenant_id", "id"}),
            frozenset({"shard_id", "attempt_number"}),
            frozenset({"tenant_id", "idempotency_key"}),
            frozenset({"provider_invocation_id"}),
        }
    ),
    "attempt_validations": frozenset(
        {
            frozenset({"tenant_id", "id"}),
            frozenset({"attempt_id", "level", "validator_key", "validator_revision"}),
        }
    ),
    "worker_health": frozenset(
        {
            frozenset({"tenant_id", "id"}),
            frozenset({"tenant_id", "worker_id"}),
        }
    ),
    "semantic_health_events": frozenset({frozenset({"tenant_id", "id"})}),
    "continuity_edges": frozenset(
        {
            frozenset({"tenant_id", "id"}),
            frozenset(
                {
                    "document_id",
                    "source_shard_id",
                    "target_shard_id",
                    "edge_type",
                    "merge_revision",
                }
            ),
        }
    ),
    "accepted_blocks": frozenset(
        {
            frozenset({"tenant_id", "id"}),
            frozenset({"document_id", "logical_block_key"}),
            frozenset({"attempt_id", "logical_block_key"}),
            frozenset({"tenant_id", "acceptance_idempotency_key"}),
            frozenset({"tenant_id", "credit_settlement_key"}),
        }
    ),
    "recovery_tasks": frozenset(
        {
            frozenset({"tenant_id", "id"}),
            frozenset({"tenant_id", "idempotency_key"}),
        }
    ),
    "arbitration_decisions": frozenset(
        {
            frozenset({"tenant_id", "id"}),
            frozenset({"tenant_id", "decision_key"}),
        }
    ),
}

_REQUIRED_FOREIGN_KEYS: dict[str, frozenset[tuple[tuple[str, ...], str]]] = {
    "parse_shards": frozenset(
        {
            (("tenant_id", "collection_id"), "collections"),
            (("tenant_id", "document_id"), "documents"),
            (("tenant_id", "processing_job_id"), "processing_jobs"),
            (("tenant_id", "parent_shard_id"), "parse_shards"),
        }
    ),
    "parse_attempts": frozenset(
        {
            (("tenant_id", "shard_id"), "parse_shards"),
            (("tenant_id", "parent_attempt_id"), "parse_attempts"),
            (("tenant_id", "provider_invocation_id"), "gpu_provider_invocations"),
        }
    ),
    "attempt_validations": frozenset({(("tenant_id", "attempt_id"), "parse_attempts")}),
    "worker_health": frozenset({(("tenant_id",), "tenants")}),
    "semantic_health_events": frozenset({(("tenant_id", "worker_health_id"), "worker_health")}),
    "continuity_edges": frozenset(
        {
            (("tenant_id", "document_id"), "documents"),
            (("tenant_id", "source_shard_id"), "parse_shards"),
            (("tenant_id", "target_shard_id"), "parse_shards"),
        }
    ),
    "accepted_blocks": frozenset(
        {
            (("tenant_id", "document_id"), "documents"),
            (("tenant_id", "shard_id"), "parse_shards"),
            (("tenant_id", "attempt_id"), "parse_attempts"),
        }
    ),
    "recovery_tasks": frozenset(
        {
            (("tenant_id", "document_id"), "documents"),
            (("tenant_id", "shard_id"), "parse_shards"),
            (("tenant_id", "source_attempt_id"), "parse_attempts"),
            (("tenant_id", "result_attempt_id"), "parse_attempts"),
        }
    ),
    "arbitration_decisions": frozenset(
        {
            (("tenant_id", "document_id"), "documents"),
            (("tenant_id", "shard_id"), "parse_shards"),
            (("tenant_id", "selected_attempt_id"), "parse_attempts"),
        }
    ),
}


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _existing_table_is_complete(table: str) -> bool:
    """Allow safe reruns only for a fully formed v6 table.

    Alembic normally executes a revision once, but test/bootstrap workflows may
    start from ORM-created metadata.  Silently returning merely because a table
    exists can bless a partially applied revision, so every structural contract
    that later code relies on is verified before the create step is skipped.
    """

    if table not in _tables():
        return False
    inspector = inspect(op.get_bind())
    actual_columns = frozenset(str(column["name"]) for column in inspector.get_columns(table))
    actual_indexes = frozenset(str(index["name"]) for index in inspector.get_indexes(table))
    actual_checks = frozenset(
        str(check["name"])
        for check in inspector.get_check_constraints(table)
        if check.get("name") is not None
    )
    actual_uniques = frozenset(
        frozenset(str(column) for column in unique["column_names"])
        for unique in inspector.get_unique_constraints(table)
    )
    actual_foreign_keys = frozenset(
        (
            tuple(str(column) for column in foreign_key["constrained_columns"]),
            str(foreign_key["referred_table"]),
        )
        for foreign_key in inspector.get_foreign_keys(table)
    )
    compatible_uniques = set(actual_uniques)
    compatible_foreign_keys = set(actual_foreign_keys)
    if table == "parse_shards" and frozenset(
        {
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "shard_key",
            "plan_version",
        }
    ) in actual_uniques:
        compatible_uniques.add(frozenset({"document_id", "shard_key", "plan_version"}))
    if table == "accepted_blocks":
        if frozenset(
            {
                "tenant_id",
                "document_id",
                "processing_job_id",
                "document_version_id",
                "logical_block_key",
                "generation",
            }
        ) in actual_uniques:
            compatible_uniques.add(frozenset({"document_id", "logical_block_key"}))
        if (
            (
                "tenant_id",
                "document_id",
                "processing_job_id",
                "document_version_id",
                "shard_id",
            ),
            "parse_shards",
        ) in actual_foreign_keys:
            compatible_foreign_keys.add((("tenant_id", "shard_id"), "parse_shards"))
        if (
            ("tenant_id", "shard_id", "attempt_id"),
            "parse_attempts",
        ) in actual_foreign_keys:
            compatible_foreign_keys.add((("tenant_id", "attempt_id"), "parse_attempts"))
    missing = {
        "columns": sorted(_REQUIRED_COLUMNS[table] - actual_columns),
        "indexes": sorted(_REQUIRED_INDEXES[table] - actual_indexes),
        "checks": sorted(_REQUIRED_CHECKS[table] - actual_checks),
        "unique_constraints": sorted(
            (sorted(columns) for columns in _REQUIRED_UNIQUES[table] - compatible_uniques),
            key=lambda columns: tuple(columns),
        ),
        "foreign_keys": sorted(
            _REQUIRED_FOREIGN_KEYS[table] - compatible_foreign_keys,
            key=lambda item: (item[1], item[0]),
        ),
    }
    incomplete = {key: value for key, value in missing.items() if value}
    if incomplete:
        raise RuntimeError(
            f"refusing to skip partial v6 table {table!r}; missing structural contract: "
            f"{incomplete}"
        )
    return True


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _tenant_id() -> sa.Column[Any]:
    return sa.Column("tenant_id", sa.Uuid(), nullable=False)


def _create_parse_shards() -> None:
    if _existing_table_is_complete("parse_shards"):
        return
    op.create_table(
        "parse_shards",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("collection_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("processing_job_id", sa.Uuid(), nullable=True),
        sa.Column("parent_shard_id", sa.Uuid(), nullable=True),
        sa.Column("shard_key", sa.String(length=160), nullable=False),
        sa.Column("shard_kind", sa.String(length=24), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("region", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("overlap", sa.JSON(), nullable=False),
        sa.Column("ownership", sa.JSON(), nullable=False),
        sa.Column("route_class", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("size_units", sa.Integer(), nullable=False),
        sa.Column("plan_version", sa.String(length=120), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("dispatch_idempotency_key", sa.String(length=160), nullable=False),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "collection_id"],
            ["collections.tenant_id", "collections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "processing_job_id"],
            ["processing_jobs.tenant_id", "processing_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("document_id", "shard_key", "plan_version"),
        sa.UniqueConstraint("tenant_id", "dispatch_idempotency_key"),
        sa.CheckConstraint(
            "shard_kind IN ("
            "'collection','document','section','page_group','page',"
            "'region','table','row','cell')",
            name="ck_parse_shards_kind",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_parse_shards_ordinal"),
        sa.CheckConstraint(
            "page_start >= 1 AND page_end >= page_start",
            name="ck_parse_shards_page_range",
        ),
        sa.CheckConstraint("priority BETWEEN 0 AND 100", name="ck_parse_shards_priority"),
        sa.CheckConstraint("size_units >= 1", name="ck_parse_shards_size_units"),
        sa.CheckConstraint("length(input_sha256) = 64", name="ck_parse_shards_input_sha"),
        sa.CheckConstraint(
            "status IN ("
            "'PLANNED','QUEUED','DISPATCHED','RUNNING','VALIDATING','ACCEPTED',"
            "'RECOVERY_PENDING','UNRESOLVED','QUARANTINED','FAILED','SUPERSEDED')",
            name="ck_parse_shards_status",
        ),
    )
    op.create_index(
        "parse_shards_document_queue_idx",
        "parse_shards",
        ["tenant_id", "document_id", "status", "priority", "ordinal"],
    )
    op.create_index(
        "parse_shards_job_idx",
        "parse_shards",
        ["tenant_id", "processing_job_id", "status"],
    )


def _create_parse_attempts() -> None:
    if _existing_table_is_complete("parse_attempts"):
        return
    op.create_table(
        "parse_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("shard_id", sa.Uuid(), nullable=False),
        sa.Column("parent_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("provider_invocation_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("attempt_kind", sa.String(length=24), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("pool_key", sa.String(length=120), nullable=False),
        sa.Column("worker_id", sa.String(length=160), nullable=True),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("model_revision", sa.String(length=160), nullable=False),
        sa.Column("runtime_identity", sa.String(length=160), nullable=False),
        sa.Column("route_policy_version", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("output_artifact_key", sa.String(length=500), nullable=True),
        sa.Column("output_sha256", sa.String(length=64), nullable=True),
        sa.Column("output_summary", sa.JSON(), nullable=False),
        sa.Column("failure_domain", sa.String(length=24), nullable=True),
        sa.Column("failure_code", sa.String(length=120), nullable=True),
        sa.Column("billing_disposition", sa.String(length=32), nullable=False),
        sa.Column("gpu_milliseconds", sa.BigInteger(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(18, 8), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "provider_invocation_id"],
            ["gpu_provider_invocations.tenant_id", "gpu_provider_invocations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("shard_id", "attempt_number"),
        sa.UniqueConstraint("tenant_id", "idempotency_key"),
        sa.UniqueConstraint("provider_invocation_id"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_parse_attempts_number"),
        sa.CheckConstraint(
            "attempt_kind IN ('primary','retry','hedge','straggler','recovery','shadow')",
            name="ck_parse_attempts_kind",
        ),
        sa.CheckConstraint(
            "state IN ("
            "'CREATED','QUEUED','RUNNING','OUTPUT_RECEIVED','VALIDATING','ACCEPTED',"
            "'REJECTED','RETRYABLE_FAILED','TERMINAL_FAILED','SUPERSEDED','QUARANTINED')",
            name="ck_parse_attempts_state",
        ),
        sa.CheckConstraint(
            "failure_domain IS NULL OR failure_domain IN ("
            "'infrastructure','semantic','policy','cancelled')",
            name="ck_parse_attempts_failure_domain",
        ),
        sa.CheckConstraint(
            "billing_disposition IN ("
            "'pending','accepted_billable','retry_unbillable','speculative_unbillable',"
            "'straggler_unbillable','unresolved_unbillable','quarantine_unbillable',"
            "'refunded','shadow_unbillable')",
            name="ck_parse_attempts_billing",
        ),
        sa.CheckConstraint("gpu_milliseconds >= 0", name="ck_parse_attempts_gpu_ms"),
        sa.CheckConstraint("cost_usd >= 0", name="ck_parse_attempts_cost"),
        sa.CheckConstraint("length(request_sha256) = 64", name="ck_parse_attempts_request_sha"),
        sa.CheckConstraint(
            "output_sha256 IS NULL OR length(output_sha256) = 64",
            name="ck_parse_attempts_output_sha",
        ),
        sa.CheckConstraint(
            "(output_artifact_key IS NULL AND output_sha256 IS NULL "
            "AND output_received_at IS NULL) OR "
            "(output_artifact_key IS NOT NULL AND output_sha256 IS NOT NULL "
            "AND output_received_at IS NOT NULL)",
            name="ck_parse_attempts_output_shape",
        ),
    )
    op.create_index(
        "parse_attempts_shard_state_idx",
        "parse_attempts",
        ["shard_id", "state", "attempt_number"],
    )
    op.create_index(
        "parse_attempts_worker_idx",
        "parse_attempts",
        ["tenant_id", "worker_id", "created_at"],
    )
    op.create_index(
        "parse_attempts_one_accepted_idx",
        "parse_attempts",
        ["shard_id"],
        unique=True,
        postgresql_where=sa.text("state = 'ACCEPTED'"),
        sqlite_where=sa.text("state = 'ACCEPTED'"),
    )


def _create_attempt_validations() -> None:
    if _existing_table_is_complete("attempt_validations"):
        return
    op.create_table(
        "attempt_validations",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("validator_key", sa.String(length=120), nullable=False),
        sa.Column("validator_revision", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("score", sa.Numeric(9, 8), nullable=True),
        sa.Column("hard_fail", sa.Boolean(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("attempt_id", "level", "validator_key", "validator_revision"),
        sa.CheckConstraint("level BETWEEN 0 AND 6", name="ck_attempt_validations_level"),
        sa.CheckConstraint(
            "status IN ('passed','failed','abstained','unavailable')",
            name="ck_attempt_validations_status",
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_attempt_validations_score",
        ),
        sa.CheckConstraint(
            "length(evidence_sha256) = 64", name="ck_attempt_validations_evidence_sha"
        ),
    )
    op.create_index(
        "attempt_validations_attempt_idx",
        "attempt_validations",
        ["attempt_id", "level", "status"],
    )


def _create_worker_health() -> None:
    if _existing_table_is_complete("worker_health"):
        return
    op.create_table(
        "worker_health",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("worker_id", sa.String(length=160), nullable=False),
        sa.Column("pool_key", sa.String(length=120), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("runtime_identity", sa.String(length=160), nullable=False),
        sa.Column("region", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("infrastructure_status", sa.String(length=24), nullable=False),
        sa.Column("semantic_status", sa.String(length=24), nullable=False),
        sa.Column("infrastructure_score", sa.Numeric(9, 8), nullable=False),
        sa.Column("semantic_score", sa.Numeric(9, 8), nullable=False),
        sa.Column("inflight", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("consecutive_semantic_failures", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("drain_reason", sa.String(length=120), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_canary_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "worker_id"),
        sa.CheckConstraint(
            "state IN ('HEALTHY','DEGRADED','DRAINING','QUARANTINED','TERMINATED')",
            name="ck_worker_health_state",
        ),
        sa.CheckConstraint(
            "infrastructure_status IN ('healthy','degraded','unreachable','terminated')",
            name="ck_worker_health_infra_status",
        ),
        sa.CheckConstraint(
            "semantic_status IN ('healthy','degraded','failing','unknown')",
            name="ck_worker_health_semantic_status",
        ),
        sa.CheckConstraint(
            "infrastructure_score >= 0 AND infrastructure_score <= 1",
            name="ck_worker_health_infra_score",
        ),
        sa.CheckConstraint(
            "semantic_score >= 0 AND semantic_score <= 1",
            name="ck_worker_health_semantic_score",
        ),
        sa.CheckConstraint("inflight >= 0", name="ck_worker_health_inflight"),
        sa.CheckConstraint("capacity >= 1", name="ck_worker_health_capacity"),
        sa.CheckConstraint(
            "inflight <= capacity",
            name="ck_worker_health_inflight_capacity",
        ),
        sa.CheckConstraint(
            "consecutive_semantic_failures >= 0",
            name="ck_worker_health_semantic_failures",
        ),
    )
    op.create_index(
        "worker_health_pool_idx",
        "worker_health",
        ["tenant_id", "pool_key", "state", "inflight"],
    )


def _create_semantic_health_events() -> None:
    if _existing_table_is_complete("semantic_health_events"):
        return
    op.create_table(
        "semantic_health_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("worker_health_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("previous_state", sa.String(length=24), nullable=False),
        sa.Column("current_state", sa.String(length=24), nullable=False),
        sa.Column("semantic_score", sa.Numeric(9, 8), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("impacted_attempt_ids", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "worker_health_id"],
            ["worker_health.tenant_id", "worker_health.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.CheckConstraint(
            "event_type IN ("
            "'canary_passed','canary_failed','degraded','draining',"
            "'quarantined','recovered','impact_replay_requested')",
            name="ck_semantic_health_events_type",
        ),
        sa.CheckConstraint(
            "previous_state IN ('HEALTHY','DEGRADED','DRAINING','QUARANTINED','TERMINATED')",
            name="ck_semantic_health_events_previous",
        ),
        sa.CheckConstraint(
            "current_state IN ('HEALTHY','DEGRADED','DRAINING','QUARANTINED','TERMINATED')",
            name="ck_semantic_health_events_current",
        ),
        sa.CheckConstraint(
            "semantic_score >= 0 AND semantic_score <= 1",
            name="ck_semantic_health_events_score",
        ),
        sa.CheckConstraint(
            "length(evidence_sha256) = 64", name="ck_semantic_health_events_evidence_sha"
        ),
    )
    op.create_index(
        "semantic_health_events_worker_idx",
        "semantic_health_events",
        ["worker_health_id", "occurred_at"],
    )


def _create_continuity_edges() -> None:
    if _existing_table_is_complete("continuity_edges"):
        return
    op.create_table(
        "continuity_edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("source_shard_id", sa.Uuid(), nullable=False),
        sa.Column("target_shard_id", sa.Uuid(), nullable=False),
        sa.Column("edge_type", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Numeric(9, 8), nullable=False),
        sa.Column("authority", sa.String(length=24), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("merge_revision", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint(
            "document_id",
            "source_shard_id",
            "target_shard_id",
            "edge_type",
            "merge_revision",
        ),
        sa.CheckConstraint(
            "source_shard_id <> target_shard_id",
            name="ck_continuity_edges_distinct",
        ),
        sa.CheckConstraint(
            "edge_type IN ("
            "'heading_continuation','paragraph_continuation','list_continuation',"
            "'table_continuation','figure_caption','footnote_reference',"
            "'reading_order','overlap_equivalence')",
            name="ck_continuity_edges_type",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_continuity_edges_confidence"
        ),
        sa.CheckConstraint(
            "authority IN ('deterministic','native','authority','cross_model','multimodal')",
            name="ck_continuity_edges_authority",
        ),
        sa.CheckConstraint(
            "status IN ('candidate','accepted','rejected','unresolved')",
            name="ck_continuity_edges_status",
        ),
        sa.CheckConstraint("length(evidence_sha256) = 64", name="ck_continuity_edges_evidence_sha"),
    )
    op.create_index(
        "continuity_edges_document_idx",
        "continuity_edges",
        ["document_id", "status", "edge_type"],
    )


def _create_accepted_blocks() -> None:
    if _existing_table_is_complete("accepted_blocks"):
        return
    op.create_table(
        "accepted_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("shard_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("logical_block_key", sa.String(length=200), nullable=False),
        sa.Column("final_state", sa.String(length=32), nullable=False),
        sa.Column("artifact_key", sa.String(length=500), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("acceptance_idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("credit_settlement_key", sa.String(length=160), nullable=True),
        sa.Column("billable", sa.Boolean(), nullable=False),
        sa.Column("credit_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("document_id", "logical_block_key"),
        sa.UniqueConstraint("attempt_id", "logical_block_key"),
        sa.UniqueConstraint("tenant_id", "acceptance_idempotency_key"),
        sa.UniqueConstraint("tenant_id", "credit_settlement_key"),
        sa.CheckConstraint(
            "final_state IN ("
            "'verified','authority_verified','cross_model_verified','auto_repaired',"
            "'unresolved','quarantined','failed')",
            name="ck_accepted_blocks_state",
        ),
        sa.CheckConstraint("length(artifact_sha256) = 64", name="ck_accepted_blocks_artifact_sha"),
        sa.CheckConstraint("credit_amount >= 0", name="ck_accepted_blocks_credit"),
        sa.CheckConstraint(
            "(billable AND final_state IN ("
            "'verified','authority_verified','cross_model_verified','auto_repaired') "
            "AND credit_settlement_key IS NOT NULL AND credit_amount > 0) OR "
            "(NOT billable AND credit_settlement_key IS NULL AND credit_amount = 0)",
            name="ck_accepted_blocks_billing_shape",
        ),
    )
    op.create_index(
        "accepted_blocks_document_idx",
        "accepted_blocks",
        ["document_id", "final_state", "accepted_at"],
    )


def _create_recovery_tasks() -> None:
    if _existing_table_is_complete("recovery_tasks"):
        return
    op.create_table(
        "recovery_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("shard_id", sa.Uuid(), nullable=False),
        sa.Column("source_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("recovery_level", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=120), nullable=False),
        sa.Column("target", sa.JSON(), nullable=False),
        sa.Column("preprocessing_variants", sa.JSON(), nullable=False),
        sa.Column("route_candidates", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("result_attempt_id", sa.Uuid(), nullable=True),
        _created_at(),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "result_attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key"),
        sa.CheckConstraint(
            "recovery_level IN ('cell','row','table','region','page','page_group')",
            name="ck_recovery_tasks_level",
        ),
        sa.CheckConstraint(
            "state IN ("
            "'REQUESTED','QUEUED','RUNNING','VALIDATING','COMPLETED',"
            "'UNRESOLVED','FAILED','CANCELLED')",
            name="ck_recovery_tasks_state",
        ),
        sa.CheckConstraint(
            "(state = 'COMPLETED' AND result_attempt_id IS NOT NULL "
            "AND completed_at IS NOT NULL) OR "
            "(state IN ('UNRESOLVED','FAILED','CANCELLED') AND completed_at IS NOT NULL) OR "
            "(state IN ('REQUESTED','QUEUED','RUNNING','VALIDATING') "
            "AND result_attempt_id IS NULL AND completed_at IS NULL)",
            name="ck_recovery_tasks_terminal",
        ),
    )
    op.create_index(
        "recovery_tasks_document_idx",
        "recovery_tasks",
        ["document_id", "state", "created_at"],
    )


def _create_arbitration_decisions() -> None:
    if _existing_table_is_complete("arbitration_decisions"):
        return
    op.create_table(
        "arbitration_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_id(),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("shard_id", sa.Uuid(), nullable=False),
        sa.Column("decision_key", sa.String(length=160), nullable=False),
        sa.Column("candidate_attempt_ids", sa.JSON(), nullable=False),
        sa.Column("excluded_attempt_ids", sa.JSON(), nullable=False),
        sa.Column("selected_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("authority_tier", sa.String(length=32), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "selected_attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "decision_key"),
        sa.CheckConstraint(
            "decision IN ('selected','unresolved','recovery_required','quarantined')",
            name="ck_arbitration_decisions_decision",
        ),
        sa.CheckConstraint(
            "authority_tier IN ("
            "'exact_authority','native','pixel_ocr','independent_agreement','none')",
            name="ck_arbitration_decisions_authority",
        ),
        sa.CheckConstraint(
            "(decision = 'selected' AND selected_attempt_id IS NOT NULL "
            "AND authority_tier <> 'none') OR "
            "(decision <> 'selected' AND selected_attempt_id IS NULL)",
            name="ck_arbitration_decisions_selection",
        ),
        sa.CheckConstraint(
            "length(evidence_sha256) = 64", name="ck_arbitration_decisions_evidence_sha"
        ),
    )
    op.create_index(
        "arbitration_decisions_shard_idx",
        "arbitration_decisions",
        ["shard_id", "created_at"],
    )


def _enable_rls(table: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    scope = f'"{table}".tenant_id = {tenant}'
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    for operation in ("select", "insert", "update", "delete"):
        op.execute(f'DROP POLICY IF EXISTS "{table}_{operation}" ON "{table}"')
    op.execute(f'CREATE POLICY "{table}_select" ON "{table}" FOR SELECT USING ({scope})')
    op.execute(f'CREATE POLICY "{table}_insert" ON "{table}" FOR INSERT WITH CHECK ({scope})')
    if table not in _APPEND_ONLY_TABLES:
        op.execute(
            f'CREATE POLICY "{table}_update" ON "{table}" FOR UPDATE USING ({scope}) '
            f"WITH CHECK ({scope})"
        )


def _install_postgresql_immutability() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION akc_parallel_reject_evidence_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'v6 evidence table % is append-only', TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table in sorted(_APPEND_ONLY_TABLES):
        op.execute(f'DROP TRIGGER IF EXISTS "trg_{table}_append_only" ON "{table}"')
        op.execute(
            f"""
            CREATE TRIGGER "trg_{table}_append_only"
            BEFORE UPDATE OR DELETE ON "{table}"
            FOR EACH ROW
            EXECUTE FUNCTION akc_parallel_reject_evidence_mutation()
            """
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION akc_parallel_guard_parse_attempt()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.state IN (
                    'ACCEPTED', 'REJECTED', 'RETRYABLE_FAILED', 'TERMINAL_FAILED',
                    'SUPERSEDED', 'QUARANTINED'
                ) OR OLD.output_received_at IS NOT NULL THEN
                    RAISE EXCEPTION
                        'terminal or output-bearing v6 parse attempt % is immutable',
                        OLD.id
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.state IN (
                'ACCEPTED', 'REJECTED', 'RETRYABLE_FAILED', 'TERMINAL_FAILED',
                'SUPERSEDED', 'QUARANTINED'
            ) THEN
                RAISE EXCEPTION 'terminal v6 parse attempt % is immutable', OLD.id
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.output_received_at IS NOT NULL AND (
                OLD.output_artifact_key IS DISTINCT FROM NEW.output_artifact_key
                OR OLD.output_sha256 IS DISTINCT FROM NEW.output_sha256
                OR OLD.output_summary::text IS DISTINCT FROM NEW.output_summary::text
                OR OLD.gpu_milliseconds IS DISTINCT FROM NEW.gpu_milliseconds
                OR OLD.cost_usd IS DISTINCT FROM NEW.cost_usd
                OR OLD.output_received_at IS DISTINCT FROM NEW.output_received_at
            ) THEN
                RAISE EXCEPTION 'provider output for v6 parse attempt % is immutable', OLD.id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute('DROP TRIGGER IF EXISTS "trg_parse_attempts_immutable" ON "parse_attempts"')
    op.execute(
        """
        CREATE TRIGGER "trg_parse_attempts_immutable"
        BEFORE UPDATE OR DELETE ON "parse_attempts"
        FOR EACH ROW
        EXECUTE FUNCTION akc_parallel_guard_parse_attempt()
        """
    )


def _configure_role_grants() -> None:
    """Grant only the mutations owned by dispatch and provider workers."""

    if op.get_bind().dialect.name != "postgresql":
        return
    tables = ", ".join(f'"{table}"' for table in _TABLES)
    for role in (_DISPATCH_ROLE, _GPU_WORKER_ROLE):
        for table in _TABLES:
            op.execute(f'REVOKE ALL PRIVILEGES ON TABLE "{table}" FROM {role}')
    for table in _TABLES:
        op.execute(f'REVOKE ALL PRIVILEGES ON TABLE "{table}" FROM PUBLIC')

    op.execute(f"GRANT SELECT ON TABLE {tables} TO {_DISPATCH_ROLE}")
    op.execute(f"GRANT INSERT ON TABLE {tables} TO {_DISPATCH_ROLE}")
    op.execute(
        f"""
        GRANT UPDATE (status, priority, updated_at)
        ON TABLE parse_shards TO {_DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            state, worker_id, output_artifact_key, output_sha256, output_summary,
            failure_domain, failure_code, billing_disposition, gpu_milliseconds,
            cost_usd, started_at, output_received_at, completed_at
        ) ON TABLE parse_attempts TO {_DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            region, state, infrastructure_status, semantic_status,
            infrastructure_score, semantic_score, inflight, capacity,
            consecutive_semantic_failures, metrics, drain_reason,
            last_heartbeat_at, last_canary_at, updated_at
        ) ON TABLE worker_health TO {_DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (state, result_attempt_id, completed_at)
        ON TABLE recovery_tasks TO {_DISPATCH_ROLE}
        """
    )

    op.execute(
        f"""
        GRANT SELECT ON TABLE
            parse_shards, parse_attempts, attempt_validations,
            worker_health, semantic_health_events, recovery_tasks
        TO {_GPU_WORKER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT INSERT ON TABLE
            attempt_validations, worker_health, semantic_health_events
        TO {_GPU_WORKER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            state, worker_id, output_artifact_key, output_sha256, output_summary,
            failure_domain, failure_code, gpu_milliseconds, cost_usd,
            started_at, output_received_at, completed_at
        ) ON TABLE parse_attempts TO {_GPU_WORKER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            region, state, infrastructure_status, semantic_status,
            infrastructure_score, semantic_score, inflight, capacity,
            consecutive_semantic_failures, metrics, drain_reason,
            last_heartbeat_at, last_canary_at, updated_at
        ) ON TABLE worker_health TO {_GPU_WORKER_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (state, result_attempt_id, completed_at)
        ON TABLE recovery_tasks TO {_GPU_WORKER_ROLE}
        """
    )


def _remove_postgresql_hardening() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for role in (_DISPATCH_ROLE, _GPU_WORKER_ROLE):
        for table in _TABLES:
            op.execute(f'REVOKE ALL PRIVILEGES ON TABLE "{table}" FROM {role}')
    op.execute("DROP FUNCTION IF EXISTS akc_parallel_guard_parse_attempt() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS akc_parallel_reject_evidence_mutation() CASCADE")


def upgrade() -> None:
    _create_parse_shards()
    _create_parse_attempts()
    _create_attempt_validations()
    _create_worker_health()
    _create_semantic_health_events()
    _create_continuity_edges()
    _create_accepted_blocks()
    _create_recovery_tasks()
    _create_arbitration_decisions()
    for table in _TABLES:
        _enable_rls(table)
    _install_postgresql_immutability()
    _configure_role_grants()


def downgrade() -> None:
    _remove_postgresql_hardening()
    existing = _tables()
    for table in reversed(_TABLES):
        if table in existing:
            op.drop_table(table)
